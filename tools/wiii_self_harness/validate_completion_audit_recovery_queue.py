#!/usr/bin/env python3
"""Validate completion-audit recovery queue artifacts."""

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
from validate_completion_audit_recovery_plan import EXECUTION_MODES  # noqa: E402
import run_completion_audit_recovery_queue as queue_runner  # noqa: E402
import validate_completion_audit_recovery_plan as recovery_plan_validator  # noqa: E402


RECOVERY_QUEUE_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_queue_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "recovery_plan_path",
    "recovery_plan_sha256",
    "recovery_plan_schema_version",
    "recovery_plan_action_items_fingerprint_sha256",
    "recovery_plan_execution_groups_fingerprint_sha256",
    "handoff_json_path",
    "handoff_json_sha256",
    "queue_state",
    "execution_group_count",
    "ready_group_count",
    "blocked_group_count",
    "blocked_by_external_setup_count",
    "blocked_by_dependency_count",
    "complete_group_count",
    "ready_for_autonomous_dispatch_count",
    "next_group_ids",
    "group_status_fingerprint_sha256",
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
GROUP_STATUSES = {
    queue_runner.READY_STATUS,
    queue_runner.BLOCKED_BY_DEPENDENCY_STATUS,
    queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS,
    queue_runner.BLOCKED_STATUS,
    queue_runner.COMPLETE_STATUS,
}


@dataclass(frozen=True)
class RecoveryQueueValidationResult:
    validation_schema_version: str
    recovery_queue_path: str
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


