"""
Ingestion Service for Knowledge Ingestion feature.

Handles PDF upload, processing, and Neo4j storage.

Feature: knowledge-ingestion
Requirements: 1.1, 4.1, 5.1, 5.2, 6.1, 6.2, 6.3
"""

import logging
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from app.engine.pdf_processor import PDFProcessor
from app.models.ingestion_job import JobStatus
from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository

logger = logging.getLogger(__name__)


# In-memory job storage (for MVP - can be replaced with PostgreSQL later)
_jobs: Dict[str, dict] = {}


class IngestionService:
    """
    Service for managing document ingestion into Knowledge Graph.
    
    Handles the full pipeline: Upload → Extract → Chunk → Store
    
    **Feature: knowledge-ingestion**
    **Validates: Requirements 1.1, 4.1, 5.1, 5.2, 6.1, 6.2, 6.3**
    """
    
    def __init__(self, knowledge_repo: Optional[Neo4jKnowledgeRepository] = None):
        """Initialize ingestion service."""
        self._pdf_processor = PDFProcessor()
        self._knowledge_repo = knowledge_repo
    
    def _get_repo(self) -> Neo4jKnowledgeRepository:
        """Get or create knowledge repository."""
        if self._knowledge_repo is None:
            from app.engine.tools.rag_tool import get_knowledge_repository
            self._knowledge_repo = get_knowledge_repository()
        return self._knowledge_repo
    
    async def create_ingestion_job(
        self,
        filename: str,
        category: str,
        uploaded_by: str,
        file_content: bytes
    ) -> str:
        """
        Create a new ingestion job.
        
        Args:
            filename: Original filename
            category: Knowledge category (e.g., COLREGs, SOLAS)
            uploaded_by: Admin user ID
            file_content: PDF file content as bytes
            
        Returns:
            Job ID for tracking
            
        **Validates: Requirements 1.1, 5.1**
        """
        job_id = str(uuid4())
        content_hash = PDFProcessor.compute_hash(file_content)
        
        # Check for duplicate
        repo = self._get_repo()
        existing_doc = await repo.check_duplicate(content_hash)
        if existing_doc:
            logger.warning(f"Duplicate document detected: {existing_doc}")
            # Still create job but mark as duplicate
            _jobs[job_id] = {
                "id": job_id,
                "filename": filename,
                "category": category,
                "status": JobStatus.FAILED.value,
                "progress": 0,
                "nodes_created": 0,
                "error_message": f"Duplicate document. Already exists as: {existing_doc}",
                "content_hash": content_hash,
                "uploaded_by": uploaded_by,
                "created_at": datetime.utcnow(),
                "completed_at": datetime.utcnow()
            }
            return job_id
        
        # Save file temporarily
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{job_id}.pdf")
        
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        # Create job record
        _jobs[job_id] = {
            "id": job_id,
            "filename": filename,
            "category": category,
            "status": JobStatus.PENDING.value,
            "progress": 0,
            "nodes_created": 0,
            "error_message": None,
            "file_path": file_path,
            "content_hash": content_hash,
            "uploaded_by": uploaded_by,
            "created_at": datetime.utcnow(),
            "completed_at": None
        }
        
        logger.info(f"Created ingestion job: {job_id} for {filename}")
        return job_id
    
    async def process_document(self, job_id: str) -> None:
        """
        Process a document in the background.
        
        Pipeline: Extract → Chunk → Create Nodes
        
        **Validates: Requirements 2.1, 3.1, 4.1, 5.2, 7.1**
        """
        if job_id not in _jobs:
            logger.error(f"Job not found: {job_id}")
            return
        
        job = _jobs[job_id]
        
        # Skip if already processed or failed
        if job["status"] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
            return
        
        try:
            # Update status to processing
            job["status"] = JobStatus.PROCESSING.value
            job["progress"] = 10
            
            file_path = job["file_path"]
            if not file_path or not os.path.exists(file_path):
                raise FileNotFoundError(f"PDF file not found: {file_path}")
            
            # Step 1: Extract text (20%)
            logger.info(f"Extracting text from {job['filename']}")
            text = self._pdf_processor.extract_text(file_path)
            job["progress"] = 20
            
            if not text or len(text) < 100:
                raise ValueError("Extracted text is too short or empty")
            
            # Step 2: Chunk text (40%)
            logger.info(f"Chunking text ({len(text)} chars)")
            chunks = self._pdf_processor.chunk_text(text)
            job["progress"] = 40
            
            if not chunks:
                raise ValueError("No chunks created from document")
            
            # Step 3: Create document node in Neo4j (50%)
            repo = self._get_repo()
            document_id = str(uuid4())
            
            await repo.create_document(
                document_id=document_id,
                filename=job["filename"],
                category=job["category"],
                content_hash=job["content_hash"],
                uploaded_by=job["uploaded_by"]
            )
            job["progress"] = 50
            
            # Step 4: Create knowledge nodes (50-90%)
            nodes_created = 0
            total_chunks = len(chunks)
            
            for i, chunk in enumerate(chunks):
                try:
                    node_id = f"{document_id}_chunk_{chunk.index}"
                    title = self._pdf_processor.generate_title(chunk)
                    
                    success = await repo.create_knowledge_node(
                        node_id=node_id,
                        title=title,
                        content=chunk.content,
                        category=job["category"],
                        source=job["filename"],
                        document_id=document_id,
                        chunk_index=chunk.index
                    )
                    
                    if success:
                        nodes_created += 1
                    
                    # Update progress (50% to 90%)
                    progress = 50 + int((i + 1) / total_chunks * 40)
                    job["progress"] = progress
                    
                except Exception as e:
                    # Log error but continue with other chunks (partial failure resilience)
                    logger.error(f"Failed to create node for chunk {chunk.index}: {e}")
            
            # Step 5: Complete (100%)
            job["status"] = JobStatus.COMPLETED.value
            job["progress"] = 100
            job["nodes_created"] = nodes_created
            job["completed_at"] = datetime.utcnow()
            
            logger.info(f"Job {job_id} completed: {nodes_created}/{total_chunks} nodes created")
            
            # Cleanup temp file
            if os.path.exists(file_path):
                os.remove(file_path)
                
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            job["status"] = JobStatus.FAILED.value
            job["error_message"] = str(e)
            job["completed_at"] = datetime.utcnow()
    
    async def get_job_status(self, job_id: str) -> Optional[dict]:
        """
        Get the status of an ingestion job.
        
        **Validates: Requirements 5.1, 5.2, 5.3**
        """
        return _jobs.get(job_id)
    
    async def list_documents(
        self,
        page: int = 1,
        limit: int = 20
    ) -> List[dict]:
        """
        Get paginated list of uploaded documents from Neo4j.
        
        **Validates: Requirements 6.1**
        """
        repo = self._get_repo()
        return await repo.get_document_list(page, limit)
    
    async def delete_document(self, document_id: str) -> int:
        """
        Delete a document and all its knowledge nodes.
        
        **Validates: Requirements 6.3**
        """
        repo = self._get_repo()
        return await repo.delete_document_nodes(document_id)
    
    async def get_stats(self) -> dict:
        """
        Get knowledge base statistics.
        
        **Validates: Requirements 6.2**
        """
        repo = self._get_repo()
        return await repo.get_extended_stats()


# Singleton instance
_ingestion_service: Optional[IngestionService] = None


def get_ingestion_service() -> IngestionService:
    """Get or create ingestion service singleton."""
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service
