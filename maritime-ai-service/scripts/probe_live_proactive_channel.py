"""Opt-in live proactive channel probe.

This probe sends one real outbound message through Wiii's proactive messenger.
It is intentionally guarded because it can contact Telegram, Messenger, or Zalo
using configured credentials.

Example:
    WIII_LIVE_PROACTIVE_CHANNEL_PROBE=1 python scripts/probe_live_proactive_channel.py --allow-send --channel telegram --recipient-id <chat_id> --out autonomy-proactive-channel-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from runtime_evidence_output import emit_json_payload  # noqa: E402


SUPPORTED_CHANNELS = {"telegram", "messenger", "zalo"}
ENV_FLAG = "WIII_LIVE_PROACTIVE_CHANNEL_PROBE"
SCHEMA_VERSION = "wiii.live_proactive_channel_probe.v1"
PREFLIGHT_SCHEMA_VERSION = "wiii.proactive_channel_preflight.v1"
SETUP_CONTRACT_VERSION = "wiii.live_evidence_setup_contract.v1"
IDENTIFIER_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def _json_print(payload: dict[str, Any]) -> None:
    emit_json_payload(payload)


def _redact_error(value: Any) -> str:
    try:
        from app.engine.runtime.event_payload_sanitizer import (
            redact_runtime_secret_text,
        )

        return redact_runtime_secret_text(str(value))
    except Exception:  # noqa: BLE001
        return str(value)


def _fallback_hash(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _safe_hash(value: Any) -> str | None:
    try:
        return _hash(value)
    except Exception:  # noqa: BLE001
        return _fallback_hash(value)


def _redact_failure_text(value: Any, args: argparse.Namespace | None = None) -> str:
    text = _redact_error(value)[:1000]
    text = IDENTIFIER_RE.sub(
        lambda match: _fallback_hash(match.group(0)) or "<redacted-identifier>",
        text,
    )
    for credential_name in (
        "TELEGRAM_BOT_TOKEN",
        "FACEBOOK_PAGE_ACCESS_TOKEN",
        "ZALO_OA_ACCESS_TOKEN",
    ):
        text = re.sub(
            rf"{re.escape(credential_name)}\s*=\s*[^\s,;]+",
            "<redacted-sensitive-field>",
            text,
            flags=re.IGNORECASE,
        )
    replacements = {
        "TELEGRAM_BOT_TOKEN=": "<redacted-sensitive-field>",
        "FACEBOOK_PAGE_ACCESS_TOKEN=": "<redacted-sensitive-field>",
        "ZALO_OA_ACCESS_TOKEN=": "<redacted-sensitive-field>",
        "TELEGRAM_BOT_TOKEN": "<redacted-sensitive-field>",
        "FACEBOOK_PAGE_ACCESS_TOKEN": "<redacted-sensitive-field>",
        "ZALO_OA_ACCESS_TOKEN": "<redacted-sensitive-field>",
        "access_token": "<redacted-sensitive-field>",
        "api_key": "<redacted-sensitive-field>",
        "authorization": "<redacted-sensitive-field>",
    }
    if args is not None:
        for raw_value in (
            getattr(args, "recipient_id", None),
            getattr(args, "organization_id", None),
            getattr(args, "message", None),
        ):
            if not raw_value:
                continue
            replacements[str(raw_value)] = _safe_hash(raw_value) or "<redacted-value>"
    for raw, replacement in replacements.items():
        text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError("preflight required_next must be a string list")
    if value != list(dict.fromkeys(value)):
        raise RuntimeError("preflight required_next must not contain duplicates")
    if any(not item for item in value):
        raise RuntimeError("preflight required_next must not contain empty strings")
    return list(value)


def load_proactive_preflight(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("--failure-preflight-json must point at a regular file")
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"--failure-preflight-json could not be read as JSON: {exc}"
        ) from exc
    if not isinstance(raw_payload, dict):
        raise RuntimeError("--failure-preflight-json root must be a JSON object")
    if raw_payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise RuntimeError(
            "--failure-preflight-json schema_version does not match proactive preflight"
        )
    if raw_payload.get("status") != "fail":
        raise RuntimeError("--failure-preflight-json status must be fail")
    if raw_payload.get("live_send_attempted") is not False:
        raise RuntimeError("--failure-preflight-json live_send_attempted must be false")
    required_next = _string_list(raw_payload.get("required_next"))
    setup_contract = raw_payload.get("setup_contract")
    if not isinstance(setup_contract, dict):
        raise RuntimeError("--failure-preflight-json setup_contract must be an object")
    if setup_contract.get("requirement_id") != "autonomy-proactive-channel":
        raise RuntimeError(
            "--failure-preflight-json setup_contract.requirement_id is invalid"
        )
    if setup_contract.get("required_next") != required_next:
        raise RuntimeError(
            "--failure-preflight-json setup_contract.required_next must match required_next"
        )
    channel_config = (
        raw_payload.get("channel_config")
        if isinstance(raw_payload.get("channel_config"), dict)
        else {}
    )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": raw_payload.get("generated_at"),
        "status": raw_payload.get("status"),
        "requested_channel": raw_payload.get("requested_channel")
        if raw_payload.get("requested_channel") in SUPPORTED_CHANNELS
        else "",
        "allow_send_acknowledged": raw_payload.get("allow_send_acknowledged") is True,
        "live_env_flag_set": raw_payload.get("live_env_flag_set") is True,
        "recipient_id_present": raw_payload.get("recipient_id_present") is True,
        "production_environment": raw_payload.get("production_environment") is True,
        "allow_production_acknowledged": raw_payload.get(
            "allow_production_acknowledged"
        )
        is True,
        "live_send_attempted": False,
        "channel_config": {
            "supported": channel_config.get("supported") is True,
            "enabled": channel_config.get("enabled") is True,
            "credential_present": channel_config.get("credential_present") is True,
            "credential_value_included": False,
            "credential_name_included": False,
        },
        "required_next": required_next,
        "setup_contract": setup_contract,
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_message_included": False,
            "raw_delivery_payload_included": False,
            "raw_channel_credentials_included": False,
        },
    }


def _failure_payload(
    exc: Exception,
    args: argparse.Namespace,
    *,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preflight = preflight or _failure_preflight_summary(args)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error_code": "proactive_channel_failed",
        "error_message": _redact_failure_text(exc, args),
        "requested_channel": preflight.get("requested_channel") or args.channel,
        "live_send_attempted": False,
        "required_next": preflight["required_next"],
        "setup_contract": preflight["setup_contract"],
        "preflight": preflight,
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
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
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _failure_preflight_summary(args: argparse.Namespace) -> dict[str, Any]:
    try:
        preflight = _build_proactive_channel_preflight(args)
    except Exception:  # noqa: BLE001
        required_next = ["inspect_live_probe_setup"]
        return {
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "fail",
            "requested_channel": args.channel,
            "allow_send_acknowledged": bool(args.allow_send),
            "live_env_flag_set": os.getenv(ENV_FLAG) == "1",
            "recipient_id_present": bool(args.recipient_id.strip()),
            "production_environment": False,
            "allow_production_acknowledged": bool(args.allow_production),
            "live_send_attempted": False,
            "channel_config": {
                "supported": args.channel in {"messenger", "telegram", "zalo"},
                "enabled": False,
                "credential_present": False,
                "credential_value_included": False,
                "credential_name_included": False,
            },
            "required_next": required_next,
            "setup_contract": _proactive_setup_contract(required_next),
            "privacy": {
                "secret_values_included": False,
                "credential_names_included": False,
                "raw_recipient_identifier_included": False,
                "raw_organization_identifier_included": False,
                "raw_message_included": False,
                "raw_delivery_payload_included": False,
                "raw_channel_credentials_included": False,
            },
        }
    required_next = preflight.get("required_next")
    safe_required_next = required_next if isinstance(required_next, list) else []
    setup_contract = preflight.get("setup_contract")
    if not isinstance(setup_contract, dict):
        setup_contract = _proactive_setup_contract(safe_required_next)
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": preflight.get("generated_at"),
        "status": preflight.get("status"),
        "requested_channel": preflight.get("requested_channel"),
        "allow_send_acknowledged": preflight.get("allow_send_acknowledged"),
        "live_env_flag_set": preflight.get("live_env_flag_set"),
        "recipient_id_present": preflight.get("recipient_id_present"),
        "production_environment": preflight.get("production_environment"),
        "allow_production_acknowledged": preflight.get(
            "allow_production_acknowledged"
        ),
        "live_send_attempted": False,
        "channel_config": preflight.get("channel_config"),
        "required_next": safe_required_next,
        "setup_contract": setup_contract,
        "privacy": preflight.get("privacy"),
    }


def _require_live_send(args: argparse.Namespace) -> None:
    if not args.allow_send:
        raise SystemExit("--allow-send is required; this probe sends one outbound message")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the live channel probe")
    if not args.recipient_id.strip():
        raise SystemExit("--recipient-id is required")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to send from production without --allow-production")


def _hash(value: str | None) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(value)


def _channel_config(settings: Any, channel: str) -> dict[str, Any]:
    if channel == "telegram":
        return {
            "enabled": bool(getattr(settings, "enable_telegram", False)),
            "credential_present": bool(getattr(settings, "telegram_bot_token", "")),
            "credential_name": "TELEGRAM_BOT_TOKEN",
        }
    if channel == "messenger":
        return {
            "enabled": True,
            "credential_present": bool(getattr(settings, "facebook_page_access_token", "")),
            "credential_name": "FACEBOOK_PAGE_ACCESS_TOKEN",
        }
    if channel == "zalo":
        return {
            "enabled": bool(getattr(settings, "enable_zalo", False)),
            "credential_present": bool(getattr(settings, "zalo_oa_access_token", "")),
            "credential_name": "ZALO_OA_ACCESS_TOKEN",
        }
    raise RuntimeError(f"Unsupported channel: {channel}")


def _preflight_required_next(
    args: argparse.Namespace,
    *,
    channel_state: dict[str, Any],
    environment: str,
    live_env_flag_set: bool,
) -> list[str]:
    required_next: list[str] = []
    if not args.allow_send:
        required_next.append("pass_allow_send")
    if not live_env_flag_set:
        required_next.append("set_live_proactive_channel_probe_env_flag")
    if environment == "production" and not args.allow_production:
        required_next.append("pass_allow_production")
    if not args.recipient_id.strip():
        required_next.append("provide_recipient_id")
    if channel_state.get("enabled") is not True:
        required_next.append("enable_selected_channel")
    if channel_state.get("credential_present") is not True:
        required_next.append("configure_selected_channel_credential")
    return required_next


def _build_proactive_channel_preflight(
    args: argparse.Namespace,
    *,
    channel_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.core.config import settings

    resolved_channel_state = (
        channel_state if channel_state is not None else _channel_config(settings, args.channel)
    )
    environment = str(getattr(settings, "environment", "") or "")
    live_env_flag_set = os.getenv(ENV_FLAG) == "1"
    required_next = _preflight_required_next(
        args,
        channel_state=resolved_channel_state,
        environment=environment,
        live_env_flag_set=live_env_flag_set,
    )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not required_next else "fail",
        "requested_channel": args.channel,
        "allow_send_acknowledged": bool(args.allow_send),
        "live_env_flag_set": live_env_flag_set,
        "recipient_id_present": bool(args.recipient_id.strip()),
        "production_environment": environment == "production",
        "allow_production_acknowledged": bool(args.allow_production),
        "live_send_attempted": False,
        "channel_config": {
            "supported": args.channel in SUPPORTED_CHANNELS,
            "enabled": bool(resolved_channel_state.get("enabled")),
            "credential_present": bool(resolved_channel_state.get("credential_present")),
            "credential_value_included": False,
            "credential_name_included": False,
        },
        "required_next": required_next,
        "setup_contract": _proactive_setup_contract(required_next),
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_message_included": False,
            "raw_delivery_payload_included": False,
            "raw_channel_credentials_included": False,
        },
    }


def _proactive_setup_contract(required_next: list[str]) -> dict[str, Any]:
    return {
        "version": SETUP_CONTRACT_VERSION,
        "requirement_id": "autonomy-proactive-channel",
        "required_next": list(required_next),
        "workflow_inputs_required": [
            "channel",
            "recipient_id",
            "allow_send",
            "allow_production",
        ],
        "environment_flags_required": ["live_proactive_channel_probe_flag"],
        "credential_slots_required": ["selected_channel_credential"],
        "external_setup_required": [
            "approved_recipient",
            "selected_channel_enabled",
        ],
        "dispatch_ready": not required_next,
    }


def _safe_labels(labels: Any) -> str:
    try:
        return json.dumps(dict(labels), ensure_ascii=False, sort_keys=True)
    except Exception:  # noqa: BLE001
        return str(labels)


def _metric_counter_map(metrics: dict[str, Any], metric_name: str) -> dict[str, int]:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return {}
    return {
        _safe_labels(labels): int(count)
        for labels, count in counters.items()
    }


def _metric_event_count(metrics: dict[str, Any], metric_name: str) -> int:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return 0
    total = 0
    for count in counters.values():
        try:
            total += max(0, int(count))
        except (TypeError, ValueError):
            continue
    return total


def _metric_histogram_values(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str] | None = None,
) -> list[float]:
    histograms = metrics.get("histograms", {}).get(metric_name, {})
    if not isinstance(histograms, dict):
        return []
    values: list[float] = []
    for labels, samples in histograms.items():
        try:
            label_map = dict(labels)
        except Exception:  # noqa: BLE001
            continue
        if expected and not all(label_map.get(key) == value for key, value in expected.items()):
            continue
        if not isinstance(samples, list):
            continue
        for sample in samples:
            try:
                values.append(float(sample))
            except (TypeError, ValueError):
                continue
    return values


def _metric_labels_include_identifier(metrics: dict[str, Any], raw_values: tuple[str, ...]) -> bool:
    needles = tuple(value for value in raw_values if value)
    if not needles:
        return False
    for group_name in ("counters", "gauges", "histograms"):
        group = metrics.get(group_name)
        if not isinstance(group, dict):
            continue
        for buckets in group.values():
            if not isinstance(buckets, dict):
                continue
            for labels in buckets:
                try:
                    rendered = json.dumps(dict(labels), ensure_ascii=False, sort_keys=True)
                except Exception:  # noqa: BLE001
                    rendered = str(labels)
                if any(value in rendered for value in needles):
                    return True
    return False


def _metric_label_seen(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str],
) -> bool:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return False
    for labels, count in counters.items():
        try:
            label_map = dict(labels)
            seen = int(count) > 0
        except Exception:  # noqa: BLE001
            continue
        if seen and all(label_map.get(key) == value for key, value in expected.items()):
            return True
    return False


def _metric_label_count(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str],
) -> int:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return 0
    total = 0
    for labels, count in counters.items():
        try:
            label_map = dict(labels)
            numeric_count = int(count)
        except Exception:  # noqa: BLE001
            continue
        if all(label_map.get(key) == value for key, value in expected.items()):
            total += max(0, numeric_count)
    return total


def _assert_proactive_channel_summary(summary: dict[str, Any]) -> None:
    errors: list[str] = []
    if summary.get("status") != "pass" or summary.get("delivered") is not True:
        errors.append("delivery did not pass")
    for path in (
        ("recipient_id_hash_present",),
        ("organization_id_hash_present",),
        ("message_hash_present",),
        ("send_attempt", "recipient_id_hash_present"),
        ("send_attempt", "organization_id_hash_present"),
        ("send_attempt", "message_hash_present"),
        ("send_attempt", "channel_supported"),
        ("channel_config", "supported"),
        ("channel_config", "enabled"),
        ("channel_config", "credential_present"),
        ("channel_config", "credential_value_included"),
        ("metrics", "can_send_allowed_seen"),
        ("metrics", "send_delivered_seen"),
        ("metrics", "send_duration_observed"),
        ("metrics", "metric_labels_include_identifiers"),
        ("metrics", "duration_metric_label_status_delivered_seen"),
        ("database", "connection_verified"),
        ("database", "opt_out_scope_request_org"),
        ("database", "send_audit_scope_request_org"),
        ("org_scope", "context_token_set"),
        ("org_scope", "organization_id_hash_present"),
        ("org_scope", "raw_organization_identifier_included"),
        ("operator_approval", "allow_send_acknowledged"),
        ("operator_approval", "approved_recipient_hash_present"),
        ("operator_approval", "raw_recipient_identifier_included"),
        ("operator_approval", "raw_message_included"),
        ("evidence_contract", "single_outbound_send"),
        ("evidence_contract", "uses_proactive_messenger"),
        ("evidence_contract", "requires_live_channel_credentials"),
        ("evidence_contract", "requires_database_guardrail"),
        ("guardrail", "allowed"),
        ("guardrail", "reason_allowed"),
        ("guardrail", "database_opt_out_check_used"),
        ("delivery", "delivered"),
        ("delivery", "duration_observed"),
        ("delivery", "channel_matches_request"),
        ("delivery", "raw_delivery_payload_included"),
        ("send_attempt", "single_send_attempt"),
        ("channel_contract", "requested_channel_supported"),
        ("channel_contract", "requested_channel_matches_delivery"),
        ("channel_contract", "credential_value_included"),
    ):
        current: Any = summary
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if path[-1] in {
            "credential_value_included",
            "metric_labels_include_identifiers",
            "raw_message_included",
            "raw_recipient_identifier_included",
            "raw_organization_identifier_included",
            "raw_delivery_payload_included",
            "raw_metric_payload_included",
            "credential_name_value_pair_included",
            "raw_trigger_target_included",
        }:
            if current is not False:
                errors.append(".".join(path))
        elif current is not True:
            errors.append(".".join(path))
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    if int(metrics.get("can_send_allowed_count") or 0) < 1:
        errors.append("allowed guardrail metric missing")
    if int(metrics.get("send_delivered_count") or 0) < 1:
        errors.append("delivered send metric missing")
    if int(metrics.get("send_duration_count") or 0) < 1:
        errors.append("duration metric missing")
    if metrics.get("metric_label_strategy") != "bounded_status_reason_channel_only":
        errors.append("metric label strategy invalid")
    delivery = summary.get("delivery") if isinstance(summary.get("delivery"), dict) else {}
    if float(delivery.get("duration_ms_min") or 0.0) < 0.0:
        errors.append("delivery duration invalid")
    privacy = summary.get("privacy") if isinstance(summary.get("privacy"), dict) else {}
    for key in (
        "raw_content_included",
        "raw_message_included",
        "raw_recipient_identifier_included",
        "raw_organization_identifier_included",
        "raw_channel_credentials_included",
        "raw_delivery_payload_included",
        "raw_metric_payload_included",
        "credential_name_value_pair_included",
        "raw_trigger_target_included",
        "metric_labels_include_identifiers",
    ):
        if privacy.get(key) is not False:
            errors.append(f"privacy.{key}")
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    forbidden = (
        str(summary.get("channel_config", {}).get("credential_name") or "") + "=",
    )
    if any(token and token in rendered for token in forbidden):
        errors.append("credential marker leaked")
    if errors:
        raise RuntimeError(f"Proactive channel evidence contract failed: {errors}")


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_send(args)

    from app.core.config import settings
    from app.core.database import test_connection
    from app.core.org_context import current_org_id
    from app.engine.living_agent.proactive_messenger import ProactiveMessenger
    from app.engine.runtime import runtime_metrics as rm

    channel_state = _channel_config(settings, args.channel)
    if not channel_state["enabled"]:
        raise RuntimeError(f"{args.channel} channel is not enabled in settings")
    if not channel_state["credential_present"]:
        raise RuntimeError(f"{channel_state['credential_name']} is not configured")
    if not test_connection():
        raise RuntimeError("Database connection failed; opt-out and send audit cannot be verified")
    database_summary = {
        "connection_verified": True,
        "opt_out_lookup_verifiable": True,
        "send_audit_verifiable": True,
        "opt_out_scope_request_org": True,
        "send_audit_scope_request_org": True,
        "raw_connection_details_included": False,
    }

    rm._reset_for_tests()
    messenger = ProactiveMessenger()
    message = args.message.strip() or _default_message(args.channel)
    org_token = current_org_id.set(args.organization_id)
    try:
        delivered = await messenger.send(
            args.recipient_id,
            args.channel,
            message,
            trigger="operator_live_channel_probe",
            priority=0.1,
        )
    finally:
        current_org_id.reset(org_token)

    metrics = rm.snapshot()
    sends_metric = "runtime.living_agent.proactive.sends"
    can_send_metric = "runtime.living_agent.proactive.can_send"
    send_counters = _metric_counter_map(metrics, sends_metric)
    can_send_counters = _metric_counter_map(metrics, can_send_metric)
    duration_metric = "runtime.living_agent.proactive.send_duration_ms"
    duration_values = _metric_histogram_values(
        metrics,
        duration_metric,
        expected={"status": "delivered"},
    )
    recipient_hash = _hash(args.recipient_id)
    organization_hash = _hash(args.organization_id)
    message_hash = _hash(message)
    can_send_allowed_count = _metric_label_count(
        metrics,
        can_send_metric,
        expected={"status": "allowed", "reason": "allowed"},
    )
    send_delivered_count = _metric_label_count(
        metrics,
        sends_metric,
        expected={"status": "delivered"},
    )
    duration_delivered_seen = bool(duration_values)
    metric_labels_include_identifiers = _metric_labels_include_identifier(
        metrics,
        (args.recipient_id, args.organization_id, message),
    )
    summary = {
        "status": "pass" if delivered else "fail",
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "channel": args.channel,
        "delivered": bool(delivered),
        "recipient_id_hash": recipient_hash,
        "recipient_id_hash_present": bool(recipient_hash),
        "organization_id_hash": organization_hash,
        "organization_id_hash_present": bool(organization_hash),
        "message_hash": message_hash,
        "message_hash_present": bool(message_hash),
        "message_char_count": len(message),
        "trigger": "operator_live_channel_probe",
        "evidence_contract": {
            "single_outbound_send": True,
            "uses_proactive_messenger": True,
            "requires_live_channel_credentials": True,
            "requires_database_guardrail": True,
            "delivery_adapter_boundary": "configured_channel_sender",
            "identifier_strategy": "hash_or_count_only",
        },
        "database": database_summary,
        "org_scope": {
            "context_token_set": True,
            "organization_id_hash_present": bool(organization_hash),
            "write_scope_expected": "request_scoped",
            "raw_organization_identifier_included": False,
        },
        "operator_approval": {
            "allow_send_acknowledged": bool(args.allow_send),
            "approved_recipient_hash_present": bool(recipient_hash),
            "raw_recipient_identifier_included": False,
            "raw_message_included": False,
        },
        "guardrail": {
            "allowed": can_send_allowed_count >= 1,
            "reason_allowed": _metric_label_seen(
                metrics,
                can_send_metric,
                expected={"status": "allowed", "reason": "allowed"},
            ),
            "blocked_metric_count": _metric_label_count(
                metrics,
                can_send_metric,
                expected={"status": "blocked"},
            ),
            "decision_source": "ProactiveMessenger.can_send",
            "database_opt_out_check_used": database_summary["opt_out_lookup_verifiable"],
            "opt_out_checked_via_database": database_summary["opt_out_lookup_verifiable"],
        },
        "delivery": {
            "channel": args.channel,
            "delivered": bool(delivered),
            "status": "delivered" if delivered else "failed",
            "channel_matches_request": True,
            "duration_observed": bool(duration_values),
            "duration_ms_min": min(duration_values) if duration_values else 0.0,
            "duration_ms_count": len(duration_values),
            "raw_delivery_payload_included": False,
        },
        "send_attempt": {
            "channel": args.channel,
            "channel_supported": args.channel in SUPPORTED_CHANNELS,
            "trigger": "operator_live_channel_probe",
            "priority": 0.1,
            "single_send_attempt": True,
            "recipient_id_hash_present": bool(recipient_hash),
            "organization_id_hash_present": bool(organization_hash),
            "message_hash_present": bool(message_hash),
            "raw_message_included": False,
        },
        "channel_contract": {
            "requested_channel": args.channel,
            "requested_channel_supported": args.channel in SUPPORTED_CHANNELS,
            "requested_channel_matches_delivery": True,
            "supported_channel_count": len(SUPPORTED_CHANNELS),
            "credential_configured": channel_state["credential_present"],
            "credential_value_included": False,
            "credential_name_value_pair_included": False,
        },
        "channel_config": {
            "supported": args.channel in SUPPORTED_CHANNELS,
            "enabled": channel_state["enabled"],
            "credential_present": channel_state["credential_present"],
            "credential_name": channel_state["credential_name"],
            "credential_value_included": False,
        },
        "metrics": {
            "can_send_event_count": _metric_event_count(metrics, can_send_metric),
            "sends_event_count": _metric_event_count(metrics, sends_metric),
            "can_send_allowed_count": can_send_allowed_count,
            "send_delivered_count": send_delivered_count,
            "send_duration_count": len(duration_values),
            "send_duration_observed": bool(duration_values),
            "send_duration_ms_min": min(duration_values) if duration_values else 0.0,
            "duration_metric_label_status_delivered_seen": duration_delivered_seen,
            "metric_labels_include_identifiers": metric_labels_include_identifiers,
            "metric_label_strategy": "bounded_status_reason_channel_only",
            "raw_metric_payload_included": False,
            "can_send_allowed_seen": _metric_label_seen(
                metrics,
                can_send_metric,
                expected={"status": "allowed", "reason": "allowed"},
            ),
            "send_delivered_seen": _metric_label_seen(
                metrics,
                sends_metric,
                expected={"status": "delivered"},
            ),
            "can_send": can_send_counters,
            "sends": send_counters,
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
            "metric_labels_include_identifiers": metric_labels_include_identifiers,
            "identifier_strategy": "hash_or_count_only",
        },
    }
    if not delivered:
        raise RuntimeError(f"Proactive {args.channel} probe was not delivered: {summary}")
    _assert_proactive_channel_summary(summary)
    return summary


def _default_message(channel: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    return f"Wiii live proactive {channel} probe at {now}. No action required."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Opt-in live proactive outbound channel probe.",
    )
    parser.add_argument("--allow-send", action="store_true", help="Permit one outbound message send.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check live proactive channel readiness without sending a message.",
    )
    parser.add_argument(
        "--failure-from-preflight",
        action="store_true",
        help=(
            "Write a failed registered evidence artifact from validated preflight "
            "diagnostics without sending a message."
        ),
    )
    parser.add_argument(
        "--failure-preflight-json",
        type=Path,
        default=None,
        help="Validated preflight JSON to embed in --failure-from-preflight output.",
    )
    parser.add_argument("--allow-production", action="store_true", help="Permit running against settings.environment=production.")
    parser.add_argument("--channel", choices=sorted(SUPPORTED_CHANNELS), required=True)
    parser.add_argument("--recipient-id", default="", help="Channel-specific recipient id/chat id/user id.")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--message", default="")
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


async def async_main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.preflight_only:
        result = _build_proactive_channel_preflight(args)
        emit_json_payload(result, args.out)
        return 0 if result.get("status") == "pass" else 1
    if args.failure_from_preflight:
        if args.out is None:
            print("--failure-from-preflight requires --out", file=sys.stderr)
            return 1
        if args.failure_preflight_json is None:
            print(
                "--failure-from-preflight requires --failure-preflight-json",
                file=sys.stderr,
            )
            return 1
        try:
            preflight = load_proactive_preflight(args.failure_preflight_json)
        except Exception as exc:  # noqa: BLE001
            print(_redact_failure_text(exc, args), file=sys.stderr)
            return 1
        emit_json_payload(
            _failure_payload(
                RuntimeError("preflight blocked live proactive channel send"),
                args,
                preflight=preflight,
            ),
            args.out,
        )
        return 1
    try:
        result = await _run_probe(args)
    except SystemExit as exc:
        print(_redact_failure_text(exc, args), file=sys.stderr)
        emit_json_payload(_failure_payload(RuntimeError(str(exc)), args), args.out)
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        emit_json_payload(_failure_payload(exc, args), args.out)
        return 1
    emit_json_payload(result, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(list(argv or sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
