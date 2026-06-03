from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2]
    / "scripts"
    / "probe_live_semantic_memory_write_doctor.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_semantic_memory_write_doctor",
    SCRIPT_PATH,
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


def _args(**overrides):
    values = {
        "allow_run": True,
        "allow_production": False,
        "user_id": "unit-user-semantic-private",
        "organization_id": "unit-org-semantic-private",
        "session_id": "unit-session-semantic-private",
        "request_id": "unit-request-semantic-private",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_semantic_memory_write_doctor_guard_requires_allow_run(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-run"):
        probe._require_live_run(_args(allow_run=False))


def test_semantic_memory_write_doctor_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_run(_args())


def test_semantic_memory_write_doctor_guard_rejects_production_without_ack(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_run(_args())


def test_semantic_memory_write_doctor_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_run(_args(allow_production=True))


def test_failure_payload_redacts_memory_markers_scope_and_secret_fields():
    user_id = "unit-user-semantic-private"
    organization_id = "unit-org-semantic-private"
    session_id = "unit-session-semantic-private"
    request_id = "unit-request-semantic-private"
    raw_uuid = "123e4567-e89b-12d3-a456-426614174000"

    payload = probe._failure_payload(
        RuntimeError(
            "Semantic write failed for "
            f"{raw_uuid} {user_id} {organization_id} {session_id} {request_id} "
            f"{probe.RAW_MESSAGE_MARKER} {probe.RAW_RESPONSE_MARKER} "
            f"{probe.RAW_CROSS_ORG_MARKER} api_key access_token authorization"
        ),
        _args(
            user_id=user_id,
            organization_id=organization_id,
            session_id=session_id,
            request_id=request_id,
        ),
    )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "semantic_memory_write_doctor_failed"
    assert payload["privacy"]["identifier_strategy"] == "hash_or_count_only"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_marker_absent"] is True
    assert payload["privacy"]["raw_user_identifier_included"] is False
    assert payload["privacy"]["raw_session_identifier_included"] is False
    assert payload["privacy"]["raw_organization_identifier_included"] is False
    assert payload["privacy"]["raw_request_identifier_included"] is False
    assert payload["privacy"]["raw_secret_included"] is False
    assert raw_uuid not in rendered
    assert user_id not in rendered
    assert organization_id not in rendered
    assert session_id not in rendered
    assert request_id not in rendered
    for token in probe._forbidden_tokens():
        assert token.casefold() not in rendered.casefold()
    assert "api_key" not in rendered
    assert "access_token" not in rendered
    assert "authorization" not in rendered
    assert probe.IDENTIFIER_RE.search(rendered) is None


@pytest.mark.asyncio
async def test_semantic_memory_write_doctor_runs_hash_count_contract(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    payload = await probe._run_probe(_args())
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "pass"
    assert payload["runtime"]["path"] == "semantic_memory_write_doctor"
    assert payload["semantic_memory_write"]["audit_schema_version"] == (
        "wiii.semantic_memory_write.v1"
    )
    assert payload["post_turn_lifecycle"]["schema_version"] == (
        "wiii.post_turn_lifecycle.v1"
    )
    assert payload["post_turn_lifecycle"]["status"] == "scheduled"
    assert payload["post_turn_lifecycle"]["reason"] == (
        "post_turn_background_tasks_scheduled"
    )
    assert payload["post_turn_lifecycle"]["semantic_memory_policy"] == "extract_facts"
    assert payload["post_turn_lifecycle"]["background_tasks_scheduled"] is True
    assert (
        payload["post_turn_lifecycle"]["lifecycle_owned_semantic_scheduling"] is True
    )
    assert payload["post_turn_lifecycle"]["compatibility_wrapper_used"] is False
    assert payload["post_turn_lifecycle"]["scheduled_task_count"] == 2
    assert payload["post_turn_lifecycle"]["scheduled_task_names"] == [
        "_store_semantic_interaction",
        "_enqueue_or_run_semantic_memory_maintenance",
    ]
    background_schedule = payload["post_turn_lifecycle"]["background_schedule"]
    assert background_schedule["schema_version"] == "wiii.background_task_schedule.v1"
    assert background_schedule["task_count"] == 2
    assert background_schedule["groups"][0] == {
        "group": "semantic_memory_interaction",
        "reason": "extract_facts",
        "status": "scheduled",
    }
    assert background_schedule["groups"][1] == {
        "group": "semantic_memory_maintenance",
        "reason": "after_interaction_write",
        "status": "scheduled",
    }
    assert payload["post_turn_lifecycle"]["privacy"]["raw_content_included"] is False
    assert payload["session_log"]["backend"] == "in_memory"
    assert payload["session_log"]["append_count"] == 3
    assert payload["session_log"]["total_event_count"] == 6
    assert payload["session_log"]["total_semantic_write_event_count"] == 3
    assert payload["session_log"]["org_scoped_semantic_write_event_count"] == 2
    assert payload["session_log"]["total_runtime_flow_ledger_event_count"] == 2
    assert payload["session_log"]["org_scoped_runtime_flow_ledger_event_count"] == 1
    assert payload["session_log"]["cross_org_event_excluded"] is True
    assert payload["session_log"]["cross_org_runtime_flow_ledger_excluded"] is True
    assert payload["session_log"]["raw_non_memory_event_ignored"] is True
    assert payload["org_scoped_doctor"]["version"] == (
        "wiii.semantic_memory_write_doctor.v1"
    )
    assert payload["org_scoped_doctor"]["status"] == "degraded"
    assert payload["org_scoped_doctor"]["summary"]["write_count"] == 2
    assert payload["org_scoped_doctor"]["summary"]["stored_fact_total"] == 2
    assert payload["org_scoped_doctor"]["summary"]["stored_insight_total"] == 1
    assert payload["org_scoped_doctor"]["source"]["org_scoped"] is True
    assert payload["org_scoped_doctor"]["privacy"]["raw_content_included"] is False
    assert payload["org_scoped_history"]["version"] == (
        "wiii.semantic_memory_write_doctor_history.v1"
    )
    assert payload["org_scoped_history"]["bucket_strategy"] == "event_created_at_hour"
    assert payload["org_scoped_history"]["identifier_strategy"] == (
        "aggregate_counts_only"
    )
    assert payload["org_scoped_history"]["source"]["semantic_memory_write_event_count"] == 2
    assert payload["org_scoped_history"]["source"]["org_scoped"] is True
    assert payload["org_scoped_history"]["source"]["window"] == (
        "recent_semantic_memory_write_history"
    )
    assert len(payload["org_scoped_history"]["buckets"]) == 1
    history_bucket = payload["org_scoped_history"]["buckets"][0]
    assert history_bucket["status"] == "degraded"
    assert history_bucket["summary"]["write_count"] == 2
    assert history_bucket["summary"]["stored_fact_total"] == 2
    assert history_bucket["summary"]["stored_insight_total"] == 1
    assert history_bucket["warnings"]["insight_store_degraded"] == 1
    assert payload["org_scoped_history"]["privacy"]["raw_content_included"] is False
    assert payload["runtime_flow_doctor"]["version"] == "wiii.runtime_flow_doctor.v1"
    assert payload["runtime_flow_doctor"]["status"] == "ready"
    assert payload["runtime_flow_doctor"]["summary"]["turn_count"] == 1
    assert payload["runtime_flow_doctor"]["finalization_statuses"]["saved"] == 1
    assert (
        payload["runtime_flow_doctor"]["source"]["runtime_flow_ledger_event_count"]
        == 1
    )
    assert payload["runtime_flow_doctor"]["source"]["org_scoped"] is True
    lifecycle_ledger = payload["runtime_flow_doctor"]["post_turn_lifecycle_ledger"]
    assert lifecycle_ledger["version"] == "wiii.post_turn_lifecycle_ledger.v1"
    assert lifecycle_ledger["event_count"] == 1
    assert lifecycle_ledger["missing_count"] == 0
    assert lifecycle_ledger["background_tasks_scheduled_count"] == 1
    assert lifecycle_ledger["background_schedule"]["task_count"] == 2
    assert lifecycle_ledger["background_schedule"]["group_counts"] == {
        "semantic_memory_interaction": 1,
        "semantic_memory_maintenance": 1,
    }
    assert lifecycle_ledger["privacy"]["raw_content_included"] is False
    assert payload["runtime_flow_doctor_history"]["version"] == (
        "wiii.runtime_flow_doctor_history.v1"
    )
    assert payload["runtime_flow_doctor_history"]["bucket_strategy"] == (
        "event_created_at_hour"
    )
    assert (
        payload["runtime_flow_doctor_history"]["source"][
            "runtime_flow_ledger_event_count"
        ]
        == 1
    )
    assert payload["runtime_flow_doctor_history"]["source"]["org_scoped"] is True
    assert payload["runtime_flow_doctor_history"]["source"]["window"] == (
        "recent_runtime_flow_ledger_history"
    )
    assert payload["runtime_flow_doctor_history"]["post_turn_lifecycle_ledger"][
        "event_count"
    ] == 1
    assert payload["runtime_flow_doctor_history"]["buckets"][0][
        "post_turn_lifecycle_ledger"
    ]["event_count"] == 1
    assert payload["runtime_flow_doctor_history"]["privacy"][
        "raw_content_included"
    ] is False
    assert payload["blocked_missing_org_context"]["status"] == "degraded"
    assert payload["blocked_missing_org_context"]["summary"]["blocked_count"] == 1
    assert payload["blocked_missing_org_context"]["warnings"]["missing_org_context"] == 1
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_user_identifier_included"] is False
    assert payload["privacy"]["raw_session_identifier_included"] is False
    assert payload["privacy"]["raw_organization_identifier_included"] is False
    assert probe.RAW_MESSAGE_MARKER not in rendered
    assert probe.RAW_RESPONSE_MARKER not in rendered
    assert probe.RAW_CROSS_ORG_MARKER not in rendered
    assert "unit-user-semantic-private" not in rendered
    assert "unit-org-semantic-private" not in rendered
    assert "unit-session-semantic-private" not in rendered
    assert "access_token" not in rendered
    assert "authorization" not in rendered


def test_semantic_memory_write_doctor_sanitizer_rejects_raw_summary():
    payload = {
        "schema_version": probe.SCHEMA_VERSION,
        "status": "pass",
        "runtime": {"path": "semantic_memory_write_doctor"},
        "session_log": {
            "append_count": 3,
            "cross_org_event_excluded": True,
            "raw_non_memory_event_ignored": True,
        },
        "org_scoped_doctor": {
            "status": "degraded",
            "summary": {
                "write_count": 2,
                "stored_fact_total": 2,
                "stored_insight_total": 1,
            },
            "source": {"org_scoped": True},
        },
        "blocked_missing_org_context": {
            "summary": {"blocked_count": 1},
            "warnings": {"missing_org_context": 1},
        },
        "privacy": {
            "raw_content_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
        },
        "leak": probe.RAW_MESSAGE_MARKER,
    }

    with pytest.raises(RuntimeError, match="forbidden data"):
        probe._assert_probe_summary(payload)
