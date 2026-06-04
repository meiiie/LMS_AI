#!/usr/bin/env python3
"""Validate completion-audit recovery work-order artifacts."""

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
import generate_completion_audit_recovery_work_order as generator  # noqa: E402
import validate_completion_audit_recovery_queue as queue_validator  # noqa: E402


RECOVERY_WORK_ORDER_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_work_order_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "recovery_queue_path",
    "recovery_queue_sha256",
    "recovery_queue_schema_version",
    "recovery_queue_group_status_fingerprint_sha256",
    "recovery_plan_path",
    "recovery_plan_sha256",
    "recovery_plan_schema_version",
    "recovery_plan_action_items_fingerprint_sha256",
    "recovery_plan_execution_groups_fingerprint_sha256",
    "handoff_json_path",
    "handoff_json_sha256",
    "queue_state",
    "work_order_state",
    "selected_group_ids",
    "selected_action_item_count",
    "setup_task_count",
    "runtime_task_count",
    "gate_task_count",
    "autonomous_dispatch_allowed",
    "operator_setup_required",
    "blocked_dependency_group_ids",
    "work_order_fingerprint_sha256",
    "tasks",
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


@dataclass(frozen=True)
class RecoveryWorkOrderValidationResult:
    validation_schema_version: str
    recovery_work_order_path: str
    recovery_queue_path: str | None
    recovery_plan_path: str | None
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


