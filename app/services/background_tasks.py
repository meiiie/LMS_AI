"""
Background Tasks - Async Task Management for Chat Processing

Extracted from chat_service.py as part of Clean Architecture refactoring.
Centralizes all background task logic for chat processing.

**Pattern:** Task Runner Service
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure
"""

import logging
from typing import Callable, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class BackgroundTaskRunner:
    """
    Manages background tasks for chat processing.
    
    Responsibilities:
    - Save messages to chat history
    - Store semantic memory interactions
    - Update learning profile stats
    - Memory summarization
    
    **Pattern:** Task Runner with lazy initialization
    """
    
    def __init__(
        self,
        chat_history=None,
        semantic_memory=None,
        memory_summarizer=None,
        profile_repo=None
    ):
        """
        Initialize with optional dependencies (lazy loaded).
        
        Args:
            chat_history: ChatHistoryRepository
            semantic_memory: SemanticMemoryEngine
            memory_summarizer: MemorySummarizer
            profile_repo: LearningProfileRepository
        """
        self._chat_history = chat_history
        self._semantic_memory = semantic_memory
        self._memory_summarizer = memory_summarizer
        self._profile_repo = profile_repo
        
        logger.info("BackgroundTaskRunner initialized")
    
    def schedule_all(
        self,
        background_save: Callable,
        user_id: str,
        session_id: UUID,
        message: str,
        response: str
    ) -> None:
        """
        Schedule all background tasks after response is sent.
        
        Args:
            background_save: FastAPI BackgroundTasks.add_task
            user_id: User identifier
            session_id: Session UUID
            message: User's message
            response: AI's response
        """
        # Task 1: Save messages to chat history
        if self._chat_history and self._chat_history.is_available():
            background_save(
                self._save_messages,
                session_id, message, response
            )
        
        # Task 2: Store semantic memory interaction
        if self._semantic_memory and self._semantic_memory.is_available():
            background_save(
                self._store_semantic_interaction,
                user_id, message, response, str(session_id)
            )
        
        # Task 3: Summarize memory if needed
        if self._memory_summarizer:
            background_save(
                self._summarize_memory,
                str(session_id), message, response
            )
        
        # Task 4: Update learning profile stats
        if self._profile_repo and self._profile_repo.is_available():
            background_save(
                self._update_profile_stats,
                user_id
            )
    
    def save_message(
        self,
        background_save: Callable,
        session_id: UUID,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        is_blocked: bool = False,
        block_reason: Optional[str] = None
    ) -> None:
        """
        Save a single message to chat history (background).
        
        Args:
            background_save: FastAPI BackgroundTasks.add_task
            session_id: Session UUID
            role: 'user' or 'assistant'
            content: Message content
            user_id: Optional user ID for blocked message logging
            is_blocked: Whether message was blocked
            block_reason: Reason for blocking
        """
        if self._chat_history and self._chat_history.is_available():
            if is_blocked:
                self._chat_history.save_message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    user_id=user_id,
                    is_blocked=True,
                    block_reason=block_reason
                )
            else:
                background_save(
                    self._chat_history.save_message,
                    session_id, role, content
                )
    
    # =========================================================================
    # PRIVATE TASK IMPLEMENTATIONS
    # =========================================================================
    
    def _save_messages(
        self,
        session_id: UUID,
        user_message: str,
        ai_response: str
    ) -> None:
        """Save user and assistant messages to chat history."""
        try:
            self._chat_history.save_message(session_id, "user", user_message)
            self._chat_history.save_message(session_id, "assistant", ai_response)
            logger.debug(f"Background saved messages to session {session_id}")
        except Exception as e:
            logger.error(f"Failed to save messages in background: {e}")
    
    async def _store_semantic_interaction(
        self,
        user_id: str,
        message: str,
        response: str,
        session_id: str
    ) -> None:
        """
        Store interaction in Semantic Memory v0.5.
        
        **Spec:** CHỈ THỊ KỸ THUẬT SỐ 06 + CHỈ THỊ 23 CẢI TIẾN
        
        v0.5 Update: Uses Insight Engine for behavioral insight extraction.
        """
        try:
            # Get conversation history for context
            conversation_history = []
            if self._chat_history and self._chat_history.is_available():
                # Need to get session_id as UUID
                from uuid import UUID as UUIDType
                try:
                    session_uuid = UUIDType(session_id)
                    recent_messages = self._chat_history.get_recent_messages(session_uuid)
                    conversation_history = [msg.content for msg in recent_messages[-5:]]
                except ValueError:
                    pass
            
            # Extract behavioral insights (CHỈ THỊ 23 CẢI TIẾN)
            insights = await self._semantic_memory.extract_and_store_insights(
                user_id=user_id,
                message=message,
                conversation_history=conversation_history,
                session_id=session_id
            )
            
            if insights:
                logger.info(f"[INSIGHT ENGINE] Extracted {len(insights)} behavioral insights for user {user_id}")
            
            # Store interaction for message history (legacy compatibility)
            await self._semantic_memory.store_interaction(
                user_id=user_id,
                message=message,
                response=response,
                session_id=session_id,
                extract_facts=True
            )
            
            # Check and summarize if needed
            await self._semantic_memory.check_and_summarize(
                user_id=user_id,
                session_id=session_id
            )
            
            logger.debug(f"Background stored semantic interaction for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store semantic interaction: {e}")
    
    async def _summarize_memory(
        self,
        session_id: str,
        message: str,
        response: str
    ) -> None:
        """
        Summarize conversation memory if needed.
        
        CHỈ THỊ KỸ THUẬT SỐ 17: Memory Summarizer Integration
        """
        try:
            await self._memory_summarizer.add_message_async(session_id, "user", message)
            await self._memory_summarizer.add_message_async(session_id, "assistant", response)
            
            logger.debug(f"Background added messages to MemorySummarizer for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to summarize memory: {e}")
    
    async def _update_profile_stats(self, user_id: str) -> None:
        """
        Update learning profile stats.
        
        **Spec:** CHỈ THỊ KỸ THUẬT SỐ 04
        """
        try:
            await self._profile_repo.increment_stats(user_id, messages=2)  # user + assistant
            logger.debug(f"Background updated profile stats for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to update profile stats in background: {e}")


# =============================================================================
# SINGLETON
# =============================================================================

_background_runner: Optional[BackgroundTaskRunner] = None


def get_background_runner(
    chat_history=None,
    semantic_memory=None,
    memory_summarizer=None,
    profile_repo=None
) -> BackgroundTaskRunner:
    """Get or create BackgroundTaskRunner singleton."""
    global _background_runner
    if _background_runner is None:
        _background_runner = BackgroundTaskRunner(
            chat_history=chat_history,
            semantic_memory=semantic_memory,
            memory_summarizer=memory_summarizer,
            profile_repo=profile_repo
        )
    return _background_runner


def init_background_runner(
    chat_history=None,
    semantic_memory=None,
    memory_summarizer=None,
    profile_repo=None
) -> BackgroundTaskRunner:
    """Initialize BackgroundTaskRunner with dependencies."""
    global _background_runner
    _background_runner = BackgroundTaskRunner(
        chat_history=chat_history,
        semantic_memory=semantic_memory,
        memory_summarizer=memory_summarizer,
        profile_repo=profile_repo
    )
    return _background_runner
