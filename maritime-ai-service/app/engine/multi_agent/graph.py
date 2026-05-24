"""
Multi-Agent Runtime Node Module - Phase 8.4

The active orchestration path runs through WiiiRunner. This module hosts shared
node wiring and the runner-backed process entrypoint.

**Integrated with agents/ framework for registry and tracing.**

**CHỈ THỊ SỐ 30: Universal ReasoningTrace for ALL paths**
"""

import asyncio
import importlib
import logging
import time
from typing import Any, Optional, Literal

from app.core.config import settings
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.graph_support import (
    _SUMMARY_MILESTONES,
    _build_turn_local_state_defaults,
    route_decision,
    _build_domain_config,
    _get_domain_greetings,
    _generate_session_summary_bg,
)
from app.engine.multi_agent.graph_trace_store import (
    _TRACERS,
    _cleanup_tracer,
    _get_or_create_tracer,
)
from app.engine.multi_agent.guardian_runtime import (
    get_guardian_impl,
    guardian_node_impl,
    guardian_route_impl,
)
from app.engine.multi_agent.direct_node_runtime import direct_response_node_impl
from app.engine.multi_agent.code_studio_tool_rounds import (
    execute_code_studio_tool_rounds_impl,
)
from app.engine.multi_agent.code_studio_node_runtime import code_studio_node_impl
from app.engine.multi_agent.graph_tool_collection_compat import (
    collect_code_studio_tools_with_settings,
    collect_direct_tools_with_settings,
    code_studio_required_tool_names_with_settings,
    direct_required_tool_names_with_settings,
)
from app.engine.multi_agent.widget_surface import (
    _has_structured_visual_event,
    _inject_widget_blocks_from_tool_results,
    _sanitize_structured_visual_answer_text,
)
from app.engine.multi_agent import tool_collection as _tool_collection_module
from app.engine.multi_agent.subagent_dispatch import (
    build_subagent_registry_impl,
    parallel_dispatch_node_impl,
)

# CHỈ THỊ SỐ 30: Universal ReasoningTrace
from app.engine.reasoning_tracer import StepNames

logger = logging.getLogger(__name__)

