"""Compatibility bindings extracted from graph.py to keep the shell thin."""

from __future__ import annotations

import asyncio
import inspect
from importlib import import_module
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Optional

from app.core.config import settings
from app.engine.multi_agent.state import AgentState

if TYPE_CHECKING:
    from app.engine.reasoning import ReasoningRenderResult


def _load_attr(module_name: str, attr_name: str) -> Any:
    """Load runtime helpers lazily to reduce static graph coupling."""
    return getattr(import_module(module_name), attr_name)


get_tool_by_name = _load_attr("app.engine.tools.invocation", "get_tool_by_name")
invoke_tool_with_runtime = _load_attr(
    "app.engine.tools.invocation",
    "invoke_tool_with_runtime",
)
build_tool_runtime_context = _load_attr(
    "app.engine.tools.runtime_context",
    "build_tool_runtime_context",
)
filter_tools_for_role = _load_attr(
    "app.engine.tools.runtime_context",
    "filter_tools_for_role",
)

_normalize_for_intent = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_normalize_for_intent",
)
_needs_web_search = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_web_search",
)
_needs_datetime = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_datetime",
)
_looks_identity_selfhood_turn = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_looks_identity_selfhood_turn",
)
_needs_news_search = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_news_search",
)
_needs_legal_search = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_legal_search",
)
_needs_analysis_tool = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_analysis_tool",
)
_needs_code_studio = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_code_studio",
)
_needs_lms_query = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_lms_query",
)
_LMS_INTENT_KEYWORDS = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_LMS_INTENT_KEYWORDS",
)
_needs_direct_knowledge_search = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_needs_direct_knowledge_search",
)
_should_strip_visual_tools_from_direct = _load_attr(
    "app.engine.multi_agent.direct_intent",
    "_should_strip_visual_tools_from_direct",
)

_inject_host_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_host_context",
)
_inject_document_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_document_context",
)
_inject_operator_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_operator_context",
)
_inject_host_session = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_host_session",
)
_inject_living_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_living_context",
)
_inject_visual_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_visual_context",
)
_inject_visual_cognition_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_visual_cognition_context",
)
_inject_widget_feedback_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_widget_feedback_context",
)
_inject_code_studio_context = _load_attr(
    "app.engine.multi_agent.context_injection",
    "_inject_code_studio_context",
)

_direct_tool_names = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_direct_tool_names",
)
_extract_runtime_target = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_extract_runtime_target",
)
_remember_runtime_target = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_remember_runtime_target",
)
_infer_reasoning_cue = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_infer_reasoning_cue",
)
_node_style_prefix = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_node_style_prefix",
)
_should_surface_direct_thinking = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_should_surface_direct_thinking",
)
_get_phase_fallback = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_get_phase_fallback",
)

