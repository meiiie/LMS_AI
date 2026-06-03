#!/usr/bin/env python3
"""Validate completion-audit dispatch gate artifacts."""

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

from generate_completion_audit_dispatch_gate import (  # noqa: E402
    BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS,
    DISPATCH_GATE_SCHEMA_VERSION,
    UNLOCKED_LIVE_COMMAND_SPEC_FIELDS,
    _dispatch_gate_fingerprint,
    generate_completion_audit_dispatch_gate,
)
from generate_completion_audit_setup_state import SETUP_BINDING_FIELDS  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_launch_pack as launch_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


DISPATCH_GATE_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_dispatch_gate_validation.v1"
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
    "setup_state_path",
    "setup_state_sha256",
    "setup_state_schema_version",
    "setup_state_fingerprint_sha256",
    "dispatch_gate_fingerprint_sha256",
    "dispatch_ready",
    "dispatch_item_count",
    "ready_dispatch_item_count",
    "blocked_dispatch_item_count",
    "dispatch_items",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
DISPATCH_ITEM_FIELDS = {
    "requirement_id",
    "title",
    "workflow",
    "probe",
    "expected_artifact",
    "setup_status",
    "dispatch_ready",
    "ready_setup_handle_count",
    "ready_setup_handles",
    "blocked_setup_check_count",
    "blocked_setup_checks",
    "unlocked_live_command_specs",
    "blocked_diagnostic_command_specs",
}
SETUP_CHECK_FIELDS = {"category", "key", "binding_tokens", "source_handle"}
COMMAND_SPEC_FIELDS = {"working_directory", "argv", "uses_shell"}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}


@dataclass(frozen=True)
class DispatchGateValidationResult:
    validation_schema_version: str
    dispatch_gate_path: str
    launch_pack_path: str | None
    setup_state_path: str | None
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