from app.engine.multi_agent.graph_runtime_bindings import (
    get_tool_by_name,
    invoke_tool_with_runtime,
    build_tool_runtime_context,
    filter_tools_for_role,
    _normalize_for_intent,
    _needs_web_search,
    _needs_datetime,
    _looks_identity_selfhood_turn,
    _needs_news_search,
    _needs_legal_search,
    _needs_analysis_tool,
    _needs_code_studio,
    _needs_lms_query,
    _LMS_INTENT_KEYWORDS,
    _needs_direct_knowledge_search,
    _should_strip_visual_tools_from_direct,
    _inject_host_context,
    _inject_operator_context,
    _inject_host_session,
    _inject_living_context,
    _inject_visual_context,
    _inject_visual_cognition_context,
    _inject_widget_feedback_context,
    _inject_code_studio_context,
    _direct_tool_names,
    _extract_runtime_target,
    _remember_runtime_target,
    _infer_reasoning_cue,
    _node_style_prefix,
    _should_surface_direct_thinking,
    _get_phase_fallback,
    _derive_code_stream_session_id,
    _should_enable_real_code_streaming,
    _supports_native_answer_streaming,
    _flatten_langchain_content,
    _langchain_message_to_openai_payload,
    _create_openai_compatible_stream_client,
    _resolve_openai_stream_model_name,
    _extract_openai_delta_text,
    _stream_openai_compatible_answer_with_route,
    _get_effective_provider,
    _get_explicit_user_provider,
    _render_reasoning,
    _render_reasoning_fast,
    detect_visual_patch_request,
    filter_tools_for_visual_intent,
    merge_quality_profile,
    merge_thinking_effort,
    recommended_visual_thinking_effort,
    required_visual_tool_names,
    resolve_visual_intent,
    _public_reasoning_delta_chunks,
    _code_studio_delta_chunks,
    _capture_public_thinking_event,
    _resolve_public_thinking_content,
    supervisor_node,
    rag_node,
    tutor_node,
    memory_node,
    colleague_agent_node,
    product_search_node,
    _strip_greeting_prefix,
    synthesizer_node,
    _log_visual_telemetry,
    _summarize_tool_result_for_stream,
    _parse_host_action_result,
    _maybe_emit_host_action_event,
    _collect_active_visual_session_ids,
    _maybe_emit_code_studio_events,
    _maybe_emit_visual_event,
    _emit_visual_commit_events,
    _DOCUMENT_STUDIO_TOOLS,
    _extract_code_studio_artifact_names,
    _is_document_studio_tool_error,
    _build_code_studio_synthesis_observations,
    _build_code_studio_stream_summary_messages,
    _get_active_code_studio_session,
    _last_inline_visual_title,
    _ground_simulation_query_from_visual_context,
    _build_code_studio_progress_messages,
    _format_code_studio_progress_message,
    _build_code_studio_retry_status,
    _looks_like_ambiguous_simulation_request,
    _build_ambiguous_simulation_clarifier,
    _build_code_studio_missing_tool_response,
    _requires_code_studio_visual_delivery,
    _should_use_pendulum_code_studio_fast_path,
    _infer_pendulum_fast_path_title,
    _should_use_colreg_code_studio_fast_path,
    _infer_colreg_fast_path_title,
    _should_use_artifact_code_studio_fast_path,
    _infer_artifact_fast_path_title,
    _build_code_studio_terminal_failure_response,
    _infer_code_studio_reasoning_cue,
    _collect_direct_tools,
    _collect_code_studio_tools,
    _needs_browser_snapshot,
    _direct_required_tool_names,
    _code_studio_required_tool_names,
    _build_visual_tool_runtime_metadata,
    _tool_name,
    _resolve_tool_choice,
    _bind_direct_tools,
    _build_code_studio_delivery_contract,
    _build_direct_tools_context,
    _build_code_studio_tools_context,
    _build_direct_chatter_system_prompt,
    _build_direct_system_messages,
    _ainvoke_with_fallback,
    _compact_visible_query,
    _build_direct_wait_heartbeat_text,
    _build_code_studio_wait_heartbeat_text,
    _push_status_only_progress,
    _contains_wait_marker,
    _thinking_start_label,
    _stream_direct_wait_heartbeats,
    _stream_code_studio_wait_heartbeats,
    _stream_answer_with_fallback,
    _stream_direct_answer_with_fallback,
    _resolve_direct_answer_timeout_profile,
    _execute_direct_tool_rounds,
    _extract_direct_response,
    _CODE_STUDIO_ACTION_JSON_RE,
    _CODE_STUDIO_SANDBOX_IMAGE_RE,
    _CODE_STUDIO_SANDBOX_LINK_RE,
    _CODE_STUDIO_SANDBOX_PATH_RE,
    _sanitize_wiii_house_text,
    _is_code_studio_chatter_paragraph,
    _strip_code_studio_chatter,
    _ensure_code_studio_delivery_lede,
    _looks_like_raw_code_dump,
    _truncate_before_code_dump,
    _tool_events_include_visual_code,
    _collapse_code_studio_source_dump,
    _sanitize_code_studio_response,
    _is_terminal_code_studio_tool_error,
    _build_direct_reasoning_summary,
    _build_direct_round_label,
    _build_direct_tool_reflection,
    _build_direct_synthesis_summary,
    _build_code_studio_reasoning_summary,
    _build_code_studio_tool_reflection,
    _execute_code_studio_tool_rounds,
    _execute_code_studio_fast_path,
    _get_phase_fallback,
)


def _langchain_message_to_openai_payload(message: Any) -> dict[str, Any]:
    """Keep graph-level patchability for OpenAI-compatible streaming helpers."""
    impl = importlib.import_module(
        "app.engine.multi_agent.openai_stream_runtime"
    )._langchain_message_to_openai_payload_impl
    return impl(
        message,
        flatten_langchain_content=_flatten_langchain_content,
    )


async def _stream_openai_compatible_answer_with_route(
    route,
    messages: list,
    push_event,
    *,
    node: str = "direct",
    thinking_stop_signal: Optional[asyncio.Event] = None,
    primary_timeout: float | None = None,
) -> tuple[object | None, bool]:
    """Use graph-local names so tests can patch the streaming dependencies here."""
    impl = importlib.import_module(
        "app.engine.multi_agent.openai_stream_runtime"
    )._stream_openai_compatible_answer_with_route_impl
    return await impl(
        route,
        messages,
        push_event,
        node=node,
        thinking_stop_signal=thinking_stop_signal,
        primary_timeout=primary_timeout,
        supports_native_answer_streaming=_supports_native_answer_streaming,
        create_openai_compatible_stream_client=_create_openai_compatible_stream_client,
        resolve_openai_stream_model_name=_resolve_openai_stream_model_name,
        langchain_message_to_openai_payload=_langchain_message_to_openai_payload,
        extract_openai_delta_text=_extract_openai_delta_text,
    )


