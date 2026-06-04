#!/usr/bin/env python3
"""Validate completion-audit recovery dispatch authorization artifacts."""

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

from strict_json import load_strict_json_file  # noqa: E402
import generate_completion_audit_recovery_dispatch_authorization as generator  # noqa: E402


RECOVERY_DISPATCH_AUTHORIZATION_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_dispatch_authorization_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "recovery_queue_progress_path",
    "recovery_queue_progress_sha256",
    "recovery_queue_progress_schema_version",
    "queue_progress_fingerprint_sha256",
    "recovery_plan_path",
    "recovery_plan_sha256",
    "recovery_plan_schema_version",
    "recovery_plan_action_items_fingerprint_sha256",
    "recovery_plan_execution_groups_fingerprint_sha256",
    "dispatch_gate_path",
    "dispatch_gate_sha256",
    "dispatch_gate_schema_version",
    "dispatch_gate_fingerprint_sha256",
    "queue_state",
    "next_group_ids",
    "authorized_group_ids",
    "blocked_group_ids",
    "dispatch_gate_enforced",
    "live_command_specs_included",
    "authorization_state",
    "autonomous_dispatch_allowed",
    "candidate_group_count",
    "authorization_item_count",
    "ready_dispatch_item_count",
    "blocked_dispatch_item_count",
    "authorization_fingerprint_sha256",
    "dispatch_items",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
DISPATCH_ITEM_FIELDS = {
    "item_id",
    "group_id",
    "requirement_id",
    "workflow",
    "probe",
    "expected_artifact",
    "recovery_status",
    "error_codes",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gate_tokens",
    "artifact_tokens",
    "preflight_required_next",
    "recovery_contract_ready",
    "dispatch_gate_status",
    "dispatch_gate_ready",
    "authorization_ready",
    "unlocked_live_command_specs",
    "blocked_reasons",
}
COMMAND_SPEC_FIELDS = {"working_directory", "argv", "uses_shell"}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_payload_included",
    "raw_identifiers_included",
}


@dataclass(frozen=True)
class RecoveryDispatchAuthorizationValidationResult:
    validation_schema_version: str
    recovery_dispatch_authorization_path: str
    recovery_queue_progress_path: str | None
    recovery_plan_path: str | None
    dispatch_gate_path: str | None
    source_recovery_queue_path: str | None
    work_order_status_path: str | None
    recovery_work_order_path: str | None
    handoff_json_path: str | None
    setup_state_path: str | None
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


