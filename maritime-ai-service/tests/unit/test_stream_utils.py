"""
Unit tests for Stream Utilities.

Tests:
- StreamEvent.to_dict() serialization
- StreamEventType constants
- create_* event generators
- NODE_DESCRIPTIONS and NODE_STEPS mappings
"""

import asyncio
import sys
import types
import pytest

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

from app.engine.multi_agent.stream_utils import (
    StreamEvent,
    StreamEventType,
    NODE_DESCRIPTIONS,
    NODE_STEPS,
    create_status_event,
    create_thinking_event,
    create_answer_event,
    create_sources_event,
    create_metadata_event,
    create_done_event,
    create_error_event,
    create_thinking_delta_event,
)

if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# =============================================================================
# Tests: StreamEventType
# =============================================================================

class TestStreamEventType:
    def test_status_type(self):
        assert StreamEventType.STATUS == "status"

    def test_thinking_type(self):
        assert StreamEventType.THINKING == "thinking"

    def test_answer_type(self):
        assert StreamEventType.ANSWER == "answer"

    def test_sources_type(self):
        assert StreamEventType.SOURCES == "sources"

    def test_metadata_type(self):
        assert StreamEventType.METADATA == "metadata"

    def test_done_type(self):
        assert StreamEventType.DONE == "done"

    def test_error_type(self):
        assert StreamEventType.ERROR == "error"

    def test_tool_call_type(self):
        assert StreamEventType.TOOL_CALL == "tool_call"

    def test_thinking_delta_type(self):
        assert StreamEventType.THINKING_DELTA == "thinking_delta"


# =============================================================================
# Tests: StreamEvent
# =============================================================================

class TestStreamEvent:
    def test_to_dict_minimal(self):
        event = StreamEvent(type="answer", content="hello")
        d = event.to_dict()
        assert d == {"type": "answer", "content": "hello"}

    def test_to_dict_with_node(self):
        event = StreamEvent(type="status", content="msg", node="supervisor")
        d = event.to_dict()
        assert d["node"] == "supervisor"

    def test_to_dict_with_step(self):
        event = StreamEvent(type="thinking", content="msg", step="routing")
        d = event.to_dict()
        assert d["step"] == "routing"

    def test_to_dict_with_confidence(self):
        event = StreamEvent(type="thinking", content="msg", confidence=0.85)
        d = event.to_dict()
        assert d["confidence"] == 0.85

    def test_to_dict_with_details(self):
        details = {"score": 8, "passed": True}
        event = StreamEvent(type="thinking", content="msg", details=details)
        d = event.to_dict()
        assert d["details"] == details

    def test_to_dict_excludes_none_optionals(self):
        event = StreamEvent(type="answer", content="text")
        d = event.to_dict()
        assert "node" not in d
        assert "step" not in d
        assert "confidence" not in d
        assert "details" not in d

    def test_to_dict_zero_confidence_included(self):
        """Confidence of 0.0 should be included (not treated as falsy)."""
        event = StreamEvent(type="thinking", content="msg", confidence=0.0)
        d = event.to_dict()
        assert "confidence" in d
        assert d["confidence"] == 0.0


# =============================================================================
# Tests: NODE_DESCRIPTIONS and NODE_STEPS
# =============================================================================

class TestNodeMappings:
    def test_node_descriptions_has_all_nodes(self):
        expected = {"supervisor", "rag_agent", "tutor_agent", "memory_agent", "direct", "code_studio_agent", "grader", "synthesizer", "product_search_agent"}
        assert set(NODE_DESCRIPTIONS.keys()) == expected

    def test_node_steps_has_all_nodes(self):
        expected = {"supervisor", "rag_agent", "tutor_agent", "memory_agent", "direct", "code_studio_agent", "grader", "synthesizer", "product_search_agent"}
        assert set(NODE_STEPS.keys()) == expected

    def test_node_descriptions_are_strings(self):
        for desc in NODE_DESCRIPTIONS.values():
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_node_steps_are_strings(self):
        for step in NODE_STEPS.values():
            assert isinstance(step, str)
            assert len(step) > 0


# =============================================================================
# Tests: Event Generators
# =============================================================================