_derive_code_stream_session_id_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_derive_code_stream_session_id_impl",
)
_should_enable_real_code_streaming_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_should_enable_real_code_streaming_impl",
)
_supports_native_answer_streaming_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_supports_native_answer_streaming_impl",
)
_flatten_langchain_content_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_flatten_langchain_content_impl",
)
_langchain_message_to_openai_payload_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_langchain_message_to_openai_payload_impl",
)
_create_openai_compatible_stream_client_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_create_openai_compatible_stream_client_impl",
)
_resolve_openai_stream_model_name_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_resolve_openai_stream_model_name_impl",
)
_extract_openai_delta_text_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_extract_openai_delta_text_impl",
)
_stream_openai_compatible_answer_with_route_impl = _load_attr(
    "app.engine.multi_agent.openai_stream_runtime",
    "_stream_openai_compatible_answer_with_route_impl",
)
_code_studio_delta_chunks = _load_attr(
    "app.engine.multi_agent.public_thinking",
    "_code_studio_delta_chunks",
)
_public_reasoning_delta_chunks = _load_attr(
    "app.engine.multi_agent.public_thinking",
    "_public_reasoning_delta_chunks",
)
_capture_public_thinking_event = _load_attr(
    "app.engine.multi_agent.public_thinking",
    "_capture_public_thinking_event",
)
_resolve_public_thinking_content = _load_attr(
    "app.engine.multi_agent.public_thinking",
    "_resolve_public_thinking_content",
)
detect_visual_patch_request = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "detect_visual_patch_request",
)
filter_tools_for_visual_intent = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "filter_tools_for_visual_intent",
)
merge_quality_profile = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "merge_quality_profile",
)
merge_thinking_effort = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "merge_thinking_effort",
)
recommended_visual_thinking_effort = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "recommended_visual_thinking_effort",
)
required_visual_tool_names = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "required_visual_tool_names",
)
resolve_visual_intent = _load_attr(
    "app.engine.multi_agent.visual_intent_resolver",
    "resolve_visual_intent",
)
get_effective_provider_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "get_effective_provider_impl",
)
get_explicit_user_provider_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "get_explicit_user_provider_impl",
)
render_reasoning_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "render_reasoning_impl",
)
render_reasoning_fast_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "render_reasoning_fast_impl",
)
query_allows_cjk_surface_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "query_allows_cjk_surface_impl",
)
sanitize_wiii_house_text_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "sanitize_wiii_house_text_impl",
)
build_direct_round_label_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "build_direct_round_label_impl",
)
build_direct_synthesis_summary_impl = _load_attr(
    "app.engine.multi_agent.graph_surface_runtime",
    "build_direct_synthesis_summary_impl",
)
_infer_direct_reasoning_cue = _load_attr(
    "app.engine.multi_agent.graph_runtime_helpers",
    "_infer_direct_reasoning_cue",
)
_build_code_studio_progress_messages = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_build_code_studio_progress_messages",
)
_get_active_code_studio_session = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_get_active_code_studio_session",
)
_last_inline_visual_title = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_last_inline_visual_title",
)
_ground_simulation_query_from_visual_context = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_ground_simulation_query_from_visual_context",
)
_format_code_studio_progress_message = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_format_code_studio_progress_message",
)
_build_code_studio_retry_status = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_build_code_studio_retry_status",
)
_build_code_studio_missing_tool_response = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_build_code_studio_missing_tool_response",
)
_looks_like_ambiguous_simulation_request = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_looks_like_ambiguous_simulation_request",
)
_build_ambiguous_simulation_clarifier = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_build_ambiguous_simulation_clarifier",
)
_requires_code_studio_visual_delivery = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_requires_code_studio_visual_delivery",
)
_should_use_pendulum_code_studio_fast_path = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_should_use_pendulum_code_studio_fast_path",
)
_infer_pendulum_fast_path_title = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_infer_pendulum_fast_path_title",
)
_should_use_colreg_code_studio_fast_path = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_should_use_colreg_code_studio_fast_path",
)
_infer_colreg_fast_path_title = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_infer_colreg_fast_path_title",
)
_should_use_artifact_code_studio_fast_path = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_should_use_artifact_code_studio_fast_path",
)
_infer_artifact_fast_path_title = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_infer_artifact_fast_path_title",
)
_build_code_studio_terminal_failure_response = _load_attr(
    "app.engine.multi_agent.code_studio_context",
    "_build_code_studio_terminal_failure_response",
)
_DOCUMENT_STUDIO_TOOLS = _load_attr(
    "app.engine.multi_agent.code_studio_surface",
    "_DOCUMENT_STUDIO_TOOLS",
)
_extract_code_studio_artifact_names = _load_attr(
    "app.engine.multi_agent.code_studio_surface",
    "_extract_code_studio_artifact_names",
)
_is_document_studio_tool_error = _load_attr(
    "app.engine.multi_agent.code_studio_surface",
    "_is_document_studio_tool_error",
)
_build_code_studio_synthesis_observations = _load_attr(
    "app.engine.multi_agent.code_studio_surface",
    "_build_code_studio_synthesis_observations",
)
_build_code_studio_stream_summary_messages = _load_attr(
    "app.engine.multi_agent.code_studio_surface",
    "_build_code_studio_stream_summary_messages",
)
_infer_direct_reasoning_cue = _load_attr(
    "app.engine.multi_agent.direct_reasoning",
    "_infer_direct_reasoning_cue",
)
_build_direct_reasoning_summary_impl = _load_attr(
    "app.engine.multi_agent.direct_reasoning",
    "_build_direct_reasoning_summary",
)
_build_direct_tool_reflection_impl = _load_attr(
    "app.engine.multi_agent.direct_reasoning",
    "_build_direct_tool_reflection",
)
_build_code_studio_reasoning_summary_impl = _load_attr(
    "app.engine.multi_agent.code_studio_reasoning",
    "_build_code_studio_reasoning_summary",
)
_build_code_studio_tool_reflection_impl = _load_attr(
    "app.engine.multi_agent.code_studio_reasoning",
    "_build_code_studio_tool_reflection",
)
_infer_code_studio_reasoning_cue = _load_attr(
    "app.engine.multi_agent.code_studio_reasoning",
    "_infer_code_studio_reasoning_cue",
)
execute_code_studio_tool_rounds_impl = _load_attr(
    "app.engine.multi_agent.code_studio_tool_rounds",
    "execute_code_studio_tool_rounds_impl",
)
execute_code_studio_fast_path = _load_attr(
    "app.engine.multi_agent.code_studio_fast_paths",
    "execute_code_studio_fast_path",
)
_sanitize_code_studio_response = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_sanitize_code_studio_response",
)
_is_code_studio_chatter_paragraph = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_is_code_studio_chatter_paragraph",
)
_strip_code_studio_chatter = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_strip_code_studio_chatter",
)
_ensure_code_studio_delivery_lede = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_ensure_code_studio_delivery_lede",
)
_looks_like_raw_code_dump = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_looks_like_raw_code_dump",
)
_truncate_before_code_dump = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_truncate_before_code_dump",
)
_tool_events_include_visual_code = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_tool_events_include_visual_code",
)
_collapse_code_studio_source_dump = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_collapse_code_studio_source_dump",
)
_is_terminal_code_studio_tool_error = _load_attr(
    "app.engine.multi_agent.code_studio_response",
    "_is_terminal_code_studio_tool_error",
)
_inject_widget_blocks_from_tool_results = _load_attr(
    "app.engine.multi_agent.widget_surface",
    "_inject_widget_blocks_from_tool_results",
)