def validate_recovery_dispatch_authorization(
    recovery_dispatch_authorization_path: Path,
    *,
    recovery_queue_progress_path: Path | None = None,
    recovery_plan_path: Path | None = None,
    dispatch_gate_path: Path | None = None,
    source_recovery_queue_path: Path | None = None,
    work_order_status_path: Path | None = None,
    recovery_work_order_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> RecoveryDispatchAuthorizationValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_dispatch_authorization_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if recovery_queue_progress_path is not None or recovery_plan_path is not None:
            errors.extend(
                _source_errors(
                    payload,
                    recovery_queue_progress_path=recovery_queue_progress_path,
                    recovery_plan_path=recovery_plan_path,
                    dispatch_gate_path=dispatch_gate_path,
                    source_recovery_queue_path=source_recovery_queue_path,
                    work_order_status_path=work_order_status_path,
                    recovery_work_order_path=recovery_work_order_path,
                    handoff_json_path=handoff_json_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
    return RecoveryDispatchAuthorizationValidationResult(
        validation_schema_version=(
            RECOVERY_DISPATCH_AUTHORIZATION_VALIDATION_SCHEMA_VERSION
        ),
        recovery_dispatch_authorization_path=str(recovery_dispatch_authorization_path),
        recovery_queue_progress_path=(
            str(recovery_queue_progress_path) if recovery_queue_progress_path else None
        ),
        recovery_plan_path=str(recovery_plan_path) if recovery_plan_path else None,
        dispatch_gate_path=str(dispatch_gate_path) if dispatch_gate_path else None,
        source_recovery_queue_path=(
            str(source_recovery_queue_path) if source_recovery_queue_path else None
        ),
        work_order_status_path=(
            str(work_order_status_path) if work_order_status_path else None
        ),
        recovery_work_order_path=(
            str(recovery_work_order_path) if recovery_work_order_path else None
        ),
        handoff_json_path=str(handoff_json_path) if handoff_json_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append(
            "completion audit recovery dispatch authorization path must be a regular file"
        )
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"completion audit recovery dispatch authorization JSON is invalid: {exc}"
        )
        return None
    if not isinstance(payload, dict):
        errors.append(
            "completion audit recovery dispatch authorization root must be an object"
        )
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery dispatch authorization missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery dispatch authorization has unsupported field(s): "
            + ", ".join(extra)
        )
    if (
        payload.get("schema_version")
        != generator.RECOVERY_DISPATCH_AUTHORIZATION_SCHEMA_VERSION
    ):
        errors.append(
            "completion audit recovery dispatch authorization schema_version must be "
            f"{generator.RECOVERY_DISPATCH_AUTHORIZATION_SCHEMA_VERSION}"
        )
    if payload.get("mode") != "dry_run":
        errors.append(
            "completion audit recovery dispatch authorization mode must be dry_run"
        )
    if payload.get("dry_run") is not True:
        errors.append(
            "completion audit recovery dispatch authorization dry_run must be true"
        )
    for field in (
        "ok",
        "dispatch_gate_enforced",
        "live_command_specs_included",
        "autonomous_dispatch_allowed",
    ):
        if not isinstance(payload.get(field), bool):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be a boolean"
            )
    for field in (
        "recovery_queue_progress_path",
        "recovery_queue_progress_schema_version",
        "queue_progress_fingerprint_sha256",
        "recovery_plan_path",
        "recovery_plan_schema_version",
        "recovery_plan_action_items_fingerprint_sha256",
        "recovery_plan_execution_groups_fingerprint_sha256",
        "queue_state",
        "authorization_state",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be non-empty"
            )
    for field in (
        "dispatch_gate_path",
        "dispatch_gate_schema_version",
        "dispatch_gate_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be a string"
            )
    if payload.get("dispatch_gate_enforced") is True:
        for field in (
            "dispatch_gate_path",
            "dispatch_gate_schema_version",
            "dispatch_gate_fingerprint_sha256",
        ):
            if not payload.get(field):
                errors.append(
                    f"completion audit recovery dispatch authorization {field} must be non-empty when dispatch gate is enforced"
                )
    else:
        for field in (
            "dispatch_gate_path",
            "dispatch_gate_schema_version",
            "dispatch_gate_fingerprint_sha256",
            "dispatch_gate_sha256",
        ):
            if payload.get(field) not in {"", None}:
                errors.append(
                    f"completion audit recovery dispatch authorization {field} must be empty without dispatch gate enforcement"
                )
    for field in (
        "recovery_queue_progress_sha256",
        "queue_progress_fingerprint_sha256",
        "recovery_plan_sha256",
        "recovery_plan_action_items_fingerprint_sha256",
        "recovery_plan_execution_groups_fingerprint_sha256",
        "authorization_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be SHA-256"
            )
    for field in ("dispatch_gate_sha256", "dispatch_gate_fingerprint_sha256"):
        value = payload.get(field)
        if value != "" and not _is_fingerprint(value):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be SHA-256 or empty"
            )
    if payload.get("authorization_state") not in generator.AUTHORIZATION_STATES:
        errors.append(
            "completion audit recovery dispatch authorization authorization_state is unsupported"
        )
    for field in ("next_group_ids", "authorized_group_ids", "blocked_group_ids"):
        if not _is_string_list(payload.get(field)):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be a string list"
            )
    for field in (
        "candidate_group_count",
        "authorization_item_count",
        "ready_dispatch_item_count",
        "blocked_dispatch_item_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(
                f"completion audit recovery dispatch authorization {field} must be non-negative"
            )
    item_errors, dispatch_items = _dispatch_item_errors(payload.get("dispatch_items"))
    errors.extend(item_errors)
    if not item_errors:
        errors.extend(_summary_errors(payload, dispatch_items))
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    return errors


