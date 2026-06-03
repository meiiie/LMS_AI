#!/usr/bin/env python3
"""Validate completion-audit recovery dispatch-run reports."""

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
import run_completion_audit_recovery_dispatch_authorization as runner  # noqa: E402


RECOVERY_DISPATCH_RUN_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_dispatch_run_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "allow_live_dispatch",
    "recovery_dispatch_authorization_path",
    "recovery_dispatch_authorization_sha256",
    "recovery_dispatch_authorization_schema_version",
    "authorization_fingerprint_sha256",
    "authorization_state",
    "autonomous_dispatch_allowed",
    "dispatch_gate_enforced",
    "live_command_specs_included",
    "authorized_group_ids",
    "blocked_group_ids",
    "authorization_item_count",
    "ready_dispatch_item_count",
    "blocked_dispatch_item_count",
    "run_state",
    "command_count",
    "executed_command_count",
    "failed_command_count",
    "denied_item_count",
    "recovery_dispatch_run_fingerprint_sha256",
    "commands",
    "denied_items",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
COMMAND_FIELDS = {
    "item_id",
    "group_id",
    "requirement_id",
    "command_name",
    "working_directory",
    "argv",
    "uses_shell",
    "executed",
    "returncode",
    "stdout_included",
    "stderr_included",
}
DENIED_ITEM_FIELDS = {
    "item_id",
    "group_id",
    "requirement_id",
    "authorization_ready",
    "dispatch_gate_status",
    "blocked_reasons",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_output_included",
}


@dataclass(frozen=True)
class RecoveryDispatchRunValidationResult:
    validation_schema_version: str
    recovery_dispatch_run_path: str
    recovery_dispatch_authorization_path: str | None
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