def _collect_direct_tools(
    query: str,
    user_role: str = "student",
    *,
    state: AgentState | None = None,
):
    """Preserve graph.settings patch behavior for legacy tests and callers."""
    return collect_direct_tools_with_settings(
        query,
        user_role=user_role,
        state=state,
        settings_obj=settings,
        tool_collection_module=_tool_collection_module,
    )


def _collect_code_studio_tools(query: str, user_role: str = "student"):
    """Preserve graph.settings patch behavior for legacy tests and callers."""
    return collect_code_studio_tools_with_settings(
        query,
        user_role=user_role,
        settings_obj=settings,
        tool_collection_module=_tool_collection_module,
    )


def _direct_required_tool_names(query: str, user_role: str = "student") -> list[str]:
    """Preserve graph.settings patch behavior for legacy tests and callers."""
    return direct_required_tool_names_with_settings(
        query,
        user_role=user_role,
        settings_obj=settings,
        tool_collection_module=_tool_collection_module,
    )


def _code_studio_required_tool_names(query: str, user_role: str = "student") -> list[str]:
    """Preserve graph.settings patch behavior for legacy tests and callers."""
    return code_studio_required_tool_names_with_settings(
        query,
        user_role=user_role,
        settings_obj=settings,
        tool_collection_module=_tool_collection_module,
    )


async def _execute_code_studio_tool_rounds(
    llm_with_tools,
    llm_auto,
    messages: list,
    tools: list,
    push_event,
    runtime_context_base=None,
    max_rounds: int = 2,  # Phase 35: 3→2 (NVIDIA NIM ~60s/round; cap latency)
    query: str = "",
    state: Optional[AgentState] = None,
    provider: str | None = None,
    runtime_provider: str | None = None,
    forced_tool_choice: str | None = None,
):
    """Use graph-local names so legacy tests can patch code-studio dependencies here."""
    return await execute_code_studio_tool_rounds_impl(
        llm_with_tools,
        llm_auto,
        messages,
        tools,
        push_event,
        runtime_context_base=runtime_context_base,
        max_rounds=max_rounds,
        query=query,
        state=state,
        provider=provider,
        runtime_provider=runtime_provider,
        forced_tool_choice=forced_tool_choice,
        should_enable_real_code_streaming=_should_enable_real_code_streaming,
        derive_code_stream_session_id=_derive_code_stream_session_id,
        ainvoke_with_fallback=_ainvoke_with_fallback,
        build_code_studio_progress_messages=_build_code_studio_progress_messages,
        render_reasoning_fast=_render_reasoning_fast,
        infer_code_studio_reasoning_cue=_infer_code_studio_reasoning_cue,
        thinking_start_label=_thinking_start_label,
        code_studio_delta_chunks=_code_studio_delta_chunks,
        stream_code_studio_wait_heartbeats=_stream_code_studio_wait_heartbeats,
        format_code_studio_progress_message=_format_code_studio_progress_message,
        build_code_studio_retry_status=_build_code_studio_retry_status,
        build_code_studio_missing_tool_response=_build_code_studio_missing_tool_response,
        requires_code_studio_visual_delivery=_requires_code_studio_visual_delivery,
        collect_active_visual_session_ids=_collect_active_visual_session_ids,
        get_tool_by_name=get_tool_by_name,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        summarize_tool_result_for_stream=_summarize_tool_result_for_stream,
        maybe_emit_visual_event=_maybe_emit_visual_event,
        emit_visual_commit_events=_emit_visual_commit_events,
        build_code_studio_tool_reflection=_build_code_studio_tool_reflection,
        is_terminal_code_studio_tool_error=_is_terminal_code_studio_tool_error,
        build_code_studio_terminal_failure_response=_build_code_studio_terminal_failure_response,
        build_code_studio_synthesis_observations=_build_code_studio_synthesis_observations,
        inject_widget_blocks_from_tool_results=_inject_widget_blocks_from_tool_results,
        push_status_only_progress=_push_status_only_progress,
        settings_obj=settings,
    )


