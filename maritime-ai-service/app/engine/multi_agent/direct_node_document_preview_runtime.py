"""Direct-node uploaded-document preview host-action execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.document_preview_contract import (
    document_preview_forced_tool_choice,
    has_document_preview_host_action_tool,
)
from app.engine.multi_agent.state import AgentState
from app.engine.tools.runtime_context import build_tool_runtime_context


PushEvent = Callable[[dict[str, Any]], Awaitable[None]]
BuildVisualToolRuntimeMetadata = Callable[[AgentState, str], dict[str, Any]]
ExecuteDirectToolRounds = Callable[..., Awaitable[tuple[Any, list[Any], list[dict[str, Any]]]]]
ExtractDirectResponse = Callable[..., tuple[str, str, list[dict[str, Any]]]]
SanitizePreviewResponse = Callable[[str, list[dict[str, Any]]], str]


@dataclass(frozen=True)
class DirectNodeDocumentPreviewResult:
    """Result of one forced direct-node document preview tool round."""

    response: str
    thinking_content: str
    tools_used: list[dict[str, Any]]
    messages: list[Any]
    tool_call_events: list[dict[str, Any]]


def _tools_used_from_preview_events(
    tool_call_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive a stable `tools_used` list from preview tool-call events."""

    tool_names = sorted({
        str(event.get("name") or "")
        for event in tool_call_events
        if event.get("name")
    })
    return [{"name": name} for name in tool_names if name]


def _set_routing_metadata(
    state: AgentState,
    *,
    key: str | None,
    debug: dict[str, Any],
    status: str | None,
    tools: list[Any],
    force_tools: bool,
    error: BaseException | None = None,
) -> None:
    """Store direct-node document preview execution status on routing metadata."""

    if not key or not status:
        return

    routing_meta = state.get("routing_metadata")
    if not isinstance(routing_meta, dict):
        routing_meta = {}
        state["routing_metadata"] = routing_meta

    payload: dict[str, Any] = {
        **debug,
        "status": status,
    }
    if error is None:
        payload.update(
            {
                "tool_count": len(tools),
                "force_tools": force_tools,
            }
        )
    else:
        payload["error"] = type(error).__name__
    routing_meta[key] = payload


async def execute_direct_node_document_preview_round(
    *,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    bus_id: Any,
    tools: list[Any],
    force_tools: bool,
    messages: list[Any],
    push_event: PushEvent,
    build_visual_tool_runtime_metadata: BuildVisualToolRuntimeMetadata,
    execute_direct_tool_rounds: ExecuteDirectToolRounds,
    extract_direct_response: ExtractDirectResponse,
    sanitize_preview_response: SanitizePreviewResponse,
    fallback_response: str = "",
    debug: dict[str, Any] | None = None,
    routing_metadata_key: str | None = None,
    success_status: str | None = None,
    failure_status: str | None = None,
    failure_log_message: str = "[DIRECT] Document preview host action failed: %s",
    logger_obj: logging.Logger | None = None,
) -> DirectNodeDocumentPreviewResult | None:
    """Run the forced preview host action once, returning sanitized state."""

    if not has_document_preview_host_action_tool(tools):
        return None

    debug_payload = dict(debug or {})
    try:
        preview_runtime_context = build_tool_runtime_context(
            event_bus_id=bus_id,
            request_id=ctx.get("request_id"),
            session_id=state.get("session_id"),
            organization_id=state.get("organization_id"),
            user_id=state.get("user_id"),
            user_role=ctx.get("user_role", "student"),
            node="direct",
            source="agentic_loop",
            metadata=build_visual_tool_runtime_metadata(state, query),
        )
        (
            preview_llm_response,
            preview_messages,
            preview_tool_call_events,
        ) = await execute_direct_tool_rounds(
            object(),
            object(),
            messages,
            tools,
            push_event,
            runtime_context_base=preview_runtime_context,
            max_rounds=1,
            query=query,
            state=state,
            forced_tool_choice=document_preview_forced_tool_choice(query, tools),
            llm_base=None,
            native_tool_messages=False,
        )
        if preview_tool_call_events:
            state["tool_call_events"] = preview_tool_call_events

        response, thinking_content, tools_used = extract_direct_response(
            preview_llm_response,
            preview_messages,
        )
        response = sanitize_preview_response(response, preview_tool_call_events)
        if not response and fallback_response:
            response = fallback_response
        if not tools_used:
            tools_used = _tools_used_from_preview_events(preview_tool_call_events)
        if tools_used:
            state["tools_used"] = tools_used

        _set_routing_metadata(
            state,
            key=routing_metadata_key,
            debug=debug_payload,
            status=success_status,
            tools=tools,
            force_tools=force_tools,
        )
        return DirectNodeDocumentPreviewResult(
            response=response,
            thinking_content=thinking_content,
            tools_used=tools_used,
            messages=preview_messages,
            tool_call_events=preview_tool_call_events,
        )
    except Exception as preview_error:  # noqa: BLE001
        _set_routing_metadata(
            state,
            key=routing_metadata_key,
            debug=debug_payload,
            status=failure_status,
            tools=tools,
            force_tools=force_tools,
            error=preview_error,
        )
        if logger_obj is not None:
            logger_obj.warning(failure_log_message, preview_error)
        return None
