"""
RAG Agent for maritime knowledge retrieval.

This module implements the RAG (Retrieval-Augmented Generation) agent
that queries the Knowledge Graph and generates responses with citations.
Now uses Hybrid Search (Dense + Sparse) for improved retrieval.

**Feature: maritime-ai-tutor, hybrid-search**
**Validates: Requirements 4.1, 4.2, 4.4, 8.3**
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.models.knowledge_graph import (
    Citation,
    GraphContext,
    KnowledgeNode,
    RelationType,
)
from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
from app.engine.rrf_reranker import HybridSearchResult

# Lazy import to avoid circular dependency with app.services
# HybridSearchService is imported in __init__ method

logger = logging.getLogger(__name__)


# Cached repository instance
_knowledge_repo = None


def get_knowledge_repository():
    """Get the Neo4j knowledge repository (cached)."""
    global _knowledge_repo
    
    if _knowledge_repo is not None:
        return _knowledge_repo
    
    _knowledge_repo = Neo4jKnowledgeRepository()
    if _knowledge_repo.is_available():
        logger.info("Using Neo4j knowledge repository")
    else:
        logger.warning("Neo4j unavailable - RAG queries will return empty results")
    
    return _knowledge_repo


@dataclass
class RAGResponse:
    """
    Response from RAG Agent with citations.
    
    **Validates: Requirements 4.1**
    """
    content: str
    citations: List[Citation]
    is_fallback: bool = False
    disclaimer: Optional[str] = None
    
    def has_citations(self) -> bool:
        """Check if response has citations."""
        return len(self.citations) > 0


class RAGAgent:
    """
    RAG Agent for maritime knowledge retrieval.
    
    Combines Knowledge Graph queries with LLM generation
    to provide accurate, cited responses.
    
    **Validates: Requirements 4.1, 4.2, 8.3**
    """
    
    # Relation types to traverse for context
    CONTEXT_RELATIONS = [
        RelationType.REGULATES,
        RelationType.APPLIES_TO,
        RelationType.RELATED_TO,
        RelationType.REFERENCES,
    ]
    
    # Fallback disclaimer when KG unavailable
    FALLBACK_DISCLAIMER = (
        "Note: This response is based on general knowledge. "
        "For authoritative information, please consult official maritime regulations."
    )
    
    def __init__(
        self,
        knowledge_graph=None,
        hybrid_search_service=None
    ):
        """
        Initialize RAG Agent.
        
        Args:
            knowledge_graph: Knowledge graph repository instance
            hybrid_search_service: Hybrid search service for Dense+Sparse search
        """
        self._kg = knowledge_graph or get_knowledge_repository()
        
        # Lazy import to avoid circular dependency
        if hybrid_search_service is None:
            from app.services.hybrid_search_service import get_hybrid_search_service
            self._hybrid_search = get_hybrid_search_service()
        else:
            self._hybrid_search = hybrid_search_service
            
        self._llm = self._init_llm()
    
    def _init_llm(self):
        """
        Initialize LLM for response synthesis.
        
        Supports Google Gemini (primary) and OpenAI/OpenRouter (fallback).
        """
        provider = getattr(settings, 'llm_provider', 'google')
        
        # Try Google Gemini first
        if provider == "google" or (not settings.openai_api_key and settings.google_api_key):
            if settings.google_api_key:
                try:
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    logger.info(f"RAG using Google Gemini: {settings.google_model}")
                    return ChatGoogleGenerativeAI(
                        google_api_key=settings.google_api_key,
                        model=settings.google_model,
                        temperature=0.3,  # Lower for factual responses
                        convert_system_message_to_human=True,
                    )
                except ImportError:
                    logger.warning("langchain-google-genai not installed")
                except Exception as e:
                    logger.error(f"Failed to initialize Gemini for RAG: {e}")
        
        # Fallback to OpenAI/OpenRouter
        if not settings.openai_api_key:
            logger.warning("No LLM API key, RAG will return raw content")
            return None
        
        try:
            llm_kwargs = {
                "api_key": settings.openai_api_key,
                "model": settings.openai_model,
                "temperature": 0.3,  # Lower for factual responses
            }
            if settings.openai_base_url:
                llm_kwargs["base_url"] = settings.openai_base_url
                logger.info(f"RAG using OpenRouter: {settings.openai_model}")
            else:
                logger.info(f"RAG using OpenAI: {settings.openai_model}")
            
            return ChatOpenAI(**llm_kwargs)
        except Exception as e:
            logger.error(f"Failed to initialize LLM for RAG: {e}")
            return None
    
    async def query(
        self, 
        question: str,
        limit: int = 5,
        conversation_history: str = "",
        user_role: str = "student"
    ) -> RAGResponse:
        """
        Query the knowledge graph and generate response.
        
        Uses Hybrid Search (Dense + Sparse) for improved retrieval.
        
        Args:
            question: User's question
            limit: Maximum number of sources to retrieve
            conversation_history: Formatted conversation history for context
            user_role: User role for role-based prompting (student/teacher/admin)
            
        Returns:
            RAGResponse with content and citations
            
        **Validates: Requirements 4.1, 8.3**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        **Feature: hybrid-search**
        """
        # Check if search is available
        if not self._hybrid_search.is_available() and not self._kg.is_available():
            return self._create_fallback_response(question)
        
        # Perform hybrid search (Dense + Sparse with RRF)
        hybrid_results = await self._hybrid_search.search(question, limit=limit)
        
        if not hybrid_results:
            # Fallback to legacy Neo4j search
            logger.info("Hybrid search returned no results, falling back to legacy search")
            nodes = await self._kg.hybrid_search(question, limit=limit)
            if not nodes:
                return self._create_no_results_response(question)
            expanded_nodes = await self._expand_context(nodes)
            citations = await self._kg.get_citations(nodes)
            content = self._generate_response(question, expanded_nodes, conversation_history, user_role)
            return RAGResponse(content=content, citations=citations, is_fallback=False)
        
        # Convert hybrid results to KnowledgeNodes for compatibility
        nodes = self._hybrid_results_to_nodes(hybrid_results)
        
        # Expand context with related nodes
        expanded_nodes = await self._expand_context(nodes)
        
        # Generate citations with relevance scores
        citations = self._generate_hybrid_citations(hybrid_results)
        
        # Generate response content with conversation history and role-based prompting
        content = self._generate_response(question, expanded_nodes, conversation_history, user_role)
        
        # Add search method info to response
        search_method = hybrid_results[0].search_method if hybrid_results else "hybrid"
        if search_method != "hybrid":
            content += f"\n\n*[Tìm kiếm: {search_method}]*"
        
        return RAGResponse(
            content=content,
            citations=citations,
            is_fallback=False
        )
    
    def _hybrid_results_to_nodes(self, results: List[HybridSearchResult]) -> List[KnowledgeNode]:
        """Convert HybridSearchResult to KnowledgeNode for compatibility."""
        from app.models.knowledge_graph import NodeType
        
        nodes = []
        for r in results:
            # Skip results with empty title or content
            title = r.title or ""
            content = r.content or ""
            
            if not title.strip() or not content.strip():
                logger.warning(f"Skipping result with empty title/content: {r.node_id}")
                continue
            
            nodes.append(KnowledgeNode(
                id=r.node_id,
                node_type=NodeType.CONCEPT,
                title=title,
                content=content,
                source=r.source or "Maritime Knowledge Base",
                metadata={
                    "category": r.category,
                    "rrf_score": r.rrf_score,
                    "dense_score": r.dense_score,
                    "sparse_score": r.sparse_score,
                    "search_method": r.search_method
                }
            ))
        return nodes
    
    def _generate_hybrid_citations(self, results: List[HybridSearchResult]) -> List[Citation]:
        """Generate citations from hybrid search results with relevance scores."""
        citations = []
        for r in results:
            citations.append(Citation(
                node_id=r.node_id,
                source=r.source or "Maritime Knowledge Base",
                title=r.title,
                relevance_score=r.rrf_score
            ))
        return citations

    
    async def _expand_context(
        self, 
        nodes: List[KnowledgeNode]
    ) -> List[KnowledgeNode]:
        """
        Expand context by traversing relations.
        
        **Validates: Requirements 4.4**
        """
        expanded = list(nodes)
        seen_ids = {n.id for n in nodes}
        
        for node in nodes:
            related = await self._kg.traverse_relations(
                node.id,
                self.CONTEXT_RELATIONS,
                depth=1
            )
            for related_node in related:
                if related_node.id not in seen_ids:
                    expanded.append(related_node)
                    seen_ids.add(related_node.id)
        
        return expanded
    
    def _generate_response(
        self, 
        question: str, 
        nodes: List[KnowledgeNode],
        conversation_history: str = "",
        user_role: str = "student"
    ) -> str:
        """
        Generate response using LLM to synthesize retrieved knowledge.
        
        Uses RAG pattern: Retrieve -> Augment -> Generate
        Includes conversation history for context continuity.
        
        Role-Based Prompting (CHỈ THỊ KỸ THUẬT SỐ 03):
        - student: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
        - teacher/admin: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
        
        **Feature: maritime-ai-tutor, Week 2: Memory Lite**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03**
        """
        if not nodes:
            return "I couldn't find specific information about that topic."
        
        # Build context from retrieved nodes
        context_parts = []
        sources = []
        
        for node in nodes[:3]:  # Top 3 most relevant
            context_parts.append(f"### {node.title}\n{node.content}")
            if node.source:
                sources.append(f"- {node.title} ({node.source})")
        
        context = "\n\n".join(context_parts)
        
        # If no LLM, return formatted raw content
        if not self._llm:
            logger.info("No LLM available, returning raw content")
            response = context
            if sources:
                response += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
            return response
        
        # Role-Based System Prompt (CHỈ THỊ KỸ THUẬT SỐ 03)
        if user_role == "student":
            # Gia sư (Tutor) - khuyến khích, giải thích cặn kẽ
            system_prompt = """Bạn là GIA SƯ HÀNG HẢI thân thiện, đang hướng dẫn sinh viên.

