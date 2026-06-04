from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "probe_live_proactive_channel.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_live_proactive_channel",
    SCRIPT_PATH,
)
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)

PREFLIGHT_VALIDATOR_PATH = (
    Path(__file__).parents[3]
    / "tools"
    / "wiii_self_harness"
    / "validate_runtime_evidence_preflight.py"
)
PREFLIGHT_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_runtime_evidence_preflight",
    PREFLIGHT_VALIDATOR_PATH,
)
preflight_validator = importlib.util.module_from_spec(PREFLIGHT_VALIDATOR_SPEC)
sys.modules[PREFLIGHT_VALIDATOR_SPEC.name] = preflight_validator
assert PREFLIGHT_VALIDATOR_SPEC.loader is not None
PREFLIGHT_VALIDATOR_SPEC.loader.exec_module(preflight_validator)


def _args(**overrides):
    values = {
        "allow_send": False,
        "allow_production": False,
        "channel": "telegram",
        "recipient_id": "safe-recipient",
        "organization_id": "org-A",
        "message": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _assert_proactive_preflight_valid(payload: dict, tmp_path: Path) -> None:
    preflight_path = tmp_path / "autonomy-proactive-channel-preflight.json"
    preflight_path.write_text(
        json.dumps(payload["preflight"], sort_keys=True),
        encoding="utf-8",
    )
    validation = preflight_validator.validate_preflight(
        preflight_path,
        requirement_id="autonomy-proactive-channel",
    )
    assert validation.ok, validation.to_dict()


def test_live_proactive_channel_probe_guard_requires_allow_send(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--allow-send"):
        probe._require_live_send(_args())


def test_live_proactive_channel_probe_guard_requires_env_flag(monkeypatch):
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    with pytest.raises(SystemExit, match=probe.ENV_FLAG):
        probe._require_live_send(_args(allow_send=True))


def test_live_proactive_channel_probe_guard_rejects_production_without_ack(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(SystemExit, match="--allow-production"):
        probe._require_live_send(_args(allow_send=True))


def test_live_proactive_channel_probe_guard_allows_production_with_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    probe._require_live_send(_args(allow_send=True, allow_production=True))


def test_live_proactive_channel_probe_guard_requires_recipient(monkeypatch):
    monkeypatch.setenv(probe.ENV_FLAG, "1")

    with pytest.raises(SystemExit, match="--recipient-id"):
        probe._require_live_send(_args(allow_send=True, recipient_id=" "))


def test_failure_payload_redacts_recipient_message_org_and_secret_fields(tmp_path):
    recipient_id = "telegram-recipient-private"
    organization_id = "org-private-proactive"
    message = "Private proactive outbound message"
    raw_uuid = "123e4567-e89b-12d3-a456-426614174000"

    payload = probe._failure_payload(
        RuntimeError(
            "Proactive send failed for "
            f"{raw_uuid} {recipient_id} {organization_id} {message} "
            "TELEGRAM_BOT_TOKEN=raw-token FACEBOOK_PAGE_ACCESS_TOKEN=raw-token "
            "ZALO_OA_ACCESS_TOKEN=raw-token access_token api_key authorization"
        ),
        _args(
            allow_send=True,
            channel="telegram",
            recipient_id=recipient_id,
            organization_id=organization_id,
            message=message,
        ),
    )
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["error_code"] == "proactive_channel_failed"
    assert payload["requested_channel"] == "telegram"
    assert payload["live_send_attempted"] is False
    assert payload["setup_contract"]["version"] == probe.SETUP_CONTRACT_VERSION
    assert payload["setup_contract"]["requirement_id"] == "autonomy-proactive-channel"
    assert payload["setup_contract"]["required_next"] == payload["required_next"]
    assert payload["preflight"]["schema_version"] == probe.PREFLIGHT_SCHEMA_VERSION
    assert payload["preflight"]["live_send_attempted"] is False
    _assert_proactive_preflight_valid(payload, tmp_path)
    assert payload["privacy"]["identifier_strategy"] == "hash_or_count_only"
    assert payload["privacy"]["failure_error_redacted"] is True
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["raw_message_included"] is False
    assert payload["privacy"]["raw_recipient_identifier_included"] is False
    assert payload["privacy"]["raw_organization_identifier_included"] is False
    assert payload["privacy"]["raw_channel_credentials_included"] is False
    assert payload["privacy"]["raw_delivery_payload_included"] is False
    assert payload["privacy"]["raw_metric_payload_included"] is False
    assert payload["privacy"]["credential_name_value_pair_included"] is False
    assert payload["privacy"]["raw_trigger_target_included"] is False
    assert payload["privacy"]["metric_labels_include_identifiers"] is False
    assert payload["privacy"]["raw_secret_included"] is False
    assert raw_uuid not in rendered
    assert recipient_id not in rendered
    assert organization_id not in rendered
    assert message not in rendered
    assert "selected_channel_credential" in rendered
    assert "TELEGRAM_BOT_TOKEN=" not in rendered
    assert "FACEBOOK_PAGE_ACCESS_TOKEN=" not in rendered
    assert "ZALO_OA_ACCESS_TOKEN=" not in rendered
    assert "raw-token" not in rendered
    assert "access_token" not in rendered
    assert "api_key" not in rendered
    assert "authorization" not in rendered
    assert probe.IDENTIFIER_RE.search(rendered) is None


def test_live_guard_failure_writes_diagnostic_evidence_artifact(
    tmp_path,
    monkeypatch,
):
    raw_recipient = "private-telegram-recipient"
    raw_org = "private-proactive-org"
    out = tmp_path / "autonomy-proactive-channel-evidence.json"
    monkeypatch.delenv(probe.ENV_FLAG, raising=False)

    code = asyncio.run(
        probe.async_main(
            [
                "--allow-send",
                "--channel",
                "telegram",
                "--recipient-id",
                raw_recipient,
                "--organization-id",
                raw_org,
                "--out",
                str(out),
            ]
        )
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, sort_keys=True)
    assert code == 1
    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["requested_channel"] == "telegram"
    assert payload["live_send_attempted"] is False
    assert "set_live_proactive_channel_probe_env_flag" in payload["required_next"]
    assert payload["setup_contract"]["version"] == probe.SETUP_CONTRACT_VERSION
    assert payload["setup_contract"]["dispatch_ready"] is False
    assert payload["preflight"]["schema_version"] == probe.PREFLIGHT_SCHEMA_VERSION
    assert payload["preflight"]["setup_contract"] == payload["setup_contract"]
    _assert_proactive_preflight_valid(payload, tmp_path)
    assert payload["privacy"]["raw_recipient_identifier_included"] is False
    assert payload["privacy"]["raw_organization_identifier_included"] is False
    assert raw_recipient not in rendered
    assert raw_org not in rendered
    assert "TELEGRAM_BOT_TOKEN" not in rendered


def test_failure_from_preflight_writes_diagnostic_evidence_without_send(
    tmp_path,
    monkeypatch,
):
    from app.core.config import settings

    out = tmp_path / "autonomy-proactive-channel-evidence.json"
    preflight_path = tmp_path / "autonomy-proactive-channel-preflight.json"
    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "development")
    preflight_payload = probe._build_proactive_channel_preflight(
        _args(allow_send=True, channel="messenger", recipient_id="safe-recipient"),
        channel_state={
            "enabled": False,
            "credential_present": False,
            "credential_name": "FACEBOOK_PAGE_ACCESS_TOKEN",
        },
    )
    assert preflight_payload["status"] == "fail"
    preflight_path.write_text(
        json.dumps(preflight_payload, sort_keys=True),
        encoding="utf-8",
    )

    async def forbidden_probe(args):
        raise AssertionError("failure-from-preflight must not send")

    monkeypatch.setattr(probe, "_run_probe", forbidden_probe)

    code = asyncio.run(
        probe.async_main(
            [
                "--failure-from-preflight",
                "--failure-preflight-json",
                str(preflight_path),
                "--allow-send",
                "--channel",
                "telegram",
                "--recipient-id",
                "private-telegram-recipient",
                "--organization-id",
                "private-proactive-org",
                "--out",
                str(out),
            ]
        )
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, sort_keys=True)
    assert code == 1
    assert payload["schema_version"] == probe.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["requested_channel"] == "messenger"
    assert payload["required_next"] == preflight_payload["required_next"]
    assert payload["setup_contract"] == preflight_payload["setup_contract"]
    assert payload["preflight"]["requested_channel"] == "messenger"
    assert payload["preflight"]["live_send_attempted"] is False
    _assert_proactive_preflight_valid(payload, tmp_path)
    assert "private-telegram-recipient" not in rendered
    assert "private-proactive-org" not in rendered
    assert "FACEBOOK_PAGE_ACCESS_TOKEN" not in rendered


def test_channel_config_reports_credential_presence_without_secret_value():
    settings = SimpleNamespace(
        enable_telegram=True,
        telegram_bot_token="raw-telegram-token",
        facebook_page_access_token="raw-facebook-token",
        enable_zalo=True,
        zalo_oa_access_token="raw-zalo-token",
    )

    telegram = probe._channel_config(settings, "telegram")
    messenger = probe._channel_config(settings, "messenger")
    zalo = probe._channel_config(settings, "zalo")
    rendered = json.dumps([telegram, messenger, zalo], sort_keys=True)

    assert telegram["enabled"] is True
    assert telegram["credential_present"] is True
    assert messenger["credential_name"] == "FACEBOOK_PAGE_ACCESS_TOKEN"
    assert zalo["credential_present"] is True
    assert "raw-telegram-token" not in rendered
    assert "raw-facebook-token" not in rendered
    assert "raw-zalo-token" not in rendered


def test_proactive_channel_preflight_reports_missing_live_requirements(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.delenv(probe.ENV_FLAG, raising=False)
    monkeypatch.setattr(settings, "environment", "development")

    summary = probe._build_proactive_channel_preflight(
        _args(allow_send=False, recipient_id=" "),
        channel_state={
            "enabled": False,
            "credential_present": False,
            "credential_name": "TELEGRAM_BOT_TOKEN",
        },
    )
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["schema_version"] == probe.PREFLIGHT_SCHEMA_VERSION
    assert summary["status"] == "fail"
    assert summary["live_send_attempted"] is False
    assert summary["recipient_id_present"] is False
    assert summary["channel_config"]["credential_name_included"] is False
    assert summary["privacy"]["credential_names_included"] is False
    assert "pass_allow_send" in summary["required_next"]
    assert "set_live_proactive_channel_probe_env_flag" in summary["required_next"]
    assert "provide_recipient_id" in summary["required_next"]
    assert "enable_selected_channel" in summary["required_next"]
    assert "configure_selected_channel_credential" in summary["required_next"]
    assert summary["setup_contract"]["version"] == probe.SETUP_CONTRACT_VERSION
    assert summary["setup_contract"]["requirement_id"] == "autonomy-proactive-channel"
    assert summary["setup_contract"]["required_next"] == summary["required_next"]
    assert summary["setup_contract"]["dispatch_ready"] is False
    assert (
        "selected_channel_credential"
        in summary["setup_contract"]["credential_slots_required"]
    )
    assert "approved_recipient" in summary["setup_contract"]["external_setup_required"]
    assert "TELEGRAM_BOT_TOKEN" not in rendered


def test_proactive_channel_preflight_passes_without_sending(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "development")

    summary = probe._build_proactive_channel_preflight(
        _args(allow_send=True, channel="messenger", recipient_id="safe-recipient"),
        channel_state={
            "enabled": True,
            "credential_present": True,
            "credential_name": "FACEBOOK_PAGE_ACCESS_TOKEN",
        },
    )
    rendered = json.dumps(summary, sort_keys=True)

    assert summary["status"] == "pass"
    assert summary["requested_channel"] == "messenger"
    assert summary["allow_send_acknowledged"] is True
    assert summary["live_env_flag_set"] is True
    assert summary["recipient_id_present"] is True
    assert summary["live_send_attempted"] is False
    assert summary["required_next"] == []
    assert summary["setup_contract"]["dispatch_ready"] is True
    assert summary["setup_contract"]["required_next"] == []
    assert summary["privacy"]["raw_recipient_identifier_included"] is False
    assert "safe-recipient" not in rendered
    assert "FACEBOOK_PAGE_ACCESS_TOKEN" not in rendered


def test_proactive_channel_preflight_requires_production_ack(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv(probe.ENV_FLAG, "1")
    monkeypatch.setattr(settings, "environment", "production")

    summary = probe._build_proactive_channel_preflight(
        _args(allow_send=True, allow_production=False),
        channel_state={
            "enabled": True,
            "credential_present": True,
            "credential_name": "TELEGRAM_BOT_TOKEN",
        },
    )

    assert summary["status"] == "fail"
    assert summary["production_environment"] is True
    assert "pass_allow_production" in summary["required_next"]


def test_metric_helpers_report_allowed_and_delivered_counts():
    metrics = {
        "counters": {
            "runtime.living_agent.proactive.can_send": {
                (("reason", "allowed"), ("status", "allowed")): 1,
            },
            "runtime.living_agent.proactive.sends": {
                (("status", "delivered"),): 1,
            },
        },
        "histograms": {
            "runtime.living_agent.proactive.send_duration_ms": {
                (("status", "delivered"),): [12.5],
            },
        },
    }

    assert (
        probe._metric_event_count(
            metrics,
            "runtime.living_agent.proactive.can_send",
        )
        == 1
    )
    assert probe._metric_label_seen(
        metrics,
        "runtime.living_agent.proactive.can_send",
        expected={"status": "allowed", "reason": "allowed"},
    )
    assert probe._metric_label_seen(
        metrics,
        "runtime.living_agent.proactive.sends",
        expected={"status": "delivered"},
    )
    assert probe._metric_histogram_values(
        metrics,
        "runtime.living_agent.proactive.send_duration_ms",
        expected={"status": "delivered"},
    ) == [12.5]
    assert not probe._metric_labels_include_identifier(
        metrics,
        ("safe-recipient", "org-A", "private message"),
    )
    assert (
        probe._metric_label_count(
            metrics,
            "runtime.living_agent.proactive.can_send",
            expected={"status": "allowed", "reason": "allowed"},
        )
        == 1
    )
    rendered = json.dumps(
        probe._metric_counter_map(
            metrics,
            "runtime.living_agent.proactive.can_send",
        ),
        sort_keys=True,
    )
    assert "allowed" in rendered


def test_proactive_channel_summary_rejects_raw_message_flag():
    summary = {
        "status": "pass",
        "delivered": True,
        "recipient_id_hash_present": True,
        "organization_id_hash_present": True,
        "message_hash_present": True,
        "database": {
            "connection_verified": True,
            "opt_out_lookup_verifiable": True,
            "send_audit_verifiable": True,
            "opt_out_scope_request_org": True,
            "send_audit_scope_request_org": True,
            "raw_connection_details_included": False,
        },
        "evidence_contract": {
            "single_outbound_send": True,
            "uses_proactive_messenger": True,
            "requires_live_channel_credentials": True,
            "requires_database_guardrail": True,
        },
        "org_scope": {
            "context_token_set": True,
            "organization_id_hash_present": True,
            "write_scope_expected": "request_scoped",
            "raw_organization_identifier_included": False,
        },
        "operator_approval": {
            "allow_send_acknowledged": True,
            "approved_recipient_hash_present": True,
            "raw_recipient_identifier_included": False,
            "raw_message_included": False,
        },
        "guardrail": {
            "allowed": True,
            "reason_allowed": True,
            "blocked_metric_count": 0,
            "database_opt_out_check_used": True,
            "opt_out_checked_via_database": True,
        },
        "delivery": {
            "channel": "telegram",
            "delivered": True,
            "channel_matches_request": True,
            "duration_observed": True,
            "duration_ms_min": 12.5,
            "duration_ms_count": 1,
            "raw_delivery_payload_included": False,
        },
        "send_attempt": {
            "channel_supported": True,
            "single_send_attempt": True,
            "recipient_id_hash_present": True,
            "organization_id_hash_present": True,
            "message_hash_present": True,
            "raw_message_included": False,
        },
        "channel_contract": {
            "requested_channel_supported": True,
            "requested_channel_matches_delivery": True,
            "credential_value_included": False,
            "credential_name_value_pair_included": False,
        },
        "channel_config": {
            "supported": True,
            "enabled": True,
            "credential_present": True,
            "credential_name": "TELEGRAM_BOT_TOKEN",
            "credential_value_included": False,
        },
        "metrics": {
            "can_send_allowed_seen": True,
            "send_delivered_seen": True,
            "can_send_allowed_count": 1,
            "send_delivered_count": 1,
            "send_duration_count": 1,
            "send_duration_observed": True,
            "duration_metric_label_status_delivered_seen": True,
            "send_duration_ms_min": 12.5,
            "metric_labels_include_identifiers": False,
            "metric_label_strategy": "bounded_status_reason_channel_only",
            "raw_metric_payload_included": False,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_message_included": True,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_channel_credentials_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "credential_name_value_pair_included": False,
            "raw_trigger_target_included": False,
            "metric_labels_include_identifiers": False,
        },
    }

    with pytest.raises(RuntimeError, match="raw_message_included"):
        probe._assert_proactive_channel_summary(summary)


def test_proactive_channel_summary_accepts_structured_privacy_contract():
    summary = {
        "status": "pass",
        "delivered": True,
        "recipient_id_hash_present": True,
        "organization_id_hash_present": True,
        "message_hash_present": True,
        "database": {
            "connection_verified": True,
            "opt_out_lookup_verifiable": True,
            "send_audit_verifiable": True,
            "opt_out_scope_request_org": True,
            "send_audit_scope_request_org": True,
            "raw_connection_details_included": False,
        },
        "evidence_contract": {
            "single_outbound_send": True,
            "uses_proactive_messenger": True,
            "requires_live_channel_credentials": True,
            "requires_database_guardrail": True,
        },
        "org_scope": {
            "context_token_set": True,
            "organization_id_hash_present": True,
            "write_scope_expected": "request_scoped",
            "raw_organization_identifier_included": False,
        },
        "operator_approval": {
            "allow_send_acknowledged": True,
            "approved_recipient_hash_present": True,
            "raw_recipient_identifier_included": False,
            "raw_message_included": False,
        },
        "guardrail": {
            "allowed": True,
            "reason_allowed": True,
            "blocked_metric_count": 0,
            "database_opt_out_check_used": True,
            "opt_out_checked_via_database": True,
        },
        "delivery": {
            "channel": "telegram",
            "delivered": True,
            "channel_matches_request": True,
            "duration_observed": True,
            "duration_ms_min": 8.0,
            "duration_ms_count": 1,
            "raw_delivery_payload_included": False,
        },
        "send_attempt": {
            "channel_supported": True,
            "single_send_attempt": True,
            "recipient_id_hash_present": True,
            "organization_id_hash_present": True,
            "message_hash_present": True,
            "raw_message_included": False,
        },
        "channel_contract": {
            "requested_channel_supported": True,
            "requested_channel_matches_delivery": True,
            "credential_value_included": False,
            "credential_name_value_pair_included": False,
        },
        "channel_config": {
            "supported": True,
            "enabled": True,
            "credential_present": True,
            "credential_name": "TELEGRAM_BOT_TOKEN",
            "credential_value_included": False,
        },
        "metrics": {
            "can_send_allowed_seen": True,
            "send_delivered_seen": True,
            "send_duration_observed": True,
            "duration_metric_label_status_delivered_seen": True,
            "metric_labels_include_identifiers": False,
            "metric_label_strategy": "bounded_status_reason_channel_only",
            "raw_metric_payload_included": False,
            "can_send_allowed_count": 1,
            "send_delivered_count": 1,
            "send_duration_count": 1,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_message_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_channel_credentials_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "credential_name_value_pair_included": False,
            "raw_trigger_target_included": False,
            "metric_labels_include_identifiers": False,
        },
    }

    probe._assert_proactive_channel_summary(summary)


def test_proactive_channel_probe_contract_has_supported_channels_and_schema():
    assert probe.SCHEMA_VERSION == "wiii.live_proactive_channel_probe.v1"
    assert probe.PREFLIGHT_SCHEMA_VERSION == "wiii.proactive_channel_preflight.v1"
    assert probe.ENV_FLAG == "WIII_LIVE_PROACTIVE_CHANNEL_PROBE"
    assert probe.SUPPORTED_CHANNELS == {"telegram", "messenger", "zalo"}
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--preflight-only" in source
    assert "--failure-from-preflight" in source
    assert "--failure-preflight-json" in source
    assert "live_send_attempted" in source
    assert "wiii.live_evidence_setup_contract.v1" in source
    assert "setup_contract" in source
    assert "selected_channel_credential" in source
    assert "recipient_id_hash_present" in source
    assert "organization_id_hash_present" in source
    assert "message_hash_present" in source
    assert "credential_value_included" in source
    assert "raw_channel_credentials_included" in source
    assert "can_send_allowed_seen" in source
    assert "send_delivered_seen" in source
    assert "send_duration_observed" in source
    assert "duration_metric_label_status_delivered_seen" in source
    assert "bounded_status_reason_channel_only" in source
    assert "single_outbound_send" in source
    assert "database_opt_out_check_used" in source
    assert "metric_labels_include_identifiers" in source
    assert "opt_out_lookup_verifiable" in source
    assert "opt_out_scope_request_org" in source
    assert "raw_delivery_payload_included" in source
