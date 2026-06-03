#!/usr/bin/env python3
"""Validate completion-audit recovery work-order status artifacts."""

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
import report_completion_audit_recovery_work_order_status as reporter  # noqa: E402


WORK_ORDER_STATUS_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_work_order_status_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "recovery_work_order_path",
    "recovery_work_order_sha256",
    "recovery_work_order_schema_version",
    "recovery_work_order_fingerprint_sha256",
    "recovery_queue_path",
    "recovery_plan_path",
    "handoff_json_path",
    "setup_state_path",
    "setup_state_sha256",
    "setup_state_schema_version",
    "setup_state_fingerprint_sha256",
    "work_order_state",
    "status_state",
    "selected_group_ids",
    "selected_group_complete",
    "completed_group_ids",
    "pending_group_ids",
    "task_status_count",
    "satisfied_task_count",
    "pending_task_count",
    "setup_task_satisfied_count",
    "autonomous_task_ready_count",
    "task_status_fingerprint_sha256",
    "task_statuses",
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


@dataclass(frozen=True)
class WorkOrderStatusValidationResult:
    validation_schema_version: str
    recovery_work_order_status_path: str
    recovery_work_order_path: str | None
    recovery_queue_path: str | None
    recovery_plan_path: str | None
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


def validate_recovery_work_order_status(
    recovery_work_order_status_path: Path,
    *,
    recovery_work_order_path: Path | None = None,
    recovery_queue_path: Path | None = None,
    recovery_plan_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> WorkOrderStatusValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_work_order_status_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if recovery_work_order_path is not None:
            errors.extend(
                _source_errors(
                    payload,
                    recovery_work_order_path=recovery_work_order_path,
                    recovery_queue_path=recovery_queue_path,
                    recovery_plan_path=recovery_plan_path,
                    handoff_json_path=handoff_json_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
        elif (
            recovery_queue_path is not None
            or recovery_plan_path is not None
            or handoff_json_path is not None
            or setup_state_path is not None
            or launch_pack_path is not None
        ):
            errors.append(
                "completion audit recovery work order status source validation "
                "requires --recovery-work-order"
            )
    return WorkOrderStatusValidationResult(
        validation_schema_version=WORK_ORDER_STATUS_VALIDATION_SCHEMA_VERSION,
        recovery_work_order_status_path=str(recovery_work_order_status_path),
        recovery_work_order_path=(
            str(recovery_work_order_path) if recovery_work_order_path else None
        ),
        recovery_queue_path=str(recovery_queue_path) if recovery_queue_path else None,
        recovery_plan_path=str(recovery_plan_path) if recovery_plan_path else None,
        handoff_json_path=str(handoff_json_path) if handoff_json_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append(
            "completion audit recovery work order status path must be a regular file"
        )
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"completion audit recovery work order status JSON is invalid: {exc}"
        )
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit recovery work order status root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery work order status missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery work order status has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != reporter.WORK_ORDER_STATUS_SCHEMA_VERSION:
        errors.append(
            "completion audit recovery work order status schema_version must be "
            f"{reporter.WORK_ORDER_STATUS_SCHEMA_VERSION}"
        )
    for field in ("ok", "selected_group_complete"):
        if not isinstance(payload.get(field), bool):
            errors.append(
                f"completion audit recovery work order status {field} must be a boolean"
            )
    for field in (
        "recovery_work_order_path",
        "recovery_work_order_schema_version",
        "recovery_work_order_fingerprint_sha256",
        "work_order_state",
        "status_state",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(
                f"completion audit recovery work order status {field} must be non-empty"
            )
    for field in (
        "recovery_queue_path",
        "recovery_plan_path",
        "handoff_json_path",
        "setup_state_path",
        "setup_state_schema_version",
        "setup_state_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str):
            errors.append(
                f"completion audit recovery work order status {field} must be a string"
            )
    if payload.get("status_state") not in reporter.STATUS_STATES:
        errors.append(
            "completion audit recovery work order status status_state is unsupported"
        )
    for field in (
        "recovery_work_order_sha256",
        "recovery_work_order_fingerprint_sha256",
        "task_status_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(
                f"completion audit recovery work order status {field} must be SHA-256"
            )
    for field in ("setup_state_sha256", "setup_state_fingerprint_sha256"):
        value = payload.get(field)
        if value != "" and not _is_fingerprint(value):
            errors.append(
                f"completion audit recovery work order status {field} must be SHA-256"
            )
    for field in (
        "task_status_count",
        "satisfied_task_count",
        "pending_task_count",
        "setup_task_satisfied_count",
        "autonomous_task_ready_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(
                f"completion audit recovery work order status {field} must be non-negative"
            )
    for field in ("selected_group_ids", "completed_group_ids", "pending_group_ids"):
        if not _is_string_list(payload.get(field)):
            errors.append(
                f"completion audit recovery work order status {field} must be a string list"
            )
    task_errors, task_statuses = _task_status_errors(payload.get("task_statuses"))
    errors.extend(task_errors)
    if not task_errors:
        errors.extend(_summary_errors(payload, task_statuses))
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    return errors


def _task_status_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    statuses: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return [
            "completion audit recovery work order status task_statuses must be a list"
        ], []
    item_ids: list[str] = []
    for status in value:
        if not isinstance(status, dict):
            errors.append(
                "completion audit recovery work order status task_status entries must be objects"
            )
            continue
        statuses.append(status)
        fields = set(status)
        missing = sorted(reporter.TASK_STATUS_FIELDS - fields)
        extra = sorted(fields - reporter.TASK_STATUS_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery work order status task_status missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery work order status task_status has unsupported field(s): "
                + ", ".join(extra)
            )
        item_id = status.get("item_id")
        if isinstance(item_id, str) and item_id:
            item_ids.append(item_id)
        else:
            errors.append(
                "completion audit recovery work order status task_status item_id must be non-empty"
            )
        for field in ("group_id", "action_type", "status", "next_action"):
            if not isinstance(status.get(field), str) or not status.get(field):
                errors.append(
                    f"completion audit recovery work order status task_status {field} must be non-empty"
                )
        if status.get("status") not in reporter.TASK_STATUSES:
            errors.append(
                "completion audit recovery work order status task_status status is unsupported"
            )
        for field in (
            "requirement_id",
            "setup_category",
            "setup_key",
            "setup_evidence_kind",
            "source_handle",
        ):
            if not isinstance(status.get(field), str):
                errors.append(
                    f"completion audit recovery work order status task_status {field} must be a string"
                )
        for field in ("operator_setup_required", "safe_to_execute_autonomously"):
            if not isinstance(status.get(field), bool):
                errors.append(
                    f"completion audit recovery work order status task_status {field} must be a boolean"
                )
    if len(item_ids) != len(set(item_ids)):
        errors.append(
            "completion audit recovery work order status task_status item_id values must be unique"
        )
    return errors, statuses


def _summary_errors(
    payload: dict[str, Any],
    task_statuses: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    expected_counts = {
        "task_status_count": len(task_statuses),
        "satisfied_task_count": sum(
            1 for status in task_statuses if status.get("status") == "satisfied"
        ),
        "pending_task_count": sum(
            1
            for status in task_statuses
            if status.get("status") in reporter._pending_statuses()
        ),
        "setup_task_satisfied_count": sum(
            1
            for status in task_statuses
            if status.get("operator_setup_required") is True
            and status.get("status") == "satisfied"
        ),
        "autonomous_task_ready_count": sum(
            1
            for status in task_statuses
            if status.get("status") == "ready_for_dispatch"
        ),
    }
    for field, expected in expected_counts.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit recovery work order status {field} must match task_statuses"
            )
    selected_group_ids = _string_list(payload.get("selected_group_ids"))
    expected_completed = []
    for group_id in selected_group_ids:
        group_statuses = [
            status for status in task_statuses if status.get("group_id") == group_id
        ]
        if group_statuses and all(status.get("status") == "satisfied" for status in group_statuses):
            expected_completed.append(group_id)
    expected_pending = [
        group_id for group_id in selected_group_ids if group_id not in expected_completed
    ]
    if payload.get("completed_group_ids") != expected_completed:
        errors.append(
            "completion audit recovery work order status completed_group_ids must match task_statuses"
        )
    if payload.get("pending_group_ids") != expected_pending:
        errors.append(
            "completion audit recovery work order status pending_group_ids must match task_statuses"
        )
    if payload.get("selected_group_complete") != (
        bool(selected_group_ids) and not expected_pending
    ):
        errors.append(
            "completion audit recovery work order status selected_group_complete must match groups"
        )
    if payload.get("task_status_fingerprint_sha256") != (
        reporter._task_status_fingerprint(task_statuses)
    ):
        errors.append(
            "completion audit recovery work order status task_status_fingerprint_sha256 "
            "must match task_statuses"
        )
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["completion audit recovery work order status privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(PRIVACY_FIELDS - fields)
    extra = sorted(fields - PRIVACY_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery work order status privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery work order status privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(
                f"completion audit recovery work order status privacy {field} must be false"
            )
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    recovery_work_order_path: Path,
    recovery_queue_path: Path | None,
    recovery_plan_path: Path | None,
    handoff_json_path: Path | None,
    setup_state_path: Path | None,
    launch_pack_path: Path | None,
) -> list[str]:
    expected = reporter.report_completion_audit_recovery_work_order_status(
        recovery_work_order_path,
        recovery_queue_path=recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    if payload != expected:
        return ["completion audit recovery work order status must match sources"]
    return []


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return [
            "completion audit recovery work order status errors must be a string list"
        ]
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes):
        if error_codes != expected_codes:
            result.append(
                "completion audit recovery work order status error_codes must match errors"
            )
    else:
        result.append(
            "completion audit recovery work order status error_codes must be a string list"
        )
    if error_code_counts != expected_counts:
        result.append(
            "completion audit recovery work order status error_code_counts must match errors"
        )
    expected_ok = not errors
    if isinstance(payload.get("ok"), bool) and payload["ok"] != expected_ok:
        result.append("completion audit recovery work order status ok must match errors")
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
    if error == "completion audit recovery work order status path must be a regular file":
        return "completion_audit_recovery_work_order_status_path_invalid"
    if error.startswith("completion audit recovery work order status JSON is invalid"):
        return "completion_audit_recovery_work_order_status_json_invalid"
    if error == "completion audit recovery work order status root must be an object":
        return "completion_audit_recovery_work_order_status_root_invalid"
    if error == "completion audit recovery work order status must match sources":
        return "completion_audit_recovery_work_order_status_source_mismatch"
    if "source validation requires" in error:
        return "completion_audit_recovery_work_order_status_source_mismatch"
    if error.startswith(
        "completion audit recovery work order status missing required field"
    ):
        return "completion_audit_recovery_work_order_status_missing_required_fields"
    if error.startswith(
        "completion audit recovery work order status has unsupported field"
    ):
        return "completion_audit_recovery_work_order_status_unsupported_fields"
    if error.startswith(
        "completion audit recovery work order status schema_version must be"
    ):
        return "completion_audit_recovery_work_order_status_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_recovery_work_order_status_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_work_order_status_privacy_invalid"
    if "task_status" in error or "task_statuses" in error:
        return "completion_audit_recovery_work_order_status_task_invalid"
    if "status_state" in error:
        return "completion_audit_recovery_work_order_status_state_invalid"
    if "count" in error or "non-negative" in error:
        return "completion_audit_recovery_work_order_status_count_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_recovery_work_order_status_error_summary_invalid"
    if "boolean" in error or error.endswith("must match errors"):
        return "completion_audit_recovery_work_order_status_boolean_invalid"
    if "string list" in error:
        return "completion_audit_recovery_work_order_status_string_list_invalid"
    return "completion_audit_recovery_work_order_status_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a recovery work-order status report.",
    )
    parser.add_argument("recovery_work_order_status", type=Path)
    parser.add_argument("--recovery-work-order", type=Path, default=None)
    parser.add_argument("--recovery-queue", type=Path, default=None)
    parser.add_argument("--recovery-plan", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_recovery_work_order_status(
        args.recovery_work_order_status,
        recovery_work_order_path=args.recovery_work_order,
        recovery_queue_path=args.recovery_queue,
        recovery_plan_path=args.recovery_plan,
        handoff_json_path=args.handoff_json,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif result.ok:
        text = "Wiii Completion Audit Recovery Work Order Status Validation: PASS\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Work Order Status Validation: FAIL\n"
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
