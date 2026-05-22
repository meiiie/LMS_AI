"""Thinking snapshot helpers for direct-node deterministic paths."""

from __future__ import annotations

from typing import Any, Callable

from app.engine.multi_agent.state import AgentState


def record_direct_node_thinking_snapshot(
    *,
    state: AgentState,
    thinking: Any,
    provenance: str,
    record_thinking_snapshot_fn: Callable[..., Any],
    node: str = "direct",
) -> str:
    """Store visible thinking state and write the matching reasoning snapshot."""

    thinking_text = str(thinking or "").strip()
    if not thinking_text:
        return ""
    state["thinking"] = thinking_text
    state["thinking_content"] = thinking_text
    record_thinking_snapshot_fn(
        state,
        thinking_text,
        node=node,
        provenance=provenance,
    )
    return thinking_text
