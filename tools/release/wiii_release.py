#!/usr/bin/env python3
"""Wiii release utilities.

This module keeps the repository's public version surfaces aligned, extracts
release notes, and produces deterministic SHA-256 manifests without requiring
third-party packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
CORE_LICENSE = "AGPL-3.0-only"
SDK_LICENSE = "Apache-2.0"
LICENSE_SOURCE_PATHS = (
    "LICENSE",
    "LICENSING.md",
    "COMMERCIAL-LICENSE.md",
    "README.md",
    "sdk/LICENSE",
    "sdk/README.md",
    "maritime-ai-service/pyproject.toml",
    "wiii-desktop/package.json",
    "wiii-desktop/src-tauri/Cargo.toml",
    "wiii-desktop/src-tauri/tauri.conf.json",
)
LICENSE_EXPECTATIONS = {
    "LICENSE": CORE_LICENSE,
    "LICENSING.md#core": CORE_LICENSE,
    "LICENSING.md#sdk": SDK_LICENSE,
    "COMMERCIAL-LICENSE.md#core": CORE_LICENSE,
    "README.md#badge": CORE_LICENSE,
    "sdk/LICENSE": SDK_LICENSE,
    "sdk/README.md#spdx": SDK_LICENSE,
    "maritime-ai-service/pyproject.toml": CORE_LICENSE,
    "wiii-desktop/package.json": CORE_LICENSE,
    "wiii-desktop/src-tauri/Cargo.toml": CORE_LICENSE,
    "wiii-desktop/src-tauri/tauri.conf.json": CORE_LICENSE,
}
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


@dataclass(frozen=True)
class TextSurface:
    path: str
    pattern: str
    replacement: str
    expected_matches: int = 1


TEXT_SURFACES = (
    TextSurface(
        "maritime-ai-service/pyproject.toml",
        r'(?ms)(^\[project\]\s*.*?^version\s*=\s*")[^"]+("\s*$)',
        r"\g<1>{version}\g<2>",
    ),
    TextSurface("maritime-ai-service/app/__init__.py", r'(__version__\s*=\s*")[^"]+("\s*)', r"\g<1>{version}\g<2>"),
    TextSurface(
        "maritime-ai-service/app/core/config/_settings_base_fields.py",
        r'(app_version:\s*str\s*=\s*Field\(default=")[^"]+("\s*,)',
        r"\g<1>{version}\g<2>",
    ),
    TextSurface("maritime-ai-service/.env.example", r'(?m)^(APP_VERSION=)[^\r\n]+$', r"\g<1>{version}"),
    TextSurface("wiii-desktop/package.json", r'("version"\s*:\s*")[^"]+("\s*,)', r"\g<1>{version}\g<2>"),
    TextSurface("wiii-desktop/src-tauri/tauri.conf.json", r'("version"\s*:\s*")[^"]+("\s*,)', r"\g<1>{version}\g<2>"),
    TextSurface("wiii-desktop/src-tauri/Cargo.toml", r'(?m)^(version\s*=\s*")[^"]+("\s*)$', r"\g<1>{version}\g<2>"),
    TextSurface("wiii-desktop/src/lib/constants.ts", r'(APP_VERSION\s*=\s*")[^"]+(";)', r"\g<1>{version}\g<2>"),
    TextSurface("wiii-desktop/index.html", r'("softwareVersion"\s*:\s*")[^"]+("\s*)', r"\g<1>{version}\g<2>"),
    TextSurface("wiii-desktop/public/splashscreen.html", r'(<div class="version">v)[^<]+(</div>)', r"\g<1>{version}\g<2>"),
    TextSurface(
        "wiii-desktop/scripts/render_wiii_installer_brand.py",
        r"VERSION\s+[0-9A-Za-z.+-]+",
        "VERSION {version}",
        2,
    ),
)


def validate_semver(version: str) -> str:
    value = version.strip()
    if not SEMVER_RE.fullmatch(value):
        raise ValueError(f"invalid SemVer: {version!r}")
    return value


def canonical_tag(version: str) -> str:
    return f"wiii-v{validate_semver(version)}"


def read_version(root: Path = ROOT) -> str:
    return validate_semver((root / "VERSION").read_text(encoding="utf-8"))


def _surface_values(root: Path, surface: TextSurface) -> list[str]:
    text = (root / surface.path).read_text(encoding="utf-8")
    matches = list(re.finditer(surface.pattern, text))
    if len(matches) != surface.expected_matches:
        raise ValueError(
            f"{surface.path}: expected {surface.expected_matches} version surface(s), "
            f"found {len(matches)}"
        )
    values: list[str] = []
    for match in matches:
        full = match.group(0)
        version_match = re.search(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", full)
        if not version_match:
            raise ValueError(f"{surface.path}: version value was not parseable")
        values.append(version_match.group(0))
    return values


def _cargo_lock_version(root: Path) -> str:
    path = root / "wiii-desktop/src-tauri/Cargo.lock"
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r'(?ms)^\[\[package\]\]\s*\nname = "wiii-desktop"\s*\nversion = "([^"]+)"',
        text,
    )
    if not match:
        raise ValueError(f"{path.relative_to(root)}: wiii-desktop package block not found")
    return match.group(1)


def _package_lock_versions(root: Path) -> list[str]:
    path = root / "wiii-desktop/package-lock.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        return [payload["version"], payload["packages"][""]["version"]]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path.relative_to(root)}: root package versions not found") from exc


def collect_versions(root: Path = ROOT) -> dict[str, list[str]]:
    versions = {surface.path: _surface_values(root, surface) for surface in TEXT_SURFACES}
    versions["wiii-desktop/package-lock.json"] = _package_lock_versions(root)
    versions["wiii-desktop/src-tauri/Cargo.lock"] = [_cargo_lock_version(root)]
    return versions


def _detected_license(text: str, marker: str, expected: str) -> str:
    return expected if marker in text else "missing"


def collect_license_metadata(root: Path = ROOT) -> dict[str, str]:
    root_license = (root / "LICENSE").read_text(encoding="utf-8")
    licensing = (root / "LICENSING.md").read_text(encoding="utf-8")
    commercial = (root / "COMMERCIAL-LICENSE.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    sdk_license = (root / "sdk/LICENSE").read_text(encoding="utf-8")
    sdk_readme = (root / "sdk/README.md").read_text(encoding="utf-8")

    with (root / "maritime-ai-service/pyproject.toml").open("rb") as handle:
        service_metadata = tomllib.load(handle)
    with (root / "wiii-desktop/src-tauri/Cargo.toml").open("rb") as handle:
        cargo_metadata = tomllib.load(handle)
    desktop_metadata = json.loads(
        (root / "wiii-desktop/package.json").read_text(encoding="utf-8")
    )
    tauri_metadata = json.loads(
        (root / "wiii-desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )

    service_license = service_metadata["project"]["license"]
    if isinstance(service_license, dict):
        service_license = service_license.get("text", "missing")

    return {
        "LICENSE": _detected_license(
            root_license, "GNU AFFERO GENERAL PUBLIC LICENSE", CORE_LICENSE
        ),
        "LICENSING.md#core": _detected_license(licensing, CORE_LICENSE, CORE_LICENSE),
        "LICENSING.md#sdk": _detected_license(licensing, SDK_LICENSE, SDK_LICENSE),
        "COMMERCIAL-LICENSE.md#core": _detected_license(
            commercial, CORE_LICENSE, CORE_LICENSE
        ),
        "README.md#badge": _detected_license(
            readme, 'alt="AGPL-3.0-only license"', CORE_LICENSE
        ),
        "sdk/LICENSE": _detected_license(
            sdk_license, "Apache License", SDK_LICENSE
        ),
        "sdk/README.md#spdx": _detected_license(
            sdk_readme, "SPDX-License-Identifier: Apache-2.0", SDK_LICENSE
        ),
        "maritime-ai-service/pyproject.toml": str(service_license),
        "wiii-desktop/package.json": str(desktop_metadata.get("license", "missing")),
        "wiii-desktop/src-tauri/Cargo.toml": str(
            cargo_metadata.get("package", {}).get("license", "missing")
        ),
        "wiii-desktop/src-tauri/tauri.conf.json": str(
            tauri_metadata.get("bundle", {}).get("license", "missing")
        ),
    }


def find_license_mismatches(surfaces: dict[str, str]) -> dict[str, dict[str, str]]:
    return {
        path: {"expected": expected, "actual": surfaces.get(path, "missing")}
        for path, expected in LICENSE_EXPECTATIONS.items()
        if surfaces.get(path) != expected
    }


def _changelog_body(label: str, heading_suffix: str, root: Path) -> str:
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^## \[{re.escape(label)}\]{heading_suffix}\s*$\n"
        r"(.*?)(?=^## \[|^\[[^\]]+\]:\s+https?://|\Z)",
        text,
    )
    if not match:
        raise ValueError(f"CHANGELOG.md has no valid [{label}] section")
    body = match.group(1).strip()
    if not body:
        raise ValueError(f"CHANGELOG.md [{label}] section is empty")
    return body


def candidate_changelog_section(version: str, root: Path = ROOT) -> str:
    version = validate_semver(version)
    body = _changelog_body("Unreleased", "", root)
    return f"## Wiii {version} candidate\n\n{body}\n"


def stable_changelog_section(version: str, root: Path = ROOT) -> str:
    version = validate_semver(version)
    body = _changelog_body(version, r"\s+-\s+\d{4}-\d{2}-\d{2}", root)
    return f"## Wiii {version}\n\n{body}\n"


def changelog_section(version: str, stable: bool = False, root: Path = ROOT) -> str:
    if stable:
        return stable_changelog_section(version, root)
    return candidate_changelog_section(version, root)


def verify_brand_manifest(root: Path = ROOT) -> int:
    brand_root = root / "docs/assets/brand/neko-family-v1"
    manifest_path = brand_root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "wiii.neko.brand.v1":
        raise ValueError("Neko brand manifest has an unexpected schema")
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Neko brand manifest has no assets")
    for entry in assets:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("Neko brand manifest contains an invalid asset entry")
        path = (brand_root / entry["path"]).resolve()
        try:
            path.relative_to(brand_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Neko brand asset escapes package: {entry['path']}") from exc
        if not path.is_file():
            raise ValueError(f"Neko brand asset is missing: {entry['path']}")
        if path.stat().st_size != entry.get("bytes"):
            raise ValueError(f"Neko brand asset size mismatch: {entry['path']}")
        if sha256(path) != entry.get("sha256"):
            raise ValueError(f"Neko brand asset hash mismatch: {entry['path']}")
    return len(assets)


def check_repository(version: str | None = None, tag: str | None = None, root: Path = ROOT) -> dict[str, object]:
    expected = validate_semver(version) if version else read_version(root)
    surfaces = collect_versions(root)
    mismatches = {
        path: values for path, values in surfaces.items() if any(value != expected for value in values)
    }
    errors: list[str] = []
    if mismatches:
        errors.append("version surfaces are not synchronized")
    license_surfaces: dict[str, str] = {}
    license_mismatches: dict[str, dict[str, str]] = {}
    try:
        license_surfaces = collect_license_metadata(root)
        license_mismatches = find_license_mismatches(license_surfaces)
        if license_mismatches:
            affected = ", ".join(sorted(license_mismatches))
            errors.append(f"license metadata is not synchronized: {affected}")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"license metadata could not be read: {exc}")
    release_state = "stable" if tag else "candidate"
    try:
        changelog_section(expected, stable=bool(tag), root=root)
    except ValueError as exc:
        errors.append(str(exc))
    brand_asset_count = 0
    try:
        brand_asset_count = verify_brand_manifest(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    expected_tag = canonical_tag(expected)
    if tag and tag != expected_tag:
        errors.append(f"tag {tag!r} does not match {expected_tag!r}")
    return {
        "schema": "wiii.release-check.v1",
        "ok": not errors,
        "version": expected,
        "tag": expected_tag,
        "release_state": release_state,
        "brand_asset_count": brand_asset_count,
        "surfaces": surfaces,
        "mismatches": mismatches,
        "license_surfaces": license_surfaces,
        "license_mismatches": license_mismatches,
        "errors": errors,
    }


def set_version(version: str, root: Path = ROOT) -> None:
    version = validate_semver(version)
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    for surface in TEXT_SURFACES:
        path = root / surface.path
        text = path.read_text(encoding="utf-8")
        replacement = surface.replacement.format(version=version)
        updated, count = re.subn(surface.pattern, replacement, text)
        if count != surface.expected_matches:
            raise ValueError(
                f"{surface.path}: expected to update {surface.expected_matches} surface(s), updated {count}"
            )
        path.write_text(updated, encoding="utf-8")

    package_lock_path = root / "wiii-desktop/package-lock.json"
    package_lock = json.loads(package_lock_path.read_text(encoding="utf-8"))
    package_lock["version"] = version
    package_lock["packages"][""]["version"] = version
    package_lock_path.write_text(
        json.dumps(package_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lock_path = root / "wiii-desktop/src-tauri/Cargo.lock"
    lock_text = lock_path.read_text(encoding="utf-8")
    lock_updated, count = re.subn(
        r'(?ms)(^\[\[package\]\]\s*\nname = "wiii-desktop"\s*\nversion = ")[^"]+("\s*$)',
        rf"\g<1>{version}\g<2>",
        lock_text,
        count=1,
    )
    if count != 1:
        raise ValueError("wiii-desktop/src-tauri/Cargo.lock: package block not updated")
    lock_path.write_text(lock_updated, encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    artifacts: Iterable[Path], version: str, git_sha: str, root: Path = ROOT
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for artifact in artifacts:
        path = artifact.resolve()
        if not path.is_file():
            raise ValueError(f"artifact does not exist: {artifact}")
        entries.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    if not entries:
        raise ValueError("at least one --artifact is required")
    return {
        "schema": "wiii.release-manifest.v1",
        "product": "Wiii Workbench",
        "version": validate_semver(version),
        "tag": canonical_tag(version),
        "git_sha": git_sha,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifacts": sorted(entries, key=lambda item: str(item["name"])),
    }


def _write_json(payload: object, output: Path | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def _git_sha(root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wiii release tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="validate release metadata")
    check_parser.add_argument("--version")
    check_parser.add_argument("--tag")
    check_parser.add_argument("--out", type=Path)

    set_parser = subparsers.add_parser("set", help="synchronize version surfaces")
    set_parser.add_argument("version")

    notes_parser = subparsers.add_parser("notes", help="extract release notes")
    notes_parser.add_argument("version", nargs="?")
    notes_parser.add_argument("--tag")
    notes_parser.add_argument("--out", type=Path)

    manifest_parser = subparsers.add_parser("manifest", help="create an artifact manifest")
    manifest_parser.add_argument("--artifact", action="append", type=Path, required=True)
    manifest_parser.add_argument("--version")
    manifest_parser.add_argument("--git-sha")
    manifest_parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            result = check_repository(args.version, args.tag)
            _write_json(result, args.out)
            return 0 if result["ok"] else 1
        if args.command == "set":
            set_version(args.version)
            result = check_repository(args.version)
            _write_json(result, None)
            return 0 if result["ok"] else 1
        if args.command == "notes":
            version = args.version or read_version()
            if args.tag and args.tag != canonical_tag(version):
                raise ValueError(
                    f"tag {args.tag!r} does not match {canonical_tag(version)!r}"
                )
            notes = changelog_section(version, stable=bool(args.tag))
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(notes, encoding="utf-8")
            print(notes, end="")
            return 0
        if args.command == "manifest":
            version = args.version or read_version()
            manifest = build_manifest(args.artifact, version, args.git_sha or _git_sha())
            _write_json(manifest, args.out)
            return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
