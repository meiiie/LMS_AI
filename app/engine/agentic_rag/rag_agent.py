"""
RAG Agent for maritime knowledge retrieval.

This module implements the RAG (Retrieval-Augmented Generation) agent
that queries the Knowledge Graph and generates responses with citations.
Now uses Hybrid Search (Dense + Sparse) for improved retrieval.

Feature: sparse-search-migration
- RAG now uses PostgreSQL for both dense (pgvector) and sparse (tsvector) search
- Neo4j is OPTIONAL and reserved for future Learning Graph integration
- System works fully without Neo4j connection

**Feature: maritime-ai-tutor, hybrid-search, sparse-search-migration**
**Validates: Requirements 4.1, 4.2, 4.4, 8.3**
"""

import logging
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

# CHỈ THỊ SỐ 29: Import thinking extraction utility (lazy import to avoid circular dependency)
# from app.services.output_processor import extract_thinking_from_response

# CHỈ THỊ SỐ 29: PromptLoader for SOTA thinking instruction
from app.prompts.prompt_loader import PromptLoader

from app.core.config import settings
from app.engine.llm_factory import create_rag_llm

# Lazy import for optional LLM providers
ChatOpenAI = None  # Will be imported if needed
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
    """
    Get the Neo4j knowledge repository (cached).
    
    Feature: sparse-search-migration
    NOTE: Neo4j is now OPTIONAL for RAG. RAG uses PostgreSQL for both
    dense (pgvector) and sparse (tsvector) search. Neo4j is reserved
    for future Learning Graph integration with LMS.
    """
    global _knowledge_repo
    
    if _knowledge_repo is not None:
        return _knowledge_repo
    
    _knowledge_repo = Neo4jKnowledgeRepository()
    if _knowledge_repo.is_available():
        logger.info("Neo4j available (reserved for Learning Graph)")
    else:
        # This is OK - RAG works without Neo4j
        logger.info("Neo4j unavailable - RAG uses PostgreSQL hybrid search")
    
    return _knowledge_repo


@dataclass
class EvidenceImage:
    """
    Evidence image reference for Multimodal RAG.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Evidence Images
    **Feature: multimodal-rag-vision**
    """
    url: str
    page_number: int
    document_id: str = ""


