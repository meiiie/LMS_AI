"""Execution of one direct tool round."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.state import AgentState


PushEvent = Callable[[dict[str, Any]], Awaitable[None]]
NormalizeToolCall = Callable[[Any], dict[str, Any]]
InferDirectReasoningCue = Callable[[str, AgentState, list[str]], str]
CollectActiveVisualSessionIds = Callable[[AgentState], list[str]]
DispatchDirectToolCall = Callable[..., Awaitable[Any]]
ProcessDirectToolPostDispatch = Callable[..., Awaitable[Any]]
EmitVisualCommitEvents = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class DirectToolRoundExecution:
    """State emitted by one direct tool round."""

    round_tool_names: list[str]
    round_cue: str
    visual_emitted_any: bool


async def execute_direct_tool_round(
    *,
    llm_response: Any,
    tool_round: int,
    tools: list[Any],
    query: str,
    state: AgentState,
    messages: list[Any],
    tool_call_events: list[dict[str, Any]],
    push_event: PushEvent,
    native_tool_messages: bool,
    visual_emitted_any: bool,
    runtime_context_base: Any,
    handoffs_enabled: bool,
    get_tool_by_name: Callable[..., Any],
    invoke_tool_with_runtime: Callable[..., Awaitable[Any]],
    is_search_tool_name: Callable[[str], bool],
    prefer_official_query_for_known_docs: Callable[..., dict[str, Any]],
    summarize_tool_result_for_stream: Callable[[str, Any], Any],
    maybe_emit_host_action_event: Callable[..., Awaitable[None]],
    maybe_emit_visual_event: Callable[..., Awaitable[tuple[list[str], list[str]]]],
    emit_visual_commit_events: EmitVisualCommitEvents,
    build_direct_tool_reflection: Callable[[Any, str, Any], Awaitable[str]],
    push_status_only_progress: Callable[..., Awaitable[None]],
    build_tool_result_message: Callable[..., Any],
    normalize_tool_call: NormalizeToolCall,
    infer_direct_reasoning_cue: InferDirectReasoningCue,
    collect_active_visual_session_ids: CollectActiveVisualSessionIds,
    dispatch_direct_tool_call: DispatchDirectToolCall,
    process_direct_tool_post_dispatch: ProcessDirectToolPostDispatch,
    logger_obj: logging.Logger,
) -> DirectToolRoundExecution:
    """Normalize, dispatch, and finalize all tool calls for one round."""

    normalized_tool_calls = [
        normalize_tool_call(tool_call) for tool_call in llm_response.tool_calls
    ]
    round_tool_names = [
        str(tool_call.get("name", "unknown"))
        for tool_call in normalized_tool_calls
        if tool_call.get("name")
    ]
    round_cue = infer_direct_reasoning_cue(query, state, round_tool_names)
    messages.append(llm_response)
    visual_session_ids: list[str] = []
    active_visual_session_ids = collect_active_visual_session_ids(state)

    next_visual_emitted_any = visual_emitted_any
    for tool_call in normalized_tool_calls:
        dispatch_result = await dispatch_direct_tool_call(
            tool_call=tool_call,
            tool_round=tool_round,
            tools=tools,
            query=query,
            push_event=push_event,
            tool_call_events=tool_call_events,
            get_tool_by_name=get_tool_by_name,
            invoke_tool_with_runtime=invoke_tool_with_runtime,
            runtime_context_base=runtime_context_base,
            is_search_tool_name=is_search_tool_name,
            prefer_official_query_for_known_docs=prefer_official_query_for_known_docs,
            summarize_tool_result_for_stream=summarize_tool_result_for_stream,
            logger_obj=logger_obj,
        )
        post_dispatch = await process_direct_tool_post_dispatch(
            tool_name=dispatch_result.tool_name,
            tool_args=dispatch_result.tool_args or {},
            tool_call_id=dispatch_result.tool_call_id,
            result=dispatch_result.result,
            state=state,
            messages=messages,
            tool_call_events=tool_call_events,
            push_event=push_event,
            native_tool_messages=native_tool_messages,
            active_visual_session_ids=active_visual_session_ids,
            visual_session_ids=visual_session_ids,
            visual_emitted_any=next_visual_emitted_any,
            handoffs_enabled=handoffs_enabled,
            maybe_emit_host_action_event=maybe_emit_host_action_event,
            maybe_emit_visual_event=maybe_emit_visual_event,
            build_direct_tool_reflection=build_direct_tool_reflection,
            push_status_only_progress=push_status_only_progress,
            build_tool_result_message=build_tool_result_message,
            logger_obj=logger_obj,
        )
        active_visual_session_ids = post_dispatch.active_visual_session_ids
        next_visual_emitted_any = post_dispatch.visual_emitted_any

    await emit_visual_commit_events(
        push_event=push_event,
        node="direct",
        visual_session_ids=visual_session_ids,
        tool_call_events=tool_call_events,
    )
    return DirectToolRoundExecution(
        round_tool_names=round_tool_names,
        round_cue=round_cue,
        visual_emitted_any=next_visual_emitted_any,
    )
