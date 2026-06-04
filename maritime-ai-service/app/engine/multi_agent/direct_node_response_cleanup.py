"""Direct-node response cleanup and source-backed fallback helpers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any, Callable

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.direct_text_utils import _fold_direct_text


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


_LIVE_LOOKUP_TOOL_NAMES = {
    "tool_web_search",
    "web_search",
    "tool_search_news",
    "search_news",
    "tool_search_legal",
    "search_legal",
    "tool_search_maritime",
    "search_maritime",
    "tool_fetch_url",
    "fetch_url",
    "tool_current_datetime",
    "current_datetime",
    "tool_current_weather",
    "current_weather",
}

_LIVE_LOOKUP_DECORATIVE_SYMBOL_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\u2600-\u27bf"
    "\ufe0f"
    "]"
)
_LIVE_LOOKUP_KAOMOJI_RE = re.compile(
    r"\s*\([^A-Za-z0-9\s)]*[\u02c3\u02c2\u02f6\u2565\ufe4f\u203f][^)]*\)"
)


def _has_live_lookup_event(tool_call_events: list[dict[str, Any]]) -> bool:
    return any(
        str(event.get("name") or "").strip().lower() in _LIVE_LOOKUP_TOOL_NAMES
        for event in tool_call_events or []
        if event.get("type") in {"call", "result"}
    )


def _query_allows_personal_context(query: str) -> bool:
    folded = _fold_direct_text(query)
    return any(
        marker in folded
        for marker in (
            "toi dang",
            "minh dang",
            "toi buon",
            "minh buon",
            "lo lang",
            "tam trang",
            "cam xuc",
            "ve toi",
            "ve minh",
            "cong viec cua toi",
            "cong viec cua minh",
        )
    )


def strip_live_lookup_inferred_personal_context(
    response: str,
    *,
    query: str,
    tool_call_events: list[dict[str, Any]],
) -> str:
    """Remove memory/persona bleed from live lookup answers.

    Live weather/news/web lookups should answer the current factual request.
    Stored memories and relationship context can still be useful elsewhere, but
    here they often create false claims like "you are sad" or unrelated
    maritime/campus framing.
    """

    if (
        not response
        or not _has_live_lookup_event(tool_call_events)
        or _query_allows_personal_context(query)
    ):
        return response

    folded_markers = (
        "minh biet cau dang",
        "minh hieu cau dang",
        "toi biet ban dang",
        "toi hieu ban dang",
        "cau dang buon",
        "ban dang buon",
        "cau dang lo",
        "ban dang lo",
        "minh lo",
        "toi lo",
        "chuan bi gi do",
        "bong",
        "bong ao",
        "bong cua minh",
        "meo bong",
        "meo ao",
        "ke chuyen meo",
        "ke chuyen bong",
        "cuon tron trong chan",
        "nghe nhac nhe",
        "uong tra",
        "o nha nghi ngoi",
        "dung thuc khuya",
        "thuc khuya qua",
        "cau dang hoc khuya",
        "ban dang hoc khuya",
        "dang hoc khuya",
        "hoc khuya",
        "dang hoc bai",
        "hoc bai",
        "cau dang o nha",
        "ban dang o nha",
        "dang o nha",
        "o nha hay di dau",
        "di dau khuya",
        "khuya vay",
        "ngu khong ngon",
        "buon ngu",
        "de met",
        "met lam",
        "nghi mot chut",
    )
    followup_markers = (
        "neu cau muon",
        "neu ban muon",
        "co gi can minh",
        "minh co the giup",
        "minh co the tao",
        "minh co the ve",
        "minh co the lam",
        "minh co the gui",
        "minh co meo",
    )
    parts = re.split(r"(?<=[.!?…])\s+", str(response))
    kept: list[str] = []
    for part in parts:
        folded = _fold_direct_text(part)
        if any(marker in folded for marker in folded_markers):
            continue
        if any(marker in folded for marker in followup_markers):
            continue
        kept.append(part)
    deduped: list[str] = []
    previous_folded = ""
    for item in kept:
        stripped = item.strip()
        if not stripped:
            continue
        folded = _fold_direct_text(stripped)
        if folded and folded == previous_folded:
            continue
        deduped.append(stripped)
        previous_folded = folded

    cleaned = " ".join(deduped).strip()
    cleaned = _LIVE_LOOKUP_DECORATIVE_SYMBOL_RE.sub("", cleaned)
    cleaned = _LIVE_LOOKUP_KAOMOJI_RE.sub("", cleaned)
    cleaned = re.sub(r"\b(cậu|bạn)\s+ơi[~～]*[,!]*\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[~～]+", "", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", cleaned) if item.strip()]
    if len(paragraphs) >= 2:
        first = _fold_direct_text(paragraphs[0])
        second = _fold_direct_text(paragraphs[1])
        if first and second.startswith(first):
            cleaned = "\n\n".join(paragraphs[1:])
    return cleaned or response


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
    cleaned_response = strip_live_lookup_inferred_personal_context(
        cleaned_response,
        query=query,
        tool_call_events=tool_call_events,
    )

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
