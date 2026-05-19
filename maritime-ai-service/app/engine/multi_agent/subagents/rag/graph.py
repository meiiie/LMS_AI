"""Compatibility shim for the removed LangGraph RAG subgraph.

Use ``app.engine.multi_agent.subagents.rag.runtime`` for native helpers.
This module preserves older imports and the explicit deprecated builder
failure expected by compatibility tests.
"""

from __future__ import annotations

from app.engine.multi_agent.subagents.rag.runtime import (
    RAGSubgraphState,
    correct_node,
    generate_node,
    grade_node,
    retrieve_node,
    should_correct,
)


def build_rag_subgraph():
    """Deprecated LangGraph builder kept only for import compatibility."""
    raise RuntimeError(
        "build_rag_subgraph() is deprecated (De-LangGraphing Phase 3). "
        "Use app.engine.multi_agent.subagents.rag.runtime helpers directly."
    )


__all__ = [
    "RAGSubgraphState",
    "build_rag_subgraph",
    "correct_node",
    "generate_node",
    "grade_node",
    "retrieve_node",
    "should_correct",
]
