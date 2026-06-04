"""
Knowledge Ingestion API Endpoints.

Provides endpoints for Admin to upload PDF documents using Multimodal RAG pipeline.

Feature: multimodal-rag-vision, semantic-chunking
Requirements: 1.1, 1.2, 1.3, 1.4, 7.1, 7.4

NOTE: Legacy Neo4j-based ingestion endpoints have been removed.
See: .kiro/specs/sparse-search-migration/design.md for migration details.
Archived files: archive/ingestion_service_legacy.py, archive/pdf_processor_legacy.py
"""

import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.api.deps import RequireAdmin, RequireAuth
from app.core.rate_limit import limiter
from app.engine.embedding_runtime import get_embedding_backend
from app.repositories.knowledge_search_org_scope import (
    log_knowledge_search_scope_blocked,
    resolve_knowledge_search_org_scope,
)
from app.services.multimodal_ingestion_service import get_ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Ingestion"])

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = ["application/pdf"]


def validate_file(file: UploadFile) -> None:
    """
    Validate uploaded file type and size.
    
    **Validates: Requirements 1.3, 1.4**
    """
    # Check file type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Only PDF files are accepted. Got: {file.content_type}"
        )
    
    # Check filename extension
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Invalid file extension. Only .pdf files are accepted."
        )


# =============================================================================
# MULTIMODAL RAG INGESTION (CHỈ THỊ KỸ THUẬT SỐ 26)
# =============================================================================

class MultimodalIngestionResponse(BaseModel):
    """Response for multimodal document ingestion."""
    status: str
    document_id: str
    total_pages: int
    successful_pages: int
    failed_pages: int
    success_rate: float
    errors: list[str] = []
    message: str
    
    # Hybrid Text/Vision Detection stats (Feature: hybrid-text-vision)
    vision_pages: int = 0       # Pages processed via Gemini Vision API
    direct_pages: int = 0       # Pages processed via PyMuPDF direct extraction
    fallback_pages: int = 0     # Pages that fell back from direct to vision
    api_savings_percent: float = 0.0  # Estimated API cost savings


@router.post("/ingest-multimodal", response_model=MultimodalIngestionResponse)
@limiter.limit("10/minute")
async def ingest_multimodal_document(
    request: Request,
    auth: RequireAdmin,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_id: str = Form(...),
    organization_id: Optional[str] = Form(default=None),
    resume: bool = Form(default=True),
    max_pages: Optional[int] = Form(default=None),
    start_page: Optional[int] = Form(default=None),
    end_page: Optional[int] = Form(default=None)
) -> MultimodalIngestionResponse:
    """
    Upload a PDF document for Multimodal RAG ingestion.

    CHỈ THỊ KỸ THUẬT SỐ 26: Vision-based Document Understanding

    Pipeline:
    1. PDF → Images (PyMuPDF - no external dependencies)
    2. Images → Object Storage (public URLs)
    3. Images → Gemini Vision (text extraction)
    4. Text → Semantic Chunking (maritime-specific patterns)
    5. Chunks + Embeddings + image_url → Neon Database

    - **file**: PDF file to upload (max 50MB)
    - **document_id**: Unique identifier for the document
    - **organization_id**: Organization scope for multi-tenant isolation (optional)
    - **resume**: Resume from last successful page if interrupted (default: True)
    - **max_pages**: Maximum pages to process (optional, for testing)
    - **start_page**: Start processing from this page (1-indexed, for batch processing)
    - **end_page**: Stop processing at this page (1-indexed, inclusive)

    Returns ingestion result with page counts and errors.

    **Feature: multimodal-rag-vision, semantic-chunking, hybrid-text-vision**
    **Validates: Requirements 2.1, 7.1, 7.4**
    """
    
    # Validate file
    validate_file(file)
    
    # Read file content
    content = await file.read()
    
    # Check file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is 50MB. Got: {len(content) / 1024 / 1024:.2f}MB"
        )
    
    # Save to temp file for PyMuPDF processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(content)
        tmp_path = tmp_file.name
    
    try:
        service = get_ingestion_service()
        
        # Process document
        result = await service.ingest_pdf(
            pdf_path=tmp_path,
            document_id=document_id,
            resume=resume,
            max_pages=max_pages,
            start_page=start_page,
            end_page=end_page,
            organization_id=organization_id,
            source_name=file.filename
        )
        
        logger.info(
            "Multimodal ingestion completed: %d/%d pages (%.1f%%)",
            result.successful_pages, result.total_pages, result.success_rate
        )
        
        return MultimodalIngestionResponse(
            status="completed" if result.failed_pages == 0 else "partial",
            document_id=result.document_id,
            total_pages=result.total_pages,
            successful_pages=result.successful_pages,
            failed_pages=result.failed_pages,
            success_rate=result.success_rate,
            errors=result.errors,
            message=f"Processed {result.successful_pages}/{result.total_pages} pages successfully",
            # Hybrid Text/Vision Detection stats (Feature: hybrid-text-vision)
            vision_pages=result.vision_pages,
            direct_pages=result.direct_pages,
            fallback_pages=result.fallback_pages,
            api_savings_percent=result.api_savings_percent
        )
        
    except Exception as e:
        logger.error("Multimodal ingestion failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Multimodal ingestion failed"
        )
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# =============================================================================
# KNOWLEDGE BASE STATISTICS (PostgreSQL-based)
# =============================================================================

