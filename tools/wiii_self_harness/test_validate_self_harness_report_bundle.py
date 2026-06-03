import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import report_runtime_evidence_coverage as coverage
import run_wiii_self_harness as harness
import validate_runtime_evidence_registry as registry_validator
import validate_self_harness_report_bundle as report_bundle


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
            "self-harness-validation.json": json.dumps(
                harness_result.to_dict(),
                indent=2,
                sort_keys=True,
            ),
            "runtime-evidence-registry-validation.json": json.dumps(
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


def _make_coverage_report_synthetic(root: Path) -> None:
    coverage_json_path = root / "runtime-evidence-coverage.json"
    payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
    for row in payload["rows"]:
        if row["requirement_id"] != "lms-test-course-replay":
            continue
        row["external_evidence_mode"] = "synthetic_external_gap"
        row["synthetic_gap_flags"] = ["synthetic_host_side_replay"]
        row["credentialed_external_flags"] = []
        break
    payload["synthetic_external_gap_count"] = 1
    payload["credentialed_external_count"] -= 1
    coverage_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    coverage_md_path = root / "runtime-evidence-coverage.md"
    lines = coverage_md_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("| lms-test-course-replay |"):
            continue
        cells = line.strip()[2:-2].split(" | ")
        cells[10] = (
            "synthetic_external_gap; credentialed:-; "
            "synthetic:synthetic_host_side_replay"
        )
        lines[index] = "| " + " | ".join(cells) + " |"
        break
    coverage_md_path.write_text(
        "\n".join(lines).replace(
            "credentialed_external=4, synthetic_external_gap=0",
            "credentialed_external=3, synthetic_external_gap=1",
        ),
        encoding="utf-8",
    )


def _make_coverage_report_weak_credentialed_external_contract(root: Path) -> None:
    coverage_json_path = root / "runtime-evidence-coverage.json"
    payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
    for row in payload["rows"]:
        if row["requirement_id"] != "provider-runtime-tool-loop":
            continue
        row["live_env_flags"] = []
        row["live_guard_tokens"] = []
        row["dispatch_or_schedule_gates"] = ["allow_live_call"]
        break
    coverage_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


class SelfHarnessReportBundleTests(unittest.TestCase):
    def test_generated_report_bundle_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)

            result = report_bundle.validate_report_bundle(root)
            payload = json.loads(json.dumps(result.to_dict()))
            rendered = report_bundle.format_summary(result)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION, result.validation_schema_version)
        self.assertRegex(result.bundle_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(4, result.fingerprinted_report_count)
        self.assertFalse(result.self_validation_report_present)
        self.assertEqual(4, result.passed_count)
        self.assertEqual(0, result.failed_count)
        for row in result.rows:
            self.assertRegex(row.report_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertEqual(
            result.bundle_fingerprint_sha256,
            payload["bundle_fingerprint_sha256"],
        )
        self.assertEqual(4, payload["fingerprinted_report_count"])
        self.assertFalse(payload["self_validation_report_present"])
        self.assertRegex(payload["rows"][0]["report_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual([], payload["error_codes"])
        self.assertEqual({}, payload["error_code_counts"])
        self.assertIn("Wiii Self-Harness Report Bundle: PASS", rendered)
        self.assertIn("validation_schema:", rendered)
        self.assertIn("fingerprinted_reports: 4", rendered)
        self.assertIn("self_validation_report_present: false", rendered)
        self.assertIn("bundle_fingerprint_sha256:", rendered)

    def test_bundle_fingerprint_changes_when_report_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)

            coverage_path = root / "runtime-evidence-coverage.md"
            coverage_path.write_text(
                coverage_path.read_text(encoding="utf-8") + "\n<!-- changed -->\n",
                encoding="utf-8",
            )
            second_result = report_bundle.validate_report_bundle(root)

        self.assertTrue(first_result.ok, first_result.to_dict())
        self.assertTrue(second_result.ok, second_result.to_dict())
        self.assertNotEqual(
            first_result.bundle_fingerprint_sha256,
            second_result.bundle_fingerprint_sha256,
        )

    def test_self_validation_report_is_allowed_without_recursive_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(first_result.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)
            required_result = report_bundle.validate_report_bundle(
                root,
                require_self_validation=True,
            )
            payload = second_result.to_dict()

        self.assertTrue(second_result.ok, payload)
        self.assertTrue(required_result.ok, required_result.to_dict())
        self.assertEqual(5, second_result.report_count)
        self.assertEqual(4, second_result.fingerprinted_report_count)
        self.assertTrue(second_result.self_validation_report_present)
        self.assertEqual(
            first_result.bundle_fingerprint_sha256,
            second_result.bundle_fingerprint_sha256,
        )
        self.assertTrue(
            any(row.file_name == report_bundle.SELF_VALIDATION_REPORT_NAME for row in second_result.rows),
            second_result.rows,
        )

    def test_self_validation_report_can_be_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)

            result = report_bundle.validate_report_bundle(
                root,
                require_self_validation=True,
            )
            payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertFalse(result.self_validation_report_present)
        self.assertIn("self_validation_report_missing", payload["error_codes"])
        self.assertEqual(
            1,
            payload["error_code_counts"]["self_validation_report_missing"],
        )

    def test_cli_can_require_self_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--require-self-validation"]
                )

            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["self_validation_report_missing"],
            payload["error_codes"],
        )
        self.assertFalse(payload["self_validation_report_present"])

    def test_report_bundle_can_require_no_synthetic_external_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            _make_coverage_report_synthetic(root)

            result = report_bundle.validate_report_bundle(
                root,
                require_no_synthetic_gaps=True,
            )
            payload = result.to_dict()
            rendered = report_bundle.format_summary(result)

        coverage_row = next(
            row
            for row in payload["rows"]
            if row["file_name"] == "runtime-evidence-coverage.json"
        )
        self.assertFalse(result.ok)
        self.assertIn(
            "report_coverage_synthetic_external_gap_present",
            payload["error_codes"],
        )
        self.assertEqual(
            1,
            payload["error_code_counts"][
                "report_coverage_synthetic_external_gap_present"
            ],
        )
        self.assertIn(
            "report_coverage_synthetic_external_gap_present",
            coverage_row["error_codes"],
        )
        self.assertIn("lms-test-course-replay", rendered)

    def test_cli_can_require_no_synthetic_external_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            _make_coverage_report_synthetic(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--require-no-synthetic-gaps"]
                )

            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "report_coverage_synthetic_external_gap_present",
            payload["error_codes"],
        )

    def test_report_bundle_can_require_credentialed_external_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)

            result = report_bundle.validate_report_bundle(
                root,
                require_credentialed_external_contracts=True,
            )
            payload = result.to_dict()

        self.assertTrue(result.ok, payload)
        self.assertEqual([], payload["error_codes"])

    def test_report_bundle_fails_when_credentialed_external_contract_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            _make_coverage_report_weak_credentialed_external_contract(root)

            result = report_bundle.validate_report_bundle(
                root,
                require_credentialed_external_contracts=True,
            )
            payload = result.to_dict()
            rendered = report_bundle.format_summary(result)

        coverage_row = next(
            row
            for row in payload["rows"]
            if row["file_name"] == "runtime-evidence-coverage.json"
        )
        self.assertFalse(result.ok)
        self.assertIn(
            "report_coverage_credentialed_external_contract_incomplete",
            payload["error_codes"],
        )
        self.assertEqual(
            1,
            payload["error_code_counts"][
                "report_coverage_credentialed_external_contract_incomplete"
            ],
        )
        self.assertIn(
            "report_coverage_credentialed_external_contract_incomplete",
            coverage_row["error_codes"],
        )
        self.assertIn("provider-runtime-tool-loop", rendered)
        self.assertIn("live_env_flags", rendered)

    def test_cli_can_require_credentialed_external_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            _make_coverage_report_weak_credentialed_external_contract(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [
                        str(root),
                        "--json",
                        "--require-credentialed-external-contracts",
                    ]
                )

            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "report_coverage_credentialed_external_contract_incomplete",
            payload["error_codes"],
        )

    def test_self_validation_report_fails_when_fingerprint_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["bundle_fingerprint_sha256"] = "0" * 64
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_bundle_fingerprint_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_fails_when_fingerprinted_count_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["fingerprinted_report_count"] = 5
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_fingerprinted_count_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_fails_when_report_count_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["report_count"] = 5
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_count_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_fails_when_it_claims_self_presence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["self_validation_report_present"] = True
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_self_validation_presence_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_fails_when_row_hash_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["rows"][0]["report_sha256"] = "0" * 64
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_rows_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_fails_when_row_errors_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["rows"][0]["errors"] = ["raw-local-path C:/secret/report.json"]
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_rows_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_rejects_recursive_row_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["rows"].append(
                {
                    "file_name": report_bundle.SELF_VALIDATION_REPORT_NAME,
                    "status": "passed",
                    "schema_version": report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
                    "report_sha256": "0" * 64,
                    "errors": [],
                    "error_codes": [],
                }
            )
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_rows_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_fails_when_row_order_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["rows"] = list(reversed(payload["rows"]))
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_rows_order_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_rejects_extra_row_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["rows"][0]["raw_payload"] = "raw-local-token"
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_row_fields_invalid",
            second_result.to_dict()["error_codes"],
        )

    def test_missing_report_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            (root / "runtime-evidence-coverage.md").unlink()

            result = report_bundle.validate_report_bundle(root)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_file_missing", payload["error_codes"])
        self.assertEqual(1, payload["error_code_counts"]["report_file_missing"])

    def test_schema_mismatch_fails_with_normalized_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["schema_version"] = "wiii.other.v1"
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)

        self.assertFalse(result.ok)
        self.assertIn("report_schema_mismatch", result.to_dict()["error_codes"])
        self.assertIn("Error code counts: report_schema_mismatch=1", rendered)
        self.assertIn("report_schema_mismatch", rendered)

    def test_coverage_report_must_expose_error_code_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload.pop("error_code_counts")
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_required_field_missing", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_required_field_missing"],
        )
        self.assertIn("missing required field 'error_code_counts'", rendered)

    def test_child_json_report_rejects_non_finite_json_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            coverage_path.write_text(
                '{"schema_version": "wiii.runtime_evidence_coverage_report.v1", '
                '"registry_version": NaN}',
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_json_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_json_invalid"],
        )
        self.assertIn("non-finite JSON number", rendered)

    def test_child_json_report_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            coverage_path.write_text(
                '{"schema_version": "wiii.runtime_evidence_coverage_report.v1", '
                '"schema_version": "wiii.runtime_evidence_coverage_report.v1"}',
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_json_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_json_invalid"],
        )
        self.assertIn("duplicate JSON object key", rendered)

    def test_validation_json_reports_must_expose_error_code_counts(self) -> None:
        required_reports = (
            "self-harness-validation.json",
            "runtime-evidence-registry-validation.json",
        )
        for file_name in required_reports:
            with self.subTest(file_name=file_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    _write_valid_report_bundle(root)
                    report_path = root / file_name
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    payload.pop("error_code_counts")
                    report_path.write_text(json.dumps(payload), encoding="utf-8")

                    result = report_bundle.validate_report_bundle(root)
                    report = result.to_dict()

                self.assertFalse(result.ok)
                self.assertIn("report_required_field_missing", report["error_codes"])
                self.assertEqual(
                    1,
                    report["error_code_counts"]["report_required_field_missing"],
                )

    def test_child_json_reports_reject_extra_top_level_fields(self) -> None:
        child_reports = (
            "self-harness-validation.json",
            "runtime-evidence-registry-validation.json",
            "runtime-evidence-coverage.json",
        )
        for file_name in child_reports:
            with self.subTest(file_name=file_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    _write_valid_report_bundle(root)
                    report_path = root / file_name
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    payload["raw_payload"] = {"secret_like": "raw-debug"}
                    report_path.write_text(json.dumps(payload), encoding="utf-8")

                    result = report_bundle.validate_report_bundle(root)
                    rendered = report_bundle.format_summary(result)
                    report = result.to_dict()

                self.assertFalse(result.ok)
                self.assertIn("report_top_level_fields_invalid", report["error_codes"])
                self.assertEqual(
                    1,
                    report["error_code_counts"]["report_top_level_fields_invalid"],
                )
                self.assertIn("top-level fields contain unsupported fields", rendered)

    def test_child_json_report_top_level_counts_must_be_non_negative_integers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["scenario_count"] = -1
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_top_level_field_values_invalid",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"]["report_top_level_field_values_invalid"],
        )
        self.assertIn(
            "top-level fields have invalid types or ranges: scenario_count",
            rendered,
        )

    def test_child_json_report_version_fields_reject_booleans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["manifest_version"] = True
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_version_invalid",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"]["report_version_invalid"],
        )
        self.assertIn("`manifest_version` must be an integer >= 1", rendered)

    def test_child_json_report_top_level_lists_must_be_string_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["layers"] = [{"raw": "debug"}]
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_top_level_field_values_invalid",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"]["report_top_level_field_values_invalid"],
        )
        self.assertIn(
            "top-level fields have invalid types or ranges: layers",
            rendered,
        )

    def test_coverage_report_rows_reject_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["rows"][0]["raw_payload"] = {"secret_like": "raw-row-debug"}
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_rows_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_rows_invalid"],
        )
        self.assertIn("fields must match coverage row schema", rendered)

    def test_coverage_report_row_count_must_match_requirement_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["rows"] = payload["rows"][:-1]
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_rows_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_rows_mismatch"],
        )
        self.assertIn("`rows` length must match requirement_count", rendered)

    def test_coverage_report_external_mode_counts_must_match_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["synthetic_external_gap_count"] = 1
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_external_mode_counts_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_external_mode_counts_mismatch"],
        )
        self.assertIn("synthetic_external_gap_count", rendered)
        self.assertIn("must match coverage rows", rendered)

    def test_coverage_report_layers_must_match_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_json_path = root / "runtime-evidence-coverage.json"
            coverage_md_path = root / "runtime-evidence-coverage.md"
            payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
            original_layers = ", ".join(payload["layers"])
            payload["layers"] = [*payload["layers"], "Wiii Drift"]
            changed_layers = ", ".join(payload["layers"])
            coverage_json_path.write_text(json.dumps(payload), encoding="utf-8")
            coverage_md_path.write_text(
                coverage_md_path.read_text(encoding="utf-8").replace(
                    f"- Layers: `{original_layers}`",
                    f"- Layers: `{changed_layers}`",
                ),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_layers_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_layers_mismatch"],
        )
        self.assertIn("layers summary must match coverage row layers", rendered)

    def test_coverage_report_must_match_registry_validation_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["registry_fingerprint_sha256"] = "0" * 64
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_registry_coverage_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_registry_coverage_mismatch"],
        )
        self.assertIn(
            "coverage report must match runtime-evidence-registry-validation.json "
            "for registry_fingerprint_sha256",
            rendered,
        )

    def test_coverage_report_must_match_registry_validation_identity_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_json_path = root / "runtime-evidence-coverage.json"
            coverage_md_path = root / "runtime-evidence-coverage.md"
            payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
            original_name = payload["registry_name"]
            original_path = payload["registry_path"]
            payload["registry_name"] = "Operator Supplied Registry"
            payload["registry_path"] = "operator/supplied/registry.json"
            coverage_json_path.write_text(json.dumps(payload), encoding="utf-8")
            coverage_md_path.write_text(
                coverage_md_path.read_text(encoding="utf-8")
                .replace(
                    f"- Registry name: `{original_name}`",
                    "- Registry name: `Operator Supplied Registry`",
                )
                .replace(
                    f"- Registry: `{original_path}`",
                    "- Registry: `operator/supplied/registry.json`",
                ),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_registry_coverage_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_registry_coverage_mismatch"],
        )
        self.assertIn(
            "coverage report must match runtime-evidence-registry-validation.json "
            "for registry_name, registry_path",
            rendered,
        )

    def test_coverage_report_must_match_registry_validation_requirement_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            registry_path = root / "runtime-evidence-registry-validation.json"
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            payload["requirement_count"] = payload["requirement_count"] + 1
            registry_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_registry_coverage_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_registry_coverage_mismatch"],
        )
        self.assertIn(
            "coverage report must match runtime-evidence-registry-validation.json "
            "for requirement_count",
            rendered,
        )

    def test_coverage_rows_must_match_current_registry_upload_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_json_path = root / "runtime-evidence-coverage.json"
            coverage_md_path = root / "runtime-evidence-coverage.md"
            payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
            old_token = payload["rows"][0]["artifact_tokens"][0]
            new_token = "operator-supplied-evidence-${{ github.run_id }}"
            payload["rows"][0]["artifact_tokens"] = [new_token]
            coverage_json_path.write_text(json.dumps(payload), encoding="utf-8")
            coverage_md_path.write_text(
                coverage_md_path.read_text(encoding="utf-8").replace(
                    old_token,
                    new_token,
                ),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_registry_coverage_row_mismatch",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"]["report_registry_coverage_row_mismatch"],
        )
        self.assertIn(
            "coverage rows must match current runtime evidence registry",
            rendered,
        )
        self.assertIn("artifact_tokens", rendered)

    def test_coverage_rows_must_match_current_registry_external_contract_flags(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_json_path = root / "runtime-evidence-coverage.json"
            coverage_md_path = root / "runtime-evidence-coverage.md"
            payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
            credentialed_flag = payload["rows"][0]["credentialed_external_flags"][0]
            payload["rows"][0]["credentialed_external_flags"] = []
            coverage_json_path.write_text(json.dumps(payload), encoding="utf-8")
            coverage_md_path.write_text(
                coverage_md_path.read_text(encoding="utf-8").replace(
                    f"credentialed:{credentialed_flag}",
                    "credentialed:-",
                ),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_registry_coverage_row_mismatch",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"]["report_registry_coverage_row_mismatch"],
        )
        self.assertIn(
            "coverage rows must match current runtime evidence registry",
            rendered,
        )
        self.assertIn("credentialed_external_flags", rendered)

    def test_coverage_markdown_must_match_coverage_json_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_json_path = root / "runtime-evidence-coverage.json"
            coverage_md_path = root / "runtime-evidence-coverage.md"
            payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
            markdown = coverage_md_path.read_text(encoding="utf-8")
            coverage_md_path.write_text(
                markdown.replace(payload["registry_fingerprint_sha256"], "0" * 64),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_markdown_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_markdown_mismatch"],
        )
        self.assertIn(
            "coverage Markdown must match runtime-evidence-coverage.json",
            rendered,
        )
        self.assertIn("Registry fingerprint SHA-256", rendered)

    def test_coverage_markdown_row_count_must_match_coverage_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_md_path = root / "runtime-evidence-coverage.md"
            lines = coverage_md_path.read_text(encoding="utf-8").splitlines()
            row_indices = [
                index
                for index, line in enumerate(lines)
                if line.startswith("| ") and not line.startswith("| Requirement ")
            ]
            del lines[row_indices[-1]]
            coverage_md_path.write_text("\n".join(lines), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_markdown_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_markdown_mismatch"],
        )
        self.assertIn("coverage table row count", rendered)

    def test_coverage_markdown_summary_values_must_match_coverage_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_md_path = root / "runtime-evidence-coverage.md"
            coverage_md_path.write_text(
                coverage_md_path.read_text(encoding="utf-8").replace(
                    "synthetic_external_gap=0",
                    "synthetic_external_gap=1",
                ),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_markdown_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_markdown_mismatch"],
        )
        self.assertIn("External evidence", rendered)

    def test_coverage_markdown_table_rows_must_match_coverage_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_md_path = root / "runtime-evidence-coverage.md"
            lines = coverage_md_path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if line.startswith("| provider-runtime-tool-loop |"):
                    lines[index] = line.replace(
                        "provider-runtime-evidence.json",
                        "operator-supplied-evidence.json",
                    )
                    break
            else:
                self.fail("provider runtime coverage row not found")
            coverage_md_path.write_text("\n".join(lines), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_markdown_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_markdown_mismatch"],
        )
        self.assertIn("coverage table row mismatch", rendered)

    def test_self_harness_report_must_match_current_manifest_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["manifest_fingerprint_sha256"] = "0" * 64
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_current_manifest_fingerprint_mismatch",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"][
                "report_current_manifest_fingerprint_mismatch"
            ],
        )
        self.assertIn(
            "manifest_fingerprint_sha256 must match current Wiii Self-Harness manifest",
            rendered,
        )

    def test_registry_report_must_match_current_registry_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            fake_fingerprint = "0" * 64
            registry_path = root / "runtime-evidence-registry-validation.json"
            coverage_json_path = root / "runtime-evidence-coverage.json"
            coverage_md_path = root / "runtime-evidence-coverage.md"

            registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
            registry_payload["registry_fingerprint_sha256"] = fake_fingerprint
            registry_path.write_text(json.dumps(registry_payload), encoding="utf-8")

            coverage_payload = json.loads(
                coverage_json_path.read_text(encoding="utf-8")
            )
            original_fingerprint = coverage_payload["registry_fingerprint_sha256"]
            coverage_payload["registry_fingerprint_sha256"] = fake_fingerprint
            coverage_json_path.write_text(
                json.dumps(coverage_payload),
                encoding="utf-8",
            )
            coverage_md_path.write_text(
                coverage_md_path.read_text(encoding="utf-8").replace(
                    original_fingerprint,
                    fake_fingerprint,
                ),
                encoding="utf-8",
            )

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn(
            "report_current_registry_fingerprint_mismatch",
            report["error_codes"],
        )
        self.assertEqual(
            1,
            report["error_code_counts"][
                "report_current_registry_fingerprint_mismatch"
            ],
        )
        self.assertIn(
            "registry_fingerprint_sha256 must match current runtime evidence registry",
            rendered,
        )

    def test_coverage_report_row_counts_must_be_non_negative_integers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["rows"][0]["payload_checks"] = -1
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_row_values_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_row_values_invalid"],
        )
        self.assertIn("values have invalid types or ranges: payload_checks", rendered)

    def test_coverage_report_target_flag_must_match_payload_freshness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["rows"][0]["coverage_target_met"])
            payload["rows"][0]["coverage_target_met"] = False
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_row_values_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_row_values_invalid"],
        )
        self.assertIn("coverage_target_met", rendered)

    def test_coverage_report_row_lists_must_be_string_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["rows"][0]["identifier_strategies"] = [{"raw": "debug"}]
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_row_values_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_row_values_invalid"],
        )
        self.assertIn(
            "values have invalid types or ranges: identifier_strategies",
            rendered,
        )

    def test_coverage_report_upload_fields_must_be_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["rows"][0]["artifact_tokens"] = [{"raw": "debug"}]
            payload["rows"][0]["diagnostic_upload_count"] = "1"
            payload["rows"][0]["diagnostic_upload_artifacts"] = [True]
            payload["rows"][0]["diagnostic_upload_paths"] = [{"path": "debug"}]
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_row_values_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_row_values_invalid"],
        )
        self.assertIn("artifact_tokens", rendered)
        self.assertIn("diagnostic_upload_count", rendered)
        self.assertIn("diagnostic_upload_artifacts", rendered)
        self.assertIn("diagnostic_upload_paths", rendered)

    def test_coverage_report_external_mode_lists_must_be_string_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["rows"][0]["synthetic_gap_flags"] = [{"raw": "debug"}]
            payload["rows"][0]["credentialed_external_flags"] = [True]
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_coverage_row_values_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_coverage_row_values_invalid"],
        )
        self.assertIn("credentialed_external_flags", rendered)
        self.assertIn("synthetic_gap_flags", rendered)

    def test_coverage_report_error_code_counts_must_be_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["error_code_counts"] = {"coverage_error": "1"}
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_error_code_counts_invalid", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_error_code_counts_invalid"],
        )
        self.assertIn("must map string codes to non-negative integers", rendered)

    def test_child_json_report_error_code_counts_must_be_empty_when_successful(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["error_code_counts"] = {"manifest_load_failed": 1}
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_error_code_counts_not_empty", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_error_code_counts_not_empty"],
        )
        self.assertIn("`error_code_counts` must be empty when bundled", rendered)

    def test_child_json_report_internal_error_lists_must_be_empty_when_successful(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            coverage_path = root / "runtime-evidence-coverage.json"
            payload = json.loads(coverage_path.read_text(encoding="utf-8"))
            payload["coverage_errors"] = [
                "provider-runtime-tool-loop: payload_checks=0 must be >= freshness_hours=72"
            ]
            coverage_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_internal_error_lists_not_empty", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_internal_error_lists_not_empty"],
        )
        self.assertIn("`coverage_errors` must be empty when bundled", rendered)

    def test_child_json_report_error_code_counts_must_match_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["ok"] = False
            payload["error_codes"] = ["manifest_load_failed"]
            payload["error_code_counts"] = {"manifest_unknown_field": 1}
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_error_code_counts_key_mismatch", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_error_code_counts_key_mismatch"],
        )
        self.assertIn("`error_code_counts` keys must match `error_codes`", rendered)

    def test_child_json_report_error_codes_must_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["ok"] = False
            payload["error_codes"] = ["manifest_load_failed", "manifest_load_failed"]
            payload["error_code_counts"] = {"manifest_load_failed": 2}
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_error_codes_duplicate", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_error_codes_duplicate"],
        )
        self.assertIn("`error_codes` must not contain duplicate entries", rendered)

    def test_child_json_report_error_code_counts_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["ok"] = False
            payload["error_codes"] = ["manifest_load_failed"]
            payload["error_code_counts"] = {"manifest_load_failed": 0}
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_error_code_counts_non_positive", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_error_code_counts_non_positive"],
        )
        self.assertIn("values must be positive for listed error codes", rendered)

    def test_child_json_report_must_be_successful(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            harness_path = root / "self-harness-validation.json"
            payload = json.loads(harness_path.read_text(encoding="utf-8"))
            payload["ok"] = False
            payload["error_codes"] = ["manifest_load_failed"]
            harness_path.write_text(json.dumps(payload), encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertIn("report_ok_false", report["error_codes"])
        self.assertIn("report_error_codes_not_empty", report["error_codes"])
        self.assertEqual(1, report["error_code_counts"]["report_ok_false"])
        self.assertEqual(
            1,
            report["error_code_counts"]["report_error_codes_not_empty"],
        )
        self.assertIn("report_ok_false", rendered)

    def test_self_validation_report_must_be_successful(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["ok"] = False
            payload["error_codes"] = ["report_file_missing"]
            payload["error_code_counts"] = {"report_file_missing": 1}
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)
            report = second_result.to_dict()

        self.assertFalse(second_result.ok)
        self.assertIn("report_ok_false", report["error_codes"])
        self.assertIn("report_error_codes_not_empty", report["error_codes"])

    def test_self_validation_report_rejects_extra_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["raw_payload"] = "raw-local-token"
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_top_level_fields_invalid",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_rejects_missing_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload.pop("passed_count")
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_top_level_fields_invalid",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_rejects_summary_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["passed_count"] = 3
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_summary_count_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_rejects_error_code_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            payload = first_result.to_dict()
            payload["error_code_counts"] = {"report_file_missing": 1}
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            second_result = report_bundle.validate_report_bundle(root)

        self.assertFalse(second_result.ok)
        self.assertIn(
            "report_error_code_counts_mismatch",
            second_result.to_dict()["error_codes"],
        )

    def test_self_validation_report_rejects_stale_shape_after_unexpected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            first_result = report_bundle.validate_report_bundle(root)
            (root / report_bundle.SELF_VALIDATION_REPORT_NAME).write_text(
                json.dumps(first_result.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            (root / "operator-note.json").write_text("{}", encoding="utf-8")

            second_result = report_bundle.validate_report_bundle(root)
            report = second_result.to_dict()

        self.assertFalse(second_result.ok)
        self.assertIn("unexpected_report_file", report["error_codes"])
        self.assertIn("report_rows_mismatch", report["error_codes"])

    def test_unexpected_report_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            (root / "operator-note.json").write_text("{}", encoding="utf-8")

            result = report_bundle.validate_report_bundle(root)

        self.assertFalse(result.ok)
        self.assertEqual(1, result.unexpected_count)
        self.assertIn("unexpected_report_file", result.to_dict()["error_codes"])

    def test_unexpected_report_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_valid_report_bundle(root)
            (root / "operator-notes").mkdir()

            result = report_bundle.validate_report_bundle(root)
            rendered = report_bundle.format_summary(result)
            report = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(1, result.unexpected_count)
        self.assertIn("unexpected_report_directory", report["error_codes"])
        self.assertEqual(
            1,
            report["error_code_counts"]["unexpected_report_directory"],
        )
        self.assertIn("unexpected report directory 'operator-notes'", rendered)

    def test_cli_json_reports_missing_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            missing_root = Path(temp_dir) / "missing"
            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main([str(missing_root), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(["bundle_root_missing"], payload["error_codes"])
        self.assertEqual({"bundle_root_missing": 1}, payload["error_code_counts"])

    def test_cli_json_can_write_report_bundle_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "bundle"
            root.mkdir()
            _write_valid_report_bundle(root)
            out_path = Path(temp_dir) / "report-bundle-validation.json"

            exit_code = report_bundle.main(
                [str(root), "--json", "--out", str(out_path)]
            )

            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertRegex(payload["bundle_fingerprint_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(4, payload["fingerprinted_report_count"])
        self.assertEqual({}, payload["error_code_counts"])

    def test_cli_rejects_report_output_inside_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "bundle"
            root.mkdir()
            _write_valid_report_bundle(root)
            out_path = root / report_bundle.SELF_VALIDATION_REPORT_NAME
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--out", str(out_path)]
                )

            payload = json.loads(stdout.getvalue())
            out_exists = out_path.exists()

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(
            ["report_bundle_output_path_inside_bundle_root"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"report_bundle_output_path_inside_bundle_root": 1},
            payload["error_code_counts"],
        )
        self.assertFalse(out_exists)

    def test_cli_rejects_report_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "bundle"
            root.mkdir()
            _write_valid_report_bundle(root)
            out_path = Path(temp_dir) / "report-output"
            out_path.mkdir()
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--out", str(out_path)]
                )

            payload = json.loads(stdout.getvalue())
            out_entries = list(out_path.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(
            ["report_bundle_output_path_directory"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"report_bundle_output_path_directory": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], out_entries)

    def test_cli_rejects_report_output_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "bundle"
            root.mkdir()
            _write_valid_report_bundle(root)
            target_out_path = Path(temp_dir) / "report-output-target.json"
            target_out_path.write_text("keep", encoding="utf-8")
            out_path = Path(temp_dir) / "report-output.json"
            try:
                os.symlink(target_out_path, out_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--out", str(out_path)]
                )

            payload = json.loads(stdout.getvalue())
            target_text = target_out_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(
            ["report_bundle_output_path_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"report_bundle_output_path_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual("keep", target_text)

    def test_cli_rejects_report_output_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "bundle"
            root.mkdir()
            _write_valid_report_bundle(root)
            target_dir = Path(temp_dir) / "target-dir"
            target_dir.mkdir()
            symlink_parent = Path(temp_dir) / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            out_path = symlink_parent / "report-output.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--out", str(out_path)]
                )

            payload = json.loads(stdout.getvalue())
            target_entries = list(target_dir.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            report_bundle.REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(
            ["report_bundle_output_path_parent_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"report_bundle_output_path_parent_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], target_entries)

    def test_cli_rejects_report_output_symlink_target_inside_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            _write_valid_report_bundle(root)
            target_out_path = root / report_bundle.SELF_VALIDATION_REPORT_NAME
            target_out_path.write_text("", encoding="utf-8")
            out_path = base / report_bundle.SELF_VALIDATION_REPORT_NAME
            try:
                os.symlink(target_out_path, out_path)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = report_bundle.main(
                    [str(root), "--json", "--out", str(out_path)]
                )

            payload = json.loads(stdout.getvalue())
            target_contents = target_out_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["report_bundle_output_path_inside_bundle_root"],
            payload["error_codes"],
        )
        self.assertEqual("", target_contents)


if __name__ == "__main__":
    unittest.main()
