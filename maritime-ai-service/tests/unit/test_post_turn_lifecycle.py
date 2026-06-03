from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.services.background_tasks import (
    BackgroundTaskGroupSchedule,
    BackgroundTaskScheduleSummary,
)
from app.services.post_turn_lifecycle import (
    POST_TURN_LIFECYCLE_METRICS_REPORT_VERSION,
    POST_TURN_LIFECYCLE_SUMMARY_VERSION,
    PostTurnLifecycleContext,
    build_post_turn_lifecycle_metrics_report,
    schedule_post_turn_lifecycle,
)


@pytest.fixture(autouse=True)
def reset_runtime_metrics():
    rm._reset_for_tests()
    yield
    rm._reset_for_tests()


def _runner(
    *,
    semantic_available: bool = True,
    non_semantic_summary: BackgroundTaskScheduleSummary | None = None,
    non_semantic_side_effect: Exception | None = None,
):
    if non_semantic_summary is None:
        non_semantic_summary = BackgroundTaskScheduleSummary(
            task_count=0,
            groups=(),
        )
    schedule_non_semantic_tasks = MagicMock(return_value=non_semantic_summary)
    if non_semantic_side_effect is not None:
        schedule_non_semantic_tasks.side_effect = non_semantic_side_effect
    return SimpleNamespace(
        _semantic_memory=SimpleNamespace(
            is_available=MagicMock(return_value=semantic_available),
        ),
        _store_semantic_interaction=MagicMock(name="_store_semantic_interaction"),
        _enqueue_or_run_semantic_memory_maintenance=MagicMock(
            name="_enqueue_or_run_semantic_memory_maintenance"
        ),
        schedule_non_semantic_tasks=schedule_non_semantic_tasks,
    )


def _context(**overrides):
    values = {
        "background_save": MagicMock(),
        "background_runner": _runner(),
        "user_id": "user-private",
        "session_id": "session-private",
        "message": "PRIVATE PROMPT",
        "response_text": "PRIVATE RESPONSE",
        "organization_id": "org-private",
        "transport_type": "sync",
        "skip_fact_extraction": False,
        "ephemeral_direct_turn": False,
    }
    values.update(overrides)
    return PostTurnLifecycleContext(**values)


def test_schedule_post_turn_lifecycle_owns_raw_semantic_write_scheduling() -> None:
    context = _context()

    result = schedule_post_turn_lifecycle(context)

    assert context.background_save.call_args_list[0].args == (
        context.background_runner._store_semantic_interaction,
        "user-private",
        "PRIVATE PROMPT",
        "PRIVATE RESPONSE",
        "session-private",
        False,
        "org-private",
    )
    assert context.background_save.call_args_list[1].args == (
        context.background_runner._enqueue_or_run_semantic_memory_maintenance,
        "user-private",
        "session-private",
        "org-private",
    )
    context.background_runner.schedule_non_semantic_tasks.assert_called_once_with(
        background_save=context.background_save,
        user_id="user-private",
        session_id="session-private",
        message="PRIVATE PROMPT",
        response="PRIVATE RESPONSE",
        org_id="org-private",
    )
    assert result.background_tasks_scheduled is True
    assert result.status == "scheduled"
    assert result.reason == "post_turn_background_tasks_scheduled"
    assert result.semantic_memory_policy == "extract_facts"
    summary = result.to_summary()
    assert summary["schema_version"] == POST_TURN_LIFECYCLE_SUMMARY_VERSION
    assert summary["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "status_only",
    }
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "PRIVATE PROMPT" not in serialized
    assert "PRIVATE RESPONSE" not in serialized
    assert "user-private" not in serialized
    assert "session-private" not in serialized

    snap = rm.snapshot()
    labels = (
        ("reason", "post_turn_background_tasks_scheduled"),
        ("semantic_memory_policy", "extract_facts"),
        ("status", "scheduled"),
        ("transport", "sync"),
    )
    assert snap["counters"]["runtime.post_turn.lifecycle.scheduling"][labels] == 1


def test_schedule_post_turn_lifecycle_includes_background_schedule_summary() -> None:
    background_summary = BackgroundTaskScheduleSummary(
        task_count=1,
        groups=(
            BackgroundTaskGroupSchedule(
                group="memory_summarizer",
                status="scheduled",
                reason="dependency_available",
            ),
        ),
    )
    context = _context(
        background_runner=_runner(non_semantic_summary=background_summary)
    )

    result = schedule_post_turn_lifecycle(context)

    assert result.to_summary()["background_schedule"] == {
        "schema_version": "wiii.background_task_schedule.v1",
        "task_count": 3,
        "groups": [
            {
                "group": "semantic_memory_interaction",
                "status": "scheduled",
                "reason": "extract_facts",
            },
            {
                "group": "semantic_memory_maintenance",
                "status": "scheduled",
                "reason": "after_interaction_write",
            },
            {
                "group": "memory_summarizer",
                "status": "scheduled",
                "reason": "dependency_available",
            },
        ],
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "status_only",
        },
    }


