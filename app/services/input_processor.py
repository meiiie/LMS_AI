"""
Input Processor - Input Validation and Context Building

Extracted from chat_service.py as part of Clean Architecture refactoring.
Handles all input processing: validation, guardian, pronoun detection, context building.

**Pattern:** Processor Service
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import settings
from app.models.schemas import ChatRequest, UserRole

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ValidationResult:
    """Result of input validation."""
    blocked: bool = False
    blocked_response: Any = None  # InternalChatResponse
    flagged: bool = False
    flag_reason: Optional[str] = None
    pronoun_style: Optional[dict] = None


@dataclass
class ChatContext:
    """Complete context for chat processing."""
    user_id: str
    session_id: UUID
    message: str
    user_role: UserRole
    user_name: Optional[str] = None
    
    # LMS Context
    lms_user_name: Optional[str] = None
    lms_module_id: Optional[str] = None
    lms_course_name: Optional[str] = None
    lms_language: str = "vi"
    
    # Memory Context
    semantic_context: str = ""
    conversation_history: str = ""
    history_list: List[Dict[str, str]] = None
    user_facts: List[Any] = None
    conversation_summary: Optional[str] = None
    
    # Analysis Context
    conversation_analysis: Any = None  # ConversationContext
    
    def __post_init__(self):
        if self.history_list is None:
            self.history_list = []
        if self.user_facts is None:
            self.user_facts = []


# =============================================================================
# INPUT PROCESSOR SERVICE
# =============================================================================

class InputProcessor:
    """
    Handles all input processing for chat requests.
    
    Responsibilities:
    - Input validation (Guardian Agent / Guardrails)
    - Pronoun detection
    - Context building (memory, history, insights)
    - User name extraction
    
    **Pattern:** Processor Service
    """
    
    def __init__(
        self,
        guardian_agent=None,
        guardrails=None,
        semantic_memory=None,
        chat_history=None,
        learning_graph=None,
        memory_summarizer=None,
        conversation_analyzer=None
    ):
        """
        Initialize with dependencies (lazy loaded).
        
        All dependencies are optional and will be lazily initialized if not provided.
        """
        self._guardian_agent = guardian_agent
        self._guardrails = guardrails
        self._semantic_memory = semantic_memory
        self._chat_history = chat_history
        self._learning_graph = learning_graph
        self._memory_summarizer = memory_summarizer
        self._conversation_analyzer = conversation_analyzer
        
        logger.info("InputProcessor initialized")
    
    async def validate(
        self,
        request: ChatRequest,
        session_id: UUID,
        create_blocked_response: callable
    ) -> ValidationResult:
        """
        Validate input with Guardian or Guardrails.
        
        CHỈ THỊ SỐ 21: Guardian Agent (LLM-based Content Moderation)
        
        Args:
            request: ChatRequest from API
            session_id: Session UUID for logging blocked messages
            create_blocked_response: Callback to create blocked response
            
        Returns:
            ValidationResult with blocked status and optional blocked response
        """
        message = request.message
        user_id = str(request.user_id)
        
        result = ValidationResult()
        
        # Use LLM-based Guardian Agent for contextual content filtering
        if self._guardian_agent is not None:
            guardian_decision = await self._guardian_agent.validate_message(
                message=message,
                context="maritime education"
            )
            
            if guardian_decision.action == "BLOCK":
                logger.warning(f"[GUARDIAN] Input blocked for user {user_id}: {guardian_decision.reason}")
                result.blocked = True
                result.blocked_response = create_blocked_response([guardian_decision.reason or "Nội dung không phù hợp"])
                
                # Log blocked message to DB
                self._log_blocked_message(session_id, message, user_id, guardian_decision.reason)
                
            elif guardian_decision.action == "FLAG":
                logger.info(f"[GUARDIAN] Input flagged for user {user_id}: {guardian_decision.reason}")
                result.flagged = True
                result.flag_reason = guardian_decision.reason
        else:
            # Fallback to rule-based Guardrails
            if self._guardrails:
                input_result = await self._guardrails.validate_input(message)
                if not input_result.is_valid:
                    logger.warning(f"Input blocked for user {user_id}: {input_result.issues}")
                    result.blocked = True
                    result.blocked_response = create_blocked_response(input_result.issues)
                    
                    # Log blocked message
                    self._log_blocked_message(session_id, message, user_id, "; ".join(input_result.issues))
        
        return result
    
    def _log_blocked_message(
        self,
        session_id: UUID,
        message: str,
        user_id: str,
        reason: str
    ) -> None:
        """Log blocked message to chat history for admin review."""
        if self._chat_history and self._chat_history.is_available():
            self._chat_history.save_message(
                session_id=session_id,
                role="user",
                content=message,
                user_id=user_id,
                is_blocked=True,
                block_reason=reason
            )
            logger.info(f"[MEMORY ISOLATION] Blocked message saved to chat_history with is_blocked=True")
    
    async def build_context(
        self,
        request: ChatRequest,
        session_id: UUID,
        user_name: Optional[str] = None
    ) -> ChatContext:
        """
        Build complete context for chat processing.
        
        Retrieves:
        - Semantic memory (insights + facts)
        - Conversation history
        - Learning graph context
        - Conversation summary
        
        Args:
            request: ChatRequest from API
            session_id: Session UUID
            user_name: Optional pre-known user name
            
        Returns:
            ChatContext with all retrieved context
        """
        user_id = str(request.user_id)
        message = request.message
        user_context = request.user_context
        
        # Initialize context
        context = ChatContext(
            user_id=user_id,
            session_id=session_id,
            message=message,
            user_role=request.role,
            user_name=user_name,
            lms_user_name=user_context.display_name if user_context else None,
            lms_module_id=user_context.current_module_id if user_context else None,
            lms_course_name=user_context.current_course_name if user_context else None,
            lms_language=user_context.language if user_context else "vi"
        )
        
        # Prioritize LMS user name
        if context.lms_user_name and not context.user_name:
            context.user_name = context.lms_user_name
        
        # Build semantic context
        semantic_parts = []
        
        # 1. Retrieve prioritized insights (v0.5)
        if self._semantic_memory and self._semantic_memory.is_available():
            try:
                insights = await self._semantic_memory.retrieve_insights_prioritized(
                    user_id=user_id,
                    query=message,
                    limit=10
                )
                
                if insights:
                    insight_lines = [f"- [{i.category.value}] {i.content}" for i in insights[:5]]
                    semantic_parts.append(f"=== Behavioral Insights ===\n" + "\n".join(insight_lines))
                    logger.info(f"[INSIGHT ENGINE] Retrieved {len(insights)} prioritized insights for user {user_id}")
                
                # Also get traditional context (facts + memories)
                mem_context = await self._semantic_memory.retrieve_context(
                    user_id=user_id,
                    query=message,
                    search_limit=5,
                    similarity_threshold=settings.similarity_threshold,
                    include_user_facts=True
                )
                traditional_context = mem_context.to_prompt_context()
                if traditional_context:
                    semantic_parts.append(traditional_context)
                
                context.user_facts = mem_context.user_facts if mem_context.user_facts else []
                
            except Exception as e:
                logger.warning(f"Semantic memory retrieval failed: {e}")
        
        # 2. Add Learning Graph context from Neo4j
        # SOTA 2025: Skip for non-student roles (teacher/admin don't need learning path tracking)
        # Teacher will have separate "Teaching Graph" context in future implementation
        if (self._learning_graph and 
            self._learning_graph.is_available() and 
            request.role == UserRole.STUDENT):
            try:
                graph_context = await self._learning_graph.get_user_learning_context(user_id)
                
                if graph_context.get("learning_path"):
                    path_items = [f"- {m['title']}" for m in graph_context["learning_path"][:5]]
                    semantic_parts.append(f"=== Learning Path ===\n" + "\n".join(path_items))
                
                if graph_context.get("knowledge_gaps"):
                    gap_items = [f"- {g['topic_name']}" for g in graph_context["knowledge_gaps"][:5]]
                    semantic_parts.append(f"=== Knowledge Gaps ===\n" + "\n".join(gap_items))
                
                logger.info(f"[LEARNING GRAPH] Added graph context for {user_id}")
            except Exception as e:
                logger.warning(f"Learning graph retrieval failed: {e}")
        
        context.semantic_context = "\n\n".join(semantic_parts)
        
        # 3. Get sliding window history
        if self._chat_history and self._chat_history.is_available():
            recent_messages = self._chat_history.get_recent_messages(session_id)
            context.conversation_history = self._chat_history.format_history_for_prompt(recent_messages)
            
            # Build history list for UnifiedAgent
            for msg in recent_messages:
                context.history_list.append({
                    "role": msg.role,
                    "content": msg.content
                })
            
            # Get user name if not already set
            if not context.user_name:
                context.user_name = self._chat_history.get_user_name(session_id)
        
        # 4. Get conversation summary
        if self._memory_summarizer:
            try:
                context.conversation_summary = await self._memory_summarizer.get_summary_async(str(session_id))
            except Exception as e:
                logger.warning(f"Failed to get conversation summary: {e}")
        
        # 5. Analyze conversation for deep reasoning
        if self._conversation_analyzer and context.history_list:
            try:
                context.conversation_analysis = self._conversation_analyzer.analyze(context.history_list)
                logger.info(f"[CONTEXT ANALYZER] Question type: {context.conversation_analysis.question_type.value}")
            except Exception as e:
                logger.warning(f"Failed to analyze conversation: {e}")
        
        # Combine semantic context with conversation history
        if context.semantic_context:
            context.conversation_history = f"{context.semantic_context}\n\n{context.conversation_history}".strip()
        
        # Debug logging
        logger.info(f"--- CONTEXT BUILT FOR USER {user_id} ---")
        logger.info(f"User Name: {context.user_name or 'UNKNOWN'}")
        logger.info(f"History Length: {len(context.conversation_history)} chars")
        logger.info(f"Semantic Context Length: {len(context.semantic_context)} chars")
        
        return context
    
    def extract_user_name(self, message: str) -> Optional[str]:
        """
        Extract user name from message.
        
        Enhanced patterns for Vietnamese and English:
        - "tên là X", "tên tôi là X", "mình tên là X"
        - "tôi là X", "em là X", "mình là X"
        - "tôi tên X", "em tên X"
        - "gọi tôi là X"
        - "I'm X", "my name is X", "call me X"
        
        **Validates: Requirements 2.1**
        """
        patterns = [
            # Vietnamese patterns
            r"tên (?:là|tôi là|mình là|em là)\s+(\w+)",
            r"mình tên là\s+(\w+)",
            r"(?:tôi|mình|em) là\s+(\w+)",
            r"(?:tôi|mình|em) tên\s+(\w+)",
            r"gọi (?:tôi|mình|em) là\s+(\w+)",
            r"tên\s+(\w+)",
            # English patterns
            r"(?:i'm|i am|my name is|call me)\s+(\w+)",
        ]
        
        # Common Vietnamese words that aren't names
        not_names = [
            "là", "tôi", "mình", "em", "anh", "chị", "bạn",
            "the", "a", "an", "gì", "đây", "này", "kia",
            "học", "sinh", "viên", "giáo", "sư"
        ]
        
        message_lower = message.lower()
        for pattern in patterns:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                name = match.group(1).capitalize()
                if name.lower() not in not_names:
                    return name
        return None
    
    async def validate_pronoun_request(
        self,
        message: str,
        current_style: Optional[dict] = None
    ) -> Optional[dict]:
        """
        Validate custom pronoun request with GuardianAgent.
        
        CHỈ THỊ SỐ 21: Custom pronoun validation
        
        Returns:
            Updated pronoun style if approved, None otherwise
        """
        if not self._guardian_agent:
            return None
        
        try:
            pronoun_result = await self._guardian_agent.validate_pronoun_request(message)
            if pronoun_result.approved:
                return {
                    "user_called": pronoun_result.user_called,
                    "ai_self": pronoun_result.ai_self
                }
        except Exception as e:
            logger.warning(f"Failed to validate pronoun request: {e}")
        
        return None


# =============================================================================
# SINGLETON
# =============================================================================

_input_processor: Optional[InputProcessor] = None


def get_input_processor() -> InputProcessor:
    """Get or create InputProcessor singleton."""
    global _input_processor
    if _input_processor is None:
        _input_processor = InputProcessor()
    return _input_processor


def init_input_processor(
    guardian_agent=None,
    guardrails=None,
    semantic_memory=None,
    chat_history=None,
    learning_graph=None,
    memory_summarizer=None,
    conversation_analyzer=None
) -> InputProcessor:
    """Initialize InputProcessor with dependencies."""
    global _input_processor
    _input_processor = InputProcessor(
        guardian_agent=guardian_agent,
        guardrails=guardrails,
        semantic_memory=semantic_memory,
        chat_history=chat_history,
        learning_graph=learning_graph,
        memory_summarizer=memory_summarizer,
        conversation_analyzer=conversation_analyzer
    )
    return _input_processor
