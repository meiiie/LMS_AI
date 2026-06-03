"""
Input Processor - Input Validation and Context Building

Extracted from chat_service.py as part of Clean Architecture refactoring.
Handles all input processing: validation, guardian, pronoun detection, context building.

**Pattern:** Processor Service
**Spec:** CHI THI KY THUAT SO 25 - Project Restructure
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import settings
from app.models.schemas import ChatRequest, UserRole
from app.engine.multi_agent.supervisor_hint_runtime import _normalize_router_text_impl
from app.engine.multi_agent.supervisor_runtime_support import _looks_reasoning_safety_meta_turn
from .input_processor_context_runtime import build_context_impl
from .input_processor_support import (
    extract_user_name_impl,
    validate_pronoun_request_impl,
)

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
    response_language: str = "vi"

    # Memory Context
    semantic_context: str = ""
    conversation_history: str = ""
    history_list: List[Dict[str, str]] = None
    user_facts: List[Any] = None
    memory_warnings: List[str] = None
    memory_retrieval_summary: Optional[Dict[str, Any]] = None
    episodic_retrieval_summary: Optional[Dict[str, Any]] = None
    history_retrieval_summary: Optional[Dict[str, Any]] = None
    context_budget_summary: Optional[Dict[str, Any]] = None
    conversation_summary: Optional[str] = None

    # Sprint 77: LangChain messages for agent nodes (no truncation)
    langchain_messages: List[Any] = None  # List[BaseMessage]

    # Sprint 73: Core Memory Block (structured user profile for all agents)
    core_memory_block: str = ""

    # Sprint 115: Emotional state mood hint
    mood_hint: str = ""
    personality_mode: Optional[str] = None

    # Sprint 160: Multi-Tenant Data Isolation
    organization_id: Optional[str] = None

    # Sprint 179: Multimodal Vision
    images: Optional[list] = None  # List[ImageInput] from ChatRequest
    image_input_error: Optional[str] = None

    # Sprint 221: Page-Aware Context
    page_context: Optional[Any] = None
    student_state: Optional[Any] = None
    available_actions: Optional[list] = None

    # Sprint 222: Universal Host Context
    host_context: Optional[Any] = None
    host_capabilities: Optional[Any] = None
    host_action_feedback: Optional[Any] = None
    host_action_control_feedback: Optional[Any] = None
    visual_context: Optional[Any] = None
    widget_feedback: Optional[Any] = None
    code_studio_context: Optional[Any] = None
    document_context: Optional[Any] = None

    # Wiii Pointy v2.8: explicit `@plugin-name` force-bind từ ChatRequest.
    # Bypass `_needs_pointy/_needs_news/_needs_legal` intent gates trong
    # tool_collection. Empty list / None = standard keyword routing.
    force_skills: Optional[list[str]] = None

    # F18 Phase B (2026-05-07) — Pointy mode UX flag.
    # When True, user is talking directly to the cursor (action mode).
    # Backend forces tool_pointy_show invocation per turn + cursor-agent
    # persona in synthesizer.
    pointy_mode: bool = False

    # Analysis Context
    conversation_analysis: Any = None

    def __post_init__(self):
        if self.history_list is None:
            self.history_list = []
        if self.user_facts is None:
            self.user_facts = []
        if self.memory_warnings is None:
            self.memory_warnings = []
        if self.memory_retrieval_summary is None:
            self.memory_retrieval_summary = {}
        if self.episodic_retrieval_summary is None:
            self.episodic_retrieval_summary = {}
        if self.history_retrieval_summary is None:
            self.history_retrieval_summary = {}
        if self.context_budget_summary is None:
            self.context_budget_summary = {}
        if self.langchain_messages is None:
            self.langchain_messages = []


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
        conversation_analyzer=None,
    ):
        """Initialize with dependencies (lazy loaded)."""
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
        create_blocked_response: callable,
    ) -> ValidationResult:
        """
        Validate input with Guardian or Guardrails.

        CHI THI SO 21: Guardian Agent (LLM-based Content Moderation)
        """
        message = request.message
        user_id = str(request.user_id)
        result = ValidationResult()

        if self._guardian_agent is not None:
            if _looks_reasoning_safety_meta_turn(_normalize_router_text_impl(message)):
                logger.info("[GUARDIAN] Input reasoning-safety fast path")
                return result

            guardian_decision = await self._guardian_agent.validate_message(
                message=message,
                context="education",
            )

            if guardian_decision.action == "BLOCK":
                logger.warning(
                    "[GUARDIAN] Input blocked for user %s: %s",
                    user_id,
                    guardian_decision.reason,
                )
                result.blocked = True
                result.blocked_response = create_blocked_response(
                    [guardian_decision.reason or "Nội dung không phù hợp"]
                )
                self._log_blocked_message(
                    session_id,
                    message,
                    user_id,
                    guardian_decision.reason,
                    organization_id=getattr(request, "organization_id", None),
                )
            elif guardian_decision.action == "FLAG":
                logger.info(
                    "[GUARDIAN] Input flagged for user %s: %s",
                    user_id,
                    guardian_decision.reason,
                )
                result.flagged = True
                result.flag_reason = guardian_decision.reason
        else:
            if self._guardrails:
                input_result = await self._guardrails.validate_input(message)
                if not input_result.is_valid:
                    logger.warning(
                        "Input blocked for user %s: %s",
                        user_id,
                        input_result.issues,
                    )
                    result.blocked = True
                    result.blocked_response = create_blocked_response(input_result.issues)
                    self._log_blocked_message(
                        session_id,
                        message,
                        user_id,
                        "; ".join(input_result.issues),
                        organization_id=getattr(request, "organization_id", None),
                    )

        return result

    def _log_blocked_message(
        self,
        session_id: UUID,
        message: str,
        user_id: str,
        reason: str,
        organization_id: Optional[str] = None,
    ) -> None:
        """Log blocked message to chat history for admin review."""
        if self._chat_history and self._chat_history.is_available():
            self._chat_history.save_message(
                session_id=session_id,
                role="user",
                content=message,
                user_id=user_id,
                is_blocked=True,
                block_reason=reason,
                organization_id=organization_id,
            )
            logger.info(
                "[MEMORY ISOLATION] Blocked message saved to chat_history with is_blocked=True"
            )

    async def build_context(
        self,
        request: ChatRequest,
        session_id: UUID,
        user_name: Optional[str] = None,
        recent_history_fallback: Optional[List[Dict[str, str]]] = None,
    ) -> ChatContext:
        """Build complete context for chat processing."""
        return await build_context_impl(
            request=request,
            session_id=session_id,
            user_name=user_name,
            recent_history_fallback=recent_history_fallback,
            chat_context_cls=ChatContext,
            semantic_memory=self._semantic_memory,
            chat_history=self._chat_history,
            learning_graph=self._learning_graph,
            memory_summarizer=self._memory_summarizer,
            conversation_analyzer=self._conversation_analyzer,
            settings_obj=settings,
            logger_obj=logger,
        )

    def extract_user_name(self, message: str) -> Optional[str]:
        """Extract user name from message."""
        return extract_user_name_impl(message)

    async def validate_pronoun_request(
        self,
        message: str,
        current_style: Optional[dict] = None,
    ) -> Optional[dict]:
        """Validate custom pronoun request with GuardianAgent."""
        return await validate_pronoun_request_impl(
            guardian_agent=self._guardian_agent,
            message=message,
            logger=logger,
        )


# =============================================================================
# SINGLETON
# =============================================================================

_input_processor: Optional[InputProcessor] = None


def get_input_processor() -> InputProcessor:
    """Get or create InputProcessor singleton with GuardianAgent enabled."""
    global _input_processor
    if _input_processor is None:
        guardian = None
        try:
            from app.engine.guardian_agent import GuardianAgent

            guardian = GuardianAgent()
        except Exception as exc:
            logger.warning("GuardianAgent init failed: %s", exc)
        _input_processor = InputProcessor(guardian_agent=guardian)
    return _input_processor


def init_input_processor(
    guardian_agent=None,
    guardrails=None,
    semantic_memory=None,
    chat_history=None,
    learning_graph=None,
    memory_summarizer=None,
    conversation_analyzer=None,
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
        conversation_analyzer=conversation_analyzer,
    )
    return _input_processor