class TestEventGenerators:
    @pytest.fixture(autouse=True)
    def _setup_loop(self):
        """Ensure event loop is available."""
        pass

    @pytest.mark.asyncio
    async def test_create_status_event(self):
        event = await create_status_event("Processing...", "supervisor")
        assert event.type == StreamEventType.STATUS
        assert event.content == "Processing..."
        assert event.node == "supervisor"
        assert event.step == "routing"

    @pytest.mark.asyncio
    async def test_create_status_event_no_node(self):
        event = await create_status_event("Starting...")
        assert event.node is None
        assert event.step is None

    @pytest.mark.asyncio
    async def test_create_thinking_event(self):
        event = await create_thinking_event("Routing to RAG", "routing", confidence=0.9, details={"routed_to": "rag"})
        assert event.type == StreamEventType.THINKING
        assert event.content == "Routing to RAG"
        assert event.step == "routing"
        assert event.confidence == 0.9
        assert event.details == {"routed_to": "rag"}

    @pytest.mark.asyncio
    async def test_create_answer_event(self):
        event = await create_answer_event("Hello world")
        assert event.type == StreamEventType.ANSWER
        assert event.content == "Hello world"

    @pytest.mark.asyncio
    async def test_create_sources_event(self):
        sources = [{"title": "Doc1", "content": "..."}]
        event = await create_sources_event(sources)
        assert event.type == StreamEventType.SOURCES
        assert event.content == sources

    @pytest.mark.asyncio
    async def test_create_sources_event_preserves_tool_identity(self):
        sources = [{"title": "Doc1", "content": "..."}]
        event = await create_sources_event(
            sources,
            node="direct",
            tool_call_id="tc_search",
            tool_name="tool_web_search",
        )
        assert event.type == StreamEventType.SOURCES
        assert event.content == sources
        assert event.node == "direct"
        assert event.details == {
            "tool_call_id": "tc_search",
            "tool_name": "tool_web_search",
        }

    @pytest.mark.asyncio
    async def test_create_metadata_event(self):
        event = await create_metadata_event(
            reasoning_trace={"steps": []},
            processing_time=1.5,
            confidence=0.8,
            model="agentic-rag-v3"
        )
        assert event.type == StreamEventType.METADATA
        assert event.content["processing_time"] == 1.5
        assert event.content["confidence"] == 0.8
        assert event.content["model"] == "agentic-rag-v3"
        assert event.content["streaming_version"] == "v3"

    @pytest.mark.asyncio
    async def test_create_done_event(self):
        event = await create_done_event(2.345)
        assert event.type == StreamEventType.DONE
        assert event.content["status"] == "complete"
        assert event.content["total_time"] == 2.345

    @pytest.mark.asyncio
    async def test_create_error_event(self):
        event = await create_error_event("Something broke")
        assert event.type == StreamEventType.ERROR
        assert event.content["message"] == "Something broke"

    @pytest.mark.asyncio
    async def test_create_thinking_delta_event(self):
        event = await create_thinking_delta_event("partial token", "tutor_agent")
        assert event.type == StreamEventType.THINKING_DELTA
        assert event.content == "partial token"
        assert event.node == "tutor_agent"

    @pytest.mark.asyncio
    async def test_create_thinking_delta_event_no_node(self):
        event = await create_thinking_delta_event("token")
        assert event.type == StreamEventType.THINKING_DELTA
        assert event.node is None

    @pytest.mark.asyncio
    async def test_create_thinking_delta_event_empty_content(self):
        event = await create_thinking_delta_event("")
        assert event.content == ""

    @pytest.mark.asyncio
    async def test_thinking_delta_to_dict(self):
        event = await create_thinking_delta_event("hello", "test_node")
        d = event.to_dict()
        assert d["type"] == "thinking_delta"
        assert d["content"] == "hello"
        assert d["node"] == "test_node"

    @pytest.mark.asyncio
    async def test_thinking_delta_serializable(self):
        """thinking_delta events should be JSON-serializable."""
        import json
        event = await create_thinking_delta_event("content", "node")
        d = event.to_dict()
        serialized = json.dumps(d)
        assert "thinking_delta" in serialized
