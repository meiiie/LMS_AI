"""
Session Manager - Session and State Management

Extracted from chat_service.py as part of Clean Architecture refactoring.
Handles session lifecycle and anti-repetition state tracking.

**Pattern:** Singleton Service
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from app.repositories.chat_history_repository import (
    ChatHistoryRepository,
    get_chat_history_repository
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SessionState:
    """
    Track session state for anti-repetition and personalization.
    
    **Validates: Requirements 3.1, 3.2, 2.3, 6.1, 6.2, 6.3**
    """
    session_id: UUID
    recent_phrases: List[str] = field(default_factory=list)
    name_usage_count: int = 0
    total_responses: int = 0
    is_first_message: bool = True
    pronoun_style: Optional[dict] = None  # CHỈ THỊ SỐ 20: Detected pronoun style
    
    def add_phrase(self, phrase: str) -> None:
        """Track a phrase that was used."""
        self.recent_phrases.append(phrase)
        if len(self.recent_phrases) > 5:  # Keep last 5
            self.recent_phrases.pop(0)
    
    def increment_response(self, used_name: bool = False) -> None:
        """Increment response counter."""
        self.total_responses += 1
        if used_name:
            self.name_usage_count += 1
        self.is_first_message = False
    
    def should_use_name(self) -> bool:
        """Check if name should be used (20-30% frequency)."""
        if self.total_responses == 0:
            return True  # First response can use name
        ratio = self.name_usage_count / self.total_responses
        return ratio < 0.25  # Target 25%
    
    def update_pronoun_style(self, style: Optional[dict]) -> None:
        """
        Update pronoun style if detected.
        
        CHỈ THỊ SỐ 20: Pronoun Adaptation
        **Validates: Requirements 6.3**
        """
        if style:
            self.pronoun_style = style
            logger.debug(f"Updated pronoun style: {style}")


@dataclass
class SessionContext:
    """
    Complete session context for a chat request.
    Combines session info with state tracking.
    """
    session_id: UUID
    user_id: str
    thread_id: Optional[str] = None
    state: SessionState = None
    user_name: Optional[str] = None
    
    def __post_init__(self):
        if self.state is None:
            self.state = SessionState(session_id=self.session_id)


# =============================================================================
# SESSION MANAGER SERVICE
# =============================================================================

class SessionManager:
    """
    Manages chat sessions and state.
    
    Responsibilities:
    - Session lifecycle (create, get)
    - SessionState tracking (anti-repetition)
    - Thread-based session support (v2.1)
    
    **Pattern:** Singleton Service
    """
    
    def __init__(self, chat_history: Optional[ChatHistoryRepository] = None):
        """
        Initialize SessionManager.
        
        Args:
            chat_history: ChatHistoryRepository instance (optional, uses singleton if not provided)
        """
        self._chat_history = chat_history or get_chat_history_repository()
        self._sessions: Dict[str, UUID] = {}  # user_id -> session_id
        self._session_states: Dict[str, SessionState] = {}  # session_id -> SessionState
        
        logger.info("SessionManager initialized")
    
    def get_or_create_session(
        self, 
        user_id: str, 
        thread_id: Optional[str] = None
    ) -> SessionContext:
        """
        Get or create a session for user.
        
        v2.1: Thread-based sessions support.
        - thread_id provided: Use as session_id (continue existing thread)
        - thread_id None: Create new session for user
        
        User facts persist across threads (queried by user_id).
        Chat history is thread-scoped (queried by session_id).
        
        Args:
            user_id: User identifier
            thread_id: Optional thread ID for multi-thread support
            
        Returns:
            SessionContext with session info and state
        """
        session_id = self._resolve_session_id(user_id, thread_id)
        state = self._get_or_create_state(session_id)
        user_name = self._get_user_name(session_id)
        
        return SessionContext(
            session_id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            state=state,
            user_name=user_name
        )
    
    def _resolve_session_id(self, user_id: str, thread_id: Optional[str]) -> UUID:
        """Resolve session_id from user_id and optional thread_id."""
        # v2.1: If thread_id provided, use it as session_id
        if thread_id:
            try:
                session_uuid = UUID(thread_id)
                self._sessions[user_id] = session_uuid
                return session_uuid
            except ValueError:
                # Invalid UUID, create new session
                pass
        
        # Try to get from chat history (persistent)
        if self._chat_history.is_available():
            chat_session = self._chat_history.get_or_create_session(user_id)
            if chat_session:
                self._sessions[user_id] = chat_session.session_id
                return chat_session.session_id
        
        # Fallback to in-memory session
        if user_id not in self._sessions:
            self._sessions[user_id] = uuid4()
        return self._sessions[user_id]
    
    def _get_or_create_state(self, session_id: UUID) -> SessionState:
        """Get or create session state for anti-repetition tracking."""
        session_key = str(session_id)
        if session_key not in self._session_states:
            self._session_states[session_key] = SessionState(session_id=session_id)
        return self._session_states[session_key]
    
    def _get_user_name(self, session_id: UUID) -> Optional[str]:
        """Get user name from chat history if available."""
        if self._chat_history.is_available():
            return self._chat_history.get_user_name(session_id)
        return None
    
    def update_user_name(self, session_id: UUID, name: str) -> None:
        """Update user name in chat history."""
        if self._chat_history.is_available():
            self._chat_history.update_user_name(session_id, name)
    
    def get_state(self, session_id: UUID) -> SessionState:
        """Get session state by session_id."""
        return self._get_or_create_state(session_id)
    
    def update_state(
        self, 
        session_id: UUID, 
        phrase: Optional[str] = None,
        used_name: bool = False,
        pronoun_style: Optional[dict] = None
    ) -> None:
        """
        Update session state after a response.
        
        Args:
            session_id: Session UUID
            phrase: Opening phrase to track (anti-repetition)
            used_name: Whether user's name was used in response
            pronoun_style: Detected pronoun style to update
        """
        state = self._get_or_create_state(session_id)
        
        if phrase:
            state.add_phrase(phrase)
        
        state.increment_response(used_name=used_name)
        
        if pronoun_style:
            state.update_pronoun_style(pronoun_style)
    
    def is_available(self) -> bool:
        """Check if session manager is available."""
        return True


# =============================================================================
# SINGLETON
# =============================================================================

_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create SessionManager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
