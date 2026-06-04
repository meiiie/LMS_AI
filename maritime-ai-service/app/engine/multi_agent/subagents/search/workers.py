"""Search subgraph node implementations."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from app.engine.multi_agent.subagents.search.workers_runtime import (
    aggregate_results_impl,
    curate_products_impl,
    emit_curated_previews_impl,
    plan_search_impl,
    platform_worker_impl,
    synthesize_response_impl,
)
from app.engine.multi_agent.subagents.event_stream import push_subagent_stream_event
from app.engine.reasoning import ReasoningRenderRequest, get_reasoning_narrator
from app.engine.reasoning.reasoning_narrator import build_tool_context_summary

logger = logging.getLogger(__name__)

_TIER1_PLATFORMS = ["websosanh", "google_shopping"]
_TIER2_PLATFORMS = ["shopee", "lazada", "tiktok_shop"]
_TIER3_PLATFORMS = ["all_web", "facebook_marketplace", "instagram_shopping"]
_BROWSER_PLATFORMS = ["facebook_groups_auto"]

_CHUNK_SIZE = 40
_CHUNK_DELAY = 0.008

_RATING_RE = re.compile(
    r"(\d+[.,]\d+)\s*(?:/\s*5|sao|stars?)"
    r"|(?:đánh giá|rating)[:\s]*(\d+[.,]\d+)",
    re.IGNORECASE,
)
_SOLD_RE = re.compile(
    r"đã bán\s*([\d.,]+\s*[kKmM]?)"
    r"|([\d.,]+\s*[kKmM]?)\s*đã bán",
    re.IGNORECASE,
)


def _extract_rating(text: str) -> float | None:
    """Extract product rating (0-5) from snippet text."""
    if not text:
        return None
    match = _RATING_RE.search(text)
    if not match:
        return None
    raw = (match.group(1) or match.group(2) or "").replace(",", ".")
    try:
        value = float(raw)
        if 0.0 < value <= 5.0:
            return round(value, 1)
    except (ValueError, TypeError):
        pass
    return None


def _parse_sold_number(raw: str) -> int | None:
    """Parse sold count string like '1.2k', '523', '1,5k' into integer."""
    if not raw:
        return None
    raw = raw.strip().replace(",", ".").lower()
    multiplier = 1
    if raw.endswith("k"):
        multiplier = 1000
        raw = raw[:-1]
    elif raw.endswith("m"):
        multiplier = 1_000_000
        raw = raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except (ValueError, TypeError):
        return None


def _extract_sold(text: str) -> int | None:
    """Extract sold count from snippet text."""
    if not text:
        return None
    match = _SOLD_RE.search(text)
    if not match:
        return None
    raw = (match.group(1) or match.group(2) or "").strip()
    return _parse_sold_number(raw)


def _get_event_queue(bus_id: Optional[str]):
    """Lazy-import event queue from the shared event-bus registry."""
    if not bus_id:
        return None
    try:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue as _queue_getter

        return _queue_getter(bus_id)
    except Exception as exc:
        logger.debug("[WORKER] Event queue unavailable: %s", exc)
        return None


async def _push(queue, event: dict) -> None:
    """Non-blocking push to event queue."""
    push_subagent_stream_event(queue, event)


async def _push_thinking_deltas(
    queue,
    text: str,
    node: str = "product_search_agent",
) -> None:
    """Stream text as thinking_delta chunks."""
    for index in range(0, len(text), _CHUNK_SIZE):
        sub = text[index : index + _CHUNK_SIZE]
        await _push(queue, {"type": "thinking_delta", "content": sub, "node": node})
        if index + _CHUNK_SIZE < len(text):
            await asyncio.sleep(_CHUNK_DELAY)


async def _render_search_narration(
    *,
    state: Dict[str, Any],
    phase: str,
    cue: str,
    next_action: str,
    observations: Optional[list[str]] = None,
    tool_names: Optional[list[str]] = None,
    result: object = None,
):
    """Render narrator-driven visible reasoning for product search."""
    context = state.get("context", {}) or {}
    return await get_reasoning_narrator().render(
        ReasoningRenderRequest(
            node="product_search_agent",
            phase=phase,
            cue=cue,
            intent="product_search",
            user_goal=state.get("query", ""),
            conversation_context=str(context.get("conversation_summary", "")),
            capability_context=str(state.get("capability_context", "")),
            tool_context=build_tool_context_summary(tool_names, result=result),
            next_action=next_action,
            observations=[item for item in (observations or []) if item],
            user_id=str(state.get("user_id", "__global__")),
            organization_id=state.get("organization_id"),
            personality_mode=context.get("personality_mode"),
            mood_hint=context.get("mood_hint"),
            visibility_mode="rich",
            style_tags=["product_search", phase],
        )
    )


async def _emit_search_narration(
    queue,
    narration,
    *,
    node: str = "product_search_agent",
    include_start: bool = True,
) -> None:
    """Push narrator output onto the search event stream."""
    if queue is None or narration is None:
        return
    if include_start:
        await _push(
            queue,
            {
                "type": "thinking_start",
                "content": narration.label,
                "node": node,
                "summary": narration.summary,
                "details": {"phase": narration.phase, "style_tags": narration.style_tags},
            },
        )
    chunks = narration.delta_chunks or ([narration.summary] if narration.summary else [])
    for chunk in chunks:
        await _push_thinking_deltas(queue, chunk, node=node)


def _get_available_platforms() -> List[str]:
    """Query SearchPlatformRegistry for enabled platform IDs."""
    try:
        from app.engine.search_platforms import get_search_platform_registry

        registry = get_search_platform_registry()
        return [adapter.get_config().id for adapter in registry.get_all_enabled()]
    except Exception as exc:
        logger.debug("[WORKER] Platform registry unavailable, using defaults: %s", exc)
        return ["google_shopping", "shopee", "lazada"]


def _order_platforms(available: List[str]) -> List[str]:
    """Sort platforms by tier priority."""
    ordered: List[str] = []
    for tier in [
        _TIER1_PLATFORMS,
        _TIER2_PLATFORMS,
        _TIER3_PLATFORMS,
        _BROWSER_PLATFORMS,
    ]:
        for platform in tier:
            if platform in available:
                ordered.append(platform)
    for platform in available:
        if platform not in ordered:
            ordered.append(platform)
    return ordered


async def plan_search(state: Dict[str, Any]) -> dict:
    """Analyse query and determine which platforms to search."""
    return await plan_search_impl(
        state,
        get_available_platforms=_get_available_platforms,
        order_platforms=_order_platforms,
        get_event_queue=_get_event_queue,
        render_search_narration=_render_search_narration,
        emit_search_narration=_emit_search_narration,
        push=_push,
    )


async def platform_worker(state: Dict[str, Any]) -> dict:
    """Execute search on a single platform."""
    return await platform_worker_impl(
        state,
        get_event_queue=_get_event_queue,
        push=_push,
        render_search_narration=_render_search_narration,
        emit_search_narration=_emit_search_narration,
        extract_rating=_extract_rating,
        extract_sold=_extract_sold,
    )


async def aggregate_results(state: Dict[str, Any]) -> dict:
    """Deduplicate products, optionally generate Excel."""
    return await aggregate_results_impl(
        state,
        get_event_queue=_get_event_queue,
        push=_push,
        render_search_narration=_render_search_narration,
        emit_search_narration=_emit_search_narration,
    )


async def _emit_curated_previews(
    eq,
    curated_products: List[Dict[str, Any]],
    query: str,
) -> None:
    """Emit preview events for curated products."""
    del query
    await emit_curated_previews_impl(eq, curated_products, _push)


async def curate_products(state: Dict[str, Any]) -> dict:
    """LLM-curate top products from deduped results."""
    return await curate_products_impl(
        state,
        get_event_queue=_get_event_queue,
        push=_push,
        render_search_narration=_render_search_narration,
        emit_search_narration=_emit_search_narration,
        emit_curated_previews=_emit_curated_previews,
    )


async def synthesize_response(state: Dict[str, Any]) -> dict:
    """Generate final user-facing response from aggregated results via LLM."""
    curated_products = state.get("curated_products")
    if curated_products is not None:
        # Keep the preference explicit in the shell for compatibility tests and
        # to make the delegation contract obvious at the entry point.
        state = {**state, "curated_products": curated_products}
    return await synthesize_response_impl(
        state,
        chunk_size=_CHUNK_SIZE,
        chunk_delay=_CHUNK_DELAY,
        get_event_queue=_get_event_queue,
        push=_push,
        render_search_narration=_render_search_narration,
        emit_search_narration=_emit_search_narration,
    )
