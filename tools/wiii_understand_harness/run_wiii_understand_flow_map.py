#!/usr/bin/env python3
"""Run a scoped deterministic Understand-Anything flow map for Wiii.

The script is intentionally a thin wrapper around the reference project's
deterministic scanner and import-map extractor. It keeps generated output in
ignored local scratch and produces a small JSON summary that points maintainers
at import hubs before they edit a Wiii flow.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".understand-anything" / "tmp"
DEFAULT_PLUGIN_ROOT = (
    REPO_ROOT
    / ".Codex"
    / "external"
    / "reference-systems"
    / "understand-anything"
    / "understand-anything-plugin"
)
DEFAULT_SUPPORT_PATTERNS = (
    "package.json",
    "pyproject.toml",
    "maritime-ai-service/pyproject.toml",
    "wiii-desktop/package.json",
    "wiii-desktop/tsconfig.json",
    "wiii-desktop/tsconfig.*.json",
    "wiii-desktop/vite.config.ts",
    "wiii-desktop/vitest.config.ts",
)


@dataclass(frozen=True)
class FlowProfile:
    description: str
    include: tuple[str, ...]
    support: tuple[str, ...] = DEFAULT_SUPPORT_PATTERNS


@dataclass(frozen=True)
class SelectedFiles:
    primary: tuple[dict[str, Any], ...]
    support: tuple[dict[str, Any], ...]

    @property
    def all(self) -> tuple[dict[str, Any], ...]:
        return self.primary + self.support


FLOW_PROFILES: dict[str, FlowProfile] = {
    "chat-baseline": FlowProfile(
        description="Ordinary chat stream, runtime ledger, frontend stream assembly, and no-tool baseline checks.",
        include=(
            "docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md",
            "docs/operations/WIII_SYSTEM_CONTROL_PLANE.md",
            "maritime-ai-service/app/api/v1/chat_stream_presenter.py",
            "maritime-ai-service/app/services/chat_stream_coordinator.py",
            "maritime-ai-service/app/services/llm_runtime_audit_service.py",
            "maritime-ai-service/app/services/llm_selectability_service.py",
            "maritime-ai-service/app/engine/multi_agent/runtime_flow_ledger.py",
            "maritime-ai-service/tests/unit/test_chat_baseline_acceptance_harness.py",
            "wiii-desktop/src/hooks/useSSEStream.ts",
            "wiii-desktop/src/stores/chat-store.ts",
            "wiii-desktop/src/components/chat/*.tsx",
            "wiii-desktop/src/components/chat/**/*.tsx",
        ),
    ),
    "lms-document-preview": FlowProfile(
        description="Uploaded document to LMS lesson preview/apply contract, host actions, source refs, and approval token path.",
        include=(
            "docs/integration/WIII_LMS_DOC_TO_COURSE_CONTRACT.md",
            "maritime-ai-service/app/api/v1/host_actions.py",
            "maritime-ai-service/app/engine/context/host_action_audit.py",
            "maritime-ai-service/app/engine/multi_agent/document_preview_contract.py",
            "maritime-ai-service/app/engine/multi_agent/direct_document_*.py",
            "maritime-ai-service/app/engine/multi_agent/direct_node_document_preview_runtime.py",
            "maritime-ai-service/app/engine/multi_agent/direct_tool_rounds_runtime.py",
            "maritime-ai-service/app/engine/multi_agent/document_course_*.py",
            "maritime-ai-service/tests/unit/test_*document*preview*.py",
            "maritime-ai-service/tests/unit/test_direct_tool_rounds_runtime.py",
            "maritime-ai-service/tests/unit/test_host_action_audit.py",
            "maritime-ai-service/tests/unit/test_sprint222b_host_action_event.py",
            "wiii-desktop/src/components/layout/PreviewPanel.tsx",
            "wiii-desktop/src/hooks/useSSEStream.ts",
            "wiii-desktop/src/__tests__/preview-panel-ui.test.tsx",
            "wiii-desktop/src/__tests__/host-action-sse.test.ts",
        ),
    ),
    "visual-code-studio": FlowProfile(
        description="Visual intent, tool capability sync, Code Studio tool rounds, and frontend visual shell.",
        include=(
            "maritime-ai-service/app/engine/multi_agent/visual_intent_*.py",
            "maritime-ai-service/app/engine/multi_agent/visual_runtime_metadata_contract.py",
            "maritime-ai-service/app/engine/multi_agent/tool_collection.py",
            "maritime-ai-service/app/engine/multi_agent/code_studio_*.py",
            "maritime-ai-service/app/engine/tools/visual_*contract.py",
            "maritime-ai-service/app/engine/tools/code_studio_app_intent_contract.py",
            "maritime-ai-service/tests/unit/test_visual_intent*.py",
            "maritime-ai-service/tests/unit/test_code_studio*.py",
            "wiii-desktop/src/components/chat/VisualBlock.tsx",
            "wiii-desktop/src/components/layout/CodeStudioPanel.tsx",
            "wiii-desktop/src/components/common/InlineVisualFrame.tsx",
            "wiii-desktop/src/lib/visual-frame-*.ts",
            "wiii-desktop/src/__tests__/*visual*.test.tsx",
            "wiii-desktop/src/__tests__/*code-studio*.test.tsx",
        ),
    ),
    "self-harness": FlowProfile(
        description="Wiii operating docs, Self-Harness manifest, workflow, and Understand-Anything guardrails.",
        include=(
            ".github/workflows/wiii-self-harness.yml",
            ".gitignore",
            ".understandignore",
            "docs/operations/WIII_SELF_HARNESS.md",
            "docs/operations/WIII_SYSTEM_CONTROL_PLANE.md",
            "docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md",
            "docs/operations/WIII_UNDERSTAND_ANYTHING_REFERENCE_AUDIT_2026-05-25.md",
            "tools/wiii_self_harness/*.py",
            "tools/wiii_self_harness/*.json",
            "tools/wiii_understand_harness/*.py",
            "tools/wiii_understand_harness/*.md",
        ),
    ),
}


def _to_posix(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return _to_posix(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return _to_posix(resolved)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    posix = PurePosixPath(path)
    return any(posix.match(pattern) for pattern in patterns)


def _unique_by_path(files: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for item in files:
        path = str(item.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        selected.append(item)
    return tuple(selected)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def select_profile_files(scan_result: dict[str, Any], profile: FlowProfile) -> SelectedFiles:
    files = scan_result.get("files")
    if not isinstance(files, list):
        raise ValueError("scan result must contain a `files` list")

    primary = _unique_by_path(
        item
        for item in files
        if isinstance(item, dict) and _matches(str(item.get("path") or ""), profile.include)
    )
    if not primary:
        raise ValueError("profile selected no primary files; check include patterns or scan input")

    primary_paths = {str(item.get("path") or "") for item in primary}
    support = _unique_by_path(
        item
        for item in files
        if (
            isinstance(item, dict)
            and str(item.get("path") or "") not in primary_paths
            and _matches(str(item.get("path") or ""), profile.support)
        )
    )
    return SelectedFiles(primary=primary, support=support)


def _counter_for(files: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in files:
        value = item.get(field)
        if isinstance(value, str) and value:
            counter[value] += 1
    return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))


def _top_outbound(import_map: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows = []
    for source, targets in import_map.items():
        if not isinstance(targets, list):
            continue
        rows.append({"path": source, "edge_count": len(targets)})
    rows.sort(key=lambda row: (-int(row["edge_count"]), str(row["path"])))
    return rows[:limit]


def _top_inbound(import_map: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    inbound: defaultdict[str, set[str]] = defaultdict(set)
    for source, targets in import_map.items():
        if not isinstance(targets, list):
            continue
        for target in targets:
            if isinstance(target, str) and target:
                inbound[target].add(source)
    rows = [{"path": path, "edge_count": len(sources)} for path, sources in inbound.items()]
    rows.sort(key=lambda row: (-int(row["edge_count"]), str(row["path"])))
    return rows[:limit]


def build_import_input(repo_root: Path, selected: SelectedFiles) -> dict[str, Any]:
    return {
        "projectRoot": str(repo_root.resolve()),
        "files": list(selected.all),
    }


def build_summary(
    *,
    profile_name: str,
    profile: FlowProfile,
    scan_result: dict[str, Any],
    selected: SelectedFiles,
    import_output: dict[str, Any],
    scan_path: Path,
    import_input_path: Path,
    import_output_path: Path,
) -> dict[str, Any]:
    import_map_raw = import_output.get("importMap", {})
    import_map = import_map_raw if isinstance(import_map_raw, dict) else {}
    stats = scan_result.get("stats", {})
    return {
        "profile": profile_name,
        "description": profile.description,
        "guardrails": {
            "runtime_dependency": False,
            "llm_graph_workflow": False,
            "output_directory": ".understand-anything/tmp",
            "raw_uploaded_documents_included": False,
        },
        "scan": {
            "path": _display_path(scan_path),
            "total_files": scan_result.get("totalFiles"),
            "estimated_complexity": scan_result.get("estimatedComplexity"),
            "stats": stats if isinstance(stats, dict) else {},
        },
        "selection": {
            "primary_file_count": len(selected.primary),
            "support_file_count": len(selected.support),
            "total_file_count": len(selected.all),
            "by_language": _counter_for(selected.all, "language"),
            "by_category": _counter_for(selected.all, "fileCategory"),
            "primary_files": [str(item.get("path")) for item in selected.primary],
            "support_files": [str(item.get("path")) for item in selected.support],
        },
        "import_map": {
            "input_path": _display_path(import_input_path),
            "output_path": _display_path(import_output_path),
            "stats": import_output.get("stats", {}),
            "top_outbound": _top_outbound(import_map, limit=10),
            "top_inbound": _top_inbound(import_map, limit=10),
        },
    }


def validate_plugin_root(plugin_root: Path) -> tuple[Path, Path]:
    skill_dir = plugin_root / "skills" / "understand"
    scan_script = skill_dir / "scan-project.mjs"
    import_script = skill_dir / "extract-import-map.mjs"
    missing = [str(path) for path in (scan_script, import_script) if not path.is_file()]
    if missing:
        joined = "\n  - ".join(missing)
        raise FileNotFoundError(
            "Understand-Anything deterministic scripts were not found. "
            "Clone the reference project into .Codex/external/reference-systems "
            "or pass --plugin-root.\nMissing:\n  - "
            + joined
        )
    return scan_script, import_script


def run_command(args: list[str], *, cwd: Path, verbose: bool) -> None:
    result = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, check=False)
    if verbose and result.stdout:
        sys.stdout.write(result.stdout)
    if verbose and result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode == 0:
        return
    stderr_tail = "\n".join(result.stderr.splitlines()[-20:])
    raise RuntimeError(
        "Command failed with exit code "
        f"{result.returncode}: {' '.join(args)}\n{stderr_tail}"
    )


def run_flow_map(
    *,
    profile_name: str,
    plugin_root: Path,
    output_dir: Path,
    scan_input: Path | None,
    verbose: bool,
) -> dict[str, Any]:
    if profile_name not in FLOW_PROFILES:
        raise ValueError(f"unknown profile {profile_name!r}")
    profile = FLOW_PROFILES[profile_name]
    scan_script, import_script = validate_plugin_root(plugin_root.resolve())

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"wiii-flow-map-{profile_name}"
    scan_path = output_dir / f"{prefix}-scan.json"
    import_input_path = output_dir / f"{prefix}-import-input.json"
    import_output_path = output_dir / f"{prefix}-import-map.json"
    summary_path = output_dir / f"{prefix}-summary.json"

    if scan_input is None:
        run_command(
            ["node", str(scan_script), str(REPO_ROOT), str(scan_path)],
            cwd=REPO_ROOT,
            verbose=verbose,
        )
    else:
        scan_path = scan_input.resolve()

    scan_result = load_json(scan_path)
    selected = select_profile_files(scan_result, profile)
    write_json(import_input_path, build_import_input(REPO_ROOT, selected))
    run_command(
        ["node", str(import_script), str(import_input_path), str(import_output_path)],
        cwd=REPO_ROOT,
        verbose=verbose,
    )
    import_output = load_json(import_output_path)
    summary = build_summary(
        profile_name=profile_name,
        profile=profile,
        scan_result=scan_result,
        selected=selected,
        import_output=import_output,
        scan_path=scan_path,
        import_input_path=import_input_path,
        import_output_path=import_output_path,
    )
    write_json(summary_path, summary)
    summary["summary_path"] = _display_path(summary_path)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default="chat-baseline",
        choices=sorted(FLOW_PROFILES),
        help="Scoped Wiii flow profile to map.",
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=DEFAULT_PLUGIN_ROOT,
        help="Path to understand-anything-plugin.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Ignored output directory for generated scan/import-map files.",
    )
    parser.add_argument(
        "--scan-input",
        type=Path,
        help="Existing scan-project JSON to reuse instead of running a fresh scan.",
    )
    parser.add_argument("--json", action="store_true", help="Print the summary JSON to stdout.")
    parser.add_argument("--verbose", action="store_true", help="Print wrapped Node command output.")
    parser.add_argument("--list-profiles", action="store_true", help="List flow profiles and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_profiles:
        for name, profile in sorted(FLOW_PROFILES.items()):
            print(f"{name}: {profile.description}")
        return 0

    try:
        summary = run_flow_map(
            profile_name=args.profile,
            plugin_root=args.plugin_root,
            output_dir=args.output_dir,
            scan_input=args.scan_input,
            verbose=args.verbose,
        )
    except Exception as exc:  # pragma: no cover - CLI boundary.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        selection = summary["selection"]
        import_stats = summary["import_map"].get("stats") or {}
        print(
            "Wiii Understand-Anything flow map complete: "
            f"profile={summary['profile']} "
            f"files={selection['total_file_count']} "
            f"edges={import_stats.get('totalEdges', 0)} "
            f"summary={summary['summary_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
