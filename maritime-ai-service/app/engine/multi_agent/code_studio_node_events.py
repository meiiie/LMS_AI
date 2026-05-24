"""Typed event sink contract for the Code Studio graph node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.state import AgentState


@dataclass(frozen=True, slots=True)
class CodeStudioNodeEventSinkRequest:
    """Dependencies required to wire Code Studio status/tool events."""

    state: AgentState
    bus_id: str | None
    get_event_queue: Callable[[str], Any]
    capture_public_thinking_event: Callable[[AgentState, dict[str, Any]], Any]
    logger: logging.Logger


@dataclass(frozen=True, slots=True)
class CodeStudioNodeEventSink:
    """Bound event queue plus the async push function used by sub-stages."""

    event_queue: Any | None
    push_event: Callable[[dict[str, Any]], Any]

    @property
    def event_queue_present(self) -> bool:
        return self.event_queue is not None


def create_code_studio_node_event_sink(
    request: CodeStudioNodeEventSinkRequest,
) -> CodeStudioNodeEventSink:
    """Create the Code Studio node event sink without hiding side effects."""

    event_queue = request.get_event_queue(request.bus_id) if request.bus_id else None

    async def push_event(event: dict[str, Any]) -> None:
        request.capture_public_thinking_event(request.state, event)
        if event_queue is None:
            return
        try:
            event_queue.put_nowait(event)
        except Exception as queue_error:  # noqa: BLE001 - event stream must not fail turn
            request.logger.debug(
                "[CODE_STUDIO] Event queue push failed: %s",
                queue_error,
            )

    return CodeStudioNodeEventSink(
        event_queue=event_queue,
        push_event=push_event,
    )
