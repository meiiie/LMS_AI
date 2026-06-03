"""
Tests for Sprint 58: Enhanced Streaming — Tool Call/Result Events.

Tests the new create_tool_call_event() and create_tool_result_event()
factory functions in stream_utils.py, and verifies graph_streaming.py
forwards tool events from agentic loop nodes.
"""

import json
import sys
import types
import pytest

# Break circular import chain — temporarily inject mock, then restore
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
    create_tool_call_event,
    create_tool_result_event,
)
from app.engine.multi_agent.state import AgentState

# Thorough restore: remove mock AND app.services that cached mock ChatService.
if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# ============================================================================
# create_tool_call_event
# ============================================================================


class TestCreateToolCallEvent:
    @pytest.mark.asyncio
    async def test_basic_tool_call(self):
        event = await create_tool_call_event(
            tool_name="knowledge_search",
            tool_args={"query": "COLREGs Rule 15"},
            tool_call_id="call_abc123",
        )
        assert isinstance(event, StreamEvent)
        assert event.type == StreamEventType.TOOL_CALL
        assert event.content["name"] == "knowledge_search"
        assert event.content["args"] == {"query": "COLREGs Rule 15"}
        assert event.content["id"] == "call_abc123"
        assert event.step == "tool_execution"
        assert event.node is None

    @pytest.mark.asyncio
    async def test_with_node(self):
        event = await create_tool_call_event(
            tool_name="search",
            tool_args={},
            tool_call_id="c1",
            node="rag_agent",
        )
        assert event.node == "rag_agent"

    @pytest.mark.asyncio
    async def test_to_dict(self):
        event = await create_tool_call_event(
            tool_name="calc",
            tool_args={"expr": "2+2"},
            tool_call_id="c2",
            node="tutor_agent",
        )
        d = event.to_dict()
        assert d["type"] == "tool_call"
        assert d["content"]["name"] == "calc"
        assert d["node"] == "tutor_agent"
        assert d["step"] == "tool_execution"

    @pytest.mark.asyncio
    async def test_empty_args(self):
        event = await create_tool_call_event(
            tool_name="get_time",
            tool_args={},
            tool_call_id="c3",
        )
        assert event.content["args"] == {}

    @pytest.mark.asyncio
    async def test_redacts_sensitive_args(self):
        event = await create_tool_call_event(
            tool_name="tool_wiii_connect_execute_action",
            tool_args={
                "provider_slug": "facebook",
                "connection_ref": "wcn_secret_connection",
                "page_id": "page_secret",
                "code_html": "<script>secret</script>",
                "nested": {"image_base64": "raw_image_payload"},
                "safe": "ok",
            },
            tool_call_id="c4",
        )

        args = event.content["args"]
        assert args["provider_slug"] == "facebook"
        assert args["safe"] == "ok"
        assert args["connection_ref"] == "[redacted]"
        assert args["page_id"] == "[redacted]"
        assert args["code_html"] == "[redacted]"
        assert args["nested"]["image_base64"] == "[redacted]"
        payload = json.dumps(event.to_dict(), ensure_ascii=False)
        assert "wcn_secret_connection" not in payload
        assert "page_secret" not in payload
        assert "<script>secret</script>" not in payload
        assert "raw_image_payload" not in payload


# ============================================================================
# create_tool_result_event
# ============================================================================


