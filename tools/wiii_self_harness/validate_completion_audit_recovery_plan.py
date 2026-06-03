#!/usr/bin/env python3
"""Validate completion-audit recovery plan artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from generate_completion_audit_recovery_plan import (  # noqa: E402
    ACTION_ITEM_FIELDS,
    EXECUTION_GROUP_FIELDS,
    RECOVERY_PLAN_SCHEMA_VERSION,
    _action_items_fingerprint,
    _execution_groups_fingerprint,
    generate_completion_audit_recovery_plan,
)
from strict_json import load_strict_json_file  # noqa: E402


RECOVERY_PLAN_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_plan_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "handoff_path",
    "handoff_sha256",
    "handoff_schema_version",
    "completion_audit_ready",
    "release_handoff_ready",
    "release_blocker_count",
    "action_item_count",
    "runtime_recovery_action_count",
    "setup_resolution_action_count",
    "gate_dependency_count",
    "action_items_fingerprint_sha256",
    "action_items",
    "execution_group_count",
    "execution_groups_fingerprint_sha256",
    "execution_groups",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_payload_included",
    "raw_identifiers_included",
}
ACTION_TYPES = {
    "workflow_probe_recovery",
    "setup_resolution",
    "gate_dependency",
    "missing_recovery_action",
}
EXECUTION_MODES = {
    "operator_setup",
    "workflow_dispatch_or_local_probe",
    "validation_gate",
}


@dataclass(frozen=True)
class RecoveryPlanValidationResult:
    validation_schema_version: str
    recovery_plan_path: str
    handoff_json_path: str | None
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


def validate_recovery_plan(
    recovery_plan_path: Path,
    *,
    handoff_json_path: Path | None = None,
) -> RecoveryPlanValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_plan_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if handoff_json_path is not None:
            errors.extend(
                _handoff_source_errors(
                    payload,
                    handoff_json_path=handoff_json_path,
                )
            )
    return RecoveryPlanValidationResult(
        validation_schema_version=RECOVERY_PLAN_VALIDATION_SCHEMA_VERSION,
        recovery_plan_path=str(recovery_plan_path),
        handoff_json_path=str(handoff_json_path) if handoff_json_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit recovery plan path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery plan JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit recovery plan root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery plan missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery plan has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != RECOVERY_PLAN_SCHEMA_VERSION:
        errors.append(
            f"completion audit recovery plan schema_version must be {RECOVERY_PLAN_SCHEMA_VERSION}"
        )
    for field in ("ok", "completion_audit_ready", "release_handoff_ready"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"completion audit recovery plan {field} must be a boolean")
    for field in (
        "handoff_path",
        "handoff_schema_version",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"completion audit recovery plan {field} must be non-empty")
    for field in (
        "handoff_sha256",
        "action_items_fingerprint_sha256",
        "execution_groups_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not FINGERPRINT_RE.match(
            payload.get(field, "")
        ):
            errors.append(f"completion audit recovery plan {field} must be SHA-256")
    for field in (
        "release_blocker_count",
        "action_item_count",
        "runtime_recovery_action_count",
        "setup_resolution_action_count",
        "gate_dependency_count",
        "execution_group_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(
                f"completion audit recovery plan {field} must be non-negative"
            )
    action_items = payload.get("action_items")
    action_item_ids: set[str] = set()
    if not isinstance(action_items, list):
        errors.append("completion audit recovery plan action_items must be a list")
    else:
        errors.extend(_action_item_errors(action_items))
        action_item_ids = {
            item["item_id"]
            for item in action_items
            if isinstance(item, dict) and isinstance(item.get("item_id"), str)
        }
        if _is_non_negative_int(payload.get("action_item_count")) and payload[
            "action_item_count"
        ] != len(action_items):
            errors.append(
                "completion audit recovery plan action_item_count must match action_items"
            )
        if payload.get("action_items_fingerprint_sha256") != _action_items_fingerprint(
            action_items
        ):
            errors.append(
                "completion audit recovery plan action_items_fingerprint_sha256 must match action_items"
            )
        _count_action_type(
            payload,
            action_items,
            field="runtime_recovery_action_count",
            action_type="workflow_probe_recovery",
            errors=errors,
        )
        _count_action_type(
            payload,
            action_items,
            field="setup_resolution_action_count",
            action_type="setup_resolution",
            errors=errors,
        )
        _count_action_type(
            payload,
            action_items,
            field="gate_dependency_count",
            action_type="gate_dependency",
            errors=errors,
        )
    execution_groups = payload.get("execution_groups")
    if not isinstance(execution_groups, list):
        errors.append("completion audit recovery plan execution_groups must be a list")
    else:
        errors.extend(_execution_group_errors(execution_groups, action_item_ids))
        if _is_non_negative_int(payload.get("execution_group_count")) and payload[
            "execution_group_count"
        ] != len(execution_groups):
            errors.append(
                "completion audit recovery plan execution_group_count must match execution_groups"
            )
        if payload.get("execution_groups_fingerprint_sha256") != (
            _execution_groups_fingerprint(execution_groups)
        ):
            errors.append(
                "completion audit recovery plan execution_groups_fingerprint_sha256 must match execution_groups"
            )
    if not _is_string_list(payload.get("errors")):
        errors.append("completion audit recovery plan errors must be a string list")
    if not _is_string_list(payload.get("error_codes")):
        errors.append("completion audit recovery plan error_codes must be a string list")
    if not isinstance(payload.get("error_code_counts"), dict):
        errors.append("completion audit recovery plan error_code_counts must be an object")
    expected_ok = isinstance(payload.get("errors"), list) and not payload["errors"]
    if isinstance(payload.get("ok"), bool) and payload["ok"] != expected_ok:
        errors.append("completion audit recovery plan ok must match errors")
    errors.extend(_privacy_errors(payload.get("privacy")))
    return errors


def _action_item_errors(action_items: list[Any]) -> list[str]:
    errors: list[str] = []
    item_ids: list[str] = []
    for item in action_items:
        if not isinstance(item, dict):
            errors.append("completion audit recovery plan action_item entries must be objects")
            continue
        fields = set(item)
        missing = sorted(ACTION_ITEM_FIELDS - fields)
        extra = sorted(fields - ACTION_ITEM_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery plan action_item missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery plan action_item has unsupported field(s): "
                + ", ".join(extra)
            )
        item_id = item.get("item_id")
        if isinstance(item_id, str) and item_id:
            item_ids.append(item_id)
        else:
            errors.append("completion audit recovery plan action_item item_id must be non-empty")
        action_type = item.get("action_type")
        if action_type not in ACTION_TYPES:
            errors.append(
                "completion audit recovery plan action_item action_type is unsupported"
            )
        for field in ("kind", "status"):
            if not isinstance(item.get(field), str):
                errors.append(
                    f"completion audit recovery plan action_item {field} must be a string"
                )
        for field in (
            "error_codes",
            "live_env_flags",
            "live_guard_tokens",
            "dispatch_or_schedule_gate_tokens",
            "artifact_tokens",
            "preflight_required_next",
            "source_handle_options",
            "diagnostic_pending_setup_keys",
            "non_diagnostic_pending_setup_keys",
        ):
            if not _is_string_list(item.get(field)):
                errors.append(
                    f"completion audit recovery plan action_item {field} must be a string list"
                )
        for field in (
            "binding_token_count",
            "attestation_option_count",
            "pending_setup_check_count",
        ):
            if not _is_non_negative_int(item.get(field)):
                errors.append(
                    f"completion audit recovery plan action_item {field} must be non-negative"
                )
        errors.extend(_action_type_errors(item))
    if len(item_ids) != len(set(item_ids)):
        errors.append("completion audit recovery plan action_item item_id values must be unique")
    return errors


def _action_type_errors(item: dict[str, Any]) -> list[str]:
    action_type = item.get("action_type")
    errors: list[str] = []
    if action_type == "workflow_probe_recovery":
        for field in ("requirement_id", "artifact", "workflow", "probe"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(
                    f"completion audit recovery plan workflow action {field} must be non-empty"
                )
    elif action_type == "setup_resolution":
        for field in ("requirement_id", "setup_category", "setup_key", "setup_evidence_kind"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(
                    f"completion audit recovery plan setup action {field} must be non-empty"
                )
    elif action_type == "gate_dependency":
        for field in ("blocker_id", "gate_reason"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(
                    f"completion audit recovery plan gate action {field} must be non-empty"
                )
    elif action_type == "missing_recovery_action":
        if not isinstance(item.get("requirement_id"), str) or not item.get(
            "requirement_id"
        ):
            errors.append(
                "completion audit recovery plan missing action requirement_id must be non-empty"
            )
    return errors


def _execution_group_errors(
    execution_groups: list[Any],
    action_item_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    group_ids: list[str] = []
    for group in execution_groups:
        if not isinstance(group, dict):
            errors.append(
                "completion audit recovery plan execution_group entries must be objects"
            )
            continue
        fields = set(group)
        missing = sorted(EXECUTION_GROUP_FIELDS - fields)
        extra = sorted(fields - EXECUTION_GROUP_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery plan execution_group missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery plan execution_group has unsupported field(s): "
                + ", ".join(extra)
            )
        group_id = group.get("group_id")
        if isinstance(group_id, str) and group_id:
            group_ids.append(group_id)
        else:
            errors.append(
                "completion audit recovery plan execution_group group_id must be non-empty"
            )
        if group.get("execution_mode") not in EXECUTION_MODES:
            errors.append(
                "completion audit recovery plan execution_group execution_mode is unsupported"
            )
        for field in ("title",):
            if not isinstance(group.get(field), str) or not group.get(field):
                errors.append(
                    f"completion audit recovery plan execution_group {field} must be non-empty"
                )
        for field in ("item_ids", "depends_on_group_ids"):
            if not _is_string_list(group.get(field)):
                errors.append(
                    f"completion audit recovery plan execution_group {field} must be a string list"
                )
        for field in ("blocked_by_external_setup", "ready_for_autonomous_dispatch"):
            if not isinstance(group.get(field), bool):
                errors.append(
                    f"completion audit recovery plan execution_group {field} must be a boolean"
                )
        item_ids = group.get("item_ids")
        if isinstance(item_ids, list):
            unknown = sorted(
                item_id
                for item_id in item_ids
                if isinstance(item_id, str) and item_id not in action_item_ids
            )
            if unknown:
                errors.append(
                    "completion audit recovery plan execution_group item_ids "
                    "must reference action_items"
                )
    if len(group_ids) != len(set(group_ids)):
        errors.append(
            "completion audit recovery plan execution_group group_id values must be unique"
        )
    known_group_ids = set(group_ids)
    for group in execution_groups:
        if not isinstance(group, dict):
            continue
        depends = group.get("depends_on_group_ids")
        group_id = group.get("group_id")
        if not isinstance(depends, list):
            continue
        if group_id in depends:
            errors.append(
                "completion audit recovery plan execution_group must not depend on itself"
            )
        unknown = sorted(
            dependency
            for dependency in depends
            if isinstance(dependency, str) and dependency not in known_group_ids
        )
        if unknown:
            errors.append(
                "completion audit recovery plan execution_group dependencies "
                "must reference execution_groups"
            )
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["completion audit recovery plan privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(PRIVACY_FIELDS - fields)
    extra = sorted(fields - PRIVACY_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery plan privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery plan privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"completion audit recovery plan privacy {field} must be false")
    return errors


def _handoff_source_errors(
    payload: dict[str, Any],
    *,
    handoff_json_path: Path,
) -> list[str]:
    try:
        expected = generate_completion_audit_recovery_plan(handoff_json_path).to_dict()
    except Exception as exc:  # noqa: BLE001
        return [f"completion audit recovery plan handoff source invalid: {exc}"]
    if payload != expected:
        return ["completion audit recovery plan must match handoff source"]
    return []


def _count_action_type(
    payload: dict[str, Any],
    items: list[Any],
    *,
    field: str,
    action_type: str,
    errors: list[str],
) -> None:
    if not _is_non_negative_int(payload.get(field)):
        return
    count = sum(
        1
        for item in items
        if isinstance(item, dict) and item.get("action_type") == action_type
    )
    if payload[field] != count:
        errors.append(f"completion audit recovery plan {field} must match action_items")


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
    )


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in errors:
        code = _error_code(error)
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit recovery plan path must be a regular file":
        return "completion_audit_recovery_plan_path_invalid"
    if error.startswith("completion audit recovery plan JSON is invalid:"):
        return "completion_audit_recovery_plan_json_invalid"
    if error == "completion audit recovery plan root must be an object":
        return "completion_audit_recovery_plan_root_invalid"
    if error.startswith("completion audit recovery plan missing required field"):
        return "completion_audit_recovery_plan_missing_required_fields"
    if error.startswith("completion audit recovery plan has unsupported field"):
        return "completion_audit_recovery_plan_unsupported_fields"
    if error.startswith("completion audit recovery plan schema_version must be"):
        return "completion_audit_recovery_plan_schema_mismatch"
    if error == "completion audit recovery plan must match handoff source":
        return "completion_audit_recovery_plan_handoff_mismatch"
    if error.startswith("completion audit recovery plan handoff source invalid:"):
        return "completion_audit_recovery_plan_handoff_invalid"
    if "fingerprint" in error:
        return "completion_audit_recovery_plan_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_plan_privacy_invalid"
    if "execution_group" in error:
        return "completion_audit_recovery_plan_execution_group_invalid"
    if "action_item" in error or " action " in error:
        return "completion_audit_recovery_plan_action_item_invalid"
    if error.endswith("must be a boolean") or error.endswith("must match errors"):
        return "completion_audit_recovery_plan_boolean_invalid"
    if error.endswith("must be non-negative") or "count" in error:
        return "completion_audit_recovery_plan_count_invalid"
    if error.endswith("must be a string list"):
        return "completion_audit_recovery_plan_string_list_invalid"
    return "completion_audit_recovery_plan_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit recovery plan."
    )
    parser.add_argument("recovery_plan", type=Path)
    parser.add_argument("--handoff-json", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = validate_recovery_plan(
        args.recovery_plan,
        handoff_json_path=args.handoff_json,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Plan Validation: "
            + ("PASS" if result.ok else "FAIL")
        )
        if result.errors:
            text += "\n" + "\n".join(f"- {error}" for error in result.errors)
        text += "\n"
    if args.out is not None:
        try:
            safe_write_report_text(args.out, text)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    else:
        print(text, end="")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
