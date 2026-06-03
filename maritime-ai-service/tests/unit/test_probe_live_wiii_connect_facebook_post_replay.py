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
    / "probe_live_wiii_connect_facebook_post_replay.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_wiii_connect_facebook_post_replay",
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
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_wiii_connect_facebook_post_replay_guard_requires_allow_run(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-run"):
        probe._require_live_run(_args(allow_run=False))


def test_wiii_connect_facebook_post_replay_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_run(_args())


def test_wiii_connect_facebook_post_replay_guard_rejects_production_without_ack(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_run(_args())


def test_wiii_connect_facebook_post_replay_guard_allows_production_with_ack(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_run(_args(allow_production=True))


def test_failure_payload_redacts_facebook_post_scope_connection_and_secret_fields():
    user_id = "unit-user-private"
    organization_id = "unit-org-private"
    session_id = "unit-session-private"
    request_id = "unit-request-private"
    raw_uuid = "123e4567-e89b-12d3-a456-426614174000"

    payload = probe._failure_payload(
        RuntimeError(
            "Wiii Connect Facebook post failed for "
            f"{raw_uuid} {user_id} {organization_id} {session_id} {request_id} "
            f"{probe.RAW_MESSAGE_MARKER} {probe.RAW_PAGE_ID} {probe.FAKE_CONNECTION_ID} "
            f"{probe.FAKE_API_KEY} {probe.FAKE_AUTH_CONFIG_ID} "
            "Bearer live-token provider-managed:// wcn_private approval_token "
            "connected_account_id connection_ref page_id api_key access_token authorization"
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
    assert payload["error_code"] == "wiii_connect_facebook_post_replay_failed"
    assert payload["privacy"]["identifier_strategy"] == "hash_or_count_only"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_marker_absent"] is True
    assert payload["privacy"]["raw_request_identifiers_included"] is False
    assert payload["privacy"]["provider_arguments_included"] is False
    assert payload["privacy"]["provider_response_included"] is False
    assert payload["privacy"]["request_payload_included"] is False
    assert payload["privacy"]["approval_credential_included"] is False
    assert payload["privacy"]["opaque_connection_identifier_included"] is False
    assert payload["privacy"]["selected_page_value_included"] is False
    assert payload["privacy"]["raw_secret_included"] is False
    assert raw_uuid not in rendered
    assert user_id not in rendered
    assert organization_id not in rendered
    assert session_id not in rendered
    assert request_id not in rendered
    assert probe.RAW_MESSAGE_MARKER not in rendered
    assert probe.RAW_PAGE_ID not in rendered
    assert probe.FAKE_CONNECTION_ID not in rendered
    assert probe.FAKE_API_KEY not in rendered
    assert probe.FAKE_AUTH_CONFIG_ID not in rendered
    assert "Bearer live-token" not in rendered
    assert "provider-managed://" not in rendered
    assert "wcn_private" not in rendered
    assert "approval_token" not in rendered
    assert "connected_account_id" not in rendered
    assert "connection_ref" not in rendered
    assert "page_id" not in rendered
    assert "api_key" not in rendered
    assert "access_token" not in rendered
    assert "authorization" not in rendered
    assert probe.IDENTIFIER_RE.search(rendered) is None


@pytest.mark.asyncio
async def test_wiii_connect_facebook_post_replay_runs_backend_contract(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    payload = await probe._run_probe(_args())
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "pass"
    assert payload["provider"] == "facebook"
    assert payload["action"] == "FACEBOOK_CREATE_POST"
    assert payload["runtime"]["path"] == "external_app_action"
    assert payload["runtime"]["request_id_hash_present"] is True
    assert payload["runtime"]["session_id_hash_present"] is True
    assert payload["runtime"]["organization_id_hash_present"] is True
    assert payload["runtime"]["user_id_hash_present"] is True
    assert payload["runtime"]["raw_identifiers_included"] is False
    assert payload["preview"]["status"] == "ready"
    assert payload["preview"]["preview_evidence_id_present"] is True
    assert payload["preview"]["preview_evidence_id_hash_present"] is True
    assert payload["preview"]["approval_credential_present"] is True
    assert payload["preview"]["approval_credential_hash_present"] is True
    assert payload["preview"]["raw_response_payload_included"] is False
    assert payload["preview"]["approval_ledger"]["status"] == "pending"
    assert payload["preview"]["approval_ledger"]["persistent"] is True
    assert payload["apply"]["status"] == "succeeded"
    assert payload["apply"]["approval_credential_hash_present"] is True
    assert payload["apply"]["preview_evidence_id_hash_present"] is True
    assert payload["apply"]["raw_response_payload_included"] is False
    assert payload["apply"]["gateway"]["status"] == "allowed"
    assert payload["apply"]["schema"]["status"] == "ready"
    assert payload["apply"]["schema"]["schema_present"] is True
    assert payload["apply"]["execution"]["status"] == "succeeded"
    assert payload["apply"]["execution"]["successful"] is True
    assert payload["apply"]["execution"]["log_id_present"] is True
    assert payload["apply"]["approval_ledger"]["status"] == "consumed"
    assert payload["apply"]["approval_ledger"]["consumed"] is True
    assert payload["replay"]["status"] == "blocked"
    assert payload["replay"]["reason"] == "approval_record_already_consumed"
    assert payload["replay"]["gateway_evaluated"] is False
    assert payload["replay"]["schema_evaluated"] is False
    assert payload["replay"]["execution_attempted"] is False
    assert payload["replay"]["approval_credential_hash_present"] is True
    assert payload["replay"]["preview_evidence_id_hash_present"] is True
    assert payload["replay"]["raw_response_payload_included"] is False
    assert payload["replay"]["approval_ledger"]["status"] == "blocked"
    assert payload["replay"]["approval_ledger"]["blocked"] is True
    assert payload["operation_approval"]["append_count"] == 1
    assert payload["operation_approval"]["consume_count"] == 2
    assert payload["operation_approval"]["preview_evidence_id_hash_present"] is True
    assert payload["provider_execute_call_count"] == 1
    assert payload["provider_executor"]["call_count"] == 1
    assert payload["provider_executor"]["required_arguments_present"] is True
    assert payload["provider_executor"]["connected_account_seen"] is True
    assert payload["provider_executor"]["raw_arguments_included"] is False
    assert payload["provider_executor"]["raw_response_included"] is False
    assert payload["provider_executor"]["provider_account_identifier_included"] is False
    assert payload["storage_scope"]["list_call_count"] >= 1
    assert payload["storage_scope"]["get_call_count"] >= 1
    assert payload["storage_scope"]["all_calls_org_scoped"] is True
    assert payload["storage_scope"]["all_calls_user_scoped"] is True
    assert payload["storage_scope"]["raw_identifiers_included"] is False
    assert payload["audits"]["record_count"] >= 3
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["provider_response_included"] is False
    assert payload["privacy"]["request_payload_included"] is False
    assert payload["privacy"]["approval_credential_included"] is False
    assert payload["privacy"]["raw_request_identifiers_included"] is False
    assert probe.RAW_MESSAGE_MARKER not in rendered
    assert probe.RAW_PAGE_ID not in rendered
    assert probe.FAKE_CONNECTION_ID not in rendered
    assert probe.FAKE_API_KEY not in rendered
    assert probe.FAKE_AUTH_CONFIG_ID not in rendered
    assert "approval_token" not in rendered
    assert "connection_ref" not in rendered
    assert "page_id" not in rendered


def test_wiii_connect_facebook_post_replay_sanitizer_rejects_sensitive_summary():
    payload = {
        "schema_version": probe.SCHEMA_VERSION,
        "status": "pass",
        "provider": "facebook",
        "action": "FACEBOOK_CREATE_POST",
        "runtime": {"path": "external_app_action"},
        "preview": {
            "status": "ready",
            "approval_ledger": {"status": "pending"},
        },
        "apply": {
            "status": "succeeded",
            "approval_ledger": {"status": "consumed"},
        },
        "replay": {
            "status": "blocked",
            "reason": "approval_record_already_consumed",
        },
        "operation_approval": {"append_count": 1, "consume_count": 2},
        "provider_execute_call_count": 1,
        "audits": {"record_count": 3},
        "privacy": {
            "raw_content_included": False,
            "provider_arguments_included": False,
            "approval_credential_included": False,
            "opaque_connection_identifier_included": False,
            "selected_page_value_included": False,
        },
        "leak": "approval_token",
    }

    with pytest.raises(RuntimeError, match="forbidden data"):
        probe._assert_probe_summary(payload)
