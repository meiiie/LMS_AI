#!/usr/bin/env python3
"""Validate completion-audit dispatch-run reports."""

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

from generate_completion_audit_dispatch_gate import (  # noqa: E402
    BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS,
    DISPATCH_GATE_SCHEMA_VERSION,
    UNLOCKED_LIVE_COMMAND_SPEC_FIELDS,
)
from run_completion_audit_dispatch_gate import (  # noqa: E402
    DISPATCH_RUN_SCHEMA_VERSION,
    _dispatch_run_fingerprint,
    _error_code_counts as dispatch_run_error_code_counts,
    _error_codes as dispatch_run_error_codes,
    _sha256_file,
    run_completion_audit_dispatch_gate,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_dispatch_gate as gate_validator  # noqa: E402


DISPATCH_RUN_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_dispatch_run_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "mode",
    "dry_run",
    "allow_live_dispatch",
    "dispatch_gate_path",
    "dispatch_gate_sha256",
    "dispatch_gate_schema_version",
    "dispatch_gate_fingerprint_sha256",
    "dispatch_ready",
    "dispatch_item_count",
    "ready_dispatch_item_count",
    "blocked_dispatch_item_count",
    "command_count",
    "diagnostic_command_count",
    "executed_command_count",
    "failed_command_count",
    "dispatch_run_fingerprint_sha256",
    "commands",
    "diagnostic_commands",
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
    "stdout_included",
    "stderr_included",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_output_included",
}


@dataclass(frozen=True)
class DispatchRunValidationResult:
    validation_schema_version: str
    dispatch_run_path: str
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


