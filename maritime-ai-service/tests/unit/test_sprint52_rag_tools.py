"""
Tests for Sprint 52: RAG Tools coverage.

Tests RAG tools including ContextVar state management:
- RAGToolState dataclass
- _get_state, init_rag_tools, get_last_retrieved_sources,
  get_last_native_thinking, get_last_reasoning_trace,
  get_last_confidence, clear_retrieved_sources
- tool_knowledge_search (success, no agent, error)
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ============================================================================
# Helpers
# ============================================================================


def _reset_module_state():
    """Reset module-level state for clean tests."""
    import app.engine.tools.rag_tools as mod
    mod._rag_agent = None
    mod._rag_tool_state.set(None)


# ============================================================================
# RAGToolState and state management
# ============================================================================


class TestRAGToolState:
    """Test state dataclass and accessors."""

    def setup_method(self):
        _reset_module_state()

    def test_defaults(self):
        from app.engine.tools.rag_tools import RAGToolState
        state = RAGToolState()
        assert state.sources == []
        assert state.native_thinking is None
        assert state.reasoning_trace is None
        assert state.confidence == 0.0
        assert state.is_complete is False
        assert state.identity_key is None

    def test_get_state_creates_new(self):
        from app.engine.tools.rag_tools import _get_state
        state = _get_state()
        assert state.confidence == 0.0

    def test_get_state_returns_same(self):
        from app.engine.tools.rag_tools import _get_state
        s1 = _get_state()
        s2 = _get_state()
        assert s1 is s2

    def test_same_runtime_identity_preserves_state(self):
        from app.engine.tools.rag_tools import _get_state, get_last_retrieved_sources
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        ctx = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-a",
            session_id="session-a",
        )

        with tool_runtime_scope(ctx):
            state = _get_state()
            state.sources = [{"title": "SOLAS"}]

            assert _get_state() is state
            assert get_last_retrieved_sources() == [{"title": "SOLAS"}]

    def test_runtime_context_identity_isolates_rag_state(self):
        from app.engine.tools.rag_tools import (
            _get_state,
            get_last_confidence,
            get_last_native_thinking,
            get_last_reasoning_trace,
            get_last_retrieved_sources,
        )
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        ctx_a = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-a",
            session_id="session-a",
        )
        ctx_b = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-b",
            session_id="session-a",
        )
        trace = MagicMock()

        with tool_runtime_scope(ctx_a):
            state = _get_state()
            state.sources = [{"title": "Private Org A Source"}]
            state.native_thinking = "Org A reasoning"
            state.reasoning_trace = trace
            state.confidence = 0.92
            state.is_complete = True

            assert get_last_retrieved_sources() == [{"title": "Private Org A Source"}]
            assert get_last_native_thinking() == "Org A reasoning"
            assert get_last_reasoning_trace() is trace
            assert get_last_confidence() == (0.92, True)

        with tool_runtime_scope(ctx_b):
            assert get_last_retrieved_sources() == []
            assert get_last_native_thinking() is None
            assert get_last_reasoning_trace() is None
            assert get_last_confidence() == (0.0, False)

        with tool_runtime_scope(ctx_a):
            assert get_last_retrieved_sources() == []
            assert get_last_native_thinking() is None


class TestInitRagTools:
    """Test init_rag_tools."""

    def setup_method(self):
        _reset_module_state()

    def test_sets_agent(self):
        import app.engine.tools.rag_tools as mod
        mock_agent = MagicMock()
        mod.init_rag_tools(mock_agent)
        assert mod._rag_agent is mock_agent


class TestGetLastRetrievedSources:
    """Test source retrieval."""

    def setup_method(self):
        _reset_module_state()

    def test_empty_by_default(self):
        from app.engine.tools.rag_tools import get_last_retrieved_sources
        assert get_last_retrieved_sources() == []

    def test_returns_stored_sources(self):
        from app.engine.tools.rag_tools import get_last_retrieved_sources, _get_state
        state = _get_state()
        state.sources = [{"title": "SOLAS Ch. III"}]
        assert len(get_last_retrieved_sources()) == 1


class TestGetLastNativeThinking:
    """Test native thinking retrieval."""

    def setup_method(self):
        _reset_module_state()

    def test_none_by_default(self):
        from app.engine.tools.rag_tools import get_last_native_thinking
        assert get_last_native_thinking() is None

    def test_returns_thinking(self):
        from app.engine.tools.rag_tools import get_last_native_thinking, _get_state
        _get_state().native_thinking = "Analyzing SOLAS requirements..."
        assert get_last_native_thinking() == "Analyzing SOLAS requirements..."


class TestGetLastReasoningTrace:
    """Test reasoning trace retrieval."""

    def setup_method(self):
        _reset_module_state()

    def test_none_by_default(self):
        from app.engine.tools.rag_tools import get_last_reasoning_trace
        assert get_last_reasoning_trace() is None

    def test_returns_trace(self):
        from app.engine.tools.rag_tools import get_last_reasoning_trace, _get_state
        mock_trace = MagicMock()
        _get_state().reasoning_trace = mock_trace
        assert get_last_reasoning_trace() is mock_trace


class TestGetLastConfidence:
    """Test confidence retrieval."""

    def setup_method(self):
        _reset_module_state()

    def test_defaults(self):
        from app.engine.tools.rag_tools import get_last_confidence
        conf, complete = get_last_confidence()
        assert conf == 0.0
        assert complete is False

    def test_returns_stored(self):
        from app.engine.tools.rag_tools import get_last_confidence, _get_state
        state = _get_state()
        state.confidence = 0.95
        state.is_complete = True
        conf, complete = get_last_confidence()
        assert conf == 0.95
        assert complete is True


class TestClearRetrievedSources:
    """Test state reset."""

    def setup_method(self):
        _reset_module_state()

    def test_resets_all(self):
        from app.engine.tools.rag_tools import clear_retrieved_sources, _get_state
        state = _get_state()
        state.sources = [{"title": "Test"}]
        state.confidence = 0.9
        state.native_thinking = "Thinking..."
        clear_retrieved_sources()
        new_state = _get_state()
        assert new_state.sources == []
        assert new_state.confidence == 0.0


# ============================================================================
# tool_knowledge_search
# ============================================================================


class TestToolKnowledgeSearch:
    """Test knowledge search tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_no_agent(self):
        import app.engine.tools.rag_tools as mod
        mod._rag_agent = None
        result = await mod.tool_knowledge_search.coroutine(query="What is SOLAS?")
        assert "Xin lỗi" in result

    @pytest.mark.asyncio
    async def test_success(self):
        import app.engine.tools.rag_tools as mod
        mock_agent = MagicMock()
        mod._rag_agent = mock_agent
        mod._rag_tool_state.set(None)

        mock_crag_result = MagicMock()
        mock_crag_result.answer = "SOLAS is the Safety of Life at Sea convention."
        mock_crag_result.confidence = 85
        mock_crag_result.sources = [
            {"node_id": "n1", "title": "SOLAS Ch III", "content": "Text...", "page_number": 5}
        ]
        mock_crag_result.reasoning_trace = MagicMock(total_steps=5)
        mock_crag_result.thinking = "Analyzing SOLAS requirements"

        with patch("app.engine.agentic_rag.corrective_rag.get_corrective_rag") as mock_get_crag, \
             patch("app.core.config.settings") as mock_settings:
            mock_crag = MagicMock()
            mock_crag.process = AsyncMock(return_value=mock_crag_result)
            mock_get_crag.return_value = mock_crag
            mock_settings.rag_confidence_high = 0.85

            result = await mod.tool_knowledge_search.coroutine(query="What is SOLAS?")

        assert "SOLAS is the Safety of Life at Sea" in result
        state = mod._get_state()
        assert state.confidence == 0.85
        assert len(state.sources) == 1

    @pytest.mark.asyncio
    async def test_success_no_sources(self):
        import app.engine.tools.rag_tools as mod
        mock_agent = MagicMock()
        mod._rag_agent = mock_agent
        mod._rag_tool_state.set(None)

        mock_crag_result = MagicMock()
        mock_crag_result.answer = "I don't have information about that."
        mock_crag_result.confidence = 30
        mock_crag_result.sources = []
        mock_crag_result.reasoning_trace = None
        mock_crag_result.thinking = None

        with patch("app.engine.agentic_rag.corrective_rag.get_corrective_rag") as mock_get_crag, \
             patch("app.core.config.settings") as mock_settings:
            mock_crag = MagicMock()
            mock_crag.process = AsyncMock(return_value=mock_crag_result)
            mock_get_crag.return_value = mock_crag
            mock_settings.rag_confidence_high = 0.85

            result = await mod.tool_knowledge_search.coroutine(query="Random question")

        state = mod._get_state()
        assert state.sources == []
        assert state.confidence == 0.30

    @pytest.mark.asyncio
    async def test_success_no_sources_sanitizes_domain_fallback(self):
        import app.engine.tools.rag_tools as mod
        mock_agent = MagicMock()
        mod._rag_agent = mock_agent
        mod._rag_tool_state.set(None)

        mock_crag_result = MagicMock()
        mock_crag_result.answer = "Xin lỗi, mình chưa có thông tin về chủ đề này nha~ ≽^•⩊•^≼"
        mock_crag_result.confidence = 30
        mock_crag_result.sources = []
        mock_crag_result.reasoning_trace = None
        mock_crag_result.thinking = None

        with patch("app.engine.agentic_rag.corrective_rag.get_corrective_rag") as mock_get_crag, \
             patch("app.core.config.settings") as mock_settings:
            mock_crag = MagicMock()
            mock_crag.process = AsyncMock(return_value=mock_crag_result)
            mock_get_crag.return_value = mock_crag
            mock_settings.rag_confidence_high = 0.85

            result = await mod.tool_knowledge_search.coroutine(query="Random question")

        assert "chưa thấy nguồn nội bộ thật sự khớp" in result.lower()
        assert "xin lỗi" not in result.lower()

    @pytest.mark.asyncio
    async def test_confidence_above_1_normalized(self):
        """CRAG confidence (0-100) is always normalized to 0-1 for config thresholds."""
        import app.engine.tools.rag_tools as mod
        mock_agent = MagicMock()
        mod._rag_agent = mock_agent
        mod._rag_tool_state.set(None)

        mock_crag_result = MagicMock()
        mock_crag_result.answer = "Answer"
        mock_crag_result.confidence = 95  # 0-100 scale
        mock_crag_result.sources = []
        mock_crag_result.reasoning_trace = None
        mock_crag_result.thinking = None

        with patch("app.engine.agentic_rag.corrective_rag.get_corrective_rag") as mock_get_crag, \
             patch("app.core.config.settings") as mock_settings:
            mock_crag = MagicMock()
            mock_crag.process = AsyncMock(return_value=mock_crag_result)
            mock_get_crag.return_value = mock_crag
            mock_settings.rag_confidence_high = 0.85

            await mod.tool_knowledge_search.coroutine(query="Q")

        assert mod._get_state().confidence == 0.95

    @pytest.mark.asyncio
    async def test_error_resets_state(self):
        import app.engine.tools.rag_tools as mod
        mock_agent = MagicMock()
        mod._rag_agent = mock_agent
        mod._rag_tool_state.set(None)

        with patch("app.engine.agentic_rag.corrective_rag.get_corrective_rag", side_effect=Exception("CRAG error")):
            result = await mod.tool_knowledge_search.coroutine(query="Q")

        assert "Lỗi khi tra cứu" in result
        # State should be reset
        state = mod._get_state()
        assert state.confidence == 0.0


# ============================================================================
# Backward compatibility
# ============================================================================


class TestBackwardCompatibility:
    """Test backward-compatible alias."""

    def test_alias_exists(self):
        from app.engine.tools.rag_tools import tool_maritime_search, tool_knowledge_search
        assert tool_maritime_search is tool_knowledge_search
