"""
SQLAlchemy database models for Maritime AI Service.

This module defines the database schema using SQLAlchemy ORM,
including tables for memory storage, learning profiles, and conversation sessions.

**Feature: maritime-ai-tutor**
**Validates: Requirements 3.5, 6.4**
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class MemoriStoreModel(Base):
    """
    SQLAlchemy model for memory storage.
    
    Stores user memories with vector embeddings for similarity search.
    
    **Validates: Requirements 3.5**
    """
    __tablename__ = "memori_store"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid4
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Note: Vector type requires pgvector extension
    # embedding = mapped_column(ARRAY(Float), nullable=True)
    entities: Mapped[dict] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now, 
        onupdate=_utc_now
    )


class LearningProfileModel(Base):
    """
    SQLAlchemy model for learning profiles.
    
    Tracks user learning progress, level, style, and weak topics.
    
    **Validates: Requirements 6.4**
    """
    __tablename__ = "learning_profile"
    
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True
    )
    current_level: Mapped[str] = mapped_column(
        String(20), 
        default="CADET",
        nullable=False
    )
    learning_style: Mapped[Optional[str]] = mapped_column(
        String(20), 
        nullable=True
    )
    weak_topics: Mapped[dict] = mapped_column(JSONB, default=list)
    completed_topics: Mapped[dict] = mapped_column(JSONB, default=list)
    assessment_history: Mapped[dict] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now, 
        onupdate=_utc_now
    )
    
    # Relationship to conversation sessions
    sessions: Mapped[list["ConversationSessionModel"]] = relationship(
        back_populates="user_profile"
    )


class ConversationSessionModel(Base):
    """
    SQLAlchemy model for conversation sessions.
    
    Tracks individual conversation sessions with users.
    
    **Validates: Requirements 3.5**
    """
    __tablename__ = "conversation_session"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("learning_profile.user_id"),
        nullable=False,
        index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), 
        nullable=True
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationship to learning profile
    user_profile: Mapped["LearningProfileModel"] = relationship(
        back_populates="sessions"
    )


# ============================================================================
# MEMORY LITE - Chat History Tables (Week 2)
# ============================================================================

class ChatSessionModel(Base):
    """
    SQLAlchemy model for chat sessions.
    
    Stores chat sessions for Memory Lite implementation.
    Each user can have multiple sessions.
    
    **Feature: maritime-ai-tutor, Week 2: Memory Lite**
    """
    __tablename__ = "chat_sessions"
    
    session_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        index=True
    )
    user_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now
    )
    
    # Relationship to messages
    messages: Mapped[list["ChatMessageModel"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageModel.created_at"
    )


class ChatMessageModel(Base):
    """
    SQLAlchemy model for chat messages.
    
    Stores individual messages in a chat session.
    Used for Sliding Window context retrieval.
    
    **Feature: maritime-ai-tutor, Week 2: Memory Lite**
    **CHỈ THỊ SỐ 22: Memory Isolation - is_blocked flag**
    """
    __tablename__ = "chat_messages"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(50), 
        nullable=False  # 'user' or 'assistant'
    )
    content: Mapped[str] = mapped_column(
        Text, 
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=_utc_now,
        index=True
    )
    
    # CHỈ THỊ SỐ 22: Memory Isolation - Blocked message tracking
    is_blocked: Mapped[bool] = mapped_column(
        default=False,
        index=True
    )
    block_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    
    # Relationship to session
    session: Mapped["ChatSessionModel"] = relationship(
        back_populates="messages"
    )


# Database connection utilities
class DatabaseManager:
    """
    Manages database connections and sessions.
    
    Provides async context manager for database operations.
    """
    
    def __init__(self, database_url: str):
        """
        Initialize database manager.
        
        Args:
            database_url: PostgreSQL connection URL
        """
        self._database_url = database_url
        self._engine = None
    
    def get_engine(self):
        """Get or create database engine."""
        if self._engine is None:
            self._engine = create_engine(
                self._database_url,
                echo=False,
                pool_pre_ping=True
            )
        return self._engine
    
    def create_tables(self):
        """Create all tables in the database."""
        engine = self.get_engine()
        Base.metadata.create_all(engine)
    
    def drop_tables(self):
        """Drop all tables in the database."""
        engine = self.get_engine()
        Base.metadata.drop_all(engine)