@dataclass
class RAGResponse:
    """
    Response from RAG Agent with citations.
    
    **Validates: Requirements 4.1**
    **Feature: multimodal-rag-vision** - Added evidence_images
    **Feature: document-kg** - Added entity_context for GraphRAG
    """
    content: str
    citations: List[Citation]
    is_fallback: bool = False
    disclaimer: Optional[str] = None
    evidence_images: List[EvidenceImage] = None  # CHỈ THỊ 26: Evidence Images
    entity_context: Optional[str] = None  # Feature: document-kg - GraphRAG entity context
    related_entities: List[str] = None  # Feature: document-kg - Related entity names
    native_thinking: Optional[str] = None  # CHỈ THỊ SỐ 29: Gemini native thinking for hybrid display
    
    def __post_init__(self):
        if self.evidence_images is None:
            self.evidence_images = []
        if self.related_entities is None:
            self.related_entities = []
    
    def has_citations(self) -> bool:
        """Check if response has citations."""
        return len(self.citations) > 0
    
    def has_evidence_images(self) -> bool:
        """Check if response has evidence images."""
        return len(self.evidence_images) > 0
    
    def has_entity_context(self) -> bool:
        """Check if response has entity context from GraphRAG."""
        return bool(self.entity_context)


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
        hybrid_search_service=None,
        graph_rag_service=None  # Feature: document-kg
    ):
        """
        Initialize RAG Agent.
        
        Args:
            knowledge_graph: Knowledge graph repository instance
            hybrid_search_service: Hybrid search service for Dense+Sparse search
            graph_rag_service: GraphRAG service for entity-enriched search
        """
        self._kg = knowledge_graph or get_knowledge_repository()
        
        # Lazy import to avoid circular dependency
        if hybrid_search_service is None:
            from app.services.hybrid_search_service import get_hybrid_search_service
            self._hybrid_search = get_hybrid_search_service()
        else:
            self._hybrid_search = hybrid_search_service
        
        # Feature: document-kg - GraphRAG for entity context
        if graph_rag_service is None:
            try:
                from app.services.graph_rag_service import get_graph_rag_service
                self._graph_rag = get_graph_rag_service()
                logger.info("GraphRAG service initialized for entity context")
            except Exception as e:
                logger.warning(f"GraphRAG not available: {e}")
                self._graph_rag = None
        else:
            self._graph_rag = graph_rag_service
        
        # CHỈ THỊ SỐ 29: Initialize PromptLoader for SOTA thinking instruction
        self._prompt_loader = PromptLoader()
            
        self._llm = self._init_llm()
    
    def _init_llm(self):
        """
        Initialize LLM for response synthesis.
        
        CHỈ THỊ SỐ 28: Uses MODERATE tier thinking (4096 tokens) for RAG synthesis.
        Supports Google Gemini (primary) and OpenAI/OpenRouter (fallback).
        """
        provider = getattr(settings, 'llm_provider', 'google')
        
        # Try Google Gemini first with MODERATE tier thinking
        if provider == "google" or (not settings.openai_api_key and settings.google_api_key):
            if settings.google_api_key:
                try:
                    logger.info(f"RAG using Gemini with MODERATE thinking: {settings.google_model}")
                    return create_rag_llm(temperature=0.3)  # Lower for factual responses
                except Exception as e:
                    logger.error(f"Failed to initialize Gemini for RAG: {e}")
        
        # Fallback to OpenAI/OpenRouter (optional)
        if not settings.openai_api_key:
            logger.warning("No LLM API key, RAG will return raw content")
            return None
        
        try:
            # Lazy import ChatOpenAI only when needed
            global ChatOpenAI
            if ChatOpenAI is None:
                try:
                    from langchain_openai import ChatOpenAI as _ChatOpenAI
                    ChatOpenAI = _ChatOpenAI
                except ImportError:
                    logger.warning("langchain-openai not installed, skipping OpenAI fallback")
                    return None
            
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
        
        Uses GraphRAG (Hybrid Search + Entity Context) for improved retrieval.
        
        Args:
            question: User's question
            limit: Maximum number of sources to retrieve
            conversation_history: Formatted conversation history for context
            user_role: User role for role-based prompting (student/teacher/admin)
            
        Returns:
            RAGResponse with content, citations, and entity context
            
        **Validates: Requirements 4.1, 8.3**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        **Feature: hybrid-search, document-kg**
        """
        # Check if search is available
        if not self._hybrid_search.is_available():
            return self._create_fallback_response(question)
        
        # Feature: document-kg - Use GraphRAG for entity-enriched search
        entity_context = ""
        related_entities = []
        hybrid_results = []
        
        if self._graph_rag and self._graph_rag.is_available():
            try:
                # GraphRAG search with entity context
                graph_results, entity_ctx = await self._graph_rag.search_with_graph_context(
                    query=question,
                    limit=limit
                )
                
                if graph_results:
                    # Convert GraphEnhancedResult to HybridSearchResult format
                    hybrid_results = self._graph_to_hybrid_results(graph_results)
                    entity_context = entity_ctx
                    
                    # Collect related entities from results
                    for gr in graph_results:
                        if gr.related_entities:
                            related_entities.extend(gr.related_entities[:3])
                        if gr.related_regulations:
                            related_entities.extend(gr.related_regulations[:3])
                    
                    # Deduplicate
                    related_entities = list(dict.fromkeys(related_entities))[:10]
                    
                    logger.info(f"[GraphRAG] Found {len(hybrid_results)} results with entity context")
            except Exception as e:
                logger.warning(f"GraphRAG search failed, falling back to hybrid: {e}")
                hybrid_results = []
        
        # Fallback to standard hybrid search if GraphRAG unavailable or failed
        if not hybrid_results:
            hybrid_results = await self._hybrid_search.search(question, limit=limit)
        
        if not hybrid_results:
            # Fallback to legacy Neo4j search
            logger.info("Hybrid search returned no results, falling back to legacy search")
            nodes = await self._kg.hybrid_search(question, limit=limit)
            if not nodes:
                return self._create_no_results_response(question)
            expanded_nodes = await self._expand_context(nodes)
            citations = await self._kg.get_citations(nodes)
            # CHỈ THỊ SỐ 29: Unpack tuple with native_thinking
            content, native_thinking = self._generate_response(question, expanded_nodes, conversation_history, user_role, entity_context)
            return RAGResponse(content=content, citations=citations, is_fallback=False, native_thinking=native_thinking)
        
        # Convert hybrid results to KnowledgeNodes for compatibility
        nodes = self._hybrid_results_to_nodes(hybrid_results)
        
        # Expand context with related nodes
        expanded_nodes = await self._expand_context(nodes)
        
        # Generate citations with relevance scores
        citations = self._generate_hybrid_citations(hybrid_results)
        
        # Generate response content with entity context
        # CHỈ THỊ SỐ 29: Unpack tuple with native_thinking
        content, native_thinking = self._generate_response(
            question, expanded_nodes, conversation_history, user_role, entity_context
        )
        
        # Add search method info to response
        search_method = hybrid_results[0].search_method if hybrid_results else "hybrid"
        if entity_context:
            search_method = "graph_enhanced"
        if search_method not in ["hybrid", "graph_enhanced"]:
            content += f"\n\n*[Tìm kiếm: {search_method}]*"
        
        # CHỈ THỊ 26: Collect evidence images
        node_ids = [r.node_id for r in hybrid_results]
        evidence_images = await self._collect_evidence_images(node_ids, max_images=3)
        
        return RAGResponse(
            content=content,
            citations=citations,
            is_fallback=False,
            evidence_images=evidence_images,
            entity_context=entity_context,
            related_entities=related_entities,
            native_thinking=native_thinking  # CHỈ THỊ SỐ 29: Propagate native thinking
        )
    
    def _graph_to_hybrid_results(self, graph_results) -> List[HybridSearchResult]:
        """Convert GraphEnhancedResult to HybridSearchResult for compatibility."""
        hybrid_results = []
        for gr in graph_results:
            hybrid_results.append(HybridSearchResult(
                node_id=gr.chunk_id,
                content=gr.content,
                title=gr.content[:50] + "..." if len(gr.content) > 50 else gr.content,
                source=gr.document_id or "Maritime Knowledge Base",
                category=getattr(gr, 'category', 'Knowledge'),  # SOTA: graceful fallback
                rrf_score=gr.score,
                dense_score=gr.dense_score,
                sparse_score=gr.sparse_score,
                search_method=gr.search_method,
                page_number=gr.page_number,
                document_id=gr.document_id,
                image_url=gr.image_url
            ))
        return hybrid_results
    
    def _hybrid_results_to_nodes(self, results: List[HybridSearchResult]) -> List[KnowledgeNode]:
        """Convert HybridSearchResult to KnowledgeNode for compatibility with chunking metadata."""
        from app.models.knowledge_graph import NodeType
        
        nodes = []
        for r in results:
            # Skip results with empty title or content
            title = r.title or ""
            content = r.content or ""
            
            if not title.strip() or not content.strip():
                logger.warning(f"Skipping result with empty title/content: {r.node_id}")
                continue
            
            # Build enhanced title with document hierarchy
            enhanced_title = self._format_title_with_hierarchy(title, r)
            
            nodes.append(KnowledgeNode(
                id=r.node_id,
                node_type=NodeType.CONCEPT,
                title=enhanced_title,
                content=content,
                source=r.source or "Maritime Knowledge Base",
                metadata={
                    "category": r.category,
                    "rrf_score": r.rrf_score,
                    "dense_score": r.dense_score,
                    "sparse_score": r.sparse_score,
                    "search_method": r.search_method,
                    # Semantic chunking metadata
                    "content_type": r.content_type,
                    "confidence_score": r.confidence_score,
                    "page_number": r.page_number,
                    "chunk_index": r.chunk_index,
                    "image_url": r.image_url,
                    "document_id": r.document_id,
                    "section_hierarchy": r.section_hierarchy
                }
            ))
        return nodes
    
    def _format_title_with_hierarchy(self, title: str, result: HybridSearchResult) -> str:
        """
        Format title with document hierarchy (Điều, Khoản, etc.).
        
        **Feature: semantic-chunking**
        **Validates: Requirements 8.4**
        """
        hierarchy = result.section_hierarchy or {}
        if not hierarchy:
            return title
        
        # Build hierarchy prefix
        parts = []
        if 'article' in hierarchy:
            parts.append(f"Điều {hierarchy['article']}")
        if 'clause' in hierarchy:
            parts.append(f"Khoản {hierarchy['clause']}")
        if 'point' in hierarchy:
            parts.append(f"Điểm {hierarchy['point']}")
        if 'rule' in hierarchy:
            parts.append(f"Rule {hierarchy['rule']}")
        
        if parts:
            hierarchy_prefix = " - ".join(parts)
            # Avoid duplicate if title already contains hierarchy
            if hierarchy_prefix.lower() not in title.lower():
                return f"[{hierarchy_prefix}] {title}"
        
        return title
    
    def _generate_hybrid_citations(self, results: List[HybridSearchResult]) -> List[Citation]:
        """
        Generate citations from hybrid search results with relevance scores and chunking metadata.
        
        **Feature: semantic-chunking, source-highlight-citation**
        **Validates: Requirements 8.4, 8.5, 2.1, 2.3**
        """
        citations = []
        for r in results:
            # Format title with hierarchy
            enhanced_title = self._format_title_with_hierarchy(r.title, r)
            
            # Add content type indicator for special types
            if r.content_type == "table":
                enhanced_title = f"📊 {enhanced_title}"
            elif r.content_type == "heading":
                enhanced_title = f"📑 {enhanced_title}"
            elif r.content_type == "diagram_reference":
                enhanced_title = f"📈 {enhanced_title}"
            
            citations.append(Citation(
                node_id=r.node_id,
                source=r.source or "Maritime Knowledge Base",
                title=enhanced_title,
                relevance_score=r.rrf_score,
                image_url=r.image_url,  # CHỈ THỊ 26: Evidence images
                # Feature: source-highlight-citation
                page_number=r.page_number,
                document_id=r.document_id,
                bounding_boxes=r.bounding_boxes
            ))
        return citations
    
    async def _collect_evidence_images(
        self,
        node_ids: List[str],
        max_images: int = 3
    ) -> List[EvidenceImage]:
        """
        Collect evidence images from database for given node IDs.
        
        CHỈ THỊ KỸ THUẬT SỐ 26: Evidence Images
        
        **Property 3: Search Results Include Image URL**
        **Property 11: Response Metadata Contains Evidence Images**
        **Property 12: Maximum Evidence Images Per Response**
        
        Args:
            node_ids: List of node IDs to get images for
            max_images: Maximum number of images to return (default 3)
            
        Returns:
            List of EvidenceImage objects
        """
        import asyncpg
        
        evidence_images = []
        seen_urls = set()
        
        try:
            # Get database URL and convert for asyncpg
            db_url = settings.database_url or ""
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
            db_url = db_url.replace("postgres://", "postgresql://")
            
            conn = await asyncpg.connect(db_url)
            try:
                # Query for image URLs - use id::text since schema uses UUID id not node_id
                rows = await conn.fetch(
                    """
                    SELECT id::text as node_id, image_url, page_number, document_id
                    FROM knowledge_embeddings
                    WHERE id::text = ANY($1)
                    AND image_url IS NOT NULL
                    ORDER BY page_number
                    """,
                    node_ids
                )
                
                for row in rows:
                    image_url = row['image_url']
                    
                    # Skip duplicates or empty URLs
                    if not image_url or image_url in seen_urls:
                        continue
                    
                    seen_urls.add(image_url)
                    evidence_images.append(EvidenceImage(
                        url=image_url,
                        page_number=row['page_number'] or 0,
                        document_id=row['document_id'] or ""
                    ))
                    
                    # Limit to max_images
                    if len(evidence_images) >= max_images:
                        break
            finally:
                await conn.close()
                        
        except Exception as e:
            logger.warning(f"Failed to collect evidence images: {e}")
        
        return evidence_images

    
    async def _expand_context(
        self, 
        nodes: List[KnowledgeNode]
    ) -> List[KnowledgeNode]:
        """
        Expand context by traversing relations.
        
        NOTE: Neo4j is DISABLED for RAG as of v0.6.0 (sparse-search-migration).
        Neo4j is reserved for future Learning Graph integration.
        This method is kept for backward compatibility but returns nodes unchanged.
        
        **Validates: Requirements 4.4**
        """
        # Neo4j disabled for RAG - reserved for Learning Graph (v0.6.0+)
        # See README.md: "Neo4j: Reserved for future Learning Graph (LMS integration)"
        return list(nodes)
    
    def _generate_response(
        self, 
        question: str, 
        nodes: List[KnowledgeNode],
        conversation_history: str = "",
        user_role: str = "student",
        entity_context: str = ""  # Feature: document-kg
    ) -> Tuple[str, Optional[str]]:
        """
        Generate response using LLM to synthesize retrieved knowledge.
        
        Uses RAG pattern: Retrieve -> Augment -> Generate
        Includes conversation history for context continuity.
        Now includes entity context from GraphRAG for enriched responses.
        
        CHỈ THỊ SỐ 29: Returns tuple of (answer, native_thinking) for hybrid display.
        
        Role-Based Prompting (CHỈ THỊ KỸ THUẬT SỐ 03):
        - student: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
        - teacher/admin: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
        
        Returns:
            Tuple of (answer_text, native_thinking) where native_thinking may be None
        
        **Feature: maritime-ai-tutor, Week 2: Memory Lite, document-kg**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03, CHỈ THỊ SỐ 29**
        """
        if not nodes:
            return "I couldn't find specific information about that topic.", None
        
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
            if entity_context:
                response = f"**Ngữ cảnh thực thể:** {entity_context}\n\n" + response
            if sources:
                response += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
            return response, None  # No native thinking when no LLM
        
        # CHỈ THỊ SỐ 29 v8: Vietnamese thinking instruction removed from YAML
        # Now using direct <thinking> tag instruction (like unified_agent.py)
        
        # CHỈ THỊ KỸ THUẬT SỐ 12: System Prompt tối ưu cho RAG v2
        if user_role == "student":
            base_prompt = """BẠN LÀ: Maritime AI Tutor - Chuyên gia tra cứu luật hàng hải.

