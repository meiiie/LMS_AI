"""Deterministic forced web-search shortcut for direct turns."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
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
    FORCED_WEB_SEARCH_TOOL_NAMES,
    _clean_forced_web_search_query,
    _force_skills_for_turn,
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
    """Execute an explicit forced web-search turn without planner LLM routing."""
    log = logger_obj or logging.getLogger(__name__)
    if not tools or "web-search" not in _force_skills_for_turn(state):
        return None

    forced_search_tool = None
    forced_search_tool_name = ""
    for candidate_name in FORCED_WEB_SEARCH_TOOL_NAMES:
        forced_search_tool = get_tool_by_name(tools, candidate_name)
        if forced_search_tool:
            forced_search_tool_name = candidate_name
            break
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
            },
            "node": "direct",
        }
    )
    sources = extract_source_infos_from_tool_result(forced_search_tool_name, result)
    if sources:
        await push_event(
            {
                "type": "sources",
                "content": sources,
                "node": "direct",
            }
        )
    tool_call_events.append(
        {
            "type": "result",
            "name": forced_search_tool_name,
            "result": sanitize_tool_result_for_event(result),
            "id": tc_id,
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
