"""
Sprint 163 Phase 3: RAG + Tutor Subgraphs + Tool Cache + Metrics — Unit Tests.

Tests cover:
- RequestScopedToolCache: get/set, hit rate, eviction, invalidation
- SubagentMetrics: record, summary, percentiles, thread safety
- RAG subgraph: state, nodes, correction loop, compilation
- Tutor subgraph: state, phases, conditional refinement, compilation
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =========================================================================
# RequestScopedToolCache
# =========================================================================


class TestRequestScopedToolCache:
    """Tool cache for avoiding duplicate calls within a request."""

    def test_miss_returns_none(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        assert cache.get("tool_search_shopee", {"query": "laptop"}) is None

    def test_set_then_get(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool_search_shopee", {"query": "laptop"}, {"results": [1, 2, 3]})
        result = cache.get("tool_search_shopee", {"query": "laptop"})
        assert result == {"results": [1, 2, 3]}

    def test_different_args_different_keys(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool_search_shopee", {"query": "laptop"}, "result_a")
        cache.set("tool_search_shopee", {"query": "phone"}, "result_b")

        assert cache.get("tool_search_shopee", {"query": "laptop"}) == "result_a"
        assert cache.get("tool_search_shopee", {"query": "phone"}) == "result_b"

    def test_different_tools_different_keys(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool_search_shopee", {"query": "x"}, "shopee_result")
        cache.set("tool_search_lazada", {"query": "x"}, "lazada_result")

        assert cache.get("tool_search_shopee", {"query": "x"}) == "shopee_result"
        assert cache.get("tool_search_lazada", {"query": "x"}) == "lazada_result"

    def test_hit_rate(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool", {"q": "a"}, "result")

        cache.get("tool", {"q": "a"})  # hit
        cache.get("tool", {"q": "a"})  # hit
        cache.get("tool", {"q": "b"})  # miss

        assert cache.hit_rate == pytest.approx(2 / 3, rel=0.01)

    def test_size(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        assert cache.size == 0
        cache.set("tool", {"q": "a"}, "r1")
        assert cache.size == 1
        cache.set("tool", {"q": "b"}, "r2")
        assert cache.size == 2

    def test_clear(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool", {"q": "a"}, "r1")
        cache.clear()
        assert cache.size == 0
        assert cache.get("tool", {"q": "a"}) is None

    def test_invalidate(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool", {"q": "a"}, "r1")
        assert cache.invalidate("tool", {"q": "a"}) is True
        assert cache.get("tool", {"q": "a"}) is None
        assert cache.invalidate("tool", {"q": "a"}) is False

    def test_eviction_at_max_entries(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache(max_entries=3)
        cache.set("t", {"n": "1"}, "r1")
        cache.set("t", {"n": "2"}, "r2")
        cache.set("t", {"n": "3"}, "r3")
        cache.set("t", {"n": "4"}, "r4")  # Should evict oldest

        assert cache.size == 3
        # Oldest entry (n=1) should be evicted
        assert cache.get("t", {"n": "4"}) == "r4"

    def test_stats(self):
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("t", {"q": "a"}, "r")
        cache.get("t", {"q": "a"})
        cache.get("t", {"q": "b"})

        stats = cache.stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_args_order_insensitive(self):
        """Args with same keys but different order should produce same cache key."""
        from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache

        cache = RequestScopedToolCache()
        cache.set("tool", {"a": 1, "b": 2}, "result")
        # json.dumps with sort_keys=True makes this order-insensitive
        assert cache.get("tool", {"b": 2, "a": 1}) == "result"


# =========================================================================
# SubagentMetrics
# =========================================================================


class TestSubagentMetrics:
    """Per-subagent metrics collection."""

    def setup_method(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        SubagentMetrics.reset()

    def test_singleton(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        a = SubagentMetrics.get_instance()
        b = SubagentMetrics.get_instance()
        assert a is b

    def test_reset(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        a = SubagentMetrics.get_instance()
        SubagentMetrics.reset()
        b = SubagentMetrics.get_instance()
        assert a is not b

    def test_record_and_summary(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        m.record("search", duration_ms=100, status="success", confidence=0.9)
        m.record("search", duration_ms=200, status="success", confidence=0.8)

        s = m.summary("search")
        assert s["invocations"] == 2
        assert s["avg_duration_ms"] == 150
        assert s["success_rate"] == 1.0
        assert s["avg_confidence"] == pytest.approx(0.85, rel=0.01)

    def test_error_rate(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        m.record("rag", duration_ms=50, status="success")
        m.record("rag", duration_ms=30, status="error")
        m.record("rag", duration_ms=40, status="timeout")

        s = m.summary("rag")
        assert s["error_rate"] == pytest.approx(2 / 3, rel=0.01)
        assert s["timeout_rate"] == pytest.approx(1 / 3, rel=0.01)

    def test_summary_missing_returns_none(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        assert m.summary("nonexistent") is None

    def test_all_summaries(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        m.record("a", duration_ms=10)
        m.record("b", duration_ms=20)

        summaries = m.all_summaries()
        assert len(summaries) == 2
        names = [s["name"] for s in summaries]
        assert "a" in names
        assert "b" in names

    def test_list_names(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        m.record("search", duration_ms=10)
        m.record("rag", duration_ms=20)

        assert m.list_names() == ["rag", "search"]

    def test_count(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        assert m.count == 0
        m.record("x", duration_ms=10)
        assert m.count == 1

    def test_percentiles(self):
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics

        m = SubagentMetrics.get_instance()
        for i in range(100):
            m.record("test", duration_ms=i * 10)

        s = m.summary("test")
        assert s["p50_duration_ms"] == 500  # median
        assert s["p95_duration_ms"] >= 900  # 95th percentile


# =========================================================================
# RAG Subgraph
# =========================================================================


class TestRAGSubgraphState:
    """RAG subgraph state schema."""

    def test_private_fields(self):
        from app.engine.multi_agent.subagents.rag.state import RAGSubgraphState
        import typing

        hints = typing.get_type_hints(RAGSubgraphState)
        assert "retrieval_docs" in hints
        assert "retrieval_scores" in hints
        assert "grading_results" in hints
        assert "correction_round" in hints

    def test_output_fields(self):
        from app.engine.multi_agent.subagents.rag.state import RAGSubgraphState
        import typing

        hints = typing.get_type_hints(RAGSubgraphState)
        assert "final_response" in hints
        assert "sources" in hints
        assert "crag_confidence" in hints


class TestRAGNodes:
    """RAG subgraph node tests."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_docs(self):
        from app.engine.multi_agent.subagents.rag.runtime import retrieve_node

        mock_search = AsyncMock()
        mock_search.search.return_value = [
            {"content": "Doc 1", "metadata": {}, "score": 0.9},
            {"content": "Doc 2", "metadata": {}, "score": 0.7},
        ]

        with patch(
            "app.services.hybrid_search_service.get_hybrid_search_service",
            return_value=mock_search,
        ):
            result = await retrieve_node({"query": "test", "domain_id": "maritime"})

        assert len(result["retrieval_docs"]) == 2
        assert len(result["retrieval_scores"]) == 2

    @pytest.mark.asyncio
    async def test_retrieve_handles_failure(self):
        from app.engine.multi_agent.subagents.rag.runtime import retrieve_node

        with patch(
            "app.services.hybrid_search_service.get_hybrid_search_service",
            side_effect=RuntimeError("DB down"),
        ):
            result = await retrieve_node({"query": "test", "domain_id": "maritime"})

        assert result["retrieval_docs"] == []

    @pytest.mark.asyncio
    async def test_grade_calculates_confidence(self):
        from app.engine.multi_agent.subagents.rag.runtime import grade_node

        result = await grade_node({
            "retrieval_docs": [{"content": "A"}, {"content": "B"}],
            "retrieval_scores": [0.9, 0.7],
            "query": "test",
        })

        assert result["retrieval_confidence"] == pytest.approx(0.8, rel=0.01)
        assert len(result["grading_results"]) == 2

    @pytest.mark.asyncio
    async def test_grade_empty_docs(self):
        from app.engine.multi_agent.subagents.rag.runtime import grade_node

        result = await grade_node({
            "retrieval_docs": [],
            "retrieval_scores": [],
            "query": "test",
        })

        assert result["retrieval_confidence"] == 0.0

    def test_should_correct_high_confidence(self):
        from app.engine.multi_agent.subagents.rag.runtime import should_correct

        assert should_correct({"retrieval_confidence": 0.9, "correction_round": 0}) == "generate"

    def test_should_correct_low_confidence(self):
        from app.engine.multi_agent.subagents.rag.runtime import should_correct

        assert should_correct({"retrieval_confidence": 0.3, "correction_round": 0}) == "correct"

    def test_should_correct_max_rounds(self):
        from app.engine.multi_agent.subagents.rag.runtime import should_correct

        assert should_correct({
            "retrieval_confidence": 0.3,
            "correction_round": 3,
            "max_correction_rounds": 3,
        }) == "generate"

    @pytest.mark.asyncio
    async def test_correct_increments_round(self):
        from app.engine.multi_agent.subagents.rag.runtime import correct_node

        result = await correct_node({"correction_round": 1})
        assert result["correction_round"] == 2

    @pytest.mark.asyncio
    async def test_generate_with_docs(self):
        from app.engine.multi_agent.subagents.rag.runtime import generate_node

        result = await generate_node({
            "retrieval_docs": [{"content": "Important fact"}],
            "query": "test",
            "retrieval_confidence": 0.9,
        })

        assert result["current_agent"] == "rag_agent"
        assert "final_response" in result
        assert result["crag_confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_generate_no_docs(self):
        """Sprint 165: Empty KB now uses LLM fallback instead of hardcoded error."""
        from app.engine.multi_agent.subagents.rag.runtime import generate_node

        result = await generate_node({
            "retrieval_docs": [],
            "query": "test",
            "retrieval_confidence": 0.0,
        })

        # Sprint 165: LLM fallback provides a real response (or falls back to static)
        assert result["final_response"]  # Non-empty response
        assert result["crag_confidence"] == 0.55  # Capped fallback confidence


class TestRAGSubgraphBuild:
    """RAG subgraph build is deprecated (De-LangGraphing Phase 3)."""

    def test_raises_runtime_error(self):
        from app.engine.multi_agent.subagents.rag.graph import build_rag_subgraph

        with pytest.raises(RuntimeError, match="deprecated"):
            build_rag_subgraph()


# =========================================================================
# Tutor Subgraph
# =========================================================================


class TestTutorSubgraphState:
    """Tutor subgraph state schema."""

    def test_private_fields(self):
        from app.engine.multi_agent.subagents.tutor.state import TutorSubgraphState
        import typing

        hints = typing.get_type_hints(TutorSubgraphState)
        assert "phase" in hints
        assert "pedagogical_approach" in hints
        assert "learner_level" in hints
        assert "concepts_identified" in hints

    def test_output_fields(self):
        from app.engine.multi_agent.subagents.tutor.state import TutorSubgraphState
        import typing

        hints = typing.get_type_hints(TutorSubgraphState)
        assert "final_response" in hints
        assert "_answer_streamed_via_bus" in hints


class TestTutorNodes:
    """Tutor subgraph node tests."""

    @pytest.mark.asyncio
    async def test_analyze_explain_approach(self):
        from app.engine.multi_agent.subagents.tutor.runtime import analyze_node

        result = await analyze_node({"query": "Giải thích quy tắc COLREG", "context": {}})
        assert result["pedagogical_approach"] == "explain"

    @pytest.mark.asyncio
    async def test_analyze_socratic_approach(self):
        from app.engine.multi_agent.subagents.tutor.runtime import analyze_node

        result = await analyze_node({"query": "Tại sao tàu phải nhường?", "context": {}})
        assert result["pedagogical_approach"] == "socratic"

    @pytest.mark.asyncio
    async def test_analyze_example_approach(self):
        from app.engine.multi_agent.subagents.tutor.runtime import analyze_node

        result = await analyze_node({"query": "Cho ví dụ về SOLAS", "context": {}})
        assert result["pedagogical_approach"] == "example"

    @pytest.mark.asyncio
    async def test_generate_produces_draft(self):
        from app.engine.multi_agent.subagents.tutor.runtime import generate_node

        result = await generate_node({
            "query": "Test query",
            "pedagogical_approach": "explain",
        })
        assert "explanation_draft" in result
        assert result["phase"] == "generation"

    def test_should_refine_short_query(self):
        from app.engine.multi_agent.subagents.tutor.runtime import should_refine

        assert should_refine({"query": "COLREG là gì?"}) == "output"

    def test_should_refine_long_query(self):
        from app.engine.multi_agent.subagents.tutor.runtime import should_refine

        long_query = "Giải thích chi tiết về quy tắc tránh va trên biển theo COLREG 72 trong trường hợp hai tàu đi ngược chiều nhau"
        assert should_refine({"query": long_query}) == "refine"

    @pytest.mark.asyncio
    async def test_refine_sets_output(self):
        from app.engine.multi_agent.subagents.tutor.runtime import refine_node

        result = await refine_node({
            "explanation_draft": "Draft text",
            "learner_level": "beginner",
        })
        assert result["current_agent"] == "tutor_agent"
        assert result["final_response"] == "Draft text"

    @pytest.mark.asyncio
    async def test_output_node(self):
        from app.engine.multi_agent.subagents.tutor.runtime import output_node

        result = await output_node({"explanation_draft": "Quick answer"})
        assert result["final_response"] == "Quick answer"
        assert result["current_agent"] == "tutor_agent"


class TestTutorSubgraphBuild:
    """Tutor subgraph build is deprecated (De-LangGraphing Phase 3)."""

    def test_raises_runtime_error(self):
        from app.engine.multi_agent.subagents.tutor.graph import build_tutor_subgraph

        with pytest.raises(RuntimeError, match="deprecated"):
            build_tutor_subgraph()


# =========================================================================
# Package exports
# =========================================================================


class TestPackageExports:
    """Verify __init__.py exports all new components."""

    def test_tool_cache_exported(self):
        from app.engine.multi_agent.subagents import RequestScopedToolCache

        cache = RequestScopedToolCache()
        assert cache.size == 0

    def test_metrics_exported(self):
        from app.engine.multi_agent.subagents import SubagentMetrics

        SubagentMetrics.reset()
        m = SubagentMetrics.get_instance()
        assert m.count == 0

    def test_rag_subgraph_not_in_exports(self):
        """build_rag_subgraph removed from __init__.py (De-LangGraphing Phase 3)."""
        import app.engine.multi_agent.subagents.rag as rag_pkg

        assert not hasattr(rag_pkg, "build_rag_subgraph")

    def test_tutor_subgraph_not_in_exports(self):
        """build_tutor_subgraph removed from __init__.py (De-LangGraphing Phase 3)."""
        import app.engine.multi_agent.subagents.tutor as tutor_pkg

        assert not hasattr(tutor_pkg, "build_tutor_subgraph")