class KnowledgeStatsResponse(BaseModel):
    """Response for knowledge statistics."""
    total_chunks: int
    total_documents: int
    content_types: dict
    avg_confidence: float
    domain_breakdown: dict = {}  # Sprint 136: Per-domain chunk counts
    warning: Optional[str] = None


EMPTY_KNOWLEDGE_BASE_WARNING = (
    "Knowledge base is empty; ingest documents before relying on source-backed RAG."
)


def build_knowledge_stats_warning(total_chunks: int, total_documents: int) -> Optional[str]:
    """Surface empty-KB readiness gaps without treating DB connectivity as failed."""
    if total_chunks <= 0 or total_documents <= 0:
        return EMPTY_KNOWLEDGE_BASE_WARNING
    return None


def _resolve_knowledge_stats_org(auth: RequireAuth) -> str:
    scope = resolve_knowledge_search_org_scope(getattr(auth, "organization_id", None))
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(logger, "knowledge_stats", scope)
        raise HTTPException(
            status_code=403,
            detail="Organization context required for knowledge statistics",
        )
    return scope.org_id


@router.get("/stats", response_model=KnowledgeStatsResponse)
@limiter.limit("60/minute")
async def get_statistics(request: Request, auth: RequireAuth) -> KnowledgeStatsResponse:
    """
    Get knowledge base statistics from PostgreSQL.
    
    Returns total chunks, documents, content type breakdown, and average confidence.
    
    **Feature: semantic-chunking**
    """
    try:
        import asyncpg
        from app.core.config import settings

        org_id = _resolve_knowledge_stats_org(auth)
        org_filter = "(organization_id = $1 OR organization_id IS NULL)"

        # Use connection as context manager to ensure proper cleanup
        conn = await asyncpg.connect(settings.asyncpg_url)
        try:
            # Run all stats queries in a single connection
            total_chunks = await conn.fetchval(
                f"SELECT COUNT(*) FROM knowledge_embeddings WHERE {org_filter}",
                org_id,
            )

            total_documents = await conn.fetchval(
                f"""
                SELECT COUNT(DISTINCT document_id)
                FROM knowledge_embeddings
                WHERE document_id IS NOT NULL
                AND {org_filter}
                """,
                org_id,
            )

            content_type_rows = await conn.fetch(
                f"""
                SELECT content_type, COUNT(*) as count
                FROM knowledge_embeddings
                WHERE content_type IS NOT NULL
                AND {org_filter}
                GROUP BY content_type
                """,
                org_id,
            )
            content_types = {row['content_type']: row['count'] for row in content_type_rows}

            avg_confidence = await conn.fetchval(
                f"""
                SELECT AVG(confidence_score)
                FROM knowledge_embeddings
                WHERE confidence_score IS NOT NULL
                AND {org_filter}
                """,
                org_id,
            ) or 0.0

            # Sprint 136: Domain breakdown
            domain_rows = await conn.fetch(
                f"""
                SELECT COALESCE(domain_id, 'untagged') as domain, COUNT(*) as count
                FROM knowledge_embeddings
                WHERE {org_filter}
                GROUP BY domain_id
                """,
                org_id,
            )
            domain_breakdown = {row['domain']: row['count'] for row in domain_rows}

            return KnowledgeStatsResponse(
                total_chunks=total_chunks or 0,
                total_documents=total_documents or 0,
                content_types=content_types,
                avg_confidence=round(float(avg_confidence), 3),
                domain_breakdown=domain_breakdown,
                warning=build_knowledge_stats_warning(
                    total_chunks=total_chunks or 0,
                    total_documents=total_documents or 0,
                )
            )
        finally:
            await conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Stats error: %s", e)
        return KnowledgeStatsResponse(
            total_chunks=0,
            total_documents=0,
            content_types={},
            avg_confidence=0.0,
            warning="Database connection failed"
        )


