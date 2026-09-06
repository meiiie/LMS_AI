from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIRECTORY = Path(__file__).parent
if str(RELEASE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(RELEASE_DIRECTORY))


def _load_module(name: str):
    path = RELEASE_DIRECTORY / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


normalizer = _load_module("normalize_desktop_bundle")
verifier = _load_module("verify_desktop_release")


class DesktopReleaseVerifierTests(unittest.TestCase):
    git_sha = "c" * 40

    def _create_release(self, root: Path, targets: tuple[str, ...], windows_signing: str = "authenticode") -> Path:
        output_root = root / "platforms"
        raw_paths = {
            "windows-x64": ("release/bundle/nsis/Wiii_1.2.0_x64-setup.exe",),
            "linux-x64": (
                "release/bundle/deb/Wiii_1.2.0_amd64.deb",
                "release/bundle/appimage/Wiii_1.2.0_amd64.AppImage",
            ),
            "macos-arm64": (
                "aarch64-apple-darwin/release/bundle/dmg/Wiii_1.2.0_aarch64.dmg",
            ),
            "macos-x64": (
                "x86_64-apple-darwin/release/bundle/dmg/Wiii_1.2.0_x64.dmg",
            ),
        }
        for target in targets:
            source_root = root / "sources" / target
            for relative in raw_paths[target]:
                path = source_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"bundle:{target}:{relative}".encode())
            normalizer.normalize_bundle(
                source_root=source_root,
                output_directory=output_root / target,
                release_target=target,
                version="1.2.0",
                git_sha=self.git_sha,
                release_channel="stable",
                windows_signing=windows_signing,
            )
        return output_root

    def test_verifies_complete_release_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = self._create_release(root, tuple(verifier.TARGET_SUFFIXES))
            result = verifier.verify_release_assets(
                root=output_root,
                version="1.2.0",
                git_sha=self.git_sha,
                release_scope="complete",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["binaries"]), 5)
            self.assertEqual(len(result["manifests"]), 4)

    def test_verifies_windows_only_emergency_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = self._create_release(root, ("windows-x64",))
            result = verifier.verify_release_assets(
                root=output_root,
                version="1.2.0",
                git_sha=self.git_sha,
                release_scope="windows-only-emergency",
            )
            self.assertEqual(result["targets"], ["windows-x64"])

    def test_unsigned_complete_release_keeps_inventory_and_integrity_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = self._create_release(Path(directory), tuple(verifier.TARGET_SUFFIXES), "unsigned")
            arguments = dict(root=output_root, version="1.2.0", git_sha=self.git_sha,
                             release_scope="complete", windows_signing="unsigned")
            result = verifier.verify_release_assets(**arguments)
            self.assertEqual(len(result["binaries"]), 5)
            self.assertEqual(len(result["manifests"]), 4)
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                verifier.verify_release_assets(**{**arguments, "windows_signing": "authenticode"})
            with self.assertRaisesRegex(ValueError, "emergency releases require"):
                verifier.verify_release_assets(**{**arguments, "release_scope": "windows-only-emergency"})
            binary = next(output_root.rglob("*.exe"))
            binary.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verifier.verify_release_assets(**arguments)

    def test_unsigned_release_rejects_false_signed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = self._create_release(Path(directory), tuple(verifier.TARGET_SUFFIXES), "unsigned")
            manifest_path = next((output_root / "windows-x64").glob("*-release-manifest.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["trust_state"] = "authenticode-signed"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected trust_state"):
                verifier.verify_release_assets(root=output_root, version="1.2.0", git_sha=self.git_sha,
                                               release_scope="complete", windows_signing="unsigned")

    def test_rejects_tampered_binary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = self._create_release(root, ("windows-x64",))
            binary = next(output_root.rglob("*.exe"))
            binary.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verifier.verify_release_assets(
                    root=output_root,
                    version="1.2.0",
                    git_sha=self.git_sha,
                    release_scope="windows-only-emergency",
                )

    def test_rejects_manifest_from_another_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_root = self._create_release(root, ("windows-x64",))
            manifest_path = next(output_root.rglob("*-release-manifest.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["git_sha"] = "d" * 40
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected git_sha"):
                verifier.verify_release_assets(
                    root=output_root,
                    version="1.2.0",
                    git_sha=self.git_sha,
                    release_scope="windows-only-emergency",
                )


if __name__ == "__main__":
    unittest.main()
