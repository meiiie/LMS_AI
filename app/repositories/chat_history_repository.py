"""
Chat History Repository - Memory Lite Implementation.

This module provides CRUD operations for chat sessions and messages,
implementing the Sliding Window strategy for context retrieval.

**Feature: maritime-ai-tutor, Week 2: Memory Lite**
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import create_engine, desc, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.database import ChatMessageModel, ChatSessionModel

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """Chat message data class."""
    id: UUID
    session_id: UUID
    role: str  # 'user' or 'assistant'
    content: str
    created_at: datetime


@dataclass
class ChatSession:
    """Chat session data class."""
    session_id: UUID
    user_id: str
    user_name: Optional[str]
    created_at: datetime
    messages: List[ChatMessage]


class ChatHistoryRepository:
    """
    Repository for chat history operations.
    
    Implements Memory Lite with Sliding Window strategy.
    
    **Feature: maritime-ai-tutor, Week 2: Memory Lite**
    """
    
    # Sliding window size - number of recent messages to retrieve
    WINDOW_SIZE = 10
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize repository with database connection (supports local Docker and Supabase)."""
        # Use postgres_url_sync for synchronous operations
        self._database_url = database_url or settings.postgres_url_sync
        self._engine = None
        self._session_factory = None
        self._available = False
        self._init_connection()
    
    def _init_connection(self):
        """Initialize database connection."""
        try:
            self._engine = create_engine(
                self._database_url,
                echo=False,
                pool_pre_ping=True
            )
            self._session_factory = sessionmaker(bind=self._engine)
            
            # Test connection
            with self._session_factory() as session:
                session.execute(select(1))
            
            self._available = True
            logger.info("Chat history repository connected to PostgreSQL")
        except Exception as e:
            logger.warning(f"Chat history repository connection failed: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if repository is available."""
        return self._available
    
    def ensure_tables(self):
        """Create tables if they don't exist."""
        if not self._available:
            return
        
        try:
            from app.models.database import Base
            Base.metadata.create_all(self._engine)
            logger.info("Chat history tables created/verified")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")

    def get_or_create_session(self, user_id: str) -> Optional[ChatSession]:
        """
        Get existing session or create new one for user.
        
        Args:
            user_id: User identifier
            
        Returns:
            ChatSession or None if unavailable
        """
        if not self._available:
            return None
        
        try:
            with self._session_factory() as session:
                # Find existing session for user
                stmt = select(ChatSessionModel).where(
                    ChatSessionModel.user_id == user_id
                ).order_by(desc(ChatSessionModel.created_at)).limit(1)
                
                result = session.execute(stmt).scalar_one_or_none()
                
                if result:
                    return ChatSession(
                        session_id=result.session_id,
                        user_id=result.user_id,
                        user_name=result.user_name,
                        created_at=result.created_at,
                        messages=[]
                    )
                
                # Create new session
                new_session = ChatSessionModel(
                    session_id=uuid4(),
                    user_id=user_id
                )
                session.add(new_session)
                session.commit()
                
                logger.info(f"Created new chat session for user {user_id}")
                
                return ChatSession(
                    session_id=new_session.session_id,
                    user_id=new_session.user_id,
                    user_name=new_session.user_name,
                    created_at=new_session.created_at,
                    messages=[]
                )
        except Exception as e:
            logger.error(f"Failed to get/create session: {e}")
            return None

    def save_message(
        self, 
        session_id: UUID, 
        role: str, 
        content: str
    ) -> Optional[ChatMessage]:
        """
        Save a message to the chat history.
        
        Args:
            session_id: Session UUID
            role: 'user' or 'assistant'
            content: Message content
            
        Returns:
            ChatMessage or None if failed
        """
        if not self._available:
            return None
        
        try:
            with self._session_factory() as session:
                message = ChatMessageModel(
                    id=uuid4(),
                    session_id=session_id,
                    role=role,
                    content=content
                )
                session.add(message)
                session.commit()
                
                return ChatMessage(
                    id=message.id,
                    session_id=message.session_id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at
                )
        except Exception as e:
            logger.error(f"Failed to save message: {e}")
            return None
    
    def get_recent_messages(
        self, 
        session_id: UUID, 
        limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """
        Get recent messages using Sliding Window strategy.
        
        Args:
            session_id: Session UUID
            limit: Number of messages (default: WINDOW_SIZE)
            
        Returns:
            List of recent messages, oldest first
        """
        if not self._available:
            return []
        
        limit = limit or self.WINDOW_SIZE

        try:
            with self._session_factory() as session:
                # Get recent messages, ordered by created_at DESC, then reverse
                stmt = select(ChatMessageModel).where(
                    ChatMessageModel.session_id == session_id
                ).order_by(desc(ChatMessageModel.created_at)).limit(limit)
                
                results = session.execute(stmt).scalars().all()
                
                # Reverse to get chronological order (oldest first)
                messages = [
                    ChatMessage(
                        id=msg.id,
                        session_id=msg.session_id,
                        role=msg.role,
                        content=msg.content,
                        created_at=msg.created_at
                    )
                    for msg in reversed(results)
                ]
                
                return messages
        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []
    
    def update_user_name(self, session_id: UUID, user_name: str) -> bool:
        """
        Update user name for a session.
        
        Args:
            session_id: Session UUID
            user_name: User's name
            
        Returns:
            True if successful
        """
        if not self._available:
            return False
        
        try:
            with self._session_factory() as session:
                stmt = select(ChatSessionModel).where(
                    ChatSessionModel.session_id == session_id
                )
                chat_session = session.execute(stmt).scalar_one_or_none()
                
                if chat_session:
                    chat_session.user_name = user_name
                    session.commit()
                    logger.info(f"Updated user name to '{user_name}'")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update user name: {e}")
            return False

    def get_user_name(self, session_id: UUID) -> Optional[str]:
        """Get user name from session."""
        if not self._available:
            return None
        
        try:
            with self._session_factory() as session:
                stmt = select(ChatSessionModel.user_name).where(
                    ChatSessionModel.session_id == session_id
                )
                return session.execute(stmt).scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get user name: {e}")
            return None
    
    def format_history_for_prompt(
        self, 
        messages: List[ChatMessage]
    ) -> str:
        """
        Format chat history for LLM prompt.
        
        Args:
            messages: List of chat messages
            
        Returns:
            Formatted string for prompt injection
        """
        if not messages:
            return ""
        
        lines = []
        for msg in messages:
            role_label = "User" if msg.role == "user" else "AI"
            # Truncate long messages
            content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            lines.append(f"{role_label}: {content}")
        
        return "\n".join(lines)


# Singleton instance
_chat_history_repo: Optional[ChatHistoryRepository] = None


def get_chat_history_repository() -> ChatHistoryRepository:
    """Get or create ChatHistoryRepository singleton."""
    global _chat_history_repo
    if _chat_history_repo is None:
        _chat_history_repo = ChatHistoryRepository()
    return _chat_history_repo