def _dispatch_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return [
            "completion audit recovery dispatch authorization dispatch_items must be a list"
        ], []
    item_ids: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item entries must be objects"
            )
            continue
        items.append(item)
        fields = set(item)
        missing = sorted(DISPATCH_ITEM_FIELDS - fields)
        extra = sorted(fields - DISPATCH_ITEM_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item has unsupported field(s): "
                + ", ".join(extra)
            )
        for field in (
            "item_id",
            "group_id",
            "requirement_id",
            "workflow",
            "probe",
            "expected_artifact",
            "recovery_status",
            "dispatch_gate_status",
        ):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(
                    f"completion audit recovery dispatch authorization dispatch_item {field} must be non-empty"
                )
        item_id = item.get("item_id")
        if isinstance(item_id, str) and item_id:
            item_ids.append(item_id)
        for field in (
            "error_codes",
            "live_env_flags",
            "live_guard_tokens",
            "dispatch_or_schedule_gate_tokens",
            "artifact_tokens",
            "preflight_required_next",
            "blocked_reasons",
        ):
            if not _is_string_list(item.get(field)):
                errors.append(
                    f"completion audit recovery dispatch authorization dispatch_item {field} must be a string list"
                )
        for field in (
            "recovery_contract_ready",
            "dispatch_gate_ready",
            "authorization_ready",
        ):
            if not isinstance(item.get(field), bool):
                errors.append(
                    f"completion audit recovery dispatch authorization dispatch_item {field} must be a boolean"
                )
        dispatch_gate_status = item.get("dispatch_gate_status")
        if dispatch_gate_status not in generator.DISPATCH_GATE_STATUSES:
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item dispatch_gate_status is unsupported"
            )
        if item.get("dispatch_gate_ready") is True and dispatch_gate_status != "matched_ready":
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item dispatch_gate_ready must match dispatch_gate_status"
            )
        if dispatch_gate_status == "matched_ready" and item.get("dispatch_gate_ready") is not True:
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item matched_ready must set dispatch_gate_ready"
            )
        if dispatch_gate_status == "matched_ready" and not item.get(
            "unlocked_live_command_specs"
        ):
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item matched_ready must include unlocked_live_command_specs"
            )
        if dispatch_gate_status != "matched_ready" and item.get(
            "unlocked_live_command_specs"
        ):
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item locked item must not include unlocked_live_command_specs"
            )
        if item.get("authorization_ready") is True and item.get("blocked_reasons"):
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item ready item must not have blocked_reasons"
            )
        expected_authorization_ready = (
            item.get("recovery_contract_ready") is True
            and dispatch_gate_status in {"not_supplied", "matched_ready"}
            and not item.get("blocked_reasons")
        )
        if item.get("authorization_ready") != expected_authorization_ready:
            errors.append(
                "completion audit recovery dispatch authorization dispatch_item authorization_ready must match gates"
            )
        errors.extend(_command_spec_errors(item.get("unlocked_live_command_specs")))
    if len(item_ids) != len(set(item_ids)):
        errors.append(
            "completion audit recovery dispatch authorization dispatch_item item_id values must be unique"
        )
    return errors, items


def _command_spec_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return [
            "completion audit recovery dispatch authorization unlocked_live_command_specs must be an object"
        ]
    errors: list[str] = []
    for command_name, spec in value.items():
        if command_name not in {"workflow_dispatch", "local_live_probe"}:
            errors.append(
                "completion audit recovery dispatch authorization unlocked_live_command_specs fields are unsupported"
            )
        if not isinstance(spec, dict):
            errors.append(
                "completion audit recovery dispatch authorization command spec must be an object"
            )
            continue
        if set(spec) != COMMAND_SPEC_FIELDS:
            errors.append(
                "completion audit recovery dispatch authorization command spec fields must match contract"
            )
        if not isinstance(spec.get("working_directory"), str) or not spec.get(
            "working_directory"
        ):
            errors.append(
                "completion audit recovery dispatch authorization command spec working_directory must be non-empty"
            )
        if not _is_string_list(spec.get("argv")) or not spec.get("argv"):
            errors.append(
                "completion audit recovery dispatch authorization command spec argv must be a non-empty string list"
            )
        if spec.get("uses_shell") is not False:
            errors.append(
                "completion audit recovery dispatch authorization command spec uses_shell must be false"
            )
    return errors


