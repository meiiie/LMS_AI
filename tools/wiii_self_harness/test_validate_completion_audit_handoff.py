import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import generate_completion_audit_handoff as handoff_generator
import validate_completion_audit_handoff as handoff_validator


def _sample_registry() -> dict:
    return {
        "registry": handoff_generator.bundle_validator.REGISTRY_NAME,
        "version": 1,
        "requirements": [
            {
                "id": "sample-a",
                "artifact": "sample-a.json",
                "schema_version": "wiii.sample_a.v1",
                "freshness": {"timestamp_path": "generated_at", "max_age_hours": 72},
                "payload_schema_field": "schema_version",
                "forbidden_payload_tokens": [],
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
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_matching_runtime_payload(
    root: Path,
    payload: dict,
    *,
    update_handoff_fingerprints: bool = False,
    update_handoff_readiness: bool = False,
) -> None:
    runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
    handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
    handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff_payload["runtime_evidence_bundle_report"] = payload
    if update_handoff_fingerprints:
        handoff_payload["completion_audit_fingerprint_sha256"] = payload[
            "completion_audit_fingerprint_sha256"
        ]
        handoff_payload["runtime_evidence_bundle_fingerprint_sha256"] = payload[
            "bundle_fingerprint_sha256"
        ]
        handoff_payload["self_harness_report_bundle_fingerprint_sha256"] = payload[
            "self_harness_report_bundle_fingerprint_sha256"
        ]
    if update_handoff_readiness:
        handoff_payload["ok"] = payload["completion_audit_ready"]
        handoff_payload["completion_audit_ready"] = payload["completion_audit_ready"]
        handoff_payload["release_handoff_ready"] = payload["completion_audit_ready"]
    _write_json(runtime_path, payload)
    _write_json(handoff_path, handoff_payload)


def _refresh_runtime_payload_fingerprints(payload: dict) -> None:
    payload["bundle_fingerprint_sha256"] = handoff_validator._runtime_bundle_fingerprint(
        payload["rows"],
        bundle_root=payload["bundle_root"],
        registry_fingerprint_sha256=payload["registry_fingerprint_sha256"],
        schema_version=payload["schema_version"],
        validated_at=payload["validated_at"],
    )
    completion_fingerprint = (
        handoff_validator._runtime_completion_audit_fingerprint(
            bundle_fingerprint_sha256=payload["bundle_fingerprint_sha256"],
            self_harness_report_bundle_fingerprint_sha256=payload[
                "self_harness_report_bundle_fingerprint_sha256"
            ],
            self_harness_report_bundle_validation_schema_version=payload[
                "self_harness_report_bundle_validation_schema_version"
            ],
        )
    )
    assert completion_fingerprint is not None
    payload["completion_audit_fingerprint_sha256"] = completion_fingerprint


def _write_matching_markdown_reports(root: Path) -> None:
    handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
    runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
    handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))

    handoff_lines = handoff_validator._expected_handoff_markdown_document_lines(
        handoff_payload
    )
    (root / handoff_generator.HANDOFF_MARKDOWN_REPORT).write_text(
        "\n".join(handoff_lines) + "\n",
        encoding="utf-8",
    )

    runtime_lines = handoff_validator._expected_runtime_markdown_document_lines(
        runtime_payload
    )
    (root / handoff_generator.RUNTIME_BUNDLE_MARKDOWN_REPORT).write_text(
        "\n".join(runtime_lines) + "\n",
        encoding="utf-8",
    )


def _write_handoff_payload(root: Path, payload: dict) -> None:
    _write_json(root / handoff_generator.HANDOFF_JSON_REPORT, payload)


def _write_report_bundle_coverage(root: Path, registry: dict) -> None:
    _write_json(
        root / "runtime-evidence-coverage.json",
        {
            "registry_fingerprint_sha256": (
                handoff_generator.bundle_validator._registry_fingerprint(registry)
            ),
            "registry_version": registry["version"],
            "requirement_count": len(registry["requirements"]),
        },
    )


def _valid_report_bundle_result(*, fingerprint: str = "f" * 64):
    return mock.Mock(
        ok=True,
        to_dict=mock.Mock(
            return_value={
                "bundle_fingerprint_sha256": fingerprint,
                "validation_schema_version": (
                    "wiii.self_harness_report_bundle_validation.v1"
                ),
                "error_codes": [],
                "rows": [],
            }
        ),
    )


def _write_passing_artifacts(root: Path) -> None:
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


def _write_readiness_report(base: Path) -> Path:
    path = base / "readiness.json"
    _write_json(
        path,
        {
            "schema_version": (
                handoff_generator.readiness_reporter.READINESS_REPORT_SCHEMA_VERSION
            ),
            "ok": True,
            "scoped_completion_audit_ready": False,
            "scoped_next_action_count": 1,
            "scoped_next_actions_fingerprint_sha256": "c" * 64,
            "scoped_next_actions": [
                {
                    "requirement_id": "sample-b",
                    "artifact": "sample-b.json",
                    "status": "missing",
                    "workflow": ".github/workflows/sample.yml",
                    "probe": "maritime-ai-service/scripts/probe_sample_b.py",
                    "blocked_by_live_setup": True,
                    "live_env_flags": ["SAMPLE_B_TOKEN"],
                    "live_guard_tokens": ["sample-b-live"],
                    "dispatch_or_schedule_gate_tokens": ["sample-b-gate"],
                    "artifact_tokens": ["sample-b.json"],
                    "preflight_required_next": [
                        "python maritime-ai-service/scripts/probe_sample_b.py"
                    ],
                    "error_codes": ["missing_artifact"],
                }
            ],
        },
    )
    return path


def _write_pending_control_sources(base: Path) -> tuple[Path, Path, Path]:
    control_path = base / "control-chain.json"
    setup_gap_path = base / "setup-gaps.json"
    setup_gap_markdown_path = base / "setup-gaps.md"
    _write_json(
        control_path,
        {
            "validation_schema_version": (
                "wiii.completion_audit_control_chain_validation.v1"
            ),
            "ok": True,
            "control_chain_ready": False,
            "dispatch_ready": False,
            "setup_gap_report_path": str(setup_gap_path),
            "setup_gap_markdown_report_path": str(setup_gap_markdown_path),
            "dispatch_diagnostics_path": str(base / "dispatch-diagnostics.json"),
            "error_codes": [],
        },
    )
    _write_json(
        setup_gap_path,
        {
            "schema_version": "wiii.completion_audit_setup_gap_report.v1",
            "ok": True,
            "setup_gap_report_fingerprint_sha256": "b" * 64,
            "setup_diagnostics_consistent": True,
            "requirement_count": 1,
            "blocked_requirement_count": 1,
            "pending_setup_check_count": 2,
            "diagnostic_pending_setup_check_count": 1,
            "non_diagnostic_pending_setup_check_count": 1,
            "diagnostic_present_setup_mismatch_count": 0,
            "privacy": {
                "secret_values_included": False,
                "credential_values_included": False,
                "raw_identifiers_included": False,
                "raw_payload_included": False,
            },
            "requirements": [
                {
                    "requirement_id": "lms-test-course-replay",
                    "pending_setup_check_count": 2,
                    "diagnostic_pending_setup_keys": [
                        "credential_slots_required:external_lms_apply_token",
                    ],
                    "non_diagnostic_pending_setup_keys": [
                        "credential_slots_required:lms_backend_bearer_token",
                    ],
                    "pending_setup_checks": [
                        {
                            "category": "credential_slots_required",
                            "key": "external_lms_apply_token",
                            "present": False,
                            "evidence_kind": "credential_slot_bound",
                            "binding_token_count": 1,
                            "source_handle_present": False,
                            "source_handle_options": ["EXTERNAL_LMS_APPLY_TOKEN"],
                            "attestation_option_count": 1,
                        },
                        {
                            "category": "credential_slots_required",
                            "key": "lms_backend_bearer_token",
                            "present": False,
                            "evidence_kind": "credential_slot_bound",
                            "binding_token_count": 1,
                            "source_handle_present": False,
                            "source_handle_options": ["LMS_BACKEND_BEARER_TOKEN"],
                            "attestation_option_count": 1,
                        },
                    ],
                },
            ],
        },
    )
    setup_gap_markdown_path.write_text("# setup gaps\n", encoding="utf-8")
    return control_path, setup_gap_path, setup_gap_markdown_path


def _mark_setup_gap_summary_inconsistent(setup_gap_path: Path) -> None:
    payload = json.loads(setup_gap_path.read_text(encoding="utf-8"))
    payload["ok"] = False
    payload["setup_diagnostics_consistent"] = False
    payload["diagnostic_present_setup_mismatch_count"] = 1
    _write_json(setup_gap_path, payload)


def _generate_handoff_bundle(
    *,
    base: Path,
    ready: bool = True,
    include_readiness: bool = False,
) -> tuple[Path, dict]:
    registry = _sample_registry()
    artifact_root = base / "runtime-artifacts"
    report_root = base / "self-harness-reports"
    out_dir = base / "completion-audit"
    artifact_root.mkdir()
    report_root.mkdir()
    registry_path = base / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    if ready:
        _write_passing_artifacts(artifact_root)
    else:
        _write_json(
            artifact_root / "sample-a.json",
            {
                "schema_version": "wiii.sample_a.v1",
                "status": "pass",
                "generated_at": "2026-06-01T10:00:00+00:00",
            },
        )
    readiness_path = _write_readiness_report(base) if include_readiness else None
    _write_report_bundle_coverage(report_root, registry)

    with (
        mock.patch.object(
            handoff_generator.bundle_validator,
            "require_valid_registry_contract",
        ),
        mock.patch.object(
            handoff_generator.bundle_validator,
            "validate_self_harness_report_bundle_contract",
            return_value=_valid_report_bundle_result(fingerprint="a" * 64),
        ),
    ):
        result = handoff_generator.generate_completion_audit_handoff(
            artifact_bundle_root=artifact_root,
            self_harness_report_bundle_root=report_root,
            out_dir=out_dir,
            registry_path=registry_path,
            as_of="2026-06-01T12:00:00+00:00",
            readiness_report_path=readiness_path,
        )
    return out_dir, result.to_dict()


class ValidateCompletionAuditHandoffTests(unittest.TestCase):
    def test_valid_handoff_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, payload = _generate_handoff_bundle(base=Path(temp_dir))

            result = handoff_validator.validate_handoff_bundle(root)
            rendered = handoff_validator.format_summary(result)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(4, result.passed_count)
        self.assertEqual(0, result.failed_count)
        self.assertEqual(0, result.unexpected_count)
        self.assertTrue(result.completion_audit_ready)
        self.assertEqual(
            payload["completion_audit_fingerprint_sha256"],
            result.completion_audit_fingerprint_sha256,
        )
        self.assertRegex(result.bundle_fingerprint_sha256, r"^[0-9a-f]{64}$")
        self.assertIn("Wiii Completion Audit Handoff Bundle: PASS", rendered)

    def test_valid_not_ready_handoff_bundle_still_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertTrue(result.ok, result.to_dict())
        self.assertFalse(result.completion_audit_ready)

    def test_valid_not_ready_handoff_binds_readiness_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
                include_readiness=True,
            )

            result = handoff_validator.validate_handoff_bundle(root)
            handoff_payload = json.loads(
                (root / handoff_generator.HANDOFF_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            1,
            handoff_payload["readiness_summary"]["scoped_next_action_count"],
        )
        self.assertEqual(
            ".github/workflows/sample.yml",
            handoff_payload["release_blockers"][0]["recovery_action"]["workflow"],
        )

    def test_readiness_recovery_actions_must_match_runtime_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
                include_readiness=True,
            )
            handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_payload["release_blockers"][0]["recovery_action"] = None
            _write_json(handoff_path, handoff_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_release_blockers_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_ready_requirement_passes_for_ready_handoff_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))

            result = handoff_validator.validate_handoff_bundle(
                root,
                require_completion_audit_ready=True,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertTrue(result.completion_audit_ready)
        self.assertTrue(result.require_completion_audit_ready)
        self.assertTrue(result.to_dict()["require_completion_audit_ready"])

    def test_ready_requirement_fails_for_not_ready_handoff_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )

            result = handoff_validator.validate_handoff_bundle(
                root,
                require_completion_audit_ready=True,
            )

        self.assertFalse(result.ok)
        self.assertFalse(result.completion_audit_ready)
        self.assertIn(
            "handoff_completion_audit_not_ready",
            result.to_dict()["error_codes"],
        )

    def test_release_gate_fails_when_runtime_ready_but_setup_pending(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_passing_artifacts(artifact_root)
            _write_report_bundle_coverage(report_root, registry)
            control_path, setup_gap_path, setup_gap_markdown_path = (
                _write_pending_control_sources(base)
            )
            with (
                mock.patch.object(
                    handoff_generator.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff_generator.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                handoff_generator.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of="2026-06-01T12:00:00+00:00",
                    control_chain_report_path=control_path,
                    setup_gap_report_path=setup_gap_path,
                    setup_gap_markdown_report_path=setup_gap_markdown_path,
                )

            structural_result = handoff_validator.validate_handoff_bundle(out_dir)
            release_gate_result = handoff_validator.validate_handoff_bundle(
                out_dir,
                require_completion_audit_ready=True,
            )

        self.assertTrue(structural_result.ok, structural_result.to_dict())
        self.assertTrue(structural_result.completion_audit_ready)
        self.assertFalse(structural_result.release_handoff_ready)
        self.assertFalse(release_gate_result.ok, release_gate_result.to_dict())
        self.assertIn(
            "handoff_completion_audit_not_ready",
            release_gate_result.to_dict()["error_codes"],
        )

    def test_tampered_release_handoff_ready_fails(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_passing_artifacts(artifact_root)
            _write_report_bundle_coverage(report_root, registry)
            control_path, setup_gap_path, setup_gap_markdown_path = (
                _write_pending_control_sources(base)
            )
            with (
                mock.patch.object(
                    handoff_generator.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff_generator.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                handoff_generator.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of="2026-06-01T12:00:00+00:00",
                    control_chain_report_path=control_path,
                    setup_gap_report_path=setup_gap_path,
                    setup_gap_markdown_report_path=setup_gap_markdown_path,
                )
            handoff_path = out_dir / handoff_generator.HANDOFF_JSON_REPORT
            payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            payload["ok"] = True
            payload["release_handoff_ready"] = True
            _write_json(handoff_path, payload)
            _write_matching_markdown_reports(out_dir)

            result = handoff_validator.validate_handoff_bundle(out_dir)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_release_ready_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_ready_requirement_changes_validation_bundle_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )

            structural_result = handoff_validator.validate_handoff_bundle(root)
            release_gate_result = handoff_validator.validate_handoff_bundle(
                root,
                require_completion_audit_ready=True,
            )

        self.assertTrue(structural_result.ok, structural_result.to_dict())
        self.assertFalse(release_gate_result.ok, release_gate_result.to_dict())
        self.assertNotEqual(
            structural_result.bundle_fingerprint_sha256,
            release_gate_result.bundle_fingerprint_sha256,
        )
        self.assertNotIn(
            "handoff_completion_audit_not_ready",
            structural_result.to_dict()["error_codes"],
        )
        self.assertIn(
            "handoff_completion_audit_not_ready",
            release_gate_result.to_dict()["error_codes"],
        )

    def test_ready_requirement_changes_validation_bundle_fingerprint_when_ready(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))

            structural_result = handoff_validator.validate_handoff_bundle(root)
            release_gate_result = handoff_validator.validate_handoff_bundle(
                root,
                require_completion_audit_ready=True,
            )

        self.assertTrue(structural_result.ok, structural_result.to_dict())
        self.assertTrue(release_gate_result.ok, release_gate_result.to_dict())
        self.assertFalse(structural_result.require_completion_audit_ready)
        self.assertTrue(release_gate_result.require_completion_audit_ready)
        self.assertNotEqual(
            structural_result.bundle_fingerprint_sha256,
            release_gate_result.bundle_fingerprint_sha256,
        )
        self.assertEqual([], structural_result.to_dict()["error_codes"])
        self.assertEqual([], release_gate_result.to_dict()["error_codes"])

    def test_validation_bundle_fingerprint_binds_row_errors(self) -> None:
        first_fingerprint = handoff_validator._bundle_fingerprint(
            [
                handoff_validator.HandoffValidationRow(
                    file_name=handoff_generator.HANDOFF_JSON_REPORT,
                    status="failed",
                    report_sha256="0" * 64,
                    errors=["handoff markdown line mismatch: first"],
                )
            ],
            validation_schema_version=handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            require_completion_audit_ready=False,
        )
        second_fingerprint = handoff_validator._bundle_fingerprint(
            [
                handoff_validator.HandoffValidationRow(
                    file_name=handoff_generator.HANDOFF_JSON_REPORT,
                    status="failed",
                    report_sha256="0" * 64,
                    errors=["handoff markdown line mismatch: second"],
                )
            ],
            validation_schema_version=handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            require_completion_audit_ready=False,
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_validation_bundle_fingerprint_binds_schema_version(self) -> None:
        rows = [
            handoff_validator.HandoffValidationRow(
                file_name=handoff_generator.HANDOFF_JSON_REPORT,
                status="passed",
                report_sha256="0" * 64,
                errors=[],
            )
        ]

        first_fingerprint = handoff_validator._bundle_fingerprint(
            rows,
            validation_schema_version=handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            require_completion_audit_ready=False,
        )
        second_fingerprint = handoff_validator._bundle_fingerprint(
            rows,
            validation_schema_version="wiii.completion_audit_handoff_validation.v2",
            require_completion_audit_ready=False,
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_validation_bundle_fingerprint_binds_row_status(self) -> None:
        first_fingerprint = handoff_validator._bundle_fingerprint(
            [
                handoff_validator.HandoffValidationRow(
                    file_name=handoff_generator.HANDOFF_JSON_REPORT,
                    status="passed",
                    report_sha256="0" * 64,
                    errors=[],
                )
            ],
            validation_schema_version=handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            require_completion_audit_ready=False,
        )
        second_fingerprint = handoff_validator._bundle_fingerprint(
            [
                handoff_validator.HandoffValidationRow(
                    file_name=handoff_generator.HANDOFF_JSON_REPORT,
                    status="failed",
                    report_sha256="0" * 64,
                    errors=[],
                )
            ],
            validation_schema_version=handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            require_completion_audit_ready=False,
        )

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_tampered_handoff_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(path.read_text(encoding="utf-8"))
            handoff_payload["completion_audit_fingerprint_sha256"] = "0" * 64
            _write_json(path, handoff_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_completion_audit_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_handoff_markdown_must_match_handoff_json_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            markdown_path = root / handoff_generator.HANDOFF_MARKDOWN_REPORT
            markdown = markdown_path.read_text(encoding="utf-8")
            markdown_path.write_text(
                markdown.replace(
                    "- Completion audit ready: `true`",
                    "- Completion audit ready: `false`",
                ),
                encoding="utf-8",
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_markdown_value_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_handoff_markdown_rejects_extra_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            markdown_path = root / handoff_generator.HANDOFF_MARKDOWN_REPORT
            markdown_path.write_text(
                markdown_path.read_text(encoding="utf-8")
                + "\n- Operator override: `ready`",
                encoding="utf-8",
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_markdown_value_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_markdown_must_match_runtime_json_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            markdown_path = root / handoff_generator.RUNTIME_BUNDLE_MARKDOWN_REPORT
            markdown = markdown_path.read_text(encoding="utf-8")
            markdown_path.write_text(
                markdown.replace("- Passed: `2`", "- Passed: `0`"),
                encoding="utf-8",
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_markdown_value_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_markdown_rejects_extra_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            markdown_path = root / handoff_generator.RUNTIME_BUNDLE_MARKDOWN_REPORT
            markdown_path.write_text(
                markdown_path.read_text(encoding="utf-8")
                + "\n\n- Operator override: `runtime-ready`",
                encoding="utf-8",
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_value_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_row_count_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_markdown_row_count_must_match_runtime_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            markdown_path = root / handoff_generator.RUNTIME_BUNDLE_MARKDOWN_REPORT
            lines = markdown_path.read_text(encoding="utf-8").splitlines()
            row_indices = [
                index
                for index, line in enumerate(lines)
                if line.startswith("| ") and not line.startswith("| Requirement ")
            ]
            del lines[row_indices[-1]]
            markdown_path.write_text("\n".join(lines), encoding="utf-8")

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_markdown_row_count_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_markdown_table_rows_must_match_runtime_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            markdown_path = root / handoff_generator.RUNTIME_BUNDLE_MARKDOWN_REPORT
            lines = markdown_path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if line.startswith("| sample-a |"):
                    lines[index] = line.replace(
                        "sample-a.json",
                        "operator-supplied.json",
                    )
                    break
            else:
                self.fail("sample-a runtime row not found")
            markdown_path.write_text("\n".join(lines), encoding="utf-8")

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_markdown_row_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_must_match_nested_handoff_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(path.read_text(encoding="utf-8"))
            runtime_payload["missing_count"] = runtime_payload["missing_count"] + 1
            _write_json(path, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_blockers_must_match_runtime_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_payload["runtime_blockers"] = []
            _write_json(handoff_path, handoff_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_runtime_blockers_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_release_blockers_must_match_runtime_and_setup_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_payload["release_blocker_count"] = 0
            handoff_payload["release_blockers"] = []
            _write_json(handoff_path, handoff_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_release_blockers_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_release_blockers_schema_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_payload["release_blocker_count"] = 1
            handoff_payload["release_blockers"] = [{"kind": "runtime_evidence"}]
            _write_json(handoff_path, handoff_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_release_blockers_invalid",
            result.to_dict()["error_codes"],
        )

    def test_setup_summary_release_blockers_validate(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_passing_artifacts(artifact_root)
            _write_report_bundle_coverage(report_root, registry)
            control_path, setup_gap_path, setup_gap_markdown_path = (
                _write_pending_control_sources(base)
            )
            _mark_setup_gap_summary_inconsistent(setup_gap_path)
            with (
                mock.patch.object(
                    handoff_generator.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff_generator.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                handoff_generator.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of="2026-06-01T12:00:00+00:00",
                    control_chain_report_path=control_path,
                    setup_gap_report_path=setup_gap_path,
                    setup_gap_markdown_report_path=setup_gap_markdown_path,
                )
            handoff_path = out_dir / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))

            result = handoff_validator.validate_handoff_bundle(out_dir)

        self.assertTrue(result.ok, result.to_dict())
        self.assertFalse(result.release_handoff_ready)
        self.assertEqual([], result.to_dict()["error_codes"])
        setup_blockers = [
            blocker
            for blocker in handoff_payload["release_blockers"]
            if blocker["kind"] == "setup_gap"
        ]
        self.assertTrue(setup_blockers)
        self.assertIn("resolution_actions", setup_blockers[0])
        self.assertEqual(2, len(setup_blockers[0]["resolution_actions"]))

    def test_runtime_json_rejects_extra_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["operator_payload"] = {"debug": True}
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_json_unsupported_fields",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_requires_complete_canonical_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload.pop("registry_name")
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_json_missing_required_fields",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_registry_name_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["registry_name"] = "Operator Supplied Registry"
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_registry_name_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_registry_version_must_be_positive_integer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["registry_version"] = True
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_registry_version_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_validated_at_must_be_normalized_utc_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["validated_at"] = "2026-06-01T19:00:00+07:00"
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_validated_at_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_paths_must_be_non_empty_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["bundle_root"] = ""
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_string_field_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_self_harness_validation_schema_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload[
                "self_harness_report_bundle_validation_schema_version"
            ] = "wiii.operator_supplied_report_bundle.v1"
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_self_harness_validation_schema_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_ok_must_match_row_status_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["ok"] = False
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_ok_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_completion_audit_ready_must_match_readiness_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["completion_audit_ready"] = True
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_readiness=True,
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_completion_audit_ready_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_completion_audit_ready_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_handoff_artifact_bundle_root_must_match_runtime_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_payload["artifact_bundle_root"] = str(Path(temp_dir) / "other")
            _write_handoff_payload(root, handoff_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_artifact_bundle_root_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_handoff_self_harness_root_must_match_runtime_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            handoff_path = root / handoff_generator.HANDOFF_JSON_REPORT
            handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_payload["self_harness_report_bundle_root"] = str(
                Path(temp_dir) / "other-self-harness"
            )
            _write_handoff_payload(root, handoff_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "handoff_self_harness_bundle_root_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_count_must_match_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["row_count"] = len(runtime_payload["rows"]) + 1
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_count_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_requirement_count_must_match_registered_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["requirement_count"] = (
                runtime_payload["requirement_count"] + 1
            )
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_requirement_count_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_registered_rows_must_have_unique_requirement_ids(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][1] = json.loads(
                json.dumps(runtime_payload["rows"][0])
            )
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_registered_requirement_id_duplicate",
            result.to_dict()["error_codes"],
        )
        self.assertIn(
            "runtime_bundle_registered_artifact_duplicate",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_registered_rows_must_have_non_empty_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["requirement_id"] = ""
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_registered_row_identity_empty",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_rows_must_be_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"] = {"sample-a": "passed"}
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_rows_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_error_codes_must_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["error_codes"] = ["missing_artifact", "missing_artifact"]
            runtime_payload["error_code_counts"] = {"missing_artifact": 1}
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_error_codes_duplicate",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_error_code_counts_must_match_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["error_codes"] = ["missing_artifact"]
            runtime_payload["error_code_counts"] = {"unexpected": 1}
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_error_code_counts_key_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_error_code_counts_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["error_codes"] = ["missing_artifact"]
            runtime_payload["error_code_counts"] = {"missing_artifact": 0}
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_error_code_counts_non_positive",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_status_counts_must_match_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["passed_count"] = runtime_payload["passed_count"] + 1
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_status_counts_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_unexpected_count_must_match_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["unexpected_count"] = runtime_payload["unexpected_count"] + 1
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_unexpected_count_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_error_code_counts_must_match_row_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["error_code_counts"] = {"missing_artifact": 2}
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_error_code_counts_value_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_error_codes_must_match_row_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            markdown_path = root / handoff_generator.RUNTIME_BUNDLE_MARKDOWN_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][1]["errors"] = ["operator supplied message"]
            _write_matching_runtime_payload(root, runtime_payload)
            markdown_path.write_text(
                markdown_path.read_text(encoding="utf-8").replace(
                    "missing artifact 'sample-b.json'",
                    "operator supplied message",
                ),
                encoding="utf-8",
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_error_codes_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_row_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_bundle_fingerprint_must_match_canonical_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["checks_passed"] = (
                runtime_payload["rows"][0]["checks_passed"] + 1
            )
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_bundle_fingerprint_must_bind_row_error_messages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            original_errors = list(runtime_payload["rows"][1]["errors"])
            runtime_payload["rows"][1]["errors"] = [
                "missing artifact 'operator-supplied.json'"
            ]
            _write_matching_runtime_payload(root, runtime_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertEqual(["missing_artifact"], runtime_payload["rows"][1]["error_codes"])
        self.assertNotEqual(original_errors, runtime_payload["rows"][1]["errors"])
        self.assertIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_row_error_codes_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_row_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_bundle_fingerprint_must_bind_validated_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["validated_at"] = "2026-06-01T12:30:00Z"
            for row in runtime_payload["rows"]:
                if row.get("age_hours") is not None:
                    row["age_hours"] = row["age_hours"] + 0.5
            _write_matching_runtime_payload(root, runtime_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        error_codes = result.to_dict()["error_codes"]
        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "runtime_bundle_row_age_hours_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            error_codes,
        )

    def test_runtime_json_bundle_fingerprint_must_bind_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["schema_version"] = "wiii.runtime_evidence_bundle_report.v2"
            _write_matching_runtime_payload(root, runtime_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        error_codes = result.to_dict()["error_codes"]
        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_schema_mismatch",
            error_codes,
        )
        self.assertIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            error_codes,
        )

    def test_runtime_json_bundle_fingerprint_must_bind_age_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["age_hours"] = (
                runtime_payload["rows"][0]["age_hours"] + 0.25
            )
            _write_matching_runtime_payload(root, runtime_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        error_codes = result.to_dict()["error_codes"]
        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_age_hours_mismatch",
            error_codes,
        )
        self.assertIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            error_codes,
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            error_codes,
        )

    def test_runtime_json_completion_fingerprint_must_match_canonical_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["self_harness_report_bundle_fingerprint_sha256"] = "0" * 64
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_completion_audit_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_self_harness_bundle_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_fingerprint_fields_must_be_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0].pop("checks_passed")
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_json_missing_required_fields",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_age_hours_must_match_validated_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["age_hours"] = 0
            _write_matching_runtime_payload(root, runtime_payload)
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_age_hours_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_generated_at_must_be_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["generated_at"] = "not-a-timestamp"
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_generated_at_invalid",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_stale_rows_must_carry_freshness_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["generated_at"] = "2026-05-27T10:00:00+00:00"
            runtime_payload["rows"][0]["age_hours"] = 122.0
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_stale_freshness_code_missing",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_row_age_hours_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_passed_rows_must_carry_artifact_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["path"] = None
            runtime_payload["rows"][0]["artifact_sha256"] = None
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_passed_row_artifact_proof_missing",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_passed_rows_must_carry_freshness_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["generated_at"] = None
            runtime_payload["rows"][0]["max_age_hours"] = None
            runtime_payload["rows"][0]["age_hours"] = None
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_passed_row_freshness_proof_missing",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_missing_rows_must_not_carry_artifact_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][1]["path"] = str(
                Path(runtime_payload["bundle_root"]) / "sample-b.json"
            )
            runtime_payload["rows"][1]["artifact_sha256"] = "0" * 64
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_missing_row_artifact_proof_present",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_path_must_stay_inside_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["path"] = str(
                Path(temp_dir) / "outside" / "sample-a.json"
            )
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_path_outside_bundle_root",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_path_basename_must_match_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["path"] = str(
                Path(runtime_payload["bundle_root"]) / "operator-supplied.json"
            )
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_path_artifact_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_document_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_entries_must_be_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0] = "not-a-row-object"
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_entries_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_status_must_be_known(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["status"] = "warning"
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_status_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_passed_rows_must_not_contain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["errors"] = ["operator supplied failure"]
            runtime_payload["rows"][0]["error_codes"] = ["validation_error"]
            runtime_payload["error_codes"] = ["validation_error"]
            runtime_payload["error_code_counts"] = {"validation_error": 1}
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_passed_row_errors_present",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_row_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_non_passed_rows_must_contain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][1]["errors"] = []
            runtime_payload["rows"][1]["error_codes"] = []
            runtime_payload["error_codes"] = []
            runtime_payload["error_code_counts"] = {}
            _refresh_runtime_payload_fingerprints(runtime_payload)
            _write_matching_runtime_payload(
                root,
                runtime_payload,
                update_handoff_fingerprints=True,
            )
            _write_matching_markdown_reports(root)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_non_passed_row_errors_missing",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_bundle_canonical_fingerprint_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "runtime_markdown_row_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertNotIn(
            "handoff_nested_runtime_report_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_error_codes_must_be_string_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["error_codes"] = "missing_artifact"
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_error_codes_invalid",
            result.to_dict()["error_codes"],
        )

    def test_runtime_json_row_error_codes_must_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            runtime_path = root / handoff_generator.RUNTIME_BUNDLE_JSON_REPORT
            runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            runtime_payload["rows"][0]["error_codes"] = [
                "missing_artifact",
                "missing_artifact",
            ]
            _write_matching_runtime_payload(root, runtime_payload)

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_bundle_row_error_codes_duplicate",
            result.to_dict()["error_codes"],
        )

    def test_missing_report_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            (root / handoff_generator.HANDOFF_MARKDOWN_REPORT).unlink()

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertIn("handoff_report_file_missing", result.to_dict()["error_codes"])

    def test_unexpected_report_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            (root / "operator-note.json").write_text("{}", encoding="utf-8")

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertEqual(1, result.unexpected_count)
        self.assertIn(
            "unexpected_handoff_report_file",
            result.to_dict()["error_codes"],
        )
        unexpected_row = next(
            row for row in result.to_dict()["rows"] if row["file_name"] == "operator-note.json"
        )
        self.assertIsInstance(unexpected_row["report_sha256"], str)

    def test_unexpected_report_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            (root / "operator-notes").mkdir()

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertEqual(1, result.unexpected_count)
        self.assertIn(
            "unexpected_handoff_report_directory",
            result.to_dict()["error_codes"],
        )
        unexpected_row = next(
            row for row in result.to_dict()["rows"] if row["file_name"] == "operator-notes"
        )
        self.assertIsNone(unexpected_row["report_sha256"])

    def test_unexpected_report_symlink_fails_without_hashing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root, _payload = _generate_handoff_bundle(base=base)
            outside_target = base / "operator-note-target.json"
            outside_target.write_text("{}", encoding="utf-8")
            try:
                os.symlink(outside_target, root / "operator-note-link.json")
            except (OSError, NotImplementedError) as exc:
                raise unittest.SkipTest(f"symlink not available: {exc}") from exc

            result = handoff_validator.validate_handoff_bundle(root)

        self.assertFalse(result.ok)
        self.assertEqual(1, result.unexpected_count)
        self.assertIn(
            "unexpected_handoff_report_symlink",
            result.to_dict()["error_codes"],
        )
        unexpected_row = next(
            row
            for row in result.to_dict()["rows"]
            if row["file_name"] == "operator-note-link.json"
        )
        self.assertIsNone(unexpected_row["report_sha256"])

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff_validator.main([str(root), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual([], payload["error_codes"])

    def test_cli_json_out_writes_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root, _payload = _generate_handoff_bundle(base=base)
            out_path = base / "completion-audit-validation.json"

            exit_code = handoff_validator.main(
                [str(root), "--json", "--out", str(out_path)]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            handoff_validator.HANDOFF_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )

    def test_cli_rejects_output_inside_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff_validator.main(
                    [
                        str(root),
                        "--json",
                        "--out",
                        str(root / "validation.json"),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["handoff_validation_output_path_inside_bundle_root"],
            payload["error_codes"],
        )

    def test_cli_can_require_completion_audit_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(base=Path(temp_dir))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff_validator.main(
                    [
                        str(root),
                        "--json",
                        "--require-completion-audit-ready",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["completion_audit_ready"], payload)

    def test_cli_ready_requirement_fails_for_not_ready_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root, _payload = _generate_handoff_bundle(
                base=Path(temp_dir),
                ready=False,
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff_validator.main(
                    [
                        str(root),
                        "--json",
                        "--require-completion-audit-ready",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["completion_audit_ready"])
        self.assertIn(
            "handoff_completion_audit_not_ready",
            payload["error_codes"],
        )

    def test_cli_json_reports_missing_bundle_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff_validator.main(
                    [str(Path(temp_dir) / "missing"), "--json"]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(["handoff_bundle_root_missing"], payload["error_codes"])


if __name__ == "__main__":
    unittest.main()
