#!/usr/bin/env python3
"""Materialize or execute a validated completion-audit dispatch gate."""

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

from generate_completion_audit_dispatch_gate import (  # noqa: E402
    BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS,
    UNLOCKED_LIVE_COMMAND_SPEC_FIELDS,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_dispatch_gate as gate_validator  # noqa: E402


DISPATCH_RUN_SCHEMA_VERSION = "wiii.completion_audit_dispatch_run.v1"
DISPATCH_RUN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit dispatch run output path must not be a directory"
)
DISPATCH_RUN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit dispatch run output path must not be a symlink"
)
DISPATCH_RUN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit dispatch run output path parent must not be a symlink"
)

CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DispatchRunCommand:
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
class DispatchRunReport:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    allow_live_dispatch: bool
    dispatch_gate_path: str
    dispatch_gate_sha256: str
    dispatch_gate_schema_version: str
    dispatch_gate_fingerprint_sha256: str
    dispatch_ready: bool
    dispatch_item_count: int
    ready_dispatch_item_count: int
    blocked_dispatch_item_count: int
    command_count: int
    diagnostic_command_count: int
    executed_command_count: int
    failed_command_count: int
    dispatch_run_fingerprint_sha256: str
    commands: list[DispatchRunCommand]
    diagnostic_commands: list[DispatchRunCommand]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def run_completion_audit_dispatch_gate(
    dispatch_gate_path: Path,
    *,
    launch_pack_path: Path,
    setup_state_path: Path,
    repo_root: Path = Path("."),
    execute: bool = False,
    allow_live_dispatch: bool = False,
    command_runner: CommandRunner | None = None,
) -> DispatchRunReport:
    errors: list[str] = []
    mode = "execute" if execute else "dry_run"
    validation = gate_validator.validate_dispatch_gate(
        dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
    )
    if not validation.ok:
        errors.append(
            "completion audit dispatch gate failed validation: "
            + "; ".join(validation.errors)
        )
        return _report(
            dispatch_gate_path,
            payload={},
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            diagnostic_commands=[],
            errors=errors,
        )
    payload = load_strict_json_file(dispatch_gate_path)
    if not isinstance(payload, dict):
        errors.append("completion audit dispatch gate root must be an object")
        return _report(
            dispatch_gate_path,
            payload={},
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            diagnostic_commands=[],
            errors=errors,
        )
    if payload.get("dispatch_ready") is not True:
        errors.append("completion audit dispatch gate is not ready")
        diagnostic_commands = _materialize_diagnostic_commands(
            payload,
            repo_root=repo_root,
            errors=errors,
        )
        return _report(
            dispatch_gate_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            diagnostic_commands=diagnostic_commands,
            errors=errors,
        )
    if execute and not allow_live_dispatch:
        errors.append(
            "completion audit dispatch execution requires --allow-live-dispatch"
        )
        return _report(
            dispatch_gate_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_live_dispatch=allow_live_dispatch,
            commands=[],
            diagnostic_commands=[],
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
        dispatch_gate_path,
        payload=payload,
        mode=mode,
        execute=execute,
        allow_live_dispatch=allow_live_dispatch,
        commands=commands,
        diagnostic_commands=[],
        errors=errors,
    )


