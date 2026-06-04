from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_heartbeat_cycle.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_heartbeat_cycle",
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
        "include_proactive_websocket": False,
        "skip_reflection": False,
        "skip_journal": False,
        "skip_briefing_audit": False,
        "user_id": "heartbeat-probe-user",
        "session_id": "heartbeat-probe-session",
        "organization_id": "org-A",
        "briefing_type": "midday",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _passing_summary(**delta_overrides):
    deltas = {
        "wiii_heartbeat_audit": {"before": 0, "after": 1, "delta": 1},
        "wiii_reflections": {"before": 0, "after": 1, "delta": 1},
        "wiii_journal": {"before": 0, "after": 1, "delta": 1},
        "wiii_briefings": {"before": 0, "after": 1, "delta": 1},
    }
    deltas.update(delta_overrides)
    return {
        "database": {"deltas": deltas},
        "proactive_websocket": {"socket_message_count": 0},
    }


def _contract_summary():
    return {
        "status": "pass",
        "scope": {
            "requested_organization_id_hash_present": True,
            "effective_organization_id_hash_present": True,
            "requested_matches_effective_org": True,
            "organization_context": "request_scoped",
            "warnings": [],
            "user_id_hash_present": True,
            "session_id_hash_present": True,
        },
        "heartbeat_cycle": {
            "cycle_id_hash_present": True,
            "is_noop": False,
            "error_present": False,
            "planned_action_count": 2,
            "reflect_planned": True,
            "write_journal_planned": True,
            "planned_actions": [
                {
                    "action_type": "reflect",
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
                {
                    "action_type": "write_journal",
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
            ],
            "actions_recorded_count": 2,
            "reflect_recorded": True,
            "write_journal_recorded": True,
            "actions_recorded": [
                {
                    "action_type": "reflect",
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
                {
                    "action_type": "write_journal",
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
            ],
            "raw_action_payload_included": False,
        },
        "lifecycle_contract": {
            "controlled_plan_used": True,
            "scheduler_execute_heartbeat_used": True,
            "prompt_patch_dependency": False,
            "required_actions_planned": True,
            "required_actions_recorded": True,
            "planned_recorded_action_count_matches": True,
            "planned_recorded_action_types_match": True,
            "briefing_audit_write_explicit": True,
            "proactive_websocket_requires_explicit_flag": True,
            "hash_count_only_output": True,
            "raw_action_metadata_values_absent": True,
            "raw_action_targets_absent": True,
        },
        "briefing": {
            "briefing_id_hash_present": True,
            "content_hash_present": True,
            "raw_content_included": False,
        },
        "proactive_websocket": {
            "raw_content_included": False,
            "payload_raw_content_included": False,
        },
        "database_scope_contract": {
            "request_org_context_set": True,
            "counted_table_count_matches_deltas": True,
            "core_table_set_checked": True,
            "heartbeat_audit_delta_observed": True,
            "briefing_delta_observed": True,
            "reflection_scope_observed": True,
            "journal_scope_observed": True,
            "proactive_message_delta_observed_when_requested": True,
            "raw_table_rows_included": False,
            "raw_sql_payload_included": False,
        },
        "metrics": {
            "heartbeat_cycles_event_count": 1,
            "heartbeat_cycle_success_count": 1,
            "heartbeat_cycle_success_seen": True,
            "heartbeat_cycle_duration_event_count": 1,
            "heartbeat_cycle_duration_success_count": 1,
            "heartbeat_cycle_duration_success_seen": True,
            "heartbeat_actions_event_count": 2,
            "heartbeat_action_success_count": 2,
            "heartbeat_action_duration_event_count": 2,
            "heartbeat_action_duration_success_count": 2,
            "heartbeat_action_duration_success_seen": True,
            "heartbeat_reflect_success_count": 1,
            "heartbeat_reflect_success_seen": True,
            "heartbeat_write_journal_success_count": 1,
            "heartbeat_write_journal_success_seen": True,
            "heartbeat_reflect_duration_success_count": 1,
            "heartbeat_reflect_duration_success_seen": True,
            "heartbeat_write_journal_duration_success_count": 1,
            "heartbeat_write_journal_duration_success_seen": True,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_action_target_included": False,
            "raw_action_metadata_values_included": False,
            "raw_briefing_content_included": False,
            "raw_socket_payload_included": False,
            "raw_metric_payload_included": False,
            "raw_database_rows_included": False,
            "raw_emotional_state_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def test_live_heartbeat_probe_guard_requires_allow_write(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-write"):
        probe._require_live_write(_args())


def test_live_heartbeat_probe_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_write(_args(allow_write=True))


def test_live_heartbeat_probe_guard_rejects_production_without_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_write(_args(allow_write=True))


def test_live_heartbeat_probe_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_write(_args(allow_write=True, allow_production=True))


def test_failure_payload_redacts_scope_target_and_secret_fields():
    user_id = "live-heartbeat-probe-user-private"
    session_id = "live-heartbeat-probe-session-private"
    organization_id = "org-private-heartbeat"
    raw_uuid = "123e4567-e89b-12d3-a456-426614174000"
    raw_target = f"reengage:{user_id}"

    payload = probe._failure_payload(
        RuntimeError(
            "Heartbeat failed for "
            f"{raw_uuid} {user_id} {session_id} {organization_id} {raw_target} "
            "access_token api_key authorization"
        ),
        _args(
            user_id=user_id,
            session_id=session_id,
            organization_id=organization_id,
        ),
    )
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "heartbeat_cycle_failed"
    assert payload["privacy"]["identifier_strategy"] == "hash_or_count_only"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_user_identifier_included"] is False
    assert payload["privacy"]["raw_session_identifier_included"] is False
    assert payload["privacy"]["raw_organization_identifier_included"] is False
    assert payload["privacy"]["raw_action_target_included"] is False
    assert payload["privacy"]["raw_action_metadata_values_included"] is False
    assert payload["privacy"]["raw_briefing_content_included"] is False
    assert payload["privacy"]["raw_socket_payload_included"] is False
    assert payload["privacy"]["raw_metric_payload_included"] is False
    assert payload["privacy"]["raw_database_rows_included"] is False
    assert payload["privacy"]["raw_emotional_state_included"] is False
    assert payload["privacy"]["raw_secret_included"] is False
    assert raw_uuid not in rendered
    assert user_id not in rendered
    assert session_id not in rendered
    assert organization_id not in rendered
    assert raw_target not in rendered
    assert "access_token" not in rendered
    assert "api_key" not in rendered
    assert "authorization" not in rendered
    assert probe.IDENTIFIER_RE.search(rendered) is None


def test_safe_action_summary_hashes_target_and_omits_metadata_values():
    action = SimpleNamespace(
        action_type=SimpleNamespace(value="send_briefing"),
        target="reengage:raw-user-id",
        priority=0.71234,
        metadata={"channel": "websocket", "probe": "raw-secret-value"},
    )

    summary = probe._safe_action_summary(action)
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["action_type"] == "send_briefing"
    assert summary["target_present"] is True
    assert summary["target_hash"]
    assert summary["priority"] == 0.712
    assert summary["metadata_keys"] == ["channel", "probe"]
    assert summary["metadata_key_count"] == 2
    assert summary["target_hash_present"] is True
    assert summary["metadata_values_included"] is False
    assert summary["raw_target_included"] is False
    assert "raw-user-id" not in rendered
    assert "raw-secret-value" not in rendered


def test_action_type_names_are_count_only():
    actions = _build_actions_for_names()

    assert probe._action_type_names(actions) == ["reflect", "write_journal"]
    assert probe._has_action_type(actions, "reflect") is True
    assert probe._has_action_type(actions, "send_briefing") is False


def _build_actions_for_names():
    return probe._build_controlled_actions(_args())


def test_metric_event_count_sums_counter_values():
    metrics = {
        "counters": {
            "runtime.living_agent.heartbeat.actions": {
                (("action_type", "reflect"), ("status", "success")): 1,
                (("action_type", "write_journal"), ("status", "success")): 2,
            }
        }
    }

    assert (
        probe._metric_event_count(
            metrics,
            "runtime.living_agent.heartbeat.actions",
        )
        == 3
    )


def test_metric_label_and_histogram_helpers_report_action_success():
    metrics = {
        "counters": {
            "runtime.living_agent.heartbeat.actions": {
                (("action_type", "reflect"), ("status", "success")): 1,
            },
        },
        "histograms": {
            "runtime.living_agent.heartbeat.action_duration_ms": {
                (("action_type", "reflect"), ("status", "success")): [10.0],
            },
        },
    }

    assert probe._metric_label_seen(
        metrics,
        "runtime.living_agent.heartbeat.actions",
        expected={"action_type": "reflect", "status": "success"},
    )
    assert (
        probe._metric_label_count(
            metrics,
            "runtime.living_agent.heartbeat.actions",
            expected={"action_type": "reflect", "status": "success"},
        )
        == 1
    )
    assert probe._histogram_label_seen(
        metrics,
        "runtime.living_agent.heartbeat.action_duration_ms",
        expected={"action_type": "reflect", "status": "success"},
    )
    assert (
        probe._histogram_event_count(
            metrics,
            "runtime.living_agent.heartbeat.action_duration_ms",
        )
        == 1
    )


def test_build_controlled_actions_can_include_proactive_websocket():
    actions = probe._build_controlled_actions(_args(include_proactive_websocket=True))

    assert [action.action_type.value for action in actions] == [
        "reflect",
        "write_journal",
        "send_briefing",
    ]
    assert actions[-1].target == "reengage:heartbeat-probe-user"
    assert actions[-1].metadata["channel"] == "websocket"


def test_table_deltas_are_count_only():
    deltas = probe._table_deltas(
        {"wiii_journal": 1, "wiii_reflections": 2},
        {"wiii_journal": 3, "wiii_reflections": 2},
    )

    assert deltas == {
        "wiii_journal": {"before": 1, "after": 3, "delta": 2},
        "wiii_reflections": {"before": 2, "after": 2, "delta": 0},
    }


def test_probe_evidence_accepts_created_or_existing_journal_and_reflection():
    summary = _passing_summary(
        wiii_reflections={"before": 1, "after": 1, "delta": 0},
        wiii_journal={"before": 1, "after": 1, "delta": 0},
    )

    probe._assert_probe_evidence(summary, _args())


def test_probe_evidence_rejects_missing_heartbeat_audit():
    summary = _passing_summary(
        wiii_heartbeat_audit={"before": 0, "after": 0, "delta": 0},
    )

    with pytest.raises(RuntimeError, match="heartbeat audit"):
        probe._assert_probe_evidence(summary, _args())


def test_probe_evidence_rejects_missing_proactive_delivery():
    summary = _passing_summary(
        wiii_proactive_messages={"before": 0, "after": 1, "delta": 1},
    )

    with pytest.raises(RuntimeError, match="probe socket"):
        probe._assert_probe_evidence(
            summary,
            _args(include_proactive_websocket=True),
        )


def test_heartbeat_summary_contract_rejects_raw_metadata_flag():
    summary = _contract_summary()
    summary["heartbeat_cycle"]["planned_actions"][0]["metadata_values_included"] = True

    with pytest.raises(RuntimeError, match="metadata_values_included"):
        probe._assert_heartbeat_summary_contract(summary, _args())


def test_heartbeat_summary_contract_rejects_action_count_mismatch():
    summary = _contract_summary()
    summary["lifecycle_contract"]["planned_recorded_action_count_matches"] = False

    with pytest.raises(RuntimeError, match="planned_recorded_action_count_matches"):
        probe._assert_heartbeat_summary_contract(summary, _args())


def test_heartbeat_summary_contract_rejects_unscoped_database_contract():
    summary = _contract_summary()
    summary["database_scope_contract"]["request_org_context_set"] = False

    with pytest.raises(RuntimeError, match="database_scope_contract.request_org_context_set"):
        probe._assert_heartbeat_summary_contract(summary, _args())