def validate_dispatch_run(
    dispatch_run_path: Path,
    *,
    dispatch_gate_path: Path | None = None,
    launch_pack_path: Path | None = None,
    setup_state_path: Path | None = None,
    repo_root: Path = Path("."),
) -> DispatchRunValidationResult:
    errors: list[str] = []
    payload = _load_payload(dispatch_run_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if (
            dispatch_gate_path is not None
            or launch_pack_path is not None
            or setup_state_path is not None
        ):
            errors.extend(
                _source_errors(
                    payload,
                    dispatch_gate_path=dispatch_gate_path,
                    launch_pack_path=launch_pack_path,
                    setup_state_path=setup_state_path,
                    repo_root=repo_root,
                )
            )
    return DispatchRunValidationResult(
        validation_schema_version=DISPATCH_RUN_VALIDATION_SCHEMA_VERSION,
        dispatch_run_path=str(dispatch_run_path),
        dispatch_gate_path=str(dispatch_gate_path) if dispatch_gate_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit dispatch run path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit dispatch run JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit dispatch run root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append("dispatch run missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("dispatch run has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != DISPATCH_RUN_SCHEMA_VERSION:
        errors.append(
            f"dispatch run schema_version must be {DISPATCH_RUN_SCHEMA_VERSION!r}"
        )
    if payload.get("mode") not in {"dry_run", "execute"}:
        errors.append("dispatch run mode must be dry_run or execute")
    for field in ("ok", "dry_run", "allow_live_dispatch", "dispatch_ready"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"dispatch run {field} must be a boolean")
    if isinstance(payload.get("mode"), str) and isinstance(payload.get("dry_run"), bool):
        if payload["dry_run"] != (payload["mode"] == "dry_run"):
            errors.append("dispatch run dry_run must match mode")
    if payload.get("allow_live_dispatch") is True and payload.get("mode") != "execute":
        errors.append("dispatch run allow_live_dispatch requires execute mode")
    for field in (
        "dispatch_item_count",
        "ready_dispatch_item_count",
        "blocked_dispatch_item_count",
        "command_count",
        "diagnostic_command_count",
        "executed_command_count",
        "failed_command_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"dispatch run {field} must be a non-negative integer")
    for field in (
        "dispatch_gate_path",
        "dispatch_gate_schema_version",
        "dispatch_gate_fingerprint_sha256",
        "dispatch_run_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str):
            errors.append(f"dispatch run {field} must be a string")
    for field in (
        "dispatch_gate_sha256",
        "dispatch_gate_fingerprint_sha256",
        "dispatch_run_fingerprint_sha256",
    ):
        value = payload.get(field)
        if value and not _is_fingerprint(value):
            errors.append(f"dispatch run {field} must be a SHA-256 hex string")
    if payload.get("dispatch_gate_schema_version") and (
        payload.get("dispatch_gate_schema_version") != DISPATCH_GATE_SCHEMA_VERSION
    ):
        errors.append(
            f"dispatch run dispatch_gate_schema_version must be {DISPATCH_GATE_SCHEMA_VERSION!r}"
        )
    for field in ("errors", "error_codes"):
        if not _is_string_list(payload.get(field)):
            errors.append(f"dispatch run {field} must be a string list")
    command_errors, commands = _command_errors(payload.get("commands"))
    errors.extend(command_errors)
    diagnostic_errors, diagnostic_commands = _diagnostic_command_errors(
        payload.get("diagnostic_commands")
    )
    errors.extend(diagnostic_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not command_errors and not diagnostic_errors:
        errors.extend(_summary_errors(payload, commands, diagnostic_commands))
    return errors


def _command_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    commands: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["dispatch run commands must be a list"], commands
    for command in value:
        if not isinstance(command, dict):
            errors.append("dispatch run command entries must be objects")
            continue
        commands.append(command)
        if set(command) != COMMAND_FIELDS:
            errors.append("dispatch run command fields must match contract")
        for field in ("requirement_id", "command_name", "working_directory"):
            if not isinstance(command.get(field), str) or not command.get(field):
                errors.append(f"dispatch run command {field} must be a non-empty string")
        if command.get("command_name") not in UNLOCKED_LIVE_COMMAND_SPEC_FIELDS:
            errors.append("dispatch run command_name must be allowlisted")
        argv = command.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append("dispatch run command argv must be a non-empty string list")
        else:
            errors.extend(_argv_shell_control_errors(argv))
            if command.get("command_name") == "workflow_dispatch" and argv[:3] != [
                "gh",
                "workflow",
                "run",
            ]:
                errors.append("dispatch run workflow_dispatch must use gh workflow run")
            if (
                command.get("command_name") == "local_live_probe"
                and argv[0] not in {"python", "python3"}
            ):
                errors.append("dispatch run local_live_probe must use python")
        if command.get("uses_shell") is not False:
            errors.append("dispatch run command uses_shell must be false")
        if not isinstance(command.get("executed"), bool):
            errors.append("dispatch run command executed must be a boolean")
        if not _is_int(command.get("returncode")):
            errors.append("dispatch run command returncode must be an integer")
        elif command.get("executed") is False and command.get("returncode") != -1:
            errors.append("dispatch run unexecuted command returncode must be -1")
        for field in ("stdout_included", "stderr_included"):
            if command.get(field) is not False:
                errors.append(f"dispatch run command {field} must be false")
    return errors, commands


def _diagnostic_command_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    commands: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["dispatch run diagnostic_commands must be a list"], commands
    for command in value:
        if not isinstance(command, dict):
            errors.append("dispatch run diagnostic command entries must be objects")
            continue
        commands.append(command)
        if set(command) != COMMAND_FIELDS:
            errors.append("dispatch run diagnostic command fields must match contract")
        for field in ("requirement_id", "command_name", "working_directory"):
            if not isinstance(command.get(field), str) or not command.get(field):
                errors.append(
                    f"dispatch run diagnostic command {field} must be a non-empty string"
                )
        if command.get("command_name") not in BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS:
            errors.append("dispatch run diagnostic command_name must be allowlisted")
        argv = command.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append(
                "dispatch run diagnostic command argv must be a non-empty string list"
            )
        else:
            errors.extend(_argv_shell_control_errors(argv))
            if command.get("command_name") == "local_failure_from_preflight":
                if argv[0] not in {"python", "python3"}:
                    errors.append(
                        "dispatch run local_failure_from_preflight must use python"
                    )
                if "--failure-from-preflight" not in argv:
                    errors.append(
                        "dispatch run local_failure_from_preflight must use failure-from-preflight"
                    )
                if not _argv_option_value(argv, "--failure-preflight-json"):
                    errors.append(
                        "dispatch run local_failure_from_preflight must bind failure preflight JSON"
                    )
                if not _argv_option_value(argv, "--out"):
                    errors.append(
                        "dispatch run local_failure_from_preflight must write --out"
                    )
        if command.get("working_directory") != "maritime-ai-service":
            errors.append(
                "dispatch run diagnostic command working_directory must be maritime-ai-service"
            )
        if command.get("uses_shell") is not False:
            errors.append("dispatch run diagnostic command uses_shell must be false")
        if command.get("executed") is not False:
            errors.append("dispatch run diagnostic commands must not execute")
        if command.get("returncode") != -1:
            errors.append("dispatch run diagnostic command returncode must be -1")
        for field in ("stdout_included", "stderr_included"):
            if command.get(field) is not False:
                errors.append(f"dispatch run diagnostic command {field} must be false")
    return errors, commands


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["dispatch run privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("dispatch run privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"dispatch run privacy.{field} must be false")
    return errors


def _summary_errors(
    payload: dict[str, Any],
    commands: list[dict[str, Any]],
    diagnostic_commands: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    executed_count = sum(1 for command in commands if command.get("executed") is True)
    failed_count = sum(
        1
        for command in commands
        if isinstance(command.get("returncode"), int)
        and command.get("returncode") not in {-1, 0}
    )
    if payload.get("command_count") != len(commands):
        errors.append("dispatch run command_count must match commands")
    if payload.get("diagnostic_command_count") != len(diagnostic_commands):
        errors.append(
            "dispatch run diagnostic_command_count must match diagnostic_commands"
        )
    if payload.get("executed_command_count") != executed_count:
        errors.append("dispatch run executed_command_count must match commands")
    if payload.get("failed_command_count") != failed_count:
        errors.append("dispatch run failed_command_count must match commands")
    if payload.get("dispatch_ready") is not True and commands:
        errors.append("dispatch run pending gates must not materialize commands")
    if payload.get("dispatch_ready") is True and diagnostic_commands:
        errors.append("dispatch run ready gates must not carry diagnostic commands")
    if payload.get("dry_run") is True and executed_count:
        errors.append("dispatch run dry_run reports must not execute commands")
    if payload.get("ok") != (not payload.get("errors")):
        errors.append("dispatch run ok must match errors")
    errors_list = payload.get("errors")
    if _is_string_list(errors_list) and payload.get("dispatch_run_fingerprint_sha256") != (
        _dispatch_run_fingerprint(commands, errors_list, diagnostic_commands)
    ):
        errors.append("dispatch run dispatch_run_fingerprint_sha256 must match commands and errors")
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    dispatch_gate_path: Path | None,
    launch_pack_path: Path | None,
    setup_state_path: Path | None,
    repo_root: Path,
) -> list[str]:
    if dispatch_gate_path is None or launch_pack_path is None or setup_state_path is None:
        return [
            "completion audit dispatch run source mismatch: "
            "--dispatch-gate, --launch-pack, and --setup-state are required together"
        ]
    gate_validation = gate_validator.validate_dispatch_gate(
        dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
    )
    if not gate_validation.ok:
        return [
            "completion audit dispatch run source mismatch: dispatch gate failed validation: "
            + "; ".join(gate_validation.errors)
        ]
    gate_payload = load_strict_json_file(dispatch_gate_path)
    if not isinstance(gate_payload, dict):
        return ["completion audit dispatch run source mismatch: dispatch gate root invalid"]
    errors: list[str] = []
    expected_fields = {
        "dispatch_gate_path": str(dispatch_gate_path),
        "dispatch_gate_sha256": _sha256_file(dispatch_gate_path),
        "dispatch_gate_schema_version": gate_payload.get("schema_version"),
        "dispatch_gate_fingerprint_sha256": gate_payload.get(
            "dispatch_gate_fingerprint_sha256"
        ),
        "dispatch_ready": gate_payload.get("dispatch_ready"),
        "dispatch_item_count": gate_payload.get("dispatch_item_count"),
        "ready_dispatch_item_count": gate_payload.get("ready_dispatch_item_count"),
        "blocked_dispatch_item_count": gate_payload.get("blocked_dispatch_item_count"),
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            errors.append(
                f"completion audit dispatch run source mismatch: {field} must match source"
            )
    if payload.get("dry_run") is True and payload.get("allow_live_dispatch") is False:
        expected_run = run_completion_audit_dispatch_gate(
            dispatch_gate_path,
            launch_pack_path=launch_pack_path,
            setup_state_path=setup_state_path,
            repo_root=repo_root,
        ).to_dict()
        for field in (
            "ok",
            "mode",
            "dry_run",
            "allow_live_dispatch",
            "command_count",
            "diagnostic_command_count",
            "executed_command_count",
            "failed_command_count",
            "dispatch_run_fingerprint_sha256",
            "commands",
            "diagnostic_commands",
            "errors",
            "error_codes",
            "error_code_counts",
        ):
            if payload.get(field) != expected_run.get(field):
                errors.append(
                    f"completion audit dispatch run source mismatch: {field} must match generated dry-run"
                )
                break
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return []
    expected_codes = dispatch_run_error_codes(errors)
    expected_counts = dispatch_run_error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes) and error_codes != expected_codes:
        result.append("dispatch run error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("dispatch run error_code_counts must match errors")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit dispatch-run report.",
    )
    parser.add_argument("dispatch_run", type=Path)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_dispatch_run(
        args.dispatch_run,
        dispatch_gate_path=args.dispatch_gate,
        launch_pack_path=args.launch_pack,
        setup_state_path=args.setup_state,
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
        print("Wiii Completion Audit Dispatch Run Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Dispatch Run Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _argv_shell_control_errors(argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for arg in argv:
        if any(token in arg for token in shell_control_tokens):
            return [
                "dispatch run command argv must not contain shell control operator tokens"
            ]
    return []


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
    if error == "completion audit dispatch run path must be a regular file":
        return "completion_audit_dispatch_run_path_invalid"
    if error.startswith("completion audit dispatch run JSON is invalid"):
        return "completion_audit_dispatch_run_json_invalid"
    if error == "completion audit dispatch run root must be an object":
        return "completion_audit_dispatch_run_root_invalid"
    if "source mismatch" in error:
        return "completion_audit_dispatch_run_source_mismatch"
    if error.startswith("dispatch run missing required field"):
        return "completion_audit_dispatch_run_missing_required_fields"
    if error.startswith("dispatch run has unsupported field"):
        return "completion_audit_dispatch_run_unsupported_fields"
    if error.startswith("dispatch run schema_version must be"):
        return "completion_audit_dispatch_run_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_dispatch_run_fingerprint_invalid"
    if "privacy" in error or "raw_" in error or "stdout" in error or "stderr" in error:
        return "completion_audit_dispatch_run_privacy_invalid"
    if "command" in error or "argv" in error or "shell" in error:
        return "completion_audit_dispatch_run_command_invalid"
    if "mode" in error or "dry_run" in error or "allow_live_dispatch" in error:
        return "completion_audit_dispatch_run_mode_invalid"
    if "count" in error:
        return "completion_audit_dispatch_run_count_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_dispatch_run_error_summary_invalid"
    if "boolean" in error:
        return "completion_audit_dispatch_run_boolean_invalid"
    return "completion_audit_dispatch_run_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
