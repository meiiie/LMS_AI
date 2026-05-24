"""Typed provider/tool/fallback pipeline for the direct node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.direct_node_document_preview_runtime import (
    execute_direct_node_document_preview_round,
)
from app.engine.multi_agent.direct_node_exception_fallbacks import (
    handle_direct_node_generation_exception,
)
from app.engine.multi_agent.direct_node_exception_fallback_contract import (
    DirectNodeExceptionFallbackDependencies,
    DirectNodeExceptionFallbackRequest,
)
from app.engine.multi_agent.direct_node_llm_fallback import (
    resolve_direct_node_llm_unavailable_fallback,
)
from app.engine.multi_agent.direct_node_llm_preflight import (
    prepare_direct_node_llm_preflight,
)
from app.engine.multi_agent.direct_node_llm_tool_loop import (
    execute_direct_node_llm_tool_loop,
)
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_codebase_analysis_fallback_answer,
    _build_codebase_analysis_fallback_thinking,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_tool_selection import select_direct_node_tools
from app.engine.multi_agent.direct_node_turn_policy import resolve_direct_node_turn_policy
from app.engine.multi_agent.direct_node_uploaded_context import (
    _build_uploaded_document_context_fallback_answer,
    _build_uploaded_document_visual_guard_answer,
    _looks_uploaded_document_preview_request,
    _looks_uploaded_file_visual_inspection_query,
    _provider_likely_supports_image_blocks,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.state import AgentState
from app.engine.runtime.runtime_metrics import inc_counter


@dataclass(frozen=True, slots=True)
class DirectNodeLlmPipelineRequest:
    """Per-turn state required by provider-backed Direct Node execution."""

    query: str
    state: AgentState
    bus_id: str | None
    push_event: Callable[..., Any]
    tracer: Any
    ctx_for_preflight: dict[str, Any]
    has_uploaded_document_context: bool
    domain_name_vi: str
    sanitize_document_preview_response: Callable[[str, list[dict[str, Any]]], str]
    explicit_web_search_turn: bool
    enable_natural_conversation: bool
    requested_model: str | None
    llm_presence_penalty: float
    llm_frequency_penalty: float
    direct_max_rounds: int
    host_ui_total_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class DirectNodeLlmPipelineDependencies:
    """Injected app contracts used by the Direct Node LLM lifecycle."""

    normalize_for_intent: Callable[[str], str]
    looks_identity_selfhood_turn: Callable[[str], bool]
    needs_web_search: Callable[[str], bool]
    needs_datetime: Callable[[str], bool]
    resolve_visual_intent: Callable[[str], Any]
    recommended_visual_thinking_effort: Callable[..., Any]
    get_active_code_studio_session: Callable[[AgentState], Any]
    merge_thinking_effort: Callable[[Any, Any], Any]
    get_effective_provider: Callable[[AgentState], Any]
    get_explicit_user_provider: Callable[[AgentState], Any]
    collect_direct_tools: Callable[..., tuple[list[Any], bool]]
    direct_required_tool_names: Callable[[str, str], list[str]]
    resolve_direct_answer_timeout_profile: Callable[..., Any]
    bind_direct_tools: Callable[..., tuple[Any, Any, Any]]
    build_direct_system_messages: Callable[..., list[Any]]
    build_visual_tool_runtime_metadata: Callable[..., dict[str, Any]]
    execute_direct_tool_rounds: Callable[..., Any]
    extract_direct_response: Callable[..., Any]
    sanitize_structured_visual_answer_text: Callable[..., str]
    sanitize_wiii_house_text: Callable[..., str]
    build_direct_reasoning_summary: Callable[..., str]
    get_phase_fallback: Callable[[AgentState], str]
    record_thinking_snapshot_fn: Callable[..., Any]
    logger_obj: logging.Logger


@dataclass(slots=True)
class DirectNodeLlmPipelineResult:
    """Resolved Direct Node response after provider/tool/fallback execution."""

    response: str | None
    tool_call_events: list[dict[str, Any]]


async def execute_direct_node_llm_pipeline(
    *,
    request: DirectNodeLlmPipelineRequest,
    dependencies: DirectNodeLlmPipelineDependencies,
) -> DirectNodeLlmPipelineResult:
    """Run Direct Node policy, tool selection, provider preflight, and fallbacks."""

    query = request.query
    state = request.state
    explicit_user_provider: str | None = None
    llm = None
    llm_response = None
    messages: list[Any] = []
    tools: list[Any] = []
    tool_call_events: list[dict[str, Any]] = []
    response: str | None = None
    response_language = "vi"
    routing_intent = ""
    is_identity_turn = False
    is_emotional_support_turn = False
    explicit_web_search_turn = request.explicit_web_search_turn

    try:
        from app.engine.multi_agent.agent_config import AgentConfigRegistry
        from app.engine.multi_agent.openai_stream_runtime import (
            _supports_native_answer_streaming_impl,
        )

        turn_policy = resolve_direct_node_turn_policy(
            query=query,
            state=state,
            has_uploaded_document_context=request.has_uploaded_document_context,
            normalize_for_intent=dependencies.normalize_for_intent,
            looks_identity_selfhood_turn=dependencies.looks_identity_selfhood_turn,
            needs_web_search=dependencies.needs_web_search,
            needs_datetime=dependencies.needs_datetime,
            resolve_visual_intent=dependencies.resolve_visual_intent,
            recommended_visual_thinking_effort=(
                dependencies.recommended_visual_thinking_effort
            ),
            get_active_code_studio_session=dependencies.get_active_code_studio_session,
            merge_thinking_effort=dependencies.merge_thinking_effort,
            get_effective_provider=dependencies.get_effective_provider,
            get_explicit_user_provider=dependencies.get_explicit_user_provider,
            looks_uploaded_document_preview_request=(
                _looks_uploaded_document_preview_request
            ),
            logger_obj=dependencies.logger_obj,
        )
        ctx = turn_policy.ctx
        response_language = turn_policy.response_language
        thinking_effort = turn_policy.thinking_effort
        routing_intent = turn_policy.routing_intent
        is_identity_turn = turn_policy.is_identity_turn
        is_emotional_support_turn = turn_policy.is_emotional_support_turn
        is_short_house_chatter = turn_policy.is_short_house_chatter
        visual_decision = turn_policy.visual_decision
        history_limit = turn_policy.history_limit
        tools_context_override = turn_policy.tools_context_override
        role_name = turn_policy.role_name
        preferred_provider = turn_policy.preferred_provider
        explicit_user_provider = turn_policy.explicit_user_provider
        use_house_voice_direct = turn_policy.use_house_voice_direct
        direct_provider_override = turn_policy.direct_provider_override
        is_codebase_source_turn = turn_policy.is_codebase_source_turn
        explicit_web_search_turn = turn_policy.explicit_web_search_turn

        tool_selection = select_direct_node_tools(
            query=query,
            state=state,
            ctx=ctx,
            routing_intent=routing_intent,
            is_short_house_chatter=is_short_house_chatter,
            is_identity_turn=is_identity_turn,
            is_emotional_support_turn=is_emotional_support_turn,
            is_codebase_source_turn=is_codebase_source_turn,
            explicit_web_search_turn=explicit_web_search_turn,
            has_uploaded_document_context=request.has_uploaded_document_context,
            needs_web_search=dependencies.needs_web_search,
            collect_direct_tools=dependencies.collect_direct_tools,
            direct_required_tool_names=dependencies.direct_required_tool_names,
            logger_obj=dependencies.logger_obj,
        )
        tools = tool_selection.tools
        force_tools = tool_selection.force_tools

        if (
            request.has_uploaded_document_context
            and _looks_uploaded_document_preview_request(query)
        ):
            preview_result = await execute_direct_node_document_preview_round(
                query=query,
                state=state,
                ctx=ctx,
                bus_id=request.bus_id,
                tools=tools,
                force_tools=force_tools,
                messages=messages,
                push_event=request.push_event,
                build_visual_tool_runtime_metadata=(
                    dependencies.build_visual_tool_runtime_metadata
                ),
                execute_direct_tool_rounds=dependencies.execute_direct_tool_rounds,
                extract_direct_response=dependencies.extract_direct_response,
                sanitize_preview_response=(
                    request.sanitize_document_preview_response
                ),
                failure_log_message=(
                    "[DIRECT] Deterministic document preview pre-LLM path failed: %s"
                ),
                logger_obj=dependencies.logger_obj,
            )
            if preview_result is not None:
                response = preview_result.response
                messages = preview_result.messages
                tool_call_events = preview_result.tool_call_events
                request.tracer.end_step(
                    result="Deterministic uploaded-document preview host action",
                    confidence=0.9,
                    details={
                        "response_type": "document_preview_host_action",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                    },
                )

        llm_preflight = prepare_direct_node_llm_preflight(
            query=query,
            state=state,
            ctx=ctx,
            ctx_for_preflight=request.ctx_for_preflight,
            has_uploaded_document_context=request.has_uploaded_document_context,
            response=response or "",
            is_identity_turn=is_identity_turn,
            is_short_house_chatter=is_short_house_chatter,
            is_emotional_support_turn=is_emotional_support_turn,
            use_house_voice_direct=use_house_voice_direct,
            is_codebase_source_turn=is_codebase_source_turn,
            thinking_effort=thinking_effort,
            direct_provider_override=direct_provider_override,
            preferred_provider=preferred_provider,
            requested_model=request.requested_model,
            enable_natural_conversation=request.enable_natural_conversation,
            presence_penalty=request.llm_presence_penalty,
            frequency_penalty=request.llm_frequency_penalty,
            get_native_llm=AgentConfigRegistry.get_native_llm,
            get_llm=AgentConfigRegistry.get_llm,
            supports_native_answer_streaming=_supports_native_answer_streaming_impl,
            looks_uploaded_file_visual_inspection_query=(
                _looks_uploaded_file_visual_inspection_query
            ),
            provider_likely_supports_image_blocks=(
                _provider_likely_supports_image_blocks
            ),
            build_uploaded_document_visual_guard_answer=(
                _build_uploaded_document_visual_guard_answer
            ),
            tracer=request.tracer,
            logger_obj=dependencies.logger_obj,
        )
        llm = llm_preflight.llm
        response = llm_preflight.response or None

        if llm and not response:
            llm_tool_loop = await execute_direct_node_llm_tool_loop(
                llm=llm,
                query=query,
                state=state,
                ctx=ctx,
                bus_id=request.bus_id,
                domain_name_vi=request.domain_name_vi,
                role_name=role_name,
                tools=tools,
                force_tools=force_tools,
                tools_context_override=tools_context_override,
                visual_decision=visual_decision,
                history_limit=history_limit,
                routing_intent=routing_intent,
                response_language=response_language,
                is_identity_turn=is_identity_turn,
                is_short_house_chatter=is_short_house_chatter,
                use_house_voice_direct=use_house_voice_direct,
                direct_provider_override=direct_provider_override,
                preferred_provider=preferred_provider,
                explicit_user_provider=explicit_user_provider,
                explicit_web_search_turn=explicit_web_search_turn,
                push_event=request.push_event,
                needs_web_search=dependencies.needs_web_search,
                needs_datetime=dependencies.needs_datetime,
                resolve_direct_answer_timeout_profile=(
                    dependencies.resolve_direct_answer_timeout_profile
                ),
                bind_direct_tools=dependencies.bind_direct_tools,
                build_direct_system_messages=dependencies.build_direct_system_messages,
                build_visual_tool_runtime_metadata=(
                    dependencies.build_visual_tool_runtime_metadata
                ),
                execute_direct_tool_rounds=dependencies.execute_direct_tool_rounds,
                extract_direct_response=dependencies.extract_direct_response,
                sanitize_structured_visual_answer_text=(
                    dependencies.sanitize_structured_visual_answer_text
                ),
                sanitize_wiii_house_text=dependencies.sanitize_wiii_house_text,
                build_direct_reasoning_summary=(
                    dependencies.build_direct_reasoning_summary
                ),
                tracer=request.tracer,
                logger_obj=dependencies.logger_obj,
                direct_max_rounds=request.direct_max_rounds,
                host_ui_total_timeout_seconds=(
                    request.host_ui_total_timeout_seconds
                ),
            )

            response = llm_tool_loop.response
            messages = llm_tool_loop.messages
            tool_call_events = llm_tool_loop.tool_call_events
        elif not response:
            llm_fallback = resolve_direct_node_llm_unavailable_fallback(
                query=query,
                state=state,
                explicit_user_provider=explicit_user_provider,
                explicit_web_search_turn=explicit_web_search_turn,
                enable_natural_conversation=request.enable_natural_conversation,
                get_phase_fallback=dependencies.get_phase_fallback,
                build_codebase_analysis_fallback_answer=(
                    _build_codebase_analysis_fallback_answer
                ),
                build_codebase_analysis_fallback_thinking=(
                    _build_codebase_analysis_fallback_thinking
                ),
                record_direct_node_thinking_snapshot=(
                    record_direct_node_thinking_snapshot
                ),
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            response = llm_fallback.response
            request.tracer.end_step(
                result="Fallback (LLM unavailable)",
                confidence=0.5,
                details={"response_type": llm_fallback.response_type},
            )
    except Exception as exc:
        llm_response = getattr(exc, "_direct_node_llm_response", llm_response)
        messages = getattr(exc, "_direct_node_messages", messages)
        tool_call_events = getattr(
            exc,
            "_direct_node_tool_call_events",
            tool_call_events,
        )
        fallback_result = await handle_direct_node_generation_exception(
            request=DirectNodeExceptionFallbackRequest(
                exc=exc,
                query=query,
                state=state,
                ctx_for_preflight=request.ctx_for_preflight,
                tools=tools,
                tool_call_events=tool_call_events,
                llm_response=llm_response,
                messages=messages,
                llm=llm,
                routing_intent=routing_intent,
                response_language=response_language,
                is_identity_turn=is_identity_turn,
                explicit_user_provider=explicit_user_provider,
                explicit_web_search_turn=explicit_web_search_turn,
                tracer=request.tracer,
                push_event=request.push_event,
            ),
            dependencies=DirectNodeExceptionFallbackDependencies(
                needs_web_search=dependencies.needs_web_search,
                extract_direct_response=dependencies.extract_direct_response,
                sanitize_structured_visual_answer_text=(
                    dependencies.sanitize_structured_visual_answer_text
                ),
                sanitize_wiii_house_text=dependencies.sanitize_wiii_house_text,
                build_search_template_fallback=build_search_template_fallback,
                build_uploaded_document_context_fallback_answer=(
                    _build_uploaded_document_context_fallback_answer
                ),
                build_codebase_analysis_fallback_answer=(
                    _build_codebase_analysis_fallback_answer
                ),
                build_codebase_analysis_fallback_thinking=(
                    _build_codebase_analysis_fallback_thinking
                ),
                get_phase_fallback=dependencies.get_phase_fallback,
                record_direct_node_thinking_snapshot=(
                    record_direct_node_thinking_snapshot
                ),
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
                inc_counter=inc_counter,
                logger_obj=dependencies.logger_obj,
            ),
        )
        response = fallback_result.response
        tool_call_events = fallback_result.tool_call_events

    return DirectNodeLlmPipelineResult(
        response=response,
        tool_call_events=tool_call_events,
    )
