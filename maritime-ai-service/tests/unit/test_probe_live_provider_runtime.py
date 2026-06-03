from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_provider_runtime.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_provider_runtime",
    SCRIPT_PATH,
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


def _args(**overrides):
    values = {
        "allow_call": False,
        "preflight_only": False,
        "include_stream_ledger": False,
        "allow_stream_write": False,
        "allow_production": False,
        "provider": "auto",
        "stream_provider": "",
        "tier": "light",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _passing_provider_summary(**overrides):
    summary = {
        "evidence_contract": {
            "credentialed_provider_call_required": True,
            "tool_roundtrip_required": True,
            "single_tool_call_required": True,
            "tool_result_linkage_required": True,
            "followup_without_extra_tool_calls_required": True,
            "trace_span_pair_required": True,
            "stream_ledger_optional": True,
            "stream_ledger_requires_allow_stream_write": True,
            "hash_count_only_output": True,
        },
        "direct_provider_tool_roundtrip": {
            "runtime_boundary": {
                "llm_pool_route_used": True,
                "wiii_chat_model_interface_used": True,
                "native_message_contract_used": True,
                "raw_provider_http_used": False,
                "raw_provider_payload_included": False,
                "raw_provider_response_included": False,
            },
            "tool_contract": {
                "tool_name_matches_probe": True,
                "forced_tool_choice_used": True,
                "additional_properties_allowed": False,
                "raw_schema_values_included": False,
            },
        },
        "stream_runtime_ledger": {"status": "skipped"},
    }
    summary.update(overrides)
    return summary


def test_live_provider_probe_guard_requires_allow_call(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-call"):
        probe._require_live_call(_args())


def test_live_provider_probe_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_call(_args(allow_call=True))


def test_live_provider_probe_guard_rejects_production_without_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_call(_args(allow_call=True))


def test_live_provider_probe_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_call(_args(allow_call=True, allow_production=True))


def test_live_provider_probe_guard_requires_stream_write_ack(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-stream-write"):
        probe._require_live_call(
            _args(allow_call=True, include_stream_ledger=True),
        )


def test_failure_payload_redacts_provider_scope_prompt_and_secret_fields():
    api_key = "provider-private-api-key"
    session_id = "provider-private-session"
    user_id = "provider-private-user"
    organization_id = "provider-private-org"
    request_id = "provider-private-request"
    stream_prompt = "Private provider stream prompt"
    raw_uuid = "123e4567-e89b-12d3-a456-426614174000"

    payload = probe._failure_payload(
        RuntimeError(
            "Provider failed for "
            f"{raw_uuid} {api_key} {session_id} {user_id} {organization_id} "
            f"{request_id} {stream_prompt} "
            '"label": "provider_runtime_probe" record_probe_fact value '
            "VERTEX_API_KEY=raw-token api_key access_token authorization"
        ),
        _args(
            allow_call=True,
            provider="vertex",
            api_key=api_key,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            request_id=request_id,
            stream_prompt=stream_prompt,
        ),
    )
    rendered = json.dumps(payload, sort_keys=True)
    error_message = payload["error_message"]

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "provider_runtime_failed"
    assert payload["privacy"]["identifier_strategy"] == "hashes_and_counts"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["tool_argument_values_included"] is False
    assert payload["privacy"]["provider_arguments_included"] is False
    assert payload["privacy"]["provider_payload_included"] is False
    assert payload["privacy"]["provider_response_included"] is False
    assert payload["privacy"]["stream_payload_included"] is False
    assert payload["privacy"]["raw_request_identifiers_included"] is False
    assert payload["privacy"]["raw_secret_included"] is False
    assert raw_uuid not in rendered
    assert api_key not in rendered
    assert session_id not in rendered
    assert user_id not in rendered
    assert organization_id not in rendered
    assert request_id not in rendered
    assert stream_prompt not in rendered
    assert '"label": "provider_runtime_probe"' not in error_message
    assert "provider_runtime_probe" not in error_message
    assert "record_probe_fact value" not in error_message
    assert "VERTEX_API_KEY=" not in rendered
    assert "VERTEX_" not in error_message
    assert "api_key" not in rendered
    assert "access_token" not in rendered
    assert "authorization" not in rendered
    assert probe.IDENTIFIER_RE.search(rendered) is None


def test_provider_runtime_preflight_passes_for_auto_selectable_provider(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "development")

    summary = probe._build_provider_runtime_preflight(
        _args(allow_call=True, provider="auto"),
        provider_rows=[
            {
                "provider": "google",
                "configured": True,
                "request_selectable": True,
            },
        ],
    )

    assert summary["schema_version"] == probe.PREFLIGHT_SCHEMA_VERSION
    assert summary["status"] == "pass"
    assert summary["provider_status_counts"]["request_selectable"] == 1
    assert summary["required_next"] == []


def test_provider_runtime_preflight_reports_missing_selected_provider(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "development")

    summary = probe._build_provider_runtime_preflight(
        _args(allow_call=True, provider="vertex"),
        provider_rows=[
            {
                "provider": "vertex",
                "configured": False,
                "request_selectable": False,
            },
        ],
    )

    rendered = json.dumps(summary, sort_keys=True)

    assert summary["status"] == "fail"
    assert summary["selected_provider"] == "vertex"
    assert "configure_selected_provider" in summary["required_next"]
    assert summary["privacy"]["secret_values_included"] is False
    assert summary["privacy"]["credential_names_included"] is False
    assert "VERTEX_API_KEY" not in rendered
    assert "vertex-api-secret-value" not in rendered


def test_provider_runtime_preflight_reports_stream_write_ack(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "development")

    summary = probe._build_provider_runtime_preflight(
        _args(
            allow_call=True,
            include_stream_ledger=True,
            allow_stream_write=False,
        ),
        provider_rows=[
            {
                "provider": "google",
                "configured": True,
                "request_selectable": True,
            },
        ],
    )

    assert summary["status"] == "fail"
    assert "pass_allow_stream_write" in summary["required_next"]


def test_extract_last_runtime_flow_ledger_prefers_terminal_event():
    metadata_ledger = {"runtime": {"provider": "google"}}
    done_ledger = {"runtime": {"provider": "zhipu"}, "stream": {"done_seen": True}}

    extracted = probe._extract_last_runtime_flow_ledger(
        [
            {"event": "metadata", "data": {"runtime_flow_ledger": metadata_ledger}},
            {"event": "answer", "data": {"content": "ignored"}},
            {"event": "done", "data": {"runtime_flow_ledger": done_ledger}},
        ],
    )

    assert extracted == done_ledger


def test_safe_tool_call_summary_omits_argument_values_and_raw_id():
    tool_call = SimpleNamespace(
        id="provider-call-id-123",
        name=probe.TOOL_NAME,
        arguments={"label": "provider_runtime_probe", "value": "live"},
    )

    summary = probe._safe_tool_call_summary(tool_call)
    rendered = __import__("json").dumps(summary, sort_keys=True)

    assert summary["name"] == probe.TOOL_NAME
    assert summary["id_hash_present"] is True
    assert summary["argument_keys"] == ["label", "value"]
    assert summary["argument_values_included"] is False
    assert summary["raw_id_included"] is False
    assert "provider_runtime_probe" not in rendered
    assert "provider-call-id-123" not in rendered


def test_safe_tool_result_summary_omits_content_values_and_raw_id():
    tool_result = SimpleNamespace(
        role="tool",
        tool_call_id="provider-call-id-123",
        content='{"ok": true, "observed_at": "2026-06-01T00:00:00Z", "label": "provider_runtime_probe"}',
    )

    summary = probe._safe_tool_result_summary(tool_result)
    rendered = __import__("json").dumps(summary, sort_keys=True)

    assert summary["role"] == "tool"
    assert summary["tool_call_id_hash_present"] is True
    assert summary["content_json_keys"] == ["label", "observed_at", "ok"]
    assert summary["content_json_key_count"] == 3
    assert summary["content_json_values_included"] is False
    assert summary["raw_content_included"] is False
    assert summary["raw_tool_call_id_included"] is False
    assert "provider_runtime_probe" not in rendered
    assert "provider-call-id-123" not in rendered


def test_safe_span_summary_omits_span_attributes_and_tracks_duration():
    spans = [
        SimpleNamespace(
            name="live_provider_runtime_probe.tool_call",
            status="success",
            duration_ms=1.25,
        ),
        SimpleNamespace(
            name="live_provider_runtime_probe.tool_result",
            status="success",
            duration_ms=2,
        ),
    ]

    summary = probe._safe_span_summary(spans)

    assert summary["span_count"] == 2
    assert summary["tool_call_span_seen"] is True
    assert summary["tool_result_span_seen"] is True
    assert summary["duration_observed"] is True
    assert summary["duration_ms_total"] == 3.25
    assert summary["raw_attribute_values_included"] is False


def test_tool_contract_summary_requires_forced_probe_tool_choice():
    summary = probe._tool_contract_summary()

    assert summary["schema_version"] == "wiii.provider_tool_contract.v1"
    assert summary["tool_name"] == probe.TOOL_NAME
    assert summary["tool_name_matches_probe"] is True
    assert summary["forced_tool_choice_used"] is True
    assert summary["required_argument_keys"] == ["label", "value"]
    assert summary["additional_properties_allowed"] is False
    assert summary["raw_schema_values_included"] is False


def test_provider_evidence_contract_rejects_raw_provider_http_boundary():
    summary = _passing_provider_summary()
    summary["direct_provider_tool_roundtrip"]["runtime_boundary"][
        "raw_provider_http_used"
    ] = True

    with pytest.raises(RuntimeError, match="raw_provider_http_used"):
        probe._assert_provider_evidence_contract(summary)


def test_provider_evidence_contract_rejects_unlinked_stream_done_count():
    summary = _passing_provider_summary(
        stream_runtime_ledger={
            "status": "pass",
            "terminal_event_name": "done",
            "done_count_matches_ledger": False,
            "privacy": {"auth_secret_included": False},
        },
    )

    with pytest.raises(RuntimeError, match="done_count_matches_ledger"):
        probe._assert_provider_evidence_contract(summary)


def test_provider_evidence_contract_accepts_hash_count_contract():
    probe._assert_provider_evidence_contract(_passing_provider_summary())


def test_stream_provider_falls_back_to_auto_for_vertex_direct_route():
    args = _args(provider="auto", stream_provider="")

    assert probe._stream_provider_for_request(args, "vertex") == "auto"
    assert probe._stream_provider_for_request(args, "openai") == "openai"