# =============================================================================
# TEXT/MARKDOWN INGESTION (Sprint 136: Universal KB)
# =============================================================================

class TextIngestionRequest(BaseModel):
    """Request body for text/markdown ingestion."""
    content: str
    document_id: str
    domain_id: Optional[str] = None
    title: Optional[str] = None
    organization_id: Optional[str] = None


class TextIngestionResponse(BaseModel):
    """Response for text ingestion."""
    status: str
    document_id: str
    total_chunks: int
    domain_id: Optional[str] = None
    message: str


@router.post("/ingest-text", response_model=TextIngestionResponse)
@limiter.limit("30/minute")
async def ingest_text_document(
    request: Request,
    auth: RequireAdmin,
    body: TextIngestionRequest,
) -> TextIngestionResponse:
    """
    Ingest raw text or markdown content into the knowledge base.

    Sprint 136: Universal KB — enables quick KB population without PDF processing.

    Pipeline:
    1. Text → SemanticChunker (general + maritime patterns)
    2. Chunks → Embedding (provider-agnostic runtime)
    3. Chunks + Embeddings → pgvector (knowledge_embeddings table)

    - **content**: Raw text or markdown content to ingest
    - **document_id**: Unique identifier for the document
    - **domain_id**: Optional domain tag for the content
    - **title**: Optional document title
    """
    from app.core.config import settings

    if not settings.enable_text_ingestion:
        raise HTTPException(status_code=403, detail="Text ingestion is disabled")

    if not body.content or not body.content.strip():
        raise HTTPException(status_code=400, detail="Content must not be empty")

    max_bytes = settings.max_ingestion_size_mb * 1024 * 1024
    if len(body.content.encode("utf-8")) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Content too large. Maximum size is {settings.max_ingestion_size_mb}MB"
        )

    try:
        from app.services.chunking_service import get_semantic_chunker
        from app.repositories.dense_search_repository import get_dense_search_repository

        chunker = get_semantic_chunker()
        embeddings = get_embedding_backend()
        dense_repo = get_dense_search_repository()

        # Chunk the text
        page_metadata = {
            "document_id": body.document_id,
            "page_number": 1,
            "image_url": "",
            "source_type": "text",
        }
        chunks = await chunker.chunk_page_content(body.content, page_metadata)

        if not chunks:
            return TextIngestionResponse(
                status="empty",
                document_id=body.document_id,
                total_chunks=0,
                domain_id=body.domain_id,
                message="No chunks generated from content",
            )

        # Generate embeddings for all chunks
        chunk_texts = [c.content for c in chunks]
        chunk_embeddings = await embeddings.aembed_documents(chunk_texts)

        # Store in database
        stored = 0
        for i, (chunk, emb) in enumerate(zip(chunks, chunk_embeddings)):
            node_id = f"{body.document_id}_chunk_{i}"
            metadata = chunk.metadata or {}
            if body.title:
                metadata["title"] = body.title
            if body.domain_id:
                metadata["domain_id"] = body.domain_id

            success = await dense_repo.store_document_chunk(
                node_id=node_id,
                content=chunk.content,
                embedding=emb,
                document_id=body.document_id,
                page_number=chunk.metadata.get("page_number", 1) if chunk.metadata else 1,
                chunk_index=i,
                content_type=chunk.content_type,
                confidence_score=chunk.confidence_score,
                image_url="",
                metadata=metadata,
                organization_id=body.organization_id,
                bounding_boxes=chunk.metadata.get("bounding_boxes") if chunk.metadata else None,
            )
            if success:
                stored += 1

        logger.info(
            "Text ingestion completed: %d/%d chunks stored for document %s",
            stored, len(chunks), body.document_id,
        )

        return TextIngestionResponse(
            status="completed" if stored == len(chunks) else "partial",
            document_id=body.document_id,
            total_chunks=stored,
            domain_id=body.domain_id,
            message=f"Stored {stored}/{len(chunks)} chunks",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Text ingestion failed: %s", e)
        raise HTTPException(status_code=500, detail="Text ingestion failed")
