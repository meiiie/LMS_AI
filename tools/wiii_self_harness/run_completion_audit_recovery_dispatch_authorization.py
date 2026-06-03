#!/usr/bin/env python3
"""Materialize or execute an authorized recovery dispatch decision."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_recovery_dispatch_authorization as authorization_validator  # noqa: E402


RECOVERY_DISPATCH_RUN_SCHEMA_VERSION = "wiii.completion_audit_recovery_dispatch_run.v1"
RECOVERY_DISPATCH_RUN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery dispatch run output path must not be a directory"
)
RECOVERY_DISPATCH_RUN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery dispatch run output path must not be a symlink"
)
RECOVERY_DISPATCH_RUN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery dispatch run output path parent must not be a symlink"
)
UNLOCKED_LIVE_COMMAND_SPEC_FIELDS = ("workflow_dispatch", "local_live_probe")
RUN_STATES = {
    "invalid",
    "blocked_by_authorization",
    "blocked_by_missing_live_command_specs",
    "live_dispatch_not_allowed",
    "ready",
    "executed",
    "command_failed",
    "no_commands",
}

CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class RecoveryDispatchRunCommand:
    item_id: str
    group_id: str
    requirement_id: str
    command_name: str
    working_directory: str
    argv: list[str]
    uses_shell: bool
    executed: bool
    returncode: int
    stdout_included: bool
    stderr_included: bool


@dataclass(frozen=True)
class RecoveryDispatchRunDeniedItem:
    item_id: str
    group_id: str
    requirement_id: str
    authorization_ready: bool
    dispatch_gate_status: str
    blocked_reasons: list[str]


@dataclass(frozen=True)
class RecoveryDispatchRunReport:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    allow_live_dispatch: bool
    recovery_dispatch_authorization_path: str
    recovery_dispatch_authorization_sha256: str
    recovery_dispatch_authorization_schema_version: str
    authorization_fingerprint_sha256: str
    authorization_state: str
    autonomous_dispatch_allowed: bool
    dispatch_gate_enforced: bool
    live_command_specs_included: bool
    authorized_group_ids: list[str]
    blocked_group_ids: list[str]
    authorization_item_count: int
    ready_dispatch_item_count: int
    blocked_dispatch_item_count: int
    run_state: str
    command_count: int
    executed_command_count: int
    failed_command_count: int
    denied_item_count: int
    recovery_dispatch_run_fingerprint_sha256: str
    commands: list[RecoveryDispatchRunCommand]
    denied_items: list[RecoveryDispatchRunDeniedItem]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def run_completion_audit_recovery_dispatch_authorization(
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
    repo_root: Path = Path("."),
    execute: bool = False,
    allow_live_dispatch: bool = False,
    command_runner: CommandRunner | None = None,
) -> RecoveryDispatchRunReport:
    errors: list[str] = []
    mode = "execute" if execute else "dry_run"
    validation = authorization_validator.validate_recovery_dispatch_authorization(
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
    )
    if not validation.ok:
        errors.append(
            "completion audit recovery dispatch authorization failed validation: "
            + "; ".join(validation.errors)
        )
        return _report(
            recovery_dispatch_authorization_path,
            payload={},
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            denied_items=[],
            errors=errors,
        )
    payload = load_strict_json_file(recovery_dispatch_authorization_path)
    if not isinstance(payload, dict):
        errors.append("completion audit recovery dispatch authorization root must be an object")
        return _report(
            recovery_dispatch_authorization_path,
            payload={},
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            denied_items=[],
            errors=errors,
        )
    denied_items = _denied_items(payload)
    if payload.get("autonomous_dispatch_allowed") is not True:
        errors.append("completion audit recovery dispatch authorization is not ready")
        return _report(
            recovery_dispatch_authorization_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            denied_items=denied_items,
            errors=errors,
        )
    if payload.get("live_command_specs_included") is not True:
        errors.append(
            "completion audit recovery dispatch authorization has no live command specs"
        )
        return _report(
            recovery_dispatch_authorization_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            denied_items=denied_items,
            errors=errors,
        )
    if execute and not allow_live_dispatch:
        errors.append(
            "completion audit recovery dispatch execution requires --allow-live-dispatch"
        )
        return _report(
            recovery_dispatch_authorization_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            denied_items=denied_items,
            errors=errors,
        )

    commands = _materialize_commands(payload, repo_root=repo_root, errors=errors)
    if execute and not errors:
        commands = _execute_commands(
            commands,
            repo_root=repo_root,
            command_runner=command_runner or _subprocess_runner,
            errors=errors,
        )
    return _report(
        recovery_dispatch_authorization_path,
        payload=payload,
        mode=mode,
        execute=execute,
        allow_live_dispatch=allow_live_dispatch,
        commands=commands,
        denied_items=denied_items,
        errors=errors,
    )


def _materialize_commands(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    errors: list[str],
) -> list[RecoveryDispatchRunCommand]:
    commands: list[RecoveryDispatchRunCommand] = []
    for item in payload.get("dispatch_items", []):
        if not isinstance(item, dict) or item.get("authorization_ready") is not True:
            continue
        specs = item.get("unlocked_live_command_specs")
        if not isinstance(specs, dict) or not specs:
            errors.append(
                "completion audit recovery dispatch run unlocked_live_command_specs must be present"
            )
            continue
        for command_name in UNLOCKED_LIVE_COMMAND_SPEC_FIELDS:
            spec = specs.get(command_name)
            if not isinstance(spec, dict):
                errors.append(
                    "completion audit recovery dispatch run unlocked command spec must be an object"
                )
                continue
            argv = _string_list(spec.get("argv"))
            working_directory = _string(spec.get("working_directory"))
            uses_shell = spec.get("uses_shell")
            _command_safety_errors(
                command_name,
                argv,
                working_directory,
                uses_shell,
                repo_root=repo_root,
                errors=errors,
            )
            commands.append(
                RecoveryDispatchRunCommand(
                    item_id=_string(item.get("item_id")),
                    group_id=_string(item.get("group_id")),
                    requirement_id=_string(item.get("requirement_id")),
                    command_name=command_name,
                    working_directory=working_directory,
                    argv=argv,
                    uses_shell=uses_shell is True,
                    executed=False,
                    returncode=-1,
                    stdout_included=False,
                    stderr_included=False,
                )
            )
    if not commands:
        errors.append("completion audit recovery dispatch run has no commands")
    return commands


def _denied_items(payload: dict[str, Any]) -> list[RecoveryDispatchRunDeniedItem]:
    items: list[RecoveryDispatchRunDeniedItem] = []
    for item in payload.get("dispatch_items", []):
        if not isinstance(item, dict) or item.get("authorization_ready") is True:
            continue
        items.append(
            RecoveryDispatchRunDeniedItem(
                item_id=_string(item.get("item_id")),
                group_id=_string(item.get("group_id")),
                requirement_id=_string(item.get("requirement_id")),
                authorization_ready=item.get("authorization_ready") is True,
                dispatch_gate_status=_string(item.get("dispatch_gate_status")),
                blocked_reasons=_string_list(item.get("blocked_reasons")),
            )
        )
    return items


def _execute_commands(
    commands: list[RecoveryDispatchRunCommand],
    *,
    repo_root: Path,
    command_runner: CommandRunner,
    errors: list[str],
) -> list[RecoveryDispatchRunCommand]:
    executed: list[RecoveryDispatchRunCommand] = []
    for command in commands:
        cwd = _resolve_working_directory(repo_root, command.working_directory)
        result = command_runner(command.argv, cwd)
        if result.returncode != 0:
            errors.append(
                "completion audit recovery dispatch command failed: "
                f"{command.requirement_id}:{command.command_name}"
            )
        executed.append(
            RecoveryDispatchRunCommand(
                item_id=command.item_id,
                group_id=command.group_id,
                requirement_id=command.requirement_id,
                command_name=command.command_name,
                working_directory=command.working_directory,
                argv=command.argv,
                uses_shell=command.uses_shell,
                executed=True,
                returncode=int(result.returncode),
                stdout_included=False,
                stderr_included=False,
            )
        )
    return executed


def _report(
    recovery_dispatch_authorization_path: Path,
    *,
    payload: dict[str, Any],
    mode: str,
    execute: bool,
    allow_live_dispatch: bool,
    commands: list[RecoveryDispatchRunCommand],
    denied_items: list[RecoveryDispatchRunDeniedItem],
    errors: list[str],
) -> RecoveryDispatchRunReport:
    executed_count = sum(1 for command in commands if command.executed)
    failed_count = sum(1 for command in commands if command.returncode not in {-1, 0})
    command_dicts = [asdict(command) for command in commands]
    denied_item_dicts = [asdict(item) for item in denied_items]
    run_state = _run_state(
        payload,
        mode=mode,
        commands=commands,
        errors=errors,
        failed_count=failed_count,
    )
    return RecoveryDispatchRunReport(
        schema_version=RECOVERY_DISPATCH_RUN_SCHEMA_VERSION,
        ok=not errors,
        mode=mode,
        dry_run=not execute,
        allow_live_dispatch=allow_live_dispatch,
        recovery_dispatch_authorization_path=str(recovery_dispatch_authorization_path),
        recovery_dispatch_authorization_sha256=_regular_file_sha(
            recovery_dispatch_authorization_path
        ),
        recovery_dispatch_authorization_schema_version=_string(
            payload.get("schema_version")
        ),
        authorization_fingerprint_sha256=_string(
            payload.get("authorization_fingerprint_sha256")
        ),
        authorization_state=_string(payload.get("authorization_state")),
        autonomous_dispatch_allowed=payload.get("autonomous_dispatch_allowed") is True,
        dispatch_gate_enforced=payload.get("dispatch_gate_enforced") is True,
        live_command_specs_included=payload.get("live_command_specs_included") is True,
        authorized_group_ids=_string_list(payload.get("authorized_group_ids")),
        blocked_group_ids=_string_list(payload.get("blocked_group_ids")),
        authorization_item_count=_int(payload.get("authorization_item_count")),
        ready_dispatch_item_count=_int(payload.get("ready_dispatch_item_count")),
        blocked_dispatch_item_count=_int(payload.get("blocked_dispatch_item_count")),
        run_state=run_state,
        command_count=len(commands),
        executed_command_count=executed_count,
        failed_command_count=failed_count,
        denied_item_count=len(denied_items),
        recovery_dispatch_run_fingerprint_sha256=_recovery_dispatch_run_fingerprint(
            mode=mode,
            allow_live_dispatch=allow_live_dispatch,
            run_state=run_state,
            commands=command_dicts,
            denied_items=denied_item_dicts,
            errors=errors,
        ),
        commands=commands,
        denied_items=denied_items,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_output_included": False,
        },
        errors=errors,
    )


def _run_state(
    payload: dict[str, Any],
    *,
    mode: str,
    commands: list[RecoveryDispatchRunCommand],
    errors: list[str],
    failed_count: int,
) -> str:
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
    if mode == "execute" and commands:
        return "executed"
    if commands:
        return "ready"
    return "no_commands"


def _command_safety_errors(
    command_name: str,
    argv: list[str],
    working_directory: str,
    uses_shell: Any,
    *,
    repo_root: Path,
    errors: list[str],
) -> None:
    if command_name not in UNLOCKED_LIVE_COMMAND_SPEC_FIELDS:
        errors.append("completion audit recovery dispatch run command name must be allowlisted")
    if uses_shell is not False:
        errors.append("completion audit recovery dispatch run command specs must not use shell")
    if not argv:
        errors.append("completion audit recovery dispatch run command argv must be non-empty")
    elif command_name == "workflow_dispatch" and argv[:3] != [
        "gh",
        "workflow",
        "run",
    ]:
        errors.append(
            "completion audit recovery dispatch run workflow_dispatch must use gh workflow run"
        )
    elif command_name == "local_live_probe" and argv[0] not in {"python", "python3"}:
        errors.append(
            "completion audit recovery dispatch run local_live_probe must use python"
        )
    if _argv_has_shell_control(argv):
        errors.append(
            "completion audit recovery dispatch run argv must not contain shell control tokens"
        )
    try:
        _resolve_working_directory(repo_root, working_directory)
    except ValueError as exc:
        errors.append(str(exc))


def _resolve_working_directory(repo_root: Path, working_directory: str) -> Path:
    if not working_directory:
        raise ValueError("completion audit recovery dispatch run working_directory must be non-empty")
    root = repo_root.resolve()
    cwd = (root / working_directory).resolve()
    if cwd != root and root not in cwd.parents:
        raise ValueError(
            "completion audit recovery dispatch run working_directory must stay inside repo root"
        )
    return cwd


def _subprocess_runner(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(RECOVERY_DISPATCH_RUN_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(RECOVERY_DISPATCH_RUN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(RECOVERY_DISPATCH_RUN_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _regular_file_sha(path: Path | None) -> str:
    if path is None or not path.is_file() or path.is_symlink():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _recovery_dispatch_run_fingerprint(
    *,
    mode: str,
    allow_live_dispatch: bool,
    run_state: str,
    commands: list[dict[str, Any]],
    denied_items: list[dict[str, Any]],
    errors: list[str],
) -> str:
    encoded = json.dumps(
        {
            "allow_live_dispatch": allow_live_dispatch,
            "commands": commands,
            "denied_items": denied_items,
            "error_codes": _error_codes(errors),
            "mode": mode,
            "run_state": run_state,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _argv_has_shell_control(argv: list[str]) -> bool:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    return any(any(token in arg for token in shell_control_tokens) for arg in argv)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error.startswith(
        "completion audit recovery dispatch authorization failed validation"
    ):
        return "completion_audit_recovery_dispatch_run_authorization_invalid"
    if error == "completion audit recovery dispatch authorization root must be an object":
        return "completion_audit_recovery_dispatch_run_authorization_root_invalid"
    if error == "completion audit recovery dispatch authorization is not ready":
        return "completion_audit_recovery_dispatch_run_authorization_not_ready"
    if error == "completion audit recovery dispatch authorization has no live command specs":
        return "completion_audit_recovery_dispatch_run_missing_live_command_specs"
    if "requires --allow-live-dispatch" in error:
        return "completion_audit_recovery_dispatch_run_live_dispatch_not_allowed"
    if "command failed" in error:
        return "completion_audit_recovery_dispatch_run_command_failed"
    if (
        "command" in error
        or "argv" in error
        or "working_directory" in error
        or "shell" in error
    ):
        return "completion_audit_recovery_dispatch_run_command_invalid"
    if error == RECOVERY_DISPATCH_RUN_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_dispatch_run_output_path_directory"
    if error == RECOVERY_DISPATCH_RUN_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_dispatch_run_output_path_symlink"
    if error == RECOVERY_DISPATCH_RUN_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_recovery_dispatch_run_output_path_parent_symlink"
    return "completion_audit_recovery_dispatch_run_failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and materialize a recovery dispatch authorization. Dry-run "
            "is the default; live execution requires --execute and "
            "--allow-live-dispatch."
        ),
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
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-live-dispatch", action="store_true")
    parser.add_argument(
        "--allow-blocked-report",
        action="store_true",
        help="Exit zero for a blocked authorization while preserving ok=false in JSON.",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = run_completion_audit_recovery_dispatch_authorization(
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
            repo_root=args.repo_root,
            execute=args.execute,
            allow_live_dispatch=args.allow_live_dispatch,
        )
    except Exception as exc:  # noqa: BLE001
        report = _error_report(args.recovery_dispatch_authorization, str(exc))
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    if report.ok:
        return 0
    if args.allow_blocked_report and report.run_state in {
        "blocked_by_authorization",
        "blocked_by_missing_live_command_specs",
    }:
        return 0
    return 1


def _error_report(
    recovery_dispatch_authorization_path: Path,
    error: str,
) -> RecoveryDispatchRunReport:
    return _report(
        recovery_dispatch_authorization_path,
        payload={},
        mode="dry_run",
        execute=False,
        allow_live_dispatch=False,
        commands=[],
        denied_items=[],
        errors=[error],
    )


if __name__ == "__main__":
    raise SystemExit(main())
