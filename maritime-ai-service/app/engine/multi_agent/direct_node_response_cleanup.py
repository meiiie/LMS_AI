"""Direct-node response cleanup and source-backed fallback helpers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from app.engine.multi_agent.state import AgentState


@dataclass(slots=True)
class DirectNodeCleanedResponse:
    response: str
    thinking_content: str
    tools_used: list[Any]


@dataclass(slots=True)
class DirectNodeSourceFallback:
    response: str
    tools_used: list[Any]
    engaged: bool


def clean_direct_node_llm_response(
    *,
    query: str,
    state: AgentState,
    response: str,
    thinking_content: str,
    tools_used: list[Any],
    tool_call_events: list[dict[str, Any]],
    is_identity_turn: bool,
    is_codebase_analysis_turn: bool,
    explicit_web_search_turn: bool,
    sanitize_structured_visual_answer_text: Callable[..., str],
    sanitize_wiii_house_text: Callable[..., str],
    strip_direct_inline_private_asides: Callable[[str], str],
    strip_dsml_residue: Callable[[str], str],
    compact_basic_identity_answer: Callable[..., str],
    looks_generic_direct_fallback_response: Callable[[str], bool],
    build_codebase_analysis_fallback_answer: Callable[[str], str],
    build_codebase_analysis_fallback_thinking: Callable[[str], str],
    record_direct_node_thinking_snapshot: Callable[..., None],
    record_thinking_snapshot_fn: Callable[..., Any],
) -> DirectNodeCleanedResponse:
    """Clean the visible direct-node response after provider/tool execution."""

    cleaned_response = sanitize_structured_visual_answer_text(
        response,
        tool_call_events=tool_call_events,
    )
    cleaned_response = sanitize_wiii_house_text(cleaned_response, query=query)
    cleaned_response = strip_direct_inline_private_asides(cleaned_response)
    cleaned_response = strip_dsml_residue(cleaned_response).strip()

    if is_identity_turn:
        cleaned_response = compact_basic_identity_answer(cleaned_response, query=query)

    if (
        is_codebase_analysis_turn
        and not explicit_web_search_turn
        and looks_generic_direct_fallback_response(cleaned_response)
    ):
        cleaned_response = build_codebase_analysis_fallback_answer(query)
        thinking_content = build_codebase_analysis_fallback_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=thinking_content,
            provenance="deterministic_codebase_fallback",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
        )

    return DirectNodeCleanedResponse(
        response=cleaned_response,
        thinking_content=thinking_content,
        tools_used=tools_used,
    )


def apply_source_backed_empty_response_fallback(
    *,
    query: str,
    response: str,
    tools_used: list[Any],
    tool_call_events: list[dict[str, Any]],
    looks_like_search_placeholder_answer: Callable[[str], bool],
    build_search_template_fallback: Callable[..., str],
    inc_counter: Callable[..., Any],
    logger_obj: logging.Logger,
) -> DirectNodeSourceFallback:
    """Use tool evidence to answer when the LLM body is empty or placeholder."""

    if not tool_call_events or (
        str(response or "").strip()
        and not looks_like_search_placeholder_answer(response)
    ):
        return DirectNodeSourceFallback(
            response=response,
            tools_used=tools_used,
            engaged=False,
        )

    try:
        synthesis_template = build_search_template_fallback(
            query=query,
            tool_call_events=tool_call_events,
        )
    except Exception as template_error:
        logger_obj.warning(
            "[DIRECT] Empty-response template fallback build failed: %s",
            template_error,
        )
        synthesis_template = ""

    if not synthesis_template:
        return DirectNodeSourceFallback(
            response=response,
            tools_used=tools_used,
            engaged=False,
        )

    logger_obj.info(
        "[DIRECT] LLM returned empty/placeholder body - engaging "
        "source-backed template fallback (events=%d, len=%d)",
        len(tool_call_events),
        len(synthesis_template),
    )
    try:
        inc_counter(
            "wiii.direct.template_fallback.engaged",
            labels={"trigger": "empty_body"},
        )
    except Exception:
        pass

    if not tools_used:
        empty_body_tool_names = sorted({
            str(event.get("name") or "")
            for event in tool_call_events
            if event.get("type") == "result" and event.get("name")
        })
        tools_used = [{"name": name} for name in empty_body_tool_names if name]

    return DirectNodeSourceFallback(
        response=synthesis_template,
        tools_used=tools_used,
        engaged=True,
    )
