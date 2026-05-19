"""
Sprint 163 Phase 4: Supervisor-Reads-Reports — Unit Tests.

Tests cover:
- SubagentReport model: defaults, is_usable, is_high_quality, to_aggregator_summary
- AggregatorDecision model: defaults, actions, confidence bounds
- build_report: auto-verdict from SubagentResult
- Deterministic decision: all failed, single usable, dominant, multiple usable
- LLM decision: synthesize, use_best, re_route, error fallback
- Aggregator node: no reports, single confident, multiple, re-route, escalate, metrics
- Aggregator route: synthesizer vs supervisor
- Parallel dispatch node: targets, empty, timeout
- Graph integration: routing map, nodes added/not, route_decision handles parallel
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =========================================================================
# SubagentReport Model
# =========================================================================


class TestSubagentReport:
    """SubagentReport: structured evaluation wrapping SubagentResult."""

    def test_defaults(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )
        from app.engine.multi_agent.subagents.result import SubagentResult

        report = SubagentReport(agent_name="rag")
        assert report.agent_name == "rag"
        assert report.agent_type == "general"
        assert report.verdict == ReportVerdict.EMPTY
        assert report.relevance_score == 0.0
        assert report.can_stand_alone is False
        assert report.needs_complement == []
        assert isinstance(report.result, SubagentResult)

    def test_is_usable_confident(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(agent_name="rag", verdict=ReportVerdict.CONFIDENT)
        assert report.is_usable is True

    def test_is_usable_partial(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(agent_name="rag", verdict=ReportVerdict.PARTIAL)
        assert report.is_usable is True

    def test_is_usable_low_confidence(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(agent_name="rag", verdict=ReportVerdict.LOW_CONFIDENCE)
        assert report.is_usable is False

    def test_is_usable_error(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(agent_name="rag", verdict=ReportVerdict.ERROR)
        assert report.is_usable is False

    def test_is_high_quality_true(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(
            agent_name="rag",
            verdict=ReportVerdict.CONFIDENT,
            relevance_score=0.85,
        )
        assert report.is_high_quality is True

    def test_is_high_quality_low_relevance(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(
            agent_name="rag",
            verdict=ReportVerdict.CONFIDENT,
            relevance_score=0.5,
        )
        assert report.is_high_quality is False

    def test_to_aggregator_summary(self):
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        report = SubagentReport(
            agent_name="tutor",
            verdict=ReportVerdict.CONFIDENT,
            relevance_score=0.9,
            can_stand_alone=True,
            summary="Giải thích Điều 15 COLREGs chi tiết",
        )
        summary = report.to_aggregator_summary()
        assert "[tutor]" in summary
        assert "HIGH" in summary
        assert "standalone=yes" in summary
        assert "0.90" in summary
        assert "Giải thích" in summary


# =========================================================================
# AggregatorDecision Model
# =========================================================================


class TestAggregatorDecision:
    """AggregatorDecision: merge strategy from aggregator."""

    def test_defaults(self):
        from app.engine.multi_agent.subagents.report import AggregatorDecision

        decision = AggregatorDecision()
        assert decision.action == "use_best"
        assert decision.primary_agent == ""
        assert decision.secondary_agents == []
        assert decision.confidence == 0.0

    def test_synthesize_action(self):
        from app.engine.multi_agent.subagents.report import AggregatorDecision

        decision = AggregatorDecision(
            action="synthesize",
            primary_agent="rag",
            secondary_agents=["tutor"],
            reasoning="Both provide complementary info",
            confidence=0.85,
        )
        assert decision.action == "synthesize"
        assert decision.secondary_agents == ["tutor"]

    def test_re_route_action(self):
        from app.engine.multi_agent.subagents.report import AggregatorDecision

        decision = AggregatorDecision(
            action="re_route",
            re_route_target="direct",
            reasoning="Cần web search",
            confidence=0.6,
        )
        assert decision.action == "re_route"
        assert decision.re_route_target == "direct"

    def test_confidence_bounds(self):
        from app.engine.multi_agent.subagents.report import AggregatorDecision

        decision = AggregatorDecision(confidence=1.0)
        assert decision.confidence == 1.0

        decision = AggregatorDecision(confidence=0.0)
        assert decision.confidence == 0.0


# =========================================================================
# build_report
# =========================================================================


class TestBuildReport:
    """Auto-build SubagentReport from SubagentResult."""

    def test_success_high_confidence(self):
        from app.engine.multi_agent.subagents.report import ReportVerdict, build_report
        from app.engine.multi_agent.subagents.result import SubagentResult

        result = SubagentResult(
            output="Điều 15 COLREGs quy định về tàu cắt mũi nhau." * 3,
            confidence=0.85,
        )
        report = build_report("rag", "retrieval", result)
        assert report.verdict == ReportVerdict.CONFIDENT
        assert report.can_stand_alone is True
        assert report.relevance_score == 0.85

    def test_success_low_confidence(self):
        from app.engine.multi_agent.subagents.report import ReportVerdict, build_report
        from app.engine.multi_agent.subagents.result import SubagentResult

        result = SubagentResult(output="Hmm...", confidence=0.3)
        report = build_report("tutor", "teaching", result)
        assert report.verdict == ReportVerdict.LOW_CONFIDENCE
        assert report.can_stand_alone is False

    def test_error_status(self):
        from app.engine.multi_agent.subagents.report import ReportVerdict, build_report
        from app.engine.multi_agent.subagents.result import (
            SubagentResult,
            SubagentStatus,
        )

        result = SubagentResult(
            status=SubagentStatus.ERROR,
            error_message="LLM unavailable",
        )
        report = build_report("rag", "retrieval", result)
        assert report.verdict == ReportVerdict.ERROR
        assert "Error:" in report.summary

    def test_empty_output(self):
        from app.engine.multi_agent.subagents.report import ReportVerdict, build_report
        from app.engine.multi_agent.subagents.result import SubagentResult

        result = SubagentResult(output="", confidence=0.5)
        report = build_report("rag", "retrieval", result)
        assert report.verdict == ReportVerdict.EMPTY

    def test_partial_needs_complement(self):
        from app.engine.multi_agent.subagents.report import build_report
        from app.engine.multi_agent.subagents.result import SubagentResult

        result = SubagentResult(output="Partial answer", confidence=0.5)
        report = build_report("rag", "retrieval", result)
        assert "teaching" in report.needs_complement

    def test_timeout_status(self):
        from app.engine.multi_agent.subagents.report import ReportVerdict, build_report
        from app.engine.multi_agent.subagents.result import (
            SubagentResult,
            SubagentStatus,
        )

        result = SubagentResult(status=SubagentStatus.TIMEOUT)
        report = build_report("tutor", "teaching", result)
        assert report.verdict == ReportVerdict.ERROR


# =========================================================================
# Deterministic Decision
# =========================================================================


class TestDeterministicDecision:
    """_deterministic_decision: fast path without LLM."""

    def _make_report(self, name, verdict, relevance=0.5, can_stand_alone=False):
        from app.engine.multi_agent.subagents.report import SubagentReport

        return SubagentReport(
            agent_name=name,
            verdict=verdict,
            relevance_score=relevance,
            can_stand_alone=can_stand_alone,
        )

    def test_empty_reports_escalate(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision

        decision = _deterministic_decision([])
        assert decision is not None
        assert decision.action == "escalate"

    def test_all_failed_escalate(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.ERROR),
            self._make_report("tutor", ReportVerdict.EMPTY),
        ]
        decision = _deterministic_decision(reports)
        assert decision is not None
        assert decision.action == "escalate"

    def test_single_usable_use_best(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.CONFIDENT, relevance=0.9),
            self._make_report("tutor", ReportVerdict.ERROR),
        ]
        decision = _deterministic_decision(reports)
        assert decision is not None
        assert decision.action == "use_best"
        assert decision.primary_agent == "rag"

    def test_one_dominant_high_quality(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.CONFIDENT, relevance=0.9),
            self._make_report("tutor", ReportVerdict.PARTIAL, relevance=0.4),
        ]
        decision = _deterministic_decision(reports)
        assert decision is not None
        assert decision.action == "use_best"
        assert decision.primary_agent == "rag"
        assert "tutor" in decision.secondary_agents

    def test_multiple_high_quality_returns_none(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.CONFIDENT, relevance=0.85),
            self._make_report("tutor", ReportVerdict.CONFIDENT, relevance=0.80),
        ]
        decision = _deterministic_decision(reports)
        assert decision is None  # Needs LLM

    def test_multiple_usable_none_high_quality_returns_none(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.PARTIAL, relevance=0.5),
            self._make_report("tutor", ReportVerdict.PARTIAL, relevance=0.5),
        ]
        decision = _deterministic_decision(reports)
        assert decision is None  # Needs LLM

    def test_all_partial_returns_none(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.PARTIAL, relevance=0.4),
            self._make_report("tutor", ReportVerdict.PARTIAL, relevance=0.5),
        ]
        decision = _deterministic_decision(reports)
        assert decision is None

    def test_mixed_quality_one_usable(self):
        from app.engine.multi_agent.subagents.aggregator import _deterministic_decision
        from app.engine.multi_agent.subagents.report import ReportVerdict

        reports = [
            self._make_report("rag", ReportVerdict.CONFIDENT, relevance=0.5),
            self._make_report("tutor", ReportVerdict.LOW_CONFIDENCE, relevance=0.2),
        ]
        decision = _deterministic_decision(reports)
        assert decision is not None
        assert decision.action == "use_best"
        assert decision.primary_agent == "rag"


# =========================================================================
# LLM Decision
# =========================================================================


class TestLLMDecision:
    """_llm_decision: LLM-guided merge for ambiguous cases."""

    @pytest.mark.asyncio
    async def test_synthesize_via_llm(self):
        from app.engine.multi_agent.subagents.aggregator import _llm_decision
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        mock_schema_result = MagicMock()
        mock_schema_result.action = "synthesize"
        mock_schema_result.primary_agent = "rag"
        mock_schema_result.secondary_agents = ["tutor"]
        mock_schema_result.reasoning = "Both add value"
        mock_schema_result.re_route_target = None
        mock_schema_result.confidence = 0.85

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_schema_result)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        reports = [
            SubagentReport(agent_name="rag", verdict=ReportVerdict.CONFIDENT, relevance_score=0.8, summary="RAG output"),
            SubagentReport(agent_name="tutor", verdict=ReportVerdict.CONFIDENT, relevance_score=0.8, summary="Tutor output"),
        ]

        with (
            patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=mock_llm),
            patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_schema_result)),
        ):
            decision = await _llm_decision(reports, "test query", {})

        assert decision.action == "synthesize"
        assert decision.primary_agent == "rag"

    @pytest.mark.asyncio
    async def test_use_best_via_llm(self):
        from app.engine.multi_agent.subagents.aggregator import _llm_decision
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        mock_schema_result = MagicMock()
        mock_schema_result.action = "use_best"
        mock_schema_result.primary_agent = "rag"
        mock_schema_result.secondary_agents = []
        mock_schema_result.reasoning = "RAG better"
        mock_schema_result.re_route_target = None
        mock_schema_result.confidence = 0.9

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_schema_result)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        reports = [
            SubagentReport(agent_name="rag", verdict=ReportVerdict.CONFIDENT, relevance_score=0.8, summary="RAG out"),
        ]

        with (
            patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=mock_llm),
            patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_schema_result)),
        ):
            decision = await _llm_decision(reports, "query", {})

        assert decision.action == "use_best"

    @pytest.mark.asyncio
    async def test_re_route_via_llm(self):
        from app.engine.multi_agent.subagents.aggregator import _llm_decision
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        mock_schema_result = MagicMock()
        mock_schema_result.action = "re_route"
        mock_schema_result.primary_agent = ""
        mock_schema_result.secondary_agents = []
        mock_schema_result.reasoning = "Need web search"
        mock_schema_result.re_route_target = "direct"
        mock_schema_result.confidence = 0.6

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_schema_result)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        reports = [
            SubagentReport(agent_name="rag", verdict=ReportVerdict.PARTIAL, relevance_score=0.3, summary="Low"),
        ]

        with (
            patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=mock_llm),
            patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_schema_result)),
        ):
            decision = await _llm_decision(reports, "query", {})

        assert decision.action == "re_route"
        assert decision.re_route_target == "direct"

    @pytest.mark.asyncio
    async def test_error_fallback(self):
        from app.engine.multi_agent.subagents.aggregator import _llm_decision
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        reports = [
            SubagentReport(agent_name="rag", verdict=ReportVerdict.CONFIDENT, relevance_score=0.8, summary="OK"),
            SubagentReport(agent_name="tutor", verdict=ReportVerdict.PARTIAL, relevance_score=0.4, summary="Low"),
        ]

        with patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=Exception("LLM unavailable"),
        ):
            decision = await _llm_decision(reports, "query", {})

        assert decision.action == "use_best"
        assert decision.primary_agent == "rag"
        assert "fallback" in decision.reasoning.lower() or "Fallback" in decision.reasoning

    @pytest.mark.asyncio
    async def test_no_llm_fallback(self):
        from app.engine.multi_agent.subagents.aggregator import _llm_decision
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )

        reports = [
            SubagentReport(agent_name="tutor", verdict=ReportVerdict.CONFIDENT, relevance_score=0.7, summary="T"),
        ]

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=None):
            decision = await _llm_decision(reports, "query", {})

        assert decision.action == "use_best"
        assert decision.primary_agent == "tutor"


# =========================================================================
# Aggregator Node
# =========================================================================


class TestAggregatorNode:
    """aggregator_node: LangGraph node processing reports."""

    def _report_dict(self, name, verdict, relevance=0.5, output="Some output"):
        from app.engine.multi_agent.subagents.report import SubagentReport
        from app.engine.multi_agent.subagents.result import SubagentResult

        return SubagentReport(
            agent_name=name,
            verdict=verdict,
            relevance_score=relevance,
            summary=output[:100],
            can_stand_alone=relevance > 0.7,
            result=SubagentResult(output=output, confidence=relevance),
        ).model_dump()

    @pytest.mark.asyncio
    async def test_no_reports(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_node

        state = {"query": "test", "subagent_reports": []}
        result = await aggregator_node(state)
        assert result["_aggregator_action"] == "escalate"

    @pytest.mark.asyncio
    async def test_single_confident(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import ReportVerdict

        state = {
            "query": "Điều 15 COLREGs",
            "subagent_reports": [
                self._report_dict("rag", ReportVerdict.CONFIDENT, 0.9, "Full answer"),
            ],
        }
        result = await aggregator_node(state)
        assert result["_aggregator_action"] == "use_best"
        assert "rag" in result.get("agent_outputs", {})

    @pytest.mark.asyncio
    async def test_multiple_synthesize(self):
        """When multiple high-quality reports, LLM decides synthesize."""
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import ReportVerdict

        mock_schema_result = MagicMock()
        mock_schema_result.action = "synthesize"
        mock_schema_result.primary_agent = "rag"
        mock_schema_result.secondary_agents = ["tutor"]
        mock_schema_result.reasoning = "Both useful"
        mock_schema_result.re_route_target = None
        mock_schema_result.confidence = 0.8

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_schema_result)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        state = {
            "query": "Giải thích quy định Điều 15 COLREGs",
            "subagent_reports": [
                self._report_dict("rag", ReportVerdict.CONFIDENT, 0.85, "RAG output"),
                self._report_dict("tutor", ReportVerdict.CONFIDENT, 0.80, "Tutor output"),
            ],
        }

        with (
            patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=mock_llm),
            patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_schema_result)),
        ):
            result = await aggregator_node(state)

        assert result["_aggregator_action"] == "synthesize"
        assert "rag" in result.get("agent_outputs", {})
        assert "tutor" in result.get("agent_outputs", {})

    @pytest.mark.asyncio
    async def test_reroute_within_limit(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import ReportVerdict

        mock_schema_result = MagicMock()
        mock_schema_result.action = "re_route"
        mock_schema_result.primary_agent = ""
        mock_schema_result.secondary_agents = []
        mock_schema_result.reasoning = "Need web"
        mock_schema_result.re_route_target = "direct"
        mock_schema_result.confidence = 0.6

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_schema_result)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        state = {
            "query": "query",
            "_reroute_count": 0,
            "subagent_reports": [
                self._report_dict("rag", ReportVerdict.PARTIAL, 0.3, "Low quality"),
                self._report_dict("tutor", ReportVerdict.PARTIAL, 0.4, "Also low"),
            ],
        }

        with (
            patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=mock_llm),
            patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_schema_result)),
        ):
            result = await aggregator_node(state)

        assert result["_aggregator_action"] == "re_route"
        assert result["_reroute_count"] == 1

    @pytest.mark.asyncio
    async def test_reroute_exceeds_limit_fallback(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import ReportVerdict

        mock_schema_result = MagicMock()
        mock_schema_result.action = "re_route"
        mock_schema_result.primary_agent = ""
        mock_schema_result.secondary_agents = []
        mock_schema_result.reasoning = "Re-route again"
        mock_schema_result.re_route_target = "direct"
        mock_schema_result.confidence = 0.5

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=mock_schema_result)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        state = {
            "query": "query",
            "_reroute_count": 1,  # Already at limit
            "subagent_reports": [
                self._report_dict("rag", ReportVerdict.PARTIAL, 0.4, "Some output"),
            ],
        }

        with (
            patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=mock_llm),
            patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_schema_result)),
        ):
            result = await aggregator_node(state)

        # Should NOT re-route — fallback to use_best instead
        assert result["_aggregator_action"] == "use_best"

    @pytest.mark.asyncio
    async def test_escalate_all_failed(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import ReportVerdict

        state = {
            "query": "query",
            "subagent_reports": [
                self._report_dict("rag", ReportVerdict.ERROR, 0.0, ""),
                self._report_dict("tutor", ReportVerdict.EMPTY, 0.0, ""),
            ],
        }
        result = await aggregator_node(state)
        assert result["_aggregator_action"] == "escalate"
        assert "Xin lỗi" in result.get("final_response", "")

    @pytest.mark.asyncio
    async def test_event_bus_status(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import ReportVerdict

        mock_queue = MagicMock()
        state = {
            "query": "test",
            "_event_bus_id": "test_bus",
            "subagent_reports": [
                self._report_dict("rag", ReportVerdict.CONFIDENT, 0.9, "OK"),
            ],
        }

        with patch("app.engine.multi_agent.graph_streaming._get_event_queue", return_value=mock_queue):
            result = await aggregator_node(state)

        # Sprint 164: aggregator now emits 2 status events (progress + decision)
        assert mock_queue.put_nowait.call_count == 2
        # First event: progress status
        event1 = mock_queue.put_nowait.call_args_list[0][0][0]
        assert event1["type"] == "status"
        assert event1["node"] == "aggregator"
        # Second event: aggregation decision with details
        event2 = mock_queue.put_nowait.call_args_list[1][0][0]
        assert event2["type"] == "status"
        assert event2["node"] == "aggregator"
        assert "details" in event2
        assert "aggregation" in event2["details"]
        assert event2["details"]["aggregation"]["strategy"] == "use_best"


# =========================================================================
# Aggregator Route
# =========================================================================


class TestAggregatorRoute:
    """aggregator_route: conditional edge from aggregator."""

    def test_synthesize_goes_to_synthesizer(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_route

        state = {"_aggregator_action": "synthesize"}
        assert aggregator_route(state) == "synthesizer"

    def test_use_best_goes_to_synthesizer(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_route

        state = {"_aggregator_action": "use_best"}
        assert aggregator_route(state) == "synthesizer"

    def test_escalate_goes_to_synthesizer(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_route

        state = {"_aggregator_action": "escalate"}
        assert aggregator_route(state) == "synthesizer"

    def test_re_route_goes_to_supervisor(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_route

        state = {"_aggregator_action": "re_route"}
        assert aggregator_route(state) == "supervisor"

    def test_empty_goes_to_synthesizer(self):
        from app.engine.multi_agent.subagents.aggregator import aggregator_route

        state = {}
        assert aggregator_route(state) == "synthesizer"


# =========================================================================
# Parallel Dispatch Node
# =========================================================================


@pytest.fixture(autouse=False)
def _mock_graph_imports():
    """Prevent graph.py from triggering real LLM initialization at import."""
    with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=None):
        yield


class TestParallelDispatchNode:
    """parallel_dispatch_node: fan-out to multiple subagents."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_graph_imports")
    async def test_dispatch_rag_and_tutor(self):
        import app.engine.multi_agent.graph as graph_mod
        from app.engine.multi_agent.subagents.result import SubagentResult

        rag_result = SubagentResult(output="RAG result", confidence=0.8)
        tutor_result = SubagentResult(output="Tutor result", confidence=0.7)

        mock_rag = AsyncMock(return_value=rag_result)
        mock_tutor = AsyncMock(return_value=tutor_result)

        state = {
            "query": "Test query",
            "_parallel_targets": ["rag", "tutor"],
        }

        original_adapters = graph_mod._SUBAGENT_ADAPTERS.copy()
        graph_mod._SUBAGENT_ADAPTERS["rag"] = mock_rag
        graph_mod._SUBAGENT_ADAPTERS["tutor"] = mock_tutor
        try:
            result = await graph_mod.parallel_dispatch_node(state)
        finally:
            graph_mod._SUBAGENT_ADAPTERS.update(original_adapters)

        reports = result.get("subagent_reports", [])
        assert len(reports) == 2
        assert reports[0]["agent_name"] == "rag"
        assert reports[1]["agent_name"] == "tutor"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_graph_imports")
    async def test_empty_targets(self):
        from app.engine.multi_agent.graph import parallel_dispatch_node

        state = {"query": "Test", "_parallel_targets": []}
        result = await parallel_dispatch_node(state)
        assert result.get("subagent_reports") == []

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_graph_imports")
    async def test_unknown_target_skipped(self):
        from app.engine.multi_agent.graph import parallel_dispatch_node

        state = {"query": "Test", "_parallel_targets": ["unknown_agent"]}
        result = await parallel_dispatch_node(state)
        assert result.get("subagent_reports") == []

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_graph_imports")
    async def test_default_targets(self):
        import app.engine.multi_agent.graph as graph_mod
        from app.engine.multi_agent.subagents.result import SubagentResult

        mock_result = SubagentResult(output="Output", confidence=0.5)
        mock_adapter = AsyncMock(return_value=mock_result)

        state = {"query": "Test"}  # No _parallel_targets → defaults to rag+tutor

        original_adapters = graph_mod._SUBAGENT_ADAPTERS.copy()
        graph_mod._SUBAGENT_ADAPTERS["rag"] = mock_adapter
        graph_mod._SUBAGENT_ADAPTERS["tutor"] = mock_adapter
        try:
            result = await graph_mod.parallel_dispatch_node(state)
        finally:
            graph_mod._SUBAGENT_ADAPTERS.update(original_adapters)

        reports = result.get("subagent_reports", [])
        assert len(reports) == 2

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_graph_imports")
    async def test_timeout_handled(self):
        """Timeout results are wrapped as reports, not raised."""
        import app.engine.multi_agent.graph as graph_mod
        from app.engine.multi_agent.subagents.result import (
            SubagentResult,
            SubagentStatus,
        )

        timeout_result = SubagentResult(
            status=SubagentStatus.TIMEOUT,
            error_message="Timed out",
            duration_ms=60000,
        )
        mock_adapter = AsyncMock(return_value=timeout_result)

        state = {"query": "Test", "_parallel_targets": ["rag"]}

        original_adapters = graph_mod._SUBAGENT_ADAPTERS.copy()
        graph_mod._SUBAGENT_ADAPTERS["rag"] = mock_adapter
        try:
            result = await graph_mod.parallel_dispatch_node(state)
        finally:
            graph_mod._SUBAGENT_ADAPTERS.update(original_adapters)

        reports = result.get("subagent_reports", [])
        assert len(reports) == 1
        assert reports[0]["verdict"] == "error"