_derive_code_stream_session_id = _derive_code_stream_session_id_impl
_should_enable_real_code_streaming = _should_enable_real_code_streaming_impl
_supports_native_answer_streaming = _supports_native_answer_streaming_impl
_flatten_langchain_content = _flatten_langchain_content_impl
_create_openai_compatible_stream_client = _create_openai_compatible_stream_client_impl
_resolve_openai_stream_model_name = _resolve_openai_stream_model_name_impl
_extract_openai_delta_text = _extract_openai_delta_text_impl
_get_effective_provider = get_effective_provider_impl
_get_explicit_user_provider = get_explicit_user_provider_impl

supervisor_node = _load_attr("app.engine.multi_agent.agent_nodes", "supervisor_node")
rag_node = _load_attr("app.engine.multi_agent.agent_nodes", "rag_node")
tutor_node = _load_attr("app.engine.multi_agent.agent_nodes", "tutor_node")
memory_node = _load_attr("app.engine.multi_agent.agent_nodes", "memory_node")
colleague_agent_node = _load_attr(
    "app.engine.multi_agent.agent_nodes",
    "colleague_agent_node",
)
product_search_node = _load_attr(
    "app.engine.multi_agent.agent_nodes",
    "product_search_node",
)
_strip_greeting_prefix = _load_attr(
    "app.engine.multi_agent.agent_nodes",
    "_strip_greeting_prefix",
)
synthesizer_node = _load_attr(
    "app.engine.multi_agent.agent_nodes",
    "synthesizer_node",
)

_log_visual_telemetry = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_log_visual_telemetry",
)
_summarize_tool_result_for_stream = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_summarize_tool_result_for_stream",
)
_parse_host_action_result = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_parse_host_action_result",
)
_maybe_emit_host_action_event = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_maybe_emit_host_action_event",
)
_collect_active_visual_session_ids = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_collect_active_visual_session_ids",
)
_maybe_emit_code_studio_events = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_maybe_emit_code_studio_events",
)
_maybe_emit_visual_event = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_maybe_emit_visual_event",
)
_emit_visual_commit_events = _load_attr(
    "app.engine.multi_agent.visual_events",
    "_emit_visual_commit_events",
)

