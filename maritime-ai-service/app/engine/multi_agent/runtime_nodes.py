"""Canonical node surface used by the WiiiRunner runtime."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.engine.multi_agent.agent_nodes import (
    colleague_agent_node,
    memory_node,
    product_search_node,
    rag_node,
    supervisor_node,
    synthesizer_node,
    tutor_node,
)
from app.engine.multi_agent.code_studio_node_runtime import code_studio_node_impl
from app.engine.multi_agent.direct_node_runtime import direct_response_node_impl
from app.engine.multi_agent.graph_runtime_bindings import (
    _bind_direct_tools,
    _build_ambiguous_simulation_clarifier,
    _build_code_studio_reasoning_summary,
    _build_code_studio_stream_summary_messages,
    _build_code_studio_tools_context,
    _build_direct_reasoning_summary,
    _build_direct_system_messages,
    _build_visual_tool_runtime_metadata,
    _capture_public_thinking_event,
    _code_studio_required_tool_names,
    _collect_active_visual_session_ids,
    _collect_code_studio_tools,
    _collect_direct_tools,
    _direct_required_tool_names,
    _direct_tool_names,
    _execute_code_studio_tool_rounds,
    _execute_direct_tool_rounds,
    _execute_code_studio_fast_path,
    _extract_direct_response,
    _get_active_code_studio_session,
    _get_effective_provider,
    _get_explicit_user_provider,
    _get_phase_fallback,
    _ground_simulation_query_from_visual_context,
    _last_inline_visual_title,
    _looks_identity_selfhood_turn,
    _looks_like_ambiguous_simulation_request,
    _needs_datetime,
    _needs_web_search,
    _normalize_for_intent,
    _resolve_direct_answer_timeout_profile,
    _resolve_public_thinking_content,
    _render_reasoning_fast,
    _sanitize_code_studio_response,
    _sanitize_wiii_house_text,
    _should_surface_direct_thinking,
    _stream_answer_with_fallback,
    _thinking_start_label,
    build_tool_runtime_context,
    merge_thinking_effort,
    recommended_visual_thinking_effort,
    resolve_visual_intent,
)
from app.engine.multi_agent.graph_support import _get_domain_greetings
from app.engine.multi_agent.graph_trace_store import _get_or_create_tracer
from app.engine.multi_agent.guardian_runtime import (
    get_guardian_impl,
    guardian_node_impl,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.subagent_dispatch import (
    build_subagent_registry_impl,
    parallel_dispatch_node_impl,
)
from app.engine.multi_agent.widget_surface import _sanitize_structured_visual_answer_text
from app.engine.reasoning_tracer import StepNames

logger = logging.getLogger(__name__)


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


def _get_guardian():
    """Runtime guardian accessor."""
    return get_guardian_impl()


async def guardian_node(state: AgentState) -> AgentState:
    """Guardian node for the WiiiRunner runtime."""
    return await guardian_node_impl(state, get_guardian=_get_guardian)


__all__ = [
    "code_studio_node",
    "colleague_agent_node",
    "direct_response_node",
    "guardian_node",
    "memory_node",
    "parallel_dispatch_node",
    "product_search_node",
    "rag_node",
    "supervisor_node",
    "synthesizer_node",
    "tutor_node",
]
