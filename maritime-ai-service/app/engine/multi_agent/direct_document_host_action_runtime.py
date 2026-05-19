"""Deterministic uploaded-document host-action execution for direct turns."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import record_thinking_snapshot


PushEvent = Callable[[dict[str, Any]], Awaitable[None]]
InvokeTool = Callable[..., Awaitable[Any]]
EmitHostAction = Callable[..., Awaitable[None]]
SummarizeToolResult = Callable[[str, Any], Any]


@dataclass(frozen=True)
class DocumentHostActionShortcut:
    """Immutable contract for a preview-only uploaded-document host action."""

    tool_name: str
    tool_call_id: str
    thinking: str
    thinking_summary: str
    thinking_provenance: str
    response: str
    failure_log_message: str


async def execute_document_host_action_shortcut(
    *,
    shortcut: DocumentHostActionShortcut,
    tool: Any,
    args: dict[str, Any],
    state: AgentState,
    tool_call_events: list[dict[str, Any]],
    push_event: PushEvent,
    invoke_tool_with_runtime: InvokeTool,
    maybe_emit_host_action_event: EmitHostAction,
    summarize_tool_result_for_stream: SummarizeToolResult,
    runtime_context_base: Any,
    query_snippet: str,
    logger_obj: logging.Logger,
) -> str:
    """Execute a preview host action and return the user-visible response."""

    await push_event(
        {
            "type": "tool_call",
            "content": {
                "name": shortcut.tool_name,
                "args": args,
                "id": shortcut.tool_call_id,
            },
            "node": "direct",
        }
    )
    tool_call_events.append(
        {
            "type": "call",
            "name": shortcut.tool_name,
            "args": args,
            "id": shortcut.tool_call_id,
        }
    )

    try:
        result = await invoke_tool_with_runtime(
            tool,
            args,
            tool_name=shortcut.tool_name,
            runtime_context_base=runtime_context_base,
            tool_call_id=shortcut.tool_call_id,
            query_snippet=query_snippet,
            prefer_async=False,
            run_sync_in_thread=True,
        )
    except Exception as tool_error:  # noqa: BLE001
        logger_obj.warning(shortcut.failure_log_message, tool_error)
        result = "Tool unavailable"

    await push_event(
        {
            "type": "tool_result",
            "content": {
                "name": shortcut.tool_name,
                "result": summarize_tool_result_for_stream(shortcut.tool_name, result),
                "id": shortcut.tool_call_id,
            },
            "node": "direct",
        }
    )
    await maybe_emit_host_action_event(
        push_event=push_event,
        tool_name=shortcut.tool_name,
        result=result,
        node="direct",
        tool_call_events=tool_call_events,
    )
    tool_call_events.append(
        {
            "type": "result",
            "name": shortcut.tool_name,
            "result": str(result),
            "id": shortcut.tool_call_id,
        }
    )

    state["thinking"] = shortcut.thinking
    state["thinking_content"] = shortcut.thinking
    record_thinking_snapshot(
        state,
        shortcut.thinking,
        node="direct",
        provenance=shortcut.thinking_provenance,
    )
    await push_event(
        {
            "type": "thinking_start",
            "content": "",
            "node": "direct",
            "summary": shortcut.thinking_summary,
        }
    )
    await push_event(
        {
            "type": "thinking_delta",
            "content": shortcut.thinking,
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
    return shortcut.response