VAI TRÒ: Gia sư (Tutor) cho sinh viên
GIỌNG VĂN: Khuyến khích, động viên, kiên nhẫn

QUY TẮC:
1. Giải thích CẶN KẼ các thuật ngữ chuyên môn (ví dụ: "starboard" = mạn phải).
2. Dùng ví dụ thực tế để minh họa.
3. Khuyến khích sinh viên: "Bạn hỏi rất hay!", "Đây là kiến thức quan trọng!".
4. Nếu User hỏi nối tiếp, nhìn vào "LỊCH SỬ HỘI THOẠI" để hiểu ngữ cảnh.
5. Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt.
6. Trích dẫn nguồn khi đề cập đến quy định cụ thể.
7. Kết thúc bằng câu hỏi gợi mở hoặc lời động viên."""
        else:
            # Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
            system_prompt = """Bạn là TRỢ LÝ HÀNG HẢI chuyên nghiệp, hỗ trợ giáo viên/quản trị viên.

VAI TRÒ: Trợ lý (Assistant) cho giáo viên/admin
GIỌNG VĂN: Chuyên nghiệp, ngắn gọn, chính xác

QUY TẮC:
1. Trả lời NGẮN GỌN, đi thẳng vào vấn đề.
2. Trích dẫn CHÍNH XÁC điều luật, số hiệu quy định.
3. Không cần giải thích thuật ngữ cơ bản.
4. Nếu User hỏi nối tiếp, nhìn vào "LỊCH SỬ HỘI THOẠI" để hiểu ngữ cảnh.
5. Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt.
6. Ưu tiên độ chính xác hơn độ dài.
7. Có thể đề xuất tài liệu tham khảo thêm."""

        # Build user prompt with history
        history_section = ""
        if conversation_history:
            history_section = f"""
