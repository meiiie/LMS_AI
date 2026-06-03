#!/usr/bin/env python3
"""Materialize a dry-run queue status from a completion-audit recovery plan."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from generate_completion_audit_recovery_plan import (  # noqa: E402
    RECOVERY_PLAN_SCHEMA_VERSION,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_recovery_plan as recovery_plan_validator  # noqa: E402


RECOVERY_QUEUE_SCHEMA_VERSION = "wiii.completion_audit_recovery_queue.v1"
RECOVERY_QUEUE_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery queue output path must not be a directory"
)
RECOVERY_QUEUE_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery queue output path must not be a symlink"
)
RECOVERY_QUEUE_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery queue output path parent must not be a symlink"
)

GROUP_STATUS_FIELDS = {
    "group_id",
    "execution_mode",
    "status",
    "item_count",
    "depends_on_group_ids",
    "blocked_dependency_group_ids",
    "blocked_by_external_setup",
    "ready_for_autonomous_dispatch",
    "next_action",
}
READY_STATUS = "ready"
BLOCKED_BY_DEPENDENCY_STATUS = "blocked_by_dependency"
BLOCKED_BY_EXTERNAL_SETUP_STATUS = "blocked_by_external_setup"
BLOCKED_STATUS = "blocked"
COMPLETE_STATUS = "complete"
QUEUE_STATES = {
    "invalid",
    "empty",
    "release_ready",
    "ready_for_autonomous_dispatch",
    "blocked_on_external_setup",
    "blocked_on_dependencies",
    "blocked",
}


@dataclass(frozen=True)
class RecoveryQueueGroupStatus:
    group_id: str
    execution_mode: str
    status: str
    item_count: int
    depends_on_group_ids: list[str]
    blocked_dependency_group_ids: list[str]
    blocked_by_external_setup: bool
    ready_for_autonomous_dispatch: bool
    next_action: str


@dataclass(frozen=True)
class RecoveryQueueReport:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    recovery_plan_path: str
    recovery_plan_sha256: str
    recovery_plan_schema_version: str
    recovery_plan_action_items_fingerprint_sha256: str
    recovery_plan_execution_groups_fingerprint_sha256: str
    handoff_json_path: str
    handoff_json_sha256: str
    queue_state: str
    execution_group_count: int
    ready_group_count: int
    blocked_group_count: int
    blocked_by_external_setup_count: int
    blocked_by_dependency_count: int
    complete_group_count: int
    ready_for_autonomous_dispatch_count: int
    next_group_ids: list[str]
    group_status_fingerprint_sha256: str
    group_statuses: list[RecoveryQueueGroupStatus]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def run_completion_audit_recovery_queue(
    recovery_plan_path: Path,
    *,
    handoff_json_path: Path | None = None,
) -> RecoveryQueueReport:
    errors: list[str] = []
    validation = recovery_plan_validator.validate_recovery_plan(
        recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    payload: dict[str, Any] = {}
    if not validation.ok:
        errors.append(
            "completion audit recovery queue recovery plan failed validation: "
            + "; ".join(validation.errors)
        )
    else:
        loaded = load_strict_json_file(recovery_plan_path)
        if isinstance(loaded, dict):
            payload = loaded
        else:
            errors.append("completion audit recovery queue recovery plan root invalid")
    group_statuses = _group_statuses(payload.get("execution_groups"), errors)
    return _report(
        recovery_plan_path,
        payload=payload,
        handoff_json_path=handoff_json_path,
        group_statuses=group_statuses,
        errors=errors,
    )


def _group_statuses(
    execution_groups: Any,
    errors: list[str],
) -> list[RecoveryQueueGroupStatus]:
    if not isinstance(execution_groups, list):
        if execution_groups is not None:
            errors.append(
                "completion audit recovery queue execution_groups must be a list"
            )
        return []
    known_group_ids = {
        group.get("group_id")
        for group in execution_groups
        if isinstance(group, dict) and isinstance(group.get("group_id"), str)
    }
    complete_group_ids: set[str] = set()
    statuses: list[RecoveryQueueGroupStatus] = []
    for group in execution_groups:
        if not isinstance(group, dict):
            errors.append(
                "completion audit recovery queue execution_group entries must be objects"
            )
            continue
        item_ids = _string_list(group.get("item_ids"))
        depends_on_group_ids = _string_list(group.get("depends_on_group_ids"))
        blocked_dependency_group_ids = [
            group_id
            for group_id in depends_on_group_ids
            if group_id in known_group_ids and group_id not in complete_group_ids
        ]
        status = _status_for_group(
            group,
            item_ids=item_ids,
            blocked_dependency_group_ids=blocked_dependency_group_ids,
        )
        next_action = _next_action_for_group(
            group,
            status=status,
            blocked_dependency_group_ids=blocked_dependency_group_ids,
        )
        group_status = RecoveryQueueGroupStatus(
            group_id=_string(group.get("group_id")),
            execution_mode=_string(group.get("execution_mode")),
            status=status,
            item_count=len(item_ids),
            depends_on_group_ids=depends_on_group_ids,
            blocked_dependency_group_ids=blocked_dependency_group_ids,
            blocked_by_external_setup=group.get("blocked_by_external_setup") is True,
            ready_for_autonomous_dispatch=(
                group.get("ready_for_autonomous_dispatch") is True
            ),
            next_action=next_action,
        )
        _assert_group_status_schema(group_status)
        if status == COMPLETE_STATUS:
            complete_group_ids.add(group_status.group_id)
        statuses.append(group_status)
    return statuses


def _status_for_group(
    group: dict[str, Any],
    *,
    item_ids: list[str],
    blocked_dependency_group_ids: list[str],
) -> str:
    if blocked_dependency_group_ids:
        return BLOCKED_BY_DEPENDENCY_STATUS
    if not item_ids:
        return COMPLETE_STATUS
    if group.get("blocked_by_external_setup") is True:
        return BLOCKED_BY_EXTERNAL_SETUP_STATUS
    if group.get("ready_for_autonomous_dispatch") is True:
        return READY_STATUS
    return BLOCKED_STATUS


def _next_action_for_group(
    group: dict[str, Any],
    *,
    status: str,
    blocked_dependency_group_ids: list[str],
) -> str:
    title = _string(group.get("title"))
    if status in {READY_STATUS, BLOCKED_BY_EXTERNAL_SETUP_STATUS}:
        return title
    if status == BLOCKED_BY_DEPENDENCY_STATUS:
        return (
            "wait for dependency groups to complete: "
            + ", ".join(blocked_dependency_group_ids)
        )
    if status == COMPLETE_STATUS:
        return "no action required"
    return title or "manual review required"


def _report(
    recovery_plan_path: Path,
    *,
    payload: dict[str, Any],
    handoff_json_path: Path | None,
    group_statuses: list[RecoveryQueueGroupStatus],
    errors: list[str],
) -> RecoveryQueueReport:
    group_status_dicts = [asdict(status) for status in group_statuses]
    next_group_ids = _next_group_ids(group_statuses)
    return RecoveryQueueReport(
        schema_version=RECOVERY_QUEUE_SCHEMA_VERSION,
        ok=not errors,
        mode="dry_run",
        dry_run=True,
        recovery_plan_path=str(recovery_plan_path),
        recovery_plan_sha256=(
            _sha256_file(recovery_plan_path)
            if recovery_plan_path.is_file() and not recovery_plan_path.is_symlink()
            else ""
        ),
        recovery_plan_schema_version=_string(payload.get("schema_version")),
        recovery_plan_action_items_fingerprint_sha256=_string(
            payload.get("action_items_fingerprint_sha256")
        ),
        recovery_plan_execution_groups_fingerprint_sha256=_string(
            payload.get("execution_groups_fingerprint_sha256")
        ),
        handoff_json_path=str(handoff_json_path) if handoff_json_path else "",
        handoff_json_sha256=(
            _sha256_file(handoff_json_path)
            if handoff_json_path is not None
            and handoff_json_path.is_file()
            and not handoff_json_path.is_symlink()
            else ""
        ),
        queue_state=_queue_state(group_statuses, errors),
        execution_group_count=len(group_statuses),
        ready_group_count=sum(
            1 for status in group_statuses if status.status == READY_STATUS
        ),
        blocked_group_count=sum(
            1 for status in group_statuses if status.status in _blocked_statuses()
        ),
        blocked_by_external_setup_count=sum(
            1
            for status in group_statuses
            if status.status == BLOCKED_BY_EXTERNAL_SETUP_STATUS
        ),
        blocked_by_dependency_count=sum(
            1
            for status in group_statuses
            if status.status == BLOCKED_BY_DEPENDENCY_STATUS
        ),
        complete_group_count=sum(
            1 for status in group_statuses if status.status == COMPLETE_STATUS
        ),
        ready_for_autonomous_dispatch_count=sum(
            1
            for status in group_statuses
            if status.ready_for_autonomous_dispatch is True
        ),
        next_group_ids=next_group_ids,
        group_status_fingerprint_sha256=_group_status_fingerprint(
            group_status_dicts
        ),
        group_statuses=group_statuses,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def _next_group_ids(
    group_statuses: list[RecoveryQueueGroupStatus],
) -> list[str]:
    return [
        status.group_id
        for status in group_statuses
        if not status.blocked_dependency_group_ids
        and status.status in {READY_STATUS, BLOCKED_BY_EXTERNAL_SETUP_STATUS}
    ]


def _queue_state(
    group_statuses: list[RecoveryQueueGroupStatus],
    errors: list[str],
) -> str:
    if errors:
        return "invalid"
    if not group_statuses:
        return "empty"
    if all(status.status == COMPLETE_STATUS for status in group_statuses):
        return "release_ready"
    if any(status.status == READY_STATUS for status in group_statuses):
        return "ready_for_autonomous_dispatch"
    if any(status.status == BLOCKED_BY_EXTERNAL_SETUP_STATUS for status in group_statuses):
        return "blocked_on_external_setup"
    if any(status.status == BLOCKED_BY_DEPENDENCY_STATUS for status in group_statuses):
        return "blocked_on_dependencies"
    return "blocked"


def _blocked_statuses() -> set[str]:
    return {
        BLOCKED_BY_DEPENDENCY_STATUS,
        BLOCKED_BY_EXTERNAL_SETUP_STATUS,
        BLOCKED_STATUS,
    }


def _assert_group_status_schema(status: RecoveryQueueGroupStatus) -> None:
    fields = set(asdict(status))
    missing = GROUP_STATUS_FIELDS - fields
    extra = fields - GROUP_STATUS_FIELDS
    if missing or extra:
        raise AssertionError("recovery queue group status schema drift")


def _group_status_fingerprint(group_statuses: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        group_statuses,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(RECOVERY_QUEUE_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(RECOVERY_QUEUE_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(RECOVERY_QUEUE_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


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
    if error.startswith("completion audit recovery queue recovery plan failed validation"):
        return "completion_audit_recovery_queue_plan_invalid"
    if error == "completion audit recovery queue recovery plan root invalid":
        return "completion_audit_recovery_queue_plan_root_invalid"
    if "execution_group" in error:
        return "completion_audit_recovery_queue_execution_group_invalid"
    if error == RECOVERY_QUEUE_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_queue_output_path_directory"
    if error == RECOVERY_QUEUE_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_queue_output_path_symlink"
    if error == RECOVERY_QUEUE_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_recovery_queue_output_path_parent_symlink"
    return "completion_audit_recovery_queue_failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a dry-run completion-audit recovery queue from a "
            "validated recovery plan."
        ),
    )
    parser.add_argument("recovery_plan", type=Path)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = run_completion_audit_recovery_queue(
            args.recovery_plan,
            handoff_json_path=args.handoff_json,
        )
    except Exception as exc:  # noqa: BLE001
        report = _error_report(args.recovery_plan, str(exc))
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0 if report.ok else 1


def _error_report(recovery_plan_path: Path, error: str) -> RecoveryQueueReport:
    return _report(
        recovery_plan_path,
        payload={
            "schema_version": RECOVERY_PLAN_SCHEMA_VERSION,
        },
        handoff_json_path=None,
        group_statuses=[],
        errors=[error],
    )


if __name__ == "__main__":
    raise SystemExit(main())
