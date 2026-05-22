import asyncio
import logging

import pytest


@pytest.mark.asyncio
async def test_direct_node_event_sink_captures_and_pushes_to_queue():
    from app.engine.multi_agent.direct_node_event_sink import DirectNodeEventSink

    state = {"query": "hello"}
    captured = []
    queue: asyncio.Queue = asyncio.Queue()
    sink = DirectNodeEventSink(
        state=state,
        capture_public_thinking_event=lambda current_state, event: captured.append(
            (current_state, event)
        ),
        event_queue=queue,
        logger_obj=logging.getLogger("test"),
    )
    event = {"type": "answer_delta", "content": "Xin chao", "node": "direct"}

    await sink.push_event(event)

    assert captured == [(state, event)]
    assert queue.get_nowait() == event


@pytest.mark.asyncio
async def test_direct_node_event_sink_capture_survives_queue_failure(caplog):
    from app.engine.multi_agent.direct_node_event_sink import DirectNodeEventSink

    class BrokenQueue:
        def put_nowait(self, _event):
            raise RuntimeError("queue closed")

    logger = logging.getLogger("test.direct_node_event_sink")
    captured = []
    sink = DirectNodeEventSink(
        state={},
        capture_public_thinking_event=lambda current_state, event: captured.append(
            (current_state, event)
        ),
        event_queue=BrokenQueue(),
        logger_obj=logger,
    )

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        await sink.push_event({"type": "status", "content": "thinking"})

    assert captured
    assert "Event queue push failed" in caplog.text


def test_build_direct_node_event_sink_uses_registered_bus_queue():
    from app.engine.multi_agent.direct_node_event_sink import build_direct_node_event_sink
    from app.engine.multi_agent.graph_event_bus import (
        _discard_event_queue,
        _register_event_queue,
    )

    bus_id = "direct-node-event-sink-test"
    queue: asyncio.Queue = asyncio.Queue()
    _register_event_queue(bus_id, queue)
    try:
        sink = build_direct_node_event_sink(
            state={},
            bus_id=bus_id,
            capture_public_thinking_event=lambda *_args, **_kwargs: None,
            logger_obj=logging.getLogger("test"),
        )
    finally:
        _discard_event_queue(bus_id)

    assert sink.event_queue is queue
