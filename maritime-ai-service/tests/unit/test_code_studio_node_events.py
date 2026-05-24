from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.multi_agent.code_studio_node_events import (
    CodeStudioNodeEventSinkRequest,
    create_code_studio_node_event_sink,
)


@pytest.mark.asyncio
async def test_code_studio_node_event_sink_captures_public_event_without_bus():
    state = {}
    captured: list[dict] = []

    sink = create_code_studio_node_event_sink(
        CodeStudioNodeEventSinkRequest(
            state=state,
            bus_id=None,
            get_event_queue=lambda _bus_id: None,
            capture_public_thinking_event=lambda _state, event: captured.append(event),
            logger=MagicMock(),
        )
    )

    await sink.push_event({"type": "status", "content": "Dang tao preview"})

    assert sink.event_queue_present is False
    assert captured == [{"type": "status", "content": "Dang tao preview"}]


@pytest.mark.asyncio
async def test_code_studio_node_event_sink_logs_queue_push_failures():
    state = {}
    captured: list[dict] = []
    logger = MagicMock()

    class Queue:
        def put_nowait(self, _event):
            raise RuntimeError("queue full")

    sink = create_code_studio_node_event_sink(
        CodeStudioNodeEventSinkRequest(
            state=state,
            bus_id="bus-1",
            get_event_queue=lambda _bus_id: Queue(),
            capture_public_thinking_event=lambda _state, event: captured.append(event),
            logger=logger,
        )
    )

    await sink.push_event({"type": "status", "content": "Dang tao preview"})

    assert sink.event_queue_present is True
    assert captured == [{"type": "status", "content": "Dang tao preview"}]
    logger.debug.assert_called_once()


@pytest.mark.asyncio
async def test_code_studio_node_event_sink_pushes_to_queue_when_available():
    state = {}
    queue = SimpleNamespace(events=[])
    queue.put_nowait = lambda event: queue.events.append(event)

    sink = create_code_studio_node_event_sink(
        CodeStudioNodeEventSinkRequest(
            state=state,
            bus_id="bus-1",
            get_event_queue=lambda _bus_id: queue,
            capture_public_thinking_event=lambda _state, _event: None,
            logger=MagicMock(),
        )
    )

    await sink.push_event({"type": "tool", "name": "tool_create_visual_code"})

    assert queue.events == [{"type": "tool", "name": "tool_create_visual_code"}]
