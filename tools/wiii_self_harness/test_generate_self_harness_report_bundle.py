import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import generate_self_harness_report_bundle as generator


class GenerateSelfHarnessReportBundleTests(unittest.TestCase):
    def test_generate_report_bundle_writes_validated_handoff_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"

            result = generator.generate_report_bundle(out_dir)
            payload = result.to_dict()

            report_names = sorted(path.name for path in out_dir.iterdir())

        self.assertTrue(result.ok, payload)
        self.assertEqual(
            sorted(generator.EXPECTED_GENERATED_REPORTS),
            report_names,
        )
        self.assertFalse(result.pre_self_validation.self_validation_report_present)
        self.assertTrue(result.final_validation.self_validation_report_present)
        self.assertEqual(4, result.pre_self_validation.passed_count)
        self.assertEqual(5, result.final_validation.passed_count)
        self.assertEqual([], payload["final_validation"]["error_codes"])

    def test_cli_json_reports_generated_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    ["--out-dir", str(out_dir), "--json"],
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            list(generator.EXPECTED_GENERATED_REPORTS),
            payload["reports"],
        )
        self.assertTrue(payload["final_validation"]["self_validation_report_present"])
        self.assertEqual([], payload["final_validation"]["error_codes"])

    def test_generate_report_bundle_can_require_no_synthetic_external_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"

            result = generator.generate_report_bundle(
                out_dir,
                require_no_synthetic_gaps=True,
            )
            payload = result.to_dict()
            report_names = sorted(path.name for path in out_dir.iterdir())

        self.assertTrue(result.ok, payload)
        self.assertEqual(
            sorted(generator.EXPECTED_GENERATED_REPORTS),
            report_names,
        )
        self.assertTrue(result.final_validation.self_validation_report_present)
        self.assertEqual([], payload["final_validation"]["error_codes"])

    def test_cli_json_can_require_no_synthetic_external_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        "--out-dir",
                        str(out_dir),
                        "--json",
                        "--require-no-synthetic-gaps",
                    ],
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["final_validation"]["self_validation_report_present"])
        self.assertEqual([], payload["final_validation"]["error_codes"])

    def test_generate_report_bundle_can_require_credentialed_external_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"

            result = generator.generate_report_bundle(
                out_dir,
                require_credentialed_external_contracts=True,
            )
            payload = result.to_dict()
            report_names = sorted(path.name for path in out_dir.iterdir())

        self.assertTrue(result.ok, payload)
        self.assertEqual(
            sorted(generator.EXPECTED_GENERATED_REPORTS),
            report_names,
        )
        self.assertTrue(result.final_validation.self_validation_report_present)
        self.assertEqual([], payload["final_validation"]["error_codes"])

    def test_cli_json_can_require_credentialed_external_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        "--out-dir",
                        str(out_dir),
                        "--json",
                        "--require-credentialed-external-contracts",
                    ],
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["final_validation"]["self_validation_report_present"])
        self.assertEqual([], payload["final_validation"]["error_codes"])

    def test_existing_report_file_fails_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            out_dir.mkdir()
            (out_dir / "operator-note.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                generator.OUTPUT_DIR_NOT_EMPTY_ERROR,
            ):
                generator.generate_report_bundle(out_dir)

            report_names = [path.name for path in out_dir.iterdir()]

        self.assertEqual(["operator-note.json"], report_names)

    def test_existing_self_validation_report_fails_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            out_dir.mkdir()
            stale_report = out_dir / generator.SELF_VALIDATION_REPORT_NAME
            stale_report.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                generator.OUTPUT_DIR_NOT_EMPTY_ERROR,
            ):
                generator.generate_report_bundle(out_dir)

            report_names = [path.name for path in out_dir.iterdir()]

        self.assertEqual([generator.SELF_VALIDATION_REPORT_NAME], report_names)

    def test_existing_output_file_fails_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            out_dir.write_text("operator note", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                generator.OUTPUT_DIR_NOT_DIRECTORY_ERROR,
            ):
                generator.generate_report_bundle(out_dir)

            output_text = out_dir.read_text(encoding="utf-8")

        self.assertEqual("operator note", output_text)

    def test_cli_json_reports_non_empty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            out_dir.mkdir()
            (out_dir / "operator-note.json").write_text("{}", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    ["--out-dir", str(out_dir), "--json"],
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["report_bundle_output_dir_not_empty"],
            payload["error_codes"],
        )

    def test_cli_json_reports_output_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "wiii-self-harness"
            out_dir.write_text("operator note", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    ["--out-dir", str(out_dir), "--json"],
                )
            payload = json.loads(stdout.getvalue())
            output_text = out_dir.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["report_bundle_output_path_not_directory"],
            payload["error_codes"],
        )
        self.assertEqual("operator note", output_text)

    def test_symlink_output_directory_fails_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            target = base / "target"
            target.mkdir()
            out_dir = base / "wiii-self-harness"
            try:
                os.symlink(target, out_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")

            with self.assertRaisesRegex(ValueError, generator.OUTPUT_DIR_SYMLINK_ERROR):
                generator.generate_report_bundle(out_dir)

            target_entries = list(target.iterdir())

        self.assertEqual([], target_entries)

    def test_cli_json_reports_symlink_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            target = base / "target"
            target.mkdir()
            out_dir = base / "wiii-self-harness"
            try:
                os.symlink(target, out_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    ["--out-dir", str(out_dir), "--json"],
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["report_bundle_output_dir_symlink"],
            payload["error_codes"],
        )

    def test_symlink_output_parent_fails_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            target = base / "target"
            target.mkdir()
            symlink_parent = base / "artifacts"
            try:
                os.symlink(target, symlink_parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")

            with self.assertRaisesRegex(
                ValueError,
                generator.OUTPUT_DIR_PARENT_SYMLINK_ERROR,
            ):
                generator.generate_report_bundle(symlink_parent / "wiii-self-harness")

            target_entries = list(target.iterdir())

        self.assertEqual([], target_entries)

    def test_cli_json_reports_symlink_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            target = base / "target"
            target.mkdir()
            symlink_parent = base / "artifacts"
            try:
                os.symlink(target, symlink_parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    ["--out-dir", str(symlink_parent / "wiii-self-harness"), "--json"],
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["report_bundle_output_dir_parent_symlink"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
