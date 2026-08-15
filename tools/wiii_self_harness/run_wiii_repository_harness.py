#!/usr/bin/env python3
"""Run Wiii's compact repository harness.

The harness verifies durable repository contracts. Product behavior belongs in
focused tests and live evidence probes; this runner links those systems without
manufacturing chains of intermediate audit artifacts.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402
from validate_runtime_evidence_registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    load_registry,
    validate_registry,
)


SCHEMA = "wiii.repository-harness.v2"
PROFILES = ("pr", "release")
CANONICAL_DOCS = (
    "README.md",
    "docs/README.md",
    "docs/WIII_PROJECT_MENTAL_MODEL.md",
    "docs/architecture/WIII_CODEBASE_MAP.md",
    "docs/architecture/WIII_WORKBENCH_IDENTITY_AND_ACP.md",
    "docs/operations/WIII_REPOSITORY_HARNESS.md",
    "docs/releases/README.md",
    "docs/releases/WIII_RELEASE_STANDARD.md",
)
REQUIRED_BRAND_ASSETS = (
    "docs/assets/brand/neko-family-v1/manifest.json",
    "docs/assets/brand/neko-family-v1/logo/neko-peek-mark.svg",
    "docs/assets/brand/neko-family-v1/logo/png/neko-peek-app-icon-master.png",
    "docs/assets/brand/neko-family-v1/mascot/neko-peek-master.png",
    "docs/assets/brand/neko-family-v1/social/wiii-readme-banner.png",
    "wiii-desktop/src-tauri/icons/icon.ico",
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


@dataclass(frozen=True)
class CheckResult:
    check: str
    ok: bool
    summary: str
    errors: list[str]


@dataclass(frozen=True)
class HarnessResult:
    schema: str
    profile: str
    ok: bool
    generated_at: str
    checks: list[CheckResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "profile": self.profile,
            "ok": self.ok,
            "generated_at": self.generated_at,
            "summary": {
                "passed": sum(check.ok for check in self.checks),
                "failed": sum(not check.ok for check in self.checks),
                "total": len(self.checks),
            },
            "checks": [asdict(check) for check in self.checks],
        }


def _result(check: str, errors: list[str], success: str) -> CheckResult:
    return CheckResult(check, not errors, success if not errors else "failed", errors)


def check_required_files(root: Path) -> CheckResult:
    required = (*CANONICAL_DOCS, *REQUIRED_BRAND_ASSETS, "VERSION", "CHANGELOG.md")
    missing = [path for path in required if not (root / path).is_file()]
    return _result("canonical-files", [f"missing: {path}" for path in missing], f"{len(required)} canonical files present")


def _load_release_module(root: Path):
    path = root / "tools/release/wiii_release.py"
    spec = importlib.util.spec_from_file_location("wiii_release_harness", path)
    if not spec or not spec.loader:
        raise ValueError("cannot load tools/release/wiii_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_release_metadata(root: Path) -> CheckResult:
    try:
        result = _load_release_module(root).check_repository(root=root)
    except Exception as exc:  # report a stable harness error instead of a traceback
        return _result("release-metadata", [str(exc)], "")
    return _result("release-metadata", list(result["errors"]), f"version {result['version']} synchronized")


def _normalize_link_target(raw: str) -> str:
    stripped = raw.strip()
    enclosed = stripped.startswith("<") and stripped.endswith(">")
    target = stripped[1:-1] if enclosed else stripped
    if " " in target and not enclosed and not target.startswith(("http://", "https://")):
        target = target.split(" ", 1)[0]
    target = target.split("#", 1)[0]
    # Legacy operator docs use Markdown links whose literal target is an
    # ellipsis to illustrate omitted steps. Windows normalizes trailing dots,
    # while POSIX treats them as a real filename, so classify the placeholder
    # explicitly instead of making link results platform-dependent.
    return "" if target in {"...", "…"} else target


def check_canonical_links(root: Path) -> CheckResult:
    errors: list[str] = []
    checked = 0
    for relative in CANONICAL_DOCS:
        document = root / relative
        if not document.is_file():
            continue
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = _normalize_link_target(raw_target)
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            candidate = (document.parent / target).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{relative}: link escapes repository: {raw_target}")
                continue
            if not candidate.exists():
                errors.append(f"{relative}: broken local link: {raw_target}")
    return _result("canonical-links", errors, f"{checked} local links resolve")


def check_product_positioning(root: Path) -> CheckResult:
    targets = ("README.md", "docs/README.md", "wiii-desktop/README.md")
    errors: list[str] = []
    combined = "\n".join((root / path).read_text(encoding="utf-8") for path in targets if (root / path).is_file()).lower()
    if "ai workbench" not in combined:
        errors.append("canonical product docs must describe Wiii as an AI workbench")
    for phrase in ("lms-first", "lms chatbot", "learning management system platform"):
        if phrase in combined:
            errors.append(f"legacy product identity remains: {phrase!r}")
    return _result("product-positioning", errors, "Wiii workbench identity is canonical")


def check_runtime_evidence_registry(root: Path) -> CheckResult:
    registry_path = root / DEFAULT_REGISTRY.relative_to(REPO_ROOT)
    try:
        data = load_registry(registry_path)
        result = validate_registry(data, repo_root=root, registry_path=registry_path)
    except Exception as exc:
        return _result("runtime-evidence-registry", [str(exc)], "")
    return _result(
        "runtime-evidence-registry",
        list(result.errors),
        f"{result.requirement_count} runtime evidence contracts valid",
    )


def check_release_git_state(root: Path) -> CheckResult:
    errors: list[str] = []
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
        if status:
            errors.append("release profile requires a clean Git worktree")
        tag = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        expected = _load_release_module(root).canonical_tag(_load_release_module(root).read_version(root))
        if tag.returncode != 0 or tag.stdout.strip() != expected:
            errors.append(f"release commit must have exact tag {expected!r}")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        errors.append(str(exc))
    return _result("release-git-state", errors, "worktree and stable tag are release-ready")


def run_harness(profile: str = "pr", root: Path = REPO_ROOT) -> HarnessResult:
    if profile not in PROFILES:
        raise ValueError(f"unknown harness profile: {profile}")
    checks: list[Callable[[Path], CheckResult]] = [
        check_required_files,
        check_release_metadata,
        check_canonical_links,
        check_product_positioning,
        check_runtime_evidence_registry,
    ]
    if profile == "release":
        checks.append(check_release_git_state)
    results = [check(root) for check in checks]
    return HarnessResult(
        schema=SCHEMA,
        profile=profile,
        ok=all(result.ok for result in results),
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        checks=results,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Wiii Repository Harness")
    parser.add_argument("--profile", choices=PROFILES, default="pr")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="print JSON rather than a text summary")
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_harness(args.profile, args.repo_root.resolve())
    payload = result.to_dict()
    if args.json:
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        lines = [f"Wiii Repository Harness ({result.profile}): {'PASS' if result.ok else 'FAIL'}"]
        lines.extend(
            f"- {'PASS' if check.ok else 'FAIL'} {check.check}: {check.summary}"
            for check in result.checks
        )
        for check in result.checks:
            lines.extend(f"  - {error}" for error in check.errors)
        rendered = "\n".join(lines) + "\n"
    if args.out:
        safe_write_report_text(args.out, rendered)
    print(rendered, end="")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