def validate_recovery_work_order(
    recovery_work_order_path: Path,
    *,
    recovery_queue_path: Path | None = None,
    recovery_plan_path: Path | None = None,
    handoff_json_path: Path | None = None,
) -> RecoveryWorkOrderValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_work_order_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if recovery_queue_path is not None or recovery_plan_path is not None:
            errors.extend(
                _source_errors(
                    payload,
                    recovery_queue_path=recovery_queue_path,
                    recovery_plan_path=recovery_plan_path,
                    handoff_json_path=handoff_json_path,
                )
            )
        elif handoff_json_path is not None:
            errors.append(
                "completion audit recovery work order source validation requires "
                "--recovery-queue and --recovery-plan"
            )
    return RecoveryWorkOrderValidationResult(
        validation_schema_version=RECOVERY_WORK_ORDER_VALIDATION_SCHEMA_VERSION,
        recovery_work_order_path=str(recovery_work_order_path),
        recovery_queue_path=str(recovery_queue_path) if recovery_queue_path else None,
        recovery_plan_path=str(recovery_plan_path) if recovery_plan_path else None,
        handoff_json_path=str(handoff_json_path) if handoff_json_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit recovery work order path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery work order JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit recovery work order root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery work order missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery work order has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != generator.RECOVERY_WORK_ORDER_SCHEMA_VERSION:
        errors.append(
            "completion audit recovery work order schema_version must be "
            f"{generator.RECOVERY_WORK_ORDER_SCHEMA_VERSION}"
        )
    if payload.get("mode") != "dry_run":
        errors.append("completion audit recovery work order mode must be dry_run")
    if payload.get("dry_run") is not True:
        errors.append("completion audit recovery work order dry_run must be true")
    for field in (
        "ok",
        "autonomous_dispatch_allowed",
        "operator_setup_required",
    ):
        if not isinstance(payload.get(field), bool):
            errors.append(
                f"completion audit recovery work order {field} must be a boolean"
            )
    for field in (
        "recovery_queue_path",
        "recovery_queue_schema_version",
        "recovery_plan_path",
        "recovery_plan_schema_version",
        "queue_state",
        "work_order_state",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(
                f"completion audit recovery work order {field} must be non-empty"
            )
    if payload.get("work_order_state") not in generator.WORK_ORDER_STATES:
        errors.append(
            "completion audit recovery work order work_order_state is unsupported"
        )
    for field in ("handoff_json_path",):
        if not isinstance(payload.get(field), str):
            errors.append(
                f"completion audit recovery work order {field} must be a string"
            )
    for field in (
        "recovery_queue_sha256",
        "recovery_queue_group_status_fingerprint_sha256",
        "recovery_plan_sha256",
        "recovery_plan_action_items_fingerprint_sha256",
        "recovery_plan_execution_groups_fingerprint_sha256",
        "work_order_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"completion audit recovery work order {field} must be SHA-256")
    handoff_sha = payload.get("handoff_json_sha256")
    if handoff_sha != "" and not _is_fingerprint(handoff_sha):
        errors.append(
            "completion audit recovery work order handoff_json_sha256 must be SHA-256"
        )
    for field in (
        "selected_action_item_count",
        "setup_task_count",
        "runtime_task_count",
        "gate_task_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(
                f"completion audit recovery work order {field} must be non-negative"
            )
    for field in ("selected_group_ids", "blocked_dependency_group_ids"):
        if not _is_string_list(payload.get(field)):
            errors.append(
                f"completion audit recovery work order {field} must be a string list"
            )
    task_errors, tasks = _task_errors(payload.get("tasks"))
    errors.extend(task_errors)
    if not task_errors:
        errors.extend(_summary_errors(payload, tasks))
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    return errors


def _task_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    tasks: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["completion audit recovery work order tasks must be a list"], []
    item_ids: list[str] = []
    for task in value:
        if not isinstance(task, dict):
            errors.append("completion audit recovery work order task entries must be objects")
            continue
        tasks.append(task)
        fields = set(task)
        missing = sorted(generator.WORK_ORDER_TASK_FIELDS - fields)
        extra = sorted(fields - generator.WORK_ORDER_TASK_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery work order task missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery work order task has unsupported field(s): "
                + ", ".join(extra)
            )
        item_id = task.get("item_id")
        if isinstance(item_id, str) and item_id:
            item_ids.append(item_id)
        else:
            errors.append(
                "completion audit recovery work order task item_id must be non-empty"
            )
        for field in ("group_id", "kind", "action_type", "status", "next_instruction"):
            if not isinstance(task.get(field), str) or not task.get(field):
                errors.append(
                    f"completion audit recovery work order task {field} must be non-empty"
                )
        if task.get("action_type") not in ACTION_TYPES:
            errors.append(
                "completion audit recovery work order task action_type is unsupported"
            )
        for field in (
            "safe_to_execute_autonomously",
            "operator_setup_required",
        ):
            if not isinstance(task.get(field), bool):
                errors.append(
                    f"completion audit recovery work order task {field} must be a boolean"
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
            if not _is_string_list(task.get(field)):
                errors.append(
                    f"completion audit recovery work order task {field} must be a string list"
                )
        for field in (
            "binding_token_count",
            "attestation_option_count",
            "pending_setup_check_count",
        ):
            if not _is_non_negative_int(task.get(field)):
                errors.append(
                    f"completion audit recovery work order task {field} must be non-negative"
                )
        errors.extend(_task_type_errors(task))
    if len(item_ids) != len(set(item_ids)):
        errors.append(
            "completion audit recovery work order task item_id values must be unique"
        )
    return errors, tasks


def _task_type_errors(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    action_type = task.get("action_type")
    if action_type == "setup_resolution":
        if task.get("operator_setup_required") is not True:
            errors.append(
                "completion audit recovery work order setup tasks must require operator setup"
            )
        if task.get("safe_to_execute_autonomously") is not False:
            errors.append(
                "completion audit recovery work order setup tasks must not be autonomous"
            )
        for field in (
            "requirement_id",
            "setup_category",
            "setup_key",
            "setup_evidence_kind",
        ):
            if not isinstance(task.get(field), str) or not task.get(field):
                errors.append(
                    f"completion audit recovery work order setup task {field} must be non-empty"
                )
    if action_type == "workflow_probe_recovery":
        for field in ("requirement_id", "artifact", "workflow", "probe"):
            if not isinstance(task.get(field), str) or not task.get(field):
                errors.append(
                    f"completion audit recovery work order runtime task {field} must be non-empty"
                )
    if action_type == "gate_dependency":
        for field in ("blocker_id", "gate_reason"):
            if not isinstance(task.get(field), str) or not task.get(field):
                errors.append(
                    f"completion audit recovery work order gate task {field} must be non-empty"
                )
    return errors


def _summary_errors(
    payload: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    expected_counts = {
        "selected_action_item_count": len(tasks),
        "setup_task_count": sum(
            1 for task in tasks if task.get("action_type") == "setup_resolution"
        ),
        "runtime_task_count": sum(
            1 for task in tasks if task.get("action_type") == "workflow_probe_recovery"
        ),
        "gate_task_count": sum(
            1 for task in tasks if task.get("action_type") == "gate_dependency"
        ),
    }
    for field, expected in expected_counts.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit recovery work order {field} must match tasks"
            )
    expected_operator = any(task.get("operator_setup_required") is True for task in tasks)
    expected_autonomous = bool(tasks) and all(
        task.get("safe_to_execute_autonomously") is True for task in tasks
    )
    if payload.get("operator_setup_required") != expected_operator:
        errors.append(
            "completion audit recovery work order operator_setup_required must match tasks"
        )
    if payload.get("autonomous_dispatch_allowed") != expected_autonomous:
        errors.append(
            "completion audit recovery work order autonomous_dispatch_allowed must match tasks"
        )
    expected_state = _expected_work_order_state(payload, tasks)
    if payload.get("work_order_state") != expected_state:
        errors.append(
            "completion audit recovery work order work_order_state must match tasks"
        )
    expected_fingerprint = generator._work_order_fingerprint(
        work_order_state=str(payload.get("work_order_state") or ""),
        selected_group_ids=_string_list(payload.get("selected_group_ids")),
        tasks=tasks,
        autonomous_dispatch_allowed=payload.get("autonomous_dispatch_allowed") is True,
        operator_setup_required=payload.get("operator_setup_required") is True,
        blocked_dependency_group_ids=_string_list(
            payload.get("blocked_dependency_group_ids")
        ),
    )
    if payload.get("work_order_fingerprint_sha256") != expected_fingerprint:
        errors.append(
            "completion audit recovery work order work_order_fingerprint_sha256 "
            "must match tasks"
        )
    return errors


def _expected_work_order_state(
    payload: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "invalid"
    queue_state = payload.get("queue_state")
    if queue_state == "empty":
        return "empty"
    if queue_state == "release_ready":
        return "release_ready"
    if _string_list(payload.get("blocked_dependency_group_ids")):
        return "blocked_by_dependency"
    if any(task.get("operator_setup_required") is True for task in tasks):
        return "operator_setup_required"
    if bool(tasks) and all(
        task.get("safe_to_execute_autonomously") is True for task in tasks
    ):
        return "autonomous_dispatch_ready"
    return "blocked"


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["completion audit recovery work order privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(PRIVACY_FIELDS - fields)
    extra = sorted(fields - PRIVACY_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery work order privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery work order privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(
                f"completion audit recovery work order privacy {field} must be false"
            )
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    recovery_queue_path: Path | None,
    recovery_plan_path: Path | None,
    handoff_json_path: Path | None,
) -> list[str]:
    if recovery_queue_path is None or recovery_plan_path is None:
        return [
            "completion audit recovery work order source mismatch: "
            "--recovery-queue and --recovery-plan are required together"
        ]
    queue_validation = queue_validator.validate_recovery_queue(
        recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not queue_validation.ok:
        return [
            "completion audit recovery work order source mismatch: queue "
            "failed validation: "
            + "; ".join(queue_validation.errors)
        ]
    expected = generator.generate_completion_audit_recovery_work_order(
        recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
    ).to_dict()
    if payload != expected:
        return ["completion audit recovery work order must match source queue and plan"]
    return []


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return ["completion audit recovery work order errors must be a string list"]
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes):
        if error_codes != expected_codes:
            result.append(
                "completion audit recovery work order error_codes must match errors"
            )
    else:
        result.append(
            "completion audit recovery work order error_codes must be a string list"
        )
    if error_code_counts != expected_counts:
        result.append(
            "completion audit recovery work order error_code_counts must match errors"
        )
    expected_ok = not errors
    if isinstance(payload.get("ok"), bool) and payload["ok"] != expected_ok:
        result.append("completion audit recovery work order ok must match errors")
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
    if error == "completion audit recovery work order path must be a regular file":
        return "completion_audit_recovery_work_order_path_invalid"
    if error.startswith("completion audit recovery work order JSON is invalid"):
        return "completion_audit_recovery_work_order_json_invalid"
    if error == "completion audit recovery work order root must be an object":
        return "completion_audit_recovery_work_order_root_invalid"
    if error.startswith("completion audit recovery work order missing required field"):
        return "completion_audit_recovery_work_order_missing_required_fields"
    if error.startswith("completion audit recovery work order has unsupported field"):
        return "completion_audit_recovery_work_order_unsupported_fields"
    if error.startswith("completion audit recovery work order schema_version must be"):
        return "completion_audit_recovery_work_order_schema_mismatch"
    if error == "completion audit recovery work order must match source queue and plan":
        return "completion_audit_recovery_work_order_source_mismatch"
    if "source mismatch" in error or "source validation requires" in error:
        return "completion_audit_recovery_work_order_source_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_recovery_work_order_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_work_order_privacy_invalid"
    if "task" in error or "tasks" in error:
        return "completion_audit_recovery_work_order_task_invalid"
    if "work_order_state" in error:
        return "completion_audit_recovery_work_order_state_invalid"
    if "count" in error or "non-negative" in error:
        return "completion_audit_recovery_work_order_count_invalid"
    if "mode" in error or "dry_run" in error:
        return "completion_audit_recovery_work_order_mode_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_recovery_work_order_error_summary_invalid"
    if "boolean" in error or error.endswith("must match errors"):
        return "completion_audit_recovery_work_order_boolean_invalid"
    if "string list" in error:
        return "completion_audit_recovery_work_order_string_list_invalid"
    return "completion_audit_recovery_work_order_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit recovery work-order artifact.",
    )
    parser.add_argument("recovery_work_order", type=Path)
    parser.add_argument("--recovery-queue", type=Path, default=None)
    parser.add_argument("--recovery-plan", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_recovery_work_order(
        args.recovery_work_order,
        recovery_queue_path=args.recovery_queue,
        recovery_plan_path=args.recovery_plan,
        handoff_json_path=args.handoff_json,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif result.ok:
        text = "Wiii Completion Audit Recovery Work Order Validation: PASS\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Work Order Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors)
            + "\n"
        )
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
