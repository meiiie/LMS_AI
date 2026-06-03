#!/usr/bin/env python3
"""Validate completion-audit recovery queue progress artifacts."""

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
import generate_completion_audit_recovery_queue_progress as generator  # noqa: E402
import run_completion_audit_recovery_queue as queue_runner  # noqa: E402


QUEUE_PROGRESS_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_queue_progress_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "source_recovery_queue_path",
    "source_recovery_queue_sha256",
    "source_recovery_queue_schema_version",
    "source_recovery_queue_group_status_fingerprint_sha256",
    "recovery_plan_path",
    "recovery_plan_sha256",
    "recovery_plan_schema_version",
    "recovery_plan_action_items_fingerprint_sha256",
    "recovery_plan_execution_groups_fingerprint_sha256",
    "work_order_status_path",
    "work_order_status_sha256",
    "work_order_status_schema_version",
    "work_order_status_task_status_fingerprint_sha256",
    "recovery_work_order_path",
    "handoff_json_path",
    "handoff_json_sha256",
    "previous_queue_state",
    "queue_state",
    "completed_group_ids",
    "pending_group_ids",
    "selected_group_complete",
    "advancement_applied",
    "execution_group_count",
    "ready_group_count",
    "blocked_group_count",
    "blocked_by_external_setup_count",
    "blocked_by_dependency_count",
    "complete_group_count",
    "ready_for_autonomous_dispatch_count",
    "next_group_ids",
    "group_status_fingerprint_sha256",
    "queue_progress_fingerprint_sha256",
    "group_statuses",
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
class QueueProgressValidationResult:
    validation_schema_version: str
    recovery_queue_progress_path: str
    source_recovery_queue_path: str | None
    recovery_plan_path: str | None
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


