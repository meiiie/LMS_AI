#!/usr/bin/env python3
"""Verify Wiii desktop release assets before provenance attestation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import wiii_release


TARGET_SUFFIXES = {
    "windows-x64": ("windows-x64-setup.exe",),
    "linux-x64": ("linux-x64.deb", "linux-x64.AppImage"),
    "macos-arm64": ("macos-arm64-unnotarized.dmg",),
    "macos-x64": ("macos-x64-unnotarized.dmg",),
}

RELEASE_SCOPES = {
    "complete": tuple(TARGET_SUFFIXES),
    "windows-only-emergency": ("windows-x64",),
}


def _binary_name(version: str, suffix: str) -> str:
    return f"Wiii-Workbench_{version}_{suffix}"


def _manifest_name(version: str, target: str) -> str:
    return f"Wiii-Workbench_{version}_{target}_release-manifest.json"


def _release_contract_file(path: Path) -> bool:
    name = path.name
    return name.startswith("Wiii-Workbench_") and (
        name.endswith((".exe", ".deb", ".AppImage", ".dmg", ".sha256"))
        or name.endswith("_release-manifest.json")
    )


def _index_contract_files(root: Path) -> dict[str, Path]:
    indexed: dict[str, Path] = {}
    duplicates: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _release_contract_file(path):
            continue
        if path.name in indexed:
            duplicates.append(path.name)
        indexed[path.name] = path
    if duplicates:
        raise ValueError(f"duplicate release asset name(s): {', '.join(sorted(set(duplicates)))}")
    return indexed


def verify_release_assets(
    *, root: Path, version: str, git_sha: str, release_scope: str
) -> dict[str, object]:
    version = wiii_release.validate_semver(version)
    if release_scope not in RELEASE_SCOPES:
        choices = ", ".join(sorted(RELEASE_SCOPES))
        raise ValueError(f"unsupported release scope {release_scope!r}; choose one of: {choices}")
    if not root.is_dir():
        raise ValueError(f"release asset directory does not exist: {root}")

    targets = RELEASE_SCOPES[release_scope]
    binaries_by_target = {
        target: tuple(_binary_name(version, suffix) for suffix in TARGET_SUFFIXES[target])
        for target in targets
    }
    binary_names = {name for names in binaries_by_target.values() for name in names}
    checksum_names = {f"{name}.sha256" for name in binary_names}
    manifest_names = {_manifest_name(version, target) for target in targets}
    expected_names = binary_names | checksum_names | manifest_names

    indexed = _index_contract_files(root)
    actual_names = set(indexed)
    missing = sorted(expected_names - actual_names)
    unexpected = sorted(actual_names - expected_names)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise ValueError("release asset inventory mismatch; " + "; ".join(details))

    binary_evidence: dict[str, dict[str, object]] = {}
    for name in sorted(binary_names):
        binary = indexed[name]
        checksum_text = indexed[f"{name}.sha256"].read_text(encoding="ascii").strip()
        checksum_parts = checksum_text.split()
        if len(checksum_parts) != 2 or checksum_parts[1] != name:
            raise ValueError(f"invalid checksum sidecar format for {name}")
        actual_hash = wiii_release.sha256(binary)
        if checksum_parts[0].lower() != actual_hash:
            raise ValueError(f"checksum mismatch for {name}")
        binary_evidence[name] = {
            "bytes": binary.stat().st_size,
            "sha256": actual_hash,
        }

    for target, target_binary_names in binaries_by_target.items():
        manifest_path = indexed[_manifest_name(version, target)]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON manifest for {target}: {exc}") from exc
        expected_headers = {
            "schema": "wiii.release-manifest.v1",
            "product": "Wiii Workbench",
            "version": version,
            "tag": wiii_release.canonical_tag(version),
            "git_sha": git_sha,
        }
        for key, expected_value in expected_headers.items():
            if manifest.get(key) != expected_value:
                raise ValueError(
                    f"manifest {target} has unexpected {key}: {manifest.get(key)!r}"
                )
        entries = manifest.get("artifacts")
        if not isinstance(entries, list):
            raise ValueError(f"manifest {target} has no artifact list")
        entries_by_name = {
            entry.get("name"): entry for entry in entries if isinstance(entry, dict)
        }
        if set(entries_by_name) != set(target_binary_names) or len(entries) != len(
            target_binary_names
        ):
            raise ValueError(f"manifest {target} artifact inventory mismatch")
        for name in target_binary_names:
            entry = entries_by_name[name]
            evidence = binary_evidence[name]
            if entry.get("bytes") != evidence["bytes"]:
                raise ValueError(f"manifest byte length mismatch for {name}")
            if entry.get("sha256") != evidence["sha256"]:
                raise ValueError(f"manifest checksum mismatch for {name}")

    return {
        "schema": "wiii.desktop-release-verification.v1",
        "ok": True,
        "version": version,
        "git_sha": git_sha,
        "release_scope": release_scope,
        "targets": list(targets),
        "binaries": sorted(binary_names),
        "manifests": sorted(manifest_names),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--release-scope", choices=sorted(RELEASE_SCOPES), required=True)
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_release_assets(
            root=args.root,
            version=args.version,
            git_sha=args.git_sha,
            release_scope=args.release_scope,
        )
    except (OSError, ValueError) as exc:
        print(f"desktop release verification error: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