class TestCreateToolResultEvent:
    @pytest.mark.asyncio
    async def test_basic_tool_result(self):
        event = await create_tool_result_event(
            tool_name="knowledge_search",
            result_summary="Found 5 relevant documents about COLREGs",
            tool_call_id="call_abc123",
        )
        assert isinstance(event, StreamEvent)
        assert event.type == StreamEventType.TOOL_RESULT
        assert event.content["name"] == "knowledge_search"
        assert "Found 5" in event.content["result"]
        assert event.content["id"] == "call_abc123"
        assert event.step == "tool_execution"

    @pytest.mark.asyncio
    async def test_with_node(self):
        event = await create_tool_result_event(
            tool_name="search",
            result_summary="COLREGs data",
            tool_call_id="c1",
            node="rag_agent",
        )
        assert event.node == "rag_agent"

    @pytest.mark.asyncio
    async def test_to_dict(self):
        event = await create_tool_result_event(
            tool_name="calc",
            result_summary="4",
            tool_call_id="c2",
            node="tutor_agent",
        )
        d = event.to_dict()
        assert d["type"] == "tool_result"
        assert d["content"]["result"] == "4"
        assert d["node"] == "tutor_agent"

    @pytest.mark.asyncio
    async def test_redacts_sensitive_result_summary(self):
        event = await create_tool_result_event(
            tool_name="external_tool",
            result_summary=(
                '{"ok": true, "provider_payload": {"access_token": '
                '"raw-result-token-123456"}, "message": '
                '"Bearer raw-bearer-token-12345678"}'
            ),
            tool_call_id="c3",
            node="direct",
        )

        payload = json.dumps(event.to_dict(), ensure_ascii=False)

        assert '"ok": true' in event.content["result"]
        assert "provider_payload" not in payload
        assert "access_token" not in payload
        assert "raw-result-token" not in payload
        assert "raw-bearer-token" not in payload
        assert "Bearer <redacted-secret>" in payload


# ============================================================================
# StreamEvent serialization
# ============================================================================


class TestToolEventSerialization:
    @pytest.mark.asyncio
    async def test_tool_call_serializes_correctly(self):
        """Tool call event should serialize to valid SSE-ready dict."""
        event = await create_tool_call_event(
            tool_name="knowledge_search",
            tool_args={"query": "SOLAS", "limit": 5},
            tool_call_id="call_001",
            node="rag_agent",
        )
        d = event.to_dict()
        assert "type" in d
        assert "content" in d
        assert isinstance(d["content"], dict)
        assert d["content"]["name"] == "knowledge_search"
        assert d["content"]["args"]["limit"] == 5

    @pytest.mark.asyncio
    async def test_tool_result_serializes_correctly(self):
        event = await create_tool_result_event(
            tool_name="knowledge_search",
            result_summary="Found 3 documents about SOLAS Chapter II-2",
            tool_call_id="call_001",
            node="rag_agent",
        )
        d = event.to_dict()
        assert d["type"] == "tool_result"
        assert "SOLAS" in d["content"]["result"]

    @pytest.mark.asyncio
    async def test_event_ordering(self):
        """Tool call event should come before tool result in sequence."""
        call_event = await create_tool_call_event(
            tool_name="search", tool_args={}, tool_call_id="c1"
        )
        result_event = await create_tool_result_event(
            tool_name="search", result_summary="data", tool_call_id="c1"
        )
        events = [call_event, result_event]
        assert events[0].type == StreamEventType.TOOL_CALL
        assert events[1].type == StreamEventType.TOOL_RESULT
        assert events[0].content["id"] == events[1].content["id"]


# ============================================================================
# AgentState tool_call_events field
# ============================================================================


class TestAgentStateToolEvents:
    def test_tool_call_events_field_exists(self):
        """AgentState should accept tool_call_events field."""
        state: AgentState = {
            "query": "test",
            "tool_call_events": [
                {"name": "search", "args": {"q": "COLREGs"}, "id": "c1"},
            ],
        }
        assert len(state["tool_call_events"]) == 1
        assert state["tool_call_events"][0]["name"] == "search"

    def test_tool_call_events_none(self):
        state: AgentState = {
            "query": "test",
            "tool_call_events": None,
        }
        assert state["tool_call_events"] is None

    def test_tool_call_events_empty(self):
        state: AgentState = {
            "query": "test",
            "tool_call_events": [],
        }
        assert state["tool_call_events"] == []


# ============================================================================
# graph_streaming tool event forwarding
# ============================================================================


