"""Aggregate diagnostics for semantic-memory write audit events."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

SEMANTIC_MEMORY_WRITE_DOCTOR_VERSION = "wiii.semantic_memory_write_doctor.v1"
SEMANTIC_MEMORY_WRITE_DOCTOR_HISTORY_VERSION = (
    "wiii.semantic_memory_write_doctor_history.v1"
)
_MAX_COUNTER_ITEMS = 24
_MAX_TOKEN_LENGTH = 96
_SAFE_COUNTER_TOKEN_RE = re.compile(
    rf"^[A-Za-z0-9_.:/-]{{1,{_MAX_TOKEN_LENGTH}}}$"
)


def _plain_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_token(value: Any, *, fallback: str = "unknown") -> str:
    token = " ".join(str(value or "").strip().split())
    if not token:
        return fallback
    if _SAFE_COUNTER_TOKEN_RE.fullmatch(token):
        return token
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    safe_fallback = fallback if _SAFE_COUNTER_TOKEN_RE.fullmatch(fallback) else "unknown"
    return f"{safe_fallback}_hash:{digest}"


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(counter.most_common(_MAX_COUNTER_ITEMS))


def _positive_int(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


def _semantic_memory_write_payload_from_event(event: Any) -> Mapping[str, Any] | None:
    if isinstance(event, Mapping):
        payload = _plain_mapping(event.get("payload", event))
    else:
        payload = _plain_mapping(getattr(event, "payload", None))
    if payload.get("schema_version") == "wiii.semantic_memory_write.v1":
        return payload
    return None


def _event_created_at_hour(event: Any) -> str:
    if isinstance(event, Mapping):
        raw_value = event.get("created_at")
    else:
        raw_value = getattr(event, "created_at", None)
    if hasattr(raw_value, "isoformat"):
        value = raw_value
    elif isinstance(raw_value, str) and raw_value.strip():
        text = raw_value.strip()
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"
    else:
        return "unknown"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return value.isoformat()


def semantic_memory_write_payloads_from_events(
    events: Iterable[Any],
) -> list[Mapping[str, Any]]:
    """Extract semantic-memory write audit payloads from session events."""

    payloads: list[Mapping[str, Any]] = []
    for event in events:
        payload = _semantic_memory_write_payload_from_event(event)
        if payload is not None:
            payloads.append(payload)
    return payloads


def build_semantic_memory_write_doctor_report(
    payloads: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize semantic-memory writes without raw content or identifiers."""

    items = [payload for payload in payloads if isinstance(payload, Mapping)]
    status_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    org_context_counts: Counter[str] = Counter()
    write_kind_counts: Counter[str] = Counter()

    message_saved_count = 0
    response_saved_count = 0
    fact_extraction_requested_count = 0
    stored_fact_total = 0
    stored_insight_total = 0
    blocked_count = 0
    raw_content_flag_count = 0

    for payload in items:
        write = _plain_mapping(payload.get("write"))
        write_kind_counts[_safe_token(write.get("kind"), fallback="unknown")] += 1
        status = _safe_token(write.get("status"), fallback="unknown")
        status_counts[status] += 1
        if write.get("message_saved") is True:
            message_saved_count += 1
        if write.get("response_saved") is True:
            response_saved_count += 1
        if write.get("fact_extraction_requested") is True:
            fact_extraction_requested_count += 1
        stored_fact_total += _positive_int(write.get("stored_fact_count"))
        stored_insight_total += _positive_int(write.get("stored_insight_count"))

        scope = _plain_mapping(payload.get("scope"))
        org_context_counts[
            _safe_token(scope.get("organization_context"), fallback="unknown")
        ] += 1
        if scope.get("write_allowed") is False or status == "blocked":
            blocked_count += 1

        privacy = _plain_mapping(payload.get("privacy"))
        if privacy.get("raw_content_included") is True:
            raw_content_flag_count += 1

        for warning in payload.get("warnings") or []:
            warning_counts[_safe_token(warning)] += 1

    write_count = len(items)
    failed_count = sum(
        count
        for status, count in status_counts.items()
        if status in {"failed", "error", "exception"}
    )
    degraded_count = status_counts.get("degraded", 0)
    warning_count = sum(warning_counts.values())
    status = "blocked" if write_count == 0 else "degraded" if (
        failed_count or degraded_count or warning_count or raw_content_flag_count
    ) else "ready"

    return {
        "version": SEMANTIC_MEMORY_WRITE_DOCTOR_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "summary": {
            "write_count": write_count,
            "message_saved_count": message_saved_count,
            "response_saved_count": response_saved_count,
            "fact_extraction_requested_count": fact_extraction_requested_count,
            "stored_fact_total": stored_fact_total,
            "stored_insight_total": stored_insight_total,
            "blocked_count": blocked_count,
            "failed_count": failed_count,
            "degraded_count": degraded_count,
            "warning_count": warning_count,
            "raw_content_flag_count": raw_content_flag_count,
        },
        "write_kinds": _counter_dict(write_kind_counts),
        "write_statuses": _counter_dict(status_counts),
        "organization_contexts": _counter_dict(org_context_counts),
        "warnings": _counter_dict(warning_counts),
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
    }


