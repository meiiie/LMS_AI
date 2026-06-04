"""Search-template early returns for direct tool rounds."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.direct_tool_message_runtime import (
    build_assistant_message,
)
from app.engine.multi_agent.direct_web_search_policy import (
    _force_skills_for_turn,
    _has_search_tool_result,
    _is_weather_lookup_query,
    _should_return_search_template_after_tool_round,
)


def build_direct_post_tool_search_template_response(
    *,
    query: str,
    state: dict[str, Any],
    tool_call_events: list[dict[str, Any]],
    tool_round: int,
    native_tool_messages: bool,
    logger_obj: logging.Logger | None = None,
) -> Any | None:
    """Return a source-backed search template when another LLM round is wasteful."""
    log = logger_obj or logging.getLogger(__name__)
    if _is_weather_lookup_query(query):
        return None
    forced_web_search = "web-search" in _force_skills_for_turn(
        state
    ) and _has_search_tool_result(tool_call_events)
    explicit_web_search = _should_return_search_template_after_tool_round(
        query=query,
        state=state,
        tool_call_events=tool_call_events,
        tool_round=tool_round,
    )
    if not forced_web_search and not explicit_web_search:
        return None

    template_response = ""
    try:
        template_response = build_search_template_fallback(
            query=query,
            tool_call_events=tool_call_events,
        )
    except Exception as template_error:  # noqa: BLE001
        if forced_web_search:
            log.warning(
                "[DIRECT] Forced @web-search template synthesis failed: %s",
                template_error,
            )
        else:
            log.warning(
                "[DIRECT] Explicit web-search template synthesis failed: %s",
                template_error,
            )
        return None

    if not template_response:
        return None

    if forced_web_search:
        log.info(
            "[DIRECT] Forced @web-search returning source-backed template "
            "immediately after tool result (events=%d, len=%d)",
            len(tool_call_events),
            len(template_response),
        )
    else:
        log.info(
            "[DIRECT] Explicit web-search returning source-backed template "
            "after tool evidence (round=%d, events=%d, len=%d)",
            tool_round,
            len(tool_call_events),
            len(template_response),
        )
    return build_assistant_message(
        template_response,
        native_tool_messages=native_tool_messages,
    )