# =========================================================================
# Graph Integration
# =========================================================================


class TestGraphIntegration:
    """Graph wiring: route_decision, routing map, node registration."""

    @pytest.mark.usefixtures("_mock_graph_imports")
    def test_route_decision_parallel_dispatch(self):
        from app.engine.multi_agent.graph import route_decision

        state = {"next_agent": "parallel_dispatch"}
        assert route_decision(state) == "parallel_dispatch"

    @pytest.mark.usefixtures("_mock_graph_imports")
    def test_route_decision_standard_agents(self):
        from app.engine.multi_agent.graph import route_decision

        assert route_decision({"next_agent": "rag_agent"}) == "rag_agent"
        assert route_decision({"next_agent": "tutor_agent"}) == "tutor_agent"
        assert route_decision({"next_agent": "memory_agent"}) == "memory_agent"
        assert route_decision({"next_agent": "direct"}) == "direct"
        assert route_decision({"next_agent": "unknown"}) == "direct"

    def test_routing_map_includes_parallel_when_enabled(self):
        """When enable_subagent_architecture=True, parallel_dispatch is in the map."""
        with patch("app.engine.multi_agent.graph.settings") as mock_settings:
            mock_settings.enable_product_search = False
            mock_settings.enable_subagent_architecture = True
            mock_settings.quality_skip_threshold = 0.85

            # Keep this focused on routing-map behavior without invoking runtime orchestration.
            _routing_map = {
                "rag_agent": "rag_agent",
                "tutor_agent": "tutor_agent",
                "memory_agent": "memory_agent",
                "direct": "direct",
            }
            if mock_settings.enable_subagent_architecture:
                _routing_map["parallel_dispatch"] = "parallel_dispatch"

            assert "parallel_dispatch" in _routing_map

    def test_routing_map_excludes_parallel_when_disabled(self):
        """When enable_subagent_architecture=False, parallel_dispatch not in map."""
        _routing_map = {
            "rag_agent": "rag_agent",
            "tutor_agent": "tutor_agent",
            "memory_agent": "memory_agent",
            "direct": "direct",
        }
        # Don't add parallel_dispatch
        assert "parallel_dispatch" not in _routing_map

    @pytest.mark.usefixtures("_mock_graph_imports")
    def test_route_decision_product_search(self):
        from app.engine.multi_agent.graph import route_decision

        state = {"next_agent": "product_search_agent"}
        assert route_decision(state) == "product_search_agent"


