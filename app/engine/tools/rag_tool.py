"""
RAG Agent for maritime knowledge retrieval.

This module implements the RAG (Retrieval-Augmented Generation) agent
that queries the Knowledge Graph and generates responses with citations.

**Feature: maritime-ai-tutor**
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
from app.repositories.knowledge_graph_repository import InMemoryKnowledgeGraphRepository
from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository

logger = logging.getLogger(__name__)


# Cached repository instance
_knowledge_repo = None


def get_knowledge_repository():
    """Get the best available knowledge repository (cached)."""
    global _knowledge_repo
    
    if _knowledge_repo is not None:
        return _knowledge_repo
    
    # Try Neo4j first
    neo4j_repo = Neo4jKnowledgeRepository()
    if neo4j_repo.is_available():
        logger.info("Using Neo4j knowledge repository")
        _knowledge_repo = neo4j_repo
        return _knowledge_repo
    
    # Fallback to in-memory
    logger.warning("Neo4j unavailable, using in-memory repository")
    _knowledge_repo = InMemoryKnowledgeGraphRepository()
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
        knowledge_graph=None
    ):
        """
        Initialize RAG Agent.
        
        Args:
            knowledge_graph: Knowledge graph repository instance
        """
        self._kg = knowledge_graph or get_knowledge_repository()
        self._llm = self._init_llm()
    
    def _init_llm(self) -> Optional[ChatOpenAI]:
        """Initialize LLM for response synthesis."""
        if not settings.openai_api_key:
            logger.warning("No OpenAI API key, RAG will return raw content")
            return None
        
        try:
            llm_kwargs = {
                "api_key": settings.openai_api_key,
                "model": settings.openai_model,
                "temperature": 0.3,  # Lower for factual responses
            }
            if settings.openai_base_url:
                llm_kwargs["base_url"] = settings.openai_base_url
            
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
        
        Args:
            question: User's question
            limit: Maximum number of sources to retrieve
            conversation_history: Formatted conversation history for context
            user_role: User role for role-based prompting (student/teacher/admin)
            
        Returns:
            RAGResponse with content and citations
            
        **Validates: Requirements 4.1, 8.3**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        """
        # Check if KG is available
        if not self._kg.is_available():
            return self._create_fallback_response(question)
        
        # Perform hybrid search
        nodes = await self._kg.hybrid_search(question, limit=limit)
        
        if not nodes:
            return self._create_no_results_response(question)
        
        # Expand context with related nodes
        expanded_nodes = await self._expand_context(nodes)
        
        # Generate citations
        citations = await self._kg.get_citations(nodes)
        
        # Generate response content with conversation history and role-based prompting
        content = self._generate_response(question, expanded_nodes, conversation_history, user_role)
        
        return RAGResponse(
            content=content,
            citations=citations,
            is_fallback=False
        )

    
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