def validate_recovery_queue(
    recovery_queue_path: Path,
    *,
    recovery_plan_path: Path | None = None,
    handoff_json_path: Path | None = None,
) -> RecoveryQueueValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_queue_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if handoff_json_path is not None and recovery_plan_path is None:
            errors.append(
                "completion audit recovery queue source validation requires --recovery-plan"
            )
        if recovery_plan_path is not None:
            errors.extend(
                _source_errors(
                    payload,
                    recovery_plan_path=recovery_plan_path,
                    handoff_json_path=handoff_json_path,
                )
            )
    return RecoveryQueueValidationResult(
        validation_schema_version=RECOVERY_QUEUE_VALIDATION_SCHEMA_VERSION,
        recovery_queue_path=str(recovery_queue_path),
        recovery_plan_path=str(recovery_plan_path) if recovery_plan_path else None,
        handoff_json_path=str(handoff_json_path) if handoff_json_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit recovery queue path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery queue JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit recovery queue root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery queue missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery queue has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != queue_runner.RECOVERY_QUEUE_SCHEMA_VERSION:
        errors.append(
            "completion audit recovery queue schema_version must be "
            f"{queue_runner.RECOVERY_QUEUE_SCHEMA_VERSION}"
        )
    if payload.get("mode") != "dry_run":
        errors.append("completion audit recovery queue mode must be dry_run")
    if payload.get("dry_run") is not True:
        errors.append("completion audit recovery queue dry_run must be true")
    for field in ("ok",):
        if not isinstance(payload.get(field), bool):
            errors.append(f"completion audit recovery queue {field} must be a boolean")
    for field in (
        "recovery_plan_path",
        "recovery_plan_schema_version",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"completion audit recovery queue {field} must be non-empty")
    for field in ("handoff_json_path",):
        if not isinstance(payload.get(field), str):
            errors.append(f"completion audit recovery queue {field} must be a string")
    for field in (
        "recovery_plan_sha256",
        "recovery_plan_action_items_fingerprint_sha256",
        "recovery_plan_execution_groups_fingerprint_sha256",
        "group_status_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"completion audit recovery queue {field} must be SHA-256")
    handoff_sha = payload.get("handoff_json_sha256")
    if handoff_sha != "" and not _is_fingerprint(handoff_sha):
        errors.append("completion audit recovery queue handoff_json_sha256 must be SHA-256")
    if payload.get("queue_state") not in queue_runner.QUEUE_STATES:
        errors.append("completion audit recovery queue queue_state is unsupported")
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
                f"completion audit recovery queue {field} must be non-negative"
            )
    group_status_errors, group_statuses = _group_status_errors(
        payload.get("group_statuses")
    )
    errors.extend(group_status_errors)
    if not group_status_errors:
        errors.extend(_summary_errors(payload, group_statuses))
    if not _is_string_list(payload.get("next_group_ids")):
        errors.append(
            "completion audit recovery queue next_group_ids must be a string list"
        )
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    return errors


def _group_status_errors(
    value: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    statuses: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["completion audit recovery queue group_statuses must be a list"], []
    group_ids: list[str] = []
    for status in value:
        if not isinstance(status, dict):
            errors.append(
                "completion audit recovery queue group_status entries must be objects"
            )
            continue
        statuses.append(status)
        fields = set(status)
        missing = sorted(queue_runner.GROUP_STATUS_FIELDS - fields)
        extra = sorted(fields - queue_runner.GROUP_STATUS_FIELDS)
        if missing:
            errors.append(
                "completion audit recovery queue group_status missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "completion audit recovery queue group_status has unsupported field(s): "
                + ", ".join(extra)
            )
        group_id = status.get("group_id")
        if isinstance(group_id, str) and group_id:
            group_ids.append(group_id)
        else:
            errors.append(
                "completion audit recovery queue group_status group_id must be non-empty"
            )
        if status.get("execution_mode") not in EXECUTION_MODES:
            errors.append(
                "completion audit recovery queue group_status execution_mode is unsupported"
            )
        if status.get("status") not in GROUP_STATUSES:
            errors.append(
                "completion audit recovery queue group_status status is unsupported"
            )
        if not _is_non_negative_int(status.get("item_count")):
            errors.append(
                "completion audit recovery queue group_status item_count must be non-negative"
            )
        for field in ("depends_on_group_ids", "blocked_dependency_group_ids"):
            if not _is_string_list(status.get(field)):
                errors.append(
                    f"completion audit recovery queue group_status {field} must be a string list"
                )
        for field in ("blocked_by_external_setup", "ready_for_autonomous_dispatch"):
            if not isinstance(status.get(field), bool):
                errors.append(
                    f"completion audit recovery queue group_status {field} must be a boolean"
                )
        if not isinstance(status.get("next_action"), str) or not status.get(
            "next_action"
        ):
            errors.append(
                "completion audit recovery queue group_status next_action must be non-empty"
            )
    if len(group_ids) != len(set(group_ids)):
        errors.append(
            "completion audit recovery queue group_status group_id values must be unique"
        )
    known_group_ids = set(group_ids)
    for status in statuses:
        errors.extend(_group_status_consistency_errors(status, known_group_ids))
    return errors, statuses


def _group_status_consistency_errors(
    status: dict[str, Any],
    known_group_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    group_id = status.get("group_id")
    depends = status.get("depends_on_group_ids")
    blocked = status.get("blocked_dependency_group_ids")
    if isinstance(depends, list):
        if group_id in depends:
            errors.append(
                "completion audit recovery queue group_status must not depend on itself"
            )
        unknown = sorted(
            dependency
            for dependency in depends
            if isinstance(dependency, str) and dependency not in known_group_ids
        )
        if unknown:
            errors.append(
                "completion audit recovery queue group_status dependencies "
                "must reference group_statuses"
            )
    if isinstance(blocked, list):
        unknown_blocked = sorted(
            dependency
            for dependency in blocked
            if isinstance(dependency, str) and dependency not in known_group_ids
        )
        if unknown_blocked:
            errors.append(
                "completion audit recovery queue group_status blocked dependencies "
                "must reference group_statuses"
            )
        if isinstance(depends, list):
            outside_depends = sorted(
                dependency
                for dependency in blocked
                if isinstance(dependency, str) and dependency not in depends
            )
            if outside_depends:
                errors.append(
                    "completion audit recovery queue group_status blocked dependencies "
                    "must also be dependencies"
                )
    group_status = status.get("status")
    blocked_list = blocked if isinstance(blocked, list) else []
    if group_status == queue_runner.BLOCKED_BY_DEPENDENCY_STATUS and not blocked_list:
        errors.append(
            "completion audit recovery queue dependency-blocked groups must name blocked dependencies"
        )
    if group_status != queue_runner.BLOCKED_BY_DEPENDENCY_STATUS and blocked_list:
        errors.append(
            "completion audit recovery queue non-dependency-blocked groups must not name blocked dependencies"
        )
    if (
        group_status == queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
        and status.get("blocked_by_external_setup") is not True
    ):
        errors.append(
            "completion audit recovery queue external-setup-blocked groups must carry external setup flag"
        )
    if (
        group_status == queue_runner.READY_STATUS
        and status.get("ready_for_autonomous_dispatch") is not True
    ):
        errors.append(
            "completion audit recovery queue ready groups must carry autonomous dispatch flag"
        )
    return errors


def _summary_errors(
    payload: dict[str, Any],
    group_statuses: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if payload.get("execution_group_count") != len(group_statuses):
        errors.append(
            "completion audit recovery queue execution_group_count must match group_statuses"
        )
    expected_counts = {
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
                f"completion audit recovery queue {field} must match group_statuses"
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
            "completion audit recovery queue next_group_ids must match group_statuses"
        )
    if payload.get("queue_state") != _expected_queue_state(payload, group_statuses):
        errors.append(
            "completion audit recovery queue queue_state must match group_statuses"
        )
    if payload.get("group_status_fingerprint_sha256") != (
        queue_runner._group_status_fingerprint(group_statuses)
    ):
        errors.append(
            "completion audit recovery queue group_status_fingerprint_sha256 "
            "must match group_statuses"
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
        return ["completion audit recovery queue privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(PRIVACY_FIELDS - fields)
    extra = sorted(fields - PRIVACY_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery queue privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery queue privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"completion audit recovery queue privacy {field} must be false")
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    recovery_plan_path: Path,
    handoff_json_path: Path | None,
) -> list[str]:
    plan_validation = recovery_plan_validator.validate_recovery_plan(
        recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not plan_validation.ok:
        return [
            "completion audit recovery queue source mismatch: recovery plan "
            "failed validation: "
            + "; ".join(plan_validation.errors)
        ]
    expected = queue_runner.run_completion_audit_recovery_queue(
        recovery_plan_path,
        handoff_json_path=handoff_json_path,
    ).to_dict()
    if payload != expected:
        return ["completion audit recovery queue must match recovery plan source"]
    return []


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return ["completion audit recovery queue errors must be a string list"]
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes):
        if error_codes != expected_codes:
            result.append("completion audit recovery queue error_codes must match errors")
    else:
        result.append("completion audit recovery queue error_codes must be a string list")
    if error_code_counts != expected_counts:
        result.append(
            "completion audit recovery queue error_code_counts must match errors"
        )
    expected_ok = not errors
    if isinstance(payload.get("ok"), bool) and payload["ok"] != expected_ok:
        result.append("completion audit recovery queue ok must match errors")
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


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit recovery queue path must be a regular file":
        return "completion_audit_recovery_queue_path_invalid"
    if error.startswith("completion audit recovery queue JSON is invalid"):
        return "completion_audit_recovery_queue_json_invalid"
    if error == "completion audit recovery queue root must be an object":
        return "completion_audit_recovery_queue_root_invalid"
    if error.startswith("completion audit recovery queue missing required field"):
        return "completion_audit_recovery_queue_missing_required_fields"
    if error.startswith("completion audit recovery queue has unsupported field"):
        return "completion_audit_recovery_queue_unsupported_fields"
    if error.startswith("completion audit recovery queue schema_version must be"):
        return "completion_audit_recovery_queue_schema_mismatch"
    if error == "completion audit recovery queue must match recovery plan source":
        return "completion_audit_recovery_queue_source_mismatch"
    if "source mismatch" in error or "source validation requires" in error:
        return "completion_audit_recovery_queue_source_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_recovery_queue_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_queue_privacy_invalid"
    if "group_status" in error or "group_statuses" in error:
        return "completion_audit_recovery_queue_group_status_invalid"
    if "queue_state" in error:
        return "completion_audit_recovery_queue_state_invalid"
    if "count" in error or "non-negative" in error:
        return "completion_audit_recovery_queue_count_invalid"
    if "mode" in error or "dry_run" in error:
        return "completion_audit_recovery_queue_mode_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_recovery_queue_error_summary_invalid"
    if "boolean" in error or error.endswith("must match errors"):
        return "completion_audit_recovery_queue_boolean_invalid"
    if "string list" in error:
        return "completion_audit_recovery_queue_string_list_invalid"
    return "completion_audit_recovery_queue_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit recovery queue artifact.",
    )
    parser.add_argument("recovery_queue", type=Path)
    parser.add_argument("--recovery-plan", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_recovery_queue(
        args.recovery_queue,
        recovery_plan_path=args.recovery_plan,
        handoff_json_path=args.handoff_json,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif result.ok:
        text = "Wiii Completion Audit Recovery Queue Validation: PASS\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Queue Validation: FAIL\n"
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
