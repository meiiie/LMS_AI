"""Finalize direct-node LLM/tool execution results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_codebase_analysis_fallback_answer,
    _build_codebase_analysis_fallback_thinking,
    _looks_generic_direct_fallback_response,
    _strip_dsml_residue,
)
from app.engine.multi_agent.direct_node_response_cleanup import (
    apply_source_backed_empty_response_fallback,
    clean_direct_node_llm_response,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_visible_thinking_finalization import (
    finalize_direct_node_visible_thinking,
)
from app.engine.multi_agent.direct_node_visible_thought import (
    _compact_basic_identity_answer,
    _strip_direct_inline_private_asides,
)
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
    looks_like_search_placeholder_answer,
)
from app.engine.reasoning import record_thinking_snapshot
from app.engine.runtime.runtime_metrics import inc_counter


@dataclass(slots=True)
class DirectNodeLlmExecutionFinalizationResult:
    response: str
    thinking_content: str
    tools_used: list[Any]
    tool_call_events: list[dict[str, Any]]


async def finalize_direct_node_llm_execution(
    *,
    query: str,
    state: dict[str, Any],
    llm_response: Any,
    messages: list[Any],
    tool_call_events: list[dict[str, Any]],
    llm: Any,
    routing_intent: str,
    response_language: str,
    is_identity_turn: bool,
    explicit_web_search_turn: bool,
    extract_direct_response: Callable[[Any, list[Any]], tuple[str, str, list[Any]]],
    sanitize_structured_visual_answer_text: Callable[[str], str],
    sanitize_wiii_house_text: Callable[[str], str],
    build_direct_reasoning_summary: Callable[..., str],
    logger_obj: Any,
    clean_direct_node_llm_response_fn: Callable[..., Any] = clean_direct_node_llm_response,
    apply_source_backed_empty_response_fallback_fn: Callable[..., Any] = (
        apply_source_backed_empty_response_fallback
    ),
    finalize_direct_node_visible_thinking_fn: Callable[..., Any] = (
        finalize_direct_node_visible_thinking
    ),
) -> DirectNodeLlmExecutionFinalizationResult:
    """Finalize a completed LLM/tool round and apply direct-node state effects."""

    if tool_call_events:
        state["tool_call_events"] = tool_call_events

    response, thinking_content, tools_used = extract_direct_response(llm_response, messages)
    cleaned_response = clean_direct_node_llm_response_fn(
        query=query,
        state=state,
        response=response,
        thinking_content=thinking_content,
        tools_used=tools_used,
        tool_call_events=tool_call_events,
        is_identity_turn=is_identity_turn,
        is_codebase_analysis_turn=_is_codebase_analysis_query(query),
        explicit_web_search_turn=explicit_web_search_turn,
        sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
        sanitize_wiii_house_text=sanitize_wiii_house_text,
        strip_direct_inline_private_asides=_strip_direct_inline_private_asides,
        strip_dsml_residue=_strip_dsml_residue,
        compact_basic_identity_answer=_compact_basic_identity_answer,
        looks_generic_direct_fallback_response=_looks_generic_direct_fallback_response,
        build_codebase_analysis_fallback_answer=_build_codebase_analysis_fallback_answer,
        build_codebase_analysis_fallback_thinking=_build_codebase_analysis_fallback_thinking,
        record_direct_node_thinking_snapshot=record_direct_node_thinking_snapshot,
        record_thinking_snapshot_fn=record_thinking_snapshot,
    )
    response = cleaned_response.response
    thinking_content = cleaned_response.thinking_content
    tools_used = list(cleaned_response.tools_used or [])

    source_fallback = apply_source_backed_empty_response_fallback_fn(
        query=query,
        response=response,
        tools_used=tools_used,
        tool_call_events=tool_call_events,
        looks_like_search_placeholder_answer=looks_like_search_placeholder_answer,
        build_search_template_fallback=build_search_template_fallback,
        inc_counter=inc_counter,
        logger_obj=logger_obj,
    )
    response = source_fallback.response
    tools_used = list(source_fallback.tools_used or [])

    await finalize_direct_node_visible_thinking_fn(
        query=query,
        state=state,
        response=response,
        thinking_content=thinking_content,
        routing_intent=routing_intent,
        response_language=response_language,
        llm=llm,
        tools_used=list(tools_used or []),
        build_direct_reasoning_summary=build_direct_reasoning_summary,
        record_direct_node_thinking_snapshot=record_direct_node_thinking_snapshot,
        record_thinking_snapshot_fn=record_thinking_snapshot,
    )
    if tools_used:
        state["tools_used"] = tools_used

    return DirectNodeLlmExecutionFinalizationResult(
        response=response,
        thinking_content=thinking_content,
        tools_used=tools_used,
        tool_call_events=tool_call_events,
    )
