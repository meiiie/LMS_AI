"""
Tests for Event Bus — Sprint 69: Intra-node streaming.

Tests cover:
- _EVENT_QUEUES registry (create, get, cleanup)
- _convert_bus_event (thinking_delta, tool_call, tool_result, fallback)
- Concurrent graph + queue consumption pattern
- Backward compatibility (no event bus)
"""

import asyncio
import sys
import types
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# Break circular import: multi_agent.__init__ → graph → agents → tutor_node
# → services.__init__ → chat_service → multi_agent.graph
_cs_key = "app.services.chat_service"
_svc_key = "app.services"
_had_cs = _cs_key in sys.modules
_had_svc = _svc_key in sys.modules
_orig_cs = sys.modules.get(_cs_key)
if not _had_cs:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs

from app.engine.multi_agent.graph_streaming import (
    _EVENT_QUEUES,
    _get_event_queue,
    _convert_bus_event,
)
from app.engine.multi_agent.stream_utils import StreamEvent, StreamEventType

if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# =============================================================================
# TestEventQueueRegistry
# =============================================================================


class TestEventQueueRegistry:
    """Tests for _EVENT_QUEUES module-level registry."""

    def setup_method(self):
        _EVENT_QUEUES.clear()

    def teardown_method(self):
        _EVENT_QUEUES.clear()

    def test_create_and_get(self):
        q = asyncio.Queue()
        _EVENT_QUEUES["test-id"] = q
        result = _get_event_queue("test-id")
        assert result is q

    def test_cleanup_after_done(self):
        q = asyncio.Queue()
        _EVENT_QUEUES["bus-1"] = q
        _EVENT_QUEUES.pop("bus-1", None)
        assert _get_event_queue("bus-1") is None

    def test_unknown_id_returns_none(self):
        assert _get_event_queue("nonexistent") is None

    def test_multiple_queues(self):
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        _EVENT_QUEUES["a"] = q1
        _EVENT_QUEUES["b"] = q2
        assert _get_event_queue("a") is q1
        assert _get_event_queue("b") is q2

    def test_cleanup_one_doesnt_affect_other(self):
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        _EVENT_QUEUES["x"] = q1
        _EVENT_QUEUES["y"] = q2
        _EVENT_QUEUES.pop("x", None)
        assert _get_event_queue("x") is None
        assert _get_event_queue("y") is q2


# =============================================================================
# TestConvertBusEvent
# =============================================================================


class TestConvertBusEvent:
    """Tests for _convert_bus_event helper."""

    @pytest.mark.asyncio
    async def test_thinking_delta(self):
        event = await _convert_bus_event({
            "type": "thinking_delta",
            "content": "reasoning...",
            "node": "tutor_agent",
        })
        assert isinstance(event, StreamEvent)
        assert event.type == StreamEventType.THINKING_DELTA
        assert event.content == "reasoning..."
        assert event.node == "tutor_agent"

    @pytest.mark.asyncio
    async def test_tool_call(self):
        event = await _convert_bus_event({
            "type": "tool_call",
            "content": {"name": "search", "args": {"q": "test"}, "id": "c1"},
            "node": "tutor_agent",
        })
        assert event.type == StreamEventType.TOOL_CALL
        assert event.content["name"] == "search"
        assert event.content["id"] == "c1"

    @pytest.mark.asyncio
    async def test_tool_result(self):
        event = await _convert_bus_event({
            "type": "tool_result",
            "content": {"name": "search", "result": "found docs", "id": "c1"},
            "node": "tutor_agent",
        })
        assert event.type == StreamEventType.TOOL_RESULT
        assert event.content["result"] == "found docs"

    @pytest.mark.asyncio
    async def test_sources(self):
        sources = [
            {
                "title": "Weather Hai Phong",
                "content": "Cloudy and warm.",
                "url": "https://weather.example/hai-phong",
                "source_type": "web",
            }
        ]

        event = await _convert_bus_event({
            "type": "sources",
            "content": sources,
            "node": "direct",
        })

        assert event.type == StreamEventType.SOURCES
        assert event.content == sources

    @pytest.mark.asyncio
    async def test_visual(self):
        event = await _convert_bus_event({
            "type": "visual",
            "content": {
                "id": "visual-1",
                "visual_session_id": "vs-1",
                "type": "comparison",
                "runtime": "svg",
                "title": "A vs B",
                "summary": "Quick compare",
                "spec": {"left": {"title": "A"}, "right": {"title": "B"}},
            },
            "node": "direct",
        })
        assert event.type == StreamEventType.VISUAL_OPEN
        assert event.content["id"] == "visual-1"
        assert event.node == "direct"

    @pytest.mark.asyncio
    async def test_visual_lifecycle_events(self):
        patch_event = await _convert_bus_event({
            "type": "visual_patch",
            "content": {
                "id": "visual-2",
                "visual_session_id": "vs-2",
                "type": "process",
                "runtime": "svg",
                "title": "Pipeline",
                "summary": "Process summary",
                "spec": {"steps": [{"title": "Start"}, {"title": "End"}]},
            },
            "node": "direct",
        })
        commit_event = await _convert_bus_event({
            "type": "visual_commit",
            "content": {"visual_session_id": "vs-2", "status": "committed"},
            "node": "direct",
        })
        dispose_event = await _convert_bus_event({
            "type": "visual_dispose",
            "content": {"visual_session_id": "vs-2", "status": "disposed", "reason": "reset"},
            "node": "direct",
        })

        assert patch_event.type == StreamEventType.VISUAL_PATCH
        assert commit_event.type == StreamEventType.VISUAL_COMMIT
        assert commit_event.content["visual_session_id"] == "vs-2"
        assert dispose_event.type == StreamEventType.VISUAL_DISPOSE

    @pytest.mark.asyncio
    async def test_unknown_fallback_status(self):
        event = await _convert_bus_event({
            "type": "unknown_type",
            "content": "something",
            "node": "test",
        })
        assert event.type == StreamEventType.STATUS
        assert event.content == "something"

    @pytest.mark.asyncio
    async def test_missing_content(self):
        event = await _convert_bus_event({
            "type": "thinking_delta",
        })
        assert event.content == ""
        assert event.node is None

    @pytest.mark.asyncio
    async def test_tool_call_empty_args(self):
        event = await _convert_bus_event({
            "type": "tool_call",
            "content": {"name": "tool", "args": {}, "id": "x"},
        })
        assert event.content["args"] == {}