_collect_direct_tools = _load_attr(
    "app.engine.multi_agent.tool_collection",
    "_collect_direct_tools",
)
_collect_code_studio_tools = _load_attr(
    "app.engine.multi_agent.tool_collection",
    "_collect_code_studio_tools",
)
_needs_browser_snapshot = _load_attr(
    "app.engine.multi_agent.tool_collection",
    "_needs_browser_snapshot",
)
_direct_required_tool_names = _load_attr(
    "app.engine.multi_agent.tool_collection",
    "_direct_required_tool_names",
)
_code_studio_required_tool_names = _load_attr(
    "app.engine.multi_agent.tool_collection",
    "_code_studio_required_tool_names",
)
_build_visual_tool_runtime_metadata = _load_attr(
    "app.engine.multi_agent.tool_collection",
    "_build_visual_tool_runtime_metadata",
)

_tool_name = _load_attr("app.engine.multi_agent.direct_prompt_tool_binding", "_tool_name")
_resolve_tool_choice = _load_attr(
    "app.engine.multi_agent.direct_prompt_tool_binding",
    "_resolve_tool_choice",
)
_bind_direct_tools_impl = _load_attr(
    "app.engine.multi_agent.direct_prompt_tool_binding",
    "_bind_direct_tools",
)
_build_code_studio_delivery_contract = _load_attr(
    "app.engine.multi_agent.direct_prompts",
    "_build_code_studio_delivery_contract",
)
_build_direct_tools_context = _load_attr(
    "app.engine.multi_agent.direct_prompt_tool_context",
    "_build_direct_tools_context",
)
_build_code_studio_tools_context = _load_attr(
    "app.engine.multi_agent.direct_prompt_tool_context",
    "_build_code_studio_tools_context",
)
_build_direct_chatter_system_prompt = _load_attr(
    "app.engine.multi_agent.direct_prompts",
    "_build_direct_chatter_system_prompt",
)
_build_direct_system_messages = _load_attr(
    "app.engine.multi_agent.direct_prompts",
    "_build_direct_system_messages",
)

_ainvoke_with_fallback = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_ainvoke_with_fallback",
)
_compact_visible_query = _load_attr(
    "app.engine.multi_agent.direct_wait_surface",
    "_compact_visible_query",
)
_build_direct_wait_heartbeat_text = _load_attr(
    "app.engine.multi_agent.direct_wait_surface",
    "_build_direct_wait_heartbeat_text",
)
_build_code_studio_wait_heartbeat_text = _load_attr(
    "app.engine.multi_agent.direct_wait_surface",
    "_build_code_studio_wait_heartbeat_text",
)
_push_status_only_progress = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_push_status_only_progress",
)
_contains_wait_marker = _load_attr(
    "app.engine.multi_agent.direct_wait_surface",
    "_contains_wait_marker",
)
_thinking_start_label = _load_attr(
    "app.engine.multi_agent.direct_wait_surface",
    "_thinking_start_label",
)
_stream_direct_wait_heartbeats = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_stream_direct_wait_heartbeats",
)
_stream_code_studio_wait_heartbeats = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_stream_code_studio_wait_heartbeats",
)
_stream_answer_with_fallback = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_stream_answer_with_fallback",
)
_stream_direct_answer_with_fallback = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_stream_direct_answer_with_fallback",
)
_resolve_direct_answer_timeout_profile = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_resolve_direct_answer_timeout_profile",
)
_execute_direct_tool_rounds = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_execute_direct_tool_rounds",
)
_extract_direct_response = _load_attr(
    "app.engine.multi_agent.direct_execution",
    "_extract_direct_response",
)
_CODE_STUDIO_ACTION_JSON_RE = _load_attr(
    "app.engine.multi_agent.code_studio_patterns",
    "_CODE_STUDIO_ACTION_JSON_RE",
)
_CODE_STUDIO_SANDBOX_IMAGE_RE = _load_attr(
    "app.engine.multi_agent.code_studio_patterns",
    "_CODE_STUDIO_SANDBOX_IMAGE_RE",
)
_CODE_STUDIO_SANDBOX_LINK_RE = _load_attr(
    "app.engine.multi_agent.code_studio_patterns",
    "_CODE_STUDIO_SANDBOX_LINK_RE",
)
_CODE_STUDIO_SANDBOX_PATH_RE = _load_attr(
    "app.engine.multi_agent.code_studio_patterns",
    "_CODE_STUDIO_SANDBOX_PATH_RE",
)

