"""Supervisor aggregator — reads subagent reports and decides merge strategy.

Sprint 163 Phase 4: Two-tier decision (deterministic fast path + LLM fallback).

Pattern inspired by Claude Code hub-and-spoke:
- Subagents are isolated, never talk to each other
- Results come back as structured SubagentReport
- Aggregator reads all reports, picks best strategy

Usage in WiiiRunner::

    runner.register_feature_node("aggregator", aggregator_node, gate_fn)
    aggregator_route(state) decides synthesizer vs supervisor follow-up.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from app.engine.multi_agent.subagents.report import (
    AggregatorDecision,
    ReportVerdict,
    SubagentReport,
    sanitize_subagent_report_for_parent,
)
from app.engine.multi_agent.subagents.event_stream import push_subagent_stream_event
from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text

logger = logging.getLogger(__name__)

# Prevent infinite re-route loops
_MAX_REROUTE_ATTEMPTS = 1

# LLM prompt for ambiguous merge decisions
_AGGREGATOR_PROMPT = """Bạn là Aggregator Agent. Đọc báo cáo từ các subagent và quyết định cách tổng hợp.

## Báo cáo:
{reports_text}

## Query gốc:
{query}

## Quyết định (chọn 1):
- "synthesize": Kết hợp nội dung từ nhiều agent (khi cả hai đều có giá trị bổ sung)
- "use_best": Dùng output của agent tốt nhất (khi một agent rõ ràng tốt hơn)
- "re_route": Gửi lại query đến agent khác (khi tất cả chưa đạt)
- "escalate": Báo lỗi (khi không agent nào có kết quả)