⚠️ QUY TẮC BẮT BUỘC VỀ SUY LUẬN (<thinking>) - CHỈ THỊ SỐ 29:

LUÔN bắt đầu response bằng <thinking> (BẰNG TIẾNG VIỆT):
- Trong <thinking>, giải thích:
  + User đang hỏi về gì? (phân tích câu hỏi)
  + Kết quả tra cứu cho thấy điều gì? (tóm tắt thông tin từ sources)
  + Cách tổng hợp thông tin để trả lời (reasoning)
- Sau </thinking>, mới đưa ra câu trả lời chính thức

VÍ DỤ:
<thinking>
Người dùng hỏi về Điều 15 của Bộ luật Hàng hải.
Kết quả tra cứu cho thấy Điều 15 quy định về định nghĩa chủ tàu.
Tôi sẽ giải thích rõ ràng và trích dẫn nguồn.
</thinking>

Theo Điều 15 Bộ luật Hàng hải Việt Nam...

QUY TẮC GỌI TÊN (RẤT QUAN TRỌNG):
- KHÔNG gọi tên ở đầu mỗi câu trả lời
- KHÔNG bắt đầu bằng "Chào [tên]" - đây là lỗi phổ biến cần tránh
- Đi thẳng vào nội dung: "Quy tắc 15 quy định rằng...", "Theo COLREGs..."
- Chỉ gọi tên khi CẦN THIẾT trong ngữ cảnh

