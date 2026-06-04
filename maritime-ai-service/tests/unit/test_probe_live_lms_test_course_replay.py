from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_lms_test_course_replay.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_lms_test_course_replay",
    SCRIPT_PATH,
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


def _args(**overrides):
    values = {
        "allow_write": False,
        "allow_external_lms_write": False,
        "allow_production": False,
        "transport_mode": "asgi",
        "base_url": "http://127.0.0.1:8000",
        "auth_mode": "auto",
        "bearer_token": "",
        "external_lms_apply_url": "https://lms.example.test/apply",
        "external_lms_apply_token": "external-lms-token-secret",
        "api_key": "local-dev-key",
        "request_id": "",
        "user_id": "teacher-1",
        "demo_email": "teacher@localhost",
        "demo_name": "Teacher Local",
        "organization_id": "org-1",
        "domain_id": "maritime",
        "role": "teacher",
        "course_id": "course-1",
        "lesson_id": "lesson-1",
        "session_id": "session-1",
        "provider": "",
        "model": "",
        "thinking_effort": "low",
        "prompt": probe.DEFAULT_PROMPT,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _passing_stream_summary(**overrides):
    summary = {
        "path": "lms_document_preview",
        "stream_transport": "sse_v3",
        "metadata_seen": True,
        "done_seen": True,
        "terminal_event_name": "done",
        "event_counts": {"done": 1, "host_action": 1},
        "host_surface": "embed_lms",
        "host_capabilities": ["lms", "host_action", "document_preview"],
        "document_context_present": True,
        "uploaded_document_count": 1,
        "source_ref_count": 1,
        "context_provenance_schema_version": "wiii.context_provenance_ledger.v1",
        "context_provenance_raw_content_included": False,
        "context_provenance_identifier_strategy": "hash_or_count_only",
        "context_provenance_document_present": True,
        "context_provenance_attachment_count": 1,
        "context_provenance_usable_attachment_count": 1,
        "context_provenance_source_ref_count": 1,
        "context_provenance_attachment_id_hash_count": 1,
        "context_provenance_media_kinds": ["document"],
        "context_provenance_source_ref_kinds": ["heading"],
        "context_provenance_host_context_present": True,
        "context_provenance_host_surface": "embed_lms",
        "context_provenance_host_capabilities": [
            "document_preview",
            "host_action",
            "lms",
        ],
        "preview_required": True,
        "preview_emitted": True,
        "apply_attempted": False,
        "approval_token_present": False,
        "host_action_result_received": False,
        "finalization_status": "saved",
        "finalization_error_absent": True,
        "post_turn_lifecycle_schema_version": "wiii.post_turn_lifecycle.v1",
        "post_turn_lifecycle_raw_content_included": False,
        "post_turn_lifecycle_identifier_strategy": "status_only",
    }
    summary.update(overrides)
    return summary


def _passing_host_action_summary(**overrides):
    summary = {
        "request_id_hash": "sha256:preview",
        "request_id_hash_present": True,
        "action": probe.PREVIEW_ACTION,
        "source_reference_count": 1,
    }
    summary.update(overrides)
    return summary


def _passing_preview_audit(**overrides):
    summary = {
        "status_code": 200,
        "status_code_ok": True,
        "status": "success",
        "status_success": True,
        "event_type": "preview_created",
        "event_type_matches_payload": True,
        "action": probe.PREVIEW_ACTION,
        "action_matches_payload": True,
        "request_id_hash": "sha256:preview",
        "request_id_hash_present": True,
        "request_id_hash_matches_payload": True,
        "preview_token_hash": "sha256:token",
        "preview_token_hash_present": True,
        "host_type_matches_lms": True,
        "workflow_stage_matches_authoring": True,
        "preview_kind_matches_lesson_patch": True,
        "target_type_matches_lesson": True,
        "metadata_probe_matches": True,
        "metadata_course_id_hash_present": True,
        "metadata_lesson_id_hash_present": True,
        "metadata_source_reference_count": 1,
        "metadata_uploaded_document_count": 1,
        "metadata_raw_content_included": False,
    }
    summary.update(overrides)
    return summary


def _passing_apply_audit(**overrides):
    summary = _passing_preview_audit(
        event_type="apply_confirmed",
        action=probe.APPLY_ACTION,
        metadata_preview_request_id_hash="sha256:preview",
        metadata_preview_request_id_hash_present=True,
        metadata_approval_token_present=True,
        metadata_approval_credential_present=True,
    )
    summary.update(overrides)
    return summary


def _passing_source_contract(**overrides):
    summary = {
        "provenance_source_ref_count_matches_runtime": True,
        "host_action_source_ref_count_matches_runtime": True,
    }
    summary.update(overrides)
    return summary


def _passing_audit_sequence_contract(**overrides):
    summary = {
        "preview_request_linked_to_apply": True,
        "shared_preview_token_hash": True,
    }
    summary.update(overrides)
    return summary


def _passing_evidence_contract(**overrides):
    summary = {
        "hash_count_only_output": True,
        "external_lms_write_required": True,
        "requires_live_channel_credentials": True,
        "synthetic_host_side_replay": False,
        "external_lms_write_disabled": False,
    }
    summary.update(overrides)
    return summary


def _passing_external_lms_write(**overrides):
    summary = {
        "schema_version": probe.EXTERNAL_LMS_WRITE_SCHEMA_VERSION,
        "mode": "webhook",
        "write_attempted": True,
        "write_acknowledged": True,
        "status_code_ok": True,
        "endpoint_hash_present": True,
        "credential_hash_present": True,
        "request_id_hash_present": True,
        "course_id_hash_present": True,
        "lesson_id_hash_present": True,
        "preview_request_id_hash_present": True,
        "preview_token_hash_present": True,
        "payload_content_hash_present": True,
        "payload_source_reference_count": 1,
        "raw_request_payload_included": False,
        "raw_response_payload_included": False,
        "raw_credential_included": False,
    }
    summary.update(overrides)
    return summary


def test_live_lms_probe_guard_requires_allow_write(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-write"):
        probe._require_live_write(_args())


def test_lms_preflight_reports_required_setup_without_live_writes(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)
    monkeypatch.delenv(probe.EXTERNAL_LMS_APPLY_URL_ENV, raising=False)
    monkeypatch.delenv(probe.EXTERNAL_LMS_APPLY_TOKEN_ENV, raising=False)

    payload = probe._build_lms_test_course_preflight(
        _args(
            external_lms_apply_url="",
            external_lms_apply_token="",
        )
    )

    assert payload["schema_version"] == probe.PREFLIGHT_SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["live_write_attempted"] is False
    assert payload["external_lms_write_attempted"] is False
    assert payload["privacy"]["secret_values_included"] is False
    assert payload["privacy"]["credential_names_included"] is False
    assert "pass_allow_write" in payload["required_next"]
    assert "pass_allow_external_lms_write" in payload["required_next"]
    assert "set_live_lms_test_course_replay_flag" in payload["required_next"]
    assert "configure_external_lms_apply_url" in payload["required_next"]
    assert "configure_external_lms_apply_token" in payload["required_next"]
    assert payload["setup_contract"]["requirement_id"] == "lms-test-course-replay"
    assert payload["setup_contract"]["required_next"] == payload["required_next"]
    assert payload["setup_contract"]["dispatch_ready"] is False
    rendered = json.dumps(payload, sort_keys=True)
    assert probe.EXTERNAL_LMS_APPLY_URL_ENV not in rendered
    assert probe.EXTERNAL_LMS_APPLY_TOKEN_ENV not in rendered
    assert "external-lms-token-secret" not in rendered
    assert "https://lms.example.test/apply" not in rendered


def test_lms_failure_from_preflight_embeds_safe_setup_summary(tmp_path):
    preflight = probe._build_lms_test_course_preflight(
        _args(
            external_lms_apply_url="",
            external_lms_apply_token="",
        )
    )
    preflight_path = tmp_path / "lms-test-course-preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    loaded = probe.load_lms_test_course_preflight(preflight_path)
    payload = probe._failure_payload(
        RuntimeError("preflight blocked live LMS test-course replay"),
        _args(),
        preflight=loaded,
    )

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["preflight"]["schema_version"] == probe.PREFLIGHT_SCHEMA_VERSION
    assert payload["live_write_attempted"] is False
    assert payload["external_lms_write_attempted"] is False
    assert payload["setup_contract"] == loaded["setup_contract"]
    rendered = json.dumps(payload, sort_keys=True)
    assert "external-lms-token-secret" not in rendered
    assert "https://lms.example.test/apply" not in rendered


def test_live_lms_probe_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_write(
            _args(allow_write=True, allow_external_lms_write=True)
        )


def test_live_lms_probe_guard_requires_external_lms_write_ack(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-external-lms-write"):
        probe._require_live_write(_args(allow_write=True))


def test_live_lms_probe_guard_requires_external_lms_credentials(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.delenv(probe.EXTERNAL_LMS_APPLY_URL_ENV, raising=False)
    monkeypatch.delenv(probe.EXTERNAL_LMS_APPLY_TOKEN_ENV, raising=False)

    with pytest.raises(SystemExit, match=probe.EXTERNAL_LMS_APPLY_URL_ENV):
        probe._require_live_write(
            _args(
                allow_write=True,
                allow_external_lms_write=True,
                external_lms_apply_url="",
            )
        )

    with pytest.raises(SystemExit, match=probe.EXTERNAL_LMS_APPLY_TOKEN_ENV):
        probe._require_live_write(
            _args(
                allow_write=True,
                allow_external_lms_write=True,
                external_lms_apply_token="",
            )
        )


def test_live_lms_probe_guard_rejects_production_without_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_write(
            _args(allow_write=True, allow_external_lms_write=True)
        )


def test_live_lms_probe_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_write(
        _args(
            allow_write=True,
            allow_external_lms_write=True,
            allow_production=True,
        )
    )


def test_live_lms_probe_guard_rejects_nonlocal_http_without_production_ack(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="non-local backend"):
        probe._require_live_write(
            _args(
                allow_write=True,
                allow_external_lms_write=True,
                transport_mode="http",
                base_url="https://wiii.example.com",
            )
        )


def test_live_lms_probe_enables_dev_login_for_local_asgi_auto(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.delenv("ENABLE_DEV_LOGIN", raising=False)
    monkeypatch.delenv("ENABLE_ORG_MEMBERSHIP_CHECK", raising=False)

    probe._require_live_write(
        _args(
            allow_write=True,
            allow_external_lms_write=True,
            auth_mode="auto",
            transport_mode="asgi",
        )
    )

    assert os.environ["ENABLE_DEV_LOGIN"] == "true"
    assert os.environ["ENABLE_ORG_MEMBERSHIP_CHECK"] == "false"


def test_api_key_auth_summary_avoids_forbidden_api_key_token():
    _, summary = probe._api_key_auth_headers(_args())
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["auth_mode"] == "local_header_secret"
    assert summary["auth_secret_hash"]
    assert "api_key" not in rendered


def test_extract_host_action_request_requires_preview_action():
    events = [
        probe.SseEvent(
            name="host_action",
            data={
                "content": {
                    "id": "req-preview-1",
                    "action": probe.PREVIEW_ACTION,
                    "params": {"lesson_id": "lesson-1"},
                }
            },
        )
    ]

    assert probe._extract_host_action_request(events) == {
        "request_id": "req-preview-1",
        "action": probe.PREVIEW_ACTION,
        "params": {"lesson_id": "lesson-1"},
    }


def test_extract_host_action_request_rejects_missing_preview_action():
    events = [
        probe.SseEvent(
            name="host_action",
            data={"content": {"id": "req-x", "action": "ui.highlight"}},
        )
    ]

    with pytest.raises(RuntimeError, match="host_action"):
        probe._extract_host_action_request(events)


def test_safe_host_action_summary_omits_raw_params_and_hashes_ids():
    host_action = {
        "request_id": "req-preview-secret",
        "action": probe.PREVIEW_ACTION,
        "params": {
            "title": "Raw title",
            "content": "raw uploaded lesson content",
            "lesson_id": "lesson-secret",
            "source_references": [{"excerpt": "raw source excerpt"}],
        },
    }

    summary = probe._safe_host_action_summary(host_action)
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["action"] == probe.PREVIEW_ACTION
    assert summary["request_id_hash"]
    assert summary["request_id_hash_present"] is True
    assert summary["lesson_id_hash_present"] is True
    assert summary["content_present"] is True
    assert summary["source_reference_count"] == 1
    assert "req-preview-secret" not in rendered
    assert "raw uploaded lesson content" not in rendered
    assert "raw source excerpt" not in rendered
    assert "lesson-secret" not in rendered


def test_build_audit_payloads_keeps_approval_token_out_of_audit_payloads():
    args = _args(allow_write=True)
    host_action = {
        "request_id": "req-preview-1",
        "action": probe.PREVIEW_ACTION,
        "params": {
            "lesson_id": "lesson-1",
            "course_id": "course-1",
            "source_references": [{"page_start": 1}],
        },
    }
    ledger = {"context": {"uploaded_document_count": 1, "source_ref_count": 1}}

    payloads = probe._build_audit_payloads(args, host_action, ledger)
    rendered_preview = json.dumps(payloads["preview"], sort_keys=True)
    rendered_apply = json.dumps(payloads["apply"], sort_keys=True)

    assert payloads["preview"]["event_type"] == "preview_created"
    assert payloads["apply"]["event_type"] == "apply_confirmed"
    assert payloads["preview"]["preview_token"] == payloads["preview_token"]
    assert payloads["apply"]["preview_token"] == payloads["preview_token"]
    assert payloads["approval_token"] not in rendered_preview
    assert payloads["approval_token"] not in rendered_apply
    assert "approval_token_present" in rendered_apply
    assert payloads["preview"]["metadata"]["raw_lms_document_included"] is False
    assert payloads["apply"]["metadata"]["approval_credential_present"] is True


def test_safe_audit_response_summary_hashes_request_and_preview_token():
    payload = {
        "event_type": "preview_created",
        "action": probe.PREVIEW_ACTION,
        "request_id": "req-preview-secret",
        "preview_token": "preview-token-secret",
        "host_type": "lms",
        "surface": "preview_panel",
        "workflow_stage": "authoring",
        "preview_kind": "lesson_patch",
        "target_type": "lesson",
        "metadata": {
            "probe": "live_lms_test_course_replay",
            "course_id": "course-1",
            "lesson_id": "lesson-1",
            "approval_token_present": True,
            "raw_content_included": False,
            "raw_lms_document_included": False,
        },
    }
    response = {
        "status": "success",
        "event_type": "preview_created",
        "action": probe.PREVIEW_ACTION,
        "request_id": "req-preview-secret",
    }

    summary = probe._safe_audit_response_summary(
        payload=payload,
        status_code=200,
        response_body=response,
    )
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["status"] == "success"
    assert summary["request_id_hash_matches_payload"] is True
    assert summary["event_type_matches_payload"] is True
    assert summary["action_matches_payload"] is True
    assert summary["preview_token_hash"]
    assert summary["preview_token_hash_present"] is True
    assert summary["request_id_hash"]
    assert summary["request_id_hash_present"] is True
    assert summary["metadata_course_id_hash_present"] is True
    assert summary["metadata_lesson_id_hash_present"] is True
    assert summary["metadata_raw_content_included"] is False
    assert summary["metadata_raw_lms_document_included"] is False
    assert "preview-token-secret" not in rendered
    assert "req-preview-secret" not in rendered


def test_external_lms_apply_payload_uses_preview_patch_without_raw_evidence_output():
    payload = probe._build_external_lms_apply_payload(
        args=_args(course_id="course-1", lesson_id="lesson-1"),
        host_action={
            "request_id": "req-preview-1",
            "params": {
                "course_id": "course-from-preview",
                "lesson_id": "lesson-from-preview",
                "title": "Preview title",
                "content": "Preview lesson content",
                "source_references": [{"page_start": 1}],
            },
        },
        audit_payloads={"preview_token": "preview-token-secret"},
        request_id="run-1",
    )

    assert payload["operation"] == "apply_lesson_patch"
    assert payload["course_id"] == "course-from-preview"
    assert payload["lesson_id"] == "lesson-from-preview"
    assert payload["preview_token"] == "preview-token-secret"
    assert payload["source_reference_count"] == 1


def test_safe_external_lms_write_summary_hashes_credentials_and_payload():
    request_payload = {
        "course_id": "course-secret",
        "lesson_id": "lesson-secret",
        "preview_request_id": "req-preview-secret",
        "preview_token": "preview-token-secret",
        "content": "raw lesson content",
        "source_reference_count": 2,
    }

    summary = probe._safe_external_lms_write_summary(
        payload=request_payload,
        endpoint_url="https://lms.example.test/private/apply",
        credential_token="external-lms-token-secret",
        request_id="run-secret",
        status_code=202,
        response_body={"status": "accepted", "resource_id": "external-lesson-secret"},
    )
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["schema_version"] == probe.EXTERNAL_LMS_WRITE_SCHEMA_VERSION
    assert summary["write_attempted"] is True
    assert summary["write_acknowledged"] is True
    assert summary["status_code_ok"] is True
    assert summary["endpoint_hash_present"] is True
    assert summary["credential_hash_present"] is True
    assert summary["payload_content_hash_present"] is True
    assert summary["payload_source_reference_count"] == 2
    assert summary["response_resource_hash_present"] is True
    assert summary["raw_request_payload_included"] is False
    assert summary["raw_response_payload_included"] is False
    assert summary["raw_credential_included"] is False
    assert "external-lms-token-secret" not in rendered
    assert "https://lms.example.test/private/apply" not in rendered
    assert "raw lesson content" not in rendered
    assert "preview-token-secret" not in rendered
    assert "external-lesson-secret" not in rendered


def test_source_contract_requires_runtime_provenance_and_audit_count_parity():
    contract = probe._build_source_contract(
        stream_summary=_passing_stream_summary(),
        host_action_summary=_passing_host_action_summary(),
        preview_audit=_passing_preview_audit(),
        apply_audit=_passing_apply_audit(),
    )

    assert contract["provenance_source_ref_count_matches_runtime"] is True
    assert contract["host_action_source_ref_count_matches_runtime"] is True
    assert contract["preview_audit_source_ref_count_matches_runtime"] is True
    assert contract["apply_audit_source_ref_count_matches_runtime"] is True
    assert contract["provenance_privacy_hash_count_only"] is True


def test_audit_sequence_contract_links_apply_to_preview_request():
    contract = probe._build_audit_sequence_contract(
        host_action_summary=_passing_host_action_summary(),
        preview_audit=_passing_preview_audit(),
        apply_audit=_passing_apply_audit(),
    )

    assert contract["event_count"] == 2
    assert contract["events"][0]["stage"] == "preview"
    assert contract["events"][1]["stage"] == "apply"
    assert contract["preview_request_linked_to_apply"] is True
    assert contract["shared_preview_token_hash"] is True


def test_lms_replay_evidence_rejects_apply_before_approval():
    with pytest.raises(RuntimeError, match="apply"):
        probe._assert_lms_replay_evidence(
            stream_summary=_passing_stream_summary(apply_attempted=True),
            host_action_summary=_passing_host_action_summary(),
            preview_audit=_passing_preview_audit(),
            apply_audit=_passing_apply_audit(),
            source_contract=_passing_source_contract(),
            audit_sequence_contract=_passing_audit_sequence_contract(),
            evidence_contract=_passing_evidence_contract(),
            external_lms_write=_passing_external_lms_write(),
            approval_token="approval-secret",
        )


def test_lms_replay_evidence_rejects_unlinked_apply_audit():
    with pytest.raises(RuntimeError, match="linked"):
        probe._assert_lms_replay_evidence(
            stream_summary=_passing_stream_summary(),
            host_action_summary=_passing_host_action_summary(),
            preview_audit=_passing_preview_audit(),
            apply_audit=_passing_apply_audit(),
            source_contract=_passing_source_contract(),
            audit_sequence_contract=_passing_audit_sequence_contract(
                preview_request_linked_to_apply=False
            ),
            evidence_contract=_passing_evidence_contract(),
            external_lms_write=_passing_external_lms_write(),
            approval_token="approval-secret",
        )


def test_lms_replay_evidence_rejects_source_count_mismatch():
    with pytest.raises(RuntimeError, match="source"):
        probe._assert_lms_replay_evidence(
            stream_summary=_passing_stream_summary(),
            host_action_summary=_passing_host_action_summary(),
            preview_audit=_passing_preview_audit(),
            apply_audit=_passing_apply_audit(),
            source_contract=_passing_source_contract(
                provenance_source_ref_count_matches_runtime=False
            ),
            audit_sequence_contract=_passing_audit_sequence_contract(),
            evidence_contract=_passing_evidence_contract(),
            external_lms_write=_passing_external_lms_write(),
            approval_token="approval-secret",
        )


def test_lms_replay_evidence_rejects_missing_external_lms_write_ack():
    with pytest.raises(RuntimeError, match="external LMS write"):
        probe._assert_lms_replay_evidence(
            stream_summary=_passing_stream_summary(),
            host_action_summary=_passing_host_action_summary(),
            preview_audit=_passing_preview_audit(),
            apply_audit=_passing_apply_audit(),
            source_contract=_passing_source_contract(),
            audit_sequence_contract=_passing_audit_sequence_contract(),
            evidence_contract=_passing_evidence_contract(),
            external_lms_write=_passing_external_lms_write(
                write_acknowledged=False,
                status_code_ok=False,
            ),
            approval_token="approval-secret",
        )


def test_lms_replay_evidence_accepts_hash_count_contract():
    probe._assert_lms_replay_evidence(
        stream_summary=_passing_stream_summary(),
        host_action_summary=_passing_host_action_summary(),
        preview_audit=_passing_preview_audit(),
        apply_audit=_passing_apply_audit(),
        source_contract=_passing_source_contract(),
        audit_sequence_contract=_passing_audit_sequence_contract(),
        evidence_contract=_passing_evidence_contract(),
        external_lms_write=_passing_external_lms_write(),
        approval_token="approval-secret",
    )