def _summary_errors(
    payload: dict[str, Any],
    dispatch_items: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    candidate_group_ids = sorted(
        {
            item.get("group_id")
            for item in dispatch_items
            if isinstance(item.get("group_id"), str) and item.get("group_id")
        }
    )
    authorized_group_ids = [
        group_id
        for group_id in candidate_group_ids
        if all(
            item.get("authorization_ready") is True
            for item in dispatch_items
            if item.get("group_id") == group_id
        )
    ]
    expected_counts = {
        "candidate_group_count": len(candidate_group_ids),
        "authorization_item_count": len(dispatch_items),
        "ready_dispatch_item_count": sum(
            1 for item in dispatch_items if item.get("authorization_ready") is True
        ),
        "blocked_dispatch_item_count": sum(
            1 for item in dispatch_items if item.get("authorization_ready") is not True
        ),
    }
    for field, expected in expected_counts.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit recovery dispatch authorization {field} must match dispatch_items"
            )
    if payload.get("authorized_group_ids") != authorized_group_ids:
        errors.append(
            "completion audit recovery dispatch authorization authorized_group_ids must match dispatch_items"
        )
    expected_blocked_groups = [
        group_id
        for group_id in _string_list(payload.get("next_group_ids"))
        if group_id not in set(authorized_group_ids)
    ]
    for group_id in candidate_group_ids:
        if group_id not in set(authorized_group_ids) and group_id not in expected_blocked_groups:
            expected_blocked_groups.append(group_id)
    if payload.get("blocked_group_ids") != expected_blocked_groups:
        errors.append(
            "completion audit recovery dispatch authorization blocked_group_ids must match next groups and dispatch_items"
        )
    expected_live_specs = any(
        bool(item.get("unlocked_live_command_specs")) for item in dispatch_items
    )
    if payload.get("live_command_specs_included") != expected_live_specs:
        errors.append(
            "completion audit recovery dispatch authorization live_command_specs_included must match dispatch_items"
        )
    if payload.get("dispatch_gate_enforced") is True:
        if any(item.get("dispatch_gate_status") == "not_supplied" for item in dispatch_items):
            errors.append(
                "completion audit recovery dispatch authorization enforced dispatch gate must be reflected in dispatch_items"
            )
    elif any(item.get("dispatch_gate_status") != "not_supplied" for item in dispatch_items):
        errors.append(
            "completion audit recovery dispatch authorization dispatch_items must not reference a dispatch gate when enforcement is disabled"
        )
    expected_state = _expected_authorization_state(payload, dispatch_items)
    if payload.get("authorization_state") != expected_state:
        errors.append(
            "completion audit recovery dispatch authorization authorization_state must match dispatch_items"
        )
    expected_allowed = payload.get("authorization_state") == "authorized"
    if payload.get("autonomous_dispatch_allowed") != expected_allowed:
        errors.append(
            "completion audit recovery dispatch authorization autonomous_dispatch_allowed must match authorization_state"
        )
    expected_fingerprint = generator._authorization_fingerprint(
        authorization_state=str(payload.get("authorization_state") or ""),
        authorized_group_ids=_string_list(payload.get("authorized_group_ids")),
        blocked_group_ids=_string_list(payload.get("blocked_group_ids")),
        dispatch_gate_enforced=payload.get("dispatch_gate_enforced") is True,
        live_command_specs_included=payload.get("live_command_specs_included") is True,
        dispatch_items=dispatch_items,
    )
    if payload.get("authorization_fingerprint_sha256") != expected_fingerprint:
        errors.append(
            "completion audit recovery dispatch authorization authorization_fingerprint_sha256 must match dispatch state"
        )
    return errors