def test_build_post_turn_lifecycle_metrics_report_is_aggregate_only() -> None:
    background_summary = BackgroundTaskScheduleSummary(
        task_count=1,
        groups=(
            BackgroundTaskGroupSchedule(
                group="semantic_memory_interaction",
                status="scheduled",
                reason="extract_facts",
            ),
        ),
    )
    schedule_post_turn_lifecycle(
        _context(
            background_runner=_runner(non_semantic_summary=background_summary)
        )
    )
    schedule_post_turn_lifecycle(
        _context(
            ephemeral_direct_turn=True,
            message="PRIVATE EPHEMERAL PROMPT",
            response_text="PRIVATE EPHEMERAL RESPONSE",
            transport_type="PRIVATE TRANSPORT VALUE",
        )
    )
    rm.inc_counter(
        "runtime.background_tasks.scheduling",
        labels={
            "group": "semantic_memory_interaction",
            "status": "scheduled",
            "reason": "extract_facts",
        },
    )
    rm.inc_counter(
        "runtime.background_tasks.scheduling",
        labels={
            "group": "memory_summarizer",
            "status": "skipped",
            "reason": "missing_dependency",
        },
    )

    report = build_post_turn_lifecycle_metrics_report()

    assert (
        POST_TURN_LIFECYCLE_METRICS_REPORT_VERSION
        == "wiii.post_turn_lifecycle_metrics.v1"
    )
    assert report["version"] == POST_TURN_LIFECYCLE_METRICS_REPORT_VERSION
    assert report["post_turn"]["event_count"] == 2
    assert report["post_turn"]["status_counts"] == {
        "scheduled": 1,
        "skipped": 1,
    }
    assert report["post_turn"]["reason_counts"] == {
        "ephemeral_direct_turn": 1,
        "post_turn_background_tasks_scheduled": 1,
    }
    assert report["post_turn"]["transport_counts"] == {"other": 1, "sync": 1}
    assert report["post_turn"]["semantic_memory_policy_counts"] == {
        "extract_facts": 1,
        "not_applicable": 1,
    }
    assert report["background_tasks"]["event_count"] == 4
    assert report["background_tasks"]["group_counts"] == {
        "memory_summarizer": 1,
        "semantic_memory_interaction": 2,
        "semantic_memory_maintenance": 1,
    }
    assert report["background_tasks"]["status_counts"] == {
        "scheduled": 3,
        "skipped": 1,
    }
    assert report["source"]["window"] == "process_lifetime_in_memory"
    assert report["source"]["org_scoped"] is False
    assert report["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "aggregate_counts_only",
    }
    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE" not in serialized
    assert "user-private" not in serialized
    assert "session-private" not in serialized


def test_schedule_post_turn_lifecycle_skips_ephemeral_turns() -> None:
    context = _context(ephemeral_direct_turn=True)

    result = schedule_post_turn_lifecycle(context)

    context.background_runner.schedule_non_semantic_tasks.assert_not_called()
    assert result.to_summary() == {
        "schema_version": "wiii.post_turn_lifecycle.v1",
        "status": "skipped",
        "reason": "ephemeral_direct_turn",
        "semantic_memory_policy": "not_applicable",
        "background_tasks_scheduled": False,
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "status_only",
        },
    }
    snap = rm.snapshot()
    labels = (
        ("reason", "ephemeral_direct_turn"),
        ("semantic_memory_policy", "not_applicable"),
        ("status", "skipped"),
        ("transport", "sync"),
    )
    assert snap["counters"]["runtime.post_turn.lifecycle.scheduling"][labels] == 1


def test_schedule_post_turn_lifecycle_reports_missing_background_save() -> None:
    context = _context(background_save=None, skip_fact_extraction=True)

    result = schedule_post_turn_lifecycle(context)

    context.background_runner.schedule_non_semantic_tasks.assert_not_called()
    assert result.background_tasks_scheduled is False
    assert result.reason == "missing_background_save"
    assert result.semantic_memory_policy == "skip_fact_extraction"


def test_schedule_post_turn_lifecycle_emits_error_metric_before_reraising() -> None:
    runner = _runner(non_semantic_side_effect=RuntimeError("down"))
    context = _context(background_runner=runner, transport_type="stream")

    with pytest.raises(RuntimeError, match="down"):
        schedule_post_turn_lifecycle(context)

    snap = rm.snapshot()
    labels = (
        ("reason", "post_turn_background_tasks_failed"),
        ("semantic_memory_policy", "extract_facts"),
        ("status", "error"),
        ("transport", "stream"),
    )
    assert snap["counters"]["runtime.post_turn.lifecycle.scheduling"][labels] == 1
