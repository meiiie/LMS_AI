#!/usr/bin/env python3
"""Report privacy-safe live setup gaps for completion-audit dispatch."""

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
import validate_completion_audit_setup_handle_plan as plan_validator  # noqa: E402


SETUP_GAP_REPORT_SCHEMA_VERSION = "wiii.completion_audit_setup_gap_report.v1"
PROACTIVE_REQUIREMENT_ID = "autonomy-proactive-channel"
PROACTIVE_ARTIFACT = "autonomy-proactive-channel-evidence.json"
PROACTIVE_SCHEMA_VERSION = "wiii.live_proactive_channel_probe.v1"
LMS_REQUIREMENT_ID = "lms-test-course-replay"
LMS_ARTIFACT = "lms-test-course-evidence.json"
LMS_SCHEMA_VERSION = "wiii.live_lms_test_course_replay.v1"
COMPOSIO_REQUIREMENT_ID = "wiii-connect-composio-acceptance"
COMPOSIO_ARTIFACT = "wiii-connect-composio-acceptance-evidence.json"
COMPOSIO_SCHEMA_VERSION = "wiii.live_wiii_connect_composio_acceptance.v1"
OUTPUT_PATH_DIRECTORY_ERROR = "completion audit setup gap report output path must not be a directory"
OUTPUT_PATH_SYMLINK_ERROR = "completion audit setup gap report output path must not be a symlink"
OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup gap report output path parent must not be a symlink"
)

REQUIRED_NEXT_TARGETS: dict[str, dict[str, list[tuple[str, str]]]] = {
    PROACTIVE_REQUIREMENT_ID: {
        "set_live_proactive_channel_probe_env_flag": [
            ("environment_flags_required", "live_proactive_channel_probe_flag")
        ],
        "enable_selected_channel": [
            ("external_setup_required", "selected_channel_enabled")
        ],
        "configure_selected_channel_credential": [
            ("credential_slots_required", "selected_channel_credential")
        ],
        "configure_approved_recipient": [
            ("external_setup_required", "approved_recipient")
        ],
        "pass_allow_send": [("workflow_inputs_required", "allow_send")],
        "pass_allow_production": [("workflow_inputs_required", "allow_production")],
    },
    LMS_REQUIREMENT_ID: {
        "pass_allow_write": [("workflow_inputs_required", "allow_write")],
        "pass_allow_external_lms_write": [
            ("workflow_inputs_required", "allow_external_lms_write")
        ],
        "set_live_lms_test_course_replay_flag": [
            ("environment_flags_required", "live_lms_test_course_replay_flag")
        ],
        "pass_allow_production": [("workflow_inputs_required", "allow_production")],
        "configure_external_lms_apply_url": [
            ("external_setup_required", "external_lms_apply_endpoint")
        ],
        "configure_external_lms_apply_token": [
            ("credential_slots_required", "external_lms_apply_token")
        ],
    },
    COMPOSIO_REQUIREMENT_ID: {
        "pass_allow_live": [("workflow_inputs_required", "allow_live")],
        "set_live_composio_acceptance_flag": [
            ("environment_flags_required", "live_composio_acceptance_flag")
        ],
        "configure_acceptance_bearer_token": [
            ("credential_slots_required", "acceptance_bearer_token")
        ],
        "configure_backend_url": [
            ("workflow_inputs_required", "backend_url"),
            ("external_setup_required", "staging_or_live_backend"),
        ],
        "fix_arguments_json": [("workflow_inputs_required", "arguments_json")],
        "configure_connected_provider_account": [
            ("external_setup_required", "connected_provider_account")
        ],
        "configure_readonly_action_schema": [
            ("external_setup_required", "readonly_action_schema")
        ],
        "configure_execution_gateway_scope_policy": [
            ("external_setup_required", "execution_gateway_scope_policy")
        ],
    },
}


@dataclass(frozen=True)
class GapCheck:
    category: str
    key: str
    present: bool
    evidence_kind: str
    binding_token_count: int
    source_handle_present: bool
    source_handle_options: list[str]
    attestation_option_count: int


@dataclass(frozen=True)
class DiagnosticMapping:
    required_next: str
    category: str
    key: str
    present: bool