Trả lời JSON:
{{"action": "...", "primary_agent": "...", "secondary_agents": [...], "reasoning": "...", "confidence": 0.0-1.0}}"""


def _deterministic_decision(
    reports: List[SubagentReport],
) -> Optional[AggregatorDecision]:
    """Fast-path decision without LLM.

    Returns None if the situation is ambiguous and needs LLM.
    """
    if not reports:
        return AggregatorDecision(
            action="escalate",
            reasoning="Không có báo cáo nào",
            confidence=1.0,
        )

    usable = [r for r in reports if r.is_usable]
    high_quality = [r for r in reports if r.is_high_quality]

    # All failed → escalate
    if not usable:
        return AggregatorDecision(
            action="escalate",
            reasoning="Tất cả subagent đều thất bại hoặc không có kết quả",
            confidence=1.0,
        )

    # Exactly one usable → use_best
    if len(usable) == 1:
        agent = usable[0]
        return AggregatorDecision(
            action="use_best",
            primary_agent=agent.agent_name,
            reasoning=f"Chỉ {agent.agent_name} có kết quả khả dụng",
            confidence=agent.relevance_score,
        )

    # One dominant high-quality, others not → use_best with secondaries
    if len(high_quality) == 1:
        best = high_quality[0]
        secondaries = [
            r.agent_name for r in usable if r.agent_name != best.agent_name
        ]
        return AggregatorDecision(
            action="use_best",
            primary_agent=best.agent_name,
            secondary_agents=secondaries,
            reasoning=f"{best.agent_name} chất lượng cao nhất",
            confidence=best.relevance_score,
        )

    # Multiple high-quality → need LLM to decide merge strategy
    if len(high_quality) > 1:
        return None  # Ambiguous — defer to LLM

    # Multiple usable but none high-quality → need LLM
    if len(usable) > 1:
        return None

    return None


async def _llm_decision(
    reports: List[SubagentReport],
    query: str,
    state: Dict[str, Any],
) -> AggregatorDecision:
    """LLM-guided merge decision for ambiguous cases.

    Falls back to highest-relevance pick on error.
    """
    try:
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        thinking_effort = state.get("thinking_effort")
        llm = AgentConfigRegistry.get_llm(
            "supervisor",
            effort_override=thinking_effort,
            provider_override=state.get("provider"),
            requested_model=state.get("model"),
        )

        if not llm:
            return _fallback_decision(reports)

        # Build reports summary for prompt
        reports_text = "\n".join(r.to_aggregator_summary() for r in reports)

        from app.engine.messages import Message
        from app.engine.messages_adapters import to_openai_dict

        chat_messages = [
            Message(role="system", content="You are an aggregator. Respond ONLY with valid JSON."),
            Message(role="user", content=_AGGREGATOR_PROMPT.format(
                reports_text=reports_text,
                query=query,
            )),
        ]

        from app.engine.structured_schemas import AggregatorDecisionSchema
        from app.services.structured_invoke_service import StructuredInvokeService

        result = await StructuredInvokeService.ainvoke(
            llm=llm,
            schema=AggregatorDecisionSchema,
            payload=[to_openai_dict(m) for m in chat_messages],
            tier="moderate",
        )

        return AggregatorDecision(
            action=result.action,
            primary_agent=result.primary_agent,
            secondary_agents=result.secondary_agents,
            reasoning=result.reasoning,
            re_route_target=result.re_route_target,
            confidence=result.confidence,
        )

    except Exception as e:
        logger.warning("[AGGREGATOR] LLM decision failed: %s, using fallback", e)
        return _fallback_decision(reports)


def _fallback_decision(reports: List[SubagentReport]) -> AggregatorDecision:
    """Pick the report with the highest relevance_score."""
    usable = [r for r in reports if r.is_usable]
    if not usable:
        return AggregatorDecision(
            action="escalate",
            reasoning="Không có kết quả khả dụng (fallback)",
            confidence=0.0,
        )

    best = max(usable, key=lambda r: r.relevance_score)
    return AggregatorDecision(
        action="use_best",
        primary_agent=best.agent_name,
        reasoning=f"Fallback: chọn {best.agent_name} (relevance={best.relevance_score:.2f})",
        confidence=best.relevance_score,
    )


async def aggregator_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """WiiiRunner node: reads subagent_reports, produces aggregator decision.

    Writes:
    - state["_aggregator_action"]
    - state["_aggregator_reasoning"]
    - state["final_response"] (for use_best/escalate)
    - state["agent_outputs"] (merged from reports)
    """
    raw_reports = state.get("subagent_reports") or []

    # Deserialize reports from dicts
    reports: List[SubagentReport] = []
    for item in raw_reports:
        if isinstance(item, SubagentReport):
            reports.append(sanitize_subagent_report_for_parent(item))
        elif isinstance(item, dict):
            try:
                reports.append(
                    sanitize_subagent_report_for_parent(SubagentReport(**item))
                )
            except Exception as e:
                logger.warning("[AGGREGATOR] Bad report dict: %s", e)
        # else skip
    state["subagent_reports"] = [report.model_dump() for report in reports]

    logger.info(
        "[AGGREGATOR] Processing %d reports: %s",
        len(reports),
        [r.agent_name for r in reports],
    )

    # Emit status event if bus available
    _bus_id = state.get("_event_bus_id")
    if _bus_id:
        try:
            from app.engine.multi_agent.graph_event_bus import _get_event_queue
            queue = _get_event_queue(_bus_id)
            if queue:
                push_subagent_stream_event(queue, {
                    "type": "status",
                    "content": "Tổng hợp báo cáo từ các agent...",
                    "node": "aggregator",
                })
        except Exception:
            pass

    # Record metrics
    try:
        from app.engine.multi_agent.subagents.metrics import SubagentMetrics
        tracker = SubagentMetrics.get_instance()
        for r in reports:
            tracker.record(
                f"aggregator_input_{r.agent_name}",
                duration_ms=r.result.duration_ms,
                status=r.result.status.value if r.result.status else "unknown",
                confidence=r.relevance_score,
            )
    except Exception:
        pass

    # Two-tier decision
    query = state.get("query", "")
    decision = _deterministic_decision(reports)

    if decision is None:
        decision = await _llm_decision(reports, query, state)

    # Re-route guard
    reroute_count = state.get("_reroute_count") or 0
    if decision.action == "re_route" and reroute_count >= _MAX_REROUTE_ATTEMPTS:
        logger.info(
            "[AGGREGATOR] Re-route blocked (count=%d >= max=%d), falling back",
            reroute_count,
            _MAX_REROUTE_ATTEMPTS,
        )
        decision = _fallback_decision(reports)

    decision = decision.model_copy(
        update={
            "reasoning": redact_runtime_secret_text(decision.reasoning),
            "primary_agent": redact_runtime_secret_text(decision.primary_agent),
            "secondary_agents": [
                redact_runtime_secret_text(agent)
                for agent in (decision.secondary_agents or [])
            ],
            "re_route_target": (
                redact_runtime_secret_text(decision.re_route_target)
                if decision.re_route_target
                else None
            ),
        }
    )
    logger.info(
        "[AGGREGATOR] Decision: action=%s, primary=%s, confidence=%.2f | %s",
        decision.action,
        decision.primary_agent,
        decision.confidence,
        decision.reasoning,
    )

    # Sprint 164: Emit aggregation decision details for desktop UI
    if _bus_id:
        try:
            from app.engine.multi_agent.graph_event_bus import _get_event_queue
            queue = _get_event_queue(_bus_id)
            if queue:
                push_subagent_stream_event(queue, {
                    "type": "status",
                    "content": f"Quyết định: {decision.action}",
                    "node": "aggregator",
                    "details": {
                        "aggregation": {
                            "strategy": decision.action,
                            "primary_agent": decision.primary_agent,
                            "confidence": decision.confidence,
                            "reasoning": decision.reasoning,
                        }
                    },
                })
        except Exception:
            pass

    # Sprint 165: If escalating due to empty KB (not real errors), try LLM fallback first
    if decision.action == "escalate" and _is_empty_kb_escalation(reports):
        logger.info("[AGGREGATOR] Empty KB escalation — attempting LLM fallback")
        fallback_response = await _llm_fallback_for_empty_kb(query, state)
        if fallback_response:
            decision = AggregatorDecision(
                action="use_best",
                primary_agent="aggregator_fallback",
                reasoning="KB trống — dùng kiến thức tổng quát LLM",
                confidence=0.45,
            )
            state["agent_outputs"] = {"aggregator_fallback": fallback_response}

    # Apply decision to state
    state["_aggregator_action"] = decision.action
    state["_aggregator_reasoning"] = decision.reasoning

    if decision.action == "escalate":
        state["final_response"] = (
            "Xin lỗi, mình chưa xử lý được lúc này. "
            "Bạn thử lại giúp mình nhé~ ≽^•⩊•^≼"
        )
        state["agent_outputs"] = {"aggregator": state["final_response"]}

    elif decision.action == "use_best":
        # Sprint 165: Skip report lookup for LLM fallback (output already in state)
        if decision.primary_agent == "aggregator_fallback" and "aggregator_fallback" in state.get("agent_outputs", {}):
            pass  # agent_outputs already set by fallback
        elif (primary := next(
            (r for r in reports if r.agent_name == decision.primary_agent),
            None,
        )) and primary.result.output:
            state["agent_outputs"] = {primary.agent_name: primary.result.output}
            # Also include secondaries for synthesis
            for sec_name in decision.secondary_agents:
                sec = next((r for r in reports if r.agent_name == sec_name), None)
                if sec and sec.result.output:
                    state["agent_outputs"][sec.agent_name] = sec.result.output
        else:
            # Primary not found or empty — try any usable
            for r in reports:
                if r.is_usable and r.result.output:
                    state["agent_outputs"] = {r.agent_name: r.result.output}
                    break
            else:
                state["agent_outputs"] = {
                    "aggregator": "Không có kết quả phù hợp."
                }

    elif decision.action == "synthesize":
        # Collect all usable outputs for synthesizer
        outputs = {}
        for r in reports:
            if r.is_usable and r.result.output:
                outputs[r.agent_name] = r.result.output
        state["agent_outputs"] = outputs if outputs else {
            "aggregator": "Không có kết quả để tổng hợp."
        }

    elif decision.action == "re_route":
        state["_reroute_count"] = reroute_count + 1
        if decision.re_route_target:
            state["next_agent"] = decision.re_route_target

    # Propagate sources, tools, and evidence images from reports
    all_sources = []
    all_tools = []
    all_evidence_images = []
    for r in reports:
        all_sources.extend(r.result.sources)
        all_tools.extend(r.result.tools_used)
        all_evidence_images.extend(r.result.evidence_images)  # Sprint 189b
    if all_sources:
        state["sources"] = all_sources
    if all_tools:
        state["tools_used"] = all_tools
    if all_evidence_images:
        state["evidence_images"] = all_evidence_images  # Sprint 189b

    return state


def _is_empty_kb_escalation(reports: List[SubagentReport]) -> bool:
    """Check if all reports failed due to empty KB (no docs), not real errors.

    Returns True when all reports are EMPTY/LOW_CONFIDENCE (KB-related),
    False if any report has ERROR/TIMEOUT status (infrastructure failure).
    """
    if not reports:
        return False

    for r in reports:
        # Real infrastructure errors → not empty KB
        if r.verdict == ReportVerdict.ERROR:
            if r.result.status and r.result.status.value in ("error", "timeout"):
                return False
    # All reports are empty/low_confidence → likely empty KB
    return all(
        r.verdict in (ReportVerdict.EMPTY, ReportVerdict.LOW_CONFIDENCE)
        for r in reports
    )


async def _llm_fallback_for_empty_kb(
    query: str, state: Dict[str, Any]
) -> Optional[str]:
    """Attempt LLM general knowledge response when KB is empty.

    Delegates to CorrectiveRAG._generate_fallback() for consistency.
    Returns None if fallback fails.
    """
    try:
        from app.engine.agentic_rag.corrective_rag import get_corrective_rag

        crag = get_corrective_rag()
        context = state.get("context") or {}
        context.setdefault("domain_name", state.get("domain_id", ""))
        response = await crag._generate_fallback(query, context)
        if response and not any(
            p in response.lower()
            for p in ("không tìm thấy", "không có thông tin", "không thể trả lời")
        ):
            return response
    except Exception as exc:
        logger.warning("[AGGREGATOR] LLM fallback for empty KB failed: %s", exc)
    return None


def aggregator_route(
    state: Dict[str, Any],
) -> Literal["synthesizer", "supervisor"]:
    """Conditional edge from aggregator node.

    - synthesize/use_best/escalate → synthesizer
    - re_route → supervisor (for another routing attempt)
    """
    action = state.get("_aggregator_action", "")
    if action == "re_route":
        return "supervisor"
    return "synthesizer"
