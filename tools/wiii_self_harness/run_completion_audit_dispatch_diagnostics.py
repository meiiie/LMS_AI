#!/usr/bin/env python3
"""Dry-run or execute pending completion-audit diagnostic commands."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from run_completion_audit_dispatch_gate import (  # noqa: E402
    DISPATCH_RUN_SCHEMA_VERSION,
    _sha256_file,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_dispatch_run as dispatch_run_validator  # noqa: E402
import validate_runtime_evidence_preflight as preflight_validator  # noqa: E402


DIAGNOSTICS_SCHEMA_VERSION = "wiii.completion_audit_dispatch_diagnostics.v1"
DIAGNOSTICS_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit dispatch diagnostics output path must not be a directory"
)
DIAGNOSTICS_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit dispatch diagnostics output path must not be a symlink"
)
DIAGNOSTICS_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit dispatch diagnostics output path parent must not be a symlink"
)

CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DispatchDiagnosticCommand:
    requirement_id: str
    command_name: str
    working_directory: str
    argv: list[str]
    uses_shell: bool
    executed: bool
    returncode: int
    execution_ok: bool
    argv_rebound: bool
    unresolved_placeholder_count: int
    output_artifact_path: str
    output_artifact_sha256: str
    output_artifact_validated: bool
    stdout_included: bool
    stderr_included: bool


@dataclass(frozen=True)
class PreflightStageResult:
    stage: DispatchPreflightStage
    payload: dict[str, Any]


@dataclass(frozen=True)
class DispatchPreflightStage:
    requirement_id: str
    source_file: str
    source_fragment: str
    source_path: str
    source_sha256: str
    target_path: str
    target_sha256: str
    validation_schema_version: str
    validation_ok: bool
    validation_error_codes: list[str]
    staged: bool


@dataclass(frozen=True)
class DispatchDiagnosticsReport:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    allow_diagnostic_execution: bool
    dispatch_run_path: str
    dispatch_run_sha256: str
    dispatch_run_schema_version: str
    dispatch_run_fingerprint_sha256: str
    dispatch_ready: bool
    diagnostic_command_count: int
    executed_diagnostic_command_count: int
    failed_diagnostic_command_count: int
    preflight_source_dir_count: int
    preflight_stage_count: int
    staged_preflight_count: int
    diagnostic_run_fingerprint_sha256: str
    commands: list[DispatchDiagnosticCommand]
    preflight_stages: list[DispatchPreflightStage]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def run_completion_audit_dispatch_diagnostics(
    dispatch_run_path: Path,
    *,
    dispatch_gate_path: Path | None = None,
    launch_pack_path: Path | None = None,
    setup_state_path: Path | None = None,
    repo_root: Path = Path("."),
    execute: bool = False,
    allow_diagnostic_execution: bool = False,
    preflight_source_dirs: list[Path] | None = None,
    command_runner: CommandRunner | None = None,
) -> DispatchDiagnosticsReport:
    errors: list[str] = []
    mode = "execute" if execute else "dry_run"
    source_dirs = list(preflight_source_dirs or [])
    validation = dispatch_run_validator.validate_dispatch_run(
        dispatch_run_path,
        dispatch_gate_path=dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=repo_root,
    )
    if not validation.ok:
        errors.append(
            "completion audit dispatch diagnostics dispatch-run failed validation: "
            + "; ".join(validation.errors)
        )
        return _report(
            dispatch_run_path,
            payload={},
            mode=mode,
            execute=execute,
            allow_diagnostic_execution=allow_diagnostic_execution,
            preflight_source_dirs=source_dirs,
            commands=[],
            preflight_stages=[],
            errors=errors,
        )
    payload = load_strict_json_file(dispatch_run_path)
    if not isinstance(payload, dict):
        errors.append("completion audit dispatch diagnostics dispatch-run root invalid")
        return _report(
            dispatch_run_path,
            payload={},
            mode=mode,
            execute=execute,
            allow_diagnostic_execution=allow_diagnostic_execution,
            preflight_source_dirs=source_dirs,
            commands=[],
            preflight_stages=[],
            errors=errors,
        )
    if payload.get("dispatch_ready") is True:
        errors.append("completion audit dispatch diagnostics requires a pending dispatch run")
        return _report(
            dispatch_run_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_diagnostic_execution=allow_diagnostic_execution,
            preflight_source_dirs=source_dirs,
            commands=[],
            preflight_stages=[],
            errors=errors,
        )
    if execute and not allow_diagnostic_execution:
        errors.append(
            "completion audit dispatch diagnostics execution requires "
            "--allow-diagnostic-execution"
        )
        return _report(
            dispatch_run_path,
            payload=payload,
            mode=mode,
            execute=execute,
            allow_diagnostic_execution=allow_diagnostic_execution,
            preflight_source_dirs=source_dirs,
            commands=[],
            preflight_stages=[],
            errors=errors,
        )
    commands = _materialize_commands(payload, repo_root=repo_root, errors=errors)
    preflight_stages: list[DispatchPreflightStage] = []
    preflight_payloads: dict[str, dict[str, Any]] = {}
    if not errors and (source_dirs or execute):
        if not source_dirs:
            errors.append(
                "completion audit dispatch diagnostics execution requires --preflight-source-dir"
            )
        elif launch_pack_path is None:
            errors.append(
                "completion audit dispatch diagnostics preflight source staging "
                "requires --launch-pack"
            )
        else:
            preflight_stages, preflight_payloads = _preflight_stages(
                commands,
                launch_pack_path=launch_pack_path,
                preflight_source_dirs=source_dirs,
                repo_root=repo_root,
                stage_targets=execute,
                errors=errors,
            )
            if not errors:
                commands = _rebind_commands_from_preflights(
                    commands,
                    preflight_payloads=preflight_payloads,
                    errors=errors,
                )
    if execute and not errors:
        unresolved = sum(command.unresolved_placeholder_count for command in commands)
        if unresolved:
            errors.append(
                "completion audit dispatch diagnostics unresolved diagnostic argv placeholders: "
                f"{unresolved}"
            )
    if execute and not errors:
        commands = _execute_commands(
            commands,
            repo_root=repo_root,
            command_runner=command_runner or _subprocess_runner,
            errors=errors,
        )
    return _report(
        dispatch_run_path,
        payload=payload,
        mode=mode,
        execute=execute,
        allow_diagnostic_execution=allow_diagnostic_execution,
        preflight_source_dirs=source_dirs,
        commands=commands,
        preflight_stages=preflight_stages,
        errors=errors,
    )


def _materialize_commands(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    errors: list[str],
) -> list[DispatchDiagnosticCommand]:
    value = payload.get("diagnostic_commands")
    if not isinstance(value, list) or not value:
        errors.append("completion audit dispatch diagnostics found no diagnostic commands")
        return []
    commands: list[DispatchDiagnosticCommand] = []
    for item in value:
        if not isinstance(item, dict):
            errors.append("completion audit dispatch diagnostic command must be an object")
            continue
        command = DispatchDiagnosticCommand(
            requirement_id=_string(item.get("requirement_id")),
            command_name=_string(item.get("command_name")),
            working_directory=_string(item.get("working_directory")),
            argv=_string_list(item.get("argv")),
            uses_shell=item.get("uses_shell") is True,
            executed=False,
            returncode=-1,
            execution_ok=False,
            argv_rebound=False,
            unresolved_placeholder_count=_unresolved_placeholder_count(
                _string_list(item.get("argv"))
            ),
            output_artifact_path="",
            output_artifact_sha256="",
            output_artifact_validated=False,
            stdout_included=False,
            stderr_included=False,
        )
        _command_safety_errors(command, repo_root=repo_root, errors=errors)
        commands.append(command)
    return commands


def _execute_commands(
    commands: list[DispatchDiagnosticCommand],
    *,
    repo_root: Path,
    command_runner: CommandRunner,
    errors: list[str],
) -> list[DispatchDiagnosticCommand]:
    executed: list[DispatchDiagnosticCommand] = []
    for command in commands:
        cwd = _resolve_working_directory(repo_root, command.working_directory)
        result = command_runner(command.argv, cwd)
        artifact_path, artifact_sha, artifact_valid = _validate_output_artifact(
            command,
            cwd=cwd,
        )
        execution_ok = int(result.returncode) == 0 or (
            int(result.returncode) == 1 and artifact_valid
        )
        if not execution_ok:
            errors.append(
                "completion audit dispatch diagnostic command failed: "
                f"{command.requirement_id}:{command.command_name}"
            )
        executed.append(
            DispatchDiagnosticCommand(
                requirement_id=command.requirement_id,
                command_name=command.command_name,
                working_directory=command.working_directory,
                argv=command.argv,
                uses_shell=command.uses_shell,
                executed=True,
                returncode=int(result.returncode),
                execution_ok=execution_ok,
                argv_rebound=command.argv_rebound,
                unresolved_placeholder_count=command.unresolved_placeholder_count,
                output_artifact_path=artifact_path,
                output_artifact_sha256=artifact_sha,
                output_artifact_validated=artifact_valid,
                stdout_included=False,
                stderr_included=False,
            )
        )
    return executed


def _validate_output_artifact(
    command: DispatchDiagnosticCommand,
    *,
    cwd: Path,
) -> tuple[str, str, bool]:
    output_name = _argv_option_value(command.argv, "--out")
    if not output_name:
        return "", "", False
    output = Path(output_name)
    if (
        output.is_absolute()
        or output.drive
        or len(output.parts) != 1
        or output.name != output_name
    ):
        return "", "", False
    output_path = cwd / output_name
    if not output_path.is_file() or output_path.is_symlink():
        return str(output_path), "", False
    artifact_sha = _sha256_file(output_path)
    try:
        artifact = load_strict_json_file(output_path)
    except Exception:  # noqa: BLE001
        return str(output_path), artifact_sha, False
    if not isinstance(artifact, dict) or artifact.get("status") != "fail":
        return str(output_path), artifact_sha, False
    setup = artifact.get("setup_contract")
    if not isinstance(setup, dict) or setup.get("requirement_id") != command.requirement_id:
        return str(output_path), artifact_sha, False
    preflight_key = (
        "preflight_summary"
        if command.requirement_id == "wiii-connect-composio-acceptance"
        else "preflight"
    )
    preflight = artifact.get(preflight_key)
    if not isinstance(preflight, dict):
        return str(output_path), artifact_sha, False
    validation = _validate_preflight_payload(
        preflight,
        requirement_id=command.requirement_id,
    )
    return str(output_path), artifact_sha, validation.ok


def _preflight_stages(
    commands: list[DispatchDiagnosticCommand],
    *,
    launch_pack_path: Path,
    preflight_source_dirs: list[Path],
    repo_root: Path,
    stage_targets: bool,
    errors: list[str],
) -> tuple[list[DispatchPreflightStage], dict[str, dict[str, Any]]]:
    launch_items = _launch_items_by_requirement(launch_pack_path, errors)
    source_dirs = _resolved_preflight_source_dirs(preflight_source_dirs, errors)
    if not launch_items or not source_dirs:
        return [], {}

    stages: list[DispatchPreflightStage] = []
    payloads: dict[str, dict[str, Any]] = {}
    for command in commands:
        target_name = _argv_option_value(command.argv, "--failure-preflight-json")
        launch_item = launch_items.get(command.requirement_id)
        if launch_item is None:
            errors.append(
                "completion audit dispatch diagnostics preflight source missing "
                f"launch item: {command.requirement_id}"
            )
            continue
        result = _preflight_stage(
            command,
            launch_item=launch_item,
            target_name=target_name,
            source_dirs=source_dirs,
            repo_root=repo_root,
            stage_target=stage_targets,
            errors=errors,
        )
        if result is not None:
            stages.append(result.stage)
            payloads[command.requirement_id] = result.payload
    return stages, payloads


def _rebind_commands_from_preflights(
    commands: list[DispatchDiagnosticCommand],
    *,
    preflight_payloads: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[DispatchDiagnosticCommand]:
    rebound: list[DispatchDiagnosticCommand] = []
    for command in commands:
        payload = preflight_payloads.get(command.requirement_id)
        if payload is None:
            errors.append(
                "completion audit dispatch diagnostics preflight payload missing "
                f"for argv rebind: {command.requirement_id}"
            )
            rebound.append(command)
            continue
        new_argv = _rebind_argv(command.argv, command.requirement_id, payload)
        unresolved_count = _unresolved_placeholder_count(new_argv)
        if _argv_has_shell_control(new_argv):
            errors.append(
                "completion audit dispatch diagnostics rebound argv must not "
                f"contain shell control tokens: {command.requirement_id}"
            )
        rebound.append(
            DispatchDiagnosticCommand(
                requirement_id=command.requirement_id,
                command_name=command.command_name,
                working_directory=command.working_directory,
                argv=new_argv,
                uses_shell=command.uses_shell,
                executed=command.executed,
                returncode=command.returncode,
                execution_ok=command.execution_ok,
                argv_rebound=new_argv != command.argv,
                unresolved_placeholder_count=unresolved_count,
                output_artifact_path=command.output_artifact_path,
                output_artifact_sha256=command.output_artifact_sha256,
                output_artifact_validated=command.output_artifact_validated,
                stdout_included=command.stdout_included,
                stderr_included=command.stderr_included,
            )
        )
    return rebound


def _rebind_argv(
    argv: list[str],
    requirement_id: str,
    preflight: dict[str, Any],
) -> list[str]:
    replacements = _preflight_placeholder_replacements(requirement_id, preflight)
    result: list[str] = []
    for arg in argv:
        value = arg
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        result.append(value)
    return result


def _preflight_placeholder_replacements(
    requirement_id: str,
    preflight: dict[str, Any],
) -> dict[str, str]:
    if requirement_id == "autonomy-proactive-channel":
        channel = _string(preflight.get("requested_channel"))
        if channel not in {"messenger", "telegram", "zalo"}:
            channel = "telegram"
        return {
            "<approved-channel>": channel,
            "<approved-recipient-id>": "diagnostic-recipient",
        }
    if requirement_id == "lms-test-course-replay":
        return {"<backend-base-url>": "http://testserver"}
    if requirement_id == "wiii-connect-composio-acceptance":
        provider = _safe_slug(_string(preflight.get("requested_provider"))) or "gmail"
        action = _safe_slug(_string(preflight.get("requested_action"))).upper()
        return {
            "<backend-url>": "http://localhost:8000",
            "<provider>": provider,
            "<optional-action>": action or "GMAIL_FETCH_EMAILS",
            "<readonly-arguments-json>": "{}",
        }
    return {}


def _safe_slug(value: str) -> str:
    normalized = value.strip().replace("-", "_")
    if not normalized:
        return ""
    if all(char.isalnum() or char == "_" for char in normalized):
        return normalized
    return ""


def _launch_items_by_requirement(
    launch_pack_path: Path,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    try:
        payload = load_strict_json_file(launch_pack_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            "completion audit dispatch diagnostics preflight source launch-pack "
            f"JSON invalid: {exc}"
        )
        return {}
    if not isinstance(payload, dict):
        errors.append(
            "completion audit dispatch diagnostics preflight source launch-pack "
            "root invalid"
        )
        return {}
    items = payload.get("launch_items")
    if not isinstance(items, list):
        errors.append(
            "completion audit dispatch diagnostics preflight source launch_items "
            "must be a list"
        )
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        requirement_id = _string(item.get("requirement_id"))
        if requirement_id:
            result[requirement_id] = item
    return result


def _resolved_preflight_source_dirs(
    preflight_source_dirs: list[Path],
    errors: list[str],
) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for source_dir in preflight_source_dirs:
        if source_dir.is_symlink():
            errors.append(
                "completion audit dispatch diagnostics preflight source directory "
                f"must not be a symlink: {source_dir}"
            )
            continue
        if not source_dir.exists():
            errors.append(
                "completion audit dispatch diagnostics preflight source directory "
                f"does not exist: {source_dir}"
            )
            continue
        if not source_dir.is_dir():
            errors.append(
                "completion audit dispatch diagnostics preflight source path must "
                f"be a directory: {source_dir}"
            )
            continue
        resolved = source_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _preflight_stage(
    command: DispatchDiagnosticCommand,
    *,
    launch_item: dict[str, Any],
    target_name: str,
    source_dirs: list[Path],
    repo_root: Path,
    stage_target: bool,
    errors: list[str],
) -> PreflightStageResult | None:
    source_file = _string(launch_item.get("preflight_source_file"))
    expected_source_sha = _string(launch_item.get("preflight_source_file_sha256"))
    source_rel, source_fragment = _split_preflight_source_file(
        source_file,
        command.requirement_id,
        errors,
    )
    target_path = _resolve_preflight_target_path(
        repo_root,
        command.working_directory,
        target_name,
        stage_target=stage_target,
        errors=errors,
    )
    if source_rel is None or target_path is None:
        return None
    source_path = _find_preflight_source_path(
        source_rel,
        source_dirs=source_dirs,
        requirement_id=command.requirement_id,
        errors=errors,
    )
    if source_path is None:
        return None

    source_sha = _sha256_file(source_path)
    if expected_source_sha and source_sha != expected_source_sha:
        errors.append(
            "completion audit dispatch diagnostics preflight source SHA mismatch: "
            f"{command.requirement_id}"
        )
    payload = _load_preflight_payload(
        source_path,
        source_fragment=source_fragment,
        requirement_id=command.requirement_id,
        errors=errors,
    )
    if payload is None:
        return None

    preflight_bytes = _canonical_preflight_bytes(payload)
    validation = _validate_preflight_payload(
        payload,
        requirement_id=command.requirement_id,
    )
    validation_dict = validation.to_dict()
    validation_error_codes = _string_list(validation_dict.get("error_codes"))
    if not validation.ok:
        errors.append(
            "completion audit dispatch diagnostics preflight source validation "
            f"failed: {command.requirement_id}: "
            + ", ".join(validation_error_codes)
        )

    staged = False
    if stage_target and validation.ok:
        target_path.write_bytes(preflight_bytes)
        staged = True

    return PreflightStageResult(
        stage=DispatchPreflightStage(
            requirement_id=command.requirement_id,
            source_file=source_file,
            source_fragment=source_fragment,
            source_path=str(source_path),
            source_sha256=source_sha,
            target_path=str(target_path),
            target_sha256=hashlib.sha256(preflight_bytes).hexdigest(),
            validation_schema_version=validation.validation_schema_version,
            validation_ok=validation.ok,
            validation_error_codes=validation_error_codes,
            staged=staged,
        ),
        payload=payload,
    )


def _split_preflight_source_file(
    source_file: str,
    requirement_id: str,
    errors: list[str],
) -> tuple[Path | None, str]:
    if not source_file:
        errors.append(
            "completion audit dispatch diagnostics preflight source file missing: "
            f"{requirement_id}"
        )
        return None, ""
    if source_file.count("#") > 1:
        errors.append(
            "completion audit dispatch diagnostics preflight source file invalid: "
            f"{requirement_id}"
        )
        return None, ""
    file_part, separator, fragment = source_file.partition("#")
    if not file_part:
        errors.append(
            "completion audit dispatch diagnostics preflight source file missing: "
            f"{requirement_id}"
        )
        return None, ""
    relative = Path(file_part)
    if (
        relative.is_absolute()
        or relative.drive
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        errors.append(
            "completion audit dispatch diagnostics preflight source file must be "
            f"a safe relative path: {requirement_id}"
        )
        return None, ""
    return relative, fragment if separator else ""


def _resolve_preflight_target_path(
    repo_root: Path,
    working_directory: str,
    target_name: str,
    *,
    stage_target: bool,
    errors: list[str],
) -> Path | None:
    if not target_name:
        errors.append(
            "completion audit dispatch diagnostics preflight target file missing"
        )
        return None
    target = Path(target_name)
    if (
        target.is_absolute()
        or target.drive
        or len(target.parts) != 1
        or target.name != target_name
    ):
        errors.append(
            "completion audit dispatch diagnostics preflight target must be a "
            "plain filename"
        )
        return None
    cwd = _resolve_working_directory(repo_root, working_directory)
    if stage_target and not cwd.is_dir():
        errors.append(
            "completion audit dispatch diagnostics preflight target cwd must "
            f"exist: {working_directory}"
        )
        return None
    target_path = cwd / target_name
    if target_path.exists() and target_path.is_dir():
        errors.append(
            "completion audit dispatch diagnostics preflight target must not be "
            f"a directory: {target_name}"
        )
        return None
    if target_path.is_symlink():
        errors.append(
            "completion audit dispatch diagnostics preflight target must not be "
            f"a symlink: {target_name}"
        )
        return None
    return target_path


def _find_preflight_source_path(
    relative_path: Path,
    *,
    source_dirs: list[Path],
    requirement_id: str,
    errors: list[str],
) -> Path | None:
    for source_dir in source_dirs:
        candidate = (source_dir / relative_path).resolve()
        if candidate != source_dir and source_dir not in candidate.parents:
            errors.append(
                "completion audit dispatch diagnostics preflight source path "
                f"must stay inside source directory: {requirement_id}"
            )
            return None
        if not candidate.exists():
            continue
        if candidate.is_symlink():
            errors.append(
                "completion audit dispatch diagnostics preflight source file "
                f"must not be a symlink: {requirement_id}"
            )
            return None
        if not candidate.is_file():
            errors.append(
                "completion audit dispatch diagnostics preflight source path "
                f"must be a regular file: {requirement_id}"
            )
            return None
        return candidate
    errors.append(
        "completion audit dispatch diagnostics preflight source file not found: "
        f"{requirement_id}:{relative_path.as_posix()}"
    )
    return None


def _load_preflight_payload(
    source_path: Path,
    *,
    source_fragment: str,
    requirement_id: str,
    errors: list[str],
) -> dict[str, Any] | None:
    try:
        payload = load_strict_json_file(source_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            "completion audit dispatch diagnostics preflight source JSON invalid: "
            f"{requirement_id}: {exc}"
        )
        return None
    if not isinstance(payload, dict):
        errors.append(
            "completion audit dispatch diagnostics preflight source root invalid: "
            f"{requirement_id}"
        )
        return None
    if not source_fragment:
        return payload
    candidate = payload.get(source_fragment)
    if not isinstance(candidate, dict):
        errors.append(
            "completion audit dispatch diagnostics preflight source fragment "
            f"missing or invalid: {requirement_id}:{source_fragment}"
        )
        return None
    return candidate


def _validate_preflight_payload(
    payload: dict[str, Any],
    *,
    requirement_id: str,
) -> preflight_validator.PreflightValidationResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "preflight.json"
        path.write_bytes(_canonical_preflight_bytes(payload))
        return preflight_validator.validate_preflight(
            path,
            requirement_id=requirement_id,
        )


def _canonical_preflight_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).rstrip("\n")
        + "\n"
    ).encode("utf-8")


def _report(
    dispatch_run_path: Path,
    *,
    payload: dict[str, Any],
    mode: str,
    execute: bool,
    allow_diagnostic_execution: bool,
    preflight_source_dirs: list[Path] | None = None,
    commands: list[DispatchDiagnosticCommand],
    preflight_stages: list[DispatchPreflightStage] | None = None,
    errors: list[str],
) -> DispatchDiagnosticsReport:
    executed_count = sum(1 for command in commands if command.executed)
    failed_count = sum(
        1 for command in commands if command.executed and not command.execution_ok
    )
    command_dicts = [asdict(command) for command in commands]
    safe_preflight_stages = list(preflight_stages or [])
    preflight_stage_dicts = [asdict(stage) for stage in safe_preflight_stages]
    return DispatchDiagnosticsReport(
        schema_version=DIAGNOSTICS_SCHEMA_VERSION,
        ok=not errors,
        mode=mode,
        dry_run=not execute,
        allow_diagnostic_execution=allow_diagnostic_execution,
        dispatch_run_path=str(dispatch_run_path),
        dispatch_run_sha256=(
            _sha256_file(dispatch_run_path)
            if dispatch_run_path.is_file() and not dispatch_run_path.is_symlink()
            else ""
        ),
        dispatch_run_schema_version=_string(payload.get("schema_version")),
        dispatch_run_fingerprint_sha256=_string(
            payload.get("dispatch_run_fingerprint_sha256")
        ),
        dispatch_ready=payload.get("dispatch_ready") is True,
        diagnostic_command_count=len(commands),
        executed_diagnostic_command_count=executed_count,
        failed_diagnostic_command_count=failed_count,
        preflight_source_dir_count=len(preflight_source_dirs or []),
        preflight_stage_count=len(safe_preflight_stages),
        staged_preflight_count=sum(1 for stage in safe_preflight_stages if stage.staged),
        diagnostic_run_fingerprint_sha256=_diagnostic_run_fingerprint(
            command_dicts,
            errors,
            _string(payload.get("dispatch_run_fingerprint_sha256")),
            preflight_stages=preflight_stage_dicts,
        ),
        commands=commands,
        preflight_stages=safe_preflight_stages,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_output_included": False,
        },
        errors=errors,
    )


def _command_safety_errors(
    command: DispatchDiagnosticCommand,
    *,
    repo_root: Path,
    errors: list[str],
) -> None:
    if command.command_name != "local_failure_from_preflight":
        errors.append("completion audit dispatch diagnostic command name invalid")
    if command.uses_shell:
        errors.append("completion audit dispatch diagnostic command must not use shell")
    if command.working_directory != "maritime-ai-service":
        errors.append(
            "completion audit dispatch diagnostic command cwd must be maritime-ai-service"
        )
    if not command.argv:
        errors.append("completion audit dispatch diagnostic argv must be non-empty")
    else:
        if command.argv[0] not in {"python", "python3"}:
            errors.append("completion audit dispatch diagnostic command must use python")
        if "--failure-from-preflight" not in command.argv:
            errors.append(
                "completion audit dispatch diagnostic command must use failure-from-preflight"
            )
        if not _argv_option_value(command.argv, "--failure-preflight-json"):
            errors.append(
                "completion audit dispatch diagnostic command must bind failure preflight JSON"
            )
        if not _argv_option_value(command.argv, "--out"):
            errors.append("completion audit dispatch diagnostic command must write --out")
    if _argv_has_shell_control(command.argv):
        errors.append(
            "completion audit dispatch diagnostic argv must not contain shell control tokens"
        )
    try:
        _resolve_working_directory(repo_root, command.working_directory)
    except ValueError as exc:
        errors.append(str(exc))


def _resolve_working_directory(repo_root: Path, working_directory: str) -> Path:
    if not working_directory:
        raise ValueError("completion audit dispatch diagnostic cwd must be non-empty")
    root = repo_root.resolve()
    cwd = (root / working_directory).resolve()
    if cwd != root and root not in cwd.parents:
        raise ValueError("completion audit dispatch diagnostic cwd must stay inside repo")
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
        raise ValueError(DIAGNOSTICS_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(DIAGNOSTICS_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(DIAGNOSTICS_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or execute non-live diagnostic commands from a pending "
            "completion-audit dispatch-run report."
        ),
    )
    parser.add_argument("dispatch_run", type=Path)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-diagnostic-execution", action="store_true")
    parser.add_argument(
        "--preflight-source-dir",
        action="append",
        type=Path,
        default=[],
        help=(
            "Directory containing validated preflight sidecars or registered "
            "diagnostic artifacts referenced by launch-pack preflight_source_file. "
            "Required for --execute."
        ),
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = run_completion_audit_dispatch_diagnostics(
            args.dispatch_run,
            dispatch_gate_path=args.dispatch_gate,
            launch_pack_path=args.launch_pack,
            setup_state_path=args.setup_state,
            repo_root=args.repo_root,
            execute=args.execute,
            allow_diagnostic_execution=args.allow_diagnostic_execution,
            preflight_source_dirs=args.preflight_source_dir,
        )
    except Exception as exc:  # noqa: BLE001
        report = _error_report(args.dispatch_run, str(exc))
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0 if report.ok else 1


def _error_report(dispatch_run_path: Path, error: str) -> DispatchDiagnosticsReport:
    return _report(
        dispatch_run_path,
        payload={},
        mode="dry_run",
        execute=False,
        allow_diagnostic_execution=False,
        commands=[],
        errors=[error],
    )


def _diagnostic_run_fingerprint(
    commands: list[dict[str, Any]],
    errors: list[str],
    dispatch_run_fingerprint_sha256: str,
    *,
    preflight_stages: list[dict[str, Any]] | None = None,
) -> str:
    encoded = json.dumps(
        {
            "commands": commands,
            "dispatch_run_fingerprint_sha256": dispatch_run_fingerprint_sha256,
            "error_codes": _error_codes(errors),
            "preflight_stages": preflight_stages or [],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _argv_has_shell_control(argv: list[str]) -> bool:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    return any(any(token in arg for token in shell_control_tokens) for arg in argv)


def _unresolved_placeholder_count(argv: list[str]) -> int:
    return sum(1 for arg in argv if "<" in arg or ">" in arg)


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


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "dispatch-run failed validation" in error:
        return "completion_audit_dispatch_diagnostics_dispatch_run_invalid"
    if "dispatch-run root invalid" in error:
        return "completion_audit_dispatch_diagnostics_dispatch_run_root_invalid"
    if "requires a pending dispatch run" in error:
        return "completion_audit_dispatch_diagnostics_not_pending"
    if "found no diagnostic commands" in error:
        return "completion_audit_dispatch_diagnostics_empty"
    if "requires --allow-diagnostic-execution" in error:
        return "completion_audit_dispatch_diagnostics_execution_not_allowed"
    if "requires --preflight-source-dir" in error:
        return "completion_audit_dispatch_diagnostics_preflight_source_required"
    if "preflight source" in error or "preflight target" in error:
        return "completion_audit_dispatch_diagnostics_preflight_source_invalid"
    if "unresolved diagnostic argv placeholders" in error:
        return "completion_audit_dispatch_diagnostics_placeholder_unresolved"
    if "rebound argv" in error:
        return "completion_audit_dispatch_diagnostics_command_invalid"
    if "diagnostic command failed" in error:
        return "completion_audit_dispatch_diagnostics_command_failed"
    if "diagnostic command" in error or "diagnostic argv" in error:
        return "completion_audit_dispatch_diagnostics_command_invalid"
    if error == DIAGNOSTICS_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_dispatch_diagnostics_output_path_directory"
    if error == DIAGNOSTICS_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_dispatch_diagnostics_output_path_symlink"
    if error == DIAGNOSTICS_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_dispatch_diagnostics_output_path_parent_symlink"
    return "completion_audit_dispatch_diagnostics_failed"


if __name__ == "__main__":
    raise SystemExit(main())
