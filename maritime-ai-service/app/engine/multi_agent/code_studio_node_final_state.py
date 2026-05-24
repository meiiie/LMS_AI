"""Final state contract for the Code Studio graph node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    record_thinking_snapshot,
    resolve_visible_thinking_from_lifecycle,
)


@dataclass(frozen=True, slots=True)
class CodeStudioNodeFinalStateRequest:
    """Response and state needed to close a Code Studio node turn."""

    state: AgentState
    response: str
    query: str


@dataclass(frozen=True, slots=True)
class CodeStudioNodeFinalStateDependencies:
    """Injected helpers for thinking cleanup and final state mutation."""

    build_code_studio_reasoning_summary: Callable[..., Any]
    direct_tool_names: Callable[[list[Any]], list[str]]
    resolve_visible_thinking_fn: Callable[..., str] = (
        resolve_visible_thinking_from_lifecycle
    )
    record_thinking_snapshot_fn: Callable[..., Any] = record_thinking_snapshot


async def apply_code_studio_node_final_state(
    *,
    request: CodeStudioNodeFinalStateRequest,
    dependencies: CodeStudioNodeFinalStateDependencies,
) -> AgentState:
    """Apply final response fields and public thinking snapshot for Code Studio."""

    state = request.state
    if not state.get("thinking_content"):
        state["thinking_content"] = dependencies.resolve_visible_thinking_fn(
            state,
            fallback=await dependencies.build_code_studio_reasoning_summary(
                request.query,
                state,
                dependencies.direct_tool_names(state.get("tools_used", [])),
            ),
            default_node="code_studio_agent",
        )
    if state.get("thinking_content"):
        dependencies.record_thinking_snapshot_fn(
            state,
            state.get("thinking_content"),
            node="code_studio_agent",
            provenance="final_snapshot",
        )

    state["final_response"] = request.response
    state["agent_outputs"] = {"code_studio_agent": request.response}
    state["current_agent"] = "code_studio_agent"
    return state