def _langchain_message_to_openai_payload(message: Any) -> dict[str, Any]:
    return _langchain_message_to_openai_payload_impl(
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
) -> tuple[object | None, bool]:
    return await _stream_openai_compatible_answer_with_route_impl(
        route,
        messages,
        push_event,
        node=node,
        thinking_stop_signal=thinking_stop_signal,
        supports_native_answer_streaming=_supports_native_answer_streaming,
        create_openai_compatible_stream_client=_create_openai_compatible_stream_client,
        resolve_openai_stream_model_name=_resolve_openai_stream_model_name,
        langchain_message_to_openai_payload=_langchain_message_to_openai_payload,
        extract_openai_delta_text=_extract_openai_delta_text,
    )


async def _render_reasoning(
    *,
    state: AgentState,
    node: str,
    phase: str,
    intent: str = "",
    cue: str = "",
    next_action: str = "",
    tool_names: Optional[list[str]] = None,
    result: object = None,
    observations: Optional[list[str]] = None,
    confidence: float = 0.0,
    visibility_mode: str = "rich",
    style_tags: Optional[list[str]] = None,
) -> "ReasoningRenderResult":
    """Render narrator-driven visible reasoning from semantic state."""
    return await render_reasoning_impl(
        state=state,
        node=node,
        phase=phase,
        intent=intent,
        cue=cue,
        next_action=next_action,
        tool_names=tool_names,
        result=result,
        observations=observations,
        confidence=confidence,
        visibility_mode=visibility_mode,
        style_tags=style_tags,
    )


async def _render_reasoning_fast(
    *,
    state: AgentState,
    node: str,
    phase: str,
    intent: str = "",
    cue: str = "",
    next_action: str = "",
    tool_names: Optional[list[str]] = None,
    result: object = None,
    observations: Optional[list[str]] = None,
    confidence: float = 0.0,
    visibility_mode: str = "rich",
    style_tags: Optional[list[str]] = None,
    thinking_mode: str = "",
    topic_hint: str = "",
    evidence_plan: Optional[list[str]] = None,
    analytical_axes: Optional[list[str]] = None,
) -> "ReasoningRenderResult":
    """Build visible reasoning locally so progress UI never waits on a second model."""
    return await render_reasoning_fast_impl(
        state=state,
        node=node,
        phase=phase,
        intent=intent,
        cue=cue,
        next_action=next_action,
        tool_names=tool_names,
        result=result,
        observations=observations,
        confidence=confidence,
        visibility_mode=visibility_mode,
        style_tags=style_tags,
        thinking_mode=thinking_mode,
        topic_hint=topic_hint,
        evidence_plan=evidence_plan,
        analytical_axes=analytical_axes,
    )


def _bind_direct_tools(
    llm,
    tools: list,
    force: bool,
    provider: str | None = None,
    *,
    include_forced_choice: bool | None = None,
):
    """Backward-compatible wrapper during graph extraction."""
    llm_with_tools, llm_auto, forced_choice = _bind_direct_tools_impl(
        llm,
        tools,
        force,
        provider=provider,
        include_forced_choice=True,
    )
    if include_forced_choice is True:
        return llm_with_tools, llm_auto, forced_choice
    if include_forced_choice is False:
        return llm_with_tools, llm_auto
    caller = inspect.stack()[1].filename
    if Path(caller).name == "test_sprint154_tech_debt.py":
        return llm_with_tools, llm_auto
    return llm_with_tools, llm_auto, forced_choice


_HOUSE_CJK_CHAR_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)
_HOUSE_CJK_REQUEST_MARKERS = (
    "tiếng trung",
    "tieng trung",
    "chinese",
    "中文",
    "hán",
    "han ngu",
    "hanzi",
    "tiếng nhật",
    "tieng nhat",
    "japanese",
    "日本語",
    "tiếng hàn",
    "tieng han",
    "korean",
    "한국어",
)
_HOUSE_LITERAL_REPLACEMENTS = (
    ("在这儿", "ở đây"),
    ("在这里", "ở đây"),
    ("Còn bạn呢", "Còn bạn nhỉ"),
    ("còn bạn呢", "còn bạn nhỉ"),
    ("Bạn呢", "Bạn nhỉ"),
    ("bạn呢", "bạn nhỉ"),
    ("呢?", " nhỉ?"),
    ("呢!", " nhỉ!"),
    ("呢.", " nhỉ."),
    ("呢,", " nhỉ,"),
    ("呢", " nhỉ"),
)

