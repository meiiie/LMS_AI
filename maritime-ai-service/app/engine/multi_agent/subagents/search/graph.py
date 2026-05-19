"""Compatibility shim for the removed LangGraph product-search subgraph.

Use ``app.engine.multi_agent.subagents.search.runtime`` for native helpers.
This module only preserves older imports and the explicit deprecated builder
failure expected by compatibility tests.
"""

from __future__ import annotations

from app.engine.multi_agent.subagents.search.runtime import (
    SearchSubgraphState,
    aggregate_results,
    curate_products,
    plan_search,
    platform_worker,
    route_to_platforms,
    synthesize_response,
)


def build_search_subgraph():
    """Deprecated LangGraph builder kept only for import compatibility."""
    raise RuntimeError(
        "build_search_subgraph() is deprecated (De-LangGraphing Phase 3). "
        "Use app.engine.multi_agent.subagents.search.runtime helpers directly."
    )


__all__ = [
    "SearchSubgraphState",
    "aggregate_results",
    "build_search_subgraph",
    "curate_products",
    "plan_search",
    "platform_worker",
    "route_to_platforms",
    "synthesize_response",
]
