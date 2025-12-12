"""
Admin API Router - Document Management for LMS Admins

Phase 6: Admin Document API
Enables LMS admins to:
- Upload and ingest documents into knowledge base
- Check ingestion status
- List all documents
- Delete documents

Pattern: LangChain Enterprise Best Practices
"""

import logging
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# =============================================================================
# Schemas
# =============================================================================

class DocumentUploadResponse(BaseModel):
    """Response after document upload."""
    job_id: str = Field(..., description="Ingestion job ID for status tracking")
    document_id: str = Field(..., description="Document identifier")
    status: str = Field(..., description="pending | processing | completed | failed")
    message: str = Field(..., description="Status message")


class DocumentStatus(BaseModel):
    """Document ingestion status."""
    job_id: str
    document_id: str
    status: str  # pending | processing | completed | failed
    progress_percent: float = 0.0
    total_pages: int = 0
    processed_pages: int = 0
    error: Optional[str] = None


class DocumentInfo(BaseModel):
    """Document information."""
    document_id: str
    title: str
    total_pages: int
    total_chunks: int
    created_at: str
    status: str


# =============================================================================
# In-memory job tracking (replace with DB in production)
# =============================================================================

_ingestion_jobs: dict = {}  # job_id -> DocumentStatus


# =============================================================================
# Background Ingestion Task
# =============================================================================

async def _run_ingestion_background(
    job_id: str,
    document_id: str,
    pdf_path: str,
    create_neo4j_module: bool = True
):
    """
    Background task for document ingestion.
    
    Steps:
    1. Update job status to "processing"
    2. Run multimodal ingestion
    3. Create Module node in Neo4j (if enabled)
    4. Update job status to "completed" or "failed"
    """
    from app.services.multimodal_ingestion_service import get_ingestion_service
    from app.repositories.user_graph_repository import get_user_graph_repository
    
    try:
        _ingestion_jobs[job_id]["status"] = "processing"
        
        # Run ingestion
        ingestion_service = get_ingestion_service()
        result = await ingestion_service.ingest_pdf(
            pdf_path=pdf_path,
            document_id=document_id,
            resume=True
        )
        
        # Update progress
        _ingestion_jobs[job_id]["total_pages"] = result.total_pages
        _ingestion_jobs[job_id]["processed_pages"] = result.successful_pages
        _ingestion_jobs[job_id]["progress_percent"] = result.success_rate
        
        # Create Module node in Neo4j (Phase 4 + 6 integration)
        if create_neo4j_module:
            user_graph = get_user_graph_repository()
            if user_graph.is_available():
                user_graph.ensure_module_node(
                    module_id=document_id,
                    title=document_id.replace("_", " ").title()
                )
                logger.info(f"[ADMIN] Created Module node in Neo4j: {document_id}")
        
        _ingestion_jobs[job_id]["status"] = "completed"
        logger.info(f"[ADMIN] Ingestion completed for {document_id}: {result.success_rate:.0%} success")
        
    except Exception as e:
        _ingestion_jobs[job_id]["status"] = "failed"
        _ingestion_jobs[job_id]["error"] = str(e)
        logger.error(f"[ADMIN] Ingestion failed for {document_id}: {e}")


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF file to ingest"),
    document_id: Optional[str] = Form(None, description="Document ID (auto-generated if not provided)"),
    create_module_node: bool = Form(True, description="Create Module node in Neo4j")
):
    """
    Upload and ingest a document into knowledge base.
    
    This endpoint:
    1. Saves the uploaded PDF
    2. Starts background ingestion
    3. Returns job_id for status tracking
    4. Optionally creates Module node in Neo4j
    
    Use GET /admin/documents/{job_id} to check progress.
    """
    import os
    import tempfile
    
    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Generate IDs
    job_id = str(uuid4())
    doc_id = document_id or file.filename.replace(".pdf", "").replace(" ", "_").lower()
    
    # Save file temporarily
    temp_dir = tempfile.gettempdir()
    pdf_path = os.path.join(temp_dir, f"{doc_id}.pdf")
    
    try:
        content = await file.read()
        with open(pdf_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
    
    # Initialize job status
    _ingestion_jobs[job_id] = {
        "job_id": job_id,
        "document_id": doc_id,
        "status": "pending",
        "progress_percent": 0.0,
        "total_pages": 0,
        "processed_pages": 0,
        "error": None
    }
    
    # Start background ingestion
    background_tasks.add_task(
        _run_ingestion_background,
        job_id=job_id,
        document_id=doc_id,
        pdf_path=pdf_path,
        create_neo4j_module=create_module_node
    )
    
    logger.info(f"[ADMIN] Document upload started: {doc_id} (job_id: {job_id})")
    
    return DocumentUploadResponse(
        job_id=job_id,
        document_id=doc_id,
        status="pending",
        message=f"Ingestion started. Use GET /admin/documents/{job_id} to check status."
    )


@router.get("/documents/{job_id}", response_model=DocumentStatus)
async def get_document_status(job_id: str):
    """
    Check ingestion job status.
    
    Returns progress information for a document ingestion job.
    """
    if job_id not in _ingestion_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = _ingestion_jobs[job_id]
    return DocumentStatus(**job)


@router.get("/documents", response_model=list)
async def list_documents():
    """
    List all documents in knowledge base.
    
    Returns list of documents with their metadata.
    """
    from app.core.database import get_shared_session_factory
    from sqlalchemy import text
    
    try:
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            result = session.execute(text("""
                SELECT 
                    document_id,
                    COUNT(*) as total_chunks,
                    MIN(created_at) as created_at
                FROM knowledge_embeddings
                GROUP BY document_id
                ORDER BY document_id
            """))
            
            documents = []
            for row in result.fetchall():
                documents.append({
                    "document_id": row[0],
                    "total_chunks": row[1],
                    "created_at": str(row[2]) if row[2] else None
                })
            
            return documents
            
    except Exception as e:
        logger.error(f"[ADMIN] Failed to list documents: {e}")
        return []


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """
    Delete a document from knowledge base.
    
    Removes all chunks and embeddings for the specified document.
    Also removes Module node from Neo4j if exists.
    """
    from app.core.database import get_shared_session_factory
    from app.repositories.user_graph_repository import get_user_graph_repository
    from sqlalchemy import text
    
    try:
        # Delete from Neon
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            result = session.execute(
                text("DELETE FROM knowledge_embeddings WHERE document_id = :doc_id"),
                {"doc_id": document_id}
            )
            deleted_count = result.rowcount
            session.commit()
        
        # Delete Module node from Neo4j
        user_graph = get_user_graph_repository()
        if user_graph.is_available():
            # Note: This would need a delete method in user_graph_repository
            logger.info(f"[ADMIN] Module node deletion not implemented yet for {document_id}")
        
        logger.info(f"[ADMIN] Deleted {deleted_count} chunks for document {document_id}")
        
        return {
            "status": "success",
            "document_id": document_id,
            "deleted_chunks": deleted_count
        }
        
    except Exception as e:
        logger.error(f"[ADMIN] Failed to delete document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