QUY TẮC VARIATION:
- Đa dạng cách mở đầu: "Theo quy định...", "Cụ thể là...", "Về vấn đề này..."
- KHÔNG dùng cùng pattern cho mọi câu trả lời
- Câu hỏi follow-up ngắn → Trả lời ngắn gọn, đi thẳng vào điểm chính

NHIỆM VỤ:
- Trả lời dựa trên KIẾN THỨC TRA CỨU ĐƯỢC bên dưới
- Nếu có NGỮ CẢNH THỰC THỂ, sử dụng để liên kết các khái niệm và điều luật liên quan
- Trích dẫn nguồn khi đề cập quy định cụ thể
- Dịch thuật ngữ: starboard = mạn phải, port = mạn trái, give-way = nhường đường
- Trả lời bằng tiếng Việt"""
        else:
            base_prompt = """BẠN LÀ: Maritime AI Assistant - Trợ lý tra cứu luật hàng hải.

⚠️ QUY TẮC BẮT BUỘC VỀ SUY LUẬN (<thinking>) - CHỈ THỊ SỐ 29:

LUÔN bắt đầu response bằng <thinking> (BẰNG TIẾNG VIỆT):
- Phân tích ngắn gọn câu hỏi và sources
- Sau </thinking>, đưa ra câu trả lời

