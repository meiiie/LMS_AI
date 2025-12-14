"""
Context Enricher for Contextual RAG

Implements Anthropic's Contextual Retrieval approach:
- Add document context to each chunk using LLM
- 49% improvement in retrieval accuracy

**Feature: contextual-rag**
**Reference: Anthropic Contextual Retrieval (2024)**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 27 - Contextual RAG**
"""
import logging
import asyncio
from typing import List, Optional, TYPE_CHECKING
from dataclasses import dataclass

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from app.core.config import settings

if TYPE_CHECKING:
    from app.services.chunking_service import ChunkResult

logger = logging.getLogger(__name__)


# Context generation prompt (optimized for maritime documents)
CONTEXT_PROMPT_TEMPLATE = """Bạn đang hỗ trợ hệ thống RAG tạo context cho các đoạn văn bản pháp luật hàng hải.

<document>
Tài liệu: {document_title}
Trang: {page_number}/{total_pages}
</document>

<chunk>
{chunk_content}
</chunk>

Viết MỘT đoạn context ngắn (50-80 từ) mô tả chunk này để cải thiện retrieval:
1. Chunk này thuộc phần/chương/điều/khoản nào của tài liệu?
2. Nội dung chính và mục đích của quy định này là gì?
3. Liên quan đến khái niệm/quy tắc hàng hải nào (nếu có)?

QUAN TRỌNG: Chỉ trả về đoạn context, không có tiêu đề, bullet points hay định dạng khác."""


@dataclass
class EnrichmentResult:
    """Result of context enrichment"""
    original_content: str
    contextual_content: str
    context_only: str  # Just the context prefix
    success: bool
    error: Optional[str] = None


class ContextEnricher:
    """
    Enrich chunks with document context using LLM.
    
    Implements Anthropic's Contextual Retrieval approach:
    1. Take each chunk
    2. Use LLM to generate context description
    3. Prepend context to chunk for better embeddings
    
    **Feature: contextual-rag**
    """
    
    def __init__(self, llm: Optional[ChatGoogleGenerativeAI] = None):
        """
        Initialize Context Enricher.
        
        Args:
            llm: Optional LLM instance, will create if not provided
        """
        self._llm = llm
        self._initialized = False
        logger.info("ContextEnricher created (lazy initialization)")
    
    def _ensure_llm(self) -> ChatGoogleGenerativeAI:
        """Lazy initialize LLM when first needed."""
        if self._llm is None:
            self._llm = ChatGoogleGenerativeAI(
                model=settings.google_model,
                google_api_key=settings.google_api_key,
                temperature=0.3,  # Lower for consistent context
                max_output_tokens=300  # Enough for 50-80 word context
            )
            logger.info(f"ContextEnricher LLM initialized: {settings.google_model}")
        return self._llm
    
    async def generate_context(
        self,
        chunk_content: str,
        document_title: str,
        page_number: int = 1,
        total_pages: int = 1
    ) -> EnrichmentResult:
        """
        Generate context for a single chunk.
        
        Args:
            chunk_content: The original chunk text
            document_title: Title/ID of the source document
            page_number: Page number in document
            total_pages: Total pages in document
            
        Returns:
            EnrichmentResult with context and enriched content
        """
        try:
            llm = self._ensure_llm()
            
            # Build prompt
            prompt = CONTEXT_PROMPT_TEMPLATE.format(
                document_title=document_title,
                page_number=page_number,
                total_pages=total_pages,
                chunk_content=chunk_content[:1500]  # Limit chunk size in prompt
            )
            
            # Generate context
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            context = response.content.strip()
            
            # Create enriched content: [Context]\n\n[Original]
            contextual_content = f"[Context: {context}]\n\n{chunk_content}"
            
            return EnrichmentResult(
                original_content=chunk_content,
                contextual_content=contextual_content,
                context_only=context,
                success=True
            )
            
        except Exception as e:
            logger.warning(f"Context generation failed: {e}")
            # Fallback: return original content
            return EnrichmentResult(
                original_content=chunk_content,
                contextual_content=chunk_content,  # No context added
                context_only="",
                success=False,
                error=str(e)
            )
    
    async def enrich_chunks(
        self,
        chunks: List["ChunkResult"],
        document_id: str,
        document_title: Optional[str] = None,
        total_pages: int = 1,
        batch_size: int = 5
    ) -> List["ChunkResult"]:
        """
        Enrich multiple chunks with context.
        
        Args:
            chunks: List of ChunkResult objects
            document_id: Document identifier
            document_title: Human-readable title (defaults to document_id)
            total_pages: Total pages in document
            batch_size: Number of chunks to process concurrently
            
        Returns:
            Updated ChunkResult list with contextual_content filled
        """
        if not settings.contextual_rag_enabled:
            logger.debug("Contextual RAG disabled, skipping enrichment")
            return chunks
        
        if not chunks:
            return chunks
        
        title = document_title or document_id
        enriched_count = 0
        failed_count = 0
        
        logger.info(f"Enriching {len(chunks)} chunks for '{title}'")
        
        # Process in batches to avoid rate limits
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            # Create tasks for batch
            tasks = []
            for chunk in batch:
                page_num = chunk.metadata.get('page_number', 1)
                task = self.generate_context(
                    chunk_content=chunk.content,
                    document_title=title,
                    page_number=page_num,
                    total_pages=total_pages
                )
                tasks.append(task)
            
            # Execute batch concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update chunks with results
            for j, result in enumerate(results):
                chunk = batch[j]
                
                if isinstance(result, Exception):
                    logger.warning(f"Chunk {i+j} enrichment failed: {result}")
                    failed_count += 1
                    continue
                
                if result.success:
                    chunk.contextual_content = result.contextual_content
                    chunk.metadata['context_generated'] = True
                    chunk.metadata['context_text'] = result.context_only
                    enriched_count += 1
                else:
                    failed_count += 1
            
            # Small delay between batches to avoid rate limits
            if i + batch_size < len(chunks):
                await asyncio.sleep(0.5)
        
        logger.info(
            f"Context enrichment complete: {enriched_count} enriched, "
            f"{failed_count} failed, {len(chunks)} total"
        )
        
        return chunks


# Singleton instance
_enricher_instance: Optional[ContextEnricher] = None


def get_context_enricher() -> ContextEnricher:
    """Get or create singleton ContextEnricher instance."""
    global _enricher_instance
    if _enricher_instance is None:
        _enricher_instance = ContextEnricher()
    return _enricher_instance
