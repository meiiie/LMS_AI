"""Runtime helpers for TutorAgentNode tool dispatch."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from app.engine.messages import Message, ToolCall
from app.engine.multi_agent.tool_policy_session import resolve_tool_policy_denial
from app.engine.multi_agent.visual_events import (
    _emit_visual_commit_events,
    _maybe_emit_visual_event,
    _summarize_tool_result_for_stream,
)


def _tool_call_dict_to_native(tool_call: dict[str, Any]) -> ToolCall:
    """Translate the LC-style ``{"name", "args", "id"}`` dict to a native ToolCall."""
    raw_args = tool_call.get("args") or {}
    if not isinstance(raw_args, dict):
        raw_args = {"value": raw_args}
    return ToolCall(
        id=str(tool_call.get("id") or ""),
        name=str(tool_call.get("name") or ""),
        arguments=raw_args,
    )


def _is_visual_result_tool(tool_name: str) -> bool:
    lowered_tool_name = str(tool_name or "").lower()
    return "visual" in lowered_tool_name or "chart" in lowered_tool_name


@dataclass(slots=True)
class TutorToolDispatchResult:
    """Outcome of a single tutor tool execution."""

    phase_transition_count: int
    last_tool_was_progress: bool = False
    should_break_loop: bool = False
    tool_result_text: str | None = None
    tool_args: dict[str, Any] | None = None


def _append_tool_observation(
    *,
    messages: list[Any],
    tool_call: dict[str, Any],
    tool_id: str,
    result: Any,
) -> None:
    messages.append(
        Message(
            role="assistant",
            content="",
            tool_calls=[_tool_call_dict_to_native(tool_call)],
        )
    )
    messages.append(
        Message(role="tool", content=str(result), tool_call_id=tool_id)
    )


def _append_tool_error(
    *,
    messages: list[Any],
    tool_call: dict[str, Any],
    tool_id: str,
    error: Exception,
) -> None:
    messages.append(
        Message(
            role="assistant",
            content="",
            tool_calls=[_tool_call_dict_to_native(tool_call)],
        )
    )
    messages.append(
        Message(role="tool", content=f"Error: {str(error)}", tool_call_id=tool_id)
    )


async def _emit_tool_result(
    *,
    push: Callable[[dict[str, Any]], Awaitable[None]],
    tool_name: str,
    result: Any,
    tool_id: str,
) -> None:
    await push(
        {
            "type": "tool_result",
            "content": {
                "name": tool_name,
                "result": str(result)[:500],
                "id": tool_id,
            },
            "node": "tutor_agent",
        }
    )


async def _emit_visual_lifecycle_if_available(
    *,
    push: Callable[[dict[str, Any]], Awaitable[None]],
    tool_name: str,
    result: Any,
    tool_id: str,
    logger_obj: Any,
) -> None:
    """Forward structured visual payloads onto the same SSE lifecycle as direct."""
    if not _is_visual_result_tool(tool_name):
        return

    visual_tool_call_events: list[dict[str, Any]] = []
    try:
        visual_session_ids, _disposed_session_ids = await _maybe_emit_visual_event(
            push_event=push,
            tool_name=tool_name,
            tool_call_id=tool_id,
            result=result,
            node="tutor_agent",
            tool_call_events=visual_tool_call_events,
        )
        if visual_session_ids:
            await _emit_visual_commit_events(
                push_event=push,
                node="tutor_agent",
                visual_session_ids=visual_session_ids,
                tool_call_events=visual_tool_call_events,
            )
    except Exception as exc:
        logger_obj.warning("[TUTOR_AGENT] Visual lifecycle emit skipped: %s", exc)


async def _emit_tool_acknowledgment(
    *,
    query: str,
    context: dict[str, Any],
    tool_name: str,
    result: Any,
    tool_acknowledgment_fn: Callable[..., Awaitable[str]],
    push_thinking_deltas: Callable[[str], Awaitable[None]],
) -> None:
    ack = await tool_acknowledgment_fn(
        query=query,
        context=context,
        tool_name=tool_name,
        result=result,
    )
    if ack and str(ack).strip():
        await push_thinking_deltas(f"\n\n{ack}")


def _record_tool_use(
    *,
    tools_used: list[dict[str, Any]],
    tool_name: str,
    tool_args: dict[str, Any],
    description: str,
    iteration: int,
) -> None:
    tools_used.append(
        {
            "name": tool_name,
            "args": tool_args,
            "description": description,
            "iteration": iteration + 1,
        }
    )


async def deny_tutor_tool_call_by_policy(
    *,
    state: dict[str, Any] | None,
    tool_call: dict[str, Any],
    iteration: int,
    messages: list[Any],
    push: Callable[[dict[str, Any]], Awaitable[None]],
    phase_transition_count: int,
    logger_obj: Any,
) -> TutorToolDispatchResult | None:
    """Emit a visible policy denial when tutor receives an out-of-session tool call."""

    tool_name = str(tool_call.get("name", "") or "")
    tool_args = tool_call.get("args", {}) or {}
    if not isinstance(tool_args, dict):
        tool_args = {"value": tool_args}
        tool_call["args"] = tool_args
    tool_id = str(tool_call.get("id") or f"call_{iteration}")

    denial = resolve_tool_policy_denial(state, tool_name.strip())
    if denial is None:
        return None

    decision, message = denial
    policy_payload = {
        "allowed": False,
        "path": decision.path,
        "reason": decision.reason,
    }
    logger_obj.warning(
        "[TUTOR_AGENT] Tool policy denied tool=%r path=%s reason=%s",
        tool_name,
        decision.path,
        decision.reason,
    )
    await push(
        {
            "type": "tool_call",
            "content": {
                "name": tool_name,
                "args": tool_args,
                "id": tool_id,
                "policy": policy_payload,
            },
            "node": "tutor_agent",
        }
    )
    await _emit_tool_result(
        push=push,
        tool_name=tool_name,
        result=message,
        tool_id=tool_id,
    )
    _append_tool_observation(
        messages=messages,
        tool_call=tool_call,
        tool_id=tool_id,
        result=message,
    )
    return TutorToolDispatchResult(
        phase_transition_count=phase_transition_count,
        tool_result_text=message,
        tool_args=tool_args,
    )


async def dispatch_tutor_tool_call(
    *,
    tool_call: dict[str, Any],
    query: str,
    context: dict[str, Any],
    iteration: int,
    tools_used: list[dict[str, Any]],
    tools: Sequence[Any],
    messages: list[Any],
    runtime_context_base: dict[str, Any],
    push: Callable[[dict[str, Any]], Awaitable[None]],
    push_thinking_deltas: Callable[[str], Awaitable[None]],
    iteration_beat_fn: Callable[..., Awaitable[Any]],
    tool_acknowledgment_fn: Callable[..., Awaitable[str]],
    get_tool_by_name_fn: Callable[..., Any],
    invoke_tool_with_runtime_fn: Callable[..., Awaitable[Any]],
    get_last_confidence_fn: Callable[[], tuple[float, bool]],
    knowledge_tool: Any,
    calculator_tool: Any,
    datetime_tool: Any,
    web_search_tool: Any,
    max_iterations: int,
    max_phase_transitions: int,
    phase_transition_count: int,
    logger_obj: Any,
) -> TutorToolDispatchResult:
    """Execute one tutor tool call while preserving tutor-node contracts."""

    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})
    tool_id = tool_call.get("id", f"call_{iteration}")

    if tool_name in ("tool_knowledge_search", "tool_maritime_search"):
        try:
            search_query = tool_args.get("query", query)
            result = await invoke_tool_with_runtime_fn(
                knowledge_tool,
                {"query": search_query},
                tool_name=tool_name,
                runtime_context_base=runtime_context_base,
                tool_call_id=tool_id,
                query_snippet=search_query,
            )

            _record_tool_use(
                tools_used=tools_used,
                tool_name=tool_name,
                tool_args=tool_args,
                description=(
                    f"Tra cuu: {search_query[:60]}..."
                    if len(search_query) > 60
                    else f"Tra cuu: {search_query}"
                ),
                iteration=iteration,
            )
            await _emit_tool_result(
                push=push,
                tool_name=tool_name,
                result=result,
                tool_id=tool_id,
            )
            await _emit_tool_acknowledgment(
                query=query,
                context=context,
                tool_name=tool_name,
                result=result,
                tool_acknowledgment_fn=tool_acknowledgment_fn,
                push_thinking_deltas=push_thinking_deltas,
            )
            _append_tool_observation(
                messages=messages,
                tool_call=tool_call,
                tool_id=tool_id,
                result=result,
            )

            logger_obj.info("[TUTOR_AGENT] Tool result length: %d", len(str(result)))
            confidence, is_complete = get_last_confidence_fn()
            if is_complete and confidence >= 0.70:
                logger_obj.info(
                    "[TUTOR_AGENT] MEDIUM+ confidence (%.2f) - EARLY TERMINATION",
                    confidence,
                )
                logger_obj.info(
                    "[TUTOR_AGENT] Skipping %d remaining iterations (Focused ReAct)",
                    max_iterations - iteration - 1,
                )
                return TutorToolDispatchResult(
                    phase_transition_count=phase_transition_count,
                    should_break_loop=True,
                    tool_result_text=str(result),
                    tool_args=tool_args,
                )
            if confidence >= 0.50:
                logger_obj.info(
                    "[TUTOR_AGENT] LOW-MEDIUM confidence (%.2f) - one more try",
                    confidence,
                )
            else:
                logger_obj.info(
                    "[TUTOR_AGENT] LOW confidence (%.2f) - will retry",
                    confidence,
                )
            return TutorToolDispatchResult(
                phase_transition_count=phase_transition_count,
                tool_args=tool_args,
            )
        except Exception as exc:
            logger_obj.error("[TUTOR_AGENT] Tool error: %s", exc)
            _append_tool_error(
                messages=messages,
                tool_call=tool_call,
                tool_id=tool_id,
                error=exc,
            )
            return TutorToolDispatchResult(phase_transition_count=phase_transition_count)

    if tool_name in ("tool_calculator", "tool_current_datetime", "tool_web_search"):
        try:
            if tool_name == "tool_calculator":
                tool_input = tool_args.get("expression", "")
                result = await invoke_tool_with_runtime_fn(
                    calculator_tool,
                    tool_input,
                    tool_name=tool_name,
                    runtime_context_base=runtime_context_base,
                    tool_call_id=tool_id,
                    query_snippet=tool_input,
                )
                desc = f"Tinh toan: {tool_input[:60]}"
            elif tool_name == "tool_current_datetime":
                tool_input = tool_args.get("dummy", "")
                result = await invoke_tool_with_runtime_fn(
                    datetime_tool,
                    tool_input,
                    tool_name=tool_name,
                    runtime_context_base=runtime_context_base,
                    tool_call_id=tool_id,
                )
                desc = "Xem ngay gio hien tai"
            else:
                tool_input = tool_args.get("query", query)
                result = await invoke_tool_with_runtime_fn(
                    web_search_tool,
                    tool_input,
                    tool_name=tool_name,
                    runtime_context_base=runtime_context_base,
                    tool_call_id=tool_id,
                    query_snippet=tool_input,
                )
                desc = f"Tim web: {tool_input[:60]}"

            _record_tool_use(
                tools_used=tools_used,
                tool_name=tool_name,
                tool_args=tool_args,
                description=desc,
                iteration=iteration,
            )
            await _emit_tool_result(
                push=push,
                tool_name=tool_name,
                result=result,
                tool_id=tool_id,
            )
            await _emit_tool_acknowledgment(
                query=query,
                context=context,
                tool_name=tool_name,
                result=result,
                tool_acknowledgment_fn=tool_acknowledgment_fn,
                push_thinking_deltas=push_thinking_deltas,
            )
            _append_tool_observation(
                messages=messages,
                tool_call=tool_call,
                tool_id=tool_id,
                result=result,
            )
            logger_obj.info(
                "[TUTOR_AGENT] %s result length: %d",
                tool_name,
                len(str(result)),
            )
            return TutorToolDispatchResult(
                phase_transition_count=phase_transition_count,
                tool_result_text=str(result),
                tool_args=tool_args,
            )
        except Exception as exc:
            logger_obj.error("[TUTOR_AGENT] %s error: %s", tool_name, exc)
            _append_tool_error(
                messages=messages,
                tool_call=tool_call,
                tool_id=tool_id,
                error=exc,
            )
            return TutorToolDispatchResult(phase_transition_count=phase_transition_count)

    if tool_name == "tool_think":
        thought = tool_args.get("thought", "")
        messages.append(
            Message(
                role="assistant",
                content="",
                tool_calls=[_tool_call_dict_to_native(tool_call)],
            )
        )
        messages.append(
            Message(
                role="tool",
                content=f"[Thought recorded: {len(thought)} chars]",
                tool_call_id=tool_id,
            )
        )
        logger_obj.info(
            "[TUTOR_AGENT] Think tool recorded internally: %d chars (public rail stays curated)",
            len(thought),
        )
        return TutorToolDispatchResult(phase_transition_count=phase_transition_count)

    if tool_name == "tool_report_progress":
        progress_msg = tool_args.get("message", "")
        next_beat = await iteration_beat_fn(
            query=query,
            context=context,
            iteration=iteration,
            tools_used=tools_used,
            phase_label=tool_args.get("phase_label", ""),
        )
        next_label = tool_args.get("phase_label", "") or "Tiep tuc phan tich"

        if phase_transition_count < max_phase_transitions:
            await push({"type": "thinking_end", "content": "", "node": "tutor_agent"})
            if progress_msg:
                await push(
                    {
                        "type": "action_text",
                        "content": progress_msg,
                        "node": "tutor_agent",
                    }
                )
            await push(
                {
                    "type": "thinking_start",
                    "content": next_beat.label,
                    "node": "tutor_agent",
                    "summary": next_beat.summary,
                    "details": {
                        "phase": next_beat.phase,
                        "tone_mode": getattr(next_beat, "tone_mode", ""),
                    },
                }
            )
            next_fragments = getattr(next_beat, "fragments", None)
            for fragment in next_fragments or []:
                if fragment and str(fragment).strip():
                    await push_thinking_deltas(f"{str(fragment).strip()}\n\n")
            phase_transition_count += 1
            last_tool_was_progress = True
        else:
            logger_obj.warning(
                "[TUTOR_AGENT] Phase transition rate limit reached (%d)",
                max_phase_transitions,
            )
            last_tool_was_progress = False

        messages.append(
            Message(
                role="assistant",
                content="",
                tool_calls=[_tool_call_dict_to_native(tool_call)],
            )
        )
        messages.append(
            Message(
                role="tool",
                content=f"[Progress reported. Next phase: {next_label}]",
                tool_call_id=tool_id,
            )
        )
        logger_obj.info(
            "[TUTOR_AGENT] Phase transition: '%s' -> '%s'",
            progress_msg,
            next_label,
        )
        return TutorToolDispatchResult(
            phase_transition_count=phase_transition_count,
            last_tool_was_progress=last_tool_was_progress,
            tool_args=tool_args,
        )

    if tool_name in ("tool_pointy_show", "tool_pointy_clear"):
        # Pointy is a UX side-effect — emit a `pointy_action` SSE event so
        # the frontend's pointy-host bridge can animate the cursor, then
        # return a brief acknowledgement to the LLM so streaming continues.
        from app.engine.tools.pointy_tools import build_pointy_event

        if tool_name == "tool_pointy_clear":
            payload = build_pointy_event(mode="clear")
            ack = "[POINTY:clear]"
        else:
            payload = build_pointy_event(
                selector=str(tool_args.get("selector", "")),
                caption=str(tool_args.get("caption", "")),
                duration_ms=int(tool_args.get("duration_ms", 4500) or 4500),
                mode=str(tool_args.get("mode", "highlight") or "highlight"),
            )
            ack = (
                f"[POINTY:{payload['mode']}] "
                f"target={payload['params']['selector']!r} "
                f"duration={payload['params']['duration_ms']}ms"
            )

        await push({
            "type": "pointy_action",
            "content": payload,
            "node": "tutor_agent",
        })
        messages.append(
            Message(
                role="assistant",
                content="",
                tool_calls=[_tool_call_dict_to_native(tool_call)],
            )
        )
        messages.append(
            Message(role="tool", content=ack, tool_call_id=tool_id)
        )
        logger_obj.info(
            "[POINTY] dispatched action=%s selector=%r",
            payload.get("action"),
            payload.get("params", {}).get("selector"),
        )
        return TutorToolDispatchResult(phase_transition_count=phase_transition_count)

    if tool_name in ("tool_character_note", "tool_character_read"):
        try:
            char_tool = get_tool_by_name_fn(tools, tool_name)
            if char_tool:
                result = await invoke_tool_with_runtime_fn(
                    char_tool,
                    tool_args,
                    tool_name=tool_name,
                    runtime_context_base=runtime_context_base,
                    tool_call_id=tool_id,
                    run_sync_in_thread=True,
                )
                desc = f"Character: {tool_name.replace('tool_character_', '')}"
            else:
                result = f"Tool {tool_name} not available"
                desc = tool_name

            _record_tool_use(
                tools_used=tools_used,
                tool_name=tool_name,
                tool_args=tool_args,
                description=desc,
                iteration=iteration,
            )
            await _emit_tool_result(
                push=push,
                tool_name=tool_name,
                result=result,
                tool_id=tool_id,
            )
            await _emit_tool_acknowledgment(
                query=query,
                context=context,
                tool_name=tool_name,
                result=result,
                tool_acknowledgment_fn=tool_acknowledgment_fn,
                push_thinking_deltas=push_thinking_deltas,
            )
            _append_tool_observation(
                messages=messages,
                tool_call=tool_call,
                tool_id=tool_id,
                result=result,
            )
            logger_obj.info("[TUTOR_AGENT] Character tool %s done", tool_name)
            return TutorToolDispatchResult(
                phase_transition_count=phase_transition_count,
                tool_result_text=str(result),
                tool_args=tool_args,
            )
        except Exception as exc:
            logger_obj.error("[TUTOR_AGENT] Character tool %s error: %s", tool_name, exc)
            _append_tool_error(
                messages=messages,
                tool_call=tool_call,
                tool_id=tool_id,
                error=exc,
            )
            return TutorToolDispatchResult(phase_transition_count=phase_transition_count)

    try:
        matched_tool = get_tool_by_name_fn(tools, tool_name)
        if matched_tool is None:
            raise ValueError(f"Tool {tool_name} not available")

        result = await invoke_tool_with_runtime_fn(
            matched_tool,
            tool_args,
            tool_name=tool_name,
            runtime_context_base=runtime_context_base,
            tool_call_id=tool_id,
            run_sync_in_thread=True,
        )
        await _emit_visual_lifecycle_if_available(
            push=push,
            tool_name=tool_name,
            result=result,
            tool_id=tool_id,
            logger_obj=logger_obj,
        )
        _record_tool_use(
            tools_used=tools_used,
            tool_name=tool_name,
            tool_args=tool_args,
            description=f"Tool: {tool_name}",
            iteration=iteration,
        )
        await _emit_tool_result(
            push=push,
            tool_name=tool_name,
            result=(
                _summarize_tool_result_for_stream(tool_name, result)
                if _is_visual_result_tool(tool_name)
                else result
            ),
            tool_id=tool_id,
        )
        await _emit_tool_acknowledgment(
            query=query,
            context=context,
            tool_name=tool_name,
            result=result,
            tool_acknowledgment_fn=tool_acknowledgment_fn,
            push_thinking_deltas=push_thinking_deltas,
        )
        _append_tool_observation(
            messages=messages,
            tool_call=tool_call,
            tool_id=tool_id,
            result=result,
        )
        return TutorToolDispatchResult(
            phase_transition_count=phase_transition_count,
            tool_result_text=str(result),
            tool_args=tool_args,
        )
    except Exception as exc:
        logger_obj.error("[TUTOR_AGENT] Generic tool %s error: %s", tool_name, exc)
        _append_tool_error(
            messages=messages,
            tool_call=tool_call,
            tool_id=tool_id,
            error=exc,
        )
        return TutorToolDispatchResult(phase_transition_count=phase_transition_count)
