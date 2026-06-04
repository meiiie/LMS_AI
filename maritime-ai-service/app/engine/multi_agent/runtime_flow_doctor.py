"""Privacy-safe aggregate diagnostics for RuntimeFlowLedger payloads."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any


RUNTIME_FLOW_DOCTOR_VERSION = "wiii.runtime_flow_doctor.v1"
RUNTIME_FLOW_DOCTOR_HISTORY_VERSION = "wiii.runtime_flow_doctor_history.v1"
POST_TURN_LIFECYCLE_LEDGER_REPORT_VERSION = "wiii.post_turn_lifecycle_ledger.v1"
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


def _safe_count(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


def _safe_nonnegative_count(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _request_id_present(ledger: Mapping[str, Any]) -> bool:
    request = _plain_mapping(ledger.get("request"))
    return bool(str(request.get("request_id") or "").strip())


def _provider_call_correlation(ledger: Mapping[str, Any]) -> Mapping[str, Any]:
    external_app = _plain_mapping(ledger.get("external_app"))
    action_trace = _plain_mapping(external_app.get("action_trace"))
    return _plain_mapping(action_trace.get("provider_call_correlation"))


def _post_turn_lifecycle(ledger: Mapping[str, Any]) -> Mapping[str, Any]:
    finalization = _plain_mapping(ledger.get("finalization"))
    return _plain_mapping(finalization.get("post_turn_lifecycle"))


def _alert(
    code: str,
    *,
    count: int,
    severity: str = "warning",
    threshold: str = "count>0",
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "count": count,
        "threshold": threshold,
    }


def _aggregate_post_turn_lifecycle_ledger(
    ledgers: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    semantic_memory_policy_counts: Counter[str] = Counter()
    background_group_counts: Counter[str] = Counter()
    background_status_counts: Counter[str] = Counter()
    background_reason_counts: Counter[str] = Counter()

    event_count = 0
    missing_count = 0
    background_tasks_scheduled_count = 0
    background_tasks_skipped_count = 0
    background_schedule_event_count = 0
    background_task_count = 0
    raw_content_flag_count = 0

    for ledger in ledgers:
        if not isinstance(ledger, Mapping):
            continue
        lifecycle = _post_turn_lifecycle(ledger)
        if not lifecycle:
            missing_count += 1
            continue

        event_count += 1
        status_counts[_safe_token(lifecycle.get("status"))] += 1
        reason_counts[_safe_token(lifecycle.get("reason"))] += 1
        semantic_memory_policy_counts[
            _safe_token(lifecycle.get("semantic_memory_policy"))
        ] += 1

        if lifecycle.get("background_tasks_scheduled") is True:
            background_tasks_scheduled_count += 1
        elif lifecycle.get("background_tasks_scheduled") is False:
            background_tasks_skipped_count += 1

        privacy = _plain_mapping(lifecycle.get("privacy"))
        if privacy.get("raw_content_included") is True:
            raw_content_flag_count += 1

        background_schedule = _plain_mapping(lifecycle.get("background_schedule"))
        if not background_schedule:
            continue

        background_schedule_event_count += 1
        background_task_count += _safe_nonnegative_count(
            background_schedule.get("task_count")
        )
        background_privacy = _plain_mapping(background_schedule.get("privacy"))
        if background_privacy.get("raw_content_included") is True:
            raw_content_flag_count += 1

        groups = background_schedule.get("groups")
        if not isinstance(groups, list):
            continue
        for group_value in groups:
            group = _plain_mapping(group_value)
            if not group:
                continue
            background_group_counts[_safe_token(group.get("group"))] += 1
            background_status_counts[_safe_token(group.get("status"))] += 1
            background_reason_counts[_safe_token(group.get("reason"))] += 1

    return {
        "version": POST_TURN_LIFECYCLE_LEDGER_REPORT_VERSION,
        "event_count": event_count,
        "missing_count": missing_count,
        "status_counts": _counter_dict(status_counts),
        "reason_counts": _counter_dict(reason_counts),
        "semantic_memory_policy_counts": _counter_dict(
            semantic_memory_policy_counts
        ),
        "background_tasks_scheduled_count": background_tasks_scheduled_count,
        "background_tasks_skipped_count": background_tasks_skipped_count,
        "raw_content_flag_count": raw_content_flag_count,
        "background_schedule": {
            "event_count": background_schedule_event_count,
            "task_count": background_task_count,
            "group_counts": _counter_dict(background_group_counts),
            "status_counts": _counter_dict(background_status_counts),
            "reason_counts": _counter_dict(background_reason_counts),
        },
        "source": {
            "ledger_path": "finalization.post_turn_lifecycle",
            "window": "runtime_flow_ledger_events",
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
    }


def _runtime_flow_ledger_from_event(event: Any) -> Mapping[str, Any] | None:
    if isinstance(event, Mapping):
        payload = _plain_mapping(event.get("payload", event))
    else:
        payload = _plain_mapping(getattr(event, "payload", None))
    ledger = payload.get("runtime_flow_ledger") or payload.get("ledger")
    if isinstance(ledger, Mapping):
        return ledger
    content = _plain_mapping(payload.get("content"))
    ledger = content.get("runtime_flow_ledger")
    return ledger if isinstance(ledger, Mapping) else None


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


def runtime_flow_ledgers_from_events(events: Iterable[Any]) -> list[Mapping[str, Any]]:
    """Extract RuntimeFlowLedger payloads from durable session events."""

    ledgers: list[Mapping[str, Any]] = []
    for event in events:
        ledger = _runtime_flow_ledger_from_event(event)
        if ledger is not None:
            ledgers.append(ledger)
    return ledgers


def build_runtime_flow_alert_trend_from_events(
    events: Iterable[Any],
) -> dict[str, Any]:
    """Bucket recent runtime-flow alert codes without exposing identifiers."""

    buckets: dict[str, dict[str, Any]] = {}
    for event in events:
        ledger = _runtime_flow_ledger_from_event(event)
        if ledger is None:
            continue
        bucket_start = _event_created_at_hour(event)
        bucket = buckets.setdefault(
            bucket_start,
            {
                "bucket_start": bucket_start,
                "turn_count": 0,
                "alert_counts": Counter(),
                "status_counts": Counter(),
            },
        )
        bucket["turn_count"] += 1
        report = build_runtime_flow_doctor_report([ledger])
        bucket["status_counts"][_safe_token(report.get("status"))] += 1
        for alert in report.get("alerts") or []:
            if not isinstance(alert, Mapping):
                continue
            code = _safe_token(alert.get("code"))
            bucket["alert_counts"][code] += max(1, _safe_count(alert.get("count")))

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        bucket_start = item[0]
        return (0 if bucket_start == "unknown" else 1, bucket_start)

    return {
        "bucket_strategy": "event_created_at_hour",
        "identifier_strategy": "aggregate_counts_only",
        "buckets": [
            {
                "bucket_start": bucket["bucket_start"],
                "turn_count": bucket["turn_count"],
                "alert_counts": _counter_dict(bucket["alert_counts"]),
                "status_counts": _counter_dict(bucket["status_counts"]),
            }
            for _bucket_start, bucket in sorted(
                buckets.items(),
                key=_sort_key,
                reverse=True,
            )
        ],
    }


def build_runtime_flow_doctor_history_from_events(
    events: Iterable[Any],
    *,
    bucket_limit: int = 24,
) -> dict[str, Any]:
    """Build aggregate doctor reports per recent time bucket."""

    buckets: dict[str, dict[str, Any]] = {}
    session_event_count = 0
    ledger_event_count = 0
    all_ledgers: list[Mapping[str, Any]] = []
    for event in events:
        session_event_count += 1
        ledger = _runtime_flow_ledger_from_event(event)
        if ledger is None:
            continue
        ledger_event_count += 1
        all_ledgers.append(ledger)
        bucket_start = _event_created_at_hour(event)
        bucket = buckets.setdefault(
            bucket_start,
            {
                "bucket_start": bucket_start,
                "events": [],
            },
        )
        bucket["events"].append(event)

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        bucket_start = item[0]
        return (0 if bucket_start == "unknown" else 1, bucket_start)

    bucket_items = sorted(buckets.items(), key=_sort_key, reverse=True)
    bounded_bucket_limit = min(max(bucket_limit, 1), 48)
    history_buckets: list[dict[str, Any]] = []
    for bucket_start, bucket in bucket_items[:bounded_bucket_limit]:
        bucket_events = bucket["events"]
        ledgers = runtime_flow_ledgers_from_events(bucket_events)
        report = build_runtime_flow_doctor_report(ledgers)
        history_buckets.append(
            {
                "bucket_start": bucket_start,
                "status": _safe_token(report.get("status")),
                "alerts": report.get("alerts", []),
                "summary": report.get("summary", {}),
                "request_correlation": report.get("request_correlation", {}),
                "subagents": report.get("subagents", {}),
                "routes": report.get("routes", {}),
                "finalization_statuses": report.get("finalization_statuses", {}),
                "post_turn_lifecycle_ledger": report.get(
                    "post_turn_lifecycle_ledger",
                    {},
                ),
                "context_warnings": report.get("context_warnings", {}),
                "source": {
                    "session_event_count": len(bucket_events),
                    "runtime_flow_ledger_event_count": len(ledgers),
                },
            }
        )

    return {
        "version": RUNTIME_FLOW_DOCTOR_HISTORY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "bucket_strategy": "event_created_at_hour",
        "identifier_strategy": "aggregate_counts_only",
        "buckets": history_buckets,
        "post_turn_lifecycle_ledger": _aggregate_post_turn_lifecycle_ledger(
            all_ledgers,
        ),
        "source": {
            "session_event_count": session_event_count,
            "runtime_flow_ledger_event_count": ledger_event_count,
            "bucket_count": len(history_buckets),
            "bucket_limit": bounded_bucket_limit,
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
    }


async def build_runtime_flow_doctor_report_from_session_log(
    log: Any,
    *,
    session_id: str,
    org_id: str | None = None,
    since_seq: int | None = None,
) -> dict[str, Any]:
    """Build a doctor report from one org-scoped durable session window."""

    events = await log.get_events(
        session_id=session_id,
        org_id=org_id,
        since_seq=since_seq,
    )
    ledgers = runtime_flow_ledgers_from_events(events)
    report = build_runtime_flow_doctor_report(ledgers)
    report["alert_trend"] = build_runtime_flow_alert_trend_from_events(events)
    report["source"] = {
        "session_event_count": len(events),
        "runtime_flow_ledger_event_count": len(ledgers),
        "since_seq": since_seq,
        "org_scoped": org_id is not None,
    }
    return report


async def build_recent_runtime_flow_doctor_report_from_session_log(
    log: Any,
    *,
    org_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Build a recent doctor report without exposing session identifiers."""

    events = await log.get_recent_events(
        org_id=org_id,
        event_type="runtime_flow_ledger",
        limit=limit,
    )
    ledgers = runtime_flow_ledgers_from_events(events)
    report = build_runtime_flow_doctor_report(ledgers)
    report["alert_trend"] = build_runtime_flow_alert_trend_from_events(events)
    report["source"] = {
        "session_event_count": len(events),
        "runtime_flow_ledger_event_count": len(ledgers),
        "limit": limit,
        "org_scoped": org_id is not None,
        "window": "recent_runtime_flow_ledger_events",
    }
    return report


