#!/usr/bin/env python3
"""Generate a source-bound recovery plan from a completion-audit handoff."""

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

from generate_completion_audit_handoff import (  # noqa: E402
    COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION,
)
from strict_json import load_strict_json_file  # noqa: E402


RECOVERY_PLAN_SCHEMA_VERSION = "wiii.completion_audit_recovery_plan.v1"
RECOVERY_PLAN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery plan output path must not be a directory"
)
RECOVERY_PLAN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery plan output path must not be a symlink"
)
RECOVERY_PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery plan output path parent must not be a symlink"
)

ACTION_ITEM_FIELDS = {
    "item_id",
    "kind",
    "action_type",
    "requirement_id",
    "blocker_id",
    "artifact",
    "status",
    "error_codes",
    "workflow",
    "probe",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gate_tokens",
    "artifact_tokens",
    "preflight_required_next",
    "setup_category",
    "setup_key",
    "setup_evidence_kind",
    "source_handle_options",
    "binding_token_count",
    "attestation_option_count",
    "pending_setup_check_count",
    "diagnostic_pending_setup_keys",
    "non_diagnostic_pending_setup_keys",
    "gate_reason",
}
EXECUTION_GROUP_FIELDS = {
    "group_id",
    "title",
    "execution_mode",
    "item_ids",
    "depends_on_group_ids",
    "blocked_by_external_setup",
    "ready_for_autonomous_dispatch",
}


