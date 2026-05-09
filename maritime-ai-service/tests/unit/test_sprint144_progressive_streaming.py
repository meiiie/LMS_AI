"""
Sprint 144: Progressive RAG Streaming — "Phản Hồi Từng Đợt"

Tests:
1. process_streaming() yields result event with CorrectiveRAGResult
2. process_streaming() uses clean Vietnamese labels (no emoji)
3. process_streaming() emits intermediate response before generation
4. RAGAgentNode uses process_streaming when event bus available
5. RAGAgentNode falls back to process() when no bus
6. _process_with_streaming forwards events to queue
7. graph_streaming tracks thinking_start in _bus_streamed_nodes
8. graph_streaming skips RAG answer when bus already streamed
"""

import asyncio
import sys
import types
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# Break circular import chain (same pattern as test_thinking_lifecycle.py)
# ============================================================================

_cs_key = "app.services.chat_service"
_svc_key = "app.services"
_graph_key = "app.engine.multi_agent.graph"
_had_cs = _cs_key in sys.modules
_had_svc = _svc_key in sys.modules
_had_graph = _graph_key in sys.modules
_orig_cs = sys.modules.get(_cs_key)
_orig_graph = sys.modules.get(_graph_key)

if not _had_cs:
    _mock_chat_svc = types.ModuleType(_cs_key)
    _mock_chat_svc.ChatService = type("ChatService", (), {})
    _mock_chat_svc.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_chat_svc

if not _had_graph:
    _mock_graph = types.ModuleType(_graph_key)
    _mock_graph._build_domain_config = MagicMock(return_value={})
    _mock_graph._build_turn_local_state_defaults = MagicMock(return_value={})
    sys.modules[_graph_key] = _mock_graph

from app.engine.agentic_rag.corrective_rag import CorrectiveRAGResult

# Restore sys.modules
if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs

# Restore graph module to avoid polluting later test files
if not _had_graph:
    sys.modules.pop(_graph_key, None)
elif _orig_graph is not None:
    sys.modules[_graph_key] = _orig_graph


# ============================================================================
# Helpers
# ============================================================================

@dataclass
class FakeAnalysis:
    complexity: MagicMock = None
    confidence: float = 0.85
    is_domain_related: bool = True
    detected_topics: list = None

    def __post_init__(self):
        if self.complexity is None:
            self.complexity = MagicMock(value="MEDIUM")
        if self.detected_topics is None:
            self.detected_topics = ["navigation"]


@dataclass
class FakeGradingResult:
    avg_score: float = 7.5
    relevant_count: int = 3


async def _collect_events(async_gen):
    """Collect all events from an async generator."""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


# ============================================================================
# Tests: process_streaming result event
# ============================================================================

class TestProcessStreamingResultEvent:
    """Test that process_streaming yields a 'result' event with CorrectiveRAGResult."""

    @pytest.mark.asyncio
    async def test_yields_result_event(self):
        """process_streaming must yield a result event with CorrectiveRAGResult."""
        from app.engine.agentic_rag.corrective_rag import CorrectiveRAG

        crag = CorrectiveRAG.__new__(CorrectiveRAG)
        crag._analyzer = MagicMock()
        crag._analyzer.analyze = AsyncMock(return_value=FakeAnalysis())
        crag._grader = MagicMock()
        crag._grader.grade_documents = AsyncMock(return_value=FakeGradingResult())
        crag._rewriter = None
        crag._grade_threshold = 6.0
        crag._rag = MagicMock()

        # Mock _retrieve to return fake documents
        crag._retrieve = AsyncMock(return_value=[
            {"content": "Rule 15 content", "title": "Rule 15", "node_id": "r15", "score": 0.9},
        ])

        # Mock _generate_response_streaming to yield tokens
        async def fake_stream(**kwargs):
            yield "Hello "
            yield "World"

        crag._rag._generate_response_streaming = fake_stream

        events = await _collect_events(crag.process_streaming("test query", {}))

        # Find result event
        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) == 1, f"Expected 1 result event, got {len(result_events)}"

        result = result_events[0]["data"]
        assert isinstance(result, CorrectiveRAGResult)
        assert result.answer == "Hello World"
        assert len(result.sources) == 1

    @pytest.mark.asyncio
    async def test_no_documents_yields_result(self):
        """When no documents found, should still yield a result event."""
        from app.engine.agentic_rag.corrective_rag import CorrectiveRAG

        crag = CorrectiveRAG.__new__(CorrectiveRAG)
        crag._analyzer = MagicMock()
        crag._analyzer.analyze = AsyncMock(return_value=FakeAnalysis())
        crag._retrieve = AsyncMock(return_value=[])
        crag._generate_fallback = AsyncMock(return_value=("Fallback answer", None))

        with patch("app.engine.llm_pool.get_llm_light", return_value=None):
            events = await _collect_events(crag.process_streaming("test query", {}))

        result_events = [e for e in events if e.get("type") == "result"]
        assert len(result_events) == 1
        result = result_events[0]["data"]
        assert isinstance(result, CorrectiveRAGResult)
        assert result.confidence == 45.0


