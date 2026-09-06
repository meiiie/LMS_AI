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
    candidate_suffix: str
    stable_suffix: str


@dataclass(frozen=True)
class ReleaseTarget:
    files: tuple[BundleFile, ...]
    candidate_trust_state: str
    stable_trust_state: str


RELEASE_TARGETS = {
    "windows-x64": ReleaseTarget(
        files=(BundleFile(
            "**/release/bundle/nsis/*-setup.exe",
            "windows-x64-unsigned-setup.exe",
            "windows-x64-signed-setup.exe",
        ),),
        candidate_trust_state="unsigned",
        stable_trust_state="authenticode-signed",
    ),
    "linux-x64": ReleaseTarget(
        files=(
            BundleFile("**/release/bundle/deb/*.deb", "linux-x64.deb", "linux-x64.deb"),
            BundleFile("**/release/bundle/appimage/*.AppImage", "linux-x64.AppImage", "linux-x64.AppImage"),
        ),
        candidate_trust_state="checksummed",
        stable_trust_state="checksummed",
    ),
    "macos-arm64": ReleaseTarget(
        files=(
            BundleFile(
                "**/release/bundle/dmg/*.dmg",
                "macos-arm64-unnotarized.dmg",
                "macos-arm64-unnotarized.dmg",
            ),
        ),
        candidate_trust_state="ad-hoc-signed-unnotarized",
        stable_trust_state="ad-hoc-signed-unnotarized",
    ),
    "macos-x64": ReleaseTarget(
        files=(
            BundleFile(
                "**/release/bundle/dmg/*.dmg",
                "macos-x64-unnotarized.dmg",
                "macos-x64-unnotarized.dmg",
            ),
        ),
        candidate_trust_state="ad-hoc-signed-unnotarized",
        stable_trust_state="ad-hoc-signed-unnotarized",
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
    release_channel: str,
    windows_signing: str = "authenticode",
) -> dict[str, object]:
    if windows_signing not in {"authenticode", "unsigned"}:
        raise ValueError("windows signing must be 'authenticode' or 'unsigned'")
    if release_target not in RELEASE_TARGETS:
        choices = ", ".join(sorted(RELEASE_TARGETS))
        raise ValueError(f"unsupported release target {release_target!r}; choose one of: {choices}")
    version = wiii_release.validate_semver(version)
    release_channel = wiii_release.validate_release_channel(release_channel)
    identity = wiii_release.build_identity(version, release_channel, git_sha)
    if not source_root.is_dir():
        raise ValueError(f"Tauri target directory does not exist: {source_root}")

    output_directory.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    for bundle_file in RELEASE_TARGETS[release_target].files:
        source = _find_exactly_one(source_root, bundle_file.source_pattern)
        suffix = (
            bundle_file.stable_suffix
            if release_channel == "stable"
            else bundle_file.candidate_suffix
        )
        if release_target == "windows-x64" and windows_signing == "unsigned":
            suffix = bundle_file.candidate_suffix
        destination = output_directory / f"Wiii-{identity}-{suffix}"
        shutil.copy2(source, destination)
        checksum = wiii_release.sha256(destination)
        destination.with_name(f"{destination.name}.sha256").write_text(
            f"{checksum}  {destination.name}\n", encoding="ascii"
        )
        normalized.append(destination)

    target = RELEASE_TARGETS[release_target]
    trust_state = (
        target.stable_trust_state
        if release_channel == "stable"
        else target.candidate_trust_state
    )
    if release_target == "windows-x64" and windows_signing == "unsigned":
        trust_state = "unsigned"
    manifest = wiii_release.build_manifest(
        normalized,
        version,
        git_sha,
        release_channel=release_channel,
        trust_state=trust_state,
    )
    manifest_path = output_directory / f"Wiii-{identity}-{release_target}-release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "release_target": release_target,
        "release_channel": release_channel,
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
    parser.add_argument("--release-channel", choices=("candidate", "stable"), required=True)
    parser.add_argument("--windows-signing", choices=("authenticode", "unsigned"), default="authenticode")
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
            release_channel=args.release_channel,
            windows_signing=args.windows_signing,
        )
    except (OSError, ValueError) as exc:
        print(f"bundle normalization error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