async def direct_response_node(state: AgentState) -> AgentState:
    return await direct_response_node_impl(
        state,
        direct_response_step_name=StepNames.DIRECT_RESPONSE,
        get_or_create_tracer=_get_or_create_tracer,
        capture_public_thinking_event=_capture_public_thinking_event,
        get_domain_greetings=_get_domain_greetings,
        normalize_for_intent=_normalize_for_intent,
        looks_identity_selfhood_turn=_looks_identity_selfhood_turn,
        needs_web_search=_needs_web_search,
        needs_datetime=_needs_datetime,
        resolve_visual_intent=resolve_visual_intent,
        recommended_visual_thinking_effort=recommended_visual_thinking_effort,
        get_active_code_studio_session=_get_active_code_studio_session,
        merge_thinking_effort=merge_thinking_effort,
        get_effective_provider=_get_effective_provider,
        get_explicit_user_provider=_get_explicit_user_provider,
        collect_direct_tools=_collect_direct_tools,
        direct_required_tool_names=_direct_required_tool_names,
        resolve_direct_answer_timeout_profile=_resolve_direct_answer_timeout_profile,
        bind_direct_tools=_bind_direct_tools,
        build_direct_system_messages=_build_direct_system_messages,
        build_visual_tool_runtime_metadata=_build_visual_tool_runtime_metadata,
        execute_direct_tool_rounds=_execute_direct_tool_rounds,
        extract_direct_response=_extract_direct_response,
        sanitize_structured_visual_answer_text=_sanitize_structured_visual_answer_text,
        sanitize_wiii_house_text=_sanitize_wiii_house_text,
        build_direct_reasoning_summary=_build_direct_reasoning_summary,
        direct_tool_names=_direct_tool_names,
        should_surface_direct_thinking=_should_surface_direct_thinking,
        resolve_public_thinking_content=_resolve_public_thinking_content,
        get_phase_fallback=_get_phase_fallback,
    )


async def code_studio_node(state: AgentState) -> AgentState:
    """Capability subagent for Python, chart, HTML, and file-generation tasks."""
    from app.engine.multi_agent.graph_event_bus import _get_event_queue

    return await code_studio_node_impl(
        state,
        settings_obj=settings,
        logger=logger,
        get_event_queue=_get_event_queue,
        capture_public_thinking_event=_capture_public_thinking_event,
        get_or_create_tracer=_get_or_create_tracer,
        step_names=StepNames,
        get_effective_provider=_get_effective_provider,
        looks_like_ambiguous_simulation_request=_looks_like_ambiguous_simulation_request,
        ground_simulation_query_from_visual_context=_ground_simulation_query_from_visual_context,
        last_inline_visual_title=_last_inline_visual_title,
        build_ambiguous_simulation_clarifier=_build_ambiguous_simulation_clarifier,
        collect_code_studio_tools=_collect_code_studio_tools,
        code_studio_required_tool_names=_code_studio_required_tool_names,
        bind_direct_tools=_bind_direct_tools,
        build_direct_system_messages=_build_direct_system_messages,
        build_code_studio_tools_context=_build_code_studio_tools_context,
        build_tool_runtime_context_fn=build_tool_runtime_context,
        build_visual_tool_runtime_metadata=_build_visual_tool_runtime_metadata,
        execute_code_studio_fast_path=_execute_code_studio_fast_path,
        execute_code_studio_tool_rounds=_execute_code_studio_tool_rounds,
        extract_direct_response=_extract_direct_response,
        build_code_studio_stream_summary_messages=_build_code_studio_stream_summary_messages,
        stream_answer_with_fallback=_stream_answer_with_fallback,
        sanitize_code_studio_response=_sanitize_code_studio_response,
        build_code_studio_reasoning_summary=_build_code_studio_reasoning_summary,
        direct_tool_names=_direct_tool_names,
        resolve_public_thinking_content=_resolve_public_thinking_content,
    )


# =============================================================================
# Sprint 163 Phase 4: Parallel Dispatch + Subagent Adapters
# Sprint 164: Added per-worker event emission for UX visualization
# =============================================================================


_SUBAGENT_ADAPTERS, _SUBAGENT_TYPES = build_subagent_registry_impl(
    render_reasoning_fast=_render_reasoning_fast,
    capture_public_thinking_event=_capture_public_thinking_event,
    thinking_start_label=_thinking_start_label,
)