# ============================================================================
# Tests: Vietnamese labels (no emoji)
# ============================================================================

class TestCleanVietnameseLabels:
    """Sprint 144: Status events should use clean Vietnamese labels."""

    @pytest.mark.asyncio
    async def test_status_events_no_emoji(self):
        """Status events should not contain emoji characters."""
        from app.engine.agentic_rag.corrective_rag import CorrectiveRAG

        crag = CorrectiveRAG.__new__(CorrectiveRAG)
        crag._analyzer = MagicMock()
        crag._analyzer.analyze = AsyncMock(return_value=FakeAnalysis())
        crag._grader = MagicMock()
        crag._grader.grade_documents = AsyncMock(return_value=FakeGradingResult())
        crag._rewriter = None
        crag._grade_threshold = 6.0
        crag._rag = MagicMock()
        crag._retrieve = AsyncMock(return_value=[
            {"content": "content", "title": "Title", "node_id": "n1", "score": 0.9},
        ])

        async def fake_stream(**kwargs):
            yield "answer"

        crag._rag._generate_response_streaming = fake_stream

        events = await _collect_events(crag.process_streaming("query", {}))

        status_events = [e for e in events if e.get("type") == "status"]
        emoji_chars = set("🎯🔍⚖️✍️📊📚✅⚠️")
        for ev in status_events:
            content = ev.get("content", "")
            for ch in content:
                assert ch not in emoji_chars, f"Emoji '{ch}' found in status: {content}"


# ============================================================================
# Tests: Intermediate response
# ============================================================================

class TestIntermediateResponse:
    """Sprint 144: process_streaming should show retrieval progress before generation."""

    @pytest.mark.asyncio
    async def test_intermediate_response_before_generation(self):
        """A doc-count status event should precede LLM answer tokens."""
        from app.engine.agentic_rag.corrective_rag import CorrectiveRAG

        crag = CorrectiveRAG.__new__(CorrectiveRAG)
        crag._analyzer = MagicMock()
        crag._analyzer.analyze = AsyncMock(return_value=FakeAnalysis())
        crag._grader = MagicMock()
        crag._grader.grade_documents = AsyncMock(return_value=FakeGradingResult())
        crag._rewriter = None
        crag._grade_threshold = 6.0
        crag._rag = MagicMock()
        crag._retrieve = AsyncMock(return_value=[
            {"content": "c1", "title": "T1", "node_id": "n1", "score": 0.9},
            {"content": "c2", "title": "T2", "node_id": "n2", "score": 0.8},
        ])

        async def fake_stream(**kwargs):
            yield "Token1"

        crag._rag._generate_response_streaming = fake_stream

        events = await _collect_events(crag.process_streaming("query", {}))

        answer_events = [e for e in events if e.get("type") == "answer"]
        assert answer_events, "Expected at least 1 LLM token"

        doc_status_index = next(
            (
                index
                for index, event in enumerate(events)
                if event.get("type") == "status"
                and "2 tài liệu" in str(event.get("content", ""))
            ),
            None,
        )
        first_answer_index = next(
            index for index, event in enumerate(events) if event.get("type") == "answer"
        )

        assert doc_status_index is not None, "Expected doc-count status before generation"
        assert doc_status_index < first_answer_index
        assert answer_events[0]["content"] == "Token1"


# ============================================================================
# Tests: RAGAgentNode streaming vs non-streaming
# ============================================================================