def _expected_authorization_state(
    payload: dict[str, Any],
    dispatch_items: list[dict[str, Any]],
) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "invalid"
    if payload.get("queue_state") == "empty":
        return "empty"
    if payload.get("queue_state") != "ready_for_autonomous_dispatch":
        return "blocked_by_queue"
    if not dispatch_items:
        return "no_runtime_dispatch_ready"
    if any(item.get("recovery_contract_ready") is not True for item in dispatch_items):
        return "blocked_by_recovery_contract"
    if any(
        item.get("dispatch_gate_status") in {"matched_blocked", "not_matched"}
        for item in dispatch_items
    ):
        return "blocked_by_dispatch_gate"
    if all(item.get("authorization_ready") is True for item in dispatch_items):
        return "authorized"
    return "blocked_by_recovery_contract"


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["completion audit recovery dispatch authorization privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(PRIVACY_FIELDS - fields)
    extra = sorted(fields - PRIVACY_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery dispatch authorization privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery dispatch authorization privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(
                f"completion audit recovery dispatch authorization privacy {field} must be false"
            )
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    recovery_queue_progress_path: Path | None,
    recovery_plan_path: Path | None,
    dispatch_gate_path: Path | None,
    source_recovery_queue_path: Path | None,
    work_order_status_path: Path | None,
    recovery_work_order_path: Path | None,
    handoff_json_path: Path | None,
    setup_state_path: Path | None,
    launch_pack_path: Path | None,
) -> list[str]:
    if recovery_queue_progress_path is None or recovery_plan_path is None:
        return [
            "completion audit recovery dispatch authorization source mismatch: "
            "--queue-progress and --recovery-plan are required together"
        ]
    expected = generator.generate_completion_audit_recovery_dispatch_authorization(
        recovery_queue_progress_path,
        recovery_plan_path=recovery_plan_path,
        dispatch_gate_path=dispatch_gate_path,
        source_recovery_queue_path=source_recovery_queue_path,
        work_order_status_path=work_order_status_path,
        recovery_work_order_path=recovery_work_order_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    if payload != expected:
        return ["completion audit recovery dispatch authorization must match sources"]
    return []


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return [
            "completion audit recovery dispatch authorization errors must be a string list"
        ]
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes):
        if error_codes != expected_codes:
            result.append(
                "completion audit recovery dispatch authorization error_codes must match errors"
            )
    else:
        result.append(
            "completion audit recovery dispatch authorization error_codes must be a string list"
        )
    if error_code_counts != expected_counts:
        result.append(
            "completion audit recovery dispatch authorization error_code_counts must match errors"
        )
    expected_ok = not errors
    if isinstance(payload.get("ok"), bool) and payload["ok"] != expected_ok:
        result.append(
            "completion audit recovery dispatch authorization ok must match errors"
        )
    return result


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if (
        error
        == "completion audit recovery dispatch authorization path must be a regular file"
    ):
        return "completion_audit_recovery_dispatch_authorization_path_invalid"
    if error.startswith(
        "completion audit recovery dispatch authorization JSON is invalid"
    ):
        return "completion_audit_recovery_dispatch_authorization_json_invalid"
    if error == "completion audit recovery dispatch authorization root must be an object":
        return "completion_audit_recovery_dispatch_authorization_root_invalid"
    if error == "completion audit recovery dispatch authorization must match sources":
        return "completion_audit_recovery_dispatch_authorization_source_mismatch"
    if "source mismatch" in error:
        return "completion_audit_recovery_dispatch_authorization_source_mismatch"
    if error.startswith(
        "completion audit recovery dispatch authorization missing required field"
    ):
        return "completion_audit_recovery_dispatch_authorization_missing_required_fields"
    if error.startswith(
        "completion audit recovery dispatch authorization has unsupported field"
    ):
        return "completion_audit_recovery_dispatch_authorization_unsupported_fields"
    if error.startswith(
        "completion audit recovery dispatch authorization schema_version must be"
    ):
        return "completion_audit_recovery_dispatch_authorization_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_recovery_dispatch_authorization_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_dispatch_authorization_privacy_invalid"
    if "dispatch_item" in error or "command spec" in error:
        return "completion_audit_recovery_dispatch_authorization_dispatch_item_invalid"
    if "authorization_state" in error or "queue_state" in error:
        return "completion_audit_recovery_dispatch_authorization_state_invalid"
    if "count" in error or "non-negative" in error:
        return "completion_audit_recovery_dispatch_authorization_count_invalid"
    if "mode" in error or "dry_run" in error:
        return "completion_audit_recovery_dispatch_authorization_mode_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_recovery_dispatch_authorization_error_summary_invalid"
    if "boolean" in error or error.endswith("must match errors"):
        return "completion_audit_recovery_dispatch_authorization_boolean_invalid"
    if "string list" in error:
        return "completion_audit_recovery_dispatch_authorization_string_list_invalid"
    return "completion_audit_recovery_dispatch_authorization_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit recovery dispatch authorization.",
    )
    parser.add_argument("recovery_dispatch_authorization", type=Path)
    parser.add_argument("--queue-progress", type=Path, default=None)
    parser.add_argument("--recovery-plan", type=Path, default=None)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--source-recovery-queue", type=Path, default=None)
    parser.add_argument("--work-order-status", type=Path, default=None)
    parser.add_argument("--recovery-work-order", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_recovery_dispatch_authorization(
        args.recovery_dispatch_authorization,
        recovery_queue_progress_path=args.queue_progress,
        recovery_plan_path=args.recovery_plan,
        dispatch_gate_path=args.dispatch_gate,
        source_recovery_queue_path=args.source_recovery_queue,
        work_order_status_path=args.work_order_status,
        recovery_work_order_path=args.recovery_work_order,
        handoff_json_path=args.handoff_json,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif result.ok:
        text = "Wiii Completion Audit Recovery Dispatch Authorization Validation: PASS\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Dispatch Authorization Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors)
            + "\n"
        )
    if args.out:
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
