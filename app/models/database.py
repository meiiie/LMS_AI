"""
SQLAlchemy database models for Maritime AI Service.

This module defines the database schema using SQLAlchemy ORM
for chat sessions and messages.

**Feature: maritime-ai-tutor, Memory Lite**
**Validates: Requirements 3.5**
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ============================================================================
# MEMORY LITE - Chat History Tables
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
