"""Direct LLM response tool-call recovery and logging."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable


ExtractRawToolCalls = Callable[..., list[dict[str, Any]]]
ToolNamesFromTools = Callable[[list[Any]], list[str]]
BuildAssistantToolCallMessage = Callable[..., Any]


@dataclass(frozen=True)
class DirectToolCallResponse:
    """LLM response plus the tool calls the direct loop should process."""

    llm_response: Any
    tool_calls: list[Any]


def prepare_direct_tool_call_response(
    *,
    llm_response: Any,
    tools: list[Any],
    native_tool_messages: bool,
    extract_raw_tool_calls_from_text: ExtractRawToolCalls,
    tool_names_from_tools: ToolNamesFromTools,
    build_assistant_tool_call_message: BuildAssistantToolCallMessage,
    logger_obj: logging.Logger,
) -> DirectToolCallResponse:
    """Recover raw text tool calls and log direct LLM tool-call shape."""

    tool_calls = list(getattr(llm_response, "tool_calls", []) or [])
    if tools and not tool_calls:
        raw_tool_calls = extract_raw_tool_calls_from_text(
            getattr(llm_response, "content", ""),
            allowed_tool_names=tool_names_from_tools(tools) or None,
        )
        if raw_tool_calls:
            logger_obj.warning(
                "[DIRECT] Converted raw JSON assistant content into %d structured tool call(s): %s",
                len(raw_tool_calls),
                [call.get("name") for call in raw_tool_calls],
            )
            llm_response = build_assistant_tool_call_message(
                raw_tool_calls,
                native_tool_messages=native_tool_messages,
            )
            tool_calls = list(getattr(llm_response, "tool_calls", raw_tool_calls) or [])

    logger_obj.warning(
        "[DIRECT] LLM response: tool_calls=%d, content_len=%d",
        len(tool_calls) if tool_calls else 0,
        len(str(getattr(llm_response, "content", ""))),
    )
    return DirectToolCallResponse(llm_response=llm_response, tool_calls=tool_calls)