# =============================================================================
# TestConcurrentConsumption
# =============================================================================


class TestConcurrentConsumption:
    """Tests for concurrent graph + queue consumption pattern."""

    def setup_method(self):
        _EVENT_QUEUES.clear()

    def teardown_method(self):
        _EVENT_QUEUES.clear()

    @pytest.mark.asyncio
    async def test_queue_events_drained(self):
        """Events put in queue should be retrievable."""
        q = asyncio.Queue()
        q.put_nowait({"type": "thinking_delta", "content": "hello", "node": "test"})
        q.put_nowait({"type": "tool_call", "content": {"name": "x", "args": {}, "id": "1"}, "node": "test"})

        events = []
        while not q.empty():
            raw = q.get_nowait()
            event = await _convert_bus_event(raw)
            events.append(event)

        assert len(events) == 2
        assert events[0].type == StreamEventType.THINKING_DELTA
        assert events[1].type == StreamEventType.TOOL_CALL

    @pytest.mark.asyncio
    async def test_non_agentic_nodes_unaffected(self):
        """Nodes that don't use event bus should work identically."""
        # No bus_id set → _get_event_queue returns None
        result = _get_event_queue("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_put_and_get(self):
        """Multiple concurrent puts should all be retrievable."""
        q = asyncio.Queue()

        async def producer():
            for i in range(5):
                q.put_nowait({"type": "thinking_delta", "content": f"tok_{i}", "node": "t"})
                await asyncio.sleep(0.001)

        await producer()
        assert q.qsize() == 5

        collected = []
        while not q.empty():
            collected.append(q.get_nowait())
        assert len(collected) == 5
        assert collected[0]["content"] == "tok_0"
        assert collected[4]["content"] == "tok_4"


# =============================================================================
# TestIntegration
# =============================================================================


class TestIntegration:
    """Integration-style tests for event bus + graph streaming."""

    def setup_method(self):
        _EVENT_QUEUES.clear()

    def teardown_method(self):
        _EVENT_QUEUES.clear()

    def test_bus_id_stored_and_retrieved(self):
        """Bus ID can be stored in state and retrieved by nodes."""
        import uuid
        bus_id = str(uuid.uuid4())
        q = asyncio.Queue()
        _EVENT_QUEUES[bus_id] = q

        # Simulates what tutor_node does
        retrieved_q = _get_event_queue(bus_id)
        assert retrieved_q is q

    def test_backward_compat_no_bus(self):
        """When _event_bus_id is not in state, no event queue is used."""
        state = {"query": "hello"}
        bus_id = state.get("_event_bus_id")
        assert bus_id is None
        result = _get_event_queue(bus_id) if bus_id else None
        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_removes_queue(self):
        """After cleanup, queue should no longer be accessible."""
        bus_id = "cleanup-test"
        q = asyncio.Queue()
        _EVENT_QUEUES[bus_id] = q

        # Simulate finally block
        _EVENT_QUEUES.pop(bus_id, None)
        assert _get_event_queue(bus_id) is None
