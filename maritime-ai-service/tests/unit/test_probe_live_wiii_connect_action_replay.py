from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_wiii_connect_action_replay.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_wiii_connect_action_replay",
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
        "user_id": "unit-user",
        "organization_id": "unit-org",
        "session_id": "unit-session",
        "request_id": "unit-request",
        "prompt": "Wiii doc Gmail moi nhat tu giao vien giup toi",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_wiii_connect_action_replay_guard_requires_allow_run(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-run"):
        probe._require_live_run(_args(allow_run=False))


def test_wiii_connect_action_replay_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_run(_args())


def test_wiii_connect_action_replay_guard_rejects_production_without_ack(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_run(_args())


def test_wiii_connect_action_replay_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_run(_args(allow_production=True))


def test_failure_payload_redacts_action_scope_connection_and_secret_fields():
    user_id = "unit-user-private"
    organization_id = "unit-org-private"
    session_id = "unit-session-private"
    request_id = "unit-request-private"
    prompt = "Private Wiii Connect action prompt"
    raw_uuid = "123e4567-e89b-12d3-a456-426614174000"

    payload = probe._failure_payload(
        RuntimeError(
            "Wiii Connect action failed for "
            f"{raw_uuid} {user_id} {organization_id} {session_id} {request_id} "
            f"{prompt} {probe.RAW_ARGUMENT_MARKER} {probe.RAW_SECRET_MARKER} "
            "local-fake-key provider-managed:// ca_wiii_connect_action_replay "
            "connected_account_id connection_ref api_key access_token authorization"
        ),
        _args(
            user_id=user_id,
            organization_id=organization_id,
            session_id=session_id,
            request_id=request_id,
            prompt=prompt,
        ),
    )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "wiii_connect_action_replay_failed"
    assert payload["privacy"]["identifier_strategy"] == "hash_or_count_only"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_marker_absent"] is True
    assert payload["privacy"]["raw_prompt_included"] is False
    assert payload["privacy"]["raw_request_identifiers_included"] is False
    assert payload["privacy"]["provider_arguments_included"] is False
    assert payload["privacy"]["provider_payload_included"] is False
    assert payload["privacy"]["raw_audit_metadata_included"] is False
    assert payload["privacy"]["opaque_connection_identifier_included"] is False
    assert payload["privacy"]["final_answer_text_included"] is False
    assert payload["privacy"]["raw_secret_included"] is False
    assert raw_uuid not in rendered
    assert user_id not in rendered
    assert organization_id not in rendered
    assert session_id not in rendered
    assert request_id not in rendered
    assert prompt not in rendered
    assert probe.RAW_ARGUMENT_MARKER not in rendered
    assert probe.RAW_SECRET_MARKER not in rendered
    assert "local-fake-key" not in rendered
    assert "provider-managed://" not in rendered
    assert "ca_wiii_connect_action_replay" not in rendered
    assert "connected_account_id" not in rendered
    assert "connection_ref" not in rendered
    assert "api_key" not in rendered
    assert "access_token" not in rendered
    assert "authorization" not in rendered
    assert probe.IDENTIFIER_RE.search(rendered) is None


@pytest.mark.asyncio
async def test_wiii_connect_action_replay_runs_backend_gateway_contract(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    payload = await probe._run_probe(_args())
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "pass"
    assert payload["runtime"]["path"] == "external_app_action"
    assert payload["runtime"]["request_id_hash_present"] is True
    assert payload["runtime"]["session_id_hash_present"] is True
    assert payload["runtime"]["organization_id_hash_present"] is True
    assert payload["runtime"]["user_id_hash_present"] is True
    assert payload["runtime"]["prompt_hash_present"] is True
    assert payload["runtime"]["raw_prompt_included"] is False
    assert payload["runtime"]["plan"]["status"] == "ready"
    assert payload["runtime"]["plan"]["kind"] == "provider_action"
    assert payload["runtime"]["plan"]["provider_ready"] is True
    assert payload["runtime"]["integration_lane"]["executor"] == "provider_worker"
    assert payload["runtime"]["integration_lane"]["visible_tool_count_matches"] is True
    assert payload["integration_worker"]["status"] == "ready"
    assert payload["integration_worker"]["stage_sequence_ready"] is True
    assert payload["integration_worker"]["argument_plan"]["source"] == "caller_provided"
    assert payload["integration_worker"]["argument_plan"]["required_argument_keys_present"] is True
    assert payload["integration_worker"]["raw_prompt_included"] is False
    assert payload["integration_worker"]["result_classification"]["outcome"] == (
        "completed"
    )
    assert payload["backend_gateway"]["status"] == "allowed"
    assert payload["backend_gateway"]["connection_present"] is True
    assert payload["backend_gateway"]["audit_persistent"] is True
    assert payload["backend_gateway"]["scope_policy"]["status"] == "allowed"
    assert payload["backend_gateway"]["scope_policy"]["required_scopes"] == ["read"]
    assert payload["backend_executor"]["schema"]["required_argument_keys"] == ["query"]
    assert payload["backend_executor"]["schema"]["schema_present"] is True
    assert payload["backend_executor"]["execution"]["status"] == "succeeded"
    assert payload["backend_executor"]["execution"]["provider_payload_included"] is False
    assert payload["backend_executor"]["required_arguments_present"] is True
    assert payload["backend_executor"]["observed_execute_argument_keys"] == [
        "max_results",
        "query",
    ]
    assert payload["connection_lookup"]["provider_scope_matches"] is True
    assert payload["connection_lookup"]["organization_id_hash_present"] is True
    assert payload["connection_lookup"]["user_id_hash_present"] is True
    assert payload["final_answer"]["source"] == "external_app_action_final_answer"
    assert payload["final_answer"]["present"] is True
    assert payload["final_answer"]["raw_answer_included"] is False
    assert payload["audits"]["record_count"] >= 2
    assert payload["audits"]["execution_event_count"] >= 2
    assert payload["audits"]["all_records_org_scoped"] is True
    assert payload["audits"]["raw_metadata_included"] is False
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_prompt_included"] is False
    assert payload["privacy"]["raw_request_identifiers_included"] is False
    assert payload["privacy"]["provider_payload_included"] is False
    assert payload["privacy"]["raw_audit_metadata_included"] is False
    assert payload["privacy"]["final_answer_text_included"] is False
    assert probe.RAW_ARGUMENT_MARKER not in rendered
    assert probe.RAW_SECRET_MARKER not in rendered
    assert "local-fake-key" not in rendered
    assert "provider-managed://" not in rendered
    assert "connection_ref" not in rendered
    assert "api_key" not in rendered


def test_wiii_connect_action_replay_sanitizer_rejects_sensitive_summary():
    payload = {
        "schema_version": probe.SCHEMA_VERSION,
        "status": "pass",
        "runtime": {
            "path": "external_app_action",
            "request_id_hash_present": True,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
            "user_id_hash_present": True,
            "prompt_hash_present": True,
            "plan": {"status": "ready", "provider_ready": True},
            "integration_lane": {
                "executor": "provider_worker",
                "visible_tool_count_matches": True,
            },
        },
        "integration_worker": {
            "stage_sequence": ["provider_gate", "action_policy", "ready"],
            "stage_sequence_ready": True,
            "argument_plan": {"required_argument_keys_present": True},
            "result_classification": {"outcome": "completed"},
        },
        "backend_gateway": {
            "status": "allowed",
            "connection_present": True,
            "audit_persistent": True,
        },
        "backend_executor": {
            "execution": {
                "status": "succeeded",
                "successful": True,
                "log_id_present": True,
                "provider_payload_included": False,
            },
            "schema": {"schema_present": True},
            "required_arguments_present": True,
        },
        "connection_lookup": {
            "organization_id_hash_present": True,
            "user_id_hash_present": True,
            "provider_scope_matches": True,
        },
        "audits": {
            "record_count": 2,
            "execution_event_count": 2,
            "started_seen": True,
            "succeeded_seen": True,
            "execute_stage_seen": True,
            "execute_result_stage_seen": True,
            "all_records_org_scoped": True,
            "all_records_user_scoped": True,
        },
        "final_answer": {"raw_answer_included": False},
        "privacy": {
            "raw_content_included": False,
            "raw_prompt_included": False,
            "raw_request_identifiers_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "raw_audit_metadata_included": False,
            "opaque_connection_identifier_included": False,
            "final_answer_text_included": False,
        },
        "leak": "api_key",
    }

    with pytest.raises(RuntimeError, match="forbidden data"):
        probe._assert_probe_summary(payload)