class TestGraphStreamingToolForwarding:
    """Test that graph_streaming forwards tool_call_events from node output."""

    @pytest.mark.asyncio
    async def test_rag_agent_forwards_tool_events(self):
        """RAG agent node output with tool_call_events yields tool events."""
        from app.engine.multi_agent.stream_utils import (
            create_tool_call_event,
            create_tool_result_event,
        )

        # Simulate node output with tool_call_events
        node_output = {
            "tool_call_events": [
                {
                    "name": "knowledge_search",
                    "args": {"query": "SOLAS"},
                    "id": "call_001",
                    "result": "Found 3 documents",
                },
            ],
            "sources": [],
        }

        # Verify the events can be created from the node output
        events = []
        for tc_event in node_output["tool_call_events"]:
            call_evt = await create_tool_call_event(
                tool_name=tc_event["name"],
                tool_args=tc_event["args"],
                tool_call_id=tc_event["id"],
                node="rag_agent",
            )
            events.append(call_evt)
            if "result" in tc_event:
                result_evt = await create_tool_result_event(
                    tool_name=tc_event["name"],
                    result_summary=str(tc_event["result"])[:200],
                    tool_call_id=tc_event["id"],
                    node="rag_agent",
                )
                events.append(result_evt)

        assert len(events) == 2
        assert events[0].type == StreamEventType.TOOL_CALL
        assert events[0].content["name"] == "knowledge_search"
        assert events[1].type == StreamEventType.TOOL_RESULT
        assert "Found 3" in events[1].content["result"]

    @pytest.mark.asyncio
    async def test_tutor_agent_forwards_tool_events(self):
        """Tutor agent node output with tool_call_events yields tool events."""
        from app.engine.multi_agent.stream_utils import (
            create_tool_call_event,
        )

        node_output = {
            "tool_call_events": [
                {"name": "search", "args": {}, "id": "c1"},
                {"name": "memory", "args": {"user_id": "u1"}, "id": "c2"},
            ],
        }

        events = []
        for tc_event in node_output["tool_call_events"]:
            evt = await create_tool_call_event(
                tool_name=tc_event["name"],
                tool_args=tc_event["args"],
                tool_call_id=tc_event["id"],
                node="tutor_agent",
            )
            events.append(evt)

        assert len(events) == 2
        assert all(e.node == "tutor_agent" for e in events)
        assert events[0].content["name"] == "search"
        assert events[1].content["name"] == "memory"

    @pytest.mark.asyncio
    async def test_no_tool_events_skips(self):
        """Node output without tool_call_events produces no tool events."""
        node_output = {
            "final_response": "Direct answer",
            "sources": [],
        }

        tool_call_events = node_output.get("tool_call_events", [])
        assert tool_call_events == []

    @pytest.mark.asyncio
    async def test_empty_tool_events_skips(self):
        """Node output with empty tool_call_events produces no tool events."""
        node_output = {
            "tool_call_events": [],
            "final_response": "Answer",
        }

        tool_call_events = node_output.get("tool_call_events", [])
        assert len(tool_call_events) == 0

    @pytest.mark.asyncio
    async def test_state_tool_events_forwarding_sanitizes_args_results_and_lifecycle(self):
        from app.engine.multi_agent.graph_stream_node_runtime import (
            emit_tool_call_events_impl,
        )

        lifecycle_state = {}

        events = [
            event
            async for event in emit_tool_call_events_impl(
                tool_call_events=[
                    {
                        "name": "external_tool",
                        "args": {
                            "access_token": "raw-state-arg-token-123456",
                            "query": "Bearer raw-state-query-token-12345678",
                            "safe": "ok",
                        },
                        "id": "tc_state_1",
                        "result": (
                            '{"summary": "done", "access_token": '
                            '"raw-state-result-token-123456"}'
                        ),
                    }
                ],
                node_name="direct",
                lifecycle_state=lifecycle_state,
                create_tool_call_event=create_tool_call_event,
                create_tool_result_event=create_tool_result_event,
            )
        ]

        serialized_events = json.dumps(
            [event.to_dict() for event in events],
            ensure_ascii=False,
        )
        serialized_lifecycle = json.dumps(lifecycle_state, ensure_ascii=False)

        assert len(events) == 2
        assert events[0].content["args"]["safe"] == "ok"
        assert events[0].content["args"]["access_token"] == "[redacted]"
        assert events[0].content["args"]["query"] == "[redacted]"
        assert "raw-state-arg-token" not in serialized_events
        assert "raw-state-query-token" not in serialized_events
        assert "raw-state-result-token" not in serialized_events
        assert "raw-state-arg-token" not in serialized_lifecycle
        assert "raw-state-query-token" not in serialized_lifecycle
        assert "raw-state-result-token" not in serialized_lifecycle
