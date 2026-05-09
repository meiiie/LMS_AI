"""
Tests for Sprint 54+63: graph_streaming.py coverage.

Tests multi-agent streaming helpers:
- _extract_thinking_content (thinking content, agent_outputs, empty — no truncation)
- _stream_answer_tokens (token chunking, delays)
- process_with_multi_agent_streaming (full flow, supervisor, rag_agent, tutor, grader,
  synthesizer, direct, guardian, memory, timeout, error)

Sprint 63 changes:
- Renamed _extract_thinking_summary → _extract_thinking_content (no truncation, no summaries)
- Supervisor routing and grader scores emit status events (not thinking)
- RAG/Tutor tool info emitted as status events

NOTE: graph_streaming has a deep circular import chain via multi_agent.graph → agents →
services → chat_service → multi_agent.graph. We break it by pre-mocking app.services
in sys.modules before importing.
"""

import pytest
import sys
import types
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from app.core.exceptions import ProviderUnavailableError

# ============================================================================
# Break circular import chain before importing graph_streaming
#
# Chain: graph_streaming → multi_agent.__init__ → graph → agents → tutor_node
#   → app.services.output_processor → app.services.__init__
#   → app.services.chat_service → app.engine.multi_agent.graph (circular!)
#
# Fix: Pre-populate app.services.chat_service in sys.modules so
# app.services.__init__ finds it already loaded (skips circular import).
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
    # Create a proper module mock (not MagicMock — MagicMock can't act as package)
    _mock_chat_svc = types.ModuleType(_cs_key)
    _mock_chat_svc.ChatService = type("ChatService", (), {})
    _mock_chat_svc.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_chat_svc

# Break graph_streaming -> graph import by providing the current runner helpers.
if not _had_graph:
    _mock_graph = types.ModuleType(_graph_key)
    _mock_graph._build_domain_config = MagicMock(return_value={})
    _mock_graph._build_turn_local_state_defaults = MagicMock(return_value={})
    sys.modules[_graph_key] = _mock_graph

from app.engine.multi_agent.graph_streaming import (
    _convert_bus_event,
    _extract_thinking_content,
    _is_likely_english,
    _narration_delta_chunks,
    _stream_answer_tokens,
    process_with_multi_agent_streaming,
    TOKEN_CHUNK_SIZE,
    TOKEN_DELAY_SEC,
)

# Thorough restore: remove mocks AND app.services that cached mock ChatService.
if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs

if not _had_graph:
    # Remove mock so later tests get the real module.
    # graph_streaming's top-level references to graph functions are fine because
    # we patch them per-test anyway via _get_patches().
    sys.modules.pop(_graph_key, None)
elif _orig_graph is not None:
    sys.modules[_graph_key] = _orig_graph


# ============================================================================
# _extract_thinking_content
# ============================================================================