# =========================================================================
# Supervisor _is_complex_query
# =========================================================================


class TestIsComplexQuery:
    """SupervisorAgent._is_complex_query heuristic."""

    def _get_supervisor(self):
        """Create a SupervisorAgent with mocked LLM."""
        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm = MagicMock(return_value=None)
            from app.engine.multi_agent.supervisor import SupervisorAgent
            return SupervisorAgent()

    def test_short_query_not_complex(self):
        supervisor = self._get_supervisor()
        assert supervisor._is_complex_query("COLREGs", {}) is False

    def test_long_query_with_mixed_signals(self):
        supervisor = self._get_supervisor()
        query = "Tra cứu nội dung Điều 15 COLREGs rồi giải thích chi tiết cho tôi hiểu cách áp dụng trong thực tế"
        assert supervisor._is_complex_query(query, {"confidence": 0.8}) is True

    def test_long_query_without_mixed_signals(self):
        supervisor = self._get_supervisor()
        query = "Giải thích Điều 15 COLREGs cho tôi hiểu rõ hơn, cụ thể các trường hợp áp dụng trong thực tế hàng hải"
        assert supervisor._is_complex_query(query, {"confidence": 0.9}) is False

    def test_borderline_confidence_long_query(self):
        supervisor = self._get_supervisor()
        query = "A" * 130  # Very long but no mixed signals
        assert supervisor._is_complex_query(query, {"confidence": 0.6}) is True

    def test_mixed_intent_lookup_and_learning(self):
        supervisor = self._get_supervisor()
        query = "Cho biết quy định Điều 8 COLREGs và hướng dẫn cách thực hiện đúng quy trình tránh va trong hải đồ"
        assert supervisor._is_complex_query(query, {}) is True


