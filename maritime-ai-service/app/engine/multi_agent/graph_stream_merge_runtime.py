"""Merged queue forwarders for graph streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.exceptions import ProviderUnavailableError
from app.engine.reasoning import capture_thinking_lifecycle_event
from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload

logger = logging.getLogger(__name__)


def _sanitize_public_bus_event(event: Any) -> dict[str, Any]:
    """Return a public-stream-safe bus event dict before SSE conversion."""

    safe_event = sanitize_runtime_payload(event)
    if isinstance(safe_event, dict):
        if not str(safe_event.get("type") or "").strip():
            safe_event["type"] = "status"
        return safe_event
    return {
        "type": "status",
        "node": "system",
        "content": str(safe_event or ""),
    }


def _should_suppress_bus_event(event: dict | None) -> bool:
    """Filter bus events that should never surface on the public stream."""
    if not isinstance(event, dict):
        return False

    event_type = str(event.get("type") or "").strip().lower()
    node = str(event.get("node") or "").strip().lower()

    # Tutor owns thinking/tool trace, but final answer authority now belongs to
    # the synthesizer. If any lower layer still emits tutor answer deltas
    # directly (for example through provider/native stream callbacks), drop
    # them here before they can reach SSE.
    if node == "tutor_agent" and event_type == "answer_delta":
        return True

    return False


async def forward_graph_events_impl(
    *,
    initial_state,
    merged_queue: asyncio.Queue,
) -> None:
    """Forward runner state updates into the merged streaming queue.

    This runtime is WiiiRunner-only. Historical LangGraph parameters were
    removed so the streaming shell matches the real execution path.
    """
    try:
        from app.engine.multi_agent.runner import get_wiii_runner

        runner = get_wiii_runner()
        await runner.run_streaming(
            initial_state,
            merged_queue=merged_queue,
        )
        logger.info("[STREAM] Executed via WiiiRunner streaming")
    except asyncio.TimeoutError:
        await merged_queue.put(("error", "Processing timeout exceeded"))
    except ProviderUnavailableError as exc:
        logger.warning(
            "[STREAM] Graph provider unavailable: provider=%s reason=%s",
            exc.provider,
            exc.reason_code,
        )
        await merged_queue.put(("provider_unavailable", exc))
    except Exception as exc:
        logger.exception("[STREAM] Graph error: %s", exc)
        await merged_queue.put(("error", "Graph processing error"))
    finally:
        await merged_queue.put(("graph_done", None))


async def forward_bus_events_impl(
    *,
    event_queue: asyncio.Queue,
    merged_queue: asyncio.Queue,
    sentinel,
    bus_streamed_nodes: set,
    bus_answer_nodes: set,
    lifecycle_state: dict | None = None,
) -> None:
    """Forward intra-node bus events into the merged streaming queue."""
    while True:
        try:
            event = await event_queue.get()
            if event is sentinel:
                break
            event = _sanitize_public_bus_event(event)
            if _should_suppress_bus_event(event):
                logger.debug(
                    "[STREAM] Suppressed bus event type=%s node=%s",
                    event.get("type"),
                    event.get("node"),
                )
                continue
            node = event.get("node")
            event_type = event.get("type")
            if node and event_type in ("thinking_delta", "thinking_start"):
                bus_streamed_nodes.add(node)
            if node and event_type == "answer_delta":
                bus_answer_nodes.add(node)
            if lifecycle_state is not None:
                capture_thinking_lifecycle_event(
                    lifecycle_state,
                    event,
                    default_node=str(node or "").strip() or None,
                )
            await merged_queue.put(("bus", event))
        except Exception as exc:
            logger.warning("[STREAM] Bus forwarding stopped: %s", exc)
            break


async def handle_bus_message_impl(
    *,
    payload,
    settings_enable_soul_emotion: bool,
    soul_buffer,
    soul_emotion_emitted: bool,
    supervisor_status_emitted: bool,
    supervisor_thinking_open: bool,
    convert_bus_event,
    create_emotion_event,
    create_answer_event,
):
    """Convert a merged bus payload into stream events and updated flags."""
    events = []
    payload = _sanitize_public_bus_event(payload)

    if _should_suppress_bus_event(payload):
        logger.debug(
            "[STREAM] Suppressed merged bus payload type=%s node=%s",
            payload.get("type"),
            payload.get("node"),
        )
        return (
            events,
            soul_emotion_emitted,
            supervisor_status_emitted,
            supervisor_thinking_open,
        )

    if (
        settings_enable_soul_emotion
        and soul_buffer is not None
        and not soul_buffer.is_done
        and payload.get("type") == "answer_delta"
    ):
        chunk = payload.get("content", "")
        try:
            emotion, clean_chunks = soul_buffer.feed(chunk)
        except Exception as exc:
            logger.warning("[SOUL] Buffer feed failed: %s, passing through", exc)
            emotion, clean_chunks = None, [chunk] if chunk else []
        if emotion and not soul_emotion_emitted:
            events.append(
                await create_emotion_event(
                    mood=emotion.mood,
                    face=emotion.face,
                    intensity=emotion.intensity,
                )
            )
            soul_emotion_emitted = True
        for clean_chunk in clean_chunks:
            if clean_chunk:
                events.append(await create_answer_event(clean_chunk))
        return (
            events,
            soul_emotion_emitted,
            supervisor_status_emitted,
            supervisor_thinking_open,
        )

    if (
        settings_enable_soul_emotion
        and soul_buffer is not None
        and not soul_buffer.is_done
    ):
        try:
            emotion, clean_chunks = soul_buffer.flush()
        except Exception as exc:
            logger.warning("[SOUL] Buffer flush failed: %s", exc)
            emotion, clean_chunks = None, []
        if emotion and not soul_emotion_emitted:
            events.append(
                await create_emotion_event(
                    mood=emotion.mood,
                    face=emotion.face,
                    intensity=emotion.intensity,
                )
            )
            soul_emotion_emitted = True
        for clean_chunk in clean_chunks:
            if clean_chunk:
                events.append(await create_answer_event(clean_chunk))

    if payload.get("node") == "supervisor":
        if payload.get("type") == "status":
            supervisor_status_emitted = True
        elif payload.get("type") == "thinking_start":
            supervisor_thinking_open = True
        elif payload.get("type") == "thinking_end":
            supervisor_thinking_open = False

    events.append(await convert_bus_event(payload))
    return (
        events,
        soul_emotion_emitted,
        supervisor_status_emitted,
        supervisor_thinking_open,
    )


async def drain_pending_bus_events_impl(
    *,
    merged_queue: asyncio.Queue,
    event_queue: asyncio.Queue,
    convert_bus_event,
    answer_emitted: bool,
    sentinel,
):
    """Drain residual bus events after graph completion."""
    events = []

    while not merged_queue.empty():
        try:
            msg_type, payload = merged_queue.get_nowait()
            if msg_type == "bus":
                payload = _sanitize_public_bus_event(payload)
                if _should_suppress_bus_event(payload):
                    continue
                if payload.get("type") == "answer_delta":
                    answer_emitted = True
                events.append(await convert_bus_event(payload))
        except Exception as exc:
            logger.debug("[STREAM] Merged queue drain stopped: %s", exc)
            break

    while not event_queue.empty():
        try:
            event = event_queue.get_nowait()
            if event is sentinel:
                continue
            event = _sanitize_public_bus_event(event)
            if _should_suppress_bus_event(event):
                continue
            if event.get("type") == "answer_delta":
                answer_emitted = True
            events.append(await convert_bus_event(event))
        except Exception as exc:
            logger.debug("[STREAM] Event queue drain stopped: %s", exc)
            break

    return events, answer_emitted