async def build_runtime_flow_doctor_history_from_session_log(
    log: Any,
    *,
    org_id: str | None = None,
    limit: int = 500,
    bucket_limit: int = 24,
) -> dict[str, Any]:
    """Build recent aggregate doctor history without exposing session IDs."""

    events = await log.get_recent_events(
        org_id=org_id,
        event_type="runtime_flow_ledger",
        limit=limit,
    )
    history = build_runtime_flow_doctor_history_from_events(
        events,
        bucket_limit=bucket_limit,
    )
    history["source"]["limit"] = limit
    history["source"]["org_scoped"] = org_id is not None
    history["source"]["window"] = "recent_runtime_flow_ledger_history"
    return history


def build_runtime_flow_doctor_report(
    ledgers: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize recent runtime ledgers without raw turn content or identifiers."""

    items = [ledger for ledger in ledgers if isinstance(ledger, Mapping)]
    route_counts: Counter[str] = Counter()
    finalization_counts: Counter[str] = Counter()
    suppressed_tool_counts: Counter[str] = Counter()
    observed_tool_counts: Counter[str] = Counter()
    context_warning_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()

    done_seen_count = 0
    metadata_seen_count = 0
    uploaded_document_turns = 0
    memory_context_turns = 0
    source_ref_total = 0
    context_provenance_turns = 0
    raw_content_flag_count = 0
    request_id_present_count = 0
    provider_call_turn_count = 0
    provider_call_correlated_turn_count = 0
    provider_call_stage_count = 0
    provider_call_stage_request_id_present_count = 0
    provider_call_stage_request_id_missing_count = 0
    provider_call_stage_request_id_match_count = 0
    provider_call_stage_request_id_mismatch_count = 0
    subagent_turn_count = 0
    subagent_report_count = 0
    subagent_state_projected_key_count = 0
    subagent_state_dropped_key_count = 0
    subagent_source_count = 0
    subagent_tool_count = 0
    subagent_thinking_dropped_count = 0
    subagent_raw_content_flag_count = 0
    subagent_warning_counts: Counter[str] = Counter()

    for ledger in items:
        if _request_id_present(ledger):
            request_id_present_count += 1

        route = _plain_mapping(ledger.get("route"))
        decision = _plain_mapping(route.get("turn_path_decision"))
        route_counts[
            _safe_token(route.get("lane") or decision.get("path"))
        ] += 1

        finalization = _plain_mapping(ledger.get("finalization"))
        finalization_counts[_safe_token(finalization.get("status"), fallback="pending")] += 1

        stream = _plain_mapping(ledger.get("stream"))
        if stream.get("done_seen") is True:
            done_seen_count += 1
        if stream.get("metadata_seen") is True:
            metadata_seen_count += 1
        event_count_map = _plain_mapping(stream.get("event_counts"))
        for event_name, count in event_count_map.items():
            event_counts[_safe_token(event_name)] += _safe_count(count)

        tools = _plain_mapping(ledger.get("tools"))
        for tool_name in tools.get("suppressed") or []:
            suppressed_tool_counts[_safe_token(tool_name)] += 1
        for tool_name in tools.get("observed") or []:
            observed_tool_counts[_safe_token(tool_name)] += 1

        context = _plain_mapping(ledger.get("context"))
        uploaded_documents = _safe_count(context.get("uploaded_document_count"))
        if uploaded_documents > 0:
            uploaded_document_turns += 1
        memory_count = _safe_count(context.get("memory_context_count"))
        if memory_count > 0:
            memory_context_turns += 1
        source_ref_total += _safe_count(context.get("source_ref_count"))

        provenance = _plain_mapping(context.get("context_provenance"))
        if provenance:
            context_provenance_turns += 1
        privacy = _plain_mapping(provenance.get("privacy"))
        if privacy.get("raw_content_included") is True:
            raw_content_flag_count += 1
        for warning in provenance.get("warnings") or []:
            context_warning_counts[_safe_token(warning)] += 1

        correlation = _provider_call_correlation(ledger)
        if correlation.get("provider_call_seen") is True:
            provider_call_turn_count += 1
            stage_count = _safe_count(correlation.get("stage_count"))
            stage_present_count = _safe_count(
                correlation.get("stage_request_id_present_count")
            )
            stage_missing_count = _safe_count(
                correlation.get("stage_request_id_missing_count")
            )
            stage_mismatch_count = _safe_count(
                correlation.get("stage_request_id_mismatch_count")
            )
            provider_call_stage_count += stage_count
            provider_call_stage_request_id_present_count += stage_present_count
            provider_call_stage_request_id_missing_count += stage_missing_count
            provider_call_stage_request_id_match_count += _safe_count(
                correlation.get("stage_request_id_match_count")
            )
            provider_call_stage_request_id_mismatch_count += stage_mismatch_count
            if (
                stage_count > 0
                and stage_present_count == stage_count
                and stage_missing_count == 0
                and stage_mismatch_count == 0
                and correlation.get("request_id_present") is True
            ):
                provider_call_correlated_turn_count += 1

        subagents = _plain_mapping(ledger.get("subagents"))
        reports = subagents.get("reports") if isinstance(subagents.get("reports"), list) else []
        report_count = _safe_nonnegative_count(subagents.get("report_count")) or len(
            reports
        )
        if report_count > 0 or reports:
            subagent_turn_count += 1
        subagent_report_count += report_count
        if subagents.get("raw_content_included") is True:
            subagent_raw_content_flag_count += 1
        for warning in subagents.get("warning_codes") or []:
            subagent_warning_counts[_safe_token(warning)] += 1
        for report in reports:
            report_map = _plain_mapping(report)
            subagent_state_projected_key_count += _safe_nonnegative_count(
                report_map.get("state_projected_key_count")
            )
            subagent_state_dropped_key_count += _safe_nonnegative_count(
                report_map.get("state_dropped_key_count")
            )
            subagent_source_count += _safe_nonnegative_count(
                report_map.get("source_count")
            )
            subagent_tool_count += _safe_nonnegative_count(report_map.get("tool_count"))
            if report_map.get("thinking_dropped") is True:
                subagent_thinking_dropped_count += 1

    post_turn_lifecycle_ledger = _aggregate_post_turn_lifecycle_ledger(items)
    post_turn_lifecycle_raw_content_flag_count = _safe_nonnegative_count(
        post_turn_lifecycle_ledger.get("raw_content_flag_count")
    )
    turn_count = len(items)
    missing_done_count = turn_count - done_seen_count
    missing_request_id_count = turn_count - request_id_present_count
    warning_count = sum(context_warning_counts.values())
    failed_finalization_count = sum(
        count
        for status, count in finalization_counts.items()
        if status in {"error", "failed", "exception"}
    )
    provider_call_uncorrelated_turn_count = (
        provider_call_turn_count - provider_call_correlated_turn_count
    )
    subagent_warning_count = sum(subagent_warning_counts.values())
    alerts: list[dict[str, Any]] = []
    if turn_count == 0:
        alerts.append(
            _alert(
                "runtime_flow_ledger_missing",
                count=0,
                severity="critical",
                threshold="turn_count==0",
            )
        )
    if missing_request_id_count:
        alerts.append(_alert("missing_request_id", count=missing_request_id_count))
    if missing_done_count:
        alerts.append(
            _alert("missing_done_event", count=missing_done_count, severity="error")
        )
    if failed_finalization_count:
        alerts.append(
            _alert(
                "failed_finalization",
                count=failed_finalization_count,
                severity="error",
            )
        )
    if raw_content_flag_count:
        alerts.append(
            _alert(
                "raw_content_flag",
                count=raw_content_flag_count,
                severity="critical",
            )
        )
    if warning_count:
        alerts.append(_alert("context_warning", count=warning_count))
    if provider_call_stage_request_id_missing_count:
        alerts.append(
            _alert(
                "provider_call_stage_request_id_missing",
                count=provider_call_stage_request_id_missing_count,
                severity="error",
            )
        )
    if provider_call_stage_request_id_mismatch_count:
        alerts.append(
            _alert(
                "provider_call_stage_request_id_mismatch",
                count=provider_call_stage_request_id_mismatch_count,
                severity="critical",
            )
        )
    if subagent_raw_content_flag_count:
        alerts.append(
            _alert(
                "subagent_boundary_raw_content_flag",
                count=subagent_raw_content_flag_count,
                severity="critical",
            )
        )
    if subagent_warning_count:
        alerts.append(
            _alert(
                "subagent_boundary_warning",
                count=subagent_warning_count,
            )
        )
    if post_turn_lifecycle_raw_content_flag_count:
        alerts.append(
            _alert(
                "post_turn_lifecycle_raw_content_flag",
                count=post_turn_lifecycle_raw_content_flag_count,
                severity="critical",
            )
        )
    status = "blocked" if turn_count == 0 else "degraded" if (
        missing_request_id_count
        or missing_done_count
        or failed_finalization_count
        or raw_content_flag_count
        or warning_count
        or provider_call_stage_request_id_missing_count
        or provider_call_stage_request_id_mismatch_count
        or subagent_raw_content_flag_count
        or subagent_warning_count
        or post_turn_lifecycle_raw_content_flag_count
    ) else "ready"

    return {
        "version": RUNTIME_FLOW_DOCTOR_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "alerts": alerts,
        "summary": {
            "turn_count": turn_count,
            "done_seen_count": done_seen_count,
            "missing_done_count": missing_done_count,
            "metadata_seen_count": metadata_seen_count,
            "uploaded_document_turns": uploaded_document_turns,
            "memory_context_turns": memory_context_turns,
            "source_ref_total": source_ref_total,
            "context_provenance_turns": context_provenance_turns,
            "context_warning_count": warning_count,
            "failed_finalization_count": failed_finalization_count,
            "raw_content_flag_count": raw_content_flag_count,
            "post_turn_lifecycle_event_count": _safe_nonnegative_count(
                post_turn_lifecycle_ledger.get("event_count")
            ),
            "post_turn_lifecycle_missing_count": _safe_nonnegative_count(
                post_turn_lifecycle_ledger.get("missing_count")
            ),
            "post_turn_lifecycle_raw_content_flag_count": (
                post_turn_lifecycle_raw_content_flag_count
            ),
        },
        "request_correlation": {
            "request_id_present_count": request_id_present_count,
            "missing_request_id_count": missing_request_id_count,
            "provider_call_turn_count": provider_call_turn_count,
            "provider_call_correlated_turn_count": (
                provider_call_correlated_turn_count
            ),
            "provider_call_uncorrelated_turn_count": (
                provider_call_uncorrelated_turn_count
            ),
            "provider_call_stage_count": provider_call_stage_count,
            "provider_call_stage_request_id_present_count": (
                provider_call_stage_request_id_present_count
            ),
            "provider_call_stage_request_id_missing_count": (
                provider_call_stage_request_id_missing_count
            ),
            "provider_call_stage_request_id_match_count": (
                provider_call_stage_request_id_match_count
            ),
            "provider_call_stage_request_id_mismatch_count": (
                provider_call_stage_request_id_mismatch_count
            ),
            "identifier_strategy": "presence_counts_only",
        },
        "subagents": {
            "turn_count": subagent_turn_count,
            "report_count": subagent_report_count,
            "state_projected_key_count": subagent_state_projected_key_count,
            "state_dropped_key_count": subagent_state_dropped_key_count,
            "source_count": subagent_source_count,
            "tool_count": subagent_tool_count,
            "thinking_dropped_count": subagent_thinking_dropped_count,
            "raw_content_flag_count": subagent_raw_content_flag_count,
            "warning_count": subagent_warning_count,
            "warnings": _counter_dict(subagent_warning_counts),
            "identifier_strategy": "aggregate_counts_only",
        },
        "routes": _counter_dict(route_counts),
        "finalization_statuses": _counter_dict(finalization_counts),
        "post_turn_lifecycle_ledger": post_turn_lifecycle_ledger,
        "stream_events": _counter_dict(event_counts),
        "suppressed_tools": _counter_dict(suppressed_tool_counts),
        "observed_tools": _counter_dict(observed_tool_counts),
        "context_warnings": _counter_dict(context_warning_counts),
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
    }


__all__ = [
    "POST_TURN_LIFECYCLE_LEDGER_REPORT_VERSION",
    "RUNTIME_FLOW_DOCTOR_HISTORY_VERSION",
    "RUNTIME_FLOW_DOCTOR_VERSION",
    "build_runtime_flow_alert_trend_from_events",
    "build_runtime_flow_doctor_history_from_events",
    "build_runtime_flow_doctor_history_from_session_log",
    "build_recent_runtime_flow_doctor_report_from_session_log",
    "build_runtime_flow_doctor_report",
    "build_runtime_flow_doctor_report_from_session_log",
    "runtime_flow_ledgers_from_events",
]
