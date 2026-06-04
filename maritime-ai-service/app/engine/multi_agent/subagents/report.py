"""Structured report models for subagent results and aggregator decisions.

Sprint 163 Phase 4: Supervisor-Reads-Reports pattern.
Subagents return SubagentReport (structured evaluation of their result).
Aggregator reads reports and produces AggregatorDecision (merge strategy).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus


_MAX_PUBLIC_ITEMS = 16
_MAX_PUBLIC_TEXT = 500
_SAFE_SOURCE_KEYS = {
    "id",
    "node_id",
    "source_id",
    "title",
    "source",
    "source_type",
    "content_type",
    "page",
    "page_number",
    "document_id",
    "image_url",
    "url",
    "relevance_score",
    "score",
    "bounding_boxes",
}
_SAFE_TOOL_KEYS = {
    "name",
    "status",
    "duration_ms",
    "tool",
    "tool_name",
    "provider",
    "source",
    "error_type",
}
_SAFE_EVIDENCE_KEYS = {
    "url",
    "image_url",
    "page",
    "page_number",
    "document_id",
    "content_type",
    "source",
}


def _safe_text(value: Any, *, max_length: int = _MAX_PUBLIC_TEXT) -> str:
    text = redact_runtime_secret_text(str(value or ""))
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 1] + "..."
    return text


def _safe_mapping_list(values: Any, *, allowed_keys: set[str]) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    safe_values: list[dict[str, Any]] = []
    for raw_item in values[:_MAX_PUBLIC_ITEMS]:
        safe_item = sanitize_runtime_payload(raw_item)
        if not isinstance(safe_item, dict):
            continue
        item = {
            str(key): _safe_public_value(value)
            for key, value in safe_item.items()
            if str(key) in allowed_keys and value not in (None, "", [], {})
        }
        if item:
            safe_values.append(item)
    return safe_values


def _safe_public_value(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value, max_length=240)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return value[:8]
    if isinstance(value, dict):
        return {
            str(key): item
            for key, item in list(value.items())[:16]
            if isinstance(item, (str, bool, int, float)) or item is None
        }
    return _safe_text(value, max_length=240)


def _safe_data_provenance(value: Any) -> dict[str, Any]:
    safe_data = sanitize_runtime_payload(value)
    if not isinstance(safe_data, dict) or not safe_data:
        return {}
    keys = sorted(
        str(key)
        for key in safe_data.keys()
        if str(key) != "redacted_secret_count"
    )
    return {
        "present": True,
        "key_count": len(keys),
        "keys": keys[:24],
    }


def _safe_boundary(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value)
    if not isinstance(safe_value, dict):
        return {}
    return {
        str(key): item
        for key, item in safe_value.items()
        if str(key) != "redacted_secret_count"
    }


def sanitize_subagent_result_for_parent(result: SubagentResult) -> SubagentResult:
    """Project a child result into the parent/aggregator-safe shape."""

    return SubagentResult(
        status=result.status,
        confidence=result.confidence,
        output=_safe_text(result.output, max_length=4000),
        data=_safe_data_provenance(result.data),
        sources=_safe_mapping_list(result.sources, allowed_keys=_SAFE_SOURCE_KEYS),
        tools_used=_safe_mapping_list(result.tools_used, allowed_keys=_SAFE_TOOL_KEYS),
        evidence_images=_safe_mapping_list(
            result.evidence_images,
            allowed_keys=_SAFE_EVIDENCE_KEYS,
        ),
        boundary=_safe_boundary(result.boundary),
        thinking=None,
        error_message=(
            _safe_text(result.error_message, max_length=500)
            if result.error_message
            else None
        ),
        duration_ms=result.duration_ms,
    )


def sanitize_subagent_report_for_parent(report: "SubagentReport") -> "SubagentReport":
    """Return a report that is safe to store in parent state or prompt."""

    return report.model_copy(
        update={
            "result": sanitize_subagent_result_for_parent(report.result),
            "summary": _safe_text(report.summary, max_length=500),
        }
    )


class ReportVerdict(str, Enum):
    """Quality verdict for a subagent's output."""

    CONFIDENT = "confident"
    PARTIAL = "partial"
    LOW_CONFIDENCE = "low_confidence"
    EMPTY = "empty"
    ERROR = "error"