def build_semantic_memory_write_doctor_history_from_events(
    events: Iterable[Any],
    *,
    bucket_limit: int = 24,
) -> dict[str, Any]:
    """Build aggregate semantic-memory write doctor reports per time bucket."""

    buckets: dict[str, dict[str, Any]] = {}
    session_event_count = 0
    write_event_count = 0
    for event in events:
        session_event_count += 1
        payload = _semantic_memory_write_payload_from_event(event)
        if payload is None:
            continue
        write_event_count += 1
        bucket_start = _event_created_at_hour(event)
        bucket = buckets.setdefault(
            bucket_start,
            {
                "bucket_start": bucket_start,
                "payloads": [],
            },
        )
        bucket["payloads"].append(payload)

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        bucket_start = item[0]
        return (0 if bucket_start == "unknown" else 1, bucket_start)

    bounded_bucket_limit = min(max(bucket_limit, 1), 48)
    history_buckets: list[dict[str, Any]] = []
    for bucket_start, bucket in sorted(
        buckets.items(),
        key=_sort_key,
        reverse=True,
    )[:bounded_bucket_limit]:
        payloads = bucket["payloads"]
        report = build_semantic_memory_write_doctor_report(payloads)
        history_buckets.append(
            {
                "bucket_start": bucket_start,
                "status": _safe_token(report.get("status")),
                "summary": report.get("summary", {}),
                "write_kinds": report.get("write_kinds", {}),
                "write_statuses": report.get("write_statuses", {}),
                "organization_contexts": report.get("organization_contexts", {}),
                "warnings": report.get("warnings", {}),
                "source": {
                    "session_event_count": len(payloads),
                    "semantic_memory_write_event_count": len(payloads),
                },
            }
        )

    return {
        "version": SEMANTIC_MEMORY_WRITE_DOCTOR_HISTORY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "bucket_strategy": "event_created_at_hour",
        "identifier_strategy": "aggregate_counts_only",
        "buckets": history_buckets,
        "source": {
            "session_event_count": session_event_count,
            "semantic_memory_write_event_count": write_event_count,
            "bucket_count": len(history_buckets),
            "bucket_limit": bounded_bucket_limit,
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
    }


async def build_recent_semantic_memory_write_doctor_report_from_session_log(
    log: Any,
    *,
    org_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    events = await log.get_recent_events(
        org_id=org_id,
        event_type="semantic_memory_write",
        limit=limit,
    )
    payloads = semantic_memory_write_payloads_from_events(events)
    report = build_semantic_memory_write_doctor_report(payloads)
    report["source"] = {
        "session_event_count": len(events),
        "semantic_memory_write_event_count": len(payloads),
        "limit": limit,
        "org_scoped": org_id is not None,
        "window": "recent_semantic_memory_write_events",
    }
    return report


async def build_semantic_memory_write_doctor_history_from_session_log(
    log: Any,
    *,
    org_id: str | None = None,
    limit: int = 500,
    bucket_limit: int = 24,
) -> dict[str, Any]:
    events = await log.get_recent_events(
        org_id=org_id,
        event_type="semantic_memory_write",
        limit=limit,
    )
    history = build_semantic_memory_write_doctor_history_from_events(
        events,
        bucket_limit=bucket_limit,
    )
    history["source"]["limit"] = limit
    history["source"]["org_scoped"] = org_id is not None
    history["source"]["window"] = "recent_semantic_memory_write_history"
    return history


__all__ = [
    "SEMANTIC_MEMORY_WRITE_DOCTOR_HISTORY_VERSION",
    "SEMANTIC_MEMORY_WRITE_DOCTOR_VERSION",
    "build_recent_semantic_memory_write_doctor_report_from_session_log",
    "build_semantic_memory_write_doctor_history_from_events",
    "build_semantic_memory_write_doctor_history_from_session_log",
    "build_semantic_memory_write_doctor_report",
    "semantic_memory_write_payloads_from_events",
]
