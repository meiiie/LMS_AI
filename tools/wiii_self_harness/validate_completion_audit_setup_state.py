#!/usr/bin/env python3
"""Validate completion-audit setup state artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from generate_completion_audit_setup_state import (  # noqa: E402
    SETUP_BINDING_FIELDS,
    SETUP_STATE_SCHEMA_VERSION,
    _setup_state_fingerprint,
    generate_completion_audit_setup_state,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_launch_pack as launch_validator  # noqa: E402


SETUP_STATE_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_state_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "launch_pack_path",
    "launch_pack_sha256",
    "launch_pack_schema_version",
    "launch_items_fingerprint_sha256",
    "launch_setup_fingerprint_sha256",
    "setup_state_fingerprint_sha256",
    "dispatch_ready",
    "requirement_count",
    "ready_requirement_count",
    "blocked_requirement_count",
    "requirements",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
REQUIREMENT_FIELDS = {
    "requirement_id",
    "title",
    "workflow",
    "probe",
    "expected_artifact",
    "setup_contract_version",
    "setup_status",
    "dispatch_ready",
    "setup_checks",
}
CHECK_FIELDS = {
    "category",
    "key",
    "binding_tokens",
    "present",
    "source_handle",
    "secret_value_included",
    "raw_identifier_included",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
}


@dataclass(frozen=True)
class SetupStateValidationResult:
    validation_schema_version: str
    setup_state_path: str
    launch_pack_path: str | None
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


def validate_setup_state(
    setup_state_path: Path,
    *,
    launch_pack_path: Path | None = None,
) -> SetupStateValidationResult:
    errors: list[str] = []
    payload = _load_payload(setup_state_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if launch_pack_path is not None:
            errors.extend(
                _launch_pack_source_errors(
                    payload,
                    launch_pack_path=launch_pack_path,
                )
            )
    return SetupStateValidationResult(
        validation_schema_version=SETUP_STATE_VALIDATION_SCHEMA_VERSION,
        setup_state_path=str(setup_state_path),
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit setup state path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit setup state JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup state root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append("setup state missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("setup state has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != SETUP_STATE_SCHEMA_VERSION:
        errors.append(
            f"setup state schema_version must be {SETUP_STATE_SCHEMA_VERSION!r}"
        )
    for field in (
        "launch_pack_path",
        "launch_pack_schema_version",
        "launch_items_fingerprint_sha256",
        "launch_setup_fingerprint_sha256",
        "setup_state_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"setup state {field} must be a non-empty string")
    for field in (
        "launch_pack_sha256",
        "launch_items_fingerprint_sha256",
        "launch_setup_fingerprint_sha256",
        "setup_state_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"setup state {field} must be a SHA-256 hex string")
    for field in ("ok", "dispatch_ready"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"setup state {field} must be a boolean")
    if payload.get("ok") is not True:
        errors.append("setup state ok must be true for generated setup states")
    for field in (
        "requirement_count",
        "ready_requirement_count",
        "blocked_requirement_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"setup state {field} must be a non-negative integer")
    for field in ("errors", "error_codes"):
        if not _is_string_list(payload.get(field)):
            errors.append(f"setup state {field} must be a string list")
    requirement_errors, requirements = _requirement_errors(
        payload.get("requirements")
    )
    errors.extend(requirement_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not requirement_errors:
        errors.extend(_summary_errors(payload, requirements))
    return errors


def _requirement_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    requirements: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["setup state requirements must be a list"], requirements
    for requirement in value:
        if not isinstance(requirement, dict):
            errors.append("setup state requirement entries must be objects")
            continue
        requirements.append(requirement)
        if set(requirement) != REQUIREMENT_FIELDS:
            errors.append("setup state requirement fields must match contract")
        for field in (
            "requirement_id",
            "title",
            "workflow",
            "probe",
            "expected_artifact",
            "setup_contract_version",
            "setup_status",
        ):
            if not isinstance(requirement.get(field), str) or not requirement.get(field):
                errors.append(f"setup state requirement {field} must be a non-empty string")
        if requirement.get("setup_status") not in {"pending", "ready"}:
            errors.append("setup state requirement setup_status must be pending or ready")
        if not isinstance(requirement.get("dispatch_ready"), bool):
            errors.append("setup state requirement dispatch_ready must be a boolean")
        check_errors, checks = _check_errors(requirement.get("setup_checks"))
        errors.extend(check_errors)
        if not check_errors:
            errors.extend(_requirement_consistency_errors(requirement, checks))
    return errors, requirements


def _check_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(value, list) or not value:
        return ["setup state setup_checks must be a non-empty list"], checks
    seen: set[tuple[str, str]] = set()
    for check in value:
        if not isinstance(check, dict):
            errors.append("setup state setup_check entries must be objects")
            continue
        checks.append(check)
        if set(check) != CHECK_FIELDS:
            errors.append("setup state setup_check fields must match contract")
        category = check.get("category")
        key = check.get("key")
        if category not in SETUP_BINDING_FIELDS:
            errors.append("setup state setup_check category must be a known setup field")
        if not isinstance(key, str) or not key:
            errors.append("setup state setup_check key must be a non-empty string")
        if isinstance(category, str) and isinstance(key, str):
            identity = (category, key)
            if identity in seen:
                errors.append("setup state setup_checks must not duplicate category/key")
            seen.add(identity)
        binding_tokens = check.get("binding_tokens")
        tokens = binding_tokens if _is_string_list(binding_tokens) else []
        if not tokens:
            errors.append("setup state setup_check binding_tokens must be a non-empty string list")
        elif "" in tokens or len(tokens) != len(set(tokens)):
            errors.append(
                "setup state setup_check binding_tokens must be unique non-empty strings"
            )
        for token in tokens:
            if not _is_safe_binding_handle(token):
                errors.append(
                    "setup state setup_check binding_tokens must contain only safe token handles"
                )
                break
        present = check.get("present")
        if not isinstance(present, bool):
            errors.append("setup state setup_check present must be a boolean")
        source_handle = check.get("source_handle")
        if not isinstance(source_handle, str):
            errors.append("setup state setup_check source_handle must be a string")
        else:
            if source_handle and not _is_safe_binding_handle(source_handle):
                errors.append(
                    "setup state setup_check source_handle must be a safe token handle"
                )
            if present is True and source_handle not in tokens:
                errors.append(
                    "setup state setup_check source_handle must match a binding token when present"
                )
            elif present is False and source_handle:
                errors.append(
                    "setup state setup_check source_handle must be empty when not present"
                )
        for field in ("secret_value_included", "raw_identifier_included"):
            if check.get(field) is not False:
                errors.append(f"setup state setup_check {field} must be false")
    return errors, checks


def _requirement_consistency_errors(
    requirement: dict[str, Any],
    checks: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    ready = all(check.get("present") is True for check in checks)
    if requirement.get("dispatch_ready") != ready:
        errors.append("setup state requirement dispatch_ready must match setup_checks")
    expected_status = "ready" if ready else "pending"
    if requirement.get("setup_status") != expected_status:
        errors.append("setup state requirement setup_status must match setup_checks")
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup state privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("setup state privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup state privacy.{field} must be false")
    return errors


def _summary_errors(
    payload: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    ready_count = sum(1 for item in requirements if item.get("dispatch_ready"))
    if not requirements:
        errors.append("setup state requirements must be non-empty")
    if payload.get("requirement_count") != len(requirements):
        errors.append("setup state requirement_count must match requirements")
    if payload.get("ready_requirement_count") != ready_count:
        errors.append("setup state ready_requirement_count must match requirements")
    if payload.get("blocked_requirement_count") != len(requirements) - ready_count:
        errors.append("setup state blocked_requirement_count must match requirements")
    if payload.get("dispatch_ready") != (ready_count == len(requirements) and bool(requirements)):
        errors.append("setup state dispatch_ready must match requirements")
    if payload.get("setup_state_fingerprint_sha256") != _setup_state_fingerprint(
        requirements
    ):
        errors.append("setup state setup_state_fingerprint_sha256 must match requirements")
    requirement_ids = [item.get("requirement_id") for item in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("setup state requirements must not duplicate requirement_id")
    return errors


def _launch_pack_source_errors(
    payload: dict[str, Any],
    *,
    launch_pack_path: Path,
) -> list[str]:
    validation = launch_validator.validate_launch_pack(launch_pack_path)
    if not validation.ok:
        return [
            "completion audit setup state source mismatch: launch pack failed validation: "
            + "; ".join(validation.errors)
        ]
    launch_payload = load_strict_json_file(launch_pack_path)
    if not isinstance(launch_payload, dict):
        return ["completion audit setup state source mismatch: launch pack must be an object"]
    errors: list[str] = []
    expected_fields = {
        "launch_pack_sha256": _sha256_file(launch_pack_path),
        "launch_pack_schema_version": launch_payload.get("schema_version"),
        "launch_items_fingerprint_sha256": launch_payload.get(
            "launch_items_fingerprint_sha256"
        ),
        "launch_setup_fingerprint_sha256": launch_payload.get(
            "launch_setup_fingerprint_sha256"
        ),
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit setup state source mismatch: {field} must match launch pack"
            )
    expected_state = generate_completion_audit_setup_state(launch_pack_path).to_dict()
    errors.extend(
        _requirements_match_launch_pack_source_errors(
            payload.get("requirements"),
            expected_state.get("requirements"),
        )
    )
    return errors


def _requirements_match_launch_pack_source_errors(
    requirements: Any,
    expected_requirements: Any,
) -> list[str]:
    if not isinstance(requirements, list) or not isinstance(expected_requirements, list):
        return []
    if len(requirements) != len(expected_requirements):
        return [
            "completion audit setup state source mismatch: requirements must match launch pack"
        ]
    errors: list[str] = []
    for requirement, expected in zip(requirements, expected_requirements, strict=True):
        if not isinstance(requirement, dict) or not isinstance(expected, dict):
            continue
        for field in (
            "requirement_id",
            "title",
            "workflow",
            "probe",
            "expected_artifact",
            "setup_contract_version",
        ):
            if requirement.get(field) != expected.get(field):
                errors.append(
                    "completion audit setup state source mismatch: "
                    f"requirement {field} must match launch pack"
                )
                return errors
        if not _setup_checks_match_source(
            requirement.get("setup_checks"),
            expected.get("setup_checks"),
        ):
            errors.append(
                "completion audit setup state source mismatch: "
                "setup_checks must match launch pack bindings"
            )
            return errors
    return errors


def _setup_checks_match_source(checks: Any, expected_checks: Any) -> bool:
    if not isinstance(checks, list) or not isinstance(expected_checks, list):
        return False
    if len(checks) != len(expected_checks):
        return False
    for check, expected in zip(checks, expected_checks, strict=True):
        if not isinstance(check, dict) or not isinstance(expected, dict):
            return False
        for field in ("category", "key", "binding_tokens"):
            if check.get(field) != expected.get(field):
                return False
    return True


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return []
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes) and error_codes != expected_codes:
        result.append("setup state error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("setup state error_code_counts must match errors")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit setup state artifact.",
    )
    parser.add_argument("setup_state", type=Path)
    parser.add_argument(
        "--launch-pack",
        type=Path,
        default=None,
        help="Optional launch pack source that the setup state must match.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_setup_state(args.setup_state, launch_pack_path=args.launch_pack)
    if args.json or args.out:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="")
    elif result.ok:
        print("Wiii Completion Audit Setup State Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup State Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_safe_binding_handle(value: str) -> bool:
    return bool(value) and not any(
        char.isspace() or char in {"=", "<", ">"} for char in value
    )


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit setup state path must be a regular file":
        return "completion_audit_setup_state_path_invalid"
    if error.startswith("completion audit setup state JSON is invalid"):
        return "completion_audit_setup_state_json_invalid"
    if error == "completion audit setup state root must be an object":
        return "completion_audit_setup_state_root_invalid"
    if "source mismatch" in error:
        return "completion_audit_setup_state_source_mismatch"
    if error.startswith("setup state missing required field"):
        return "completion_audit_setup_state_missing_required_fields"
    if error.startswith("setup state has unsupported field"):
        return "completion_audit_setup_state_unsupported_fields"
    if error.startswith("setup state schema_version must be"):
        return "completion_audit_setup_state_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_setup_state_fingerprint_invalid"
    if "privacy" in error or "secret_value" in error or "raw_identifier" in error:
        return "completion_audit_setup_state_privacy_invalid"
    if "setup_check" in error or "setup_checks" in error:
        return "completion_audit_setup_state_check_invalid"
    if "requirement" in error:
        return "completion_audit_setup_state_requirement_invalid"
    if "dispatch_ready" in error or "setup_status" in error:
        return "completion_audit_setup_state_consistency_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_setup_state_error_summary_invalid"
    if "boolean" in error:
        return "completion_audit_setup_state_boolean_invalid"
    if "non-negative integer" in error:
        return "completion_audit_setup_state_count_invalid"
    if "string list" in error:
        return "completion_audit_setup_state_string_list_invalid"
    return "completion_audit_setup_state_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
