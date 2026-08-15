#!/usr/bin/env python3
"""Normalize Tauri desktop bundles into Wiii's public artifact contract."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import wiii_release


@dataclass(frozen=True)
class BundleFile:
    source_pattern: str
    public_suffix: str


@dataclass(frozen=True)
class ReleaseTarget:
    files: tuple[BundleFile, ...]


RELEASE_TARGETS = {
    "windows-x64": ReleaseTarget(
        files=(BundleFile("**/release/bundle/nsis/*-setup.exe", "windows-x64-setup.exe"),)
    ),
    "linux-x64": ReleaseTarget(
        files=(
            BundleFile("**/release/bundle/deb/*.deb", "linux-x64.deb"),
            BundleFile("**/release/bundle/appimage/*.AppImage", "linux-x64.AppImage"),
        )
    ),
    "macos-arm64": ReleaseTarget(
        files=(
            BundleFile(
                "**/release/bundle/dmg/*.dmg",
                "macos-arm64-unnotarized.dmg",
            ),
        )
    ),
    "macos-x64": ReleaseTarget(
        files=(
            BundleFile(
                "**/release/bundle/dmg/*.dmg",
                "macos-x64-unnotarized.dmg",
            ),
        )
    ),
}


def _find_exactly_one(source_root: Path, pattern: str) -> Path:
    matches = sorted(path for path in source_root.glob(pattern) if path.is_file())
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches) or "none"
        raise ValueError(
            f"expected exactly one Tauri bundle for {pattern!r}, found {len(matches)}: {rendered}"
        )
    return matches[0]


def normalize_bundle(
    *,
    source_root: Path,
    output_directory: Path,
    release_target: str,
    version: str,
    git_sha: str,
) -> dict[str, object]:
    if release_target not in RELEASE_TARGETS:
        choices = ", ".join(sorted(RELEASE_TARGETS))
        raise ValueError(f"unsupported release target {release_target!r}; choose one of: {choices}")
    version = wiii_release.validate_semver(version)
    if not source_root.is_dir():
        raise ValueError(f"Tauri target directory does not exist: {source_root}")

    output_directory.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    for bundle_file in RELEASE_TARGETS[release_target].files:
        source = _find_exactly_one(source_root, bundle_file.source_pattern)
        destination = output_directory / (
            f"Wiii-Workbench_{version}_{bundle_file.public_suffix}"
        )
        shutil.copy2(source, destination)
        checksum = wiii_release.sha256(destination)
        destination.with_name(f"{destination.name}.sha256").write_text(
            f"{checksum}  {destination.name}\n", encoding="ascii"
        )
        normalized.append(destination)

    manifest = wiii_release.build_manifest(normalized, version, git_sha)
    manifest_path = output_directory / (
        f"Wiii-Workbench_{version}_{release_target}_release-manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "release_target": release_target,
        "artifacts": [str(path) for path in normalized],
        "manifest": str(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-target", choices=sorted(RELEASE_TARGETS), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = normalize_bundle(
            source_root=args.source_root,
            output_directory=args.output_dir,
            release_target=args.release_target,
            version=args.version,
            git_sha=args.git_sha,
        )
    except (OSError, ValueError) as exc:
        print(f"bundle normalization error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
