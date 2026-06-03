from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_scheduled_task_replay.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_scheduled_task_replay",
    SCRIPT_PATH,
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


def _args(**overrides):
    values = {
        "allow_write": False,
        "allow_production": False,
        "keep_task": False,
        "verbose": False,
        "user_id": "scheduled-probe-user",
        "organization_id": "org-A",
        "domain_id": "maritime",
        "session_id": "scheduled-probe-session",
        "description": "Probe reminder",
        "delay_seconds": 0.1,
        "settle_seconds": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeResult:
    rowcount = 1


class _FakeSession:
    def __init__(self) -> None:
        self.calls = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _FakeResult()

    def commit(self) -> None:
        self.committed = True


def test_live_scheduler_probe_guard_requires_allow_write(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-write"):
        probe._require_live_write(_args())


def test_live_scheduler_probe_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_write(_args(allow_write=True))


def test_live_scheduler_probe_guard_rejects_production_without_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_write(_args(allow_write=True))


def test_live_scheduler_probe_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_write(_args(allow_write=True, allow_production=True))


def test_extract_task_id_parses_uuid_and_rejects_missing_id():
    task_id = "123e4567-e89b-12d3-a456-426614174000"

    assert probe._extract_task_id(f"scheduled task created: {task_id}") == task_id
    with pytest.raises(RuntimeError, match="Could not parse task id"):
        probe._extract_task_id("scheduled task created without identifier")


def test_delete_task_row_is_org_scoped_and_committed():
    fake_session = _FakeSession()

    deleted = probe._delete_task_row(
        lambda: fake_session,
        "123e4567-e89b-12d3-a456-426614174000",
        "org-A",
    )

    assert deleted is True
    assert fake_session.committed is True
    statement, params = fake_session.calls[0]
    assert "DELETE FROM scheduled_tasks" in statement
    assert "organization_id = :organization_id" in statement
    assert params["organization_id"] == "org-A"


def test_cleanup_summary_is_hash_count_only():
    summary = probe._cleanup_summary(
        requested=True,
        deleted=True,
        task_id="123e4567-e89b-12d3-a456-426614174000",
    )

    assert summary["requested"] is True
    assert summary["deleted"] is True
    assert summary["task_id_hash_present"] is True
    assert summary["raw_task_id_included"] is False
    assert summary["raw_organization_identifier_included"] is False
    assert summary["identifier_strategy"] == "hash_only"
    assert "123e4567" not in str(summary)


def test_scheduler_metric_helpers_report_worker_counts():
    metrics = {
        "counters": {
            "runtime.scheduled_tasks.polls": {
                (("status", "success"),): 1,
            },
            "runtime.scheduled_tasks.due": {
                (): 1,
            },
            "runtime.scheduled_tasks.runs": {
                (("mode", "notification"), ("status", "success")): 1,
            },
            "runtime.scheduled_tasks.delivery": {
                (("mode", "notification"), ("status", "delivered")): 1,
            },
        },
        "histograms": {
            "runtime.scheduled_tasks.duration_ms": {
                (("mode", "notification"), ("status", "success")): [12.0],
            },
        },
    }

    assert probe._metric_event_count(metrics, "runtime.scheduled_tasks.due") == 1
    assert probe._metric_label_seen(
        metrics,
        "runtime.scheduled_tasks.runs",
        expected={"mode": "notification", "status": "success"},
    )
    assert (
        probe._metric_label_count(
            metrics,
            "runtime.scheduled_tasks.delivery",
            expected={"mode": "notification", "status": "delivered"},
        )
        == 1
    )
    assert (
        probe._histogram_label_count(
            metrics,
            "runtime.scheduled_tasks.duration_ms",
            expected={"mode": "notification", "status": "success"},
        )
        == 1
    )


def test_scheduler_replay_summary_rejects_raw_description_flag():
    summary = {
        "status": "pass",
        "scope": {
            "user_id_hash_present": True,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
            "request_org_context_set": True,
        },
        "database": {
            "task_id_hash_present": True,
            "created_row_org_hash_present": True,
            "created_row_matches_scope": True,
            "completed_row_present": True,
            "completed_last_run_present": True,
            "completed_next_run_is_null": True,
        },
        "clock": {
            "due_poll_seen": True,
            "due_poll_scoped": True,
            "due_poll_allow_all_orgs": False,
            "due_task_found_by_hash": True,
        },
        "execution": {
            "description_hash_present": True,
            "response_hash_present": True,
            "response_matches_description": True,
            "raw_description_included": True,
        },
        "delivery": {
            "delivered": True,
            "socket_accepted": True,
            "payload_task_id_hash_present": True,
            "payload_task_id_matches_created": True,
            "payload_content_hash_present": True,
            "payload_content_matches_response_hash": True,
            "payload_raw_content_included": False,
        },
        "replay_contract": {
            "uses_scheduler_tool": True,
            "uses_scoped_repository_poll": True,
            "executor_observability_path_used": True,
            "websocket_adapter_delivery_used": True,
            "single_created_task_executed": True,
            "cleanup_required_by_default": True,
            "hash_count_only_output": True,
            "raw_scheduler_tool_result_included": False,
        },
        "database_lifecycle_contract": {
            "created_active_before_execution": True,
            "created_row_org_hash_present": True,
            "created_row_matches_scope": True,
            "completed_row_present": True,
            "completed_status_final": True,
            "created_to_completed_transition": True,
            "completed_run_count_positive": True,
            "completed_last_run_present": True,
            "completed_next_run_is_null": True,
            "completed_org_hash_matches_created": True,
            "raw_database_row_included": False,
        },
        "delivery_contract": {
            "websocket_channel_used": True,
            "scheduled_task_payload_used": True,
            "notification_mode_used": True,
            "socket_delivery_count_positive": True,
            "payload_task_hash_matches_created": True,
            "payload_content_hash_matches_response": True,
            "raw_delivery_payload_included": False,
        },
        "metrics": {
            "poll_success_count": 1,
            "poll_success_seen": True,
            "due_event_count": 1,
            "runs_event_count": 1,
            "run_success_count": 1,
            "run_success_seen": True,
            "delivery_event_count": 1,
            "delivery_delivered_count": 1,
            "delivery_delivered_seen": True,
            "duration_event_count": 1,
            "duration_success_count": 1,
            "duration_success_seen": True,
            "raw_metric_payload_included": False,
        },
        "cleanup": {
            "requested": True,
            "deleted": True,
            "raw_task_id_included": False,
            "raw_organization_identifier_included": False,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_task_id_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_description_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "raw_database_row_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }

    with pytest.raises(RuntimeError, match="raw_description_included"):
        probe._assert_scheduler_replay_summary(summary)


def test_scheduler_replay_summary_rejects_unscoped_replay_contract():
    summary = _valid_scheduler_summary_for_assertion()
    summary["replay_contract"]["uses_scoped_repository_poll"] = False

    with pytest.raises(RuntimeError, match="replay_contract.uses_scoped_repository_poll"):
        probe._assert_scheduler_replay_summary(summary)


def test_scheduler_replay_summary_rejects_database_lifecycle_drift():
    summary = _valid_scheduler_summary_for_assertion()
    summary["database_lifecycle_contract"]["created_to_completed_transition"] = False

    with pytest.raises(
        RuntimeError,
        match="database_lifecycle_contract.created_to_completed_transition",
    ):
        probe._assert_scheduler_replay_summary(summary)


def test_failure_payload_redacts_task_scope_description_and_secret_fields():
    task_id = "123e4567-e89b-12d3-a456-426614174000"
    args = _args(
        user_id="scheduled-live-replay-user",
        session_id="scheduled-live-replay-session",
        organization_id="org-private-scheduler",
        description="Private scheduler replay description",
    )

    payload = probe._failure_payload(
        RuntimeError(
            "failed task "
            f"{task_id} "
            "scheduled-live-replay-user "
            "scheduled-live-replay-session "
            "org-private-scheduler "
            "Private scheduler replay description "
            "access_token api_key authorization"
        ),
        args,
    )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "scheduler_replay_failed"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_task_id_included"] is False
    assert payload["privacy"]["raw_description_included"] is False
    assert task_id not in rendered
    assert "scheduled-live-replay-user" not in rendered
    assert "scheduled-live-replay-session" not in rendered
    assert "org-private-scheduler" not in rendered
    assert "Private scheduler replay description" not in rendered
    assert "access_token" not in rendered
    assert "api_key" not in rendered
    assert "authorization" not in rendered


def _valid_scheduler_summary_for_assertion():
    return {
        "status": "pass",
        "scope": {
            "user_id_hash_present": True,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
            "request_org_context_set": True,
        },
        "database": {
            "task_id_hash_present": True,
            "created_row_org_hash_present": True,
            "created_row_matches_scope": True,
            "completed_row_present": True,
            "completed_last_run_present": True,
            "completed_next_run_is_null": True,
        },
        "clock": {
            "due_poll_seen": True,
            "due_poll_scoped": True,
            "due_poll_allow_all_orgs": False,
            "due_task_found_by_hash": True,
        },
        "execution": {
            "description_hash_present": True,
            "response_hash_present": True,
            "response_matches_description": True,
            "raw_description_included": False,
        },
        "delivery": {
            "delivered": True,
            "socket_accepted": True,
            "payload_task_id_hash_present": True,
            "payload_task_id_matches_created": True,
            "payload_content_hash_present": True,
            "payload_content_matches_response_hash": True,
            "payload_raw_content_included": False,
        },
        "replay_contract": {
            "uses_scheduler_tool": True,
            "uses_scoped_repository_poll": True,
            "executor_observability_path_used": True,
            "websocket_adapter_delivery_used": True,
            "single_created_task_executed": True,
            "cleanup_required_by_default": True,
            "hash_count_only_output": True,
            "raw_scheduler_tool_result_included": False,
        },
        "database_lifecycle_contract": {
            "created_active_before_execution": True,
            "created_row_org_hash_present": True,
            "created_row_matches_scope": True,
            "completed_row_present": True,
            "completed_status_final": True,
            "created_to_completed_transition": True,
            "completed_run_count_positive": True,
            "completed_last_run_present": True,
            "completed_next_run_is_null": True,
            "completed_org_hash_matches_created": True,
            "raw_database_row_included": False,
        },
        "delivery_contract": {
            "websocket_channel_used": True,
            "scheduled_task_payload_used": True,
            "notification_mode_used": True,
            "socket_delivery_count_positive": True,
            "payload_task_hash_matches_created": True,
            "payload_content_hash_matches_response": True,
            "raw_delivery_payload_included": False,
        },
        "metrics": {
            "poll_success_count": 1,
            "poll_success_seen": True,
            "due_event_count": 1,
            "runs_event_count": 1,
            "run_success_count": 1,
            "run_success_seen": True,
            "delivery_event_count": 1,
            "delivery_delivered_count": 1,
            "delivery_delivered_seen": True,
            "duration_event_count": 1,
            "duration_success_count": 1,
            "duration_success_seen": True,
            "raw_metric_payload_included": False,
        },
        "cleanup": {
            "requested": True,
            "deleted": True,
            "raw_task_id_included": False,
            "raw_organization_identifier_included": False,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_task_id_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_description_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "raw_database_row_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def test_scheduler_probe_contract_has_schema_and_hash_count_privacy_tokens():
    assert probe.SCHEMA_VERSION == "wiii.live_scheduler_replay_probe.v1"
    assert probe.ENV_FLAG == "WIII_LIVE_SCHEDULER_REPLAY"
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "cleanup" in source
    assert "task_id_hash_present" in source
    assert "payload_task_id_hash_present" in source
    assert "_execute_due_task_with_observability" in source
    assert "due_poll_allow_all_orgs" in source
    assert "poll_success_seen" in source
    assert "duration_success_seen" in source
    assert "scheduler_replay_contract" in source
    assert "scheduler_database_lifecycle_contract" in source
    assert "scheduler_delivery_contract" in source
    assert "raw_delivery_payload_included" in source
