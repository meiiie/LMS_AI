"""Deterministic forced web-search shortcut for direct turns."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.direct_tool_event_metadata import (
    build_tool_result_event_metadata,
)
from app.engine.multi_agent.direct_tool_sources import (
    extract_source_infos_from_tool_result,
)
from app.engine.multi_agent.direct_tool_message_runtime import (
    build_assistant_message,
)
from app.engine.multi_agent.tool_event_sanitizer import (
    sanitize_tool_args_for_event,
    sanitize_tool_result_for_event,
)
from app.engine.multi_agent.direct_web_search_policy import (
    FORCED_WEB_FETCH_TOOL_NAMES,
    FORCED_WEB_SEARCH_TOOL_NAMES,
    _clean_forced_web_search_query,
    _extract_first_url,
    _force_skills_for_turn,
    _is_explicit_web_fetch_turn,
)
from app.engine.reasoning import record_thinking_snapshot


_FORCED_WEB_SEARCH_FALLBACK = (
    "Mình đã thử tra cứu web, nhưng chưa lấy được nguồn đủ rõ "
    "để tổng hợp chắc tay cho lượt này. Cậu thử đổi từ khóa "
    "hẹp hơn một chút nhé."
)
_FORCED_WEB_SEARCH_THINKING = (
    "Mình sẽ tra cứu web bằng truy vấn đã làm sạch, đọc URL/snippet trả về, "
    "rồi chỉ tổng hợp phần có nguồn. Nếu kết quả quá mỏng, mình sẽ nói rõ "
    "thay vì đoán."
)


_FORCED_WEB_FETCH_FALLBACK = (
    "Minh da mo URL ban dua nhung chua doc duoc noi dung du ro de tra loi chac tay."
)
_FORCED_WEB_FETCH_THINKING = (
    "Minh doc truc tiep URL bang tool_fetch_url, giu nguon kem tool call, "
    "roi chi tra loi tu noi dung fetch duoc."
)


def _tool_by_any_name(
    *,
    tools: list[Any],
    candidate_names: tuple[str, ...],
    get_tool_by_name: Callable[[list[Any], str], Any],
) -> tuple[Any | None, str]:
    for candidate_name in candidate_names:
        candidate = get_tool_by_name(tools, candidate_name)
        if candidate:
            return candidate, candidate_name
    return None, ""


def _looks_h1_fetch_request(query: str) -> bool:
    folded = " ".join(str(query or "").casefold().split())
    return any(
        marker in folded
        for marker in (
            "h1",
            "heading",
            "tieu de",
            "tiêu đề",
        )
    )


def _extract_prefixed_heading(lines: list[str], prefixes: tuple[str, ...]) -> str:
    for line in lines:
        lowered = line.casefold()
        for prefix in prefixes:
            marker = f"{prefix.casefold()}:"
            if lowered.startswith(marker):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    return ""


def _extract_fetch_heading(result: Any, *, prefer_h1: bool = False) -> str:
    """Extract the first real page heading from a web_fetch markdown result."""

    lines = [raw_line.strip() for raw_line in str(result or "").splitlines()]
    lines = [line for line in lines if line]

    if prefer_h1:
        h1_heading = _extract_prefixed_heading(lines, ("h1",))
        if h1_heading:
            return h1_heading

    title_heading = _extract_prefixed_heading(lines, ("title",))

    for line in lines:
        lowered = line.lower()
        if lowered.startswith("_(via ") or lowered.startswith("(via "):
            continue
        if line.startswith("#"):
            candidate = line.lstrip("#").strip()
            if candidate.startswith("http://") or candidate.startswith("https://"):
                continue
            if candidate.lower().startswith("title:"):
                candidate = candidate.split(":", 1)[1].strip()
            if candidate:
                return candidate
        if line.startswith("http://") or line.startswith("https://"):
            continue
        if len(line) <= 120:
            if line.lower().startswith("title:"):
                line = line.split(":", 1)[1].strip()
            if line.lower().startswith("h1:"):
                line = line.split(":", 1)[1].strip()
            return line
    return title_heading


def _build_forced_fetch_response(
    *,
    query: str,
    result: Any,
    tool_call_events: list[dict[str, Any]],
) -> str:
    wants_h1 = _looks_h1_fetch_request(query)
    heading = _extract_fetch_heading(result, prefer_h1=wants_h1)
    if wants_h1 and heading:
        return f"H1: {heading}"

    try:
        template_response = build_search_template_fallback(
            query=query,
            tool_call_events=tool_call_events,
        )
    except Exception:  # noqa: BLE001
        template_response = ""
    if template_response:
        return template_response
    if heading:
        return f"Minh da doc URL nay. Tieu de noi bat: {heading}"
    return _FORCED_WEB_FETCH_FALLBACK


async def _execute_forced_web_fetch_shortcut(
    *,
    query: str,
    state: dict[str, Any],
    tools: list[Any],
    messages: list[Any],
    tool_call_events: list[dict[str, Any]],
    push_event: Callable[[dict[str, Any]], Awaitable[Any]],
    native_tool_messages: bool,
    runtime_context_base: Any,
    get_tool_by_name: Callable[[list[Any], str], Any],
    invoke_tool_with_runtime: Callable[..., Awaitable[Any]],
    summarize_tool_result_for_stream: Callable[[str, Any], Any],
    logger_obj: logging.Logger | None = None,
) -> Any | None:
    """Execute explicit URL fetch without asking the chat model to call a tool."""

    log = logger_obj or logging.getLogger(__name__)
    if not tools or not _is_explicit_web_fetch_turn(query, state):
        return None
    url = _extract_first_url(query)
    if not url:
        return None

    forced_fetch_tool, forced_fetch_tool_name = _tool_by_any_name(
        tools=tools,
        candidate_names=FORCED_WEB_FETCH_TOOL_NAMES,
        get_tool_by_name=get_tool_by_name,
    )
    if forced_fetch_tool is None:
        return None

    tc_id = "forced_web_fetch_0"
    tc_args = {"url": url}
    public_tc_args = sanitize_tool_args_for_event(tc_args)
    await push_event(
        {
            "type": "tool_call",
            "content": {
                "name": forced_fetch_tool_name,
                "args": public_tc_args,
                "id": tc_id,
            },
            "node": "direct",
        }
    )
    tool_call_events.append(
        {
            "type": "call",
            "name": forced_fetch_tool_name,
            "args": public_tc_args,
            "id": tc_id,
        }
    )
    try:
        result = await invoke_tool_with_runtime(
            forced_fetch_tool,
            tc_args,
            tool_name=forced_fetch_tool_name,
            runtime_context_base=runtime_context_base,
            tool_call_id=tc_id,
            query_snippet=url[:100],
            prefer_async=False,
            run_sync_in_thread=True,
        )
    except Exception as tool_error:  # noqa: BLE001
        log.warning("[DIRECT] Forced web_fetch tool failed: %s", tool_error)
        result = "Tool unavailable"

    sources = extract_source_infos_from_tool_result(forced_fetch_tool_name, result)
    metadata = build_tool_result_event_metadata(
        forced_fetch_tool_name,
        result,
        sources=sources,
    )
    await push_event(
        {
            "type": "tool_result",
            "content": {
                "name": forced_fetch_tool_name,
                "result": summarize_tool_result_for_stream(
                    forced_fetch_tool_name,
                    result,
                ),
                "id": tc_id,
                "metadata": metadata,
            },
            "node": "direct",
        }
    )
    if sources:
        await push_event(
            {
                "type": "sources",
                "content": sources,
                "node": "direct",
                "details": {
                    "tool_call_id": tc_id,
                    "tool_name": forced_fetch_tool_name,
                },
            }
        )
    tool_call_events.append(
        {
            "type": "result",
            "name": forced_fetch_tool_name,
            "result": sanitize_tool_result_for_event(result),
            "id": tc_id,
            "metadata": metadata,
        }
    )

    response = _build_forced_fetch_response(
        query=query,
        result=result,
        tool_call_events=tool_call_events,
    )
    messages.append(
        build_assistant_message(
            response,
            native_tool_messages=native_tool_messages,
        )
    )

    state["thinking"] = _FORCED_WEB_FETCH_THINKING
    state["thinking_content"] = _FORCED_WEB_FETCH_THINKING
    record_thinking_snapshot(
        state,
        _FORCED_WEB_FETCH_THINKING,
        node="direct",
        provenance="deterministic_forced_web_fetch",
    )
    await push_event(
        {
            "type": "thinking_start",
            "content": "",
            "node": "direct",
            "summary": "Doc URL truc tiep",
        }
    )
    await push_event(
        {
            "type": "thinking_delta",
            "content": _FORCED_WEB_FETCH_THINKING,
            "node": "direct",
        }
    )
    await push_event(
        {
            "type": "thinking_end",
            "content": "",
            "node": "direct",
        }
    )
    log.info(
        "[DIRECT] Forced web_fetch executed deterministically "
        "without planner LLM (events=%d, len=%d)",
        len(tool_call_events),
        len(response),
    )
    return build_assistant_message(
        response,
        native_tool_messages=native_tool_messages,
    )


async def execute_forced_web_search_shortcut(
    *,
    query: str,
    state: dict[str, Any],
    tools: list[Any],
    messages: list[Any],
    tool_call_events: list[dict[str, Any]],
    push_event: Callable[[dict[str, Any]], Awaitable[Any]],
    native_tool_messages: bool,
    runtime_context_base: Any,
    get_tool_by_name: Callable[[list[Any], str], Any],
    invoke_tool_with_runtime: Callable[..., Awaitable[Any]],
    summarize_tool_result_for_stream: Callable[[str, Any], Any],
    logger_obj: logging.Logger | None = None,
) -> Any | None:
    """Execute an explicit forced web-search/fetch turn without planner LLM routing."""
    log = logger_obj or logging.getLogger(__name__)
    forced_fetch_response = await _execute_forced_web_fetch_shortcut(
        query=query,
        state=state,
        tools=tools,
        messages=messages,
        tool_call_events=tool_call_events,
        push_event=push_event,
        native_tool_messages=native_tool_messages,
        runtime_context_base=runtime_context_base,
        get_tool_by_name=get_tool_by_name,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        summarize_tool_result_for_stream=summarize_tool_result_for_stream,
        logger_obj=log,
    )
    if forced_fetch_response is not None:
        return forced_fetch_response

    if not tools or "web-search" not in _force_skills_for_turn(state):
        return None

    forced_search_tool, forced_search_tool_name = _tool_by_any_name(
        tools=tools,
        candidate_names=FORCED_WEB_SEARCH_TOOL_NAMES,
        get_tool_by_name=get_tool_by_name,
    )
    if forced_search_tool is None:
        return None

    tc_id = "forced_web_search_0"
    tc_args = {"query": _clean_forced_web_search_query(query)}
    public_tc_args = sanitize_tool_args_for_event(tc_args)
    await push_event(
        {
            "type": "tool_call",
            "content": {
                "name": forced_search_tool_name,
                "args": public_tc_args,
                "id": tc_id,
            },
            "node": "direct",
        }
    )
    tool_call_events.append(
        {
            "type": "call",
            "name": forced_search_tool_name,
            "args": public_tc_args,
            "id": tc_id,
        }
    )
    try:
        result = await invoke_tool_with_runtime(
            forced_search_tool,
            tc_args,
            tool_name=forced_search_tool_name,
            runtime_context_base=runtime_context_base,
            tool_call_id=tc_id,
            query_snippet=str(tc_args.get("query", ""))[:100],
            prefer_async=False,
            run_sync_in_thread=True,
        )
    except Exception as tool_error:  # noqa: BLE001
        log.warning("[DIRECT] Forced @web-search tool failed: %s", tool_error)
        result = "Tool unavailable"

    sources = extract_source_infos_from_tool_result(forced_search_tool_name, result)
    metadata = build_tool_result_event_metadata(
        forced_search_tool_name,
        result,
        sources=sources,
    )
    await push_event(
        {
            "type": "tool_result",
            "content": {
                "name": forced_search_tool_name,
                "result": summarize_tool_result_for_stream(
                    forced_search_tool_name,
                    result,
                ),
                "id": tc_id,
                "metadata": metadata,
            },
            "node": "direct",
        }
    )
    if sources:
        await push_event(
            {
                "type": "sources",
                "content": sources,
                "node": "direct",
                "details": {
                    "tool_call_id": tc_id,
                    "tool_name": forced_search_tool_name,
                },
            }
        )
    tool_call_events.append(
        {
            "type": "result",
            "name": forced_search_tool_name,
            "result": sanitize_tool_result_for_event(result),
            "id": tc_id,
            "metadata": metadata,
        }
    )

    template_response = ""
    try:
        template_response = build_search_template_fallback(
            query=query,
            tool_call_events=tool_call_events,
        )
    except Exception as template_error:  # noqa: BLE001
        log.warning("[DIRECT] Forced @web-search template synthesis failed: %s", template_error)
    if not template_response:
        template_response = _FORCED_WEB_SEARCH_FALLBACK

    state["thinking"] = _FORCED_WEB_SEARCH_THINKING
    state["thinking_content"] = _FORCED_WEB_SEARCH_THINKING
    record_thinking_snapshot(
        state,
        _FORCED_WEB_SEARCH_THINKING,
        node="direct",
        provenance="deterministic_forced_web_search",
    )
    await push_event(
        {
            "type": "thinking_start",
            "content": "",
            "node": "direct",
            "summary": "Tra cứu web có nguồn",
        }
    )
    await push_event(
        {
            "type": "thinking_delta",
            "content": _FORCED_WEB_SEARCH_THINKING,
            "node": "direct",
        }
    )
    await push_event(
        {
            "type": "thinking_end",
            "content": "",
            "node": "direct",
        }
    )
    log.info(
        "[DIRECT] Forced @web-search executed deterministically "
        "without planner LLM (events=%d, len=%d)",
        len(tool_call_events),
        len(template_response),
    )
    return build_assistant_message(
        template_response,
        native_tool_messages=native_tool_messages,
    )
