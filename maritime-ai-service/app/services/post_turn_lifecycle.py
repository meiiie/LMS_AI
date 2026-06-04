"""Typed post-turn lifecycle scheduling for raw-response side effects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.engine.runtime.runtime_metrics import inc_counter

POST_TURN_LIFECYCLE_SUMMARY_VERSION = "wiii.post_turn_lifecycle.v1"
POST_TURN_LIFECYCLE_METRICS_REPORT_VERSION = (
    "wiii.post_turn_lifecycle_metrics.v1"
)
BACKGROUND_TASK_SCHEDULE_SUMMARY_SCHEMA = "wiii.background_task_schedule.v1"
POST_TURN_LIFECYCLE_METRIC_NAME = "runtime.post_turn.lifecycle.scheduling"
BACKGROUND_TASK_SCHEDULING_METRIC_NAME = "runtime.background_tasks.scheduling"
_SAFE_LABEL_RE = re.compile(r"[^a-z0-9._:/-]+")
_KNOWN_TRANSPORT_LABELS = frozenset(
    {"api", "desktop", "http", "lms", "stream", "sse", "sync", "tauri", "unknown"}
)


def _safe_label(value: Any, *, fallback: str = "unknown") -> str:
    label = str(value or "").strip().casefold()
    label = _SAFE_LABEL_RE.sub("_", label).strip("_")
    return (label or fallback)[:96]


def _safe_transport_label(value: Any) -> str:
    label = _safe_label(value)
    return label if label in _KNOWN_TRANSPORT_LABELS else "other"


@dataclass(frozen=True, slots=True)
class PostTurnLifecycleContext:
    """Raw post-turn values needed to schedule memory and continuity tasks."""

    background_save: Callable[..., Any] | None
    background_runner: Any
    user_id: str
    session_id: Any
    message: str
    response_text: str
    organization_id: str | None
    transport_type: str
    skip_fact_extraction: bool
    ephemeral_direct_turn: bool


@dataclass(frozen=True, slots=True)
class PostTurnLifecycleScheduleResult:
    """Raw-content-free scheduling summary for operator logs and tests."""

    status: str
    reason: str
    semantic_memory_policy: str
    background_tasks_scheduled: bool
    background_schedule: Mapping[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        summary = {
            "schema_version": POST_TURN_LIFECYCLE_SUMMARY_VERSION,
            "status": self.status,
            "reason": self.reason,
            "semantic_memory_policy": self.semantic_memory_policy,
            "background_tasks_scheduled": self.background_tasks_scheduled,
            "privacy": {
                "raw_content_included": False,
                "identifier_strategy": "status_only",
            },
        }
        if self.background_schedule is not None:
            summary["background_schedule"] = dict(self.background_schedule)
        return summary


def _semantic_memory_policy(*, skip_fact_extraction: bool) -> str:
    return "skip_fact_extraction" if skip_fact_extraction else "extract_facts"


def _emit_post_turn_lifecycle_metric(
    *,
    status: str,
    reason: str,
    transport_type: str,
    semantic_memory_policy: str,
) -> None:
    inc_counter(
        POST_TURN_LIFECYCLE_METRIC_NAME,
        labels={
            "status": _safe_label(status),
            "reason": _safe_label(reason),
            "transport": _safe_transport_label(transport_type),
            "semantic_memory_policy": _safe_label(semantic_memory_policy),
        },
    )


def _result(
    *,
    status: str,
    reason: str,
    transport_type: str,
    semantic_memory_policy: str,
    background_tasks_scheduled: bool,
    background_schedule: Mapping[str, Any] | None = None,
) -> PostTurnLifecycleScheduleResult:
    _emit_post_turn_lifecycle_metric(
        status=status,
        reason=reason,
        transport_type=transport_type,
        semantic_memory_policy=semantic_memory_policy,
    )
    return PostTurnLifecycleScheduleResult(
        status=status,
        reason=reason,
        semantic_memory_policy=semantic_memory_policy,
        background_tasks_scheduled=background_tasks_scheduled,
        background_schedule=background_schedule,
    )


def _background_schedule_summary(schedule_result: Any) -> Mapping[str, Any] | None:
    try:
        from app.services.background_tasks import (
            BACKGROUND_TASK_SCHEDULE_SUMMARY_VERSION,
            BackgroundTaskScheduleSummary,
        )

        if isinstance(schedule_result, BackgroundTaskScheduleSummary):
            if (
                BACKGROUND_TASK_SCHEDULE_SUMMARY_VERSION
                != BACKGROUND_TASK_SCHEDULE_SUMMARY_SCHEMA
            ):
                return None
            summary = schedule_result.to_summary()
            if (
                summary.get("schema_version")
                == BACKGROUND_TASK_SCHEDULE_SUMMARY_VERSION
            ):
                return summary
    except Exception:
        return None
    return None


def schedule_post_turn_background_tasks(
    context: PostTurnLifecycleContext,
) -> Any:
    """Schedule all post-turn background work with lifecycle-owned memory writes."""

    from app.services.background_tasks import (
        BackgroundTaskGroupSchedule,
        BackgroundTaskScheduleSummary,
    )

    groups: list[BackgroundTaskGroupSchedule] = []
    task_count = 0

    def record_group(*, group: str, status: str, reason: str) -> None:
        groups.append(
            BackgroundTaskGroupSchedule(
                group=group,
                status=status,
                reason=reason,
            )
        )
        inc_counter(
            BACKGROUND_TASK_SCHEDULING_METRIC_NAME,
            labels={
                "group": _safe_label(group),
                "status": _safe_label(status),
                "reason": _safe_label(reason),
            },
        )

    semantic_memory = getattr(context.background_runner, "_semantic_memory", None)
    try:
        semantic_memory_available = bool(
            semantic_memory and semantic_memory.is_available()
        )
    except Exception:
        semantic_memory_available = False

    store_interaction = getattr(
        context.background_runner,
        "_store_semantic_interaction",
        None,
    )
    run_maintenance = getattr(
        context.background_runner,
        "_enqueue_or_run_semantic_memory_maintenance",
        None,
    )
    org_id = context.organization_id or ""

    if (
        semantic_memory_available
        and callable(store_interaction)
        and callable(run_maintenance)
    ):
        context.background_save(
            store_interaction,
            context.user_id,
            context.message,
            context.response_text,
            str(context.session_id),
            context.skip_fact_extraction,
            org_id,
        )
        task_count += 1
        record_group(
            group="semantic_memory_interaction",
            status="scheduled",
            reason=(
                "skip_fact_extraction"
                if context.skip_fact_extraction
                else "extract_facts"
            ),
        )
        context.background_save(
            run_maintenance,
            context.user_id,
            str(context.session_id),
            org_id,
        )
        task_count += 1
        record_group(
            group="semantic_memory_maintenance",
            status="scheduled",
            reason="after_interaction_write",
        )
    else:
        reason = (
            "semantic_memory_task_unavailable"
            if semantic_memory_available
            else "semantic_memory_unavailable"
        )
        record_group(
            group="semantic_memory_interaction",
            status="skipped",
            reason=reason,
        )
        record_group(
            group="semantic_memory_maintenance",
            status="skipped",
            reason=reason,
        )

    schedule_non_semantic_tasks = getattr(
        context.background_runner,
        "schedule_non_semantic_tasks",
        None,
    )
    if callable(schedule_non_semantic_tasks):
        non_semantic_summary = schedule_non_semantic_tasks(
            background_save=context.background_save,
            user_id=context.user_id,
            session_id=context.session_id,
            message=context.message,
            response=context.response_text,
            org_id=org_id,
        )
        if isinstance(non_semantic_summary, BackgroundTaskScheduleSummary):
            task_count += non_semantic_summary.task_count
            groups.extend(non_semantic_summary.groups)
    else:
        record_group(
            group="non_semantic_tasks",
            status="skipped",
            reason="missing_background_runner_contract",
        )

    return BackgroundTaskScheduleSummary(
        task_count=task_count,
        groups=tuple(groups),
    )


def _metric_labels_to_dict(label_key: Any) -> dict[str, str]:
    if not label_key:
        return {}
    try:
        items = tuple(label_key)
    except TypeError:
        return {}

    labels: dict[str, str] = {}
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        key, value = item
        labels[str(key)] = str(value)
    return labels


def _metric_counter_bucket(
    metrics_snapshot: Mapping[str, Any], metric_name: str
) -> Mapping[Any, Any]:
    counters = metrics_snapshot.get("counters")
    if not isinstance(counters, Mapping):
        return {}
    bucket = counters.get(metric_name)
    if isinstance(bucket, Mapping):
        return bucket
    return {}


def _counter_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _add_count(counts: dict[str, int], label: str, value: int) -> None:
    if value <= 0:
        return
    counts[label] = counts.get(label, 0) + value


def _sorted_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return {key: counts[key] for key in sorted(counts)}


def _aggregate_post_turn_counter(
    counter: Mapping[Any, Any],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    transport_counts: dict[str, int] = {}
    semantic_memory_policy_counts: dict[str, int] = {}
    event_count = 0

    for label_key, raw_value in counter.items():
        value = _counter_value(raw_value)
        if value <= 0:
            continue
        labels = _metric_labels_to_dict(label_key)
        event_count += value
        _add_count(status_counts, _safe_label(labels.get("status")), value)
        _add_count(reason_counts, _safe_label(labels.get("reason")), value)
        _add_count(
            transport_counts,
            _safe_transport_label(labels.get("transport")),
            value,
        )
        _add_count(
            semantic_memory_policy_counts,
            _safe_label(labels.get("semantic_memory_policy")),
            value,
        )

    return {
        "event_count": event_count,
        "status_counts": _sorted_counts(status_counts),
        "reason_counts": _sorted_counts(reason_counts),
        "transport_counts": _sorted_counts(transport_counts),
        "semantic_memory_policy_counts": _sorted_counts(
            semantic_memory_policy_counts
        ),
    }


def _aggregate_background_task_counter(
    counter: Mapping[Any, Any],
) -> dict[str, Any]:
    group_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    event_count = 0

    for label_key, raw_value in counter.items():
        value = _counter_value(raw_value)
        if value <= 0:
            continue
        labels = _metric_labels_to_dict(label_key)
        event_count += value
        _add_count(group_counts, _safe_label(labels.get("group")), value)
        _add_count(status_counts, _safe_label(labels.get("status")), value)
        _add_count(reason_counts, _safe_label(labels.get("reason")), value)

    return {
        "event_count": event_count,
        "group_counts": _sorted_counts(group_counts),
        "status_counts": _sorted_counts(status_counts),
        "reason_counts": _sorted_counts(reason_counts),
    }


def build_post_turn_lifecycle_metrics_report(
    metrics_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return aggregate, raw-content-free post-turn scheduling evidence."""

    if metrics_snapshot is None:
        from app.engine.runtime.runtime_metrics import snapshot

        metrics_snapshot = snapshot()

    return {
        "version": POST_TURN_LIFECYCLE_METRICS_REPORT_VERSION,
        "post_turn": _aggregate_post_turn_counter(
            _metric_counter_bucket(
                metrics_snapshot,
                POST_TURN_LIFECYCLE_METRIC_NAME,
            )
        ),
        "background_tasks": _aggregate_background_task_counter(
            _metric_counter_bucket(
                metrics_snapshot,
                BACKGROUND_TASK_SCHEDULING_METRIC_NAME,
            )
        ),
        "source": {
            "metrics_backend": "runtime_metrics.snapshot",
            "window": "process_lifetime_in_memory",
            "org_scoped": False,
            "counter_names": {
                "post_turn": POST_TURN_LIFECYCLE_METRIC_NAME,
                "background_tasks": BACKGROUND_TASK_SCHEDULING_METRIC_NAME,
            },
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
    }


def schedule_post_turn_lifecycle(
    context: PostTurnLifecycleContext,
) -> PostTurnLifecycleScheduleResult:
    """Schedule post-turn background tasks through one explicit contract."""

    semantic_memory_policy = _semantic_memory_policy(
        skip_fact_extraction=context.skip_fact_extraction
    )
    if context.ephemeral_direct_turn:
        return _result(
            status="skipped",
            reason="ephemeral_direct_turn",
            transport_type=context.transport_type,
            semantic_memory_policy="not_applicable",
            background_tasks_scheduled=False,
        )
    if context.background_save is None:
        return _result(
            status="skipped",
            reason="missing_background_save",
            transport_type=context.transport_type,
            semantic_memory_policy=semantic_memory_policy,
            background_tasks_scheduled=False,
        )
    if context.background_runner is None:
        return _result(
            status="skipped",
            reason="missing_background_runner",
            transport_type=context.transport_type,
            semantic_memory_policy=semantic_memory_policy,
            background_tasks_scheduled=False,
        )

    try:
        schedule_result = schedule_post_turn_background_tasks(context)
    except Exception:
        _emit_post_turn_lifecycle_metric(
            status="error",
            reason="post_turn_background_tasks_failed",
            transport_type=context.transport_type,
            semantic_memory_policy=semantic_memory_policy,
        )
        raise

    return _result(
        status="scheduled",
        reason="post_turn_background_tasks_scheduled",
        transport_type=context.transport_type,
        semantic_memory_policy=semantic_memory_policy,
        background_tasks_scheduled=True,
        background_schedule=_background_schedule_summary(schedule_result),
    )


__all__ = [
    "POST_TURN_LIFECYCLE_METRICS_REPORT_VERSION",
    "POST_TURN_LIFECYCLE_SUMMARY_VERSION",
    "PostTurnLifecycleContext",
    "PostTurnLifecycleScheduleResult",
    "build_post_turn_lifecycle_metrics_report",
    "schedule_post_turn_background_tasks",
    "schedule_post_turn_lifecycle",
]
