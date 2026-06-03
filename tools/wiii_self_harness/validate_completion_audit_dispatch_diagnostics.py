#!/usr/bin/env python3
"""Validate completion-audit dispatch diagnostics reports."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import re
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from run_completion_audit_dispatch_diagnostics import (  # noqa: E402
    DIAGNOSTICS_SCHEMA_VERSION,
    _diagnostic_run_fingerprint,
    _error_code_counts as diagnostics_error_code_counts,
    _error_codes as diagnostics_error_codes,
    run_completion_audit_dispatch_diagnostics,
)
from run_completion_audit_dispatch_gate import (  # noqa: E402
    DISPATCH_RUN_SCHEMA_VERSION,
    _sha256_file,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_dispatch_run as dispatch_run_validator  # noqa: E402


DIAGNOSTICS_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_dispatch_diagnostics_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "allow_diagnostic_execution",
    "dispatch_run_path",
    "dispatch_run_sha256",
    "dispatch_run_schema_version",
    "dispatch_run_fingerprint_sha256",
    "dispatch_ready",
    "diagnostic_command_count",
    "executed_diagnostic_command_count",
    "failed_diagnostic_command_count",
    "preflight_source_dir_count",
    "preflight_stage_count",
    "staged_preflight_count",
    "diagnostic_run_fingerprint_sha256",
    "commands",
    "preflight_stages",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
COMMAND_FIELDS = {
    "requirement_id",
    "command_name",
    "working_directory",
    "argv",
    "uses_shell",
    "executed",
    "returncode",
    "execution_ok",
    "argv_rebound",
    "unresolved_placeholder_count",
    "output_artifact_path",
    "output_artifact_sha256",
    "output_artifact_validated",
    "stdout_included",
    "stderr_included",
}
PREFLIGHT_STAGE_FIELDS = {
    "requirement_id",
    "source_file",
    "source_fragment",
    "source_path",
    "source_sha256",
    "target_path",
    "target_sha256",
    "validation_schema_version",
    "validation_ok",
    "validation_error_codes",
    "staged",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_output_included",
}


@dataclass(frozen=True)
class DiagnosticsValidationResult:
    validation_schema_version: str
    diagnostics_report_path: str
    dispatch_run_path: str | None
    dispatch_gate_path: str | None
    launch_pack_path: str | None
    setup_state_path: str | None
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


def validate_dispatch_diagnostics(
    diagnostics_report_path: Path,
    *,
    dispatch_run_path: Path | None = None,
    dispatch_gate_path: Path | None = None,
    launch_pack_path: Path | None = None,
    setup_state_path: Path | None = None,
    preflight_source_dirs: list[Path] | None = None,
    repo_root: Path = Path("."),
) -> DiagnosticsValidationResult:
    errors: list[str] = []
    payload = _load_payload(diagnostics_report_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if (
            dispatch_run_path is not None
            or dispatch_gate_path is not None
            or launch_pack_path is not None
            or setup_state_path is not None
        ):
            errors.extend(
                _source_errors(
                    payload,
                    dispatch_run_path=dispatch_run_path,
                    dispatch_gate_path=dispatch_gate_path,
                    launch_pack_path=launch_pack_path,
                    setup_state_path=setup_state_path,
                    preflight_source_dirs=preflight_source_dirs or [],
                    repo_root=repo_root,
                )
            )
    return DiagnosticsValidationResult(
        validation_schema_version=DIAGNOSTICS_VALIDATION_SCHEMA_VERSION,
        diagnostics_report_path=str(diagnostics_report_path),
        dispatch_run_path=str(dispatch_run_path) if dispatch_run_path else None,
        dispatch_gate_path=str(dispatch_gate_path) if dispatch_gate_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit dispatch diagnostics path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit dispatch diagnostics JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit dispatch diagnostics root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "dispatch diagnostics missing required field(s): " + ", ".join(missing)
        )
    if extra:
        errors.append(
            "dispatch diagnostics has unsupported field(s): " + ", ".join(extra)
        )
    if payload.get("schema_version") != DIAGNOSTICS_SCHEMA_VERSION:
        errors.append(
            f"dispatch diagnostics schema_version must be {DIAGNOSTICS_SCHEMA_VERSION!r}"
        )
    if payload.get("mode") not in {"dry_run", "execute"}:
        errors.append("dispatch diagnostics mode must be dry_run or execute")
    for field in ("ok", "dry_run", "allow_diagnostic_execution", "dispatch_ready"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"dispatch diagnostics {field} must be a boolean")
    if isinstance(payload.get("mode"), str) and isinstance(payload.get("dry_run"), bool):
        if payload["dry_run"] != (payload["mode"] == "dry_run"):
            errors.append("dispatch diagnostics dry_run must match mode")
    if (
        payload.get("allow_diagnostic_execution") is True
        and payload.get("mode") != "execute"
    ):
        errors.append("dispatch diagnostics allow_diagnostic_execution requires execute mode")
    for field in (
        "diagnostic_command_count",
        "executed_diagnostic_command_count",
        "failed_diagnostic_command_count",
        "preflight_source_dir_count",
        "preflight_stage_count",
        "staged_preflight_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"dispatch diagnostics {field} must be a non-negative integer")
    for field in (
        "dispatch_run_path",
        "dispatch_run_schema_version",
        "dispatch_run_fingerprint_sha256",
        "diagnostic_run_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str):
            errors.append(f"dispatch diagnostics {field} must be a string")
    for field in (
        "dispatch_run_sha256",
        "dispatch_run_fingerprint_sha256",
        "diagnostic_run_fingerprint_sha256",
    ):
        value = payload.get(field)
        if value and not _is_fingerprint(value):
            errors.append(f"dispatch diagnostics {field} must be a SHA-256 hex string")
    if payload.get("dispatch_run_schema_version") and (
        payload.get("dispatch_run_schema_version") != DISPATCH_RUN_SCHEMA_VERSION
    ):
        errors.append(
            f"dispatch diagnostics dispatch_run_schema_version must be {DISPATCH_RUN_SCHEMA_VERSION!r}"
        )
    for field in ("errors", "error_codes"):
        if not _is_string_list(payload.get(field)):
            errors.append(f"dispatch diagnostics {field} must be a string list")
    command_errors, commands = _command_errors(payload.get("commands"))
    errors.extend(command_errors)
    preflight_stage_errors, preflight_stages = _preflight_stage_errors(
        payload.get("preflight_stages")
    )
    errors.extend(preflight_stage_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not command_errors and not preflight_stage_errors:
        errors.extend(_summary_errors(payload, commands, preflight_stages))
    return errors


def _command_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    commands: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["dispatch diagnostics commands must be a list"], commands
    for command in value:
        if not isinstance(command, dict):
            errors.append("dispatch diagnostics command entries must be objects")
            continue
        commands.append(command)
        if set(command) != COMMAND_FIELDS:
            errors.append("dispatch diagnostics command fields must match contract")
        for field in ("requirement_id", "command_name", "working_directory"):
            if not isinstance(command.get(field), str) or not command.get(field):
                errors.append(
                    f"dispatch diagnostics command {field} must be a non-empty string"
                )
        if command.get("command_name") != "local_failure_from_preflight":
            errors.append("dispatch diagnostics command_name must be local_failure_from_preflight")
        argv = command.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append("dispatch diagnostics command argv must be a non-empty string list")
        else:
            errors.extend(_argv_shell_control_errors(argv))
            if argv[0] not in {"python", "python3"}:
                errors.append("dispatch diagnostics command must use python")
            if "--failure-from-preflight" not in argv:
                errors.append(
                    "dispatch diagnostics command must use failure-from-preflight"
                )
            if not _argv_option_value(argv, "--failure-preflight-json"):
                errors.append(
                    "dispatch diagnostics command must bind failure preflight JSON"
                )
            if not _argv_option_value(argv, "--out"):
                errors.append("dispatch diagnostics command must write --out")
        if command.get("working_directory") != "maritime-ai-service":
            errors.append("dispatch diagnostics command cwd must be maritime-ai-service")
        if command.get("uses_shell") is not False:
            errors.append("dispatch diagnostics command uses_shell must be false")
        if not isinstance(command.get("executed"), bool):
            errors.append("dispatch diagnostics command executed must be a boolean")
        if not _is_int(command.get("returncode")):
            errors.append("dispatch diagnostics command returncode must be an integer")
        elif command.get("executed") is False and command.get("returncode") != -1:
            errors.append("dispatch diagnostics unexecuted command returncode must be -1")
        if not isinstance(command.get("execution_ok"), bool):
            errors.append("dispatch diagnostics command execution_ok must be a boolean")
        if command.get("executed") is False and command.get("execution_ok") is not False:
            errors.append("dispatch diagnostics unexecuted command execution_ok must be false")
        if not isinstance(command.get("argv_rebound"), bool):
            errors.append("dispatch diagnostics command argv_rebound must be a boolean")
        if not _is_non_negative_int(command.get("unresolved_placeholder_count")):
            errors.append(
                "dispatch diagnostics command unresolved_placeholder_count must be a non-negative integer"
            )
        elif _is_string_list(argv) and command.get(
            "unresolved_placeholder_count"
        ) != _unresolved_placeholder_count(argv):
            errors.append(
                "dispatch diagnostics command unresolved_placeholder_count must match argv"
            )
        if not isinstance(command.get("output_artifact_path"), str):
            errors.append(
                "dispatch diagnostics command output_artifact_path must be a string"
            )
        if not isinstance(command.get("output_artifact_sha256"), str):
            errors.append(
                "dispatch diagnostics command output_artifact_sha256 must be a string"
            )
        elif command.get("output_artifact_sha256") and not _is_fingerprint(
            command.get("output_artifact_sha256")
        ):
            errors.append(
                "dispatch diagnostics command output_artifact_sha256 must be SHA-256"
            )
        if not isinstance(command.get("output_artifact_validated"), bool):
            errors.append(
                "dispatch diagnostics command output_artifact_validated must be a boolean"
            )
        if command.get("executed") is False:
            if command.get("output_artifact_path") or command.get("output_artifact_sha256"):
                errors.append(
                    "dispatch diagnostics unexecuted command output artifact fields must be empty"
                )
            if command.get("output_artifact_validated") is not False:
                errors.append(
                    "dispatch diagnostics unexecuted command output_artifact_validated must be false"
                )
        for field in ("stdout_included", "stderr_included"):
            if command.get(field) is not False:
                errors.append(f"dispatch diagnostics command {field} must be false")
    return errors, commands


def _preflight_stage_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    stages: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["dispatch diagnostics preflight_stages must be a list"], stages
    for stage in value:
        if not isinstance(stage, dict):
            errors.append("dispatch diagnostics preflight stage entries must be objects")
            continue
        stages.append(stage)
        if set(stage) != PREFLIGHT_STAGE_FIELDS:
            errors.append("dispatch diagnostics preflight stage fields must match contract")
        for field in (
            "requirement_id",
            "source_file",
            "source_path",
            "source_sha256",
            "target_path",
            "target_sha256",
            "validation_schema_version",
        ):
            if not isinstance(stage.get(field), str) or not stage.get(field):
                errors.append(
                    f"dispatch diagnostics preflight stage {field} must be a non-empty string"
                )
        if not isinstance(stage.get("source_fragment"), str):
            errors.append(
                "dispatch diagnostics preflight stage source_fragment must be a string"
            )
        for field in ("source_sha256", "target_sha256"):
            if stage.get(field) and not _is_fingerprint(stage.get(field)):
                errors.append(
                    f"dispatch diagnostics preflight stage {field} must be SHA-256"
                )
        if not isinstance(stage.get("validation_ok"), bool):
            errors.append(
                "dispatch diagnostics preflight stage validation_ok must be a boolean"
            )
        if not _is_string_list(stage.get("validation_error_codes")):
            errors.append(
                "dispatch diagnostics preflight stage validation_error_codes must be a string list"
            )
        elif (stage.get("validation_ok") is True) != (
            not stage.get("validation_error_codes")
        ):
            errors.append(
                "dispatch diagnostics preflight stage validation_ok must match validation errors"
            )
        if not isinstance(stage.get("staged"), bool):
            errors.append("dispatch diagnostics preflight stage staged must be a boolean")
    return errors, stages


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["dispatch diagnostics privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("dispatch diagnostics privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"dispatch diagnostics privacy.{field} must be false")
    return errors


def _summary_errors(
    payload: dict[str, Any],
    commands: list[dict[str, Any]],
    preflight_stages: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    executed_count = sum(1 for command in commands if command.get("executed") is True)
    failed_count = sum(
        1
        for command in commands
        if command.get("executed") is True and command.get("execution_ok") is not True
    )
    if payload.get("dispatch_ready") is True and commands:
        errors.append("dispatch diagnostics reports must not run ready dispatch reports")
    if payload.get("diagnostic_command_count") != len(commands):
        errors.append("dispatch diagnostics diagnostic_command_count must match commands")
    if payload.get("executed_diagnostic_command_count") != executed_count:
        errors.append(
            "dispatch diagnostics executed_diagnostic_command_count must match commands"
        )
    if payload.get("failed_diagnostic_command_count") != failed_count:
        errors.append(
            "dispatch diagnostics failed_diagnostic_command_count must match commands"
        )
    if payload.get("preflight_stage_count") != len(preflight_stages):
        errors.append("dispatch diagnostics preflight_stage_count must match stages")
    staged_count = sum(1 for stage in preflight_stages if stage.get("staged") is True)
    if payload.get("staged_preflight_count") != staged_count:
        errors.append("dispatch diagnostics staged_preflight_count must match stages")
    if payload.get("preflight_stage_count", 0) and payload.get(
        "preflight_source_dir_count"
    ) == 0:
        errors.append(
            "dispatch diagnostics preflight stages require preflight source dirs"
        )
    if payload.get("ok") is True and payload.get("mode") == "execute":
        if payload.get("preflight_stage_count") != payload.get("diagnostic_command_count"):
            errors.append(
                "dispatch diagnostics execute reports must stage every diagnostic preflight"
            )
        if payload.get("staged_preflight_count") != payload.get(
            "diagnostic_command_count"
        ):
            errors.append(
                "dispatch diagnostics execute reports must mark every preflight staged"
            )
        if any(command.get("unresolved_placeholder_count") for command in commands):
            errors.append(
                "dispatch diagnostics execute reports must resolve diagnostic argv placeholders"
            )
        if any(command.get("output_artifact_validated") is not True for command in commands):
            errors.append(
                "dispatch diagnostics execute reports must validate every output artifact"
            )
    if payload.get("dry_run") is True and executed_count:
        errors.append("dispatch diagnostics dry_run reports must not execute commands")
    if payload.get("ok") != (not payload.get("errors")):
        errors.append("dispatch diagnostics ok must match errors")
    errors_list = payload.get("errors")
    source_fingerprint = payload.get("dispatch_run_fingerprint_sha256")
    if (
        _is_string_list(errors_list)
        and isinstance(source_fingerprint, str)
        and payload.get("diagnostic_run_fingerprint_sha256")
        != _diagnostic_run_fingerprint(
            commands,
            errors_list,
            source_fingerprint,
            preflight_stages=preflight_stages,
        )
    ):
        errors.append(
            "dispatch diagnostics diagnostic_run_fingerprint_sha256 must match commands and errors"
        )
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    dispatch_run_path: Path | None,
    dispatch_gate_path: Path | None,
    launch_pack_path: Path | None,
    setup_state_path: Path | None,
    preflight_source_dirs: list[Path],
    repo_root: Path,
) -> list[str]:
    if dispatch_run_path is None:
        return [
            "completion audit dispatch diagnostics source mismatch: "
            "--dispatch-run is required when source validation is requested"
        ]
    if (
        dispatch_gate_path is None
        or launch_pack_path is None
        or setup_state_path is None
    ) and (
        dispatch_gate_path is not None
        or launch_pack_path is not None
        or setup_state_path is not None
    ):
        return [
            "completion audit dispatch diagnostics source mismatch: "
            "--dispatch-gate, --launch-pack, and --setup-state are required together"
        ]
    validation = dispatch_run_validator.validate_dispatch_run(
        dispatch_run_path,
        dispatch_gate_path=dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=repo_root,
    )
    if not validation.ok:
        return [
            "completion audit dispatch diagnostics source mismatch: "
            "dispatch run failed validation: "
            + "; ".join(validation.errors)
        ]
    dispatch_payload = load_strict_json_file(dispatch_run_path)
    if not isinstance(dispatch_payload, dict):
        return ["completion audit dispatch diagnostics source mismatch: dispatch run root invalid"]
    errors: list[str] = []
    expected_fields = {
        "dispatch_run_path": str(dispatch_run_path),
        "dispatch_run_sha256": _sha256_file(dispatch_run_path),
        "dispatch_run_schema_version": dispatch_payload.get("schema_version"),
        "dispatch_run_fingerprint_sha256": dispatch_payload.get(
            "dispatch_run_fingerprint_sha256"
        ),
        "dispatch_ready": dispatch_payload.get("dispatch_ready"),
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit dispatch diagnostics source mismatch: {field} must match source"
            )
    if payload.get("dry_run") is True and payload.get("allow_diagnostic_execution") is False:
        expected_run = run_completion_audit_dispatch_diagnostics(
            dispatch_run_path,
            dispatch_gate_path=dispatch_gate_path,
            launch_pack_path=launch_pack_path,
            setup_state_path=setup_state_path,
            repo_root=repo_root,
            preflight_source_dirs=preflight_source_dirs,
        ).to_dict()
        for field in (
            "ok",
            "mode",
            "dry_run",
            "allow_diagnostic_execution",
            "diagnostic_command_count",
            "executed_diagnostic_command_count",
            "failed_diagnostic_command_count",
            "diagnostic_run_fingerprint_sha256",
            "commands",
            "preflight_source_dir_count",
            "preflight_stage_count",
            "staged_preflight_count",
            "preflight_stages",
            "errors",
            "error_codes",
            "error_code_counts",
        ):
            if payload.get(field) != expected_run.get(field):
                errors.append(
                    f"completion audit dispatch diagnostics source mismatch: {field} must match generated dry-run"
                )
                break
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return []
    expected_codes = diagnostics_error_codes(errors)
    expected_counts = diagnostics_error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes) and error_codes != expected_codes:
        result.append("dispatch diagnostics error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("dispatch diagnostics error_code_counts must match errors")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit dispatch diagnostics report.",
    )
    parser.add_argument("diagnostics_report", type=Path)
    parser.add_argument("--dispatch-run", type=Path, default=None)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument(
        "--preflight-source-dir",
        action="append",
        type=Path,
        default=[],
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_dispatch_diagnostics(
        args.diagnostics_report,
        dispatch_run_path=args.dispatch_run,
        dispatch_gate_path=args.dispatch_gate,
        launch_pack_path=args.launch_pack,
        setup_state_path=args.setup_state,
        preflight_source_dirs=args.preflight_source_dir,
        repo_root=args.repo_root,
    )
    if args.json or args.out:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="")
    elif result.ok:
        print("Wiii Completion Audit Dispatch Diagnostics Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Dispatch Diagnostics Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _argv_shell_control_errors(argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for arg in argv:
        if any(token in arg for token in shell_control_tokens):
            return [
                "dispatch diagnostics command argv must not contain shell control operator tokens"
            ]
    return []


def _unresolved_placeholder_count(argv: list[str]) -> int:
    return sum(1 for arg in argv if "<" in arg or ">" in arg)


def _argv_option_value(argv: list[str], option: str) -> str:
    for index, arg in enumerate(argv[:-1]):
        if arg == option:
            return argv[index + 1].strip("\"'")
    return ""


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit dispatch diagnostics path must be a regular file":
        return "completion_audit_dispatch_diagnostics_path_invalid"
    if error.startswith("completion audit dispatch diagnostics JSON is invalid"):
        return "completion_audit_dispatch_diagnostics_json_invalid"
    if error == "completion audit dispatch diagnostics root must be an object":
        return "completion_audit_dispatch_diagnostics_root_invalid"
    if "source mismatch" in error:
        return "completion_audit_dispatch_diagnostics_source_mismatch"
    if "preflight stage" in error or "preflight stages" in error:
        return "completion_audit_dispatch_diagnostics_preflight_stage_invalid"
    if error.startswith("dispatch diagnostics missing required field"):
        return "completion_audit_dispatch_diagnostics_missing_required_fields"
    if error.startswith("dispatch diagnostics has unsupported field"):
        return "completion_audit_dispatch_diagnostics_unsupported_fields"
    if error.startswith("dispatch diagnostics schema_version must be"):
        return "completion_audit_dispatch_diagnostics_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_dispatch_diagnostics_fingerprint_invalid"
    if "privacy" in error or "raw_" in error or "stdout" in error or "stderr" in error:
        return "completion_audit_dispatch_diagnostics_privacy_invalid"
    if "command" in error or "argv" in error or "shell" in error:
        return "completion_audit_dispatch_diagnostics_command_invalid"
    if "mode" in error or "dry_run" in error or "allow_diagnostic_execution" in error:
        return "completion_audit_dispatch_diagnostics_mode_invalid"
    if "count" in error:
        return "completion_audit_dispatch_diagnostics_count_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_dispatch_diagnostics_error_summary_invalid"
    if "boolean" in error:
        return "completion_audit_dispatch_diagnostics_boolean_invalid"
    return "completion_audit_dispatch_diagnostics_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
