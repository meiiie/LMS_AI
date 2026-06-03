"""
Chat Orchestrator - Pipeline Orchestration for Chat Processing

Extracted from chat_service.py as part of Clean Architecture refactoring.
Orchestrates the complete chat processing pipeline.

**Pattern:** Orchestrator / Pipeline
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

Authoritative request flow:
see app/services/REQUEST_FLOW_CONTRACT.md
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from app.core.config import settings
from app.engine.llm_runtime_metadata import resolve_runtime_llm_metadata
from app.models.schemas import ChatRequest, InternalChatResponse
from .chat_orchestrator_multi_agent import (
    build_minimal_multi_agent_execution_input_impl,
    build_multi_agent_context_impl,
    build_multi_agent_execution_input_impl,
    resolve_request_scope_impl,
)
from .chat_orchestrator_runtime import (
    prepare_turn_impl,
    process_with_multi_agent_impl,
)
from .chat_orchestrator_support import (
    finalize_response_turn_impl,
    load_pronoun_style_from_facts_impl,
    maybe_summarize_previous_session_impl,
    persist_pronoun_style_impl,
)
from .chat_orchestrator_fallback_runtime import (
    build_fast_chatter_result_impl,
    persist_chat_message_impl,
    process_with_direct_llm_impl,
    process_without_multi_agent_impl,
    should_use_local_direct_llm_fallback_impl,
    upsert_thread_view_impl,
)

from .session_manager import (
    SessionContext,
    SessionManager,
    get_session_manager,
)
from .input_processor import InputProcessor, ChatContext, get_input_processor
from .output_processor import (
    OutputProcessor,
    ProcessingResult,
    extract_thinking_from_response,
    get_output_processor,
)
from .background_tasks import BackgroundTaskRunner, get_background_runner
from . import living_continuity as _living_continuity

PostResponseContinuityContext = _living_continuity.PostResponseContinuityContext
schedule_post_response_continuity = _living_continuity.schedule_post_response_continuity
_analyze_and_process_sentiment = _living_continuity._analyze_and_process_sentiment

# Compatibility note: legacy Sprint 210 source-inspection tests still verify
# that chat_orchestrator.py references the LLM sentiment path via
# SentimentAnalyzer/get_sentiment_analyzer, even though the implementation now
# lives behind living_continuity.schedule_post_response_continuity().

logger = logging.getLogger(__name__)


# =============================================================================
# AGENT TYPE ENUM (for backward compatibility)
# =============================================================================

class AgentType(str, Enum):
    """Types of agents in the system."""
    CHAT = "chat"
    RAG = "rag"
    TUTOR = "tutor"
    DIRECT = "direct"
    MEMORY = "memory"
    CODE_STUDIO = "code_studio"


# Map supervisor next_agent values → AgentType
_AGENT_TYPE_MAP = {
    "rag_agent": AgentType.RAG,
    "tutor_agent": AgentType.TUTOR,
    "memory_agent": AgentType.MEMORY,
    "direct": AgentType.DIRECT,
    "code_studio_agent": AgentType.CODE_STUDIO,
}

@dataclass(frozen=True)
class RequestScope:
    """Resolved organization and domain for a chat request."""

    organization_id: str | None
    domain_id: str | None


@dataclass
class PreparedTurn:
    """Shared turn-preparation result for sync and streaming paths."""

    request_scope: RequestScope
    session: SessionContext
    session_id: object
    validation: object
    chat_context: ChatContext | None = None


@dataclass(frozen=True)
class MultiAgentExecutionInput:
    """Authoritative invocation payload for the multi-agent graph."""

    query: str
    user_id: str
    session_id: str
    context: dict
    domain_id: str
    thinking_effort: str | None = None
    provider: str | None = None
    model: str | None = None


# =============================================================================
# CHAT ORCHESTRATOR
# =============================================================================

class ChatOrchestrator:
    """
    Orchestrates the chat processing pipeline.
    
    Pipeline stages:
    1. Input validation (Guardian/Guardrails)
    2. Context retrieval (Memory, History, Insights)
    3. Agent processing (MultiAgent)
    4. Output validation & formatting
    5. Background tasks (Memory, Profile)
    
    **Pattern:** Orchestrator with Single Responsibility stages

    Contract note:
    Stage ordering here is the authoritative sync implementation for the chat
    business flow. Changes to that ordering should be reflected in
    REQUEST_FLOW_CONTRACT.md.
    """
    
    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        input_processor: Optional[InputProcessor] = None,
        output_processor: Optional[OutputProcessor] = None,
        background_runner: Optional[BackgroundTaskRunner] = None,
        multi_agent_runner=None,
        rag_agent=None,
        semantic_memory=None,
        chat_history=None,
        prompt_loader=None,
        guardrails=None
    ):
        """
        Initialize orchestrator with all dependencies.
        
        Dependencies are lazily initialized if not provided.
        """
        # Core processors
        self._session_manager = session_manager or get_session_manager()
        self._input_processor = input_processor or get_input_processor()
        self._output_processor = output_processor or get_output_processor()
        self._background_runner = background_runner or get_background_runner()
        
        # Agents
        self._multi_agent_runner = multi_agent_runner
        self._rag_agent = rag_agent
        
        # Dependencies for context building
        self._semantic_memory = semantic_memory
        self._chat_history = chat_history
        self._prompt_loader = prompt_loader
        self._guardrails = guardrails
        
        # Configuration flags
        self._use_multi_agent = getattr(settings, 'use_multi_agent', True)
        
        logger.info("ChatOrchestrator initialized")

    async def validate_request(
        self,
        request: ChatRequest,
        session_id,
    ):
        """Run the authoritative input validation contract for this request."""
        return await self._input_processor.validate(
            request=request,
            session_id=session_id,
            create_blocked_response=self._output_processor.create_blocked_response,
        )

    def persist_chat_message(
        self,
        session_id,
        role: str,
        content: str,
        user_id: str | None = None,
        organization_id: str | None = None,
        background_save: Optional[Callable] = None,
        immediate: bool = False,
    ) -> None:
        """Persist a chat message using transport-specific timing."""
        persist_chat_message_impl(
            chat_history=self._chat_history,
            session_id=session_id,
            role=role,
            content=content,
            user_id=user_id,
            organization_id=organization_id,
            background_save=background_save,
            immediate=immediate,
        )

    def upsert_thread_view(
        self,
        *,
        user_id: str,
        session_id,
        domain_id: str | None,
        title: str,
        organization_id: str | None,
    ) -> None:
        """Keep thread discovery state aligned across sync and streaming paths."""
        upsert_thread_view_impl(
            logger_obj=logger,
            user_id=user_id,
            session_id=session_id,
            domain_id=domain_id,
            title=title,
            organization_id=organization_id,
        )

    def _build_sync_fast_chatter_result(
        self,
        context: ChatContext | None,
    ) -> ProcessingResult | None:
        """Return a deterministic result for obvious sync-only chatter."""
        return build_fast_chatter_result_impl(
            context=context,
            processing_result_cls=ProcessingResult,
            agent_type_direct=AgentType.DIRECT,
            routing_method="sync_fast_chatter",
            model_name="wiii-sync-fast-chatter-v1",
        )

    def finalize_response_turn(
        self,
        *,
        session_id,
        user_id: str,
        user_role,
        message: str,
        response_text: str,
        context: ChatContext | None,
        domain_id: str | None,
        organization_id: str | None,
        current_agent: str = "",
        background_save: Optional[Callable] = None,
        save_response_immediately: bool = False,
        include_lms_insights: bool = True,
        continuity_channel: str = "web",
        transport_type: str = "sync",
        request_id: str | None = None,
    ) -> dict:
        """Run the authoritative post-response scheduling contract."""
        return finalize_response_turn_impl(
            logger_obj=logger,
            session_manager=self._session_manager,
            persist_chat_message=self.persist_chat_message,
            upsert_thread_view=self.upsert_thread_view,
            background_runner=self._background_runner,
            post_response_context_cls=PostResponseContinuityContext,
            schedule_post_response_continuity_fn=schedule_post_response_continuity,
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            message=message,
            response_text=response_text,
            context=context,
            domain_id=domain_id,
            organization_id=organization_id,
            current_agent=current_agent,
            background_save=background_save,
            save_response_immediately=save_response_immediately,
            include_lms_insights=include_lms_insights,
            continuity_channel=continuity_channel,
            transport_type=transport_type,
            request_id=request_id,
        )

    @staticmethod
    def normalize_thread_id(request: ChatRequest) -> str | None:
        """Normalize thread/session identifiers into one authoritative thread id."""
        thread_id = request.thread_id
        if thread_id and thread_id.lower() == "new":
            thread_id = None
        if not thread_id and request.session_id:
            thread_id = request.session_id
        return thread_id

    async def resolve_request_scope(self, request: ChatRequest) -> RequestScope:
        """Resolve the authoritative organization and domain for this request."""
        from app.core.org_context import (
            get_current_org_allowed_domains,
            get_current_org_id,
        )
        from app.domains.router import get_domain_router

        return await resolve_request_scope_impl(
            request,
            default_organization_id=settings.default_organization_id,
            enable_multi_tenant=settings.enable_multi_tenant,
            environment=settings.environment,
            get_current_org_id_fn=get_current_org_id,
            get_current_org_allowed_domains_fn=get_current_org_allowed_domains,
            get_domain_router_fn=get_domain_router,
            request_scope_cls=RequestScope,
        )

    async def resolve_lms_identity(
        self,
        user_id: str,
        organization_id: str | None,
    ) -> tuple[str | None, str | None]:
        """Resolve the LMS external identity for a user when integration is enabled."""
        if not settings.enable_lms_integration:
            return None, None

        try:
            from app.auth.external_identity import resolve_lms_identity

            return await resolve_lms_identity(user_id, organization_id)
        except Exception as exc:
            logger.debug("[ORCH] LMS identity resolve failed: %s", exc)
            return None, None

    async def build_multi_agent_context(
        self,
        context: ChatContext,
        session: SessionContext,
    ) -> dict:
        """Build the authoritative multi-agent context payload."""
        return await build_multi_agent_context_impl(
            context,
            session,
            resolve_lms_identity_fn=self.resolve_lms_identity,
        )

    async def build_multi_agent_execution_input(
        self,
        *,
        request: ChatRequest,
        prepared_turn: PreparedTurn,
        include_streaming_fields: bool = False,
        thinking_effort: str | None = None,
        provider: str | None = None,
        request_id: str | None = None,
    ) -> MultiAgentExecutionInput:
        """Build the authoritative graph invocation payload for this turn."""
        return await build_multi_agent_execution_input_impl(
            request=request,
            prepared_turn=prepared_turn,
            include_streaming_fields=include_streaming_fields,
            thinking_effort=thinking_effort,
            provider=provider,
            request_id=request_id,
            build_multi_agent_context_fn=self.build_multi_agent_context,
            multi_agent_execution_input_cls=MultiAgentExecutionInput,
            default_domain=settings.default_domain,
        )

    def build_minimal_multi_agent_execution_input(
        self,
        *,
        request: ChatRequest,
        prepared_turn: PreparedTurn,
        thinking_effort: str | None = None,
        provider: str | None = None,
        request_id: str | None = None,
    ) -> MultiAgentExecutionInput:
        """Build a minimal but valid graph invocation payload for degraded paths."""
        return build_minimal_multi_agent_execution_input_impl(
            request=request,
            prepared_turn=prepared_turn,
            thinking_effort=thinking_effort,
            provider=provider,
            request_id=request_id,
            multi_agent_execution_input_cls=MultiAgentExecutionInput,
            default_domain=settings.default_domain,
        )

    async def prepare_turn(
        self,
        request: ChatRequest,
        background_save: Optional[Callable] = None,
        persist_user_message_immediately: bool = False,
    ) -> PreparedTurn:
        """Prepare the authoritative pre-execution turn state."""
        from app.prompts.prompt_loader import detect_pronoun_style

        return await prepare_turn_impl(
            request=request,
            background_save=background_save,
            persist_user_message_immediately=persist_user_message_immediately,
            normalize_thread_id_fn=self.normalize_thread_id,
            resolve_request_scope_fn=self.resolve_request_scope,
            session_manager=self._session_manager,
            maybe_summarize_previous_session_fn=self._maybe_summarize_previous_session,
            load_pronoun_style_from_facts_fn=self._load_pronoun_style_from_facts,
            validate_request_fn=self.validate_request,
            persist_chat_message_fn=self.persist_chat_message,
            input_processor=self._input_processor,
            semantic_memory=self._semantic_memory,
            persist_pronoun_style_fn=self._persist_pronoun_style,
            prepared_turn_cls=PreparedTurn,
            detect_pronoun_style_fn=detect_pronoun_style,
        )
    
    async def process(
        self,
        request: ChatRequest,
        background_save: Optional[Callable] = None,
        record: bool = False,
    ) -> InternalChatResponse:
        """
        Process a chat request through the full pipeline.

        Pipeline:
        1. Get/create session
        2. Validate input
        3. Build context
        4. Process with agent
        5. Format output
        6. Schedule background tasks
        7. Optional eval snapshot (Phase 6 of #207, gated by settings.enable_eval_recording)

        Args:
            request: ChatRequest from API
            background_save: FastAPI BackgroundTasks.add_task
            record: When True AND settings.enable_eval_recording=True,
                snapshot this turn into the JSONL eval log. Per-call
                opt-in lets canary traffic flag itself for replay.

        Returns:
            InternalChatResponse ready for API serialization
        """
        user_id = str(request.user_id)
        message = request.message
        user_role = request.role

        prepared_turn = await self.prepare_turn(
            request=request,
            background_save=background_save,
        )
        org_id = prepared_turn.request_scope.organization_id
        domain_id = prepared_turn.request_scope.domain_id
        logger.info("[DOMAIN] Resolved domain: %s (org: %s)", domain_id, org_id)

        # Sprint 66: thinking effort for multi-agent processing
        thinking_effort = getattr(request, 'thinking_effort', None)
        provider = getattr(request, 'provider', None)
        model = getattr(request, 'model', None)

        session = prepared_turn.session
        session_id = prepared_turn.session_id

        logger.info("Processing request for user %s with role: %s", user_id, user_role.value)

        if prepared_turn.validation.blocked:
            return prepared_turn.validation.blocked_response

        context = prepared_turn.chat_context

        if provider and provider != "auto":
            from app.services.llm_selectability_service import ensure_provider_is_selectable

            ensure_provider_is_selectable(provider)

        # ================================================================
        # STAGE 4: AGENT PROCESSING
        # ================================================================
        
        fast_result = self._build_sync_fast_chatter_result(context)

        # Option A: Deterministic fast path for obvious sync-only chatter.
        if fast_result is not None:
            result = fast_result

        # Option B: Multi-Agent System (SOTA 2025)
        elif self._use_multi_agent:
            result = await self._process_with_multi_agent(
                context,
                session,
                domain_id,
                thinking_effort,
                provider,
                model,
            )

        # Option C: Fallback to direct RAG mode
        else:
            result = await self.process_without_multi_agent(context)
        
        # ================================================================
        # STAGE 5: OUTPUT FORMATTING
        # ================================================================
        response = await self._output_processor.validate_and_format(
            result=result,
            session_id=session_id,
            user_name=context.user_name,
            user_role=user_role
        )
        
        # ================================================================
        # STAGE 6: POST-PROCESSING & BACKGROUND TASKS
        # ================================================================
        # Source-inspection compatibility: this stage still covers
        # save_message, post-turn lifecycle scheduling,
        # routine_tracker.record_interaction, and _analyze_and_process_sentiment
        # via finalize_response_turn()
        # and living_continuity.schedule_post_response_continuity().
        # Tenant-isolation marker: finalize_response_turn_impl forwards the
        # resolved organization_id into lifecycle-owned background scheduling.
        
        post_turn_lifecycle = self.finalize_response_turn(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            message=message,
            response_text=result.message or "",
            context=context,
            domain_id=domain_id,
            organization_id=org_id,
            current_agent=(result.metadata or {}).get("current_agent", ""),
            background_save=background_save,
            continuity_channel="web",
            transport_type="sync",
        )
        response.metadata = {
            **(response.metadata or {}),
            "post_turn_lifecycle": post_turn_lifecycle,
        }

        if record and getattr(settings, "enable_eval_recording", False):
            await self._record_eval_turn(
                request=request,
                response=response,
                result=result,
                session_id=session_id,
                org_id=org_id,
            )

        return response

    async def _record_eval_turn(
        self,
        *,
        request: ChatRequest,
        response: InternalChatResponse,
        result: "ProcessingResult",
        session_id: str,
        org_id: Optional[str],
    ) -> None:
        """Snapshot one turn into the eval JSONL log (Phase 6 of #207).

        Fail-soft: a recorder I/O error must never bubble up into the
        chat response — log and move on.
        """
        try:
            from pathlib import Path

            from app.engine.runtime.eval_recorder import (
                EvalRecord,
                EvalRecorder,
                sanitize_eval_payload,
            )

            base_dir = Path(getattr(settings, "eval_recording_dir", "eval_recordings"))
            recorder = EvalRecorder(base_dir=base_dir)

            request_payload: dict = {
                "message": getattr(request, "message", ""),
                "user_id": str(getattr(request, "user_id", "")),
                "role": (
                    getattr(request, "role").value
                    if hasattr(getattr(request, "role", None), "value")
                    else str(getattr(request, "role", ""))
                ),
                "domain_id": getattr(request, "domain_id", None),
                "organization_id": getattr(request, "organization_id", None),
            }

            request_payload = sanitize_eval_payload(request_payload)

            metadata = sanitize_eval_payload(dict(result.metadata or {}))
            metadata.setdefault("current_agent", metadata.get("current_agent", ""))

            sources_payload: list[dict] = []
            for src in getattr(response, "sources", None) or []:
                if hasattr(src, "model_dump"):
                    sources_payload.append(sanitize_eval_payload(src.model_dump()))
                elif isinstance(src, dict):
                    sources_payload.append(sanitize_eval_payload(src))

            tool_calls_payload: list[dict] = []
            for call in metadata.get("tool_calls", []) or []:
                if isinstance(call, dict):
                    tool_calls_payload.append(sanitize_eval_payload(call))

            record_obj = EvalRecord(
                session_id=session_id,
                org_id=org_id,
                request=request_payload,
                response=(
                    getattr(response, "message", None)
                    or getattr(response, "response", "")
                    or result.message
                    or ""
                ),
                tool_calls=tool_calls_payload,
                sources=sources_payload,
                metadata=metadata,
            )
            await recorder.write(record_obj)
        except Exception as exc:  # noqa: BLE001 — fail-soft on I/O
            logger.warning("[EVAL_RECORDER] failed to record turn: %s", exc)

    def _should_use_local_direct_llm_fallback(self) -> bool:
        """Use direct local inference when local mode is enabled without cloud retrieval support."""
        return should_use_local_direct_llm_fallback_impl(settings_obj=settings)

    async def process_without_multi_agent(self, context: ChatContext) -> ProcessingResult:
        """Run the authoritative non-multi-agent fallback used by sync and stream."""
        return await process_without_multi_agent_impl(
            context=context,
            rag_agent=self._rag_agent,
            output_processor=self._output_processor,
            logger_obj=logger,
            should_use_local_direct_llm_fallback=self._should_use_local_direct_llm_fallback(),
            process_with_direct_llm_fn=self._process_with_direct_llm,
            resolve_runtime_llm_metadata_fn=resolve_runtime_llm_metadata,
            processing_result_cls=ProcessingResult,
            agent_type_rag=AgentType.RAG,
            agent_type_direct=AgentType.DIRECT,
        )

    async def _process_with_direct_llm(self, context: ChatContext) -> ProcessingResult:
        """Generate a local-first response without RAG when cloud retrieval is unavailable."""
        from app.engine.llm_pool import get_llm_light
        return await process_with_direct_llm_impl(
            context=context,
            get_llm_light_fn=get_llm_light,
            extract_thinking_from_response_fn=extract_thinking_from_response,
            resolve_runtime_llm_metadata_fn=resolve_runtime_llm_metadata,
            processing_result_cls=ProcessingResult,
            agent_type_direct=AgentType.DIRECT,
        )
    
    def _load_pronoun_style_from_facts(
        self,
        session: SessionContext,
        user_id: str,
    ) -> None:
        """Sprint 79: Load persisted pronoun style from user facts into new session."""
        load_pronoun_style_from_facts_impl(
            semantic_memory=self._semantic_memory,
            session=session,
            user_id=user_id,
        )

    def _persist_pronoun_style(
        self,
        background_save: Callable,
        user_id: str,
        pronoun_style: dict,
    ) -> None:
        """Sprint 79: Store detected pronoun style as a user fact for cross-session persistence."""
        persist_pronoun_style_impl(
            background_save=background_save,
            user_id=user_id,
            pronoun_style=pronoun_style,
        )

    def _maybe_summarize_previous_session(
        self,
        background_save: Callable,
        user_id: str,
        organization_id: str | None = None,
    ) -> None:
        """Sprint 79: Trigger background summarization of user's previous session.

        When a user starts a new session (first message), summarize the previous
        session so that Layer 3 cross-session context (session_summarizer) is populated.
        """
        maybe_summarize_previous_session_impl(
            background_save=background_save,
            user_id=user_id,
            organization_id=organization_id,
        )

    async def _process_with_multi_agent(
        self,
        context: ChatContext,
        session: SessionContext,
        domain_id: str | None = None,
        thinking_effort: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> ProcessingResult:
        """
        Process with the WiiiRunner multi-agent runtime.
        
        Phase 8: SOTA 2025 - Supervisor Agent
        """
        logger.info("[MULTI-AGENT] Processing with Multi-Agent System (SOTA 2025)")
        return await process_with_multi_agent_impl(
            context=context,
            session=session,
            domain_id=domain_id,
            thinking_effort=thinking_effort,
            provider=provider,
            model=model,
            build_multi_agent_execution_input_fn=self.build_multi_agent_execution_input,
            request_scope_cls=RequestScope,
            prepared_turn_cls=PreparedTurn,
            processing_result_cls=ProcessingResult,
            agent_type_map=_AGENT_TYPE_MAP,
            default_agent_type=AgentType.RAG,
        )

# =============================================================================
# SINGLETON
# =============================================================================

_chat_orchestrator: Optional[ChatOrchestrator] = None


def get_chat_orchestrator() -> ChatOrchestrator:
    """Get or create ChatOrchestrator singleton."""
    global _chat_orchestrator
    if _chat_orchestrator is None:
        _chat_orchestrator = ChatOrchestrator()
    return _chat_orchestrator


def init_chat_orchestrator(
    session_manager=None,
    input_processor=None,
    output_processor=None,
    background_runner=None,
    multi_agent_runner=None,
    rag_agent=None,
    semantic_memory=None,
    chat_history=None,
    prompt_loader=None,
    guardrails=None
) -> ChatOrchestrator:
    """Initialize ChatOrchestrator with all dependencies."""
    global _chat_orchestrator
    _chat_orchestrator = ChatOrchestrator(
        session_manager=session_manager,
        input_processor=input_processor,
        output_processor=output_processor,
        background_runner=background_runner,
        multi_agent_runner=multi_agent_runner,
        rag_agent=rag_agent,
        semantic_memory=semantic_memory,
        chat_history=chat_history,
        prompt_loader=prompt_loader,
        guardrails=guardrails
    )
    return _chat_orchestrator