---
LỊCH SỬ HỘI THOẠI (Gần nhất):
{conversation_history}
---
"""

        user_prompt = f"""{history_section}
KIẾN THỨC TRA CỨU ĐƯỢC (RAG):
{context}
---

CÂU HỎI HIỆN TẠI:
{question}

Hãy trả lời câu hỏi dựa trên thông tin trên."""

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = self._llm.invoke(messages)
            answer = response.content
            
            # Add sources
            if sources:
                answer += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
            
            return answer
            
        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}")
            # Fallback to raw content
            response = context
            if sources:
                response += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
            return response
    
    def _create_fallback_response(self, question: str) -> RAGResponse:
        """
        Create fallback response when KG is unavailable.
        
        **Validates: Requirements 8.3**
        """
        logger.warning("Knowledge Graph unavailable, using fallback response")
        
        content = (
            f"I understand you're asking about: {question}\n\n"
            "While I can provide general guidance on maritime topics, "
            "I'm currently unable to access the detailed knowledge base. "
            "Please try again later for more specific information with citations."
        )
        
        return RAGResponse(
            content=content,
            citations=[],
            is_fallback=True,
            disclaimer=self.FALLBACK_DISCLAIMER
        )
    
    def _create_no_results_response(self, question: str) -> RAGResponse:
        """Create response when no results found."""
        content = (
            f"I searched for information about: {question}\n\n"
            "Unfortunately, I couldn't find specific information in the knowledge base. "
            "You might want to:\n"
            "- Rephrase your question\n"
            "- Ask about a more specific topic\n"
            "- Consult official maritime documentation directly"
        )
        
        return RAGResponse(
            content=content,
            citations=[],
            is_fallback=False
        )
    
    def is_available(self) -> bool:
        """Check if RAG Agent is available."""
        return self._kg.is_available()


class MaritimeDocumentParser:
    """
    Parser for maritime regulation documents.
    
    Extracts structured data from SOLAS, COLREGs, etc.
    
    **Validates: Requirements 4.5, 4.6**
    """
    
    @staticmethod
    def parse_regulation(
        code: str,
        title: str,
        content: str,
        source: str = ""
    ) -> KnowledgeNode:
        """
        Parse a regulation into a KnowledgeNode.
        
        Args:
            code: Regulation code (e.g., "SOLAS II-2/10")
            title: Regulation title
            content: Full regulation text
            source: Source document
            
        Returns:
            KnowledgeNode representing the regulation
            
        **Validates: Requirements 4.5**
        """
        from app.models.knowledge_graph import NodeType
        
        return KnowledgeNode(
            id=f"reg_{code.lower().replace('/', '_').replace('-', '_')}",
            node_type=NodeType.REGULATION,
            title=title,
            content=content,
            source=source,
            metadata={"code": code}
        )
    
    @staticmethod
    def serialize_to_document(node: KnowledgeNode) -> str:
        """
        Serialize a KnowledgeNode back to document format.
        
        Args:
            node: The node to serialize
            
        Returns:
            Document string representation
            
        **Validates: Requirements 4.6**
        """
        parts = []
        
        # Add code if available
        code = node.metadata.get("code", "")
        if code:
            parts.append(f"Code: {code}")
        
        parts.append(f"Title: {node.title}")
        parts.append(f"Content: {node.content}")
        
        if node.source:
            parts.append(f"Source: {node.source}")
        
        return "\n".join(parts)