@dataclass(frozen=True)
class RequirementGap:
    requirement_id: str
    title: str
    setup_status: str
    dispatch_ready: bool
    pending_setup_check_count: int
    diagnostic_pending_setup_check_count: int
    non_diagnostic_pending_setup_check_count: int
    diagnostic_pending_setup_keys: list[str]
    non_diagnostic_pending_setup_keys: list[str]
    ready_setup_check_count: int
    pending_setup_checks: list[GapCheck]
    diagnostic_available: bool
    diagnostic_artifact: str
    diagnostic_artifact_sha256: str
    diagnostic_status: str
    diagnostic_schema_version: str
    diagnostic_preflight_schema_version: str
    diagnostic_setup_contract_dispatch_ready: bool
    diagnostic_required_next: list[str]
    diagnostic_required_next_mapped_checks: list[DiagnosticMapping]
    diagnostic_present_setup_mismatches: list[DiagnosticMapping]
    diagnostic_unmapped_required_next: list[str]


@dataclass(frozen=True)
class SetupGapReport:
    schema_version: str
    ok: bool
    setup_handle_plan_path: str
    setup_handle_plan_sha256: str
    setup_handle_plan_schema_version: str
    setup_handle_plan_fingerprint_sha256: str
    setup_gap_report_fingerprint_sha256: str
    requirement_count: int
    blocked_requirement_count: int
    pending_setup_check_count: int
    diagnostic_pending_setup_check_count: int
    non_diagnostic_pending_setup_check_count: int
    diagnostic_requirement_count: int
    diagnostic_present_setup_mismatch_count: int
    setup_diagnostics_consistent: bool
    requirements: list[RequirementGap]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def report_completion_audit_setup_gaps(
    setup_handle_plan_path: Path,
    *,
    runtime_evidence_dir: Path | None = None,
    proactive_channel_evidence_path: Path | None = None,
    lms_test_course_evidence_path: Path | None = None,
    composio_acceptance_evidence_path: Path | None = None,
) -> SetupGapReport:
    validation = plan_validator.validate_setup_handle_plan(setup_handle_plan_path)
    if not validation.ok:
        raise ValueError(
            "completion audit setup gap report setup-handle plan failed validation: "
            + "; ".join(validation.errors)
        )
    plan_payload = load_strict_json_file(setup_handle_plan_path)
    if not isinstance(plan_payload, dict):
        raise ValueError("completion audit setup handle plan root must be an object")
    if runtime_evidence_dir is not None:
        _validate_runtime_dir(runtime_evidence_dir)
    if proactive_channel_evidence_path is None and runtime_evidence_dir is not None:
        proactive_channel_evidence_path = _runtime_evidence_file(
            runtime_evidence_dir,
            PROACTIVE_ARTIFACT,
        )
    if lms_test_course_evidence_path is None and runtime_evidence_dir is not None:
        lms_test_course_evidence_path = _runtime_evidence_file(
            runtime_evidence_dir,
            LMS_ARTIFACT,
        )
    if composio_acceptance_evidence_path is None and runtime_evidence_dir is not None:
        composio_acceptance_evidence_path = _runtime_evidence_file(
            runtime_evidence_dir,
            COMPOSIO_ARTIFACT,
        )
    diagnostics = {
        PROACTIVE_REQUIREMENT_ID: _diagnostic_from_artifact(
            proactive_channel_evidence_path,
            expected_schema=PROACTIVE_SCHEMA_VERSION,
            nested_preflight_key="preflight",
        ),
        LMS_REQUIREMENT_ID: _diagnostic_from_artifact(
            lms_test_course_evidence_path,
            expected_schema=LMS_SCHEMA_VERSION,
            nested_preflight_key="preflight",
        ),
        COMPOSIO_REQUIREMENT_ID: _diagnostic_from_artifact(
            composio_acceptance_evidence_path,
            expected_schema=COMPOSIO_SCHEMA_VERSION,
            nested_preflight_key="preflight_summary",
        ),
    }
    requirements = [
        _requirement_gap(item, diagnostics.get(str(item.get("requirement_id") or "")))
        for item in plan_payload.get("plan_items", [])
        if isinstance(item, dict)
    ]
    requirement_dicts = [asdict(item) for item in requirements]
    mismatch_count = sum(
        len(item.diagnostic_present_setup_mismatches) for item in requirements
    )
    errors: list[str] = []
    return SetupGapReport(
        schema_version=SETUP_GAP_REPORT_SCHEMA_VERSION,
        ok=True,
        setup_handle_plan_path=str(setup_handle_plan_path),
        setup_handle_plan_sha256=_sha256_file(setup_handle_plan_path),
        setup_handle_plan_schema_version=str(plan_payload.get("schema_version") or ""),
        setup_handle_plan_fingerprint_sha256=str(
            plan_payload.get("setup_handle_plan_fingerprint_sha256") or ""
        ),
        setup_gap_report_fingerprint_sha256=_report_fingerprint(requirement_dicts),
        requirement_count=len(requirements),
        blocked_requirement_count=sum(
            1 for item in requirements if not item.dispatch_ready
        ),
        pending_setup_check_count=sum(
            item.pending_setup_check_count for item in requirements
        ),
        diagnostic_pending_setup_check_count=sum(
            item.diagnostic_pending_setup_check_count for item in requirements
        ),
        non_diagnostic_pending_setup_check_count=sum(
            item.non_diagnostic_pending_setup_check_count for item in requirements
        ),
        diagnostic_requirement_count=sum(
            1 for item in requirements if item.diagnostic_available
        ),
        diagnostic_present_setup_mismatch_count=mismatch_count,
        setup_diagnostics_consistent=mismatch_count == 0,
        requirements=requirements,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        errors=errors,
    )


