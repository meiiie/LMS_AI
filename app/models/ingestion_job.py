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
from sqlalchemy import Column, String, Integer, Text, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.models.database import Base


class JobStatus(str, Enum):
    """Ingestion job status enum."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJob(Base):
    """SQLAlchemy model for ingestion_jobs table."""
    
    __tablename__ = "ingestion_jobs"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    filename = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    status = Column(String(20), default=JobStatus.PENDING.value)
    progress = Column(Integer, default=0)
    nodes_created = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    content_hash = Column(String(64), nullable=True)
    uploaded_by = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="check_status"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="check_progress"),
    )


# Pydantic schemas for API
class IngestionJobCreate(BaseModel):
    """Schema for creating a new ingestion job."""
    filename: str
    category: str
    uploaded_by: str
    file_path: Optional[str] = None
    content_hash: Optional[str] = None


class IngestionJobResponse(BaseModel):
    """Schema for ingestion job API response."""
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


class IngestionJobUpdate(BaseModel):
    """Schema for updating ingestion job status."""
    status: Optional[JobStatus] = None
    progress: Optional[int] = Field(None, ge=0, le=100)
    nodes_created: Optional[int] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
