"""Native product-search runtime helpers.

LangGraph is no longer part of Wiii's runtime. This module owns the remaining
plain-Python helpers used by WiiiRunner and tests: platform fan-out plus the
worker functions imported from ``workers.py``.

Compatibility imports from ``subagents.search.graph`` are kept in a small shim
so old tests/extensions fail predictably without making this file look like a
live graph runtime.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.engine.multi_agent.subagents.search.state import SearchSubgraphState
from app.engine.multi_agent.subagents.search.workers import (
    aggregate_results,
    curate_products,
    plan_search,
    platform_worker,
    synthesize_response,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SearchSubgraphState",
    "aggregate_results",
    "curate_products",
    "plan_search",
    "platform_worker",
    "route_to_platforms",
    "synthesize_response",
]


def route_to_platforms(state: Dict[str, Any]) -> List[dict]:
    """Fan-out: create parallel task dicts for each platform.

    Returns plain task dicts for use with WiiiRunner/``asyncio.gather``.
    """
    platforms = state.get("platforms_to_search", [])
    query = state.get("query", "")
    org_id = state.get("organization_id")
    bus_id = state.get("_event_bus_id")

    tasks = [
        {
            "query": query,
            "platform_id": pid,
            "max_results": 20,
            "page": 1,
            "organization_id": org_id,
            "_event_bus_id": bus_id,
        }
        for pid in platforms
    ]

    if not tasks:
        tasks.append({
            "query": query,
            "platform_id": "google_shopping",
            "max_results": 20,
            "page": 1,
            "organization_id": org_id,
            "_event_bus_id": bus_id,
        })

    logger.info("[SEARCH_SUBGRAPH] Fan-out: %d parallel platform workers", len(tasks))
    return tasks