def validate_recovery_dispatch_run(
    recovery_dispatch_run_path: Path,
    *,
    recovery_dispatch_authorization_path: Path | None = None,
    recovery_queue_progress_path: Path | None = None,
    recovery_plan_path: Path | None = None,
    dispatch_gate_path: Path | None = None,
    source_recovery_queue_path: Path | None = None,
    work_order_status_path: Path | None = None,
    recovery_work_order_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
    repo_root: Path = Path("."),
) -> RecoveryDispatchRunValidationResult:
    errors: list[str] = []
    payload = _load_payload(recovery_dispatch_run_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if recovery_dispatch_authorization_path is not None:
            errors.extend(
                _source_errors(
                    payload,
                    recovery_dispatch_authorization_path=(
                        recovery_dispatch_authorization_path
                    ),
                    recovery_queue_progress_path=recovery_queue_progress_path,
                    recovery_plan_path=recovery_plan_path,
                    dispatch_gate_path=dispatch_gate_path,
                    source_recovery_queue_path=source_recovery_queue_path,
                    work_order_status_path=work_order_status_path,
                    recovery_work_order_path=recovery_work_order_path,
                    handoff_json_path=handoff_json_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                    repo_root=repo_root,
                )
            )
    return RecoveryDispatchRunValidationResult(
        validation_schema_version=RECOVERY_DISPATCH_RUN_VALIDATION_SCHEMA_VERSION,
        recovery_dispatch_run_path=str(recovery_dispatch_run_path),
        recovery_dispatch_authorization_path=(
            str(recovery_dispatch_authorization_path)
            if recovery_dispatch_authorization_path
            else None
        ),
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
        errors.append("completion audit recovery dispatch run path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery dispatch run JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit recovery dispatch run root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "completion audit recovery dispatch run missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "completion audit recovery dispatch run has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != runner.RECOVERY_DISPATCH_RUN_SCHEMA_VERSION:
        errors.append(
            "completion audit recovery dispatch run schema_version must be "
            f"{runner.RECOVERY_DISPATCH_RUN_SCHEMA_VERSION}"
        )
    if payload.get("mode") not in {"dry_run", "execute"}:
        errors.append("completion audit recovery dispatch run mode must be dry_run or execute")
    for field in (
        "ok",
        "dry_run",
        "allow_live_dispatch",
        "autonomous_dispatch_allowed",
        "dispatch_gate_enforced",
        "live_command_specs_included",
    ):
        if not isinstance(payload.get(field), bool):
            errors.append(
                f"completion audit recovery dispatch run {field} must be a boolean"
            )
    if isinstance(payload.get("mode"), str) and isinstance(payload.get("dry_run"), bool):
        if payload["dry_run"] != (payload["mode"] == "dry_run"):
            errors.append("completion audit recovery dispatch run dry_run must match mode")
    if payload.get("allow_live_dispatch") is True and payload.get("mode") != "execute":
        errors.append(
            "completion audit recovery dispatch run allow_live_dispatch requires execute mode"
        )
    for field in (
        "recovery_dispatch_authorization_path",
        "recovery_dispatch_authorization_schema_version",
        "authorization_fingerprint_sha256",
        "authorization_state",
        "run_state",
        "recovery_dispatch_run_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str):
            errors.append(
                f"completion audit recovery dispatch run {field} must be a string"
            )
    if payload.get("run_state") not in runner.RUN_STATES:
        errors.append(
            "completion audit recovery dispatch run run_state is unsupported"
        )
    for field in (
        "recovery_dispatch_authorization_sha256",
        "authorization_fingerprint_sha256",
        "recovery_dispatch_run_fingerprint_sha256",
    ):
        value = payload.get(field)
        if value and not _is_fingerprint(value):
            errors.append(
                f"completion audit recovery dispatch run {field} must be SHA-256"
            )
    for field in ("authorized_group_ids", "blocked_group_ids"):
        if not _is_string_list(payload.get(field)):
            errors.append(
                f"completion audit recovery dispatch run {field} must be a string list"
            )
    for field in (
        "authorization_item_count",
        "ready_dispatch_item_count",
        "blocked_dispatch_item_count",
        "command_count",
        "executed_command_count",
        "failed_command_count",
        "denied_item_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(
                f"completion audit recovery dispatch run {field} must be non-negative"
            )
    command_errors, commands = _command_errors(payload.get("commands"), payload)
    errors.extend(command_errors)
    denied_errors, denied_items = _denied_item_errors(payload.get("denied_items"))
    errors.extend(denied_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not command_errors and not denied_errors:
        errors.extend(_summary_errors(payload, commands, denied_items))
    return errors


def _command_errors(
    value: Any,
    payload: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    commands: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["completion audit recovery dispatch run commands must be a list"], commands
    for command in value:
        if not isinstance(command, dict):
            errors.append(
                "completion audit recovery dispatch run command entries must be objects"
            )
            continue
        commands.append(command)
        if set(command) != COMMAND_FIELDS:
            errors.append(
                "completion audit recovery dispatch run command fields must match contract"
            )
        for field in (
            "item_id",
            "group_id",
            "requirement_id",
            "command_name",
            "working_directory",
        ):
            if not isinstance(command.get(field), str) or not command.get(field):
                errors.append(
                    f"completion audit recovery dispatch run command {field} must be non-empty"
                )
        if command.get("command_name") not in runner.UNLOCKED_LIVE_COMMAND_SPEC_FIELDS:
            errors.append(
                "completion audit recovery dispatch run command_name must be allowlisted"
            )
        argv = command.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append(
                "completion audit recovery dispatch run command argv must be a non-empty string list"
            )
        else:
            errors.extend(_argv_shell_control_errors(argv))
            if command.get("command_name") == "workflow_dispatch" and argv[:3] != [
                "gh",
                "workflow",
                "run",
            ]:
                errors.append(
                    "completion audit recovery dispatch run workflow_dispatch must use gh workflow run"
                )
            if (
                command.get("command_name") == "local_live_probe"
                and argv[0] not in {"python", "python3"}
            ):
                errors.append(
                    "completion audit recovery dispatch run local_live_probe must use python"
                )
        if command.get("uses_shell") is not False:
            errors.append(
                "completion audit recovery dispatch run command uses_shell must be false"
            )
        if not isinstance(command.get("executed"), bool):
            errors.append(
                "completion audit recovery dispatch run command executed must be a boolean"
            )
        if not _is_int(command.get("returncode")):
            errors.append(
                "completion audit recovery dispatch run command returncode must be an integer"
            )
        elif command.get("executed") is False and command.get("returncode") != -1:
            errors.append(
                "completion audit recovery dispatch run unexecuted command returncode must be -1"
            )
        if payload.get("mode") == "dry_run" and command.get("executed") is not False:
            errors.append(
                "completion audit recovery dispatch run dry-run commands must not execute"
            )
        for field in ("stdout_included", "stderr_included"):
            if command.get(field) is not False:
                errors.append(
                    f"completion audit recovery dispatch run command {field} must be false"
                )
    return errors, commands


def _denied_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return [
            "completion audit recovery dispatch run denied_items must be a list"
        ], items
    for item in value:
        if not isinstance(item, dict):
            errors.append(
                "completion audit recovery dispatch run denied_item entries must be objects"
            )
            continue
        items.append(item)
        if set(item) != DENIED_ITEM_FIELDS:
            errors.append(
                "completion audit recovery dispatch run denied_item fields must match contract"
            )
        for field in (
            "item_id",
            "group_id",
            "requirement_id",
            "dispatch_gate_status",
        ):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(
                    f"completion audit recovery dispatch run denied_item {field} must be non-empty"
                )
        if item.get("authorization_ready") is not False:
            errors.append(
                "completion audit recovery dispatch run denied_item authorization_ready must be false"
            )
        if not _is_string_list(item.get("blocked_reasons")):
            errors.append(
                "completion audit recovery dispatch run denied_item blocked_reasons must be a string list"
            )
    return errors, items


def _summary_errors(
    payload: dict[str, Any],
    commands: list[dict[str, Any]],
    denied_items: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    executed_count = sum(1 for command in commands if command.get("executed") is True)
    failed_count = sum(
        1
        for command in commands
        if isinstance(command.get("returncode"), int)
        and command.get("returncode") not in {-1, 0}
    )
    expected_counts = {
        "command_count": len(commands),
        "executed_command_count": executed_count,
        "failed_command_count": failed_count,
        "denied_item_count": len(denied_items),
    }
    for field, expected in expected_counts.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit recovery dispatch run {field} must match rows"
            )
    expected_state = _expected_run_state(payload, commands, failed_count)
    if payload.get("run_state") != expected_state:
        errors.append(
            "completion audit recovery dispatch run run_state must match authorization and commands"
        )
    if payload.get("ok") != (not payload.get("errors")):
        errors.append("completion audit recovery dispatch run ok must match errors")
    expected_fingerprint = runner._recovery_dispatch_run_fingerprint(
        mode=str(payload.get("mode") or ""),
        allow_live_dispatch=payload.get("allow_live_dispatch") is True,
        run_state=str(payload.get("run_state") or ""),
        commands=commands,
        denied_items=denied_items,
        errors=_string_list(payload.get("errors")),
    )
    if payload.get("recovery_dispatch_run_fingerprint_sha256") != expected_fingerprint:
        errors.append(
            "completion audit recovery dispatch run recovery_dispatch_run_fingerprint_sha256 must match rows"
        )
    if payload.get("autonomous_dispatch_allowed") is False and commands:
        errors.append(
            "completion audit recovery dispatch run blocked authorization must not materialize commands"
        )
    if payload.get("live_command_specs_included") is False and commands:
        errors.append(
            "completion audit recovery dispatch run missing live specs must not materialize commands"
        )
    return errors


def _expected_run_state(
    payload: dict[str, Any],
    commands: list[dict[str, Any]],
    failed_count: int,
) -> str:
    errors = _string_list(payload.get("errors"))
    if any(
        error.startswith(
            "completion audit recovery dispatch authorization failed validation"
        )
        or "root must be an object" in error
        for error in errors
    ):
        return "invalid"
    if payload.get("autonomous_dispatch_allowed") is not True:
        return "blocked_by_authorization"
    if payload.get("live_command_specs_included") is not True:
        return "blocked_by_missing_live_command_specs"
    if any("requires --allow-live-dispatch" in error for error in errors):
        return "live_dispatch_not_allowed"
    if failed_count:
        return "command_failed"
    if payload.get("mode") == "execute" and commands:
        return "executed"
    if commands:
        return "ready"
    return "no_commands"


def _source_errors(
    payload: dict[str, Any],
    *,
    recovery_dispatch_authorization_path: Path,
    recovery_queue_progress_path: Path | None,
    recovery_plan_path: Path | None,
    dispatch_gate_path: Path | None,
    source_recovery_queue_path: Path | None,
    work_order_status_path: Path | None,
    recovery_work_order_path: Path | None,
    handoff_json_path: Path | None,
    setup_state_path: Path | None,
    launch_pack_path: Path | None,
    repo_root: Path,
) -> list[str]:
    if payload.get("mode") != "dry_run":
        return [
            "completion audit recovery dispatch run source validation requires dry_run mode"
        ]
    expected = runner.run_completion_audit_recovery_dispatch_authorization(
        recovery_dispatch_authorization_path,
        recovery_queue_progress_path=recovery_queue_progress_path,
        recovery_plan_path=recovery_plan_path,
        dispatch_gate_path=dispatch_gate_path,
        source_recovery_queue_path=source_recovery_queue_path,
        work_order_status_path=work_order_status_path,
        recovery_work_order_path=recovery_work_order_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
        repo_root=repo_root,
    ).to_dict()
    if payload != expected:
        return ["completion audit recovery dispatch run must match sources"]
    return []


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["completion audit recovery dispatch run privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append(
            "completion audit recovery dispatch run privacy fields must match contract"
        )
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(
                f"completion audit recovery dispatch run privacy.{field} must be false"
            )
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return ["completion audit recovery dispatch run errors must be a string list"]
    expected_codes = runner._error_codes(errors)
    expected_counts = runner._error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes):
        if error_codes != expected_codes:
            result.append(
                "completion audit recovery dispatch run error_codes must match errors"
            )
    else:
        result.append(
            "completion audit recovery dispatch run error_codes must be a string list"
        )
    if error_code_counts != expected_counts:
        result.append(
            "completion audit recovery dispatch run error_code_counts must match errors"
        )
    return result


def _argv_shell_control_errors(argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    if any(any(token in arg for token in shell_control_tokens) for arg in argv):
        return [
            "completion audit recovery dispatch run argv must not contain shell control tokens"
        ]
    return []


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_negative_int(value: Any) -> bool:
    return _is_int(value) and value >= 0


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
    if error == "completion audit recovery dispatch run path must be a regular file":
        return "completion_audit_recovery_dispatch_run_path_invalid"
    if error.startswith("completion audit recovery dispatch run JSON is invalid"):
        return "completion_audit_recovery_dispatch_run_json_invalid"
    if error == "completion audit recovery dispatch run root must be an object":
        return "completion_audit_recovery_dispatch_run_root_invalid"
    if error == "completion audit recovery dispatch run must match sources":
        return "completion_audit_recovery_dispatch_run_source_mismatch"
    if "source validation requires dry_run" in error:
        return "completion_audit_recovery_dispatch_run_source_mode_invalid"
    if error.startswith(
        "completion audit recovery dispatch run missing required field"
    ):
        return "completion_audit_recovery_dispatch_run_missing_required_fields"
    if error.startswith(
        "completion audit recovery dispatch run has unsupported field"
    ):
        return "completion_audit_recovery_dispatch_run_unsupported_fields"
    if error.startswith(
        "completion audit recovery dispatch run schema_version must be"
    ):
        return "completion_audit_recovery_dispatch_run_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_recovery_dispatch_run_fingerprint_invalid"
    if "privacy" in error or "raw_output" in error:
        return "completion_audit_recovery_dispatch_run_privacy_invalid"
    if "command" in error or "argv" in error or "shell" in error:
        return "completion_audit_recovery_dispatch_run_command_invalid"
    if "denied_item" in error:
        return "completion_audit_recovery_dispatch_run_denied_item_invalid"
    if "run_state" in error or "mode" in error:
        return "completion_audit_recovery_dispatch_run_state_invalid"
    if "count" in error or "non-negative" in error:
        return "completion_audit_recovery_dispatch_run_count_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_recovery_dispatch_run_error_summary_invalid"
    if "boolean" in error or error.endswith("must match errors"):
        return "completion_audit_recovery_dispatch_run_boolean_invalid"
    if "string list" in error:
        return "completion_audit_recovery_dispatch_run_string_list_invalid"
    return "completion_audit_recovery_dispatch_run_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit recovery dispatch-run report.",
    )
    parser.add_argument("recovery_dispatch_run", type=Path)
    parser.add_argument("--recovery-dispatch-authorization", type=Path, default=None)
    parser.add_argument("--queue-progress", type=Path, default=None)
    parser.add_argument("--recovery-plan", type=Path, default=None)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--source-recovery-queue", type=Path, default=None)
    parser.add_argument("--work-order-status", type=Path, default=None)
    parser.add_argument("--recovery-work-order", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_recovery_dispatch_run(
        args.recovery_dispatch_run,
        recovery_dispatch_authorization_path=args.recovery_dispatch_authorization,
        recovery_queue_progress_path=args.queue_progress,
        recovery_plan_path=args.recovery_plan,
        dispatch_gate_path=args.dispatch_gate,
        source_recovery_queue_path=args.source_recovery_queue,
        work_order_status_path=args.work_order_status,
        recovery_work_order_path=args.recovery_work_order,
        handoff_json_path=args.handoff_json,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
        repo_root=args.repo_root,
    )
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif result.ok:
        text = "Wiii Completion Audit Recovery Dispatch Run Validation: PASS\n"
    else:
        text = (
            "Wiii Completion Audit Recovery Dispatch Run Validation: FAIL\n"
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