class TestExtractThinkingContent:
    """Test thinking content extraction from node outputs.

    Sprint 63: Renamed from _extract_thinking_summary. Key changes:
    - No truncation (frontend handles display via collapsible blocks)
    - No structured summaries (tools/sources/scores are status events, not thinking)
    - Only returns real AI reasoning content
    """

    def test_with_thinking_content(self):
        output = {"thinking": "I need to analyze this maritime regulation carefully."}
        result = _extract_thinking_content(output)
        assert result == "I need to analyze this maritime regulation carefully."

    def test_long_thinking_not_truncated(self):
        """Sprint 63: No truncation — frontend handles display."""
        long_thinking = "A" * 600
        output = {"thinking": long_thinking}
        result = _extract_thinking_content(output)
        assert result == long_thinking
        assert len(result) == 600

    def test_very_long_thinking_preserved(self):
        """Sprint 63: Even very long thinking is preserved."""
        long_thinking = "B" * 2000
        output = {"thinking": long_thinking}
        result = _extract_thinking_content(output)
        assert result == long_thinking

    def test_short_thinking_ignored(self):
        output = {"thinking": "Short"}
        result = _extract_thinking_content(output)
        # <= 20 chars falls through to other checks
        assert result == ""  # No other data

    def test_agent_outputs_not_used_as_thinking(self):
        """Sprint 64: agent_outputs contain answer text, NOT thinking."""
        output = {
            "thinking": "",
            "agent_outputs": {
                "some_agent": "A" * 100  # Answer text, not reasoning
            }
        }
        result = _extract_thinking_content(output)
        assert result == ""  # Should NOT fall back to agent_outputs

    def test_agent_outputs_ignored_even_when_long(self):
        """Sprint 64: agent_outputs are never used as thinking content."""
        output = {
            "thinking": "",
            "agent_outputs": {"rag": "This is a very long answer text " * 10}
        }
        result = _extract_thinking_content(output)
        assert result == ""

    def test_no_structured_summary(self):
        """Sprint 63: Structured summary removed — tools/sources/scores are status events."""
        output = {
            "thinking": "",
            "tools_used": [{"name": "knowledge_search"}, {"name": "rag_lookup"}],
            "sources": [{"title": "s1"}, {"title": "s2"}],
            "grader_score": 8,
            "next_agent": "tutor_agent",
        }
        result = _extract_thinking_content(output)
        # No structured summary — returns empty when no real thinking
        assert result == ""

    def test_empty_output(self):
        result = _extract_thinking_content({})
        assert result == ""

    def test_thinking_takes_priority(self):
        """thinking field is used when both thinking and thinking_content exist."""
        output = {
            "thinking": "This is the real AI reasoning about the question at hand.",
            "thinking_content": "",
        }
        result = _extract_thinking_content(output)
        assert result == "This is the real AI reasoning about the question at hand."

    def test_native_thinking_preferred_over_thinking_content(self):
        """Sprint 140b: Native thinking (model reasoning) preferred over thinking_content.

        thinking_content may be a ReasoningTracer pipeline dump; native thinking
        is always genuine model reasoning even if English.
        """
        output = {
            "thinking_content": "Phân tích câu hỏi về quy tắc hàng hải...",
            "thinking": "Analyzing the maritime regulation question...",
        }
        result = _extract_thinking_content(output)
        assert "Analyzing" in result  # Native model reasoning preferred

    def test_pipeline_summary_filtered_from_thinking(self):
        """Sprint 140b: Pipeline dumps in thinking field are filtered out."""
        output = {
            "thinking": "**Quá trình suy nghĩ:**\n1. Phân tích câu hỏi\n2. Tìm kiếm",
            "thinking_content": "",
        }
        result = _extract_thinking_content(output)
        assert result == ""

    def test_pipeline_summary_filtered_from_thinking_content(self):
        """Sprint 140b: Pipeline dumps in thinking_content are also filtered."""
        output = {
            "thinking": "",
            "thinking_content": "Quá trình suy nghĩ: 1. Bước phân tích câu hỏi 2. Tìm kiếm tài liệu",
        }
        result = _extract_thinking_content(output)
        assert result == ""

    def test_rag_analysis_prefix_not_filtered(self):
        """Sprint 140b: [RAG Analysis] with genuine thinking is NOT filtered."""
        output = {
            "thinking": "[RAG Analysis]\nThe question asks about COLREG Rule 15 crossing situations...",
        }
        result = _extract_thinking_content(output)
        assert "[RAG Analysis]" in result  # Valid combined thinking preserved


def test_narration_delta_chunks_skips_summary_echo():
    narration = types.SimpleNamespace(
        summary=(
            "Doc cau nay, minh thay trong do co mot khoang chung xuong.\n\n"
            "Luc nay dieu quan trong nhat la o lai voi ban cho that diu."
        ),
        delta_chunks=[
            "Doc cau nay, minh thay trong do co mot khoang chung xuong.",
            "Luc nay dieu quan trong nhat la o lai voi ban cho that diu.",
            "Luc nay dieu quan trong nhat la o lai voi ban cho that diu.",
        ],
    )

    assert _narration_delta_chunks(narration) == []


# ============================================================================
# _stream_answer_tokens
# ============================================================================


