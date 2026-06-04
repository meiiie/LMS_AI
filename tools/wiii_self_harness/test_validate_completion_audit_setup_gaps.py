import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_generate_completion_audit_run_plan import _write_json
from test_report_completion_audit_setup_gaps import (
    _append_lms_plan_item,
    _write_failed_diagnostics,
    _write_plan,
)
from test_validate_completion_audit_setup_state import _load_json
import report_completion_audit_setup_gaps as reporter
import validate_completion_audit_setup_gaps as validator


def _write_gap_report(
    root: Path,
    *,
    ready: bool = False,
    include_lms: bool = False,
) -> tuple[Path, Path]:
    plan_path = _write_plan(root, ready=ready)
    if include_lms:
        _append_lms_plan_item(plan_path, ready=ready)
    evidence_dir = _write_failed_diagnostics(root)
    report_path = root / "setup-gaps.json"
    report = reporter.report_completion_audit_setup_gaps(
        plan_path,
        runtime_evidence_dir=evidence_dir,
    )
    _write_json(report_path, report.to_dict())
    return plan_path, report_path


def _write_gap_markdown(root: Path, plan_path: Path) -> Path:
    report = reporter.report_completion_audit_setup_gaps(
        plan_path,
        runtime_evidence_dir=root / "runtime-evidence",
    )
    markdown_path = root / "setup-gaps.md"
    markdown_path.write_text(reporter.render_markdown(report), encoding="utf-8")
    return markdown_path


def _refresh_gap_fingerprint(payload: dict) -> None:
    payload["setup_gap_report_fingerprint_sha256"] = reporter._report_fingerprint(
        payload["requirements"]
    )


class ValidateCompletionAuditSetupGapsTests(unittest.TestCase):
    def test_valid_setup_gap_report_passes_with_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, report_path = _write_gap_report(root, include_lms=True)
            markdown_path = _write_gap_markdown(root, plan_path)

            result = validator.validate_setup_gap_report(
                report_path,
                setup_handle_plan_path=plan_path,
                markdown_report_path=markdown_path,
            )
            payload = _load_json(report_path)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])
        self.assertEqual(3, payload["diagnostic_requirement_count"])
        self.assertFalse(payload["privacy"]["raw_payload_included"])

    def test_markdown_report_must_match_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, report_path = _write_gap_report(root, include_lms=True)
            markdown_path = _write_gap_markdown(root, plan_path)
            text = markdown_path.read_text(encoding="utf-8")
            markdown_path.write_text(
                text.replace(
                    "- blocked_requirement_count: 3",
                    "- blocked_requirement_count: 0",
                ),
                encoding="utf-8",
            )

            result = validator.validate_setup_gap_report(
                report_path,
                setup_handle_plan_path=plan_path,
                markdown_report_path=markdown_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_markdown_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_markdown_report_must_match_requirement_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, report_path = _write_gap_report(root, include_lms=True)
            markdown_path = _write_gap_markdown(root, plan_path)
            text = markdown_path.read_text(encoding="utf-8")
            markdown_path.write_text(
                text.replace(
                    "## lms-test-course-replay",
                    "## stale-lms-test-course-replay",
                ),
                encoding="utf-8",
            )

            result = validator.validate_setup_gap_report(
                report_path,
                setup_handle_plan_path=plan_path,
                markdown_report_path=markdown_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_markdown_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_source_hash_must_match_setup_handle_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, report_path = _write_gap_report(root)
            payload = _load_json(report_path)
            payload["setup_handle_plan_sha256"] = "0" * 64
            _write_json(report_path, payload)

            result = validator.validate_setup_gap_report(
                report_path,
                setup_handle_plan_path=plan_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_fingerprint_must_match_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _plan_path, report_path = _write_gap_report(root)
            payload = _load_json(report_path)
            payload["setup_gap_report_fingerprint_sha256"] = "0" * 64
            _write_json(report_path, payload)

            result = validator.validate_setup_gap_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_summary_counts_must_match_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _plan_path, report_path = _write_gap_report(root, include_lms=True)
            payload = _load_json(report_path)
            payload["diagnostic_requirement_count"] = 0
            _write_json(report_path, payload)

            result = validator.validate_setup_gap_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_count_invalid",
            result.to_dict()["error_codes"],
        )

    def test_diagnostic_pending_counts_must_match_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _plan_path, report_path = _write_gap_report(root, include_lms=True)
            payload = _load_json(report_path)
            payload["diagnostic_pending_setup_check_count"] = 0
            _write_json(report_path, payload)

            result = validator.validate_setup_gap_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_count_invalid",
            result.to_dict()["error_codes"],
        )

    def test_diagnostic_pending_key_lists_must_match_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _plan_path, report_path = _write_gap_report(root, include_lms=True)
            payload = _load_json(report_path)
            payload["requirements"][0]["diagnostic_pending_setup_keys"] = []
            _refresh_gap_fingerprint(payload)
            _write_json(report_path, payload)

            result = validator.validate_setup_gap_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_mapping_invalid",
            result.to_dict()["error_codes"],
        )

    def test_present_mismatches_must_match_mapped_present_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _plan_path, report_path = _write_gap_report(
                root,
                ready=True,
                include_lms=True,
            )
            payload = _load_json(report_path)
            payload["requirements"][0]["diagnostic_present_setup_mismatches"] = []
            payload["diagnostic_present_setup_mismatch_count"] = sum(
                len(item["diagnostic_present_setup_mismatches"])
                for item in payload["requirements"]
            )
            payload["setup_diagnostics_consistent"] = (
                payload["diagnostic_present_setup_mismatch_count"] == 0
            )
            _refresh_gap_fingerprint(payload)
            _write_json(report_path, payload)

            result = validator.validate_setup_gap_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_mapping_invalid",
            result.to_dict()["error_codes"],
        )

    def test_present_mismatches_make_report_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _plan_path, report_path = _write_gap_report(
                root,
                ready=True,
                include_lms=True,
            )

            result = validator.validate_setup_gap_report(report_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_gap_report_diagnostic_inconsistent",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path, report_path = _write_gap_report(root)
            markdown_path = _write_gap_markdown(root, plan_path)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(report_path),
                        "--setup-handle-plan",
                        str(plan_path),
                        "--markdown-report",
                        str(markdown_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.SETUP_GAP_REPORT_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertIn("--setup-handle-plan", validator.build_parser().format_help())
        self.assertIn("--markdown-report", validator.build_parser().format_help())


if __name__ == "__main__":
    unittest.main()
