"""
ARCHIVED: Legacy Ingestion Job Model for Neo4j Knowledge Ingestion

This file has been archived as part of the sparse-search-migration.
Job tracking for the new multimodal pipeline is handled differently.

Original location: app/models/ingestion_job.py
Archived date: 2025-12-09
Reason: Neo4j-based ingestion replaced by MultimodalIngestionService

See: .kiro/specs/sparse-search-migration/design.md for migration details.
"""

# Original content below for reference
# =====================================

"""
Ingestion Job Model for Knowledge Ingestion feature.

Tracks PDF upload and processing jobs for Neo4j Knowledge Graph.

Feature: knowledge-ingestion
Requirements: 5.1, 5.2, 5.3
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Ingestion job status enum."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# NOTE: SQLAlchemy model removed as table is no longer used
# The new multimodal pipeline uses IngestionResult dataclass instead

class IngestionJobResponse(BaseModel):
    """Schema for ingestion job API response (archived)."""
    id: UUID
    filename: str
    category: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    nodes_created: int = 0
    error_message: Optional[str] = None
    uploaded_by: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