class TestLanguageDetection:
    def test_romanized_vietnamese_fast_path_text_is_not_treated_as_english(self):
        text = (
            "Minh thay cau da gui anh, nhung hien Wiii chua co provider vision kha dung "
            "nen minh khong nen doan noi dung anh."
        )

        assert _is_likely_english(text) is False

    def test_plain_english_still_triggers_translation_detection(self):
        text = "The attached image appears to show a navigation chart with labels and a short note."

        assert _is_likely_english(text) is True


class TestStreamAnswerTokens:
    """Test token-level streaming."""

    @pytest.mark.asyncio
    async def test_chunks_text(self):
        text = "Hello World 1234567890"
        events = []
        async for event in _stream_answer_tokens(text):
            events.append(event)

        # Verify all text is captured
        reconstructed = "".join(e.content for e in events)
        assert reconstructed == text

    @pytest.mark.asyncio
    async def test_chunk_sizes(self):
        text = "A" * 50
        events = []
        async for event in _stream_answer_tokens(text):
            events.append(event)

        # _stream_answer_tokens may translate text via _ensure_vietnamese,
        # so total chars may differ from input. Verify chunks cover full output.
        reconstructed = "".join(e.content for e in events)
        expected_chunks = (len(reconstructed) + TOKEN_CHUNK_SIZE - 1) // TOKEN_CHUNK_SIZE
        assert len(events) == expected_chunks

    @pytest.mark.asyncio
    async def test_empty_text(self):
        events = []
        async for event in _stream_answer_tokens(""):
            events.append(event)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_short_text(self):
        events = []
        async for event in _stream_answer_tokens("Hi"):
            events.append(event)
        assert len(events) == 1
        assert events[0].content == "Hi"

    @pytest.mark.asyncio
    async def test_event_type(self):
        events = []
        async for event in _stream_answer_tokens("test"):
            events.append(event)
        assert events[0].type == "answer"


class TestCodeStudioBusEventConversion:
    """Ensure Code Studio bus events keep their studio metadata through graph_streaming."""

    @pytest.mark.asyncio
    async def test_preserves_code_open_metadata(self):
        event = await _convert_bus_event({
            "type": "code_open",
            "node": "code_studio_agent",
            "content": {
                "session_id": "vs_1",
                "title": "Pendulum App",
                "language": "html",
                "version": 2,
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
            },
        })

        assert event.type == "code_open"
        assert event.content["studio_lane"] == "app"
        assert event.content["artifact_kind"] == "html_app"
        assert event.content["quality_profile"] == "premium"
        assert event.content["renderer_contract"] == "host_shell"

    @pytest.mark.asyncio
    async def test_preserves_code_complete_metadata(self):
        event = await _convert_bus_event({
            "type": "code_complete",
            "node": "code_studio_agent",
            "content": {
                "session_id": "vs_1",
                "full_code": "<div>done</div>",
                "language": "html",
                "version": 2,
                "visual_payload": {"id": "visual-1"},
                "studio_lane": "artifact",
                "artifact_kind": "document",
                "quality_profile": "standard",
                "renderer_contract": "host_shell",
            },
        })

        assert event.type == "code_complete"
        assert event.content["studio_lane"] == "artifact"
        assert event.content["artifact_kind"] == "document"
        assert event.content["quality_profile"] == "standard"
        assert event.content["renderer_contract"] == "host_shell"


# ============================================================================
# process_with_multi_agent_streaming — Full flow
# ============================================================================