def validate_recovery_queue_progress(
    recovery_queue_progress_path: Path,
    *,
    source_recovery_queue_path: Path | None = None,
    recovery_plan_path: Path | None = None,
    work_order_status_path: Path | None = None,
    recovery_work_order_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> QueueProgressValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_queue_progress_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if (
            source_recovery_queue_path is not None
            or recovery_plan_path is not None
            or work_order_status_path is not None
        ):
            errors.extend(
                _source_errors(
                    payload,
                    source_recovery_queue_path=source_recovery_queue_path,
                    recovery_plan_path=recovery_plan_path,
                    work_order_status_path=work_order_status_path,
                    recovery_work_order_path=recovery_work_order_path,
                    handoff_json_path=handoff_json_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
    return QueueProgressValidationResult(
        validation_schema_version=QUEUE_PROGRESS_VALIDATION_SCHEMA_VERSION,
        recovery_queue_progress_path=str(recovery_queue_progress_path),
        source_recovery_queue_path=(
            str(source_recovery_queue_path) if source_recovery_queue_path else None
        ),
        recovery_plan_path=str(recovery_plan_path) if recovery_plan_path else None,
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
        errors.append("completion audit recovery queue progress path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery queue progress JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit recovery queue progress root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery queue progress missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery queue progress has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != generator.QUEUE_PROGRESS_SCHEMA_VERSION:
        errors.append(
            "completion audit recovery queue progress schema_version must be "
            f"{generator.QUEUE_PROGRESS_SCHEMA_VERSION}"
        )
    if payload.get("mode") != "dry_run":
        errors.append("completion audit recovery queue progress mode must be dry_run")
    if payload.get("dry_run") is not True:
        errors.append("completion audit recovery queue progress dry_run must be true")
    for field in ("ok", "selected_group_complete", "advancement_applied"):
        if not isinstance(payload.get(field), bool):
            errors.append(
                f"completion audit recovery queue progress {field} must be a boolean"
            )
    for field in (
        "source_recovery_queue_path",
        "source_recovery_queue_schema_version",
        "source_recovery_queue_group_status_fingerprint_sha256",
        "recovery_plan_path",
        "recovery_plan_schema_version",
        "recovery_plan_action_items_fingerprint_sha256",
        "recovery_plan_execution_groups_fingerprint_sha256",
        "work_order_status_path",
        "work_order_status_schema_version",
        "work_order_status_task_status_fingerprint_sha256",
        "previous_queue_state",
        "queue_state",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(
                f"completion audit recovery queue progress {field} must be non-empty"
            )
    for field in ("recovery_work_order_path", "handoff_json_path"):
        if not isinstance(payload.get(field), str):
            errors.append(
                f"completion audit recovery queue progress {field} must be a string"
            )
    for field in (
        "source_recovery_queue_sha256",
        "source_recovery_queue_group_status_fingerprint_sha256",
        "recovery_plan_sha256",
        "recovery_plan_action_items_fingerprint_sha256",
        "recovery_plan_execution_groups_fingerprint_sha256",
        "work_order_status_sha256",
        "work_order_status_task_status_fingerprint_sha256",
        "group_status_fingerprint_sha256",
        "queue_progress_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(
                f"completion audit recovery queue progress {field} must be SHA-256"
            )
    handoff_sha = payload.get("handoff_json_sha256")
    if handoff_sha != "" and not _is_fingerprint(handoff_sha):
        errors.append(
            "completion audit recovery queue progress handoff_json_sha256 must be SHA-256"
        )
    if payload.get("queue_state") not in queue_runner.QUEUE_STATES:
        errors.append(
            "completion audit recovery queue progress queue_state is unsupported"
        )
    for field in (
        "completed_group_ids",
        "pending_group_ids",
        "next_group_ids",
    ):
        if not _is_string_list(payload.get(field)):
            errors.append(
                f"completion audit recovery queue progress {field} must be a string list"
            )
    for field in (
        "execution_group_count",
        "ready_group_count",
        "blocked_group_count",
        "blocked_by_external_setup_count",
        "blocked_by_dependency_count",
        "complete_group_count",
        "ready_for_autonomous_dispatch_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(
                f"completion audit recovery queue progress {field} must be non-negative"
            )
    group_errors, group_statuses = _group_status_errors(payload.get("group_statuses"))
    errors.extend(group_errors)
    if not group_errors:
        errors.extend(_summary_errors(payload, group_statuses))
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    return errors


def _group_status_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    statuses: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return [
            "completion audit recovery queue progress group_statuses must be a list"
        ], []
    group_ids: list[str] = []
    for status in value:
        if not isinstance(status, dict):
            errors.append(
                "completion audit recovery queue progress group_status entries must be objects"
            )
            continue
        statuses.append(status)
        fields = set(status)
        missing = sorted(queue_runner.GROUP_STATUS_FIELDS - fields)
        extra = sorted(fields - queue_runner.GROUP_STATUS_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery queue progress group_status missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery queue progress group_status has unsupported field(s): "
                + ", ".join(extra)
            )
        group_id = status.get("group_id")
        if isinstance(group_id, str) and group_id:
            group_ids.append(group_id)
        else:
            errors.append(
                "completion audit recovery queue progress group_status group_id must be non-empty"
            )
        if status.get("status") not in {
            queue_runner.READY_STATUS,
            queue_runner.BLOCKED_BY_DEPENDENCY_STATUS,
            queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS,
            queue_runner.BLOCKED_STATUS,
            queue_runner.COMPLETE_STATUS,
        }:
            errors.append(
                "completion audit recovery queue progress group_status status is unsupported"
            )
        if not _is_non_negative_int(status.get("item_count")):
            errors.append(
                "completion audit recovery queue progress group_status item_count must be non-negative"
            )
        for field in ("depends_on_group_ids", "blocked_dependency_group_ids"):
            if not _is_string_list(status.get(field)):
                errors.append(
                    f"completion audit recovery queue progress group_status {field} must be a string list"
                )
        for field in ("blocked_by_external_setup", "ready_for_autonomous_dispatch"):
            if not isinstance(status.get(field), bool):
                errors.append(
                    f"completion audit recovery queue progress group_status {field} must be a boolean"
                )
        if not isinstance(status.get("next_action"), str) or not status.get(
            "next_action"
        ):
            errors.append(
                "completion audit recovery queue progress group_status next_action must be non-empty"
            )
    if len(group_ids) != len(set(group_ids)):
        errors.append(
            "completion audit recovery queue progress group_status group_id values must be unique"
        )
    return errors, statuses


def _summary_errors(
    payload: dict[str, Any],
    group_statuses: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    expected_counts = {
        "execution_group_count": len(group_statuses),
        "ready_group_count": sum(
            1
            for status in group_statuses
            if status.get("status") == queue_runner.READY_STATUS
        ),
        "blocked_group_count": sum(
            1
            for status in group_statuses
            if status.get("status") in queue_runner._blocked_statuses()
        ),
        "blocked_by_external_setup_count": sum(
            1
            for status in group_statuses
            if status.get("status") == queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
        ),
        "blocked_by_dependency_count": sum(
            1
            for status in group_statuses
            if status.get("status") == queue_runner.BLOCKED_BY_DEPENDENCY_STATUS
        ),
        "complete_group_count": sum(
            1
            for status in group_statuses
            if status.get("status") == queue_runner.COMPLETE_STATUS
        ),
        "ready_for_autonomous_dispatch_count": sum(
            1
            for status in group_statuses
            if status.get("ready_for_autonomous_dispatch") is True
        ),
    }
    for field, expected in expected_counts.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit recovery queue progress {field} must match group_statuses"
            )
    expected_next_group_ids = [
        status["group_id"]
        for status in group_statuses
        if not status.get("blocked_dependency_group_ids")
        and status.get("status")
        in {
            queue_runner.READY_STATUS,
            queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS,
        }
    ]
    if payload.get("next_group_ids") != expected_next_group_ids:
        errors.append(
            "completion audit recovery queue progress next_group_ids must match group_statuses"
        )
    if payload.get("queue_state") != _expected_queue_state(payload, group_statuses):
        errors.append(
            "completion audit recovery queue progress queue_state must match group_statuses"
        )
    if payload.get("advancement_applied") != bool(payload.get("completed_group_ids")):
        errors.append(
            "completion audit recovery queue progress advancement_applied must match completed_group_ids"
        )
    if payload.get("group_status_fingerprint_sha256") != (
        queue_runner._group_status_fingerprint(group_statuses)
    ):
        errors.append(
            "completion audit recovery queue progress group_status_fingerprint_sha256 "
            "must match group_statuses"
        )
    expected_progress = generator._queue_progress_fingerprint(
        completed_group_ids=_string_list(payload.get("completed_group_ids")),
        group_statuses=group_statuses,
        queue_state=str(payload.get("queue_state") or ""),
        next_group_ids=_string_list(payload.get("next_group_ids")),
    )
    if payload.get("queue_progress_fingerprint_sha256") != expected_progress:
        errors.append(
            "completion audit recovery queue progress queue_progress_fingerprint_sha256 "
            "must match progress state"
        )
    return errors


def _expected_queue_state(
    payload: dict[str, Any],
    group_statuses: list[dict[str, Any]],
) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "invalid"
    if not group_statuses:
        return "empty"
    status_values = [status.get("status") for status in group_statuses]
    if all(value == queue_runner.COMPLETE_STATUS for value in status_values):
        return "release_ready"
    if queue_runner.READY_STATUS in status_values:
        return "ready_for_autonomous_dispatch"
    if queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS in status_values:
        return "blocked_on_external_setup"
    if queue_runner.BLOCKED_BY_DEPENDENCY_STATUS in status_values:
        return "blocked_on_dependencies"
    return "blocked"


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["completion audit recovery queue progress privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(PRIVACY_FIELDS - fields)
    extra = sorted(fields - PRIVACY_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery queue progress privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery queue progress privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(
                f"completion audit recovery queue progress privacy {field} must be false"
            )
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    source_recovery_queue_path: Path | None,
    recovery_plan_path: Path | None,
    work_order_status_path: Path | None,
    recovery_work_order_path: Path | None,
    handoff_json_path: Path | None,
    setup_state_path: Path | None,
    launch_pack_path: Path | None,
) -> list[str]:
    if (
        source_recovery_queue_path is None
        or recovery_plan_path is None
        or work_order_status_path is None
    ):
        return [
            "completion audit recovery queue progress source mismatch: "
            "--source-recovery-queue, --recovery-plan, and "
            "--work-order-status are required together"
        ]
    expected = generator.generate_completion_audit_recovery_queue_progress(
        source_recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        work_order_status_path=work_order_status_path,
        recovery_work_order_path=recovery_work_order_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    if payload != expected:
        return ["completion audit recovery queue progress must match sources"]
    return []


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return ["completion audit recovery queue progress errors must be a string list"]
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes):
        if error_codes != expected_codes:
            result.append(
                "completion audit recovery queue progress error_codes must match errors"
            )
    else:
        result.append(
            "completion audit recovery queue progress error_codes must be a string list"
        )
    if error_code_counts != expected_counts:
        result.append(
            "completion audit recovery queue progress error_code_counts must match errors"
        )
    expected_ok = not errors
    if isinstance(payload.get("ok"), bool) and payload["ok"] != expected_ok:
        result.append("completion audit recovery queue progress ok must match errors")
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
    if error == "completion audit recovery queue progress path must be a regular file":
        return "completion_audit_recovery_queue_progress_path_invalid"
    if error.startswith("completion audit recovery queue progress JSON is invalid"):
        return "completion_audit_recovery_queue_progress_json_invalid"
    if error == "completion audit recovery queue progress root must be an object":
        return "completion_audit_recovery_queue_progress_root_invalid"
    if error == "completion audit recovery queue progress must match sources":
        return "completion_audit_recovery_queue_progress_source_mismatch"
    if "source mismatch" in error:
        return "completion_audit_recovery_queue_progress_source_mismatch"
    if error.startswith(
        "completion audit recovery queue progress missing required field"
    ):
        return "completion_audit_recovery_queue_progress_missing_required_fields"
    if error.startswith(
        "completion audit recovery queue progress has unsupported field"
    ):
        return "completion_audit_recovery_queue_progress_unsupported_fields"
    if error.startswith(
        "completion audit recovery queue progress schema_version must be"
    ):
        return "completion_audit_recovery_queue_progress_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_recovery_queue_progress_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_queue_progress_privacy_invalid"
    if "group_status" in error or "group_statuses" in error:
        return "completion_audit_recovery_queue_progress_group_status_invalid"
    if "queue_state" in error:
        return "completion_audit_recovery_queue_progress_state_invalid"
    if "count" in error or "non-negative" in error:
        return "completion_audit_recovery_queue_progress_count_invalid"
    if "mode" in error or "dry_run" in error:
        return "completion_audit_recovery_queue_progress_mode_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_recovery_queue_progress_error_summary_invalid"
    if "boolean" in error or error.endswith("must match errors"):
        return "completion_audit_recovery_queue_progress_boolean_invalid"
    if "string list" in error:
        return "completion_audit_recovery_queue_progress_string_list_invalid"
    return "completion_audit_recovery_queue_progress_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a progressed completion-audit recovery queue.",
    )
    parser.add_argument("recovery_queue_progress", type=Path)
    parser.add_argument("--source-recovery-queue", type=Path, default=None)
    parser.add_argument("--recovery-plan", type=Path, default=None)
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
    result = validate_recovery_queue_progress(
        args.recovery_queue_progress,
        source_recovery_queue_path=args.source_recovery_queue,
        recovery_plan_path=args.recovery_plan,
        work_order_status_path=args.work_order_status,
        recovery_work_order_path=args.recovery_work_order,
        handoff_json_path=args.handoff_json,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif result.ok:
        text = "Wiii Completion Audit Recovery Queue Progress Validation: PASS\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Queue Progress Validation: FAIL\n"
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
