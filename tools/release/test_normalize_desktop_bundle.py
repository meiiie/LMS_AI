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

MODULE_PATH = RELEASE_DIRECTORY / "normalize_desktop_bundle.py"
SPEC = importlib.util.spec_from_file_location("normalize_desktop_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
normalizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = normalizer
SPEC.loader.exec_module(normalizer)


class DesktopBundleNormalizerTests(unittest.TestCase):
    def test_normalizes_every_release_target(self) -> None:
        cases = {
            "windows-x64": [
                ("release/bundle/nsis/Wiii_1.2.0_x64-setup.exe", "windows-x64-setup.exe"),
            ],
            "linux-x64": [
                ("release/bundle/deb/Wiii_1.2.0_amd64.deb", "linux-x64.deb"),
                ("release/bundle/appimage/Wiii_1.2.0_amd64.AppImage", "linux-x64.AppImage"),
            ],
            "macos-arm64": [
                (
                    "aarch64-apple-darwin/release/bundle/dmg/Wiii_1.2.0_aarch64.dmg",
                    "macos-arm64-unnotarized.dmg",
                ),
            ],
            "macos-x64": [
                (
                    "x86_64-apple-darwin/release/bundle/dmg/Wiii_1.2.0_x64.dmg",
                    "macos-x64-unnotarized.dmg",
                ),
            ],
        }
        for release_target, source_files in cases.items():
            with self.subTest(release_target=release_target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source_root = root / "target"
                output_directory = root / "output"
                for relative, _suffix in source_files:
                    path = source_root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(f"bundle:{release_target}:{relative}".encode())

                result = normalizer.normalize_bundle(
                    source_root=source_root,
                    output_directory=output_directory,
                    release_target=release_target,
                    version="1.2.0",
                    git_sha="a" * 40,
                )

                self.assertEqual(result["release_target"], release_target)
                for _relative, suffix in source_files:
                    artifact = output_directory / f"Wiii-Workbench_1.2.0_{suffix}"
                    self.assertTrue(artifact.is_file())
                    sidecar = artifact.with_name(f"{artifact.name}.sha256")
                    self.assertIn(artifact.name, sidecar.read_text(encoding="ascii"))
                manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(len(manifest["artifacts"]), len(source_files))
                self.assertEqual(manifest["git_sha"], "a" * 40)

    def test_rejects_ambiguous_tauri_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("one-setup.exe", "two-setup.exe"):
                path = root / "target/release/bundle/nsis" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            with self.assertRaisesRegex(ValueError, "found 2"):
                normalizer.normalize_bundle(
                    source_root=root / "target",
                    output_directory=root / "output",
                    release_target="windows-x64",
                    version="1.2.0",
                    git_sha="b" * 40,
                )


if __name__ == "__main__":
    unittest.main()