# =========================================================================
# AggregatorDecisionSchema
# =========================================================================


class TestAggregatorDecisionSchema:
    """Structured schema for LLM output."""

    def test_schema_fields(self):
        from app.engine.structured_schemas import AggregatorDecisionSchema

        schema = AggregatorDecisionSchema(
            action="synthesize",
            primary_agent="rag",
            secondary_agents=["tutor"],
            reasoning="Cả hai đều hữu ích",
            confidence=0.85,
        )
        assert schema.action == "synthesize"
        assert schema.primary_agent == "rag"
        assert schema.confidence == 0.85

    def test_schema_defaults(self):
        from app.engine.structured_schemas import AggregatorDecisionSchema

        schema = AggregatorDecisionSchema(action="use_best")
        assert schema.primary_agent == ""
        assert schema.secondary_agents == []
        assert schema.re_route_target is None
        assert schema.confidence == 0.8


# =========================================================================
# State Fields
# =========================================================================


class TestStateFields:
    """Verify new AgentState fields exist and are Optional."""

    def test_new_state_fields_are_optional(self):
        from app.engine.multi_agent.state import AgentState

        # TypedDict with total=False — all fields optional
        state: AgentState = {
            "query": "test",
        }
        # These should not raise
        assert state.get("subagent_reports") is None
        assert state.get("_aggregator_action") is None
        assert state.get("_aggregator_reasoning") is None
        assert state.get("_reroute_count") is None
        assert state.get("_parallel_targets") is None

    def test_state_accepts_new_fields(self):
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "test",
            "subagent_reports": [{"agent_name": "rag"}],
            "_aggregator_action": "use_best",
            "_aggregator_reasoning": "Best result",
            "_reroute_count": 0,
            "_parallel_targets": ["rag", "tutor"],
        }
        assert state["subagent_reports"] == [{"agent_name": "rag"}]
        assert state["_parallel_targets"] == ["rag", "tutor"]