class SubagentReport(BaseModel):
    """Structured report wrapping a subagent's result for the aggregator.

    The supervisor dispatches queries to multiple subagents in parallel.
    Each result is wrapped in a SubagentReport with quality metadata so
    the aggregator can make informed merge decisions without re-reading
    full outputs.
    """

    agent_name: str = Field(..., min_length=1, max_length=64)
    agent_type: str = Field(default="general", max_length=32)
    result: SubagentResult = Field(default_factory=SubagentResult)
    verdict: ReportVerdict = Field(default=ReportVerdict.EMPTY)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = Field(default="", max_length=500)
    can_stand_alone: bool = Field(default=False)
    needs_complement: List[str] = Field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """Report has actionable content (confident or partial)."""
        return self.verdict in (ReportVerdict.CONFIDENT, ReportVerdict.PARTIAL)

    @property
    def is_high_quality(self) -> bool:
        """Report is confident with high relevance."""
        return self.verdict == ReportVerdict.CONFIDENT and self.relevance_score >= 0.7

    def to_aggregator_summary(self) -> str:
        """One-line summary for inclusion in aggregator LLM prompt."""
        quality = "HIGH" if self.is_high_quality else (
            "OK" if self.is_usable else "LOW"
        )
        standalone = "yes" if self.can_stand_alone else "no"
        summary = _safe_text(self.summary, max_length=500)
        return (
            f"[{self.agent_name}] quality={quality} "
            f"relevance={self.relevance_score:.2f} "
            f"standalone={standalone} | {summary}"
        )


def build_report(
    agent_name: str,
    agent_type: str,
    result: SubagentResult,
) -> SubagentReport:
    """Build a SubagentReport from a SubagentResult with auto-verdict.

    Evaluates the result quality and assigns verdict, relevance_score,
    summary, and can_stand_alone automatically.
    """
    original_result = result
    result = sanitize_subagent_result_for_parent(result)

    # Determine verdict from original status and confidence
    if result.status == SubagentStatus.ERROR:
        verdict = ReportVerdict.ERROR
    elif result.status == SubagentStatus.TIMEOUT:
        verdict = ReportVerdict.ERROR
    elif result.status == SubagentStatus.SKIPPED:
        verdict = ReportVerdict.EMPTY
    elif not original_result.output and not original_result.data:
        verdict = ReportVerdict.EMPTY
    elif result.confidence >= 0.7:
        verdict = ReportVerdict.CONFIDENT
    elif result.confidence >= 0.4:
        verdict = ReportVerdict.PARTIAL
    else:
        verdict = ReportVerdict.LOW_CONFIDENCE

    # Auto-generate summary
    if result.output:
        summary = result.output[:200].replace("\n", " ").strip()
    elif result.error_message:
        summary = f"Error: {result.error_message[:150]}"
    else:
        summary = "No output"

    # Can stand alone if confident with sufficient output
    can_stand_alone = (
        verdict == ReportVerdict.CONFIDENT
        and len(result.output) >= 50
    )

    # Needs complement hints
    needs_complement: List[str] = []
    if verdict == ReportVerdict.PARTIAL:
        if agent_type == "retrieval":
            needs_complement.append("teaching")
        elif agent_type == "teaching":
            needs_complement.append("retrieval")

    return SubagentReport(
        agent_name=agent_name,
        agent_type=agent_type,
        result=result,
        verdict=verdict,
        relevance_score=result.confidence,
        summary=summary,
        can_stand_alone=can_stand_alone,
        needs_complement=needs_complement,
    )


class AggregatorDecision(BaseModel):
    """Decision from the aggregator on how to merge subagent reports.

    Actions:
    - synthesize: Merge content from multiple agents
    - use_best: Use the primary agent's output as-is
    - re_route: Send query to a different agent
    - escalate: All agents failed, return error
    """

    action: str = Field(
        default="use_best",
        pattern=r"^(synthesize|use_best|re_route|escalate)$",
    )
    primary_agent: str = Field(default="")
    secondary_agents: List[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=500)
    re_route_target: Optional[str] = Field(default=None)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