async def parallel_dispatch_node(state: AgentState) -> AgentState:
    """Dispatch query to multiple subagents in parallel and collect reports."""
    return await parallel_dispatch_node_impl(
        state,
        subagent_adapters=_SUBAGENT_ADAPTERS,
        subagent_types=_SUBAGENT_TYPES,
    )


# =============================================================================
# Guardian Agent Node (SOTA 2026: Defense-in-depth Layer 2)
# =============================================================================

def _get_guardian():
    """Backward-compatible guardian accessor for legacy tests/hooks."""
    return get_guardian_impl()


async def guardian_node(state: AgentState) -> AgentState:
    """Guardian Agent node — input validation perimeter."""
    return await guardian_node_impl(state, get_guardian=_get_guardian)


def guardian_route(state: AgentState) -> Literal["supervisor", "synthesizer"]:
    """Route based on Guardian decision."""
    return guardian_route_impl(state)


async def process_with_multi_agent(
    query: str,
    user_id: str,
    session_id: str = "",
    context: dict = None,
    domain_id: Optional[str] = None,
    thinking_effort: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Compatibility wrapper for legacy graph imports."""
    from app.engine.multi_agent.runtime import process_with_multi_agent as process

    return await process(
        query=query,
        user_id=user_id,
        session_id=session_id,
        context=context,
        domain_id=domain_id,
        thinking_effort=thinking_effort,
        provider=provider,
        model=model,
    )


# =============================================================================
# V3 STREAMING: Extracted to graph_streaming.py
# Re-export for backward compatibility (lazy to avoid circular import)
# =============================================================================

def __getattr__(name):
    lazy_attr_map = {
        "process_with_multi_agent_streaming": (
            "app.engine.multi_agent.graph_streaming",
            "process_with_multi_agent_streaming",
        ),
        "get_supervisor_agent": (
            "app.engine.multi_agent.supervisor",
            "get_supervisor_agent",
        ),
        "get_agent_registry": (
            "app.engine.agents",
            "get_agent_registry",
        ),
        "get_reasoning_tracer": (
            "app.engine.reasoning_tracer",
            "get_reasoning_tracer",
        ),
        "get_rag_agent_node": (
            "app.engine.multi_agent.agents.rag_node",
            "get_rag_agent_node",
        ),
        "get_tutor_agent_node": (
            "app.engine.multi_agent.agents.tutor_node",
            "get_tutor_agent_node",
        ),
        "get_memory_agent_node": (
            "app.engine.multi_agent.agents.memory_agent",
            "get_memory_agent_node",
        ),
        "sanitize_visible_reasoning_text": (
            "app.engine.reasoning",
            "sanitize_visible_reasoning_text",
        ),
        "execute_code_studio_fast_path": (
            "app.engine.multi_agent.code_studio_fast_paths",
            "execute_code_studio_fast_path",
        ),
        "_load_code_studio_visual_skills": (
            "app.engine.multi_agent.code_studio_assets",
            "_load_code_studio_visual_skills",
        ),
        "_load_code_studio_example": (
            "app.engine.multi_agent.code_studio_assets",
            "_load_code_studio_example",
        ),
        "_should_use_pendulum_code_studio_fast_path": (
            "app.engine.multi_agent.code_studio_context",
            "_should_use_pendulum_code_studio_fast_path",
        ),
        "_infer_pendulum_fast_path_title": (
            "app.engine.multi_agent.code_studio_context",
            "_infer_pendulum_fast_path_title",
        ),
        "_should_use_colreg_code_studio_fast_path": (
            "app.engine.multi_agent.code_studio_context",
            "_should_use_colreg_code_studio_fast_path",
        ),
        "_infer_colreg_fast_path_title": (
            "app.engine.multi_agent.code_studio_context",
            "_infer_colreg_fast_path_title",
        ),
        "_should_use_artifact_code_studio_fast_path": (
            "app.engine.multi_agent.code_studio_context",
            "_should_use_artifact_code_studio_fast_path",
        ),
        "_infer_artifact_fast_path_title": (
            "app.engine.multi_agent.code_studio_context",
            "_infer_artifact_fast_path_title",
        ),
    }
    if name in lazy_attr_map:
        module_name, attr_name = lazy_attr_map[name]
        module = importlib.import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
