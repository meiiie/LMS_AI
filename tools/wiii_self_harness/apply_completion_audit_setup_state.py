#!/usr/bin/env python3
"""Apply privacy-safe setup handles to a completion-audit setup state."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from generate_completion_audit_setup_state import (  # noqa: E402
    SETUP_STATE_SCHEMA_VERSION,
    _error_code_counts as setup_state_error_code_counts,
    _error_codes as setup_state_error_codes,
    _setup_state_fingerprint,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


SETUP_HANDLE_PATCH_SCHEMA_VERSION = "wiii.completion_audit_setup_handle_patch.v1"
PATCH_TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "setup_state_sha256",
    "setup_state_schema_version",
    "setup_state_fingerprint_sha256",
    "checks",
    "privacy",
}
PATCH_CHECK_FIELDS = {
    "requirement_id",
    "category",
    "key",
    "source_handle",
}
PATCH_PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
}
APPLY_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup state apply output path must not be a directory"
)
APPLY_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup state apply output path must not be a symlink"
)
APPLY_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup state apply output path parent must not be a symlink"
)


def apply_completion_audit_setup_state(
    setup_state_path: Path,
    patch_path: Path,
    *,
    launch_pack_path: Path | None = None,
) -> dict[str, Any]:
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        raise ValueError(
            "completion audit setup state apply source failed validation: "
            + "; ".join(setup_validation.errors)
        )
    setup_payload = load_strict_json_file(setup_state_path)
    patch_payload = load_strict_json_file(patch_path)
    if not isinstance(setup_payload, dict):
        raise ValueError("completion audit setup state root must be an object")
    if not isinstance(patch_payload, dict):
        raise ValueError("completion audit setup handle patch root must be an object")
    patch_errors = _patch_errors(patch_payload)
    if patch_errors:
        raise ValueError(
            "completion audit setup handle patch failed validation: "
            + "; ".join(patch_errors)
        )
    source_errors = _patch_source_errors(
        patch_payload,
        setup_payload=setup_payload,
        setup_state_path=setup_state_path,
    )
    if source_errors:
        raise ValueError(
            "completion audit setup handle patch source mismatch: "
            + "; ".join(source_errors)
        )

    result = deepcopy(setup_payload)
    binding_errors = _patch_binding_errors(result, patch_payload)
    if binding_errors:
        raise ValueError("; ".join(binding_errors))
    index = _setup_check_index(result)
    for patch in patch_payload["checks"]:
        identity = (
            patch["requirement_id"],
            patch["category"],
            patch["key"],
        )
        check = index[identity]
        source_handle = patch["source_handle"]
        check["present"] = True
        check["source_handle"] = source_handle
        check["secret_value_included"] = False
        check["raw_identifier_included"] = False

    _refresh_setup_state_summary(result)
    result_errors = setup_validator._payload_errors(result)
    if launch_pack_path is not None:
        result_errors.extend(
            setup_validator._launch_pack_source_errors(
                result,
                launch_pack_path=launch_pack_path,
            )
        )
    if result_errors:
        raise ValueError(
            "completion audit setup state apply result failed validation: "
            + "; ".join(result_errors)
        )
    return result


def _patch_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(PATCH_TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - PATCH_TOP_LEVEL_FIELDS)
    if missing:
        errors.append("setup handle patch missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("setup handle patch has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != SETUP_HANDLE_PATCH_SCHEMA_VERSION:
        errors.append(
            "setup handle patch schema_version must be "
            f"{SETUP_HANDLE_PATCH_SCHEMA_VERSION!r}"
        )
    if payload.get("setup_state_schema_version") != SETUP_STATE_SCHEMA_VERSION:
        errors.append(
            "setup handle patch setup_state_schema_version must be "
            f"{SETUP_STATE_SCHEMA_VERSION!r}"
        )
    for field in ("setup_state_sha256", "setup_state_fingerprint_sha256"):
        value = payload.get(field)
        if not isinstance(value, str) or not setup_validator._is_fingerprint(value):
            errors.append(f"setup handle patch {field} must be a SHA-256 hex string")
    if payload.get("ok") is not True:
        errors.append("setup handle patch ok must be true")
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("setup handle patch checks must be a non-empty list")
    elif not all(isinstance(check, dict) for check in checks):
        errors.append("setup handle patch checks entries must be objects")
    else:
        for check in checks:
            errors.extend(_patch_check_errors(check))
    errors.extend(_patch_privacy_errors(payload.get("privacy")))
    return errors


def _patch_source_errors(
    patch_payload: dict[str, Any],
    *,
    setup_payload: dict[str, Any],
    setup_state_path: Path,
) -> list[str]:
    errors: list[str] = []
    expected_fields = {
        "setup_state_sha256": _sha256_file(setup_state_path),
        "setup_state_schema_version": setup_payload.get("schema_version"),
        "setup_state_fingerprint_sha256": setup_payload.get(
            "setup_state_fingerprint_sha256"
        ),
    }
    for field, expected in expected_fields.items():
        if patch_payload.get(field) != expected:
            errors.append(f"{field} must match setup state source")
    return errors


def _patch_check_errors(check: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(check) != PATCH_CHECK_FIELDS:
        errors.append("setup handle patch check fields must match contract")
    for field in ("requirement_id", "category", "key", "source_handle"):
        value = check.get(field)
        if not isinstance(value, str) or not value:
            errors.append(f"setup handle patch check {field} must be a non-empty string")
    source_handle = check.get("source_handle")
    if isinstance(source_handle, str) and not setup_validator._is_safe_binding_handle(
        source_handle
    ):
        errors.append("setup handle patch source_handle must be a safe token handle")
    return errors


def _patch_privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup handle patch privacy must be an object"]
    errors: list[str] = []
    if set(value) != PATCH_PRIVACY_FIELDS:
        errors.append("setup handle patch privacy fields must match contract")
    for field in PATCH_PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup handle patch privacy.{field} must be false")
    return errors


def _patch_binding_errors(
    setup_payload: dict[str, Any],
    patch_payload: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    index = _setup_check_index(setup_payload)
    seen: set[tuple[str, str, str]] = set()
    checks = patch_payload.get("checks")
    if not isinstance(checks, list):
        return errors
    for patch in checks:
        if not isinstance(patch, dict):
            continue
        identity = (
            patch.get("requirement_id"),
            patch.get("category"),
            patch.get("key"),
        )
        if not all(isinstance(value, str) for value in identity):
            continue
        typed_identity = (
            str(identity[0]),
            str(identity[1]),
            str(identity[2]),
        )
        if typed_identity in seen:
            errors.append(
                "completion audit setup handle patch must not duplicate setup checks"
            )
            continue
        seen.add(typed_identity)
        check = index.get(typed_identity)
        if check is None:
            errors.append(
                "completion audit setup handle patch references unknown setup check"
            )
            continue
        source_handle = patch.get("source_handle")
        if source_handle not in check.get("binding_tokens", []):
            errors.append(
                "completion audit setup handle patch source_handle must match a "
                "binding token"
            )
    return errors


def _setup_check_index(
    setup_payload: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    requirements = setup_payload.get("requirements")
    if not isinstance(requirements, list):
        return index
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = requirement.get("requirement_id")
        checks = requirement.get("setup_checks")
        if not isinstance(requirement_id, str) or not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict):
                continue
            category = check.get("category")
            key = check.get("key")
            if isinstance(category, str) and isinstance(key, str):
                index[(requirement_id, category, key)] = check
    return index


def _refresh_setup_state_summary(payload: dict[str, Any]) -> None:
    requirements = payload["requirements"]
    ready_count = 0
    for requirement in requirements:
        checks = requirement["setup_checks"]
        ready = all(check["present"] is True for check in checks)
        requirement["dispatch_ready"] = ready
        requirement["setup_status"] = "ready" if ready else "pending"
        if ready:
            ready_count += 1
    payload["dispatch_ready"] = ready_count == len(requirements) and bool(requirements)
    payload["ready_requirement_count"] = ready_count
    payload["blocked_requirement_count"] = len(requirements) - ready_count
    payload["setup_state_fingerprint_sha256"] = _setup_state_fingerprint(requirements)
    payload["privacy"] = {
        "secret_values_included": False,
        "credential_values_included": False,
        "raw_identifiers_included": False,
    }
    payload["errors"] = []
    payload["error_codes"] = setup_state_error_codes([])
    payload["error_code_counts"] = setup_state_error_code_counts([])


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(APPLY_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(APPLY_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(APPLY_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Apply privacy-safe setup handles to a completion-audit setup state "
            "without writing secret values or raw identifiers."
        ),
    )
    parser.add_argument("setup_state", type=Path)
    parser.add_argument("patch", type=Path)
    parser.add_argument(
        "--launch-pack",
        type=Path,
        default=None,
        help="Optional launch pack source that the setup state must continue to match.",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        result = apply_completion_audit_setup_state(
            args.setup_state,
            args.patch,
            launch_pack_path=args.launch_pack,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_STATE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "source failed validation" in error:
        return "completion_audit_setup_state_apply_source_invalid"
    if "patch source mismatch" in error:
        return "completion_audit_setup_state_apply_patch_source_mismatch"
    if "patch failed validation" in error:
        return "completion_audit_setup_state_apply_patch_invalid"
    if "duplicate setup checks" in error:
        return "completion_audit_setup_state_apply_duplicate_check"
    if "unknown setup check" in error:
        return "completion_audit_setup_state_apply_unknown_check"
    if "source_handle must match" in error:
        return "completion_audit_setup_state_apply_unbound_handle"
    if "result failed validation" in error:
        return "completion_audit_setup_state_apply_result_invalid"
    if error == APPLY_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_state_apply_output_path_directory"
    if error == APPLY_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_state_apply_output_path_symlink"
    if error == APPLY_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_state_apply_output_path_parent_symlink"
    return "completion_audit_setup_state_apply_failed"


if __name__ == "__main__":
    raise SystemExit(main())