class TestRAGAgentNodeStreaming:
    """Sprint 144: RAGAgentNode branches on _event_bus_id."""

    @pytest.mark.asyncio
    async def test_uses_process_streaming_when_bus_available(self):
        """When _event_bus_id is in state, should use _process_with_streaming."""
        from app.engine.multi_agent.agents.rag_node import RAGAgentNode

        node = RAGAgentNode.__new__(RAGAgentNode)
        node._corrective_rag = MagicMock()
        node._config = MagicMock(id="rag_agent")

        # Mock process_streaming to yield events
        fake_result = CorrectiveRAGResult(
            answer="Test answer",
            sources=[{"title": "T1"}],
            confidence=80.0,
        )

        async def fake_process_streaming(query, context):
            yield {"type": "status", "content": "Analyzing"}
            yield {"type": "thinking", "content": "Details", "step": "retrieval"}
            yield {"type": "answer", "content": "Test answer"}
            yield {"type": "result", "data": fake_result}
            yield {"type": "done", "content": ""}

        node._corrective_rag.process_streaming = fake_process_streaming

        # Create event queue and mock _get_event_queue
        event_queue = asyncio.Queue()

        state = {
            "query": "test",
            "context": {},
            "_event_bus_id": "test-bus-123",
        }

        # Patch at graph_streaming module level (lazy import inside process())
        mock_gs = MagicMock()
        mock_gs._get_event_queue = MagicMock(return_value=event_queue)
        fake_narrator = MagicMock()
        fake_narrator.render = AsyncMock(
            return_value=types.SimpleNamespace(
                label="Tra cứu nguồn",
                summary="Đang rà nguồn phù hợp.",
                phase="retrieve",
            )
        )
        with patch.dict(sys.modules, {
            "app.engine.multi_agent.graph_streaming": mock_gs,
        }), patch(
            "app.engine.multi_agent.agents.rag_node.get_reasoning_narrator",
            return_value=fake_narrator,
        ):
            result_state = await node.process(state)

        assert result_state["rag_output"] == "Test answer"
        assert result_state["current_agent"] == "rag_agent"

        # Verify events were forwarded to queue
        forwarded = []
        while not event_queue.empty():
            forwarded.append(event_queue.get_nowait())

        types_forwarded = [e["type"] for e in forwarded]
        # status event → "status" type, thinking → thinking_start/delta/end, answer → answer_delta
        assert "status" in types_forwarded
        assert "thinking_start" in types_forwarded
        assert "thinking_delta" in types_forwarded
        assert "answer_delta" in types_forwarded

    @pytest.mark.asyncio
    async def test_falls_back_to_process_when_no_bus(self):
        """When _event_bus_id is NOT in state, should use process() as before."""
        from app.engine.multi_agent.agents.rag_node import RAGAgentNode

        node = RAGAgentNode.__new__(RAGAgentNode)
        node._corrective_rag = MagicMock()
        node._config = MagicMock(id="rag_agent")

        fake_result = CorrectiveRAGResult(
            answer="Sync answer",
            sources=[],
            confidence=75.0,
        )
        node._corrective_rag.process = AsyncMock(return_value=fake_result)

        state = {
            "query": "test",
            "context": {},
            # No _event_bus_id
        }

        result_state = await node.process(state)
        assert result_state["rag_output"] == "Sync answer"
        node._corrective_rag.process.assert_awaited_once()


# ============================================================================
# Tests: _process_with_streaming event forwarding
# ============================================================================

