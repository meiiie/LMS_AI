import contextlib
import io
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_runtime_evidence_bundle as bundle_validator


def _sample_registry() -> dict:
    return {
        "registry": bundle_validator.REGISTRY_NAME,
        "version": 1,
        "requirements": [
            {
                "id": "sample-a",
                "artifact": "sample-a.json",
                "schema_version": "wiii.sample_a.v1",
                "freshness": {"timestamp_path": "generated_at", "max_age_hours": 72},
                "payload_schema_field": "schema_version",
                "forbidden_payload_tokens": ["secret"],
                "forbidden_payload_regexes": [],
                "payload_checks": [{"path": "status", "equals": "pass"}],
            },
            {
                "id": "sample-b",
                "artifact": "sample-b.json",
                "schema_version": "wiii.sample_b.v1",
                "freshness": {"timestamp_path": "generated_at", "max_age_hours": 72},
                "payload_schema_field": "schema_version",
                "forbidden_payload_tokens": [],
                "forbidden_payload_regexes": [],
                "payload_checks": [{"path": "count", "min": 2}],
            },
        ]
    }


def _sample_registry_with(requirements: list[dict]) -> dict:
    return {
        "registry": bundle_validator.REGISTRY_NAME,
        "version": 1,
        "requirements": requirements,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_report_bundle_coverage(
    root: Path,
    registry: dict,
    *,
    fingerprint: str | None = None,
    registry_version: int | None = None,
    requirement_count: int | None = None,
) -> None:
    requirements = registry.get("requirements")
    _write_json(
        root / "runtime-evidence-coverage.json",
        {
            "registry_fingerprint_sha256": (
                fingerprint or bundle_validator._registry_fingerprint(registry)
            ),
            "registry_version": (
                registry_version
                if registry_version is not None
                else registry.get("version")
            ),
            "requirement_count": (
                requirement_count
                if requirement_count is not None
                else len(requirements)
                if isinstance(requirements, list)
                else None
            ),
        },
    )


def _valid_report_bundle_result(
    *,
    fingerprint: str = "f" * 64,
    validation_schema_version: str = "wiii.self_harness_report_bundle_validation.v1",
):
    return mock.Mock(
        ok=True,
        to_dict=mock.Mock(
            return_value={
                "bundle_fingerprint_sha256": fingerprint,
                "validation_schema_version": validation_schema_version,
                "error_codes": [],
                "rows": [],
            }
        ),
    )


class RuntimeEvidenceBundleTests(unittest.TestCase):
    as_of = "2026-06-01T12:00:00+00:00"

    def test_complete_bundle_passes(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "nested" / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:30:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(2, report.passed_count)
        self.assertEqual(0, report.missing_count)
        self.assertEqual(0, report.failed_count)
        self.assertEqual(0, report.unexpected_count)
        self.assertEqual(2, report.requirement_count)
        self.assertEqual(2, report.row_count)
        self.assertEqual([], report.error_codes)
        self.assertEqual({}, report.error_code_counts)
        self.assertEqual(
            bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            report.schema_version,
        )
        self.assertEqual(bundle_validator.REGISTRY_NAME, report.registry_name)
        self.assertEqual(1, report.registry_version)
        self.assertEqual("2026-06-01T12:00:00Z", report.validated_at)
        self.assertIsNone(report.self_harness_report_bundle_root)
        self.assertIsNone(report.self_harness_report_bundle_fingerprint_sha256)
        self.assertIsNone(report.self_harness_report_bundle_validation_schema_version)
        self.assertFalse(report.completion_audit_ready)
        self.assertFalse(report.to_dict()["completion_audit_ready"])
        self.assertRegex(report.registry_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(
            report.completion_audit_fingerprint_sha256,
            r"^[0-9a-f]{64}$",
        )
        for row in report.rows:
            self.assertIsNotNone(row.artifact_sha256)
            self.assertRegex(row.artifact_sha256 or "", r"^[0-9a-f]{64}$")

    def test_missing_artifact_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(1, report.missing_count)
        self.assertTrue(any(row.status == "missing" for row in report.rows))

    def test_registry_identity_is_required(self) -> None:
        registry = _sample_registry()
        registry["registry"] = "Unexpected Evidence Registry"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "registry `registry`"):
                bundle_validator.validate_bundle(
                    registry=registry,
                    bundle_root=root,
                    as_of=bundle_validator._parse_timestamp(self.as_of),
                )

    def test_registry_version_is_required(self) -> None:
        registry = _sample_registry()
        registry["version"] = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "registry `version`"):
                bundle_validator.validate_bundle(
                    registry=registry,
                    bundle_root=root,
                    as_of=bundle_validator._parse_timestamp(self.as_of),
                )

    def test_registry_version_rejects_boolean(self) -> None:
        registry = _sample_registry()
        registry["version"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "registry `version`"):
                bundle_validator.validate_bundle(
                    registry=registry,
                    bundle_root=root,
                    as_of=bundle_validator._parse_timestamp(self.as_of),
                )

    def test_registry_requirements_must_not_be_empty(self) -> None:
        registry = _sample_registry()
        registry["requirements"] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "non-empty list"):
                bundle_validator.validate_bundle(
                    registry=registry,
                    bundle_root=root,
                    as_of=bundle_validator._parse_timestamp(self.as_of),
                )

    def test_bundle_root_symlink_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            target = base / "target"
            target.mkdir()
            link = base / "bundle-link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink not available: {exc}")

            with self.assertRaisesRegex(ValueError, "bundle root must not be a symlink"):
                bundle_validator.validate_bundle(
                    registry=registry,
                    bundle_root=link,
                    as_of=bundle_validator._parse_timestamp(self.as_of),
                )

    def test_invalid_artifact_payload_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 1,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            rendered = bundle_validator.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertEqual(1, report.failed_count)
        self.assertIn("sample-b", rendered)
        self.assertIn("count", rendered)
        self.assertIn("SHA-256", rendered)

    def test_boolean_freshness_max_age_is_not_treated_as_one_hour(self) -> None:
        registry = _sample_registry_with(
            [
                {
                    "id": "sample-a",
                    "artifact": "sample-a.json",
                    "schema_version": "wiii.sample_a.v1",
                    "freshness": {
                        "timestamp_path": "generated_at",
                        "max_age_hours": True,
                    },
                    "payload_schema_field": "schema_version",
                    "forbidden_payload_tokens": [],
                    "forbidden_payload_regexes": [],
                    "payload_checks": [{"path": "status", "equals": "pass"}],
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T11:30:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(1, report.failed_count)
        self.assertIn("freshness_max_age_hours_missing", report.error_codes)

    def test_freshness_reader_rejects_non_finite_json_numbers(self) -> None:
        registry = _sample_registry_with(
            [
                {
                    "id": "sample-a",
                    "artifact": "sample-a.json",
                    "schema_version": "wiii.sample_a.v1",
                    "freshness": {
                        "timestamp_path": "generated_at",
                        "max_age_hours": 72,
                    },
                    "payload_schema_field": "schema_version",
                    "forbidden_payload_tokens": [],
                    "forbidden_payload_regexes": [],
                    "payload_checks": [{"path": "status", "equals": "pass"}],
                }
            ]
        )
        requirement = registry["requirements"][0]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_path = root / "sample-a.json"
            artifact_path.write_text(
                '{"schema_version": "wiii.sample_a.v1", '
                '"status": "pass", '
                '"generated_at": "2026-06-01T11:30:00+00:00", '
                '"duration_ms": NaN}',
                encoding="utf-8",
            )

            result = bundle_validator.validate_freshness(
                requirement=requirement,
                artifact_path=artifact_path,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertTrue(result["errors"], result)
        self.assertTrue(
            any("non-finite JSON number" in error for error in result["errors"]),
            result,
        )

    def test_freshness_reader_rejects_duplicate_json_keys(self) -> None:
        registry = _sample_registry_with(
            [
                {
                    "id": "sample-a",
                    "artifact": "sample-a.json",
                    "schema_version": "wiii.sample_a.v1",
                    "freshness": {
                        "timestamp_path": "generated_at",
                        "max_age_hours": 72,
                    },
                    "payload_schema_field": "schema_version",
                    "forbidden_payload_tokens": [],
                    "forbidden_payload_regexes": [],
                    "payload_checks": [{"path": "status", "equals": "pass"}],
                }
            ]
        )
        requirement = registry["requirements"][0]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_path = root / "sample-a.json"
            artifact_path.write_text(
                '{"schema_version": "wiii.sample_a.v1", '
                '"generated_at": "2026-06-01T11:30:00+00:00", '
                '"generated_at": "2026-06-01T11:45:00+00:00"}',
                encoding="utf-8",
            )

            result = bundle_validator.validate_freshness(
                requirement=requirement,
                artifact_path=artifact_path,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertTrue(result["errors"], result)
        self.assertTrue(
            any("duplicate JSON object key" in error for error in result["errors"]),
            result,
        )

    def test_bundle_report_exposes_normalized_error_codes(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 1,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            rendered = bundle_validator.format_markdown(report)
            payload = report.to_dict()

        failed_rows = [row for row in payload["rows"] if row["status"] == "failed"]
        self.assertEqual(1, len(failed_rows), payload)
        self.assertEqual(
            ["payload_check_min_mismatch"],
            failed_rows[0]["error_codes"],
        )
        self.assertEqual(
            {"payload_check_min_mismatch": 1},
            payload["error_code_counts"],
        )
        self.assertEqual(
            ["payload_check_min_mismatch"],
            payload["error_codes"],
        )
        self.assertEqual(["payload_check_min_mismatch"], report.error_codes)
        self.assertIn("Error codes", rendered)
        self.assertIn("- Error codes: `payload_check_min_mismatch`", rendered)
        self.assertIn("- Error code counts: `payload_check_min_mismatch=1`", rendered)
        self.assertIn("payload_check_min_mismatch", rendered)

    def test_bundle_uses_artifact_error_code_taxonomy_for_payload_errors(self) -> None:
        errors = [
            "artifact: schema_version must be 'wiii.sample_a.v1', got 'wiii.other.v1'",
            "payload_checks[0]: count must be >= 2, got [1]",
        ]

        for error in errors:
            self.assertEqual(
                bundle_validator.normalize_artifact_error_code(error),
                bundle_validator._error_code(error),
            )

    def test_markdown_table_cells_collapse_layout_breaks(self) -> None:
        row = bundle_validator.BundleRow(
            requirement_id="sample-a",
            artifact="sample-a.json",
            status="failed",
            path="bundle\npath|with-pipe",
            artifact_sha256=None,
            checks_passed=0,
            generated_at=None,
            max_age_hours=None,
            age_hours=None,
            errors=["first line\nsecond\tline|pipe"],
        )
        report = bundle_validator.BundleReport(
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            registry_name=bundle_validator.REGISTRY_NAME,
            registry_version=1,
            bundle_root="bundle",
            validated_at="2026-06-01T12:00:00Z",
            registry_fingerprint_sha256="0" * 64,
            bundle_fingerprint_sha256="1" * 64,
            completion_audit_fingerprint_sha256="2" * 64,
            self_harness_report_bundle_root=None,
            self_harness_report_bundle_fingerprint_sha256=None,
            self_harness_report_bundle_validation_schema_version=None,
            requirement_count=1,
            row_count=1,
            passed_count=0,
            missing_count=0,
            failed_count=1,
            unexpected_count=0,
            error_codes=["validation_error"],
            error_code_counts={"validation_error": 1},
            rows=[row],
        )

        rendered = bundle_validator.format_markdown(report)
        data_rows = [
            line
            for line in rendered.splitlines()
            if line.startswith("| sample-a |")
        ]

        self.assertEqual(1, len(data_rows), rendered)
        self.assertIn("bundle path\\|with-pipe", data_rows[0])
        self.assertIn("first line second line\\|pipe", data_rows[0])

    def test_bundle_report_exposes_schema_version(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            payload = report.to_dict()
            rendered = bundle_validator.format_markdown(report)

        self.assertEqual(
            bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertIn(
            f"- Schema version: `{bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION}`",
            rendered,
        )

    def test_bundle_report_exposes_registry_identity(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        sample_registry["version"] = 3
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            payload = report.to_dict()
            rendered = bundle_validator.format_markdown(report)

        self.assertEqual(bundle_validator.REGISTRY_NAME, payload["registry_name"])
        self.assertEqual(3, payload["registry_version"])
        self.assertIn(f"- Registry name: `{bundle_validator.REGISTRY_NAME}`", rendered)
        self.assertIn("- Registry version: `3`", rendered)

    def test_bundle_report_includes_artifact_sha256(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            rendered = bundle_validator.format_markdown(report)
            payload = report.to_dict()

        row = report.rows[0]
        self.assertTrue(report.ok, report.to_dict())
        self.assertIsNotNone(row.artifact_sha256)
        self.assertRegex(row.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertIn(row.artifact_sha256 or "", rendered)
        self.assertEqual(row.artifact_sha256, payload["rows"][0]["artifact_sha256"])

    def test_bundle_report_includes_bundle_fingerprint(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "sample-a.json"
            _write_json(
                artifact,
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            first_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            rendered = bundle_validator.format_markdown(first_report)
            payload = first_report.to_dict()

            _write_json(
                artifact,
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:30:00+00:00",
                },
            )
            second_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertTrue(first_report.ok, first_report.to_dict())
        self.assertEqual("2026-06-01T12:00:00Z", first_report.validated_at)
        self.assertRegex(first_report.registry_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(first_report.bundle_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(
            first_report.completion_audit_fingerprint_sha256,
            r"^[0-9a-f]{64}$",
        )
        self.assertIn("2026-06-01T12:00:00Z", rendered)
        self.assertIn(first_report.registry_fingerprint_sha256, rendered)
        self.assertIn(first_report.bundle_fingerprint_sha256, rendered)
        self.assertIn("Completion audit fingerprint SHA-256", rendered)
        self.assertIn(first_report.completion_audit_fingerprint_sha256, rendered)
        self.assertIn("Completion audit ready", rendered)
        self.assertFalse(first_report.completion_audit_ready)
        self.assertFalse(payload["completion_audit_ready"])
        self.assertEqual("2026-06-01T12:00:00Z", payload["validated_at"])
        self.assertEqual(
            first_report.registry_fingerprint_sha256,
            payload["registry_fingerprint_sha256"],
        )
        self.assertEqual(
            first_report.bundle_fingerprint_sha256,
            payload["bundle_fingerprint_sha256"],
        )
        self.assertEqual(
            first_report.completion_audit_fingerprint_sha256,
            payload["completion_audit_fingerprint_sha256"],
        )
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )

    def test_bundle_fingerprint_changes_when_validated_at_changes(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            first_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp("2026-06-01T12:00:00+00:00"),
            )
            second_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp("2026-06-01T12:30:00+00:00"),
            )

        self.assertTrue(first_report.ok, first_report.to_dict())
        self.assertTrue(second_report.ok, second_report.to_dict())
        self.assertNotEqual(first_report.validated_at, second_report.validated_at)
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )
        self.assertNotEqual(
            first_report.completion_audit_fingerprint_sha256,
            second_report.completion_audit_fingerprint_sha256,
        )

    def test_bundle_fingerprint_changes_when_schema_version_changes(self) -> None:
        row = bundle_validator.BundleRow(
            requirement_id="sample-a",
            artifact="sample-a.json",
            status="passed",
            path=str(Path("bundle") / "sample-a.json"),
            artifact_sha256="0" * 64,
            checks_passed=3,
            generated_at="2026-06-01T10:00:00+00:00",
            max_age_hours=72,
            age_hours=2.0,
            errors=[],
        )

        first_fingerprint = bundle_validator._bundle_fingerprint(
            [row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )
        second_fingerprint = bundle_validator._bundle_fingerprint(
            [row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version="wiii.runtime_evidence_bundle_report.v2",
            validated_at="2026-06-01T12:00:00Z",
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_bundle_fingerprint_changes_when_age_hours_changes(self) -> None:
        first_row = bundle_validator.BundleRow(
            requirement_id="sample-a",
            artifact="sample-a.json",
            status="passed",
            path=str(Path("bundle") / "sample-a.json"),
            artifact_sha256="0" * 64,
            checks_passed=3,
            generated_at="2026-06-01T10:00:00+00:00",
            max_age_hours=72,
            age_hours=2.0,
            errors=[],
        )
        second_row = bundle_validator.BundleRow(
            requirement_id=first_row.requirement_id,
            artifact=first_row.artifact,
            status=first_row.status,
            path=first_row.path,
            artifact_sha256=first_row.artifact_sha256,
            checks_passed=first_row.checks_passed,
            generated_at=first_row.generated_at,
            max_age_hours=first_row.max_age_hours,
            age_hours=2.5,
            errors=first_row.errors,
        )

        first_fingerprint = bundle_validator._bundle_fingerprint(
            [first_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )
        second_fingerprint = bundle_validator._bundle_fingerprint(
            [second_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_completion_audit_fingerprint_changes_when_report_bundle_changes(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            first_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
                report_bundle_link=bundle_validator.ReportBundleLink(
                    bundle_root="reports-a",
                    bundle_fingerprint_sha256="a" * 64,
                    validation_schema_version=(
                        "wiii.self_harness_report_bundle_validation.v1"
                    ),
                ),
            )
            second_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
                report_bundle_link=bundle_validator.ReportBundleLink(
                    bundle_root="reports-b",
                    bundle_fingerprint_sha256="b" * 64,
                    validation_schema_version=(
                        "wiii.self_harness_report_bundle_validation.v1"
                    ),
                ),
            )

        self.assertEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )
        self.assertTrue(first_report.completion_audit_ready)
        self.assertTrue(first_report.to_dict()["completion_audit_ready"])
        self.assertNotEqual(
            first_report.completion_audit_fingerprint_sha256,
            second_report.completion_audit_fingerprint_sha256,
        )

    def test_bundle_fingerprint_changes_when_artifact_path_changes(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = {
                "schema_version": "wiii.sample_a.v1",
                "status": "pass",
                "generated_at": "2026-06-01T10:00:00+00:00",
            }
            first_artifact = root / "sample-a.json"
            second_artifact = root / "nested" / "sample-a.json"
            _write_json(first_artifact, payload)

            first_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            first_artifact.unlink()
            _write_json(second_artifact, payload)
            second_report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertTrue(first_report.ok, first_report.to_dict())
        self.assertTrue(second_report.ok, second_report.to_dict())
        self.assertEqual(
            first_report.rows[0].artifact_sha256,
            second_report.rows[0].artifact_sha256,
        )
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )

    def test_bundle_fingerprint_changes_when_error_code_changes(self) -> None:
        base_row = bundle_validator.BundleRow(
            requirement_id="sample-a",
            artifact="sample-a.json",
            status="failed",
            path=str(Path("bundle") / "sample-a.json"),
            artifact_sha256=None,
            checks_passed=0,
            generated_at=None,
            max_age_hours=72,
            age_hours=None,
            errors=["artifact path must be a file: bundle/sample-a.json"],
        )
        symlink_row = bundle_validator.BundleRow(
            requirement_id=base_row.requirement_id,
            artifact=base_row.artifact,
            status=base_row.status,
            path=base_row.path,
            artifact_sha256=base_row.artifact_sha256,
            checks_passed=base_row.checks_passed,
            generated_at=base_row.generated_at,
            max_age_hours=base_row.max_age_hours,
            age_hours=base_row.age_hours,
            errors=["artifact path must not be a symlink: bundle/sample-a.json"],
        )

        first_fingerprint = bundle_validator._bundle_fingerprint(
            [base_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )
        second_fingerprint = bundle_validator._bundle_fingerprint(
            [symlink_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )

        self.assertEqual(
            ["artifact_path_not_file"],
            bundle_validator._row_error_codes(base_row),
        )
        self.assertEqual(
            ["artifact_path_symlink"],
            bundle_validator._row_error_codes(symlink_row),
        )
        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_bundle_fingerprint_distinguishes_payload_error_codes(self) -> None:
        equals_row = bundle_validator.BundleRow(
            requirement_id="sample-a",
            artifact="sample-a.json",
            status="failed",
            path=str(Path("bundle") / "sample-a.json"),
            artifact_sha256="0" * 64,
            checks_passed=3,
            generated_at="2026-06-01T10:00:00+00:00",
            max_age_hours=72,
            age_hours=2.0,
            errors=["payload_checks[0]: status must equal 'pass', got ['fail']"],
        )
        min_row = bundle_validator.BundleRow(
            requirement_id=equals_row.requirement_id,
            artifact=equals_row.artifact,
            status=equals_row.status,
            path=equals_row.path,
            artifact_sha256=equals_row.artifact_sha256,
            checks_passed=equals_row.checks_passed,
            generated_at=equals_row.generated_at,
            max_age_hours=equals_row.max_age_hours,
            age_hours=equals_row.age_hours,
            errors=["payload_checks[0]: count must be >= 2, got [1]"],
        )

        first_fingerprint = bundle_validator._bundle_fingerprint(
            [equals_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )
        second_fingerprint = bundle_validator._bundle_fingerprint(
            [min_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )

        self.assertEqual(
            ["payload_check_equals_mismatch"],
            bundle_validator._row_error_codes(equals_row),
        )
        self.assertEqual(
            ["payload_check_min_mismatch"],
            bundle_validator._row_error_codes(min_row),
        )
        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_bundle_fingerprint_distinguishes_row_error_messages_with_same_code(
        self,
    ) -> None:
        first_row = bundle_validator.BundleRow(
            requirement_id="sample-a",
            artifact="sample-a.json",
            status="failed",
            path=str(Path("bundle") / "sample-a.json"),
            artifact_sha256="0" * 64,
            checks_passed=3,
            generated_at="2026-06-01T10:00:00+00:00",
            max_age_hours=72,
            age_hours=2.0,
            errors=["operator supplied failure A"],
        )
        second_row = bundle_validator.BundleRow(
            requirement_id=first_row.requirement_id,
            artifact=first_row.artifact,
            status=first_row.status,
            path=first_row.path,
            artifact_sha256=first_row.artifact_sha256,
            checks_passed=first_row.checks_passed,
            generated_at=first_row.generated_at,
            max_age_hours=first_row.max_age_hours,
            age_hours=first_row.age_hours,
            errors=["operator supplied failure B"],
        )

        first_fingerprint = bundle_validator._bundle_fingerprint(
            [first_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )
        second_fingerprint = bundle_validator._bundle_fingerprint(
            [second_row],
            bundle_root=Path("bundle"),
            registry_fingerprint_sha256="0" * 64,
            schema_version=bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            validated_at="2026-06-01T12:00:00Z",
        )

        self.assertEqual(["validation_error"], bundle_validator._row_error_codes(first_row))
        self.assertEqual(["validation_error"], bundle_validator._row_error_codes(second_row))
        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_bundle_fingerprint_changes_when_registry_contract_changes(self) -> None:
        first_registry = _sample_registry_with(_sample_registry()["requirements"][:1])
        second_registry = json.loads(json.dumps(first_registry))
        second_registry["requirements"][0]["payload_checks"].append(
            {
                "path": "schema_version",
                "equals": "wiii.sample_a.v1",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            first_report = bundle_validator.validate_bundle(
                registry=first_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            second_report = bundle_validator.validate_bundle(
                registry=second_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertTrue(first_report.ok, first_report.to_dict())
        self.assertTrue(second_report.ok, second_report.to_dict())
        self.assertNotEqual(
            first_report.registry_fingerprint_sha256,
            second_report.registry_fingerprint_sha256,
        )
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )

    def test_duplicate_artifact_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "one" / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "two" / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(1, report.failed_count)
        duplicate_rows = [
            row for row in report.rows if "multiple matching artifacts" in "; ".join(row.errors)
        ]
        self.assertEqual(1, len(duplicate_rows), report.rows)
        self.assertRegex(duplicate_rows[0].artifact_sha256 or "", r"^[0-9a-f]{64}$")

    def test_bundle_fingerprint_changes_when_duplicate_artifact_changes(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            duplicate_path = root / "one" / "sample-b.json"
            _write_json(
                duplicate_path,
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "two" / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            first_report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            _write_json(
                duplicate_path,
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 3,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            second_report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        first_duplicate = [
            row
            for row in first_report.rows
            if "multiple matching artifacts" in "; ".join(row.errors)
        ][0]
        second_duplicate = [
            row
            for row in second_report.rows
            if "multiple matching artifacts" in "; ".join(row.errors)
        ][0]
        self.assertFalse(first_report.ok)
        self.assertFalse(second_report.ok)
        self.assertRegex(first_duplicate.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertRegex(second_duplicate.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            first_duplicate.artifact_sha256,
            second_duplicate.artifact_sha256,
        )
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )

    def test_duplicate_symlink_artifact_reports_path_errors(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "one" / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            outside = base / "outside-sample-b.json"
            _write_json(
                outside,
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            (root / "two").mkdir()
            try:
                os.symlink(outside, root / "two" / "sample-b.json")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        duplicate_rows = [
            row for row in report.rows if "multiple matching artifacts" in "; ".join(row.errors)
        ]
        self.assertFalse(report.ok)
        self.assertEqual(1, len(duplicate_rows), report.rows)
        self.assertRegex(duplicate_rows[0].artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertTrue(
            any("symlink" in error for error in duplicate_rows[0].errors),
            duplicate_rows[0].errors,
        )

    def test_duplicate_registry_artifact_name_fails_before_search(self) -> None:
        registry = _sample_registry()
        duplicate = json.loads(json.dumps(registry["requirements"][0]))
        duplicate["id"] = "sample-a-copy"
        registry["requirements"].append(duplicate)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(2, report.failed_count)
        self.assertTrue(
            any("duplicate artifact name" in "; ".join(row.errors) for row in report.rows),
            report.rows,
        )

    def test_duplicate_requirement_id_fails_before_search(self) -> None:
        registry = _sample_registry()
        duplicate = json.loads(json.dumps(registry["requirements"][0]))
        duplicate["artifact"] = "sample-c.json"
        registry["requirements"].append(duplicate)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(2, report.failed_count)
        self.assertTrue(
            any("duplicate requirement id" in "; ".join(row.errors) for row in report.rows),
            report.rows,
        )

    def test_non_object_requirement_fails_instead_of_skipping(self) -> None:
        registry = _sample_registry()
        registry["requirements"].append("not-a-requirement-object")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(3, report.requirement_count)
        self.assertEqual(3, report.row_count)
        self.assertEqual(1, report.failed_count)
        self.assertTrue(
            any("registry requirement must be an object" in "; ".join(row.errors) for row in report.rows),
            report.rows,
        )

    def test_symlink_artifact_fails(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root.with_name(f"{root.name}-outside-sample-a.json")
            _write_json(
                outside,
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            try:
                os.symlink(outside, root / "sample-a.json")
            except (OSError, NotImplementedError) as exc:
                outside.unlink(missing_ok=True)
                self.skipTest(f"symlink not available: {exc}")

            report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

            outside.unlink(missing_ok=True)

        self.assertFalse(report.ok)
        self.assertEqual(1, report.failed_count)
        self.assertTrue(any("symlink" in "; ".join(row.errors) for row in report.rows), report.rows)

    def test_unsafe_artifact_name_fails_before_pattern_search(self) -> None:
        registry = _sample_registry()["requirements"][:1]
        registry[0]["artifact"] = "sample-*.json"
        sample_registry = _sample_registry_with(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=sample_registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(2, report.failed_count)
        self.assertTrue(
            any("unsafe artifact name" in "; ".join(row.errors) for row in report.rows),
            report.rows,
        )

    def test_unregistered_json_artifact_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "operator-note.json",
                {
                    "status": "not-registered",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        self.assertFalse(report.ok)
        self.assertEqual(2, report.requirement_count)
        self.assertEqual(3, report.row_count)
        self.assertEqual(1, report.failed_count)
        self.assertEqual(1, report.unexpected_count)
        rendered = bundle_validator.format_markdown(report)
        self.assertIn("- Requirements: `2`", rendered)
        self.assertIn("- Rows: `3`", rendered)
        self.assertIn("- Unexpected: `1`", rendered)
        unexpected_rows = [
            row for row in report.rows if bundle_validator._is_unexpected_artifact_row(row)
        ]
        self.assertEqual(1, len(unexpected_rows), report.rows)
        self.assertRegex(unexpected_rows[0].artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertIn(unexpected_rows[0].artifact_sha256 or "", rendered)
        self.assertTrue(
            any("unexpected unregistered artifact" in "; ".join(row.errors) for row in report.rows),
            report.rows,
        )

    def test_unregistered_non_json_artifact_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "nested" / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            raw_path = root / "debug" / "raw.log"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("private trace should not ride along", encoding="utf-8")

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        unexpected_rows = [
            row for row in report.rows if bundle_validator._is_unexpected_artifact_row(row)
        ]
        self.assertFalse(report.ok)
        self.assertEqual(2, report.requirement_count)
        self.assertEqual(3, report.row_count)
        self.assertEqual(1, report.failed_count)
        self.assertEqual(1, report.unexpected_count)
        self.assertEqual(1, len(unexpected_rows), report.rows)
        self.assertEqual("raw.log", unexpected_rows[0].artifact)
        self.assertRegex(unexpected_rows[0].artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertTrue(
            any("unexpected unregistered artifact" in "; ".join(row.errors) for row in report.rows),
            report.rows,
        )

    def test_bundle_fingerprint_changes_when_unregistered_artifact_changes(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            unexpected_path = root / "operator-note.json"
            _write_json(unexpected_path, {"status": "not-registered"})

            first_report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            _write_json(unexpected_path, {"status": "not-registered", "revision": 2})
            second_report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        first_unexpected = [
            row
            for row in first_report.rows
            if bundle_validator._is_unexpected_artifact_row(row)
        ][0]
        second_unexpected = [
            row
            for row in second_report.rows
            if bundle_validator._is_unexpected_artifact_row(row)
        ][0]
        self.assertFalse(first_report.ok)
        self.assertFalse(second_report.ok)
        self.assertRegex(first_unexpected.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertRegex(second_unexpected.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            first_unexpected.artifact_sha256,
            second_unexpected.artifact_sha256,
        )
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )

    def test_bundle_fingerprint_changes_when_unregistered_non_json_artifact_changes(
        self,
    ) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            unexpected_path = root / "raw.log"
            unexpected_path.write_text("first raw trace", encoding="utf-8")

            first_report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            unexpected_path.write_text("second raw trace", encoding="utf-8")
            second_report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        first_unexpected = [
            row
            for row in first_report.rows
            if bundle_validator._is_unexpected_artifact_row(row)
        ][0]
        second_unexpected = [
            row
            for row in second_report.rows
            if bundle_validator._is_unexpected_artifact_row(row)
        ][0]
        self.assertFalse(first_report.ok)
        self.assertFalse(second_report.ok)
        self.assertRegex(first_unexpected.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertRegex(second_unexpected.artifact_sha256 or "", r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            first_unexpected.artifact_sha256,
            second_unexpected.artifact_sha256,
        )
        self.assertNotEqual(
            first_report.bundle_fingerprint_sha256,
            second_report.bundle_fingerprint_sha256,
        )

    def test_unregistered_symlink_json_artifact_reports_path_errors(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            outside = base / "outside-note.json"
            _write_json(outside, {"status": "outside"})
            try:
                os.symlink(outside, root / "operator-note.json")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )

        unexpected_rows = [
            row for row in report.rows if bundle_validator._is_unexpected_artifact_row(row)
        ]
        self.assertFalse(report.ok)
        self.assertEqual(1, len(unexpected_rows), report.rows)
        self.assertIsNone(unexpected_rows[0].artifact_sha256)
        self.assertTrue(
            any("symlink" in error for error in unexpected_rows[0].errors),
            unexpected_rows[0].errors,
        )

    def test_cli_writes_json_report(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            out_path = base / "bundle-report.json"

            with mock.patch.object(bundle_validator, "require_valid_registry_contract") as gate:
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                        "--out",
                        str(out_path),
                    ]
                )
            gate.assert_called_once()

            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual(2, payload["passed_count"])
        self.assertEqual(0, payload["unexpected_count"])
        self.assertEqual(2, payload["requirement_count"])
        self.assertEqual(2, payload["row_count"])
        self.assertEqual([], payload["error_codes"])
        self.assertEqual({}, payload["error_code_counts"])
        self.assertEqual(
            bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual(bundle_validator.REGISTRY_NAME, payload["registry_name"])
        self.assertEqual(1, payload["registry_version"])
        self.assertEqual("2026-06-01T12:00:00Z", payload["validated_at"])
        self.assertTrue(
            re.fullmatch(r"[0-9a-f]{64}", payload["registry_fingerprint_sha256"]),
            payload,
        )
        self.assertTrue(
            re.fullmatch(r"[0-9a-f]{64}", payload["bundle_fingerprint_sha256"]),
            payload,
        )
        self.assertTrue(
            re.fullmatch(r"[0-9a-f]{64}", payload["rows"][0]["artifact_sha256"]),
            payload["rows"][0],
        )

    def test_cli_validates_registry_contract_before_bundle_scan(self) -> None:
        registry = _sample_registry()
        registry["decorative_config"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
        self.assertFalse(payload["ok"])
        self.assertIn("registry validation failed", payload["errors"][0])
        self.assertEqual(["registry_contract_invalid"], payload["error_codes"])
        self.assertEqual(
            {"registry_contract_invalid": 1},
            payload["error_code_counts"],
        )

    def test_cli_rejects_report_output_inside_bundle_root(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            out_path = root / "bundle-report.json"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(1, exit_code)
            self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
            self.assertFalse(payload["ok"])
            self.assertIn("bundle report output path", payload["errors"][0])
            self.assertEqual(
                ["bundle_report_output_path_inside_bundle_root"],
                payload["error_codes"],
            )
            self.assertEqual(
                {"bundle_report_output_path_inside_bundle_root": 1},
                payload["error_code_counts"],
            )
            self.assertFalse(out_path.exists())

    def test_cli_rejects_report_output_directory(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            out_path = base / "bundle-report"
            out_path.mkdir()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            out_entries = list(out_path.iterdir())

        self.assertEqual(1, exit_code)
        self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
        self.assertFalse(payload["ok"])
        self.assertIn("bundle report output path", payload["errors"][0])
        self.assertEqual(
            ["bundle_report_output_path_directory"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"bundle_report_output_path_directory": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], out_entries)

    def test_cli_rejects_report_output_symlink(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            target_out_path = base / "bundle-report-target.json"
            target_out_path.write_text("keep", encoding="utf-8")
            out_path = base / "bundle-report.json"
            try:
                os.symlink(target_out_path, out_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            target_text = target_out_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
        self.assertFalse(payload["ok"])
        self.assertIn("bundle report output path", payload["errors"][0])
        self.assertEqual(
            ["bundle_report_output_path_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"bundle_report_output_path_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual("keep", target_text)

    def test_cli_rejects_report_output_parent_symlink(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            target_dir = base / "target-dir"
            target_dir.mkdir()
            symlink_parent = base / "linked-parent"
            try:
                os.symlink(target_dir, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            out_path = symlink_parent / "bundle-report.json"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                        "--out",
                        str(out_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            target_entries = list(target_dir.iterdir())

        self.assertEqual(1, exit_code)
        self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
        self.assertFalse(payload["ok"])
        self.assertIn("bundle report output path", payload["errors"][0])
        self.assertEqual(
            ["bundle_report_output_path_parent_symlink"],
            payload["error_codes"],
        )
        self.assertEqual(
            {"bundle_report_output_path_parent_symlink": 1},
            payload["error_code_counts"],
        )
        self.assertEqual([], target_entries)

    def test_cli_rejects_registry_path_inside_bundle_root(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(1, exit_code)
            self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
            self.assertFalse(payload["ok"])
            self.assertIn("bundle registry path", payload["errors"][0])
            self.assertEqual(
                ["bundle_registry_path_inside_bundle_root"],
                payload["error_codes"],
            )
            self.assertEqual(
                {"bundle_registry_path_inside_bundle_root": 1},
                payload["error_code_counts"],
            )

    def test_cli_rejects_registry_symlink_path_inside_bundle_root(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            target_registry_path = base / "registry.json"
            target_registry_path.write_text(json.dumps(registry), encoding="utf-8")
            registry_path = root / "registry-link.json"
            try:
                os.symlink(target_registry_path, registry_path)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "json",
                        "--as-of",
                        self.as_of,
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(1, exit_code)
            self.assertEqual(bundle_validator.BUNDLE_REPORT_SCHEMA_VERSION, payload["schema_version"])
            self.assertFalse(payload["ok"])
            self.assertIn("bundle registry path", payload["errors"][0])
            self.assertEqual(
                ["bundle_registry_path_inside_bundle_root"],
                payload["error_codes"],
            )

    def test_cli_rejects_report_output_symlink_path_inside_bundle_root(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            target_out_path = base / "bundle-report.md"
            target_out_path.write_text("", encoding="utf-8")
            out_path = root / "bundle-report.md"
            try:
                os.symlink(target_out_path, out_path)
            except OSError as exc:
                self.skipTest(f"symlink not available: {exc}")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--format",
                        "markdown",
                        "--as-of",
                        self.as_of,
                        "--out",
                        str(out_path),
                    ]
                )

            self.assertEqual(1, exit_code)
            self.assertIn("bundle report output path", stderr.getvalue())

    def test_stale_artifact_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-05-20T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )

            report = bundle_validator.validate_bundle(
                registry=registry,
                bundle_root=root,
                as_of=bundle_validator._parse_timestamp(self.as_of),
            )
            rendered = bundle_validator.format_markdown(report)

        self.assertFalse(report.ok)
        self.assertEqual(1, report.failed_count)
        self.assertIn("stale", rendered)

    def test_cli_can_require_self_harness_report_bundle_registry_match(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            report_root = base / "self-harness-reports"
            root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_report_bundle_coverage(report_root, registry)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            stdout = io.StringIO()

            with (
                mock.patch.object(bundle_validator, "require_valid_registry_contract"),
                mock.patch.object(
                    bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                with contextlib.redirect_stdout(stdout):
                    exit_code = bundle_validator.main(
                        [
                            str(root),
                            "--registry",
                            str(registry_path),
                            "--self-harness-report-bundle",
                            str(report_root),
                            "--format",
                            "json",
                            "--as-of",
                            self.as_of,
                        ]
                    )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["completion_audit_ready"], payload)
        self.assertEqual([], payload["error_codes"])
        self.assertEqual(
            str(report_root),
            payload["self_harness_report_bundle_root"],
        )
        self.assertEqual(
            "a" * 64,
            payload["self_harness_report_bundle_fingerprint_sha256"],
        )
        self.assertEqual(
            "wiii.self_harness_report_bundle_validation.v1",
            payload["self_harness_report_bundle_validation_schema_version"],
        )
        self.assertRegex(
            payload["completion_audit_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )

    def test_cli_can_require_completion_audit_link(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            report_root = base / "self-harness-reports"
            root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_report_bundle_coverage(report_root, registry)
            _write_json(
                root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_json(
                root / "sample-b.json",
                {
                    "schema_version": "wiii.sample_b.v1",
                    "count": 2,
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            stdout = io.StringIO()

            with (
                mock.patch.object(bundle_validator, "require_valid_registry_contract"),
                mock.patch.object(
                    bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                with contextlib.redirect_stdout(stdout):
                    exit_code = bundle_validator.main(
                        [
                            str(root),
                            "--registry",
                            str(registry_path),
                            "--self-harness-report-bundle",
                            str(report_root),
                            "--require-completion-audit-link",
                            "--format",
                            "json",
                            "--as-of",
                            self.as_of,
                        ]
                    )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["completion_audit_ready"], payload)
        self.assertEqual([], payload["error_codes"])

    def test_cli_requires_completion_audit_link_when_requested(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = bundle_validator.main(
                    [
                        str(root),
                        "--registry",
                        str(registry_path),
                        "--require-completion-audit-link",
                        "--format",
                        "json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(["completion_audit_link_missing"], payload["error_codes"])
        self.assertEqual(
            {"completion_audit_link_missing": 1},
            payload["error_code_counts"],
        )

    def test_cli_rejects_report_bundle_registry_fingerprint_mismatch(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            report_root = base / "self-harness-reports"
            root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_report_bundle_coverage(report_root, registry, fingerprint="0" * 64)
            stdout = io.StringIO()

            with (
                mock.patch.object(bundle_validator, "require_valid_registry_contract"),
                mock.patch.object(
                    bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(),
                ),
            ):
                with contextlib.redirect_stdout(stdout):
                    exit_code = bundle_validator.main(
                        [
                            str(root),
                            "--registry",
                            str(registry_path),
                            "--self-harness-report-bundle",
                            str(report_root),
                            "--format",
                            "json",
                        ]
                    )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["report_bundle_registry_fingerprint_mismatch"],
            payload["error_codes"],
        )

    def test_self_harness_report_bundle_must_be_valid_before_registry_match(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "bundle"
            report_root = base / "self-harness-reports"
            root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_report_bundle_coverage(report_root, registry)
            stdout = io.StringIO()

            with mock.patch.object(bundle_validator, "require_valid_registry_contract"):
                with contextlib.redirect_stdout(stdout):
                    exit_code = bundle_validator.main(
                        [
                            str(root),
                            "--registry",
                            str(registry_path),
                            "--self-harness-report-bundle",
                            str(report_root),
                            "--format",
                            "json",
                        ]
                    )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["self_harness_report_bundle_invalid"],
            payload["error_codes"],
        )

    def test_report_bundle_registry_version_and_count_must_match(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            report_root = base / "self-harness-reports"
            report_root.mkdir()
            _write_report_bundle_coverage(report_root, registry, registry_version=2)

            with (
                mock.patch.object(
                    bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(),
                ),
                self.assertRaisesRegex(ValueError, "registry_version"),
            ):
                bundle_validator.require_registry_matches_report_bundle(
                    registry,
                    report_bundle_root=report_root,
                )

            _write_report_bundle_coverage(report_root, registry, requirement_count=1)

            with (
                mock.patch.object(
                    bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(),
                ),
                self.assertRaisesRegex(ValueError, "requirement_count"),
            ):
                bundle_validator.require_registry_matches_report_bundle(
                    registry,
                    report_bundle_root=report_root,
                )


if __name__ == "__main__":
    unittest.main()
