#!/usr/bin/env python3
"""Generate a privacy-safe live setup state from a completion-audit launch pack."""

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

from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_launch_pack as launch_validator  # noqa: E402


SETUP_STATE_SCHEMA_VERSION = "wiii.completion_audit_setup_state.v1"
SETUP_STATE_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup state output path must not be a directory"
)
SETUP_STATE_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup state output path must not be a symlink"
)
SETUP_STATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup state output path parent must not be a symlink"
)
SETUP_STATE_LAUNCH_PACK_VALIDATION_ERROR = (
    "completion audit launch pack failed validation"
)
SETUP_BINDING_FIELDS = (
    "workflow_inputs_required",
    "environment_flags_required",
    "credential_slots_required",
    "external_setup_required",
)


@dataclass(frozen=True)
class SetupCheck:
    category: str
    key: str
    binding_tokens: list[str]
    present: bool
    source_handle: str
    secret_value_included: bool
    raw_identifier_included: bool


@dataclass(frozen=True)
class SetupRequirement:
    requirement_id: str
    title: str
    workflow: str
    probe: str
    expected_artifact: str
    setup_contract_version: str
    setup_status: str
    dispatch_ready: bool
    setup_checks: list[SetupCheck]


@dataclass(frozen=True)
class CompletionAuditSetupState:
    schema_version: str
    ok: bool
    launch_pack_path: str
    launch_pack_sha256: str
    launch_pack_schema_version: str
    launch_items_fingerprint_sha256: str
    launch_setup_fingerprint_sha256: str
    setup_state_fingerprint_sha256: str
    dispatch_ready: bool
    requirement_count: int
    ready_requirement_count: int
    blocked_requirement_count: int
    requirements: list[SetupRequirement]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_setup_state(
    launch_pack_path: Path,
    *,
    repo_root: Path | None = None,
) -> CompletionAuditSetupState:
    validation = launch_validator.validate_launch_pack(launch_pack_path)
    if not validation.ok:
        raise ValueError(
            SETUP_STATE_LAUNCH_PACK_VALIDATION_ERROR
            + ": "
            + "; ".join(validation.errors)
        )
    payload = load_strict_json_file(launch_pack_path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit launch pack root must be an object")

    requirements = [
        _setup_requirement(item, repo_root=repo_root)
        for item in payload.get("launch_items", [])
        if isinstance(item, dict)
    ]
    ready_count = sum(1 for item in requirements if item.dispatch_ready)
    errors: list[str] = []
    return CompletionAuditSetupState(
        schema_version=SETUP_STATE_SCHEMA_VERSION,
        ok=True,
        launch_pack_path=str(launch_pack_path),
        launch_pack_sha256=_sha256_file(launch_pack_path),
        launch_pack_schema_version=str(payload.get("schema_version") or ""),
        launch_items_fingerprint_sha256=str(
            payload.get("launch_items_fingerprint_sha256") or ""
        ),
        launch_setup_fingerprint_sha256=str(
            payload.get("launch_setup_fingerprint_sha256") or ""
        ),
        setup_state_fingerprint_sha256=_setup_state_fingerprint(
            [asdict(item) for item in requirements]
        ),
        dispatch_ready=ready_count == len(requirements) and bool(requirements),
        requirement_count=len(requirements),
        ready_requirement_count=ready_count,
        blocked_requirement_count=len(requirements) - ready_count,
        requirements=requirements,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def _setup_requirement(
    item: dict[str, Any],
    *,
    repo_root: Path | None,
) -> SetupRequirement:
    checks = _setup_checks(
        item.get("preflight_setup_contract_bindings"),
        launch_item=item,
        repo_root=repo_root,
    )
    dispatch_ready = bool(checks) and all(check.present for check in checks)
    return SetupRequirement(
        requirement_id=_string(item.get("requirement_id")),
        title=_string(item.get("title")),
        workflow=_string(item.get("workflow")),
        probe=_string(item.get("probe")),
        expected_artifact=_string(item.get("expected_artifact")),
        setup_contract_version=_string(
            _dict_field(item.get("preflight_setup_contract")).get("version")
        ),
        setup_status="ready" if dispatch_ready else "pending",
        dispatch_ready=dispatch_ready,
        setup_checks=checks,
    )


def _setup_checks(
    value: Any,
    *,
    launch_item: dict[str, Any],
    repo_root: Path | None,
) -> list[SetupCheck]:
    bindings = value if isinstance(value, dict) else {}
    checks: list[SetupCheck] = []
    for category in SETUP_BINDING_FIELDS:
        group = bindings.get(category)
        if not isinstance(group, dict):
            continue
        for key in sorted(group):
            tokens = _string_list(group.get(key))
            source_handle = _repo_proven_source_handle(
                category,
                tokens,
                launch_item=launch_item,
                repo_root=repo_root,
            )
            checks.append(
                SetupCheck(
                    category=category,
                    key=str(key),
                    binding_tokens=tokens,
                    present=bool(source_handle),
                    source_handle=source_handle,
                    secret_value_included=False,
                    raw_identifier_included=False,
                )
            )
    return checks


def _repo_proven_source_handle(
    category: str,
    tokens: list[str],
    *,
    launch_item: dict[str, Any],
    repo_root: Path | None,
) -> str:
    if repo_root is None:
        return ""
    if category == "workflow_inputs_required":
        return _first_command_proven_handle(tokens, launch_item)
    return ""


def _first_command_proven_handle(
    tokens: list[str],
    launch_item: dict[str, Any],
) -> str:
    argvs = _command_argvs(launch_item)
    for token in tokens:
        if any(_token_is_present_in_argv(token, argv) for argv in argvs):
            return token
    return ""


def _command_argvs(launch_item: dict[str, Any]) -> list[list[str]]:
    command_specs = _dict_field(launch_item.get("command_specs"))
    argvs: list[list[str]] = []
    for name in ("workflow_dispatch", "local_preflight", "local_live_probe"):
        spec = _dict_field(command_specs.get(name))
        argv = _string_list(spec.get("argv"))
        if argv:
            argvs.append(argv)
    return argvs


def _token_is_present_in_argv(token: str, argv: list[str]) -> bool:
    if not token:
        return False
    if token.startswith("--"):
        return token in argv
    return any(arg == token or arg.startswith(f"{token}=") for arg in argv)


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(SETUP_STATE_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(SETUP_STATE_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(SETUP_STATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a privacy-safe setup-state template from a validated "
            "completion-audit launch pack."
        ),
    )
    parser.add_argument("launch_pack", type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Optional repository root used to mark workflow-input handles "
            "proven by source-controlled launch contracts."
        ),
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        state = generate_completion_audit_setup_state(
            args.launch_pack,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(state.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_STATE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error.startswith(SETUP_STATE_LAUNCH_PACK_VALIDATION_ERROR):
        return "completion_audit_setup_state_launch_pack_invalid"
    if error == SETUP_STATE_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_state_output_path_directory"
    if error == SETUP_STATE_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_state_output_path_symlink"
    if error == SETUP_STATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_state_output_path_parent_symlink"
    return "completion_audit_setup_state_generation_failed"


def _setup_state_fingerprint(requirements: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        requirements,
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


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dict_field(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
