#!/usr/bin/env python3
"""Generate a source-bound recovery resume checkpoint from a control chain."""

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
import validate_completion_audit_recovery_control_chain as control_chain_validator  # noqa: E402


RECOVERY_CHECKPOINT_SCHEMA_VERSION = "wiii.completion_audit_recovery_checkpoint.v1"
RECOVERY_CHECKPOINT_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery checkpoint output path must not be a directory"
)
RECOVERY_CHECKPOINT_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery checkpoint output path must not be a symlink"
)
RECOVERY_CHECKPOINT_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery checkpoint output path parent must not be a symlink"
)

STATE_FIELDS = (
    "chain_state",
    "recovery_chain_ready",
    "release_gate_ready",
    "operator_setup_required",
    "autonomous_dispatch_allowed",
    "queue_state",
    "work_order_state",
    "status_state",
    "authorization_state",
    "dispatch_run_state",
    "next_group_ids",
    "completed_group_ids",
    "pending_group_ids",
    "authorized_group_ids",
    "blocked_group_ids",
    "command_count",
    "chain_fingerprint_sha256",
)


@dataclass(frozen=True)
class RecoveryCheckpointReport:
    schema_version: str
    ok: bool
    recovery_control_chain_path: str
    recovery_control_chain_sha256: str
    recovery_control_chain_validation_schema_version: str
    chain_fingerprint_sha256: str
    chain_state: str
    resume_state: str
    release_gate_ready: bool
    recovery_chain_ready: bool
    operator_setup_required: bool
    autonomous_dispatch_allowed: bool
    queue_state: str
    work_order_state: str
    status_state: str
    authorization_state: str
    dispatch_run_state: str
    next_group_ids: list[str]
    completed_group_ids: list[str]
    pending_group_ids: list[str]
    authorized_group_ids: list[str]
    blocked_group_ids: list[str]
    command_count: int
    required_resume_inputs: list[str]
    resume_checkpoint_fingerprint_sha256: str
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_recovery_checkpoint(
    recovery_control_chain_path: Path,
    *,
    repo_root: Path = Path("."),
) -> RecoveryCheckpointReport:
    errors: list[str] = []
    payload: dict[str, Any] = {}
    replay_payload: dict[str, Any] = {}
    try:
        loaded = load_strict_json_file(recovery_control_chain_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery checkpoint control chain invalid: {exc}")
    else:
        if isinstance(loaded, dict):
            payload = loaded
        else:
            errors.append("completion audit recovery checkpoint control chain root invalid")
    if payload:
        errors.extend(_control_chain_payload_errors(payload))
        replay = _replay_control_chain(payload, repo_root=repo_root)
        replay_payload = replay.to_dict()
        if not replay.ok:
            errors.append(
                "completion audit recovery checkpoint control chain replay failed: "
                + "; ".join(replay.errors)
            )
        errors.extend(_replay_parity_errors(payload, replay_payload))
    return _report(
        recovery_control_chain_path,
        control_chain_payload=payload,
        replay_payload=replay_payload,
        errors=errors,
    )


def _report(
    recovery_control_chain_path: Path,
    *,
    control_chain_payload: dict[str, Any],
    replay_payload: dict[str, Any],
    errors: list[str],
) -> RecoveryCheckpointReport:
    state_source = replay_payload if replay_payload else control_chain_payload
    ok = not errors
    chain_state = _string(state_source.get("chain_state"))
    resume_state = _resume_state(state_source, errors=errors)
    required_resume_inputs = _required_resume_inputs(resume_state)
    chain_fingerprint = _string(state_source.get("chain_fingerprint_sha256"))
    checkpoint_fingerprint = _checkpoint_fingerprint(
        recovery_control_chain_sha256=_sha256_file(recovery_control_chain_path),
        chain_fingerprint_sha256=chain_fingerprint,
        chain_state=chain_state,
        resume_state=resume_state,
        next_group_ids=_string_list(state_source.get("next_group_ids")),
        completed_group_ids=_string_list(state_source.get("completed_group_ids")),
        pending_group_ids=_string_list(state_source.get("pending_group_ids")),
        authorized_group_ids=_string_list(state_source.get("authorized_group_ids")),
        blocked_group_ids=_string_list(state_source.get("blocked_group_ids")),
        command_count=_int(state_source.get("command_count")),
        required_resume_inputs=required_resume_inputs,
    )
    return RecoveryCheckpointReport(
        schema_version=RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        ok=ok,
        recovery_control_chain_path=str(recovery_control_chain_path),
        recovery_control_chain_sha256=_sha256_file(recovery_control_chain_path),
        recovery_control_chain_validation_schema_version=_string(
            control_chain_payload.get("validation_schema_version")
        ),
        chain_fingerprint_sha256=chain_fingerprint,
        chain_state=chain_state,
        resume_state=resume_state,
        release_gate_ready=state_source.get("release_gate_ready") is True,
        recovery_chain_ready=state_source.get("recovery_chain_ready") is True,
        operator_setup_required=state_source.get("operator_setup_required") is True,
        autonomous_dispatch_allowed=(
            state_source.get("autonomous_dispatch_allowed") is True
        ),
        queue_state=_string(state_source.get("queue_state")),
        work_order_state=_string(state_source.get("work_order_state")),
        status_state=_string(state_source.get("status_state")),
        authorization_state=_string(state_source.get("authorization_state")),
        dispatch_run_state=_string(state_source.get("dispatch_run_state")),
        next_group_ids=_string_list(state_source.get("next_group_ids")),
        completed_group_ids=_string_list(state_source.get("completed_group_ids")),
        pending_group_ids=_string_list(state_source.get("pending_group_ids")),
        authorized_group_ids=_string_list(state_source.get("authorized_group_ids")),
        blocked_group_ids=_string_list(state_source.get("blocked_group_ids")),
        command_count=_int(state_source.get("command_count")),
        required_resume_inputs=required_resume_inputs,
        resume_checkpoint_fingerprint_sha256=checkpoint_fingerprint,
        privacy={
            "raw_output_included": False,
            "raw_evidence_payload_included": False,
            "secret_values_included": False,
        },
        errors=errors,
    )


def _control_chain_payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if (
        payload.get("validation_schema_version")
        != control_chain_validator.RECOVERY_CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION
    ):
        errors.append(
            "completion audit recovery checkpoint control chain schema version invalid"
        )
    if payload.get("ok") is not True:
        errors.append("completion audit recovery checkpoint control chain must be ok")
    for field in STATE_FIELDS:
        if field not in payload:
            errors.append(
                f"completion audit recovery checkpoint control chain missing {field}"
            )
    return errors


def _replay_control_chain(
    payload: dict[str, Any],
    *,
    repo_root: Path,
) -> control_chain_validator.RecoveryControlChainValidationResult:
    return control_chain_validator.validate_recovery_control_chain(
        recovery_plan_path=Path(_string(payload.get("recovery_plan_path"))),
        recovery_queue_path=Path(_string(payload.get("recovery_queue_path"))),
        recovery_work_order_path=Path(_string(payload.get("recovery_work_order_path"))),
        recovery_work_order_status_path=Path(
            _string(payload.get("recovery_work_order_status_path"))
        ),
        recovery_queue_progress_path=Path(
            _string(payload.get("recovery_queue_progress_path"))
        ),
        recovery_dispatch_authorization_path=Path(
            _string(payload.get("recovery_dispatch_authorization_path"))
        ),
        recovery_dispatch_run_path=Path(
            _string(payload.get("recovery_dispatch_run_path"))
        ),
        handoff_json_path=_optional_path(payload.get("handoff_json_path")),
        setup_state_path=_optional_path(payload.get("setup_state_path")),
        dispatch_gate_path=_optional_path(payload.get("dispatch_gate_path")),
        launch_pack_path=_optional_path(payload.get("launch_pack_path")),
        repo_root=repo_root,
    )


def _replay_parity_errors(
    payload: dict[str, Any],
    replay_payload: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not replay_payload:
        return errors
    for field in STATE_FIELDS:
        if payload.get(field) != replay_payload.get(field):
            errors.append(
                f"completion audit recovery checkpoint control chain {field} must match replay"
            )
    return errors


def _resume_state(payload: dict[str, Any], *, errors: list[str]) -> str:
    if errors:
        return "invalid"
    if payload.get("release_gate_ready") is True:
        return "release_ready"
    if payload.get("operator_setup_required") is True:
        return "collect_operator_setup"
    if payload.get("chain_state") == "ready_for_recovery_dispatch":
        return "dispatch_recovery"
    if payload.get("chain_state") == "recovery_dispatch_executed":
        return "refresh_completion_audit"
    if payload.get("chain_state") == "blocked_by_missing_live_command_specs":
        return "blocked_missing_live_command_specs"
    if payload.get("chain_state") == "blocked_by_authorization":
        return "blocked_by_authorization"
    return "blocked"


def _required_resume_inputs(resume_state: str) -> list[str]:
    inputs_by_state = {
        "collect_operator_setup": [
            "setup_attestation",
            "attested_setup_state",
            "attested_dispatch_gate",
            "recovery_control_chain_replay",
        ],
        "dispatch_recovery": [
            "operator_dispatch_approval",
            "live_command_specs",
            "recovery_dispatch_run",
        ],
        "refresh_completion_audit": [
            "runtime_evidence_bundle_refresh",
            "completion_audit_control_chain_validation",
        ],
        "blocked_missing_live_command_specs": [
            "live_command_specs",
            "recovery_dispatch_authorization",
        ],
        "blocked_by_authorization": [
            "dispatch_gate_unlock",
            "recovery_dispatch_authorization",
        ],
        "blocked": ["recovery_control_chain_replay"],
        "invalid": ["valid_recovery_control_chain"],
        "release_ready": [],
    }
    return inputs_by_state[resume_state]


def _checkpoint_fingerprint(
    *,
    recovery_control_chain_sha256: str,
    chain_fingerprint_sha256: str,
    chain_state: str,
    resume_state: str,
    next_group_ids: list[str],
    completed_group_ids: list[str],
    pending_group_ids: list[str],
    authorized_group_ids: list[str],
    blocked_group_ids: list[str],
    command_count: int,
    required_resume_inputs: list[str],
) -> str:
    encoded = json.dumps(
        {
            "chain_fingerprint_sha256": chain_fingerprint_sha256,
            "chain_state": chain_state,
            "command_count": command_count,
            "completed_group_ids": completed_group_ids,
            "authorized_group_ids": authorized_group_ids,
            "blocked_group_ids": blocked_group_ids,
            "next_group_ids": next_group_ids,
            "pending_group_ids": pending_group_ids,
            "recovery_control_chain_sha256": recovery_control_chain_sha256,
            "required_resume_inputs": required_resume_inputs,
            "resume_state": resume_state,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(RECOVERY_CHECKPOINT_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(RECOVERY_CHECKPOINT_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(RECOVERY_CHECKPOINT_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _sha256_file(path: Path | None) -> str:
    if path is None or not path.is_file() or path.is_symlink():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _optional_path(value: Any) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


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
    if "output path must not be a directory" in error:
        return "completion_audit_recovery_checkpoint_output_path_directory"
    if "output path must not be a symlink" in error:
        return "completion_audit_recovery_checkpoint_output_path_symlink"
    if "output path parent must not be a symlink" in error:
        return "completion_audit_recovery_checkpoint_output_path_parent_symlink"
    if "replay failed" in error:
        return "completion_audit_recovery_checkpoint_source_invalid"
    if "must match replay" in error:
        return "completion_audit_recovery_checkpoint_source_mismatch"
    if "schema version invalid" in error:
        return "completion_audit_recovery_checkpoint_schema_invalid"
    if "must be ok" in error:
        return "completion_audit_recovery_checkpoint_source_not_ok"
    if "missing" in error:
        return "completion_audit_recovery_checkpoint_source_incomplete"
    if "invalid" in error:
        return "completion_audit_recovery_checkpoint_source_invalid"
    return "completion_audit_recovery_checkpoint_error"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a source-bound completion-audit recovery checkpoint.",
    )
    parser.add_argument("recovery_control_chain", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        result = generate_completion_audit_recovery_checkpoint(
            args.recovery_control_chain,
            repo_root=args.repo_root,
        )
        if args.json or args.out:
            text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        elif result.ok:
            text = "Wiii Completion Audit Recovery Checkpoint: PASS\n"
        else:
            text = (
                "Wiii Completion Audit Recovery Checkpoint: FAIL\n"
                + "\n".join(f"- {error}" for error in result.errors)
                + "\n"
            )
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 0 if result.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="" if args.json else "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