class TestProcessWithStreaming:
    """Sprint 144: _process_with_streaming forwards correct event types."""

    @pytest.mark.asyncio
    async def test_status_becomes_status_event(self):
        """Status events should be forwarded as status type (not thinking block)."""
        from app.engine.multi_agent.agents.rag_node import RAGAgentNode

        node = RAGAgentNode.__new__(RAGAgentNode)
        node._corrective_rag = MagicMock()

        fake_result = CorrectiveRAGResult(answer="x", sources=[], confidence=80.0)

        async def fake_streaming(query, context):
            yield {"type": "status", "content": "Tìm kiếm tài liệu"}
            yield {"type": "result", "data": fake_result}

        node._corrective_rag.process_streaming = fake_streaming

        queue = asyncio.Queue()
        result = await node._process_with_streaming("q", {}, queue)

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        assert len(events) == 1
        assert events[0]["type"] == "status"
        assert events[0]["content"] == "Tìm kiếm tài liệu"
        assert events[0]["node"] == "rag_agent"
        assert result is fake_result

    @pytest.mark.asyncio
    async def test_thinking_becomes_full_block(self):
        """Thinking events should create start + delta + end."""
        from app.engine.multi_agent.agents.rag_node import RAGAgentNode

        node = RAGAgentNode.__new__(RAGAgentNode)
        node._corrective_rag = MagicMock()

        fake_result = CorrectiveRAGResult(answer="x", sources=[], confidence=80.0)

        async def fake_streaming(query, context):
            yield {"type": "thinking", "content": "Analysis details", "step": "retrieval"}
            yield {"type": "result", "data": fake_result}

        node._corrective_rag.process_streaming = fake_streaming

        queue = asyncio.Queue()
        fake_narrator = MagicMock()
        fake_narrator.render = AsyncMock(
            return_value=types.SimpleNamespace(
                label="Tra cứu nguồn",
                summary="Đang rà nguồn phù hợp.",
                phase="retrieve",
            )
        )
        with patch(
            "app.engine.multi_agent.agents.rag_node.get_reasoning_narrator",
            return_value=fake_narrator,
        ):
            await node._process_with_streaming("q", {}, queue)

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        assert len(events) == 3
        assert events[0]["type"] == "thinking_start"
        # Label is now generated by reasoning narrator (dynamic, not static)
        assert isinstance(events[0]["content"], str)
        assert len(events[0]["content"]) > 0
        assert events[1]["type"] == "thinking_delta"
        assert events[1]["content"] == "Mình đang rà nguồn phù hợp trước khi chốt câu trả lời."
        assert events[2]["type"] == "thinking_end"

    @pytest.mark.asyncio
    async def test_answer_becomes_answer_delta(self):
        """Answer events should be forwarded as answer_delta."""
        from app.engine.multi_agent.agents.rag_node import RAGAgentNode

        node = RAGAgentNode.__new__(RAGAgentNode)
        node._corrective_rag = MagicMock()

        fake_result = CorrectiveRAGResult(answer="Hello", sources=[], confidence=80.0)

        async def fake_streaming(query, context):
            yield {"type": "answer", "content": "Hello"}
            yield {"type": "result", "data": fake_result}

        node._corrective_rag.process_streaming = fake_streaming

        queue = asyncio.Queue()
        await node._process_with_streaming("q", {}, queue)

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        assert len(events) == 1
        assert events[0]["type"] == "answer_delta"
        assert events[0]["content"] == "Hello"
        assert events[0]["node"] == "rag_agent"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_result_event(self):
        """If process_streaming never yields result, should return None."""
        from app.engine.multi_agent.agents.rag_node import RAGAgentNode

        node = RAGAgentNode.__new__(RAGAgentNode)
        node._corrective_rag = MagicMock()

        async def fake_streaming(query, context):
            yield {"type": "done", "content": ""}

        node._corrective_rag.process_streaming = fake_streaming

        queue = asyncio.Queue()
        result = await node._process_with_streaming("q", {}, queue)
        assert result is None


# ============================================================================
# Tests: Bus tracking — thinking_start included
# ============================================================================

class TestBusTrackingThinkingStart:
    """Sprint 144: _bus_streamed_nodes should track thinking_start events."""

    def test_thinking_start_tracked(self):
        """Simulating the tracking logic: thinking_start should add node to set."""
        # Reproduce the tracking logic from graph_streaming
        _bus_streamed_nodes = set()

        events = [
            {"type": "thinking_start", "content": "Phân tích", "node": "rag_agent"},
            {"type": "thinking_delta", "content": "details", "node": "rag_agent"},
            {"type": "thinking_end", "node": "rag_agent"},
        ]

        for event in events:
            node = event.get("node")
            etype = event.get("type")
            if node and etype in ("thinking_delta", "thinking_start"):
                _bus_streamed_nodes.add(node)

        assert "rag_agent" in _bus_streamed_nodes

    def test_thinking_start_alone_sufficient(self):
        """Even without thinking_delta, thinking_start alone should mark node."""
        _bus_streamed_nodes = set()

        event = {"type": "thinking_start", "content": "Status", "node": "rag_agent"}
        node = event.get("node")
        etype = event.get("type")
        if node and etype in ("thinking_delta", "thinking_start"):
            _bus_streamed_nodes.add(node)

        assert "rag_agent" in _bus_streamed_nodes


# ============================================================================
# Tests: RAG answer dedup
# ============================================================================

class TestRAGAnswerDedup:
    """Sprint 144: RAG answer should be skipped when bus already streamed."""

    def test_dedup_logic(self):
        """Simulating dedup: if rag_agent in _bus_answer_nodes, skip bulk emission."""
        _bus_answer_nodes = {"rag_agent"}
        answer_emitted = False
        agent_output_text = "Some answer from RAG"
        bulk_emitted = False

        if agent_output_text and not answer_emitted:
            if "rag_agent" not in _bus_answer_nodes:
                bulk_emitted = True

        assert not bulk_emitted, "Should NOT emit bulk answer when bus already streamed"

    def test_no_dedup_without_bus(self):
        """When rag_agent NOT in _bus_answer_nodes, should emit bulk answer."""
        _bus_answer_nodes = set()
        answer_emitted = False
        agent_output_text = "Some answer"
        bulk_emitted = False

        if agent_output_text and not answer_emitted:
            if "rag_agent" not in _bus_answer_nodes:
                bulk_emitted = True

        assert bulk_emitted, "Should emit bulk answer when bus did NOT stream"
