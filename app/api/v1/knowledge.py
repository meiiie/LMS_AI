"""
Knowledge Ingestion API Endpoints.

Provides endpoints for Admin to upload PDF documents into Neo4j Knowledge Graph.

Feature: knowledge-ingestion
Requirements: 1.1, 1.2, 1.3, 1.4, 5.1, 6.1, 6.2, 6.3
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.ingestion_service import get_ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Ingestion"])

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = ["application/pdf"]


# Response Models
class IngestionResponse(BaseModel):
    """Response for document ingestion request."""
    status: str
    job_id: str
    message: str


class JobStatusResponse(BaseModel):
    """Response for job status query."""
    job_id: str
    status: str
    progress: int
    nodes_created: int
    error_message: Optional[str] = None
    filename: str
    category: str


class DocumentInfo(BaseModel):
    """Document information."""
    id: str
    filename: str
    category: str
    nodes_count: int
    uploaded_by: str


class DocumentListResponse(BaseModel):
    """Response for document list."""
    documents: list
    page: int
    limit: int


class KnowledgeStatsResponse(BaseModel):
    """Response for knowledge statistics."""
    total_documents: int
    total_nodes: int
    categories: dict
    recent_uploads: list


class DeleteResponse(BaseModel):
    """Response for document deletion."""
    status: str
    document_id: str
    nodes_deleted: int


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


@router.post("/ingest", response_model=IngestionResponse)
async def ingest_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(...),
    role: str = Form(...)
) -> IngestionResponse:
    """
    Upload a PDF document for ingestion into Knowledge Graph.
    
    - **file**: PDF file to upload (max 50MB)
    - **category**: Knowledge category (e.g., COLREGs, SOLAS, MARPOL)
    - **role**: User role (must be "admin")
    
    Returns a job_id for tracking the ingestion progress.
    
    **Feature: knowledge-ingestion**
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
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
    
    # Create ingestion job
    service = get_ingestion_service()
    job_id = await service.create_ingestion_job(
        filename=file.filename,
        category=category,
        uploaded_by="admin",  # In production, get from auth token
        file_content=content
    )
    
    # Queue background processing
    background_tasks.add_task(service.process_document, job_id)
    
    logger.info(f"Ingestion job created: {job_id} for {file.filename}")
    
    return IngestionResponse(
        status="accepted",
        job_id=job_id,
        message=f"Document '{file.filename}' accepted for processing."
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Get the status of an ingestion job.
    
    - **job_id**: The job ID returned from /ingest endpoint
    
    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """
    service = get_ingestion_service()
    job = await service.get_job_status(job_id)
    
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found: {job_id}"
        )
    
    return JobStatusResponse(
        job_id=job["id"],
        status=job["status"],
        progress=job["progress"],
        nodes_created=job["nodes_created"],
        error_message=job.get("error_message"),
        filename=job["filename"],
        category=job["category"]
    )


@router.get("/list", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    limit: int = 20
) -> DocumentListResponse:
    """
    Get paginated list of uploaded documents.
    
    - **page**: Page number (default: 1)
    - **limit**: Items per page (default: 20, max: 100)
    
    Returns empty list if no documents exist or on database error.
    
    **Validates: Requirements 6.1**
    **Feature: tech-debt-cleanup**
    """
    if limit > 100:
        limit = 100
    
    try:
        service = get_ingestion_service()
        documents = await service.list_documents(page, limit)
        
        return DocumentListResponse(
            documents=documents,
            page=page,
            limit=limit
        )
    except Exception as e:
        logger.error(f"List documents error: {e}")
        # Return empty results instead of 500 error
        return DocumentListResponse(
            documents=[],
            page=page,
            limit=limit
        )


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def get_statistics() -> KnowledgeStatsResponse:
    """
    Get knowledge base statistics.
    
    Returns total documents, nodes, category breakdown, and recent uploads.
    Returns default empty stats if database is unavailable.
    
    **Validates: Requirements 6.2**
    **Feature: tech-debt-cleanup**
    """
    try:
        service = get_ingestion_service()
        stats = await service.get_stats()
        
        return KnowledgeStatsResponse(
            total_documents=stats.get("total_documents", 0),
            total_nodes=stats.get("total_nodes", 0),
            categories=stats.get("categories", {}),
            recent_uploads=stats.get("recent_uploads", [])
        )
    except Exception as e:
        logger.error(f"Stats error: {e}")
        # Return empty stats instead of 500 error
        return KnowledgeStatsResponse(
            total_documents=0,
            total_nodes=0,
            categories={},
            recent_uploads=[]
        )


class ReingestEmbeddingsResponse(BaseModel):
    """Response for re-ingest embeddings."""
    status: str
    nodes_processed: int
    embeddings_created: int
    message: str


@router.post("/reingest-embeddings", response_model=ReingestEmbeddingsResponse)
async def reingest_embeddings(
    background_tasks: BackgroundTasks,
    role: str = Form(default="admin")
) -> ReingestEmbeddingsResponse:
    """
    Re-ingest all Knowledge nodes and create embeddings for Dense Search.
    
    This endpoint:
    1. Fetches all Knowledge nodes from Neo4j
    2. Generates Gemini embeddings (768 dims)
    3. Stores embeddings in pgvector (Supabase)
    
    - **role**: User role (must be "admin")
    
    **Feature: hybrid-search**
    **Validates: Requirements 2.1, 6.1**
    """
    # Validate admin role
    validate_admin_role(role)
    
    try:
        from app.repositories.dense_search_repository import DenseSearchRepository
        from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        
        # Initialize components
        neo4j_repo = Neo4jKnowledgeRepository()
        dense_repo = DenseSearchRepository()
        embeddings = GeminiOptimizedEmbeddings()
        
        # Fetch all Knowledge nodes from Neo4j
        nodes = neo4j_repo.get_all_knowledge_nodes()
        logger.info(f"Found {len(nodes)} Knowledge nodes to process")
        
        if not nodes:
            return ReingestEmbeddingsResponse(
                status="completed",
                nodes_processed=0,
                embeddings_created=0,
                message="No Knowledge nodes found in Neo4j"
            )
        
        # Process each node
        success_count = 0
        for node in nodes:
            try:
                # Generate embedding
                text = f"{node.get('title', '')}\n{node.get('content', '')}"
                embedding = embeddings.embed_documents([text])[0]
                
                # Store in pgvector
                await dense_repo.upsert_embedding(
                    node_id=node['id'],
                    content=text[:500],
                    embedding=embedding
                )
                success_count += 1
                
            except Exception as e:
                logger.error(f"Failed to process node {node.get('id')}: {e}")
        
        logger.info(f"Re-ingest completed: {success_count}/{len(nodes)} embeddings created")
        
        return ReingestEmbeddingsResponse(
            status="completed",
            nodes_processed=len(nodes),
            embeddings_created=success_count,
            message=f"Successfully created {success_count}/{len(nodes)} embeddings"
        )
        
    except Exception as e:
        logger.error(f"Re-ingest failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Re-ingest failed: {str(e)}"
        )


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: str,
    role: str = Form(...)
) -> DeleteResponse:
    """
    Delete a document and all its associated knowledge nodes.
    
    - **document_id**: The document ID to delete
    - **role**: User role (must be "admin")
    
    **Validates: Requirements 6.3, 6.4**
    """
    # Validate admin role
    validate_admin_role(role)
    
    service = get_ingestion_service()
    
    try:
        nodes_deleted = await service.delete_document(document_id)
        
        return DeleteResponse(
            status="deleted",
            document_id=document_id,
            nodes_deleted=nodes_deleted
        )
    except Exception as e:
        logger.error(f"Failed to delete document {document_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document: {str(e)}"
        )
