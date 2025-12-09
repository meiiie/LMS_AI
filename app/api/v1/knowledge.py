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

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Ingestion"])

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = ["application/pdf"]


def validate_admin_role(role: str) -> None:
    """
    Validate that the user has admin role.
    
    **Validates: Requirements 1.2, 6.4**
    """
    if role.lower() != "admin":
        logger.warning(f"Non-admin access attempt with role: {role}")
        raise HTTPException(
            status_code=403,
            detail="Permission denied. Only Admins can access this endpoint."
        )


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


@router.post("/ingest-multimodal", response_model=MultimodalIngestionResponse)
async def ingest_multimodal_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_id: str = Form(...),
    role: str = Form(...),
    resume: bool = Form(default=True),
    max_pages: Optional[int] = Form(default=None)
) -> MultimodalIngestionResponse:
    """
    Upload a PDF document for Multimodal RAG ingestion.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Vision-based Document Understanding
    
    Pipeline:
    1. PDF → Images (PyMuPDF - no external dependencies)
    2. Images → Supabase Storage (public URLs)
    3. Images → Gemini Vision (text extraction)
    4. Text → Semantic Chunking (maritime-specific patterns)
    5. Chunks + Embeddings + image_url → Neon Database
    
    - **file**: PDF file to upload (max 50MB)
    - **document_id**: Unique identifier for the document
    - **role**: User role (must be "admin")
    - **resume**: Resume from last successful page if interrupted (default: True)
    - **max_pages**: Maximum pages to process (optional, for testing)
    
    Returns ingestion result with page counts and errors.
    
    **Feature: multimodal-rag-vision, semantic-chunking**
    **Validates: Requirements 2.1, 7.1, 7.4**
    """
    # Validate admin role
    validate_admin_role(role)
    
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
        # Import multimodal ingestion service
        from app.services.multimodal_ingestion_service import get_ingestion_service
        
        service = get_ingestion_service()
        
        # Process document
        result = await service.ingest_pdf(
            pdf_path=tmp_path,
            document_id=document_id,
            resume=resume,
            max_pages=max_pages
        )
        
        logger.info(
            f"Multimodal ingestion completed: {result.successful_pages}/{result.total_pages} pages "
            f"({result.success_rate:.1f}%)"
        )
        
        return MultimodalIngestionResponse(
            status="completed" if result.failed_pages == 0 else "partial",
            document_id=result.document_id,
            total_pages=result.total_pages,
            successful_pages=result.successful_pages,
            failed_pages=result.failed_pages,
            success_rate=result.success_rate,
            errors=result.errors,
            message=f"Processed {result.successful_pages}/{result.total_pages} pages successfully"
        )
        
    except Exception as e:
        logger.error(f"Multimodal ingestion failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Multimodal ingestion failed: {str(e)}"
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
    warning: Optional[str] = None


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def get_statistics() -> KnowledgeStatsResponse:
    """
    Get knowledge base statistics from PostgreSQL.
    
    Returns total chunks, documents, content type breakdown, and average confidence.
    
    **Feature: semantic-chunking**
    """
    try:
        import asyncpg
        from app.core.config import settings
        
        db_url = settings.database_url or ""
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        db_url = db_url.replace("postgres://", "postgresql://")
        
        conn = await asyncpg.connect(db_url)
        try:
            # Get total chunks
            total_chunks = await conn.fetchval(
                "SELECT COUNT(*) FROM knowledge_embeddings"
            )
            
            # Get unique documents
            total_documents = await conn.fetchval(
                "SELECT COUNT(DISTINCT document_id) FROM knowledge_embeddings WHERE document_id IS NOT NULL"
            )
            
            # Get content type breakdown
            content_type_rows = await conn.fetch(
                """
                SELECT content_type, COUNT(*) as count 
                FROM knowledge_embeddings 
                WHERE content_type IS NOT NULL
                GROUP BY content_type
                """
            )
            content_types = {row['content_type']: row['count'] for row in content_type_rows}
            
            # Get average confidence
            avg_confidence = await conn.fetchval(
                "SELECT AVG(confidence_score) FROM knowledge_embeddings WHERE confidence_score IS NOT NULL"
            ) or 0.0
            
            return KnowledgeStatsResponse(
                total_chunks=total_chunks or 0,
                total_documents=total_documents or 0,
                content_types=content_types,
                avg_confidence=round(float(avg_confidence), 3),
                warning=None
            )
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return KnowledgeStatsResponse(
            total_chunks=0,
            total_documents=0,
            content_types={},
            avg_confidence=0.0,
            warning=f"Database connection failed: {str(e)[:100]}"
        )
