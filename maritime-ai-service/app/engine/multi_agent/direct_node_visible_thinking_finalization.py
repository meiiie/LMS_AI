"""Direct-node visible thinking finalization."""

from __future__ import annotations

from typing import Any, Callable

from app.engine.multi_agent.direct_node_visible_thought import (
    _align_direct_visible_thought,
    _build_emotional_rescue_visible_thought,
    _contains_direct_internal_thought_leak,
    _should_surface_direct_visible_thought,
)
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import should_align_visible_thinking_language


async def finalize_direct_node_visible_thinking(
    *,
    query: str,
    state: AgentState,
    response: str,
    thinking_content: str,
    routing_intent: str,
    response_language: str,
    llm: Any,
    tools_used: list[Any],
    build_direct_reasoning_summary: Callable[..., Any],
    record_direct_node_thinking_snapshot: Callable[..., str],
    record_thinking_snapshot_fn: Callable[..., Any],
    should_surface_direct_visible_thought_fn: Callable[..., bool] | None = None,
    align_direct_visible_thought_fn: Callable[..., Any] | None = None,
    contains_direct_internal_thought_leak_fn: Callable[[str], bool] | None = None,
    should_align_visible_thinking_language_fn: Callable[..., bool] | None = None,
    build_emotional_rescue_visible_thought_fn: Callable[..., Any] | None = None,
) -> None:
    """Finalize visible thinking state after a direct-node LLM/tool response."""

    should_surface = (
        should_surface_direct_visible_thought_fn
        or _should_surface_direct_visible_thought
    )
    align_thought = align_direct_visible_thought_fn or _align_direct_visible_thought
    contains_leak = (
        contains_direct_internal_thought_leak_fn
        or _contains_direct_internal_thought_leak
    )
    needs_language_alignment = (
        should_align_visible_thinking_language_fn
        or should_align_visible_thinking_language
    )
    build_emotional_rescue = (
        build_emotional_rescue_visible_thought_fn
        or _build_emotional_rescue_visible_thought
    )

    if should_surface(
        thinking_content,
        routing_intent=routing_intent,
        response=response,
    ):
        aligned_thinking = await align_thought(
            thinking_content,
            response_language=response_language,
            llm=llm,
        )
        if (
            aligned_thinking
            and not contains_leak(aligned_thinking)
            and not needs_language_alignment(
                aligned_thinking,
                target_language=response_language,
            )
        ):
            record_direct_node_thinking_snapshot(
                state=state,
                thinking=aligned_thinking,
                provenance="aligned_cleanup",
                record_thinking_snapshot_fn=record_thinking_snapshot_fn,
            )
        else:
            _clear_visible_thinking(state)
    else:
        _clear_visible_thinking(state)

    if str(state.get("thinking_content") or "").strip():
        return

    emotional_rescue = await build_emotional_rescue(
        query=query,
        state=state,
        response=response,
        response_language=response_language,
        llm=llm,
        build_direct_reasoning_summary=build_direct_reasoning_summary,
        tool_names=list(tools_used or []),
    )
    if emotional_rescue:
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=emotional_rescue,
            provenance="aligned_cleanup",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
        )


def _clear_visible_thinking(state: AgentState) -> None:
    state.pop("thinking", None)
    state["thinking_content"] = ""