def _materialize_commands(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    errors: list[str],
) -> list[DispatchRunCommand]:
    commands: list[DispatchRunCommand] = []
    for item in payload.get("dispatch_items", []):
        if not isinstance(item, dict) or item.get("dispatch_ready") is not True:
            continue
        requirement_id = _string(item.get("requirement_id"))
        specs = item.get("unlocked_live_command_specs")
        if not isinstance(specs, dict):
            errors.append("dispatch run unlocked_live_command_specs must be an object")
            continue
        for command_name in UNLOCKED_LIVE_COMMAND_SPEC_FIELDS:
            spec = specs.get(command_name)
            if not isinstance(spec, dict):
                errors.append("dispatch run unlocked command spec must be an object")
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
                DispatchRunCommand(
                    requirement_id=requirement_id,
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
    return commands


def _materialize_diagnostic_commands(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    errors: list[str],
) -> list[DispatchRunCommand]:
    commands: list[DispatchRunCommand] = []
    for item in payload.get("dispatch_items", []):
        if not isinstance(item, dict) or item.get("dispatch_ready") is True:
            continue
        requirement_id = _string(item.get("requirement_id"))
        specs = item.get("blocked_diagnostic_command_specs")
        if not isinstance(specs, dict):
            errors.append(
                "dispatch run blocked_diagnostic_command_specs must be an object"
            )
            continue
        expected_artifact = _string(item.get("expected_artifact"))
        for command_name in BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS:
            spec = specs.get(command_name)
            if not isinstance(spec, dict):
                errors.append("dispatch run blocked diagnostic command spec must be an object")
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
                allowlist=BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS,
                diagnostic=True,
                expected_artifact=expected_artifact,
            )
            commands.append(
                DispatchRunCommand(
                    requirement_id=requirement_id,
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
    return commands


def _execute_commands(
    commands: list[DispatchRunCommand],
    *,
    repo_root: Path,
    command_runner: CommandRunner,
    errors: list[str],
) -> list[DispatchRunCommand]:
    executed: list[DispatchRunCommand] = []
    for command in commands:
        cwd = _resolve_working_directory(repo_root, command.working_directory)
        result = command_runner(command.argv, cwd)
        if result.returncode != 0:
            errors.append(
                "completion audit dispatch command failed: "
                f"{command.requirement_id}:{command.command_name}"
            )
        executed.append(
            DispatchRunCommand(
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
    dispatch_gate_path: Path,
    *,
    payload: dict[str, Any],
    mode: str,
    execute: bool,
    allow_live_dispatch: bool,
    commands: list[DispatchRunCommand],
    diagnostic_commands: list[DispatchRunCommand],
    errors: list[str],
) -> DispatchRunReport:
    executed_count = sum(1 for command in commands if command.executed)
    failed_count = sum(1 for command in commands if command.returncode not in {-1, 0})
    return DispatchRunReport(
        schema_version=DISPATCH_RUN_SCHEMA_VERSION,
        ok=not errors,
        mode=mode,
        dry_run=not execute,
        allow_live_dispatch=allow_live_dispatch,
        dispatch_gate_path=str(dispatch_gate_path),
        dispatch_gate_sha256=(
            _sha256_file(dispatch_gate_path)
            if dispatch_gate_path.is_file() and not dispatch_gate_path.is_symlink()
            else ""
        ),
        dispatch_gate_schema_version=_string(payload.get("schema_version")),
        dispatch_gate_fingerprint_sha256=_string(
            payload.get("dispatch_gate_fingerprint_sha256")
        ),
        dispatch_ready=payload.get("dispatch_ready") is True,
        dispatch_item_count=_int(payload.get("dispatch_item_count")),
        ready_dispatch_item_count=_int(payload.get("ready_dispatch_item_count")),
        blocked_dispatch_item_count=_int(payload.get("blocked_dispatch_item_count")),
        command_count=len(commands),
        diagnostic_command_count=len(diagnostic_commands),
        executed_command_count=executed_count,
        failed_command_count=failed_count,
        dispatch_run_fingerprint_sha256=_dispatch_run_fingerprint(
            [asdict(command) for command in commands],
            errors,
            [asdict(command) for command in diagnostic_commands],
        ),
        commands=commands,
        diagnostic_commands=diagnostic_commands,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_output_included": False,
        },
        errors=errors,
    )


def _command_safety_errors(
    command_name: str,
    argv: list[str],
    working_directory: str,
    uses_shell: Any,
    *,
    repo_root: Path,
    errors: list[str],
    allowlist: tuple[str, ...] = UNLOCKED_LIVE_COMMAND_SPEC_FIELDS,
    diagnostic: bool = False,
    expected_artifact: str = "",
) -> None:
    if command_name not in allowlist:
        errors.append("dispatch run command name must be allowlisted")
    if uses_shell is not False:
        errors.append("dispatch run command specs must not use shell execution")
    if not argv:
        errors.append("dispatch run command argv must be non-empty")
    elif command_name == "workflow_dispatch" and argv[:3] != [
        "gh",
        "workflow",
        "run",
    ]:
        errors.append("dispatch run workflow_dispatch must use gh workflow run")
    elif command_name == "local_live_probe" and argv[0] not in {"python", "python3"}:
        errors.append("dispatch run local_live_probe must use python")
    elif command_name == "local_failure_from_preflight":
        if argv[0] not in {"python", "python3"}:
            errors.append("dispatch run local_failure_from_preflight must use python")
        if "--failure-from-preflight" not in argv:
            errors.append(
                "dispatch run local_failure_from_preflight must use failure-from-preflight"
            )
        if not _argv_option_value(argv, "--failure-preflight-json"):
            errors.append(
                "dispatch run local_failure_from_preflight must bind failure preflight JSON"
            )
        failure_output = _argv_option_value(argv, "--out")
        if not failure_output:
            errors.append("dispatch run local_failure_from_preflight must write --out")
        elif diagnostic and expected_artifact and failure_output != expected_artifact:
            errors.append(
                "dispatch run local_failure_from_preflight must write expected artifact"
            )
    if _argv_has_shell_control(argv):
        errors.append("dispatch run argv must not contain shell control tokens")
    try:
        _resolve_working_directory(repo_root, working_directory)
    except ValueError as exc:
        errors.append(str(exc))


def _resolve_working_directory(repo_root: Path, working_directory: str) -> Path:
    if not working_directory:
        raise ValueError("dispatch run working_directory must be non-empty")
    root = repo_root.resolve()
    cwd = (root / working_directory).resolve()
    if cwd != root and root not in cwd.parents:
        raise ValueError("dispatch run working_directory must stay inside repo root")
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
        raise ValueError(DISPATCH_RUN_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(DISPATCH_RUN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(DISPATCH_RUN_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and materialize a completion-audit dispatch gate. "
            "Dry-run is the default; live execution requires --execute and "
            "--allow-live-dispatch."
        ),
    )
    parser.add_argument("dispatch_gate", type=Path)
    parser.add_argument("--launch-pack", type=Path, required=True)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-live-dispatch", action="store_true")
    parser.add_argument(
        "--allow-pending-report",
        action="store_true",
        help="Exit zero for a not-ready gate while preserving ok=false in JSON.",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = run_completion_audit_dispatch_gate(
            args.dispatch_gate,
            launch_pack_path=args.launch_pack,
            setup_state_path=args.setup_state,
            repo_root=args.repo_root,
            execute=args.execute,
            allow_live_dispatch=args.allow_live_dispatch,
        )
    except Exception as exc:  # noqa: BLE001
        report = _error_report(args.dispatch_gate, str(exc))
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    if report.ok:
        return 0
    if args.allow_pending_report and not report.dispatch_ready:
        return 0
    return 1


def _error_report(dispatch_gate_path: Path, error: str) -> DispatchRunReport:
    return _report(
        dispatch_gate_path,
        payload={},
        mode="dry_run",
        execute=False,
        allow_live_dispatch=False,
        commands=[],
        diagnostic_commands=[],
        errors=[error],
    )


def _dispatch_run_fingerprint(
    commands: list[dict[str, Any]],
    errors: list[str],
    diagnostic_commands: list[dict[str, Any]] | None = None,
) -> str:
    encoded = json.dumps(
        {
            "commands": commands,
            "diagnostic_commands": diagnostic_commands or [],
            "error_codes": _error_codes(errors),
        },
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


def _argv_has_shell_control(argv: list[str]) -> bool:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    return any(any(token in arg for token in shell_control_tokens) for arg in argv)


def _argv_option_value(argv: list[str], option: str) -> str:
    for index, arg in enumerate(argv[:-1]):
        if arg == option:
            return argv[index + 1].strip("\"'")
    return ""


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
    if error.startswith("completion audit dispatch gate failed validation"):
        return "completion_audit_dispatch_run_gate_invalid"
    if error == "completion audit dispatch gate root must be an object":
        return "completion_audit_dispatch_run_gate_root_invalid"
    if error == "completion audit dispatch gate is not ready":
        return "completion_audit_dispatch_run_gate_not_ready"
    if "requires --allow-live-dispatch" in error:
        return "completion_audit_dispatch_run_live_dispatch_not_allowed"
    if "command failed" in error:
        return "completion_audit_dispatch_run_command_failed"
    if (
        "command" in error
        or "argv" in error
        or "working_directory" in error
        or "shell" in error
    ):
        return "completion_audit_dispatch_run_command_invalid"
    if error == DISPATCH_RUN_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_dispatch_run_output_path_directory"
    if error == DISPATCH_RUN_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_dispatch_run_output_path_symlink"
    if error == DISPATCH_RUN_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_dispatch_run_output_path_parent_symlink"
    return "completion_audit_dispatch_run_failed"


if __name__ == "__main__":
    raise SystemExit(main())
