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
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


HARNESS_NAME = "Wiii Self-Harness"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("wiii_self_harness_scenarios.json")
DEFAULT_REQUIRED_SCENARIOS = (
    "system-flow-observability-map",
    "memory-context-provenance-ledger",
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
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


@dataclass(frozen=True)
class HarnessResult:
    harness: str
    manifest_path: str
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
        return [item.strip() for item in value]

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
        if data.get("harness") != HARNESS_NAME:
            self.error(f"manifest: `harness` must be {HARNESS_NAME!r}")
        else:
            self.pass_check()

        version = data.get("version")
        if not isinstance(version, int) or version < 1:
            self.error("manifest: `version` must be an integer >= 1")
        else:
            self.pass_check()

        self.require_string(data.get("description"), "description", context="manifest")
        required_scenarios = self.require_string_list(
            data.get("required_scenarios"),
            "required_scenarios",
            context="manifest",
        )

        scenario_items = data.get("scenarios")
        if not isinstance(scenario_items, list) or not scenario_items:
            self.error("manifest: `scenarios` must be a non-empty list")
            scenario_items = []
        else:
            self.pass_check()

        scenario_ids: set[str] = set()
        for index, scenario in enumerate(scenario_items):
            self.validate_scenario(scenario, index=index, scenario_ids=scenario_ids)

        required_id_set = set(required_scenarios)
        missing_required = sorted(required_id_set - scenario_ids)
        for scenario_id in missing_required:
            self.error(f"manifest: required scenario {scenario_id!r} is missing from scenarios")

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

        if scenario_ids and not missing_required:
            self.pass_check()

        return HarnessResult(
            harness=HARNESS_NAME,
            manifest_path=str(self.manifest_path),
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
    ) -> None:
        context = f"scenario[{index}]"
        if not isinstance(scenario, dict):
            self.error(f"{context}: scenario must be an object")
            return

        scenario_id = self.require_string(scenario.get("id"), "id", context=context)
        if scenario_id:
            context = f"scenario[{scenario_id}]"
            if not SCENARIO_ID_RE.match(scenario_id):
                self.error(f"{context}: `id` must be lowercase kebab-case")
            elif scenario_id in scenario_ids:
                self.error(f"{context}: duplicate scenario id")
            else:
                scenario_ids.add(scenario_id)
                self.pass_check()

        for field in ("title", "owner", "contract"):
            self.require_string(scenario.get(field), field, context=context)

        status = self.require_string(scenario.get("status"), "status", context=context)
        if status and status not in VALID_STATUS_VALUES:
            self.error(f"{context}: `status` must be one of {sorted(VALID_STATUS_VALUES)}")
        elif status:
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
        for item_index, item in enumerate(evidence):
            self.validate_evidence(item, context=f"{context}.evidence[{item_index}]")

    def validate_verification(self, item: Any, *, context: str) -> None:
        if not isinstance(item, dict):
            self.error(f"{context}: verification item must be an object")
            return
        self.require_string(item.get("command"), "command", context=context)
        self.require_string(item.get("purpose"), "purpose", context=context)

    def validate_evidence(self, item: Any, *, context: str) -> None:
        if not isinstance(item, dict):
            self.error(f"{context}: evidence item must be an object")
            return

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
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


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
        f"manifest: {result.manifest_path}",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Validate {HARNESS_NAME}.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation output.")
    parser.add_argument("--list", action="store_true", help="List scenarios without running validation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        data = load_manifest(args.manifest)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)]}, indent=2), file=sys.stdout)
        else:
            print(f"{HARNESS_NAME}: FAIL\n- {exc}", file=sys.stderr)
        return 1

    if args.list:
        print(format_scenario_list(data))
        return 0

    result = validate_manifest(
        data,
        repo_root=args.repo_root,
        manifest_path=args.manifest,
        enforce_default_scenarios=True,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_summary(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