QUY TẮC:
- Đi thẳng vào vấn đề, KHÔNG greeting
- Trích dẫn chính xác số hiệu quy định
- Súc tích, chuyên nghiệp

NHIỆM VỤ:
- Trả lời dựa trên KIẾN THỨC TRA CỨU ĐƯỢC bên dưới
- Nếu có NGỮ CẢNH THỰC THỂ, tham chiếu các điều luật liên quan
- Trả lời bằng tiếng Việt"""
        
        # Use base_prompt directly (thinking instruction now embedded)
        system_prompt = base_prompt


        # Build user prompt with history and entity context
        history_section = ""
        if conversation_history:
            history_section = f"""
---
LỊCH SỬ HỘI THOẠI (Gần nhất):
{conversation_history}
---
"""

        # Feature: document-kg - Add entity context section
        entity_section = ""
        if entity_context:
            entity_section = f"""
---
NGỮ CẢNH THỰC THỂ (GraphRAG):
{entity_context}
---
"""

        user_prompt = f"""{history_section}{entity_section}
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
            
            # CHỈ THỊ SỐ 29: Extract native thinking from Gemini response
            # When include_thoughts=True, response.content may be a list of content blocks
            # Lazy import to avoid circular dependency
            from app.services.output_processor import extract_thinking_from_response
            answer, native_thinking = extract_thinking_from_response(response.content)
            
            if native_thinking:
                logger.info(f"[RAG] Native thinking extracted: {len(native_thinking)} chars")
            
            # Add sources
            if sources:
                answer += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
            
            return answer, native_thinking
            
        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}")
            # Fallback to raw content
            response = context
            if sources:
                response += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
            return response, None  # No native thinking on error
    
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
        """
        Check if RAG Agent is available.
        
        Feature: sparse-search-migration
        RAG is available if hybrid search (PostgreSQL) is available.
        Neo4j is optional and not required for RAG functionality.
        """
        return self._hybrid_search.is_available()


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