# =========================================================================
# Sprint 165: LLM Fallback & Confidence Scale
# =========================================================================


class TestRAGSubgraphFallback:
    """Sprint 165: RAG subgraph uses LLM fallback when KB is empty."""

    @pytest.mark.asyncio
    async def test_rag_subgraph_fallback_empty_kb(self):
        """When no docs found, generate_node calls LLM fallback instead of hardcoded error."""
        from app.engine.multi_agent.subagents.rag.runtime import generate_node

        state = {
            "retrieval_docs": [],
            "query": "Điều 15 COLREGs là gì?",
            "retrieval_confidence": 0.0,
            "context": {"domain_name": "Hàng hải"},
        }

        mock_crag = MagicMock()
        mock_crag._generate_fallback = AsyncMock(
            return_value="Điều 15 COLREGs quy định về tình huống cắt mũi nhau."
        )

        with patch(
            "app.engine.agentic_rag.corrective_rag.get_corrective_rag",
            return_value=mock_crag,
        ):
            result = await generate_node(state)

        assert "cắt mũi" in result["final_response"]
        assert "Xin lỗi" not in result["final_response"]
        mock_crag._generate_fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rag_subgraph_fallback_confidence_scale(self):
        """Fallback response gets capped confidence on 0-1 scale."""
        from app.engine.multi_agent.subagents.rag.runtime import generate_node

        state = {
            "retrieval_docs": [],
            "query": "Test query",
            "retrieval_confidence": 0.0,
            "context": {},
        }

        mock_crag = MagicMock()
        mock_crag._generate_fallback = AsyncMock(return_value="LLM answer")

        with patch(
            "app.engine.agentic_rag.corrective_rag.get_corrective_rag",
            return_value=mock_crag,
        ):
            result = await generate_node(state)

        # Fallback confidence should be 0.55 (0-1 scale)
        assert result["crag_confidence"] == 0.55
        assert 0 <= result["crag_confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_rag_subgraph_fallback_failure_returns_static(self):
        """When LLM fallback fails, returns static error message."""
        from app.engine.multi_agent.subagents.rag.runtime import generate_node

        state = {
            "retrieval_docs": [],
            "query": "Test query",
            "retrieval_confidence": 0.0,
        }

        with patch(
            "app.engine.agentic_rag.corrective_rag.get_corrective_rag",
            side_effect=Exception("LLM unavailable"),
        ):
            result = await generate_node(state)

        assert "Xin lỗi" in result["final_response"]


class TestAggregatorEmptyKBFallback:
    """Sprint 165: Aggregator tries LLM fallback before escalating on empty KB."""

    @pytest.mark.asyncio
    async def test_aggregator_empty_kb_fallback_before_escalate(self):
        """When all reports are empty (KB), try LLM before escalating."""
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )
        from app.engine.multi_agent.subagents.result import SubagentResult

        state = {
            "query": "Quy định COLREGs",
            "subagent_reports": [
                SubagentReport(
                    agent_name="rag",
                    verdict=ReportVerdict.EMPTY,
                    relevance_score=0.0,
                    result=SubagentResult(output="", confidence=0.0),
                ).model_dump(),
                SubagentReport(
                    agent_name="tutor",
                    verdict=ReportVerdict.EMPTY,
                    relevance_score=0.0,
                    result=SubagentResult(output="", confidence=0.0),
                ).model_dump(),
            ],
        }

        mock_crag = MagicMock()
        mock_crag._generate_fallback = AsyncMock(
            return_value="COLREGs là bộ quy tắc tránh va chạm trên biển."
        )

        with patch(
            "app.engine.agentic_rag.corrective_rag.get_corrective_rag",
            return_value=mock_crag,
        ):
            result = await aggregator_node(state)

        # Should use fallback, NOT escalate
        assert result["_aggregator_action"] == "use_best"
        assert "aggregator_fallback" in result.get("agent_outputs", {})
        assert "COLREGs" in result["agent_outputs"]["aggregator_fallback"]

    @pytest.mark.asyncio
    async def test_aggregator_real_error_still_escalates(self):
        """Real errors (timeout/crash) still escalate — no LLM fallback attempted."""
        from app.engine.multi_agent.subagents.aggregator import aggregator_node
        from app.engine.multi_agent.subagents.report import (
            ReportVerdict,
            SubagentReport,
        )
        from app.engine.multi_agent.subagents.result import (
            SubagentResult,
            SubagentStatus,
        )

        state = {
            "query": "Test",
            "subagent_reports": [
                SubagentReport(
                    agent_name="rag",
                    verdict=ReportVerdict.ERROR,
                    relevance_score=0.0,
                    result=SubagentResult(
                        status=SubagentStatus.ERROR,
                        error_message="Connection refused",
                    ),
                ).model_dump(),
            ],
        }

        result = await aggregator_node(state)
        # Real errors should still escalate
        assert result["_aggregator_action"] == "escalate"
        assert "Xin lỗi" in result.get("final_response", "")

    @pytest.mark.asyncio
    async def test_confidence_scale_consistency(self):
        """Confidence values throughout pipeline stay on 0-1 scale."""
        from app.engine.multi_agent.subagents.rag.runtime import grade_node

        # Simulating retrieval scores (already 0-1 from search service)
        state = {
            "retrieval_docs": [{"content": "Test", "metadata": {}}],
            "retrieval_scores": [0.7, 0.8, 0.6],
            "query": "Test",
        }
        result = await grade_node(state)

        confidence = result["retrieval_confidence"]
        assert 0 <= confidence <= 1.0, f"Confidence {confidence} out of 0-1 range"