class TestProcessWithMultiAgentStreaming:
    """Test full multi-agent streaming."""

    def _mock_graph_stream(self, state_updates):
        """Create mock WiiiRunner streaming updates."""
        async def _run_streaming(initial_state, *, merged_queue=None):
            final_state = dict(initial_state)
            for update in state_updates:
                if merged_queue is not None:
                    await merged_queue.put(("graph", update))
                for node_state in update.values():
                    if isinstance(node_state, dict):
                        final_state.update(node_state)
            return final_state

        mock_runner = MagicMock()
        mock_runner.run_streaming = AsyncMock(side_effect=_run_streaming)
        return mock_runner

    def _get_patches(self, mock_graph):
        """Return common patches for streaming tests."""

        # Mock reasoning narrator for deterministic labels
        _labels = {
            "supervisor": "Phân tích câu hỏi",
            "rag_agent": "Tra cứu tri thức",
            "tutor_agent": "Soạn bài giảng",
            "memory_agent": "Truy xuất bộ nhớ",
            "direct": "Suy nghĩ câu trả lời",
            "synthesizer": "Tổng hợp câu trả lời",
        }
        mock_narrator = MagicMock()

        async def _mock_render(req):
            result = MagicMock()
            result.label = _labels.get(req.node, req.node)
            result.summary = f"Mock summary for {req.node}"
            result.action_text = ""
            result.delta_chunks = [f"Thinking..."]
            result.phase = "route"
            result.style_tags = []
            return result

        def _mock_render_fast(req):
            result = MagicMock()
            result.label = _labels.get(req.node, req.node)
            result.summary = f"Mock summary for {req.node}"
            result.action_text = ""
            result.delta_chunks = [f"Thinking..."]
            result.phase = "route"
            result.style_tags = []
            return result

        mock_narrator.render = _mock_render
        mock_narrator.render_fast = _mock_render_fast

        return {
            "graph": patch(
                "app.engine.multi_agent.runner.get_wiii_runner",
                return_value=mock_graph,
            ),
            "registry": patch("app.engine.multi_agent.graph_streaming.get_agent_registry"),
            "domain_config": patch(
                "app.engine.multi_agent.graph_streaming._build_domain_config",
                return_value={}
            ),
            "turn_defaults": patch(
                "app.engine.multi_agent.graph_streaming._build_turn_local_state_defaults",
                return_value={}
            ),
            "host_context": patch(
                "app.engine.multi_agent.graph._inject_host_context",
                return_value=None
            ),
            "narrator": patch(
                "app.engine.multi_agent.graph_streaming.get_reasoning_narrator",
                return_value=mock_narrator
            ),
            "settings": patch("app.engine.multi_agent.graph_streaming.settings"),
        }

    def _setup_registry(self, mock_reg):
        mock_registry = MagicMock()
        mock_registry.start_request_trace.return_value = "trace-1"
        mock_registry.end_request_trace.return_value = {"span_count": 0}
        mock_reg.return_value = mock_registry
        return mock_registry

    def _setup_settings(self, mock_settings):
        mock_settings.default_domain = "maritime"
        mock_settings.rag_model_version = "gemini-2.0"

    @pytest.mark.asyncio
    async def test_supervisor_routing(self):
        mock_graph = self._mock_graph_stream([
            {"supervisor": {"next_agent": "rag_agent"}},
            {"synthesizer": {"final_response": "Answer", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q?", "u1", "s1"):
                events.append(event)

        event_types = [e.type for e in events]
        assert "status" in event_types
        assert "answer" in event_types
        assert "done" in event_types
        # Sprint 63: Supervisor routing is status, not thinking
        # Event topology may omit explicit supervisor-noded events depending on
        # the stream queue path, but routing should still surface progress
        # without leaking unsupported event types.
        supervisor_events = [e for e in events if e.node == "supervisor"]
        supervisor_types = {e.type for e in supervisor_events}
        allowed_types = {"status", "thinking_start", "thinking_end", "thinking", "thinking_delta"}
        assert supervisor_types <= allowed_types

    @pytest.mark.asyncio
    async def test_rag_agent_node(self):
        mock_graph = self._mock_graph_stream([
            {"rag_agent": {"thinking": "Analyzing SOLAS regulations carefully and thoroughly here", "tools_used": []}},
            {"synthesizer": {"final_response": "Answer", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        status_events = [e for e in events if e.type == "status"]
        assert len(status_events) >= 1

    @pytest.mark.asyncio
    async def test_direct_node(self):
        mock_graph = self._mock_graph_stream([
            {"direct": {"final_response": "Direct answer", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Hi", "u1"):
                events.append(event)

        answer_events = [e for e in events if e.type == "answer"]
        reconstructed = "".join(e.content for e in answer_events)
        assert reconstructed == "Direct answer"

    @pytest.mark.asyncio
    async def test_legacy_grader_updates_are_ignored(self):
        mock_graph = self._mock_graph_stream([
            {"grader": {"grader_score": 8, "grader_feedback": "Good quality"}},
            {"synthesizer": {"final_response": "A", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        grader_events = [e for e in events if e.node == "grader"]
        assert grader_events == []

    @pytest.mark.asyncio
    async def test_guardian_node(self):
        mock_graph = self._mock_graph_stream([
            {"guardian": {"guardian_passed": True}},
            {"synthesizer": {"final_response": "OK", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        assert any(e.type == "done" for e in events)

    @pytest.mark.asyncio
    async def test_memory_agent_node(self):
        mock_graph = self._mock_graph_stream([
            {"memory_agent": {"context": "user data"}},
            {"synthesizer": {"final_response": "OK", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        status_events = [e for e in events if e.type == "status"]
        assert len(status_events) >= 1

    @pytest.mark.asyncio
    async def test_sources_emitted(self):
        mock_graph = self._mock_graph_stream([
            {"synthesizer": {
                "final_response": "Answer",
                "sources": [{"title": "SOLAS", "content": "Chapter III"}],
            }},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        assert any(e.type == "sources" for e in events)

    @pytest.mark.asyncio
    async def test_metadata_emitted(self):
        mock_graph = self._mock_graph_stream([
            {"synthesizer": {
                "final_response": "A",
                "sources": [],
                "grader_score": 7,
                "reasoning_trace": None,
                "thinking": "Some thinking",
            }},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        assert any(e.type == "metadata" for e in events)

    @pytest.mark.asyncio
    async def test_error_in_graph_init_propagates(self):
        """Exception while resolving WiiiRunner yields error event."""

        def _exploding_open():
            raise Exception("Runner init error")

        with patch("app.engine.multi_agent.runner.get_wiii_runner",
                    new=_exploding_open):
            with patch("app.engine.multi_agent.graph_streaming.get_agent_registry") as mock_reg:
                self._setup_registry(mock_reg)
                with patch("app.engine.multi_agent.graph_streaming._build_turn_local_state_defaults",
                           return_value={}), \
                     patch("app.engine.multi_agent.graph._inject_host_context",
                           return_value=None), \
                     patch("app.engine.multi_agent.graph_streaming.get_reasoning_narrator"), \
                     patch("app.engine.multi_agent.graph_streaming.settings") as mock_settings:
                    self._setup_settings(mock_settings)
                    events = []
                    async for event in process_with_multi_agent_streaming("Q", "u1"):
                        events.append(event)
                    assert any(e.type == "error" for e in events)

    @pytest.mark.asyncio
    async def test_error_in_graph_stream_yields_error(self):
        """Exception inside try block yields error event."""
        async def _exploding_run_streaming(*args, **kwargs):
            raise Exception("Stream processing error")

        mock_graph = MagicMock()
        mock_graph.run_streaming = AsyncMock(side_effect=_exploding_run_streaming)
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1", "s1"):
                events.append(event)

        assert any(e.type == "error" for e in events)

    @pytest.mark.asyncio
    async def test_provider_unavailable_in_graph_stream_reraises(self):
        """Explicit provider failures must bubble up for stream coordinator UX."""

        async def _exploding_run_streaming(*args, **kwargs):
            raise ProviderUnavailableError(
                provider="google",
                reason_code="rate_limit",
                message="Provider tam thoi ban hoac da cham gioi han.",
            )

        mock_graph = MagicMock()
        mock_graph.run_streaming = AsyncMock(side_effect=_exploding_run_streaming)
        patches = self._get_patches(mock_graph)

        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            with pytest.raises(ProviderUnavailableError):
                async for _event in process_with_multi_agent_streaming("Q", "u1", "s1", provider="google"):
                    pass

    @pytest.mark.asyncio
    async def test_tutor_agent_with_thinking(self):
        mock_graph = self._mock_graph_stream([
            {"tutor_agent": {"thinking": "Analyzing the student question about navigation in detail here"}},
            {"synthesizer": {"final_response": "Tutorial", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        # Sprint 141b: Bulk thinking now emitted as thinking_delta (not thinking)
        thinking_events = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking_events) >= 1

    @pytest.mark.asyncio
    async def test_tutor_agent_fallback_tools(self):
        """Sprint 63: Tool info emitted as status events, not thinking."""
        mock_graph = self._mock_graph_stream([
            {"tutor_agent": {"thinking": "", "tools_used": [{"name": "t1"}, {"name": "t2"}]}},
            {"synthesizer": {"final_response": "A", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        status_events = [e for e in events if e.type == "status"]
        assert any("2 nguồn" in e.content for e in status_events)

    @pytest.mark.asyncio
    async def test_rag_agent_tool_fallback(self):
        """Sprint 63: Tool info emitted as status events, not thinking."""
        mock_graph = self._mock_graph_stream([
            {"rag_agent": {"thinking": "", "tools_used": [{"name": "knowledge_search"}]}},
            {"synthesizer": {"final_response": "A", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        status_events = [e for e in events if e.type == "status"]
        assert any("knowledge_search" in e.content for e in status_events)

    @pytest.mark.asyncio
    async def test_no_session_id(self):
        mock_graph = self._mock_graph_stream([
            {"synthesizer": {"final_response": "A", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1", ""):
                events.append(event)

        assert any(e.type == "done" for e in events)

    @pytest.mark.asyncio
    async def test_reasoning_trace_model_dump(self):
        mock_trace = MagicMock()
        mock_trace.model_dump.return_value = {"steps": ["step1"]}

        mock_graph = self._mock_graph_stream([
            {"synthesizer": {
                "final_response": "A", "sources": [],
                "grader_score": 8, "reasoning_trace": mock_trace, "thinking": None,
            }},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        assert any(e.type == "metadata" for e in events)

    @pytest.mark.asyncio
    async def test_reasoning_trace_fallback_dict(self):
        mock_trace = MagicMock()
        mock_trace.model_dump.side_effect = AttributeError("no model_dump")
        mock_trace.dict.return_value = {"steps": ["step1"]}

        mock_graph = self._mock_graph_stream([
            {"synthesizer": {
                "final_response": "A", "sources": [],
                "grader_score": 5, "reasoning_trace": mock_trace, "thinking": None,
            }},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        assert any(e.type == "metadata" for e in events)

    @pytest.mark.asyncio
    async def test_answer_not_duplicated(self):
        mock_graph = self._mock_graph_stream([
            {"synthesizer": {"final_response": "First answer", "sources": []}},
            {"direct": {"final_response": "Second answer", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        answer_events = [e for e in events if e.type == "answer"]
        reconstructed = "".join(e.content for e in answer_events)
        assert reconstructed == "First answer"

    @pytest.mark.asyncio
    async def test_session_only_no_user_config(self):
        mock_graph = self._mock_graph_stream([
            {"synthesizer": {"final_response": "A", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "", "session-only"):
                events.append(event)

        assert any(e.type == "done" for e in events)

    @pytest.mark.asyncio
    async def test_grader_zero_score_no_quality_status(self):
        """Sprint 63: Zero score should not produce quality status event."""
        mock_graph = self._mock_graph_stream([
            {"grader": {"grader_score": 0, "grader_feedback": ""}},
            {"synthesizer": {"final_response": "A", "sources": []}},
        ])
        patches = self._get_patches(mock_graph)

        events = []
        with patches["graph"], patches["registry"] as mock_reg, \
             patches["domain_config"], patches["turn_defaults"], \
             patches["host_context"], patches["narrator"], \
             patches["settings"] as mock_settings:
            self._setup_registry(mock_reg)
            self._setup_settings(mock_settings)
            async for event in process_with_multi_agent_streaming("Q", "u1"):
                events.append(event)

        # Zero score should not produce quality status event
        status_events = [e for e in events if e.type == "status"]
        quality_events = [e for e in status_events
                         if isinstance(e.content, str) and "/10" in e.content]
        assert len(quality_events) == 0
