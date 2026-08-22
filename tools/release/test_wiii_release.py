from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("wiii_release.py")
SPEC = importlib.util.spec_from_file_location("wiii_release", MODULE_PATH)
assert SPEC and SPEC.loader
wiii_release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wiii_release
SPEC.loader.exec_module(wiii_release)


class ReleaseToolTests(unittest.TestCase):
    def test_semver_and_tag(self) -> None:
        self.assertEqual(wiii_release.validate_semver("1.2.0"), "1.2.0")
        self.assertEqual(wiii_release.canonical_tag("1.2.0-rc.1"), "wiii-v1.2.0-rc.1")
        with self.assertRaises(ValueError):
            wiii_release.validate_semver("2026.08.15")

    def test_repository_surfaces_are_synchronized(self) -> None:
        result = wiii_release.check_repository()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["version"], "1.2.0")
        self.assertFalse(result["license_mismatches"])

    def test_license_surfaces_are_synchronized(self) -> None:
        surfaces = wiii_release.collect_license_metadata()
        self.assertEqual(set(wiii_release.LICENSE_EXPECTATIONS), set(surfaces))
        self.assertFalse(wiii_release.find_license_mismatches(surfaces))

    def test_license_drift_reports_the_affected_path(self) -> None:
        source_root = wiii_release.ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in wiii_release.LICENSE_SOURCE_PATHS:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_root / relative, destination)

            tauri_path = root / "wiii-desktop/src-tauri/tauri.conf.json"
            tauri_metadata = json.loads(tauri_path.read_text(encoding="utf-8"))
            tauri_metadata["bundle"]["license"] = "MIT"
            tauri_path.write_text(json.dumps(tauri_metadata), encoding="utf-8")

            mismatches = wiii_release.find_license_mismatches(
                wiii_release.collect_license_metadata(root)
            )
            self.assertEqual(
                mismatches["wiii-desktop/src-tauri/tauri.conf.json"],
                {"expected": "AGPL-3.0-only", "actual": "MIT"},
            )

    def test_manifest_is_deterministic_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "Wiii-Workbench_1.2.0_windows-x64-setup.exe"
            artifact.write_bytes(b"wiii-release-test")
            manifest = wiii_release.build_manifest([artifact], "1.2.0", "a" * 40)
            self.assertEqual(manifest["schema"], "wiii.release-manifest.v1")
            self.assertEqual(manifest["artifacts"][0]["bytes"], 17)
            self.assertEqual(len(manifest["artifacts"][0]["sha256"]), 64)
            json.dumps(manifest)

    def test_set_version_updates_every_surface(self) -> None:
        source_root = wiii_release.ROOT
        relative_files = {
            "VERSION",
            "CHANGELOG.md",
            "wiii-desktop/package-lock.json",
            "wiii-desktop/src-tauri/Cargo.lock",
            *(surface.path for surface in wiii_release.TEXT_SURFACES),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in relative_files:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_root / relative, destination)
            wiii_release.set_version("1.2.1", root)
            versions = wiii_release.collect_versions(root)
            self.assertTrue(versions)
            self.assertTrue(all(value == "1.2.1" for values in versions.values() for value in values))
            self.assertEqual("1.2.1", wiii_release.read_version(root))


if __name__ == "__main__":
    unittest.main()
