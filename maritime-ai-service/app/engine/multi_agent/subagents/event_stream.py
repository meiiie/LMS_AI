"""Safe event queue helpers for subagent streaming."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload


logger = logging.getLogger(__name__)


def sanitize_subagent_stream_event(event: Any) -> dict[str, Any]:
    """Return an event payload safe for parent/user-facing stream queues."""

    safe_event = sanitize_runtime_payload(event)
    return safe_event if isinstance(safe_event, dict) else {}


def push_subagent_stream_event(queue: Any, event: Any) -> None:
    """Non-blocking safe push to a subagent stream queue."""

    if queue is None:
        return
    safe_event = sanitize_subagent_stream_event(event)
    if not safe_event:
        return
    try:
        queue.put_nowait(safe_event)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[SUBAGENT_STREAM] Event push failed: %s", exc)


__all__ = ["push_subagent_stream_event", "sanitize_subagent_stream_event"]
