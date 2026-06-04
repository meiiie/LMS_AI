"""Post-dispatch side effects for direct tool results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.direct_handoff_runtime import record_direct_handoff_request
from app.engine.multi_agent.direct_pointy_runtime import handle_direct_pointy_post_dispatch
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_event_sanitizer import sanitize_tool_result_for_event
from app.engine.context.host_action_result_bridge import (
    DEFAULT_HOST_ACTION_RESULT_TIMEOUT_SECONDS,
    parse_host_action_request_result,
    register_host_action_result_request,
    should_wait_for_host_action_result,
    wait_for_host_action_result,
)


PushEvent = Callable[[dict[str, Any]], Awaitable[None]]
MaybeEmitHostAction = Callable[..., Awaitable[None]]
MaybeEmitVisualEvent = Callable[..., Awaitable[tuple[list[str], list[str]]]]
BuildDirectToolReflection = Callable[[Any, str, Any], Awaitable[str]]
PushStatusOnlyProgress = Callable[..., Awaitable[None]]
BuildToolResultMessage = Callable[..., Any]


@dataclass(frozen=True)
class DirectToolPostDispatchState:
    """Updated direct tool-loop state after a tool result is processed."""

    result: Any
    active_visual_session_ids: list[str]
    visual_emitted_any: bool


async def process_direct_tool_post_dispatch(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str,
    result: Any,
    state: AgentState,
    messages: list[Any],
    tool_call_events: list[dict[str, Any]],
    push_event: PushEvent,
    native_tool_messages: bool,
    active_visual_session_ids: list[str],
    visual_session_ids: list[str],
    visual_emitted_any: bool,
    handoffs_enabled: bool,
    maybe_emit_host_action_event: MaybeEmitHostAction,
    maybe_emit_visual_event: MaybeEmitVisualEvent,
    build_direct_tool_reflection: BuildDirectToolReflection,
    push_status_only_progress: PushStatusOnlyProgress,
    build_tool_result_message: BuildToolResultMessage,
    logger_obj: logging.Logger,
) -> DirectToolPostDispatchState:
    """Run the ordered post-dispatch side effects for one direct tool result."""

    pointy_post_dispatch = await handle_direct_pointy_post_dispatch(
        tool_name=tool_name,
        tool_args=tool_args or {},
        result=result,
        state=state,
        push_event=push_event,
        logger_obj=logger_obj,
    )
    updated_result = pointy_post_dispatch.result

    host_action_request = parse_host_action_request_result(tool_name, updated_result)
    host_action_ticket = None
    if host_action_request and should_wait_for_host_action_result(host_action_request.action):
        host_action_ticket = register_host_action_result_request(
            request_id=host_action_request.request_id,
            action=host_action_request.action,
            user_id=state.get("user_id"),
            organization_id=state.get("organization_id"),
        )

    await maybe_emit_host_action_event(
        push_event=push_event,
        tool_name=tool_name,
        result=updated_result,
        node="direct",
        tool_call_events=tool_call_events,
    )
    if host_action_ticket is not None:
        host_action_result = await wait_for_host_action_result(
            host_action_ticket,
            timeout_seconds=DEFAULT_HOST_ACTION_RESULT_TIMEOUT_SECONDS,
        )
        if host_action_result:
            updated_result = json.dumps(host_action_result, ensure_ascii=False)
            tool_call_events.append(
                {
                    "type": "host_action_result",
                    "id": host_action_ticket.request_id,
                    "action": host_action_ticket.action,
                    "success": bool(host_action_result.get("success")),
                    "status": host_action_result.get("status"),
                }
            )
    emitted_visual_session_ids, disposed_visual_session_ids = await maybe_emit_visual_event(
        push_event=push_event,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        result=updated_result,
        node="direct",
        tool_call_events=tool_call_events,
        previous_visual_session_ids=active_visual_session_ids,
    )

    next_active_visual_session_ids = active_visual_session_ids
    next_visual_emitted_any = visual_emitted_any
    if emitted_visual_session_ids:
        visual_session_ids.extend(emitted_visual_session_ids)
        next_active_visual_session_ids = list(dict.fromkeys(emitted_visual_session_ids))
        next_visual_emitted_any = True
    elif disposed_visual_session_ids:
        disposed = set(disposed_visual_session_ids)
        next_active_visual_session_ids = [
            session_id
            for session_id in active_visual_session_ids
            if session_id not in disposed
        ]

    reflection = await build_direct_tool_reflection(state, tool_name, updated_result)
    if reflection:
        await push_status_only_progress(
            push_event,
            node="direct",
            content=reflection,
            subtype="tool_reflection",
        )

    tool_call_events.append(
        {
            "type": "result",
            "name": tool_name,
            "result": sanitize_tool_result_for_event(updated_result),
            "id": tool_call_id,
        }
    )
    messages.append(
        build_tool_result_message(
            str(updated_result),
            tool_call_id=tool_call_id,
            native_tool_messages=native_tool_messages,
        )
    )

    record_direct_handoff_request(
        state=state,
        tool_name=tool_name,
        tool_args=tool_args or {},
        enabled=handoffs_enabled,
        logger_obj=logger_obj,
    )

    return DirectToolPostDispatchState(
        result=updated_result,
        active_visual_session_ids=next_active_visual_session_ids,
        visual_emitted_any=next_visual_emitted_any,
    )