def validate_dispatch_gate(
    dispatch_gate_path: Path,
    *,
    launch_pack_path: Path | None = None,
    setup_state_path: Path | None = None,
) -> DispatchGateValidationResult:
    errors: list[str] = []
    payload = _load_payload(dispatch_gate_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if launch_pack_path is not None or setup_state_path is not None:
            errors.extend(
                _source_errors(
                    payload,
                    launch_pack_path=launch_pack_path,
                    setup_state_path=setup_state_path,
                )
            )
    return DispatchGateValidationResult(
        validation_schema_version=DISPATCH_GATE_VALIDATION_SCHEMA_VERSION,
        dispatch_gate_path=str(dispatch_gate_path),
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit dispatch gate path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit dispatch gate JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit dispatch gate root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "dispatch gate missing required field(s): " + ", ".join(missing)
        )
    if extra:
        errors.append("dispatch gate has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != DISPATCH_GATE_SCHEMA_VERSION:
        errors.append(
            f"dispatch gate schema_version must be {DISPATCH_GATE_SCHEMA_VERSION!r}"
        )
    if payload.get("ok") is not True:
        errors.append("dispatch gate ok must be true for generated dispatch gates")
    for field in (
        "launch_pack_path",
        "launch_pack_schema_version",
        "launch_items_fingerprint_sha256",
        "launch_setup_fingerprint_sha256",
        "setup_state_path",
        "setup_state_schema_version",
        "setup_state_fingerprint_sha256",
        "dispatch_gate_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"dispatch gate {field} must be a non-empty string")
    for field in (
        "launch_pack_sha256",
        "launch_items_fingerprint_sha256",
        "launch_setup_fingerprint_sha256",
        "setup_state_sha256",
        "setup_state_fingerprint_sha256",
        "dispatch_gate_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"dispatch gate {field} must be a SHA-256 hex string")
    if not isinstance(payload.get("dispatch_ready"), bool):
        errors.append("dispatch gate dispatch_ready must be a boolean")
    for field in (
        "dispatch_item_count",
        "ready_dispatch_item_count",
        "blocked_dispatch_item_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"dispatch gate {field} must be a non-negative integer")
    for field in ("errors", "error_codes"):
        if not _is_string_list(payload.get(field)):
            errors.append(f"dispatch gate {field} must be a string list")
    item_errors, items = _dispatch_item_errors(payload.get("dispatch_items"))
    errors.extend(item_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not item_errors:
        errors.extend(_summary_errors(payload, items))
    return errors


def _dispatch_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["dispatch gate dispatch_items must be a list"], items
    for item in value:
        if not isinstance(item, dict):
            errors.append("dispatch gate dispatch_item entries must be objects")
            continue
        items.append(item)
        if set(item) != DISPATCH_ITEM_FIELDS:
            errors.append("dispatch gate dispatch_item fields must match contract")
        for field in (
            "requirement_id",
            "title",
            "workflow",
            "probe",
            "expected_artifact",
            "setup_status",
        ):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(
                    f"dispatch gate dispatch_item {field} must be a non-empty string"
                )
        if item.get("setup_status") not in {"pending", "ready"}:
            errors.append("dispatch gate dispatch_item setup_status must be pending or ready")
        if not isinstance(item.get("dispatch_ready"), bool):
            errors.append("dispatch gate dispatch_item dispatch_ready must be a boolean")
        ready_errors, ready_checks = _setup_check_errors(
            item.get("ready_setup_handles"),
            source_handle_required=True,
        )
        blocked_errors, blocked_checks = _setup_check_errors(
            item.get("blocked_setup_checks"),
            source_handle_required=False,
        )
        errors.extend(ready_errors)
        errors.extend(blocked_errors)
        for field in ("ready_setup_handle_count", "blocked_setup_check_count"):
            if not _is_non_negative_int(item.get(field)):
                errors.append(f"dispatch gate dispatch_item {field} must be a non-negative integer")
        if not ready_errors and item.get("ready_setup_handle_count") != len(ready_checks):
            errors.append("dispatch gate ready_setup_handle_count must match handles")
        if (
            not blocked_errors
            and item.get("blocked_setup_check_count") != len(blocked_checks)
        ):
            errors.append("dispatch gate blocked_setup_check_count must match checks")
        errors.extend(_unlocked_live_command_spec_errors(item))
        errors.extend(_blocked_diagnostic_command_spec_errors(item))
    return errors, items


def _setup_check_errors(
    value: Any,
    *,
    source_handle_required: bool,
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["dispatch gate setup check groups must be lists"], checks
    seen: set[tuple[str, str]] = set()
    for check in value:
        if not isinstance(check, dict):
            errors.append("dispatch gate setup check entries must be objects")
            continue
        checks.append(check)
        if set(check) != SETUP_CHECK_FIELDS:
            errors.append("dispatch gate setup check fields must match contract")
        category = check.get("category")
        key = check.get("key")
        if category not in SETUP_BINDING_FIELDS:
            errors.append("dispatch gate setup check category must be a known setup field")
        if not isinstance(key, str) or not key:
            errors.append("dispatch gate setup check key must be a non-empty string")
        if isinstance(category, str) and isinstance(key, str):
            identity = (category, key)
            if identity in seen:
                errors.append("dispatch gate setup checks must not duplicate category/key")
            seen.add(identity)
        binding_tokens = check.get("binding_tokens")
        tokens = binding_tokens if _is_string_list(binding_tokens) else []
        if not tokens:
            errors.append("dispatch gate setup check binding_tokens must be a non-empty string list")
        elif "" in tokens or len(tokens) != len(set(tokens)):
            errors.append(
                "dispatch gate setup check binding_tokens must be unique non-empty strings"
            )
        for token in tokens:
            if not _is_safe_binding_handle(token):
                errors.append(
                    "dispatch gate setup check binding_tokens must contain only safe token handles"
                )
                break
        source_handle = check.get("source_handle")
        if not isinstance(source_handle, str):
            errors.append("dispatch gate setup check source_handle must be a string")
        elif source_handle_required:
            if not source_handle:
                errors.append(
                    "dispatch gate ready setup check source_handle must be non-empty"
                )
            elif not _is_safe_binding_handle(source_handle):
                errors.append(
                    "dispatch gate ready setup check source_handle must be a safe token handle"
                )
            elif source_handle not in tokens:
                errors.append(
                    "dispatch gate ready setup check source_handle must match a binding token"
                )
        elif source_handle:
            errors.append(
                "dispatch gate blocked setup check source_handle must be empty"
            )
    return errors, checks


def _unlocked_live_command_spec_errors(item: dict[str, Any]) -> list[str]:
    value = item.get("unlocked_live_command_specs")
    if not isinstance(value, dict):
        return ["dispatch gate unlocked_live_command_specs must be an object"]
    ready = item.get("dispatch_ready") is True
    if not ready:
        if value != {}:
            return [
                "dispatch gate unlocked_live_command_specs must be empty while setup is pending"
            ]
        return []
    errors: list[str] = []
    expected_keys = set(UNLOCKED_LIVE_COMMAND_SPEC_FIELDS)
    if set(value) != expected_keys:
        errors.append(
            "dispatch gate unlocked_live_command_specs fields must match live command contract"
        )
    for field in UNLOCKED_LIVE_COMMAND_SPEC_FIELDS:
        spec = value.get(field)
        if not isinstance(spec, dict):
            errors.append(f"dispatch gate {field} command spec must be an object")
            continue
        if set(spec) != COMMAND_SPEC_FIELDS:
            errors.append(f"dispatch gate {field} command spec fields must match contract")
        if not isinstance(spec.get("working_directory"), str) or not spec.get("working_directory"):
            errors.append(f"dispatch gate {field} working_directory must be a non-empty string")
        argv = spec.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append(f"dispatch gate {field} argv must be a non-empty string list")
        else:
            errors.extend(_argv_shell_control_errors(argv))
        if spec.get("uses_shell") is not False:
            errors.append(f"dispatch gate {field} uses_shell must be false")
    return errors


def _blocked_diagnostic_command_spec_errors(item: dict[str, Any]) -> list[str]:
    value = item.get("blocked_diagnostic_command_specs")
    if not isinstance(value, dict):
        return ["dispatch gate blocked_diagnostic_command_specs must be an object"]
    ready = item.get("dispatch_ready") is True
    if ready:
        if value != {}:
            return [
                "dispatch gate blocked_diagnostic_command_specs must be empty when setup is ready"
            ]
        return []
    expected_keys = set(BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS)
    errors: list[str] = []
    if set(value) != expected_keys:
        errors.append(
            "dispatch gate blocked_diagnostic_command_specs fields must match diagnostic command contract"
        )
    artifact = item.get("expected_artifact")
    for field in BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS:
        spec = value.get(field)
        if not isinstance(spec, dict):
            errors.append(f"dispatch gate {field} diagnostic command spec must be an object")
            continue
        if set(spec) != COMMAND_SPEC_FIELDS:
            errors.append(
                f"dispatch gate {field} diagnostic command spec fields must match contract"
            )
        if spec.get("working_directory") != "maritime-ai-service":
            errors.append(
                f"dispatch gate {field} diagnostic command cwd must be maritime-ai-service"
            )
        argv = spec.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append(
                f"dispatch gate {field} diagnostic argv must be a non-empty string list"
            )
            continue
        errors.extend(_argv_shell_control_errors(argv))
        if "--failure-from-preflight" not in argv:
            errors.append(
                f"dispatch gate {field} diagnostic command must use failure-from-preflight"
            )
        if "--failure-preflight-json" not in argv:
            errors.append(
                f"dispatch gate {field} diagnostic command must bind failure preflight JSON"
            )
        if isinstance(artifact, str) and artifact and artifact not in argv:
            errors.append(
                f"dispatch gate {field} diagnostic command must write expected artifact"
            )
        if spec.get("uses_shell") is not False:
            errors.append(f"dispatch gate {field} diagnostic uses_shell must be false")
    return errors


def _summary_errors(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    ready_count = sum(1 for item in items if item.get("dispatch_ready") is True)
    if not items:
        errors.append("dispatch gate dispatch_items must be non-empty")
    if payload.get("dispatch_item_count") != len(items):
        errors.append("dispatch gate dispatch_item_count must match dispatch_items")
    if payload.get("ready_dispatch_item_count") != ready_count:
        errors.append("dispatch gate ready_dispatch_item_count must match dispatch_items")
    if payload.get("blocked_dispatch_item_count") != len(items) - ready_count:
        errors.append("dispatch gate blocked_dispatch_item_count must match dispatch_items")
    if payload.get("dispatch_ready") != (ready_count == len(items) and bool(items)):
        errors.append("dispatch gate dispatch_ready must match dispatch_items")
    if payload.get("dispatch_gate_fingerprint_sha256") != _dispatch_gate_fingerprint(
        items
    ):
        errors.append("dispatch gate dispatch_gate_fingerprint_sha256 must match dispatch_items")
    requirement_ids = [item.get("requirement_id") for item in items]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("dispatch gate dispatch_items must not duplicate requirement_id")
    for item in items:
        ready = item.get("dispatch_ready") is True
        status = item.get("setup_status")
        if status != ("ready" if ready else "pending"):
            errors.append("dispatch gate setup_status must match dispatch_ready")
        blocked_count = item.get("blocked_setup_check_count")
        if ready and blocked_count != 0:
            errors.append("dispatch gate ready items must have zero blocked setup checks")
        if not ready and blocked_count == 0:
            errors.append("dispatch gate pending items must have blocked setup checks")
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["dispatch gate privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("dispatch gate privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"dispatch gate privacy.{field} must be false")
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    launch_pack_path: Path | None,
    setup_state_path: Path | None,
) -> list[str]:
    if launch_pack_path is None or setup_state_path is None:
        return [
            "completion audit dispatch gate source mismatch: "
            "--launch-pack and --setup-state are required together"
        ]
    launch_validation = launch_validator.validate_launch_pack(launch_pack_path)
    if not launch_validation.ok:
        return [
            "completion audit dispatch gate source mismatch: launch pack failed validation: "
            + "; ".join(launch_validation.errors)
        ]
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        return [
            "completion audit dispatch gate source mismatch: setup state failed validation: "
            + "; ".join(setup_validation.errors)
        ]
    launch_payload = load_strict_json_file(launch_pack_path)
    setup_payload = load_strict_json_file(setup_state_path)
    if not isinstance(launch_payload, dict) or not isinstance(setup_payload, dict):
        return ["completion audit dispatch gate source mismatch: source root invalid"]
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
        "setup_state_sha256": _sha256_file(setup_state_path),
        "setup_state_schema_version": setup_payload.get("schema_version"),
        "setup_state_fingerprint_sha256": setup_payload.get(
            "setup_state_fingerprint_sha256"
        ),
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit dispatch gate source mismatch: {field} must match source"
            )
    expected_gate = generate_completion_audit_dispatch_gate(
        launch_pack_path,
        setup_state_path,
    ).to_dict()
    for field in (
        "dispatch_ready",
        "dispatch_item_count",
        "ready_dispatch_item_count",
        "blocked_dispatch_item_count",
        "dispatch_gate_fingerprint_sha256",
        "dispatch_items",
    ):
        if payload.get(field) != expected_gate.get(field):
            errors.append(
                f"completion audit dispatch gate source mismatch: {field} must match sources"
            )
            break
    return errors


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
        result.append("dispatch gate error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("dispatch gate error_code_counts must match errors")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit dispatch gate artifact.",
    )
    parser.add_argument("dispatch_gate", type=Path)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_dispatch_gate(
        args.dispatch_gate,
        launch_pack_path=args.launch_pack,
        setup_state_path=args.setup_state,
    )
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
        print("Wiii Completion Audit Dispatch Gate Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Dispatch Gate Validation: FAIL\n"
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


def _argv_shell_control_errors(argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for arg in argv:
        if any(token in arg for token in shell_control_tokens):
            return [
                "dispatch gate unlocked command specs argv must not contain shell control operator tokens"
            ]
    return []


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit dispatch gate path must be a regular file":
        return "completion_audit_dispatch_gate_path_invalid"
    if error.startswith("completion audit dispatch gate JSON is invalid"):
        return "completion_audit_dispatch_gate_json_invalid"
    if error == "completion audit dispatch gate root must be an object":
        return "completion_audit_dispatch_gate_root_invalid"
    if "source mismatch" in error:
        return "completion_audit_dispatch_gate_source_mismatch"
    if error.startswith("dispatch gate missing required field"):
        return "completion_audit_dispatch_gate_missing_required_fields"
    if error.startswith("dispatch gate has unsupported field"):
        return "completion_audit_dispatch_gate_unsupported_fields"
    if error.startswith("dispatch gate schema_version must be"):
        return "completion_audit_dispatch_gate_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_dispatch_gate_fingerprint_invalid"
    if "privacy" in error or "secret" in error or "raw_identifier" in error:
        return "completion_audit_dispatch_gate_privacy_invalid"
    if (
        "unlocked_live_command_specs" in error
        or "blocked_diagnostic_command_specs" in error
        or "command spec" in error
        or "argv" in error
    ):
        return "completion_audit_dispatch_gate_command_invalid"
    if "setup check" in error or "setup checks" in error:
        return "completion_audit_dispatch_gate_setup_check_invalid"
    if "dispatch_item" in error or "dispatch_items" in error:
        return "completion_audit_dispatch_gate_item_invalid"
    if "dispatch_ready" in error or "setup_status" in error:
        return "completion_audit_dispatch_gate_consistency_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_dispatch_gate_error_summary_invalid"
    if "boolean" in error:
        return "completion_audit_dispatch_gate_boolean_invalid"
    if "non-negative integer" in error:
        return "completion_audit_dispatch_gate_count_invalid"
    if "string list" in error:
        return "completion_audit_dispatch_gate_string_list_invalid"
    return "completion_audit_dispatch_gate_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
