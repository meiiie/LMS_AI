"""Compatibility shim for the removed LangGraph tutor subgraph.

Use ``app.engine.multi_agent.subagents.tutor.runtime`` for native helpers.
This module preserves older imports and the explicit deprecated builder
failure expected by compatibility tests.
"""

from __future__ import annotations

from app.engine.multi_agent.subagents.tutor.runtime import (
    TutorSubgraphState,
    analyze_node,
    generate_node,
    output_node,
    refine_node,
    should_refine,
)


def build_tutor_subgraph():
    """Deprecated LangGraph builder kept only for import compatibility."""
    raise RuntimeError(
        "build_tutor_subgraph() is deprecated (De-LangGraphing Phase 3). "
        "Use app.engine.multi_agent.subagents.tutor.runtime helpers directly."
    )


__all__ = [
    "TutorSubgraphState",
    "analyze_node",
    "build_tutor_subgraph",
    "generate_node",
    "output_node",
    "refine_node",
    "should_refine",
]
