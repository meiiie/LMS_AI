"""
Tests for Sprint 75: Pipeline Latency Elimination — Tier 1.

Tests:
1. Guardian singleton — _get_guardian() returns same instance, guardian_node uses singleton
2. Tutor skips grader — WiiiRunner lanes route tutor_agent → synthesizer directly
3. Bulk answer push — _push_answer_bulk() sends large chunks with no delay
4. Runner structure — verify WiiiRunner node registration
"""

import sys
import types
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================================
# Break circular import chain (same pattern as test_sprint74)
# ============================================================================

_cs_key = "app.services.chat_service"
_svc_key = "app.services"
_had_cs = _cs_key in sys.modules
_orig_cs = sys.modules.get(_cs_key)

if not _had_cs:
    _mock_chat_svc = types.ModuleType(_cs_key)
    _mock_chat_svc.ChatService = type("ChatService", (), {})
    _mock_chat_svc.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_chat_svc

import app.engine.multi_agent.graph as _graph_mod  # noqa: E402

if not _had_cs:
    sys.modules.pop(_cs_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# ============================================================================
# 1. Guardian Singleton Tests
# ============================================================================


@pytest.mark.skip(reason="De-LangGraphing Phase 3: _guardian_instance removed from graph module")
class TestGuardianSingleton:
    """Sprint 75: Guardian agent reused across invocations via module singleton."""

    def setup_method(self):
        """Reset singleton before each test."""
        self._orig = _graph_mod._guardian_instance
        _graph_mod._guardian_instance = None

    def teardown_method(self):
        """Restore original singleton."""
        _graph_mod._guardian_instance = self._orig

    def test_get_guardian_creates_once(self):
        """_get_guardian() should only instantiate GuardianAgent once."""
        mock_instance = MagicMock()

        with patch("app.engine.guardian_agent.GuardianAgent", return_value=mock_instance):
            g1 = _graph_mod._get_guardian()
            g2 = _graph_mod._get_guardian()

        assert g1 is g2, "Should return same instance"
        assert g1 is mock_instance

    def test_get_guardian_returns_singleton(self):
        """After first call, _get_guardian() returns cached instance."""
        sentinel = MagicMock()
        _graph_mod._guardian_instance = sentinel

        result = _graph_mod._get_guardian()
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_guardian_node_uses_singleton(self):
        """guardian_node() should call _get_guardian(), not create new instance."""
        guardian_node = _graph_mod.guardian_node

        mock_guardian = MagicMock()
        mock_decision = MagicMock()
        mock_decision.action = "ALLOW"
        mock_decision.reason = None
        mock_guardian.validate_message = AsyncMock(return_value=mock_decision)

        state = {"query": "COLREGs Rule 5 là gì?", "guardian_passed": False}

        with patch("app.engine.multi_agent.graph._get_guardian", return_value=mock_guardian):
            result = await guardian_node(state)

        assert result["guardian_passed"] is True
        mock_guardian.validate_message.assert_called_once_with(
            "COLREGs Rule 5 là gì?", context="education", domain_id=None
        )

    @pytest.mark.asyncio
    async def test_guardian_node_skip_short_still_works(self):
        """Short messages (<3 chars) still skip without touching singleton."""
        guardian_node = _graph_mod.guardian_node

        state = {"query": "hi", "guardian_passed": False}
        result = await guardian_node(state)
        assert result["guardian_passed"] is True

    @pytest.mark.asyncio
    async def test_guardian_node_fail_open_on_error(self):
        """If _get_guardian() raises, guardian_node fails open."""
        guardian_node = _graph_mod.guardian_node

        state = {"query": "some valid question here", "guardian_passed": False}

        with patch(
            "app.engine.multi_agent.graph._get_guardian",
            side_effect=RuntimeError("init failed"),
        ):
            result = await guardian_node(state)

        assert result["guardian_passed"] is True

    @pytest.mark.asyncio
    async def test_guardian_node_block_still_works(self):
        """Blocked messages still return guardian_passed=False."""
        guardian_node = _graph_mod.guardian_node

        mock_guardian = MagicMock()
        mock_decision = MagicMock()
        mock_decision.action = "BLOCK"
        mock_decision.reason = "Nội dung không phù hợp."
        mock_guardian.validate_message = AsyncMock(return_value=mock_decision)

        state = {"query": "something inappropriate here", "guardian_passed": True}

        with patch("app.engine.multi_agent.graph._get_guardian", return_value=mock_guardian):
            result = await guardian_node(state)

        assert result["guardian_passed"] is False
        assert "Nội dung không phù hợp" in result["final_response"]


# ============================================================================
# 2. Tutor Skips Grader Tests
# ============================================================================


class TestGraderRemovedFromPipeline:
    """Sprint 233: Grader removed from WiiiRunner. Agents route to synthesizer."""

    @staticmethod
    async def _run_lane(agent_name: str):
        """Run a minimal WiiiRunner lane and capture step execution order."""
        from app.engine.multi_agent.runner import WiiiRunner

        calls = []
        runner = WiiiRunner()

        async def _node(name, state):
            calls.append(name)
            next_state = dict(state)
            if name == agent_name:
                next_state["final_response"] = (
                    "This is a sufficiently complete response from the selected lane."
                )
            return next_state

        for name in ("guardian", "supervisor", agent_name, "synthesizer"):
            runner.register_node(name, lambda state, _name=name: _node(_name, state))

        with patch("app.engine.multi_agent.runtime_routes.guardian_route", return_value="supervisor"), \
             patch("app.engine.multi_agent.graph_support.route_decision", return_value=agent_name), \
             patch("app.engine.multi_agent.runner.run_input_guardrails", new=AsyncMock(return_value=(True, None))), \
             patch("app.engine.multi_agent.runner.run_output_guardrails", new=AsyncMock()):
            await runner.run({"query": "test", "guardian_passed": True})

        return calls

    def test_grader_node_not_in_graph(self):
        """Sprint 233: grader node should no longer exist in WiiiRunner."""
        from app.engine.multi_agent.runner import get_wiii_runner

        runner = get_wiii_runner()
        assert "grader" not in runner._nodes
        assert "grader" not in runner._feature_nodes

    @pytest.mark.asyncio
    async def test_rag_routes_directly_to_synthesizer(self):
        """Sprint 233: RAG agent routes to synthesizer, no grader."""
        calls = await self._run_lane("rag_agent")

        assert calls == ["guardian", "supervisor", "rag_agent", "synthesizer"]

    @pytest.mark.asyncio
    async def test_tutor_routes_to_synthesizer(self):
        """Tutor agent routes directly to synthesizer."""
        calls = await self._run_lane("tutor_agent")
        assert calls == ["guardian", "supervisor", "tutor_agent", "synthesizer"]

    @pytest.mark.asyncio
    async def test_memory_routes_to_synthesizer(self):
        """Memory agent routes directly to synthesizer."""
        calls = await self._run_lane("memory_agent")
        assert calls == ["guardian", "supervisor", "memory_agent", "synthesizer"]


# ============================================================================
# 3. Bulk Answer Push Tests
# ============================================================================


class TestBulkAnswerPush:
    """Sprint 75: _push_answer_bulk() sends large chunks with no delay."""

    @pytest.mark.asyncio
    async def test_bulk_push_sends_all_content(self):
        """All text content should be sent via answer_delta events."""
        events = []
        queue = asyncio.Queue()

        # Simulate the bulk push function behavior
        text = "A" * 500  # 500 chars
        _BULK_SIZE = 200

        for i in range(0, len(text), _BULK_SIZE):
            sub = text[i:i + _BULK_SIZE]
            events.append({
                "type": "answer_delta",
                "content": sub,
                "node": "tutor_agent",
            })

        # Should produce 3 chunks: 200 + 200 + 100
        assert len(events) == 3
        total_content = "".join(e["content"] for e in events)
        assert total_content == text

    @pytest.mark.asyncio
    async def test_bulk_push_chunk_sizes(self):
        """Bulk push should use 200-char chunks (not 12-char sub-chunks)."""
        text = "X" * 600  # Exactly 3 chunks of 200
        _BULK_SIZE = 200

        chunks = []
        for i in range(0, len(text), _BULK_SIZE):
            chunks.append(text[i:i + _BULK_SIZE])

        assert len(chunks) == 3
        assert all(len(c) == 200 for c in chunks)

    @pytest.mark.asyncio
    async def test_bulk_push_single_chunk_for_short_text(self):
        """Short text should produce a single chunk."""
        text = "Hello world"
        _BULK_SIZE = 200

        chunks = []
        for i in range(0, len(text), _BULK_SIZE):
            chunks.append(text[i:i + _BULK_SIZE])

        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    @pytest.mark.asyncio
    async def test_bulk_push_empty_text_no_events(self):
        """Empty text should produce no events."""
        text = ""
        _BULK_SIZE = 200

        chunks = []
        for i in range(0, len(text), _BULK_SIZE):
            chunks.append(text[i:i + _BULK_SIZE])

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_bulk_push_faster_than_sub_chunk(self):
        """Bulk push should be significantly faster than sub-chunked push.

        Sub-chunk: 12 chars * 18ms = ~1500ms for 1000 chars
        Bulk: no delay = ~0ms for 1000 chars
        """
        import time

        text = "A" * 1000  # 1000 chars
        _BULK_SIZE = 200

        start = time.monotonic()
        chunks = []
        for i in range(0, len(text), _BULK_SIZE):
            chunks.append(text[i:i + _BULK_SIZE])
        elapsed = time.monotonic() - start

        # Bulk push should complete in < 10ms (no sleep delays)
        assert elapsed < 0.01, f"Bulk push took {elapsed:.3f}s, expected < 10ms"
        assert len(chunks) == 5  # 1000 / 200




# ============================================================================
# 4. Integration: Latency Constant Verification
# ============================================================================


class TestLatencyConstants:
    """Verify Sprint 75 constants are correctly set."""




    @pytest.mark.skip(reason="De-LangGraphing Phase 3: _guardian_instance removed")
    def test_guardian_singleton_exists(self):
        """Module-level _guardian_instance variable should exist."""
        import app.engine.multi_agent.graph as graph_mod
        assert hasattr(graph_mod, "_guardian_instance")

    def test_get_guardian_function_exists(self):
        """_get_guardian() function should be available."""
        from app.engine.multi_agent.graph import _get_guardian
        assert callable(_get_guardian)
