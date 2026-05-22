"""Direct-node event sink lifecycle helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.engine.multi_agent.state import AgentState


@dataclass
class DirectNodeEventSink:
    state: AgentState
    capture_public_thinking_event: Callable[[AgentState, dict[str, Any]], Any]
    event_queue: Any | None
    logger_obj: logging.Logger

    async def push_event(self, event: dict[str, Any]) -> None:
        self.capture_public_thinking_event(self.state, event)
        if self.event_queue:
            try:
                self.event_queue.put_nowait(event)
            except Exception as queue_error:  # noqa: BLE001
                self.logger_obj.debug("[DIRECT] Event queue push failed: %s", queue_error)


def build_direct_node_event_sink(
    *,
    state: AgentState,
    bus_id: str | None,
    capture_public_thinking_event: Callable[[AgentState, dict[str, Any]], Any],
    logger_obj: logging.Logger,
) -> DirectNodeEventSink:
    """Create the direct-node event sink without binding the runtime shell to SSE."""

    event_queue = None
    if bus_id:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue

        event_queue = _get_event_queue(bus_id)
    return DirectNodeEventSink(
        state=state,
        capture_public_thinking_event=capture_public_thinking_event,
        event_queue=event_queue,
        logger_obj=logger_obj,
    )