def _requirement_gap(
    item: dict[str, Any],
    diagnostic: dict[str, Any] | None,
) -> RequirementGap:
    checks = [
        check for check in item.get("setup_checks", []) if isinstance(check, dict)
    ]
    pending_checks = [_gap_check(check) for check in checks if check.get("present") is not True]
    ready_count = sum(1 for check in checks if check.get("present") is True)
    requirement_id = str(item.get("requirement_id") or "")
    required_next = _string_list((diagnostic or {}).get("required_next"))
    mapped = _diagnostic_mappings(requirement_id, required_next, checks)
    present_mismatches = [mapping for mapping in mapped if mapping.present]
    mapped_tokens = {mapping.required_next for mapping in mapped}
    diagnostic_pending_keys = {
        (mapping.category, mapping.key) for mapping in mapped if not mapping.present
    }
    diagnostic_pending_key_list = _setup_key_list(diagnostic_pending_keys)
    non_diagnostic_pending_keys = {
        (check.category, check.key)
        for check in pending_checks
        if (check.category, check.key) not in diagnostic_pending_keys
    }
    non_diagnostic_pending_key_list = _setup_key_list(non_diagnostic_pending_keys)
    return RequirementGap(
        requirement_id=requirement_id,
        title=str(item.get("title") or ""),
        setup_status=str(item.get("setup_status") or ""),
        dispatch_ready=item.get("dispatch_ready") is True,
        pending_setup_check_count=len(pending_checks),
        diagnostic_pending_setup_check_count=len(diagnostic_pending_key_list),
        non_diagnostic_pending_setup_check_count=len(non_diagnostic_pending_key_list),
        diagnostic_pending_setup_keys=diagnostic_pending_key_list,
        non_diagnostic_pending_setup_keys=non_diagnostic_pending_key_list,
        ready_setup_check_count=ready_count,
        pending_setup_checks=pending_checks,
        diagnostic_available=diagnostic is not None,
        diagnostic_artifact=str((diagnostic or {}).get("artifact") or ""),
        diagnostic_artifact_sha256=str((diagnostic or {}).get("artifact_sha256") or ""),
        diagnostic_status=str((diagnostic or {}).get("status") or ""),
        diagnostic_schema_version=str((diagnostic or {}).get("schema_version") or ""),
        diagnostic_preflight_schema_version=str(
            (diagnostic or {}).get("preflight_schema_version") or ""
        ),
        diagnostic_setup_contract_dispatch_ready=(
            (diagnostic or {}).get("setup_contract_dispatch_ready") is True
        ),
        diagnostic_required_next=required_next,
        diagnostic_required_next_mapped_checks=mapped,
        diagnostic_present_setup_mismatches=present_mismatches,
        diagnostic_unmapped_required_next=[
            token for token in required_next if token not in mapped_tokens
        ],
    )


def _setup_key_list(keys: set[tuple[str, str]]) -> list[str]:
    return sorted(f"{category}:{key}" for category, key in keys if category and key)