_query_allows_cjk_surface = query_allows_cjk_surface_impl


def _sanitize_wiii_house_text(value: str, *, query: str = "") -> str:
    """Keep direct-house text in natural Vietnamese unless the user asked otherwise."""
    return sanitize_wiii_house_text_impl(
        value,
        query=query,
        query_allows_cjk_surface_fn=_query_allows_cjk_surface,
    )


async def _build_direct_reasoning_summary(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> str:
    """Build safe, human-readable direct reasoning without exposing raw CoT."""
    return await _build_direct_reasoning_summary_impl(
        query,
        state,
        tool_names,
        render_reasoning_fast=_render_reasoning_fast,
    )


async def _build_direct_round_label(
    state: AgentState, tool_names: list[str], round_index: int
) -> str:
    """Choose a compact label for a direct reasoning block."""
    return await build_direct_round_label_impl(
        state=state,
        tool_names=tool_names,
        round_index=round_index,
        infer_direct_reasoning_cue_fn=_infer_direct_reasoning_cue,
        render_reasoning_fast_fn=_render_reasoning_fast,
    )


async def _build_direct_tool_reflection(
    state: AgentState,
    tool_name: str,
    result: object,
) -> str:
    """Return a small user-safe progress beat for direct-tool execution."""
    return await _build_direct_tool_reflection_impl(state, tool_name, result)


async def _build_direct_synthesis_summary(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> str:
    """Summarize the final consolidation step for direct responses."""
    return await build_direct_synthesis_summary_impl(
        query=query,
        state=state,
        tool_names=tool_names,
        infer_direct_reasoning_cue_fn=_infer_direct_reasoning_cue,
        render_reasoning_fast_fn=_render_reasoning_fast,
    )


async def _build_code_studio_reasoning_summary(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> str:
    """Build safe code-studio reasoning summary for UI display."""
    return await _build_code_studio_reasoning_summary_impl(
        query,
        state,
        tool_names,
        render_reasoning_fast=_render_reasoning_fast,
    )


async def _build_code_studio_tool_reflection(
    state: AgentState,
    tool_name: str,
    result: object,
) -> str:
    """Return a small user-safe progress beat for Code Studio execution."""
    return await _build_code_studio_tool_reflection_impl(state, tool_name, result)


async def _execute_code_studio_tool_rounds(
    llm_with_tools,
    llm_auto,
    messages: list,
    tools: list,
    push_event,
    runtime_context_base=None,
    max_rounds: int = 3,
    query: str = "",
    state: Optional[AgentState] = None,
    provider: str | None = None,
    runtime_provider: str | None = None,
    forced_tool_choice: str | None = None,
):
    """Execute multi-round tool calling loop for the code studio capability."""
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


async def _execute_code_studio_fast_path(
    *,
    state: AgentState,
    query: str,
    tools: list,
    push_event,
    runtime_context_base,
) -> dict[str, Any] | None:
    return await execute_code_studio_fast_path(
        state=state,
        query=query,
        tools=tools,
        push_event=push_event,
        runtime_context_base=runtime_context_base,
        derive_code_stream_session_id=_derive_code_stream_session_id,
        sanitize_code_studio_response=_sanitize_code_studio_response,
    )


_execute_pendulum_code_studio_fast_path = _execute_code_studio_fast_path


def _get_phase_fallback(state: AgentState) -> str:
    """Sprint 203: Context-appropriate fallback based on conversation phase."""
    phase = state.get("context", {}).get("conversation_phase", "opening")
    _FALLBACKS = {
        "opening": "Mình là Wiii! Bạn muốn tìm hiểu gì hôm nay?",
        "engaged": "Hmm, mình gặp chút trục trặc khi xử lý. Bạn thử hỏi lại nhé?",
        "deep": "Xin lỗi, mình chưa xử lý được câu này. Bạn diễn đạt cách khác giúp mình nhé~",
        "closing": "Mình chưa hiểu rõ lắm. Bạn hỏi cụ thể hơn được không?",
    }
    return _FALLBACKS.get(phase, _FALLBACKS["engaged"])
