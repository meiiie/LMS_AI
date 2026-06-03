import os
from pathlib import Path
import tempfile
import unittest

import safe_report_output


class SafeReportOutputTests(unittest.TestCase):
    def test_safe_write_report_text_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "reports" / "result.json"

            safe_report_output.safe_write_report_text(out_path, '{"ok": true}\n')

            self.assertEqual('{"ok": true}\n', out_path.read_text(encoding="utf-8"))

    def test_safe_write_report_text_replaces_existing_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "result.json"
            out_path.write_text("old\n", encoding="utf-8")

            safe_report_output.safe_write_report_text(out_path, "new\n")

            self.assertEqual("new\n", out_path.read_text(encoding="utf-8"))
            self.assertEqual([], list(Path(temp_dir).glob(".result.json.*.tmp")))

    def test_validate_report_output_path_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "report-dir"
            out_path.mkdir()

            with self.assertRaisesRegex(ValueError, "must not be a directory"):
                safe_report_output.validate_report_output_path(out_path)

    def test_validate_report_output_path_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            out_path = root / "linked-report.json"
            try:
                os.symlink(target, out_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                safe_report_output.validate_report_output_path(out_path)

    def test_validate_report_output_path_rejects_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_dir = root / "target"
            target_dir.mkdir()
            symlink_parent = root / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                safe_report_output.validate_report_output_path(
                    symlink_parent / "report.json"
                )


if __name__ == "__main__":
    unittest.main()
