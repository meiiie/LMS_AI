"""Deterministic uploaded-document host-action execution for direct turns."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_event_sanitizer import (
    sanitize_tool_args_for_event,
    sanitize_tool_result_for_event,
)
from app.engine.reasoning import record_thinking_snapshot


PushEvent = Callable[[dict[str, Any]], Awaitable[None]]
InvokeTool = Callable[..., Awaitable[Any]]
EmitHostAction = Callable[..., Awaitable[None]]
SummarizeToolResult = Callable[[str, Any], Any]
ShouldRequestPreview = Callable[..., bool]
FindHostActionTool = Callable[[list[Any]], Any | None]
BuildHostActionParams = Callable[[str, AgentState | None], dict[str, Any]]
BuildAssistantMessage = Callable[..., Any]
UploadedDocumentAttachments = Callable[[AgentState | None], list[Any]]


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


@dataclass(frozen=True)
class RequestedDocumentHostActionShortcut:
    """Resolved preview-only shortcut selected for the current user turn."""

    shortcut: DocumentHostActionShortcut
    tool: Any
    args: dict[str, Any]
    log_message: str


def resolve_requested_document_host_action_shortcut(
    *,
    query: str,
    state: AgentState,
    tools: list[Any],
    should_request_course_preview: ShouldRequestPreview,
    find_course_host_action_tool: FindHostActionTool,
    build_course_params: BuildHostActionParams,
    course_shortcut: DocumentHostActionShortcut,
    should_request_lesson_preview: ShouldRequestPreview,
    find_lesson_host_action_tool: FindHostActionTool,
    build_lesson_params: BuildHostActionParams,
    lesson_shortcut: DocumentHostActionShortcut,
) -> RequestedDocumentHostActionShortcut | None:
    """Resolve the deterministic uploaded-document preview shortcut for a turn."""

    if should_request_course_preview(query=query, state=state, tools=tools):
        course_tool = find_course_host_action_tool(tools)
        if course_tool is not None:
            return RequestedDocumentHostActionShortcut(
                shortcut=course_shortcut,
                tool=course_tool,
                args=build_course_params(query, state),
                log_message=(
                    "[DIRECT] Deterministic document course host action requested "
                    "(attachments=%d, source_refs=%d)"
                ),
            )

    if should_request_lesson_preview(query=query, state=state, tools=tools):
        preview_tool = find_lesson_host_action_tool(tools)
        if preview_tool is not None:
            return RequestedDocumentHostActionShortcut(
                shortcut=lesson_shortcut,
                tool=preview_tool,
                args=build_lesson_params(query, state),
                log_message=(
                    "[DIRECT] Deterministic document preview host action requested "
                    "(attachments=%d, source_refs=%d)"
                ),
            )

    return None


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

    public_args = sanitize_tool_args_for_event(args)
    await push_event(
        {
            "type": "tool_call",
            "content": {
                "name": shortcut.tool_name,
                "args": public_args,
                "id": shortcut.tool_call_id,
            },
            "node": "direct",
        }
    )
    tool_call_events.append(
        {
            "type": "call",
            "name": shortcut.tool_name,
            "args": public_args,
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
            "result": sanitize_tool_result_for_event(result),
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


async def execute_requested_document_host_action_shortcut(
    *,
    query: str,
    state: AgentState,
    tools: list[Any],
    tool_call_events: list[dict[str, Any]],
    push_event: PushEvent,
    native_tool_messages: bool,
    runtime_context_base: Any,
    invoke_tool_with_runtime: InvokeTool,
    maybe_emit_host_action_event: EmitHostAction,
    summarize_tool_result_for_stream: SummarizeToolResult,
    should_request_course_preview: ShouldRequestPreview,
    find_course_host_action_tool: FindHostActionTool,
    build_course_params: BuildHostActionParams,
    course_shortcut: DocumentHostActionShortcut,
    should_request_lesson_preview: ShouldRequestPreview,
    find_lesson_host_action_tool: FindHostActionTool,
    build_lesson_params: BuildHostActionParams,
    lesson_shortcut: DocumentHostActionShortcut,
    build_assistant_message: BuildAssistantMessage,
    uploaded_document_attachments_from_state: UploadedDocumentAttachments,
    logger_obj: logging.Logger,
) -> Any | None:
    """Execute the requested uploaded-document preview shortcut, if any."""

    request = resolve_requested_document_host_action_shortcut(
        query=query,
        state=state,
        tools=tools,
        should_request_course_preview=should_request_course_preview,
        find_course_host_action_tool=find_course_host_action_tool,
        build_course_params=build_course_params,
        course_shortcut=course_shortcut,
        should_request_lesson_preview=should_request_lesson_preview,
        find_lesson_host_action_tool=find_lesson_host_action_tool,
        build_lesson_params=build_lesson_params,
        lesson_shortcut=lesson_shortcut,
    )
    if request is None:
        return None

    response = await execute_document_host_action_shortcut(
        shortcut=request.shortcut,
        tool=request.tool,
        args=request.args,
        state=state,
        tool_call_events=tool_call_events,
        push_event=push_event,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        maybe_emit_host_action_event=maybe_emit_host_action_event,
        summarize_tool_result_for_stream=summarize_tool_result_for_stream,
        runtime_context_base=runtime_context_base,
        query_snippet=str(request.args.get("title", ""))[:100],
        logger_obj=logger_obj,
    )
    logger_obj.info(
        request.log_message,
        len(uploaded_document_attachments_from_state(state)),
        len(request.args.get("source_references") or []),
    )
    return build_assistant_message(
        response,
        native_tool_messages=native_tool_messages,
    )
