#!/usr/bin/env python3
"""Validate the Wiii Self-Harness scenario manifest.

The harness is intentionally static and deterministic. It does not replace the
focused backend, desktop, or LMS E2E tests listed by each scenario. Its job is
to keep Wiii's active system contracts explicit, owned, and tied to evidence
files that must continue to exist.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

from safe_report_output import safe_write_report_text
from strict_json import load_strict_json_file


HARNESS_NAME = "Wiii Self-Harness"
HARNESS_VALIDATION_SCHEMA_VERSION = "wiii.self_harness_validation.v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("wiii_self_harness_scenarios.json")
DEFAULT_REQUIRED_SCENARIOS = (
    "system-flow-observability-map",
    "system-comprehension-reference-harness",
    "memory-context-provenance-ledger",
    "wiii-connect-public-tool-event-boundary",
    "chat-baseline-acceptance-harness",
    "visual-tool-capability-sync",
    "code-studio-scaffold-boundary",
    "lms-document-preview-apply-approval",
    "host-action-audit-route",
    "frontend-visual-code-studio-shell",
)
VALID_STATUS_VALUES = {"active", "deferred", "blocked"}
VALID_RISK_VALUES = {"low", "medium", "high"}
VALID_LAYER_VALUES = {
    "Wiii Core",
    "Wiii Living",
    "Wiii Host",
    "Wiii Org",
    "Wiii Data",
    "Governance",
}
ALLOWED_MANIFEST_KEYS = {
    "harness",
    "version",
    "description",
    "required_scenarios",
    "scenarios",
}
ALLOWED_SCENARIO_KEYS = {
    "id",
    "title",
    "status",
    "layer",
    "risk",
    "owner",
    "active_product_path",
    "contract",
    "invariants",
    "evidence",
    "verification",
}
ALLOWED_VERIFICATION_KEYS = {"command", "purpose"}
ALLOWED_EVIDENCE_KEYS = {"kind", "path", "must_contain"}
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


@dataclass(frozen=True)
class HarnessResult:
    validation_schema_version: str
    harness: str
    manifest_version: int | None
    manifest_path: str
    manifest_fingerprint_sha256: str
    scenario_count: int
    evidence_count: int
    passed_checks: int
    warnings: list[str]
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


class ManifestValidator:
    def __init__(self, *, repo_root: Path, manifest_path: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.manifest_path = manifest_path.resolve()
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.passed_checks = 0
        self.evidence_count = 0

    def pass_check(self) -> None:
        self.passed_checks += 1

    def error(self, message: str) -> None:
        self.errors.append(message)

    def require_string(self, value: Any, field: str, *, context: str) -> str:
        if not isinstance(value, str) or not value.strip():
            self.error(f"{context}: `{field}` must be a non-empty string")
            return ""
        self.pass_check()
        return value.strip()

    def require_string_list(self, value: Any, field: str, *, context: str) -> list[str]:
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            self.error(f"{context}: `{field}` must be a non-empty string list")
            return []
        self.pass_check()
        values = [item.strip() for item in value]
        self.require_unique_string_values(values, field=field, context=context)
        return values

    def require_unique_string_values(
        self,
        values: list[str],
        *,
        field: str,
        context: str,
    ) -> None:
        seen_values: set[str] = set()
        duplicate_values: list[str] = []
        for value in values:
            if value in seen_values and value not in duplicate_values:
                duplicate_values.append(value)
            seen_values.add(value)
        if duplicate_values:
            rendered = ", ".join(repr(value) for value in duplicate_values)
            self.error(f"{context}: `{field}` must not contain duplicate values: {rendered}")
            return
        self.pass_check()

    def reject_unknown_keys(
        self,
        item: dict[str, Any],
        *,
        allowed_keys: set[str],
        context: str,
    ) -> None:
        unknown_keys = sorted(set(item) - allowed_keys)
        if unknown_keys:
            self.error(f"{context}: unknown field(s): {', '.join(unknown_keys)}")
            return
        self.pass_check()

    def resolve_repo_path(self, raw_path: str, *, context: str) -> Path | None:
        normalized = raw_path.replace("\\", "/").strip()
        posix_path = PurePosixPath(normalized)
        parts = posix_path.parts
        if (
            not normalized
            or Path(normalized).is_absolute()
            or posix_path.is_absolute()
            or ".." in parts
            or (parts and ":" in parts[0])
        ):
            self.error(f"{context}: evidence path must be repo-relative: {raw_path!r}")
            return None

        candidate = (self.repo_root / Path(*parts)).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError:
            self.error(f"{context}: evidence path escapes repo root: {raw_path!r}")
            return None
        return candidate

    def validate_manifest(self, data: dict[str, Any], *, enforce_default_scenarios: bool) -> HarnessResult:
        self.reject_unknown_keys(
            data,
            allowed_keys=ALLOWED_MANIFEST_KEYS,
            context="manifest",
        )
        if data.get("harness") != HARNESS_NAME:
            self.error(f"manifest: `harness` must be {HARNESS_NAME!r}")
        else:
            self.pass_check()

        version = data.get("version")
        if not _is_positive_int(version):
            self.error("manifest: `version` must be an integer >= 1")
        else:
            self.pass_check()

        self.require_string(data.get("description"), "description", context="manifest")
        required_scenarios = self.require_string_list(
            data.get("required_scenarios"),
            "required_scenarios",
            context="manifest",
        )
        for required_scenario_id in required_scenarios:
            if not SCENARIO_ID_RE.match(required_scenario_id):
                self.error(
                    "manifest: required_scenarios id must be lowercase kebab-case: "
                    f"{required_scenario_id!r}"
                )
            else:
                self.pass_check()

        scenario_items = data.get("scenarios")
        if not isinstance(scenario_items, list) or not scenario_items:
            self.error("manifest: `scenarios` must be a non-empty list")
            scenario_items = []
        else:
            self.pass_check()

        scenario_ids: set[str] = set()
        active_scenario_ids: set[str] = set()
        scenario_status_by_id: dict[str, str] = {}
        for index, scenario in enumerate(scenario_items):
            self.validate_scenario(
                scenario,
                index=index,
                scenario_ids=scenario_ids,
                active_scenario_ids=active_scenario_ids,
                scenario_status_by_id=scenario_status_by_id,
            )

        required_id_set = set(required_scenarios)
        missing_required = sorted(required_id_set - scenario_ids)
        for scenario_id in missing_required:
            self.error(f"manifest: required scenario {scenario_id!r} is missing from scenarios")
        inactive_required = sorted(
            scenario_id
            for scenario_id in required_id_set & set(scenario_status_by_id)
            if scenario_status_by_id[scenario_id] != "active"
        )
        for scenario_id in inactive_required:
            self.error(
                f"manifest: required scenario {scenario_id!r} must be active, "
                f"got {scenario_status_by_id[scenario_id]!r}"
            )
        unrequired_active = sorted(active_scenario_ids - required_id_set)
        for scenario_id in unrequired_active:
            self.error(
                f"manifest: active scenario {scenario_id!r} is missing from "
                "`required_scenarios`"
            )

        if enforce_default_scenarios:
            for scenario_id in DEFAULT_REQUIRED_SCENARIOS:
                if scenario_id not in required_id_set:
                    self.error(
                        "manifest: default Wiii Self-Harness scenario "
                        f"{scenario_id!r} is missing from `required_scenarios`"
                    )
                if scenario_id not in scenario_ids:
                    self.error(
                        "manifest: default Wiii Self-Harness scenario "
                        f"{scenario_id!r} is missing from `scenarios`"
                    )

        if scenario_ids and not missing_required and not inactive_required and not unrequired_active:
            self.pass_check()

        return HarnessResult(
            validation_schema_version=HARNESS_VALIDATION_SCHEMA_VERSION,
            harness=HARNESS_NAME,
            manifest_version=version if _is_positive_int(version) else None,
            manifest_path=str(self.manifest_path),
            manifest_fingerprint_sha256=_manifest_fingerprint(data),
            scenario_count=len(scenario_items),
            evidence_count=self.evidence_count,
            passed_checks=self.passed_checks,
            warnings=self.warnings,
            errors=self.errors,
        )

    def validate_scenario(
        self,
        scenario: Any,
        *,
        index: int,
        scenario_ids: set[str],
        active_scenario_ids: set[str],
        scenario_status_by_id: dict[str, str],
    ) -> None:
        context = f"scenario[{index}]"
        if not isinstance(scenario, dict):
            self.error(f"{context}: scenario must be an object")
            return
        self.reject_unknown_keys(
            scenario,
            allowed_keys=ALLOWED_SCENARIO_KEYS,
            context=context,
        )

        scenario_id = self.require_string(scenario.get("id"), "id", context=context)
        valid_scenario_id = ""
        if scenario_id:
            context = f"scenario[{scenario_id}]"
            if not SCENARIO_ID_RE.match(scenario_id):
                self.error(f"{context}: `id` must be lowercase kebab-case")
            elif scenario_id in scenario_ids:
                self.error(f"{context}: duplicate scenario id")
            else:
                scenario_ids.add(scenario_id)
                valid_scenario_id = scenario_id
                self.pass_check()

        for field in ("title", "owner", "contract"):
            self.require_string(scenario.get(field), field, context=context)

        status = self.require_string(scenario.get("status"), "status", context=context)
        if status and status not in VALID_STATUS_VALUES:
            self.error(f"{context}: `status` must be one of {sorted(VALID_STATUS_VALUES)}")
        elif status:
            if valid_scenario_id:
                scenario_status_by_id[valid_scenario_id] = status
            if status == "active" and valid_scenario_id:
                active_scenario_ids.add(valid_scenario_id)
            self.pass_check()

        risk = self.require_string(scenario.get("risk"), "risk", context=context)
        if risk and risk not in VALID_RISK_VALUES:
            self.error(f"{context}: `risk` must be one of {sorted(VALID_RISK_VALUES)}")
        elif risk:
            self.pass_check()

        layer = self.require_string(scenario.get("layer"), "layer", context=context)
        if layer and layer not in VALID_LAYER_VALUES:
            self.error(f"{context}: `layer` must be one of {sorted(VALID_LAYER_VALUES)}")
        elif layer:
            self.pass_check()

        active_path = scenario.get("active_product_path")
        if not isinstance(active_path, bool):
            self.error(f"{context}: `active_product_path` must be boolean")
        else:
            self.pass_check()

        self.require_string_list(scenario.get("invariants"), "invariants", context=context)
        verification = scenario.get("verification")
        if not isinstance(verification, list) or not verification:
            self.error(f"{context}: `verification` must be a non-empty list")
        else:
            self.pass_check()
            for item_index, item in enumerate(verification):
                self.validate_verification(item, context=f"{context}.verification[{item_index}]")

        evidence = scenario.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            self.error(f"{context}: `evidence` must be a non-empty list")
            return
        self.pass_check()
        seen_evidence_entries: set[tuple[str, str]] = set()
        for item_index, item in enumerate(evidence):
            self.validate_unique_evidence_entry(
                item,
                seen_evidence_entries=seen_evidence_entries,
                context=f"{context}.evidence[{item_index}]",
            )
            self.validate_evidence(item, context=f"{context}.evidence[{item_index}]")
        self.require_active_scenario_evidence_floor(
            evidence,
            status=status,
            context=context,
        )

    def validate_unique_evidence_entry(
        self,
        item: Any,
        *,
        seen_evidence_entries: set[tuple[str, str]],
        context: str,
    ) -> None:
        if not isinstance(item, dict):
            return
        raw_kind = item.get("kind")
        raw_path = item.get("path")
        if not isinstance(raw_kind, str) or not raw_kind.strip():
            return
        if not isinstance(raw_path, str) or not raw_path.strip():
            return
        key = (raw_kind.strip(), _normalized_manifest_path_key(raw_path))
        if key in seen_evidence_entries:
            self.error(
                f"{context}: duplicate evidence entry for kind/path "
                f"{key[0]!r} {key[1]!r}"
            )
            return
        seen_evidence_entries.add(key)
        self.pass_check()

    def require_active_scenario_evidence_floor(
        self,
        evidence: list[Any],
        *,
        status: str,
        context: str,
    ) -> None:
        if status != "active":
            return
        evidence_kinds = {
            item.get("kind").strip()
            for item in evidence
            if isinstance(item, dict)
            and isinstance(item.get("kind"), str)
            and item.get("kind").strip()
        }
        if "runtime" not in evidence_kinds:
            self.error(f"{context}: active scenario must include runtime evidence")
        else:
            self.pass_check()
        if "test" not in evidence_kinds:
            self.error(f"{context}: active scenario must include test evidence")
        else:
            self.pass_check()

    def validate_verification(self, item: Any, *, context: str) -> None:
        if not isinstance(item, dict):
            self.error(f"{context}: verification item must be an object")
            return
        self.reject_unknown_keys(
            item,
            allowed_keys=ALLOWED_VERIFICATION_KEYS,
            context=context,
        )
        self.require_string(item.get("command"), "command", context=context)
        self.require_string(item.get("purpose"), "purpose", context=context)

    def validate_evidence(self, item: Any, *, context: str) -> None:
        if not isinstance(item, dict):
            self.error(f"{context}: evidence item must be an object")
            return
        self.reject_unknown_keys(
            item,
            allowed_keys=ALLOWED_EVIDENCE_KEYS,
            context=context,
        )

        raw_path = self.require_string(item.get("path"), "path", context=context)
        kind = self.require_string(item.get("kind"), "kind", context=context)
        if kind and kind not in {"runtime", "test", "docs", "ci", "governance"}:
            self.error(f"{context}: unsupported evidence kind {kind!r}")

        must_contain = item.get("must_contain", [])
        if not isinstance(must_contain, list) or not all(
            isinstance(token, str) and token.strip() for token in must_contain
        ):
            self.error(f"{context}: `must_contain` must be a string list when present")
            must_contain = []
        else:
            self.pass_check()
            self.require_unique_string_values(
                [token.strip() for token in must_contain],
                field="must_contain",
                context=context,
            )

        if not raw_path:
            return
        full_path = self.resolve_repo_path(raw_path, context=context)
        if full_path is None:
            return
        if not full_path.exists():
            self.error(f"{context}: evidence file does not exist: {raw_path}")
            return
        if not full_path.is_file():
            self.error(f"{context}: evidence path must be a file: {raw_path}")
            return

        self.evidence_count += 1
        self.pass_check()
        if not must_contain:
            return

        try:
            text = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            self.error(f"{context}: evidence file is not valid UTF-8: {raw_path} ({exc})")
            return

        for token in must_contain:
            if token not in text:
                self.error(f"{context}: token {token!r} missing from {raw_path}")
            else:
                self.pass_check()


def load_manifest(path: Path) -> dict[str, Any]:
    data = load_strict_json_file(path)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


def _normalized_manifest_path_key(raw_path: str) -> str:
    return str(PurePosixPath(raw_path.replace("\\", "/").strip()))


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _manifest_fingerprint(data: dict[str, Any]) -> str:
    contract = {
        "harness": data.get("harness"),
        "version": data.get("version"),
        "required_scenarios": data.get("required_scenarios"),
        "scenarios": data.get("scenarios"),
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in errors:
        code = _error_code(error)
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "self-harness validation output path must not overwrite manifest":
        return "self_harness_output_path_overwrites_manifest"
    if error == "self-harness validation output path must not be a symlink":
        return "self_harness_output_path_symlink"
    if error == "self-harness validation output path parent must not be a symlink":
        return "self_harness_output_path_parent_symlink"
    if error == "self-harness validation output path must not be a directory":
        return "self_harness_output_path_directory"
    if error == "manifest root must be a JSON object":
        return "manifest_root_not_object"
    if (
        "No such file or directory" in error
        or "cannot find the file" in error
        or "non-finite JSON number is not allowed" in error
        or "duplicate JSON object key(s)" in error
    ):
        return "manifest_load_failed"
    if error.startswith("manifest: unknown field(s):"):
        return "manifest_unknown_field"
    if error.startswith("manifest: `harness` must be "):
        return "manifest_identity_mismatch"
    if error == "manifest: `version` must be an integer >= 1":
        return "manifest_version_invalid"
    if error == "manifest: `description` must be a non-empty string":
        return "manifest_description_missing"
    if error == "manifest: `required_scenarios` must be a non-empty string list":
        return "manifest_required_scenarios_invalid"
    if error.startswith("manifest: required_scenarios id must be lowercase kebab-case:"):
        return "manifest_required_scenario_id_invalid"
    if error == "manifest: `scenarios` must be a non-empty list":
        return "manifest_scenarios_invalid"
    if error.startswith("manifest: required scenario "):
        if " must be active, got " in error:
            return "manifest_required_scenario_not_active"
        return "manifest_required_scenario_missing"
    if error.startswith("manifest: active scenario ") and "missing from `required_scenarios`" in error:
        return "manifest_active_scenario_not_required"
    if error.startswith("manifest: default Wiii Self-Harness scenario "):
        return "manifest_default_scenario_missing"
    if error.endswith(": scenario must be an object"):
        return "scenario_not_object"
    if ": unknown field(s):" in error:
        if ".verification[" in error:
            return "verification_unknown_field"
        if ".evidence[" in error:
            return "evidence_unknown_field"
        if error.startswith("scenario["):
            return "scenario_unknown_field"
    if ": `id` must be lowercase kebab-case" in error:
        return "scenario_id_invalid"
    if error.endswith(": duplicate scenario id"):
        return "scenario_id_duplicate"
    if ": `status` must be one of " in error:
        return "scenario_status_invalid"
    if ": `risk` must be one of " in error:
        return "scenario_risk_invalid"
    if ": `layer` must be one of " in error:
        return "scenario_layer_invalid"
    if error.endswith(": `active_product_path` must be boolean"):
        return "scenario_active_product_path_invalid"
    if error.endswith(": `invariants` must be a non-empty string list"):
        return "scenario_invariants_invalid"
    if error.endswith(": `verification` must be a non-empty list"):
        return "scenario_verification_invalid"
    if error.endswith(": verification item must be an object"):
        return "verification_item_not_object"
    if error.endswith(": evidence item must be an object"):
        return "evidence_item_not_object"
    if ": duplicate evidence entry for kind/path " in error:
        return "scenario_evidence_duplicate"
    if ": unsupported evidence kind " in error:
        return "evidence_kind_unsupported"
    if error.endswith(": `must_contain` must be a string list when present"):
        return "evidence_must_contain_invalid"
    if "must not contain duplicate values" in error:
        return "manifest_string_list_duplicate"
    if ": evidence path must be repo-relative:" in error:
        return "evidence_path_not_relative"
    if ": evidence path escapes repo root:" in error:
        return "evidence_path_escapes_repo_root"
    if ": evidence file does not exist:" in error:
        return "evidence_file_missing"
    if ": evidence path must be a file:" in error:
        return "evidence_path_not_file"
    if ": evidence file is not valid UTF-8:" in error:
        return "evidence_file_not_utf8"
    if ": token " in error and " missing from " in error:
        return "evidence_token_missing"
    if ": `evidence` must be a non-empty list" in error:
        return "scenario_evidence_invalid"
    if error.endswith(": active scenario must include runtime evidence"):
        return "scenario_runtime_evidence_missing"
    if error.endswith(": active scenario must include test evidence"):
        return "scenario_test_evidence_missing"
    if ": `" in error and "must be a non-empty string" in error:
        return "scenario_string_field_missing"
    return "validation_error"


def validate_manifest(
    data: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    enforce_default_scenarios: bool = True,
) -> HarnessResult:
    validator = ManifestValidator(repo_root=repo_root, manifest_path=manifest_path)
    return validator.validate_manifest(data, enforce_default_scenarios=enforce_default_scenarios)


def format_summary(result: HarnessResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"{HARNESS_NAME}: {status}",
        f"validation_schema: {result.validation_schema_version}",
        f"manifest: {result.manifest_path}",
        f"manifest_version: {result.manifest_version if result.manifest_version is not None else '-'}",
        f"manifest_fingerprint_sha256: {result.manifest_fingerprint_sha256}",
        f"scenarios: {result.scenario_count}",
        f"evidence files: {result.evidence_count}",
        f"checks passed: {result.passed_checks}",
    ]
    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result.warnings)
    if result.errors:
        lines.append("")
        lines.append("Errors:")
        lines.append(f"Error codes: {', '.join(_error_codes(result.errors)) or '-'}")
        lines.append(
            f"Error code counts: {_format_error_code_counts(_error_code_counts(result.errors))}"
        )
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)


def format_scenario_list(data: dict[str, Any]) -> str:
    scenarios = data.get("scenarios", [])
    if not isinstance(scenarios, list):
        return ""
    rows: list[str] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = str(scenario.get("id") or "").strip()
        title = str(scenario.get("title") or "").strip()
        status = str(scenario.get("status") or "").strip()
        rows.append(f"{scenario_id}\t{status}\t{title}")
    return "\n".join(rows)


def _format_error_code_counts(error_code_counts: dict[str, int]) -> str:
    if not error_code_counts:
        return "-"
    return ", ".join(
        f"{error_code}={count}" for error_code, count in error_code_counts.items()
    )


def validate_output_path(*, manifest_path: Path, out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.resolve() == manifest_path.resolve():
        raise ValueError("self-harness validation output path must not overwrite manifest")
    if out_path.is_symlink():
        raise ValueError("self-harness validation output path must not be a symlink")
    if _path_has_symlink_parent(out_path):
        raise ValueError(
            "self-harness validation output path parent must not be a symlink"
        )
    if out_path.exists() and out_path.is_dir():
        raise ValueError("self-harness validation output path must not be a directory")


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


def write_cli_output(rendered: str, out_path: Path | None) -> None:
    if out_path is None:
        print(rendered)
        return
    safe_write_report_text(out_path, rendered + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Validate {HARNESS_NAME}.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation output.")
    parser.add_argument("--out", type=Path, default=None, help="Write output directly to a UTF-8 file.")
    parser.add_argument("--list", action="store_true", help="List scenarios without running validation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        validate_output_path(manifest_path=args.manifest, out_path=args.out)
    except Exception as exc:
        if args.json:
            error_code = _error_code(str(exc))
            print(
                json.dumps(
                    {
                        "validation_schema_version": HARNESS_VALIDATION_SCHEMA_VERSION,
                        "ok": False,
                        "errors": [str(exc)],
                        "error_codes": [error_code],
                        "error_code_counts": {error_code: 1},
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stdout,
            )
        else:
            print(f"{HARNESS_NAME}: FAIL\n- {exc}", file=sys.stderr)
        return 1

    try:
        data = load_manifest(args.manifest)
    except Exception as exc:
        if args.json:
            error_code = _error_code(str(exc))
            write_cli_output(
                json.dumps(
                    {
                        "validation_schema_version": HARNESS_VALIDATION_SCHEMA_VERSION,
                        "ok": False,
                        "errors": [str(exc)],
                        "error_codes": [error_code],
                        "error_code_counts": {error_code: 1},
                    },
                    indent=2,
                    sort_keys=True,
                ),
                args.out,
            )
        else:
            print(f"{HARNESS_NAME}: FAIL\n- {exc}", file=sys.stderr)
        return 1

    if args.list:
        write_cli_output(format_scenario_list(data), args.out)
        return 0

    result = validate_manifest(
        data,
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        enforce_default_scenarios=True,
    )
    if args.json:
        write_cli_output(json.dumps(result.to_dict(), indent=2, sort_keys=True), args.out)
    else:
        write_cli_output(format_summary(result), args.out)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
