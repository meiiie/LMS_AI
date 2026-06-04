#!/usr/bin/env python3
"""Validate privacy-safe live-evidence preflight diagnostic JSON files."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from strict_json import loads_strict_json  # noqa: E402


PREFLIGHT_VALIDATION_SCHEMA_VERSION = "wiii.runtime_evidence_preflight_validation.v1"
SETUP_CONTRACT_VERSION = "wiii.live_evidence_setup_contract.v1"
PREFLIGHT_SCHEMAS: dict[str, dict[str, Any]] = {
    "wiii.provider_runtime_preflight.v1": {
        "requirement_id": "provider-runtime-tool-loop",
        "fields": {
            "schema_version",
            "generated_at",
            "status",
            "requested_provider",
            "selected_provider",
            "tier",
            "allow_call_acknowledged",
            "live_env_flag_set",
            "include_stream_ledger",
            "allow_stream_write_acknowledged",
            "production_environment",
            "allow_production_acknowledged",
            "provider_status_counts",
            "providers",
            "required_next",
            "privacy",
        },
        "privacy_false_fields": {
            "secret_values_included",
            "credential_names_included",
            "raw_request_identifiers_included",
            "provider_payload_included",
            "provider_response_included",
        },
    },
    "wiii.proactive_channel_preflight.v1": {
        "requirement_id": "autonomy-proactive-channel",
        "fields": {
            "schema_version",
            "generated_at",
            "status",
            "requested_channel",
            "allow_send_acknowledged",
            "live_env_flag_set",
            "recipient_id_present",
            "production_environment",
            "allow_production_acknowledged",
            "live_send_attempted",
            "channel_config",
            "required_next",
            "setup_contract",
            "privacy",
        },
        "privacy_false_fields": {
            "secret_values_included",
            "credential_names_included",
            "raw_recipient_identifier_included",
            "raw_organization_identifier_included",
            "raw_message_included",
            "raw_delivery_payload_included",
            "raw_channel_credentials_included",
        },
    },
    "wiii.connect_composio_acceptance_preflight.v1": {
        "requirement_id": "wiii-connect-composio-acceptance",
        "fields": {
            "schema_version",
            "generated_at",
            "status",
            "requested_provider",
            "requested_action",
            "allow_live_acknowledged",
            "live_env_flag_set",
            "live_backend_call_attempted",
            "provider_execution_attempted",
            "backend",
            "authentication",
            "flags",
            "arguments",
            "required_next",
            "setup_contract",
            "privacy",
        },
        "privacy_false_fields": {
            "secret_values_included",
            "credential_names_included",
            "bearer_value_included",
            "bearer_env_name_included",
            "raw_backend_url_included",
            "raw_connection_selection_included",
            "raw_arguments_included",
            "provider_payload_included",
            "provider_response_included",
        },
    },
    "wiii.lms_test_course_preflight.v1": {
        "requirement_id": "lms-test-course-replay",
        "fields": {
            "schema_version",
            "generated_at",
            "status",
            "allow_write_acknowledged",
            "allow_external_lms_write_acknowledged",
            "live_env_flag_set",
            "production_environment",
            "allow_production_acknowledged",
            "live_write_attempted",
            "external_lms_write_attempted",
            "backend",
            "authentication",
            "external_lms",
            "required_next",
            "setup_contract",
            "privacy",
        },
        "privacy_false_fields": {
            "secret_values_included",
            "credential_names_included",
            "bearer_value_included",
            "raw_backend_url_included",
            "raw_external_lms_endpoint_included",
            "raw_external_lms_token_included",
            "raw_request_identifiers_included",
            "raw_lms_document_included",
        },
    },
}
STATUS_VALUES = {"pass", "fail"}


@dataclass(frozen=True)
class PreflightValidationResult:
    validation_schema_version: str
    preflight_path: str
    schema_version: str | None
    requirement_id: str | None
    passed_checks: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def validate_preflight(
    preflight_path: Path,
    *,
    requirement_id: str | None = None,
) -> PreflightValidationResult:
    errors: list[str] = []
    passed_checks = 0
    payload = _load_payload(preflight_path, errors)
    schema_version: str | None = None
    resolved_requirement_id: str | None = None
    if payload is not None:
        if isinstance(payload.get("schema_version"), str):
            schema_version = payload["schema_version"]
            contract = PREFLIGHT_SCHEMAS.get(schema_version)
            if contract:
                resolved_requirement_id = str(contract["requirement_id"])
        payload_errors, checks = _payload_errors(payload, requirement_id=requirement_id)
        errors.extend(payload_errors)
        passed_checks += checks
    return PreflightValidationResult(
        validation_schema_version=PREFLIGHT_VALIDATION_SCHEMA_VERSION,
        preflight_path=str(preflight_path),
        schema_version=schema_version,
        requirement_id=resolved_requirement_id,
        passed_checks=passed_checks,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("preflight: path must be a regular file")
        return None
    try:
        payload = loads_strict_json(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"preflight: could not read JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("preflight: root must be a JSON object")
        return None
    return payload


def _payload_errors(
    payload: dict[str, Any],
    *,
    requirement_id: str | None,
) -> tuple[list[str], int]:
    errors: list[str] = []
    passed_checks = 0
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str):
        errors.append("preflight: schema_version must be a string")
        return errors, passed_checks
    contract = PREFLIGHT_SCHEMAS.get(schema_version)
    if contract is None:
        errors.append(f"preflight: unsupported schema_version {schema_version!r}")
        return errors, passed_checks
    passed_checks += 1
    expected_requirement_id = str(contract["requirement_id"])
    if requirement_id and requirement_id != expected_requirement_id:
        errors.append(
            "preflight: requirement_id must match schema contract "
            f"{expected_requirement_id!r}"
        )
    else:
        passed_checks += 1

    errors.extend(_closed_schema_errors(payload, contract))
    errors.extend(_common_field_errors(payload))
    errors.extend(_privacy_errors(payload, contract))
    errors.extend(_setup_contract_errors(payload, expected_requirement_id))
    errors.extend(_schema_specific_errors(payload, schema_version))
    if not errors:
        passed_checks += 1
    return errors, passed_checks


def _closed_schema_errors(
    payload: dict[str, Any],
    contract: dict[str, Any],
) -> list[str]:
    fields = set(payload)
    allowed = set(contract["fields"])
    missing = sorted(allowed - fields)
    extra = sorted(fields - allowed)
    errors: list[str] = []
    if missing:
        errors.append("preflight: missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("preflight: unsupported field(s): " + ", ".join(extra))
    return errors


def _common_field_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("status") not in STATUS_VALUES:
        errors.append("preflight: status must be pass or fail")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        errors.append("preflight: generated_at must be a non-empty string")
    elif not _is_iso_timestamp(generated_at):
        errors.append("preflight: generated_at must be an ISO timestamp")
    required_next = payload.get("required_next")
    if not _is_string_list(required_next):
        errors.append("preflight: required_next must be a string list")
    else:
        if required_next != list(dict.fromkeys(required_next)):
            errors.append("preflight: required_next must not contain duplicates")
        if any(not item for item in required_next):
            errors.append("preflight: required_next must not contain empty strings")
        if payload.get("status") == "pass" and required_next:
            errors.append("preflight: pass status must have empty required_next")
        if payload.get("status") == "fail" and not required_next:
            errors.append("preflight: fail status must include required_next")
    return errors


def _privacy_errors(
    payload: dict[str, Any],
    contract: dict[str, Any],
) -> list[str]:
    privacy = payload.get("privacy")
    if not isinstance(privacy, dict):
        return ["preflight: privacy must be an object"]
    errors: list[str] = []
    for field in sorted(contract["privacy_false_fields"]):
        if privacy.get(field) is not False:
            errors.append(f"preflight: privacy.{field} must be false")
    extra_secret_true = [
        key
        for key, value in privacy.items()
        if isinstance(key, str)
        and value is True
        and any(token in key for token in ("secret", "credential", "raw_", "bearer"))
    ]
    if extra_secret_true:
        errors.append(
            "preflight: privacy sensitive flags must not be true: "
            + ", ".join(sorted(extra_secret_true))
        )
    return errors


def _setup_contract_errors(
    payload: dict[str, Any],
    expected_requirement_id: str,
) -> list[str]:
    if "setup_contract" not in payload:
        return []
    setup = payload.get("setup_contract")
    if not isinstance(setup, dict):
        return ["preflight: setup_contract must be an object"]
    expected_fields = {
        "version",
        "requirement_id",
        "required_next",
        "workflow_inputs_required",
        "environment_flags_required",
        "credential_slots_required",
        "external_setup_required",
        "dispatch_ready",
    }
    errors: list[str] = []
    if set(setup) != expected_fields:
        errors.append("preflight: setup_contract fields must match contract")
    if setup.get("version") != SETUP_CONTRACT_VERSION:
        errors.append(
            f"preflight: setup_contract.version must be {SETUP_CONTRACT_VERSION!r}"
        )
    if setup.get("requirement_id") != expected_requirement_id:
        errors.append("preflight: setup_contract.requirement_id must match schema")
    if setup.get("required_next") != payload.get("required_next"):
        errors.append("preflight: setup_contract.required_next must match required_next")
    for field in (
        "workflow_inputs_required",
        "environment_flags_required",
        "credential_slots_required",
        "external_setup_required",
    ):
        value = setup.get(field)
        if not _is_string_list(value):
            errors.append(f"preflight: setup_contract.{field} must be a string list")
        elif value != list(dict.fromkeys(value)):
            errors.append(f"preflight: setup_contract.{field} must not contain duplicates")
        elif any(not item for item in value):
            errors.append(f"preflight: setup_contract.{field} must not contain empty strings")
    if not isinstance(setup.get("dispatch_ready"), bool):
        errors.append("preflight: setup_contract.dispatch_ready must be boolean")
    elif setup["dispatch_ready"] != (payload.get("status") == "pass"):
        errors.append("preflight: setup_contract.dispatch_ready must match status")
    rendered = json.dumps(setup, sort_keys=True)
    forbidden = (
        "TELEGRAM_BOT_TOKEN",
        "FACEBOOK_PAGE_ACCESS_TOKEN",
        "ZALO_OA_ACCESS_TOKEN",
        "WIII_ACCEPTANCE_BEARER_TOKEN",
        "WIII_LMS_TEST_COURSE_BEARER_TOKEN",
        "WIII_LMS_TEST_COURSE_APPLY_URL",
        "WIII_LMS_TEST_COURSE_APPLY_TOKEN",
        "access_token",
        "api_key",
        "authorization",
    )
    if any(token in rendered for token in forbidden):
        errors.append("preflight: setup_contract must not include credential names")
    return errors


def _schema_specific_errors(payload: dict[str, Any], schema_version: str) -> list[str]:
    if schema_version == "wiii.provider_runtime_preflight.v1":
        return _provider_preflight_errors(payload)
    if schema_version == "wiii.proactive_channel_preflight.v1":
        return _proactive_preflight_errors(payload)
    if schema_version == "wiii.connect_composio_acceptance_preflight.v1":
        return _composio_preflight_errors(payload)
    if schema_version == "wiii.lms_test_course_preflight.v1":
        return _lms_test_course_preflight_errors(payload)
    return []


def _provider_preflight_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "allow_call_acknowledged",
        "live_env_flag_set",
        "include_stream_ledger",
        "allow_stream_write_acknowledged",
        "production_environment",
        "allow_production_acknowledged",
    ):
        _append_boolean_error(payload, field, errors)
    selected = payload.get("selected_provider")
    if selected is not None and not isinstance(selected, str):
        errors.append("preflight: selected_provider must be a string or null")
    counts = payload.get("provider_status_counts")
    if not isinstance(counts, dict):
        errors.append("preflight: provider_status_counts must be an object")
    else:
        for field in ("total", "configured", "request_selectable"):
            if not _is_non_negative_int(counts.get(field)):
                errors.append(f"preflight: provider_status_counts.{field} must be >= 0")
    providers = payload.get("providers")
    if not isinstance(providers, list):
        errors.append("preflight: providers must be a list")
    else:
        for provider in providers:
            if not isinstance(provider, dict):
                errors.append("preflight: provider entries must be objects")
                continue
            if set(provider) != {"provider", "configured", "request_selectable"}:
                errors.append("preflight: provider entries have invalid fields")
            if not isinstance(provider.get("provider"), str) or not provider["provider"]:
                errors.append("preflight: provider entry provider must be non-empty")
            for field in ("configured", "request_selectable"):
                if not isinstance(provider.get(field), bool):
                    errors.append(f"preflight: provider entry {field} must be boolean")
    return errors


def _proactive_preflight_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "allow_send_acknowledged",
        "live_env_flag_set",
        "recipient_id_present",
        "production_environment",
        "allow_production_acknowledged",
        "live_send_attempted",
    ):
        _append_boolean_error(payload, field, errors)
    if payload.get("live_send_attempted") is not False:
        errors.append("preflight: live_send_attempted must be false")
    channel_config = payload.get("channel_config")
    if not isinstance(channel_config, dict):
        errors.append("preflight: channel_config must be an object")
    else:
        expected = {
            "supported",
            "enabled",
            "credential_present",
            "credential_value_included",
            "credential_name_included",
        }
        if set(channel_config) != expected:
            errors.append("preflight: channel_config fields must match contract")
        for field in expected:
            if not isinstance(channel_config.get(field), bool):
                errors.append(f"preflight: channel_config.{field} must be boolean")
        for field in ("credential_value_included", "credential_name_included"):
            if channel_config.get(field) is not False:
                errors.append(f"preflight: channel_config.{field} must be false")
    return errors


def _composio_preflight_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "allow_live_acknowledged",
        "live_env_flag_set",
        "live_backend_call_attempted",
        "provider_execution_attempted",
    ):
        _append_boolean_error(payload, field, errors)
    for field in ("live_backend_call_attempted", "provider_execution_attempted"):
        if payload.get(field) is not False:
            errors.append(f"preflight: {field} must be false")
    errors.extend(
        _object_contract_errors(
            payload.get("backend"),
            "backend",
            {
                "valid",
                "placeholder",
                "scheme",
                "host_hash_present",
                "origin_hash_present",
                "raw_backend_url_included",
            },
            false_fields={"raw_backend_url_included"},
        )
    )
    errors.extend(
        _object_contract_errors(
            payload.get("authentication"),
            "authentication",
            {
                "mode",
                "bearer_token_present",
                "bearer_source",
                "dev_login_allowed_by_mode",
                "bearer_value_included",
                "bearer_env_name_included",
            },
            false_fields={"bearer_value_included", "bearer_env_name_included"},
        )
    )
    errors.extend(
        _object_contract_errors(
            payload.get("flags"),
            "flags",
            {
                "expect_connected",
                "require_execution_ready",
                "execute_readonly",
                "skip_connect_link",
                "explicit_connection_selection_present",
            },
        )
    )
    errors.extend(
        _object_contract_errors(
            payload.get("arguments"),
            "arguments",
            {
                "valid_json_object",
                "argument_key_count",
                "arguments_present",
                "raw_arguments_included",
            },
            false_fields={"raw_arguments_included"},
            non_negative_int_fields={"argument_key_count"},
        )
    )
    return errors


def _lms_test_course_preflight_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "allow_write_acknowledged",
        "allow_external_lms_write_acknowledged",
        "live_env_flag_set",
        "production_environment",
        "allow_production_acknowledged",
        "live_write_attempted",
        "external_lms_write_attempted",
    ):
        _append_boolean_error(payload, field, errors)
    for field in ("live_write_attempted", "external_lms_write_attempted"):
        if payload.get(field) is not False:
            errors.append(f"preflight: {field} must be false")
    errors.extend(
        _object_contract_errors(
            payload.get("backend"),
            "backend",
            {
                "transport_mode",
                "base_url_local",
                "raw_base_url_included",
            },
            false_fields={"raw_base_url_included"},
        )
    )
    backend = payload.get("backend")
    if isinstance(backend, dict):
        if backend.get("transport_mode") not in {"asgi", "http"}:
            errors.append("preflight: backend.transport_mode must be asgi or http")
    errors.extend(
        _object_contract_errors(
            payload.get("authentication"),
            "authentication",
            {
                "auth_mode",
                "bearer_token_present",
                "bearer_value_included",
            },
            false_fields={"bearer_value_included"},
        )
    )
    authentication = payload.get("authentication")
    if isinstance(authentication, dict):
        if authentication.get("auth_mode") not in {"auto", "bearer", "api-key", "dev-login"}:
            errors.append(
                "preflight: authentication.auth_mode must be a supported auth mode"
            )
    errors.extend(
        _object_contract_errors(
            payload.get("external_lms"),
            "external_lms",
            {
                "apply_url_present",
                "apply_token_present",
                "endpoint_hash_present",
                "raw_endpoint_included",
                "raw_token_included",
            },
            false_fields={"raw_endpoint_included", "raw_token_included"},
        )
    )
    return errors


def _object_contract_errors(
    value: Any,
    name: str,
    fields: set[str],
    *,
    false_fields: set[str] | None = None,
    non_negative_int_fields: set[str] | None = None,
) -> list[str]:
    if not isinstance(value, dict):
        return [f"preflight: {name} must be an object"]
    errors: list[str] = []
    if set(value) != fields:
        errors.append(f"preflight: {name} fields must match contract")
    false_fields = false_fields or set()
    non_negative_int_fields = non_negative_int_fields or set()
    for field in fields:
        if field in false_fields:
            if value.get(field) is not False:
                errors.append(f"preflight: {name}.{field} must be false")
        elif field in non_negative_int_fields:
            if not _is_non_negative_int(value.get(field)):
                errors.append(f"preflight: {name}.{field} must be >= 0")
        elif field.endswith("_present") or field in {
            "valid",
            "placeholder",
            "base_url_local",
            "dev_login_allowed_by_mode",
            "expect_connected",
            "require_execution_ready",
            "execute_readonly",
            "skip_connect_link",
            "explicit_connection_selection_present",
            "valid_json_object",
            "arguments_present",
        }:
            if not isinstance(value.get(field), bool):
                errors.append(f"preflight: {name}.{field} must be boolean")
    return errors


def _append_boolean_error(
    payload: dict[str, Any],
    field: str,
    errors: list[str],
) -> None:
    if not isinstance(payload.get(field), bool):
        errors.append(f"preflight: {field} must be boolean")


def _is_iso_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return counts


def _error_code(error: str) -> str:
    if error == "preflight: path must be a regular file":
        return "runtime_evidence_preflight_path_invalid"
    if error.startswith("preflight: could not read JSON"):
        return "runtime_evidence_preflight_json_invalid"
    if error == "preflight: root must be a JSON object":
        return "runtime_evidence_preflight_root_invalid"
    if "schema_version" in error:
        return "runtime_evidence_preflight_schema_invalid"
    if "requirement_id" in error:
        return "runtime_evidence_preflight_requirement_mismatch"
    if "unsupported field" in error or "missing required field" in error:
        return "runtime_evidence_preflight_closed_schema_invalid"
    if "privacy" in error or "raw_" in error or "credential" in error or "bearer" in error:
        return "runtime_evidence_preflight_privacy_invalid"
    if "required_next" in error:
        return "runtime_evidence_preflight_required_next_invalid"
    return "runtime_evidence_preflight_contract_invalid"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a privacy-safe live-evidence preflight diagnostic JSON.",
    )
    parser.add_argument("preflight_path", type=Path)
    parser.add_argument(
        "--requirement-id",
        default=None,
        help="Optional runtime evidence requirement id expected for this preflight.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_preflight(
        args.preflight_path,
        requirement_id=args.requirement_id,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif result.ok:
        print("Wiii Runtime Evidence Preflight Validation: PASS")
    else:
        print(
            "Wiii Runtime Evidence Preflight Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