def _gap_check(check: dict[str, Any]) -> GapCheck:
    return GapCheck(
        category=str(check.get("category") or ""),
        key=str(check.get("key") or ""),
        present=check.get("present") is True,
        evidence_kind=_first_string(check.get("recommended_evidence_kinds")),
        binding_token_count=len(_string_list(check.get("binding_tokens"))),
        source_handle_present=bool(str(check.get("source_handle") or "")),
        source_handle_options=_source_handle_options(check),
        attestation_option_count=len(
            _string_list(check.get("recommended_attestation_specs"))
        ),
    )


def _diagnostic_mappings(
    requirement_id: str,
    required_next: list[str],
    checks: list[dict[str, Any]],
) -> list[DiagnosticMapping]:
    result: list[DiagnosticMapping] = []
    for token in required_next:
        matched = _checks_for_required_next(requirement_id, token, checks)
        for check in matched:
            result.append(
                DiagnosticMapping(
                    required_next=token,
                    category=str(check.get("category") or ""),
                    key=str(check.get("key") or ""),
                    present=check.get("present") is True,
                )
            )
    return result


def _checks_for_required_next(
    requirement_id: str,
    token: str,
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets = REQUIRED_NEXT_TARGETS.get(requirement_id, {}).get(token, [])
    if targets:
        return [
            check
            for check in checks
            if (str(check.get("category") or ""), str(check.get("key") or ""))
            in targets
        ]
    return [
        check
        for check in checks
        if token == str(check.get("key") or "")
        or token in _string_list(check.get("binding_tokens"))
    ]


def _source_handle_options(check: dict[str, Any]) -> list[str]:
    specs = _string_list(check.get("recommended_handle_specs"))
    result: list[str] = []
    for spec in specs:
        if "=" not in spec:
            continue
        value = spec.split("=", 1)[1]
        if value:
            result.append(value)
    return result


def _diagnostic_from_artifact(
    path: Path | None,
    *,
    expected_schema: str,
    nested_preflight_key: str,
) -> dict[str, Any] | None:
    if path is None:
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("completion audit setup gap diagnostic artifact path invalid")
    payload = load_strict_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit setup gap diagnostic artifact root must be an object")
    schema_version = str(payload.get("schema_version") or "")
    if schema_version != expected_schema:
        raise ValueError(
            "completion audit setup gap diagnostic artifact schema mismatch"
        )
    preflight = (
        payload.get(nested_preflight_key)
        if isinstance(payload.get(nested_preflight_key), dict)
        else {}
    )
    setup_contract = (
        payload.get("setup_contract")
        if isinstance(payload.get("setup_contract"), dict)
        else preflight.get("setup_contract")
        if isinstance(preflight.get("setup_contract"), dict)
        else {}
    )
    required_next = _string_list(payload.get("required_next")) or _string_list(
        preflight.get("required_next")
    )
    return {
        "artifact": path.name,
        "artifact_sha256": _sha256_file(path),
        "schema_version": schema_version,
        "preflight_schema_version": str(preflight.get("schema_version") or ""),
        "status": str(payload.get("status") or ""),
        "required_next": required_next,
        "setup_contract_dispatch_ready": setup_contract.get("dispatch_ready") is True,
    }


def _validate_runtime_dir(runtime_evidence_dir: Path) -> None:
    if runtime_evidence_dir.is_symlink() or not runtime_evidence_dir.is_dir():
        raise ValueError("completion audit setup gap runtime evidence dir must be a directory")


def _runtime_evidence_file(runtime_evidence_dir: Path, name: str) -> Path | None:
    matches = sorted(
        path
        for path in runtime_evidence_dir.rglob(name)
        if path.name == name and path.is_file()
    )
    if len(matches) > 1:
        raise ValueError(
            "completion audit setup gap runtime evidence artifact matched multiple files"
        )
    if not matches:
        return None
    path = matches[0]
    if path.is_symlink() or _path_has_symlink_parent(path, stop_at=runtime_evidence_dir):
        raise ValueError("completion audit setup gap runtime evidence artifact path invalid")
    return path


def _path_has_symlink_parent(path: Path, *, stop_at: Path) -> bool:
    stop = stop_at.resolve()
    for parent in path.parents:
        if parent.resolve() == stop:
            return False
        if parent.is_symlink():
            return True
    return False


def render_markdown(report: SetupGapReport) -> str:
    data = report.to_dict()
    lines = [
        "# Wiii Completion Audit Setup Gap Report",
        "",
        f"- setup_diagnostics_consistent: {str(data['setup_diagnostics_consistent']).lower()}",
        f"- blocked_requirement_count: {data['blocked_requirement_count']}",
        f"- pending_setup_check_count: {data['pending_setup_check_count']}",
        f"- diagnostic_pending_setup_check_count: {data['diagnostic_pending_setup_check_count']}",
        f"- non_diagnostic_pending_setup_check_count: {data['non_diagnostic_pending_setup_check_count']}",
        f"- diagnostic_present_setup_mismatch_count: {data['diagnostic_present_setup_mismatch_count']}",
        "",
    ]
    for item in data["requirements"]:
        lines.extend(
            [
                f"## {item['requirement_id']}",
                "",
                f"- dispatch_ready: {str(item['dispatch_ready']).lower()}",
                f"- pending_setup_check_count: {item['pending_setup_check_count']}",
                f"- diagnostic_pending_setup_check_count: {item['diagnostic_pending_setup_check_count']}",
                "- diagnostic_pending_setup_keys: "
                + (", ".join(item["diagnostic_pending_setup_keys"]) or "none"),
                f"- non_diagnostic_pending_setup_check_count: {item['non_diagnostic_pending_setup_check_count']}",
                "- non_diagnostic_pending_setup_keys: "
                + (", ".join(item["non_diagnostic_pending_setup_keys"]) or "none"),
                f"- diagnostic_status: {item['diagnostic_status'] or 'missing'}",
                "- diagnostic_required_next: "
                + (", ".join(item["diagnostic_required_next"]) or "none"),
                "- diagnostic_present_setup_mismatches: "
                + (
                    ", ".join(
                        f"{m['required_next']}->{m['category']}:{m['key']}"
                        for m in item["diagnostic_present_setup_mismatches"]
                    )
                    or "none"
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report privacy-safe setup gaps and preflight/setup-state "
            "mismatches before live completion-audit dispatch."
        ),
    )
    parser.add_argument("setup_handle_plan", type=Path)
    parser.add_argument("--runtime-evidence-dir", type=Path, default=None)
    parser.add_argument("--proactive-channel-evidence", type=Path, default=None)
    parser.add_argument("--lms-test-course-evidence", type=Path, default=None)
    parser.add_argument("--composio-acceptance-evidence", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = report_completion_audit_setup_gaps(
            args.setup_handle_plan,
            runtime_evidence_dir=args.runtime_evidence_dir,
            proactive_channel_evidence_path=args.proactive_channel_evidence,
            lms_test_course_evidence_path=args.lms_test_course_evidence,
            composio_acceptance_evidence_path=args.composio_acceptance_evidence,
        )
    except Exception as exc:  # noqa: BLE001
        payload = _json_error_payload(str(exc))
        rendered = json.dumps(payload, indent=2, sort_keys=True)
        if args.out:
            safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
        else:
            print(rendered)
        return 1
    if args.format == "markdown":
        rendered = render_markdown(report)
    else:
        rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True).rstrip("\n") + "\n"
    if args.out:
        safe_write_report_text(args.out, rendered)
    else:
        print(rendered, end="")
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_GAP_REPORT_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _report_fingerprint(requirements: list[dict[str, Any]]) -> str:
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _first_string(value: Any) -> str:
    items = _string_list(value)
    return items[0] if items else ""


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "setup-handle plan failed validation" in error:
        return "completion_audit_setup_gap_report_plan_invalid"
    if "setup handle plan root" in error:
        return "completion_audit_setup_gap_report_plan_root_invalid"
    if "runtime evidence dir" in error:
        return "completion_audit_setup_gap_report_runtime_dir_invalid"
    if "matched multiple files" in error:
        return "completion_audit_setup_gap_report_runtime_artifact_duplicate"
    if "diagnostic artifact path invalid" in error or "artifact path invalid" in error:
        return "completion_audit_setup_gap_report_artifact_path_invalid"
    if "diagnostic artifact root" in error:
        return "completion_audit_setup_gap_report_artifact_root_invalid"
    if "diagnostic artifact schema mismatch" in error:
        return "completion_audit_setup_gap_report_artifact_schema_mismatch"
    if error == OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_gap_report_output_path_directory"
    if error == OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_gap_report_output_path_symlink"
    if error == OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_gap_report_output_path_parent_symlink"
    return "completion_audit_setup_gap_report_failed"


if __name__ == "__main__":
    raise SystemExit(main())