# =============================================================================
# SINGLETON PATTERN (Professional Implementation)
# =============================================================================
# Pattern: Thread-safe lazy initialization with double-check locking
# Reference: Python `logging` module pattern, Google style guide
# 
# Why singleton for LLM:
# - Each RAGAgent creates an LLM instance (~100MB RAM)
# - Without singleton, each request creates new instances → memory overflow
# - Singleton is VALID pattern for single-process Python apps (expert verified)
# =============================================================================

# Note: imports moved to top of file

_rag_agent: Optional[RAGAgent] = None
_rag_agent_lock = threading.Lock()


def get_rag_agent(
    knowledge_graph=None,
    hybrid_search_service=None,
    graph_rag_service=None,
    force_new: bool = False
) -> RAGAgent:
    """
    Get or create RAGAgent singleton (thread-safe).
    
    This is the RECOMMENDED way to obtain a RAGAgent instance.
    Direct instantiation via RAGAgent() should be avoided in production
    to prevent memory overflow from creating multiple LLM instances.
    
    Pattern: Double-check locking for thread-safety without performance penalty.
    
    Args:
        knowledge_graph: Optional knowledge graph repository
        hybrid_search_service: Optional hybrid search service
        graph_rag_service: Optional GraphRAG service
        force_new: If True, create a new instance (for testing only)
        
    Returns:
        RAGAgent singleton instance
        
    Example:
        >>> agent = get_rag_agent()
        >>> response = await agent.query("What is Rule 15?")
        
    Note:
        For testing, use `reset_rag_agent()` to clear singleton between tests.
    """
    global _rag_agent
    
    # Fast path: return existing instance (no lock needed)
    if _rag_agent is not None and not force_new:
        return _rag_agent
    
    # Slow path: create new instance with lock
    with _rag_agent_lock:
        # Double-check inside lock (another thread might have created it)
        if _rag_agent is None or force_new:
            try:
                logger.info("[RAGAgent] Creating singleton instance...")
                _rag_agent = RAGAgent(
                    knowledge_graph=knowledge_graph,
                    hybrid_search_service=hybrid_search_service,
                    graph_rag_service=graph_rag_service
                )
                logger.info("[RAGAgent] Singleton created successfully")
            except Exception as e:
                logger.error(f"[RAGAgent] Failed to create singleton: {e}")
                raise  # Re-raise to let caller handle
    
    return _rag_agent


def reset_rag_agent() -> None:
    """
    Reset the RAGAgent singleton (for testing only).
    
    This clears the cached instance, allowing the next call to
    get_rag_agent() to create a fresh instance.
    
    WARNING: Do NOT call in production - only for unit tests.
    
    Example:
        >>> # In test teardown
        >>> reset_rag_agent()
    """
    global _rag_agent
    with _rag_agent_lock:
        if _rag_agent is not None:
            logger.info("[RAGAgent] Resetting singleton (test mode)")
            _rag_agent = None


def is_rag_agent_initialized() -> bool:
    """
    Check if RAGAgent singleton is already initialized.
    
    Useful for health checks and pre-warming verification.
    
    Returns:
        True if singleton exists, False otherwise
    """
    return _rag_agent is not None


