"""Emergency fallback helpers for the direct response node."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _clean_emergency_web_search_query,
)
from app.engine.multi_agent.direct_node_visible_thought import (
    _align_direct_visible_thought,
    _best_effort_direct_visible_thought_raw,
    _compact_basic_identity_answer,
    _should_surface_direct_visible_thought,
    _strip_direct_inline_private_asides,
)
from app.engine.multi_agent.tool_event_sanitizer import sanitize_tool_args_for_event
from app.engine.multi_agent.visual_events import _summarize_tool_result_for_stream

logger = logging.getLogger(__name__)


async def _emergency_search_fallback(
    *,
    query: str,
    tools: list[Any],
    timeout_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """Run a bounded LLM-free search fallback when direct planning times out."""
    if not tools or not query.strip():
        return []

    target_names = (
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
    )
    chosen = None
    for tool_obj in tools:
        name = (
            getattr(tool_obj, "name", None)
            or getattr(tool_obj, "__name__", None)
            or ""
        )
        if str(name).lower() in target_names:
            chosen = tool_obj
            break
    if chosen is None:
        return []

    chosen_name = getattr(chosen, "name", None) or getattr(chosen, "__name__", "tool_web_search")
    invoker = getattr(chosen, "ainvoke", None)
    search_query = _clean_emergency_web_search_query(query)
    payload = {"query": search_query}
    try:
        if invoker is not None and inspect.iscoroutinefunction(invoker):
            result = await asyncio.wait_for(invoker(payload), timeout=timeout_seconds)
        else:
            sync_invoker = getattr(chosen, "invoke", None)
            if sync_invoker is None:
                return []
            result = await asyncio.wait_for(
                asyncio.to_thread(sync_invoker, payload),
                timeout=timeout_seconds,
            )
    except asyncio.TimeoutError:
        logger.warning(
            "[DIRECT] Emergency %s exceeded %.1fs - abandoning fallback",
            chosen_name,
            timeout_seconds,
        )
        return []
    except Exception as exc:
        logger.warning("[DIRECT] Emergency %s raised %s - abandoning", chosen_name, exc)
        return []

    if not result or not str(result).strip():
        return []

    return [
        {
            "type": "call",
            "id": "emergency-1",
            "name": chosen_name,
            "args": {"query": search_query},
        },
        {
            "type": "result",
            "id": "emergency-1",
            "name": chosen_name,
            "result": str(result),
        },
    ]


async def _emit_synthetic_tool_events(
    events: list[dict[str, Any]],
    *,
    push_event,
) -> None:
    """Surface LLM-free emergency tool work through the same SSE tool strip."""
    for event in events or []:
        event_type = event.get("type")
        name = str(event.get("name") or "")
        event_id = str(event.get("id") or "")
        if event_type == "call":
            public_args = sanitize_tool_args_for_event(event.get("args") or {})
            await push_event(
                {
                    "type": "tool_call",
                    "content": {
                        "name": name,
                        "args": public_args,
                        "id": event_id,
                    },
                    "node": "direct",
                }
            )
        elif event_type == "result":
            result = str(event.get("result") or "")
            await push_event(
                {
                    "type": "tool_result",
                    "content": {
                        "name": name,
                        "result": _summarize_tool_result_for_stream(name, result),
                        "id": event_id,
                    },
                    "node": "direct",
                }
            )


async def _salvage_direct_turn_from_final_result(
    *,
    llm_response: Any,
    messages: list[Any],
    extract_direct_response,
    sanitize_structured_visual_answer_text,
    sanitize_wiii_house_text,
    tool_call_events: list[dict[str, Any]],
    query: str,
    is_identity_turn: bool,
    routing_intent: str,
    response_language: str,
    llm: Any,
) -> tuple[str, str, list[dict[str, Any]]] | None:
    """Recover a usable response if post-processing fails after an LLM result."""
    if llm_response is None:
        return None

    try:
        response, thinking_content, tools_used = extract_direct_response(
            llm_response,
            messages or [],
        )
    except Exception as exc:
        logger.warning("[DIRECT] Salvage extraction failed: %s", exc)
        return None

    response = str(response or "").strip()
    if not response:
        return None

    try:
        response = sanitize_structured_visual_answer_text(
            response,
            tool_call_events=tool_call_events,
        )
    except Exception as exc:
        logger.debug("[DIRECT] Salvage skipped visual sanitize: %s", exc)

    try:
        response = sanitize_wiii_house_text(response, query=query)
    except Exception as exc:
        logger.debug("[DIRECT] Salvage skipped house sanitize: %s", exc)

    response = _strip_direct_inline_private_asides(response)
    if is_identity_turn:
        try:
            response = _compact_basic_identity_answer(response, query=query)
        except Exception as exc:
            logger.debug("[DIRECT] Salvage skipped identity compaction: %s", exc)

    response = str(response or "").strip()
    if not response:
        return None

    visible_thought = ""
    if _should_surface_direct_visible_thought(
        thinking_content,
        routing_intent=routing_intent,
        response=response,
    ):
        try:
            visible_thought = await _align_direct_visible_thought(
                thinking_content,
                response_language=response_language,
                llm=llm,
            )
        except Exception as exc:
            logger.debug("[DIRECT] Salvage alignment skipped: %s", exc)
        if not visible_thought:
            visible_thought = _best_effort_direct_visible_thought_raw(thinking_content)

    return response, visible_thought, tools_used