@dataclass(frozen=True)
class CompletionAuditRecoveryPlan:
    schema_version: str
    ok: bool
    handoff_path: str
    handoff_sha256: str
    handoff_schema_version: str
    completion_audit_ready: bool
    release_handoff_ready: bool
    release_blocker_count: int
    action_item_count: int
    runtime_recovery_action_count: int
    setup_resolution_action_count: int
    gate_dependency_count: int
    action_items_fingerprint_sha256: str
    action_items: list[dict[str, Any]]
    execution_group_count: int
    execution_groups_fingerprint_sha256: str
    execution_groups: list[dict[str, Any]]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_recovery_plan(
    handoff_json_path: Path,
) -> CompletionAuditRecoveryPlan:
    payload = _load_handoff_payload(handoff_json_path)
    release_blockers = payload.get("release_blockers")
    errors: list[str] = []
    if not isinstance(release_blockers, list):
        release_blockers = []
        errors.append("completion audit recovery plan source release_blockers invalid")
    release_blocker_count = payload.get("release_blocker_count")
    if (
        not isinstance(release_blocker_count, int)
        or isinstance(release_blocker_count, bool)
        or release_blocker_count != len(release_blockers)
    ):
        errors.append(
            "completion audit recovery plan source release_blocker_count mismatch"
        )
    action_items, action_errors = _action_items_from_release_blockers(
        release_blockers
    )
    execution_groups = _execution_groups(action_items)
    errors.extend(action_errors)
    return CompletionAuditRecoveryPlan(
        schema_version=RECOVERY_PLAN_SCHEMA_VERSION,
        ok=not errors,
        handoff_path=str(handoff_json_path),
        handoff_sha256=_sha256_file(handoff_json_path),
        handoff_schema_version=str(payload.get("schema_version") or ""),
        completion_audit_ready=payload.get("completion_audit_ready") is True,
        release_handoff_ready=payload.get("release_handoff_ready") is True,
        release_blocker_count=len(release_blockers),
        action_item_count=len(action_items),
        runtime_recovery_action_count=sum(
            1 for item in action_items if item["action_type"] == "workflow_probe_recovery"
        ),
        setup_resolution_action_count=sum(
            1 for item in action_items if item["action_type"] == "setup_resolution"
        ),
        gate_dependency_count=sum(
            1 for item in action_items if item["action_type"] == "gate_dependency"
        ),
        action_items_fingerprint_sha256=_action_items_fingerprint(action_items),
        action_items=action_items,
        execution_group_count=len(execution_groups),
        execution_groups_fingerprint_sha256=_execution_groups_fingerprint(
            execution_groups
        ),
        execution_groups=execution_groups,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def format_markdown(plan: CompletionAuditRecoveryPlan) -> str:
    lines = [
        "# Wiii Completion Audit Recovery Plan",
        "",
        f"- Schema version: `{plan.schema_version}`",
        f"- Status: `{'PASS' if plan.ok else 'FAIL'}`",
        f"- Handoff report: `{plan.handoff_path}`",
        f"- Handoff report SHA-256: `{plan.handoff_sha256}`",
        f"- Completion audit ready: `{str(plan.completion_audit_ready).lower()}`",
        f"- Release handoff ready: `{str(plan.release_handoff_ready).lower()}`",
        f"- Release blockers: `{plan.release_blocker_count}`",
        f"- Action items: `{plan.action_item_count}`",
        f"- Runtime recovery actions: `{plan.runtime_recovery_action_count}`",
        f"- Setup resolution actions: `{plan.setup_resolution_action_count}`",
        f"- Gate dependencies: `{plan.gate_dependency_count}`",
        "- Action items fingerprint SHA-256: "
        f"`{plan.action_items_fingerprint_sha256}`",
        f"- Execution groups: `{plan.execution_group_count}`",
        "- Execution groups fingerprint SHA-256: "
        f"`{plan.execution_groups_fingerprint_sha256}`",
        "",
        "## Execution Groups",
        "",
        "| Group | Mode | Items | Depends on | Autonomous dispatch |",
        "|---|---|---:|---|---|",
    ]
    for group in plan.execution_groups:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(group["group_id"]),
                    _cell(group["execution_mode"]),
                    _cell(len(group["item_ids"])),
                    _cell(", ".join(group["depends_on_group_ids"]) or "-"),
                    _cell(str(group["ready_for_autonomous_dispatch"]).lower()),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Action Items",
            "",
            "| Item | Action | Requirement | Workflow/probe | Setup handle | Status |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in plan.action_items:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(item["item_id"]),
                    _cell(item["action_type"]),
                    _cell(item["requirement_id"] or item["blocker_id"] or "-"),
                    _cell(_workflow_probe_cell(item)),
                    _cell(_setup_cell(item)),
                    _cell(item["status"]),
                ]
            )
            + " |"
        )
    if plan.errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{error}`" for error in plan.errors)
    return "\n".join(lines)


def _load_handoff_payload(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("completion audit handoff JSON path must be a regular file")
    payload = load_strict_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit handoff JSON root must be an object")
    if payload.get("schema_version") != COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION:
        raise ValueError("completion audit handoff schema_version mismatch")
    return payload


def _action_items_from_release_blockers(
    release_blockers: list[Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for blocker in release_blockers:
        if not isinstance(blocker, dict):
            errors.append("completion audit recovery plan release_blocker invalid")
            continue
        kind = str(blocker.get("kind") or "")
        if kind == "runtime_evidence":
            item, error = _runtime_recovery_item(blocker)
            items.append(item)
            if error:
                errors.append(error)
            continue
        if kind == "setup_gap":
            setup_items, setup_errors = _setup_resolution_items(blocker)
            items.extend(setup_items)
            errors.extend(setup_errors)
            continue
        if kind in {"control_chain", "runtime_readiness", "setup_gap_summary"}:
            items.append(_gate_dependency_item(blocker))
    return items, errors


def _runtime_recovery_item(blocker: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    requirement_id = _string(blocker.get("requirement_id"))
    recovery = blocker.get("recovery_action")
    item = _base_item(
        item_id=f"runtime:{requirement_id or '-'}",
        kind="runtime_evidence",
        action_type="workflow_probe_recovery",
        requirement_id=requirement_id,
        artifact=_string(blocker.get("artifact")),
        status=_string(blocker.get("status")),
        error_codes=_string_list(blocker.get("error_codes")),
    )
    if not isinstance(recovery, dict):
        item["action_type"] = "missing_recovery_action"
        return (
            item,
            "completion audit recovery plan runtime blocker missing recovery_action",
        )
    for field in (
        "workflow",
        "probe",
        "live_env_flags",
        "live_guard_tokens",
        "dispatch_or_schedule_gate_tokens",
        "artifact_tokens",
        "preflight_required_next",
    ):
        if field in {
            "workflow",
            "probe",
        }:
            item[field] = _string(recovery.get(field))
        else:
            item[field] = _string_list(recovery.get(field))
    return item, None


def _setup_resolution_items(blocker: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    requirement_id = _string(blocker.get("requirement_id"))
    actions = blocker.get("resolution_actions")
    if not isinstance(actions, list):
        return [], ["completion audit recovery plan setup_gap resolution_actions invalid"]
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            errors.append("completion audit recovery plan setup resolution action invalid")
            continue
        category = _string(action.get("category"))
        key = _string(action.get("key"))
        items.append(
            _base_item(
                item_id=f"setup:{requirement_id or '-'}:{category or '-'}:{key or '-'}",
                kind="setup_gap",
                action_type="setup_resolution",
                requirement_id=requirement_id,
                status="pending",
                pending_setup_check_count=_non_negative_int(
                    blocker.get("pending_setup_check_count")
                ),
                diagnostic_pending_setup_keys=_string_list(
                    blocker.get("diagnostic_pending_setup_keys")
                ),
                non_diagnostic_pending_setup_keys=_string_list(
                    blocker.get("non_diagnostic_pending_setup_keys")
                ),
                setup_category=category,
                setup_key=key,
                setup_evidence_kind=_string(action.get("evidence_kind")),
                source_handle_options=_string_list(action.get("source_handle_options")),
                binding_token_count=_non_negative_int(action.get("binding_token_count")),
                attestation_option_count=_non_negative_int(
                    action.get("attestation_option_count")
                ),
            )
        )
    return items, errors


def _gate_dependency_item(blocker: dict[str, Any]) -> dict[str, Any]:
    kind = _string(blocker.get("kind"))
    blocker_id = _string(blocker.get("blocker_id"))
    return _base_item(
        item_id=f"gate:{kind or '-'}:{blocker_id or '-'}",
        kind=kind,
        action_type="gate_dependency",
        blocker_id=blocker_id,
        status=_string(blocker.get("status")),
        error_codes=_string_list(blocker.get("error_codes")),
        pending_setup_check_count=_non_negative_int(
            blocker.get("pending_setup_check_count")
        ),
        gate_reason=_gate_reason(kind, blocker_id),
    )


def _execution_groups(action_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    setup_item_ids = [
        item["item_id"]
        for item in action_items
        if item["action_type"] == "setup_resolution"
    ]
    runtime_item_ids = [
        item["item_id"]
        for item in action_items
        if item["action_type"]
        in {"workflow_probe_recovery", "missing_recovery_action"}
    ]
    gate_item_ids = [
        item["item_id"]
        for item in action_items
        if item["action_type"] == "gate_dependency"
    ]
    groups: list[dict[str, Any]] = []
    if setup_item_ids:
        groups.append(
            _execution_group(
                group_id="setup-resolution",
                title="Resolve external setup and credential handles",
                execution_mode="operator_setup",
                item_ids=setup_item_ids,
                depends_on_group_ids=[],
                blocked_by_external_setup=True,
                ready_for_autonomous_dispatch=False,
            )
        )
    if runtime_item_ids:
        depends_on = ["setup-resolution"] if setup_item_ids else []
        has_missing_action = any(
            item["action_type"] == "missing_recovery_action"
            for item in action_items
        )
        groups.append(
            _execution_group(
                group_id="runtime-evidence-dispatch",
                title="Run guarded runtime evidence workflows or probes",
                execution_mode="workflow_dispatch_or_local_probe",
                item_ids=runtime_item_ids,
                depends_on_group_ids=depends_on,
                blocked_by_external_setup=bool(setup_item_ids or has_missing_action),
                ready_for_autonomous_dispatch=not setup_item_ids
                and not has_missing_action,
            )
        )
    if gate_item_ids:
        depends_on = [
            group["group_id"]
            for group in groups
            if group["group_id"] in {"setup-resolution", "runtime-evidence-dispatch"}
        ]
        groups.append(
            _execution_group(
                group_id="release-gate-validation",
                title="Re-run completion-audit release gate validation",
                execution_mode="validation_gate",
                item_ids=gate_item_ids,
                depends_on_group_ids=depends_on,
                blocked_by_external_setup=bool(depends_on),
                ready_for_autonomous_dispatch=not depends_on,
            )
        )
    return groups


def _execution_group(
    *,
    group_id: str,
    title: str,
    execution_mode: str,
    item_ids: list[str],
    depends_on_group_ids: list[str],
    blocked_by_external_setup: bool,
    ready_for_autonomous_dispatch: bool,
) -> dict[str, Any]:
    group = {
        "group_id": group_id,
        "title": title,
        "execution_mode": execution_mode,
        "item_ids": list(item_ids),
        "depends_on_group_ids": list(depends_on_group_ids),
        "blocked_by_external_setup": blocked_by_external_setup,
        "ready_for_autonomous_dispatch": ready_for_autonomous_dispatch,
    }
    missing = EXECUTION_GROUP_FIELDS - set(group)
    extra = set(group) - EXECUTION_GROUP_FIELDS
    if missing or extra:
        raise AssertionError("recovery execution group schema drift")
    return group


def _base_item(
    *,
    item_id: str,
    kind: str,
    action_type: str,
    requirement_id: str = "",
    blocker_id: str = "",
    artifact: str = "",
    status: str = "",
    error_codes: list[str] | None = None,
    workflow: str = "",
    probe: str = "",
    live_env_flags: list[str] | None = None,
    live_guard_tokens: list[str] | None = None,
    dispatch_or_schedule_gate_tokens: list[str] | None = None,
    artifact_tokens: list[str] | None = None,
    preflight_required_next: list[str] | None = None,
    setup_category: str = "",
    setup_key: str = "",
    setup_evidence_kind: str = "",
    source_handle_options: list[str] | None = None,
    binding_token_count: int = 0,
    attestation_option_count: int = 0,
    pending_setup_check_count: int = 0,
    diagnostic_pending_setup_keys: list[str] | None = None,
    non_diagnostic_pending_setup_keys: list[str] | None = None,
    gate_reason: str = "",
) -> dict[str, Any]:
    item = {
        "item_id": item_id,
        "kind": kind,
        "action_type": action_type,
        "requirement_id": requirement_id,
        "blocker_id": blocker_id,
        "artifact": artifact,
        "status": status,
        "error_codes": error_codes or [],
        "workflow": workflow,
        "probe": probe,
        "live_env_flags": live_env_flags or [],
        "live_guard_tokens": live_guard_tokens or [],
        "dispatch_or_schedule_gate_tokens": dispatch_or_schedule_gate_tokens or [],
        "artifact_tokens": artifact_tokens or [],
        "preflight_required_next": preflight_required_next or [],
        "setup_category": setup_category,
        "setup_key": setup_key,
        "setup_evidence_kind": setup_evidence_kind,
        "source_handle_options": source_handle_options or [],
        "binding_token_count": binding_token_count,
        "attestation_option_count": attestation_option_count,
        "pending_setup_check_count": pending_setup_check_count,
        "diagnostic_pending_setup_keys": diagnostic_pending_setup_keys or [],
        "non_diagnostic_pending_setup_keys": non_diagnostic_pending_setup_keys or [],
        "gate_reason": gate_reason,
    }
    missing = ACTION_ITEM_FIELDS - set(item)
    extra = set(item) - ACTION_ITEM_FIELDS
    if missing or extra:
        raise AssertionError("recovery action item schema drift")
    return item


def _gate_reason(kind: str, blocker_id: str) -> str:
    if kind == "runtime_readiness":
        return "runtime evidence must satisfy completion-audit readiness"
    if kind == "control_chain":
        return f"control-chain gate {blocker_id or '-'} must become ready"
    if kind == "setup_gap_summary":
        return f"setup-gap summary gate {blocker_id or '-'} must become ready"
    return "release gate dependency must become ready"


def _workflow_probe_cell(item: dict[str, Any]) -> str:
    if item["action_type"] != "workflow_probe_recovery":
        return "-"
    return f"{item['workflow']} / {item['probe']}"


def _setup_cell(item: dict[str, Any]) -> str:
    if item["action_type"] != "setup_resolution":
        return "-"
    return (
        f"{item['setup_category']}:{item['setup_key']}"
        f"@{item['setup_evidence_kind']}"
    )


def _action_items_fingerprint(items: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        items,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _execution_groups_fingerprint(groups: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        groups,
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


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _write_output(path: Path | None, text: str) -> None:
    if path is None:
        print(text)
        return
    _validate_output_path(path)
    safe_write_report_text(path, text)


def _validate_output_path(path: Path) -> None:
    if path.exists() and path.is_dir():
        raise ValueError(RECOVERY_PLAN_OUTPUT_PATH_DIRECTORY_ERROR)
    if path.is_symlink():
        raise ValueError(RECOVERY_PLAN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(
                f"{RECOVERY_PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR}: {parent}"
            )


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in errors:
        code = _error_code(error)
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit recovery plan source release_blockers invalid":
        return "completion_audit_recovery_plan_source_invalid"
    if error == "completion audit recovery plan source release_blocker_count mismatch":
        return "completion_audit_recovery_plan_source_mismatch"
    if error == "completion audit recovery plan release_blocker invalid":
        return "completion_audit_recovery_plan_release_blocker_invalid"
    if error == "completion audit recovery plan runtime blocker missing recovery_action":
        return "completion_audit_recovery_plan_runtime_action_missing"
    if error == "completion audit recovery plan setup_gap resolution_actions invalid":
        return "completion_audit_recovery_plan_setup_actions_invalid"
    if error == "completion audit recovery plan setup resolution action invalid":
        return "completion_audit_recovery_plan_setup_actions_invalid"
    return "completion_audit_recovery_plan_error"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": RECOVERY_PLAN_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a recovery plan from a completion-audit handoff JSON."
    )
    parser.add_argument("handoff_json", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        plan = generate_completion_audit_recovery_plan(args.handoff_json)
        if args.format == "markdown":
            _write_output(args.out, format_markdown(plan).rstrip("\n") + "\n")
        else:
            _write_output(
                args.out,
                json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n",
            )
        return 0
    except Exception as exc:  # noqa: BLE001
        payload = _json_error_payload(str(exc))
        if args.format == "json":
            text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        else:
            text = f"Wiii Completion Audit Recovery Plan: FAIL\n{exc}\n"
        _write_output(args.out, text)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
