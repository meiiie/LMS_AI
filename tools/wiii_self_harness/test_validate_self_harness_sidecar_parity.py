import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import report_runtime_evidence_coverage as coverage
import run_wiii_self_harness as harness
import validate_runtime_evidence_registry as registry_validator
import validate_self_harness_sidecar_parity as parity


_VALID_REPORT_BUNDLE_TEXTS: dict[str, str] | None = None


def _valid_report_bundle_texts() -> dict[str, str]:
    global _VALID_REPORT_BUNDLE_TEXTS
    if _VALID_REPORT_BUNDLE_TEXTS is None:
        manifest = harness.load_manifest(harness.DEFAULT_MANIFEST)
        registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)
        harness_result = harness.validate_manifest(manifest)
        registry_result = registry_validator.validate_registry(registry)
        coverage_result = coverage.build_report(registry)

        _VALID_REPORT_BUNDLE_TEXTS = {
            parity.SELF_HARNESS_REPORT_NAME: json.dumps(
                harness_result.to_dict(),
                indent=2,
                sort_keys=True,
            ),
            parity.REGISTRY_REPORT_NAME: json.dumps(
                registry_result.to_dict(),
                indent=2,
                sort_keys=True,
            ),
            "runtime-evidence-coverage.json": json.dumps(
                coverage_result.to_dict(),
                indent=2,
                sort_keys=True,
            ),
            "runtime-evidence-coverage.md": coverage.format_markdown(coverage_result),
        }
    return _VALID_REPORT_BUNDLE_TEXTS


def _write_valid_report_bundle(root: Path) -> None:
    for file_name, text in _valid_report_bundle_texts().items():
        (root / file_name).write_text(text, encoding="utf-8")


def _copy_sidecars(bundle_root: Path, sidecar_root: Path) -> tuple[Path, Path]:
    self_harness_sidecar = sidecar_root / "wiii-self-harness-validation.json"
    registry_sidecar = sidecar_root / "wiii-runtime-evidence-registry-validation.json"
    self_harness_sidecar.write_text(
        (bundle_root / parity.SELF_HARNESS_REPORT_NAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry_sidecar.write_text(
        (bundle_root / parity.REGISTRY_REPORT_NAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return self_harness_sidecar, registry_sidecar


class SelfHarnessSidecarParityTests(unittest.TestCase):
    def test_matching_standalone_sidecars_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_valid_report_bundle(bundle_root)
            self_harness_sidecar, registry_sidecar = _copy_sidecars(bundle_root, root)

            result = parity.validate_sidecar_parity(
                bundle_root=bundle_root,
                self_harness_sidecar=self_harness_sidecar,
                registry_sidecar=registry_sidecar,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(2, result.compared_count)
        payload = result.to_dict()
        self.assertEqual([], payload["error_codes"])
        self.assertEqual(
            [
                parity.SELF_HARNESS_REPORT_NAME,
                parity.REGISTRY_REPORT_NAME,
            ],
            [comparison["bundle_report"] for comparison in payload["comparisons"]],
        )
        for comparison in payload["comparisons"]:
            with self.subTest(report=comparison["bundle_report"]):
                self.assertTrue(comparison["matched"])
                self.assertRegex(comparison["bundle_payload_sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(
                    comparison["bundle_payload_sha256"],
                    comparison["sidecar_payload_sha256"],
                )

    def test_mismatched_sidecar_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_valid_report_bundle(bundle_root)
            self_harness_sidecar, registry_sidecar = _copy_sidecars(bundle_root, root)
            payload = json.loads(self_harness_sidecar.read_text(encoding="utf-8"))
            payload["passed_checks"] += 1
            self_harness_sidecar.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            result = parity.validate_sidecar_parity(
                bundle_root=bundle_root,
                self_harness_sidecar=self_harness_sidecar,
                registry_sidecar=registry_sidecar,
            )

        self.assertFalse(result.ok)
        payload = result.to_dict()
        self.assertIn("sidecar_parity_report_mismatch", payload["error_codes"])
        mismatches = [
            comparison
            for comparison in payload["comparisons"]
            if not comparison["matched"]
        ]
        self.assertEqual(1, len(mismatches))
        self.assertEqual(parity.SELF_HARNESS_REPORT_NAME, mismatches[0]["bundle_report"])
        self.assertNotEqual(
            mismatches[0]["bundle_payload_sha256"],
            mismatches[0]["sidecar_payload_sha256"],
        )

    def test_standalone_sidecar_must_stay_outside_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_valid_report_bundle(bundle_root)
            _, registry_sidecar = _copy_sidecars(bundle_root, root)

            result = parity.validate_sidecar_parity(
                bundle_root=bundle_root,
                self_harness_sidecar=bundle_root / parity.SELF_HARNESS_REPORT_NAME,
                registry_sidecar=registry_sidecar,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "sidecar_parity_path_inside_bundle_root",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_out_writes_utf8_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_valid_report_bundle(bundle_root)
            self_harness_sidecar, registry_sidecar = _copy_sidecars(bundle_root, root)
            out_path = root / "sidecar-parity-validation.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = parity.main(
                    [
                        "--bundle-root",
                        str(bundle_root),
                        "--self-harness-sidecar",
                        str(self_harness_sidecar),
                        "--registry-sidecar",
                        str(registry_sidecar),
                        "--json",
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(
            parity.SIDECAR_PARITY_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(2, len(payload["comparisons"]))
        self.assertTrue(all(comparison["matched"] for comparison in payload["comparisons"]))

    def test_cli_out_rejects_path_inside_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_valid_report_bundle(bundle_root)
            self_harness_sidecar, registry_sidecar = _copy_sidecars(bundle_root, root)
            out_path = bundle_root / "sidecar-parity-validation.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = parity.main(
                    [
                        "--bundle-root",
                        str(bundle_root),
                        "--self-harness-sidecar",
                        str(self_harness_sidecar),
                        "--registry-sidecar",
                        str(registry_sidecar),
                        "--json",
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["sidecar_parity_output_path_inside_bundle_root"],
            payload["error_codes"],
        )
        self.assertFalse(out_path.exists())

    def test_cli_out_rejects_overwriting_input_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "bundle"
            bundle_root.mkdir()
            _write_valid_report_bundle(bundle_root)
            self_harness_sidecar, registry_sidecar = _copy_sidecars(bundle_root, root)
            original_sidecar = self_harness_sidecar.read_text(encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = parity.main(
                    [
                        "--bundle-root",
                        str(bundle_root),
                        "--self-harness-sidecar",
                        str(self_harness_sidecar),
                        "--registry-sidecar",
                        str(registry_sidecar),
                        "--json",
                        "--out",
                        str(self_harness_sidecar),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            sidecar_after = self_harness_sidecar.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["sidecar_parity_output_path_overwrites_input"],
            payload["error_codes"],
        )
        self.assertEqual(original_sidecar, sidecar_after)


if __name__ == "__main__":
    unittest.main()
