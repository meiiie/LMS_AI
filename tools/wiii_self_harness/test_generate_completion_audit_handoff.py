import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import generate_completion_audit_handoff as handoff


def _sample_registry() -> dict:
    return {
        "registry": handoff.bundle_validator.REGISTRY_NAME,
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


def _write_report_bundle_coverage(root: Path, registry: dict) -> None:
    _write_json(
        root / "runtime-evidence-coverage.json",
        {
            "registry_fingerprint_sha256": (
                handoff.bundle_validator._registry_fingerprint(registry)
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
            "schema_version": handoff.readiness_reporter.READINESS_REPORT_SCHEMA_VERSION,
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
                handoff.control_chain_validator.CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION
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
            "schema_version": handoff.setup_gap_validator.SETUP_GAP_REPORT_SCHEMA_VERSION,
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


class GenerateCompletionAuditHandoffTests(unittest.TestCase):
    as_of = "2026-06-01T12:00:00+00:00"

    def test_generate_handoff_writes_completion_audit_reports(self) -> None:
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

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                result = handoff.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of=self.as_of,
                )
            payload = result.to_dict()
            report_payload = json.loads(
                (out_dir / handoff.RUNTIME_BUNDLE_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )
            handoff_payload = json.loads(
                (out_dir / handoff.HANDOFF_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )
            markdown = (out_dir / handoff.RUNTIME_BUNDLE_MARKDOWN_REPORT).read_text(
                encoding="utf-8"
            )
            handoff_markdown = (out_dir / handoff.HANDOFF_MARKDOWN_REPORT).read_text(
                encoding="utf-8"
            )
            report_names = sorted(path.name for path in out_dir.iterdir())

        self.assertTrue(result.ok, payload)
        self.assertTrue(payload["completion_audit_ready"], payload)
        self.assertEqual(
            sorted(handoff.EXPECTED_GENERATED_REPORTS),
            report_names,
        )
        self.assertEqual(payload, handoff_payload)
        self.assertTrue(handoff_payload["completion_audit_ready"], handoff_payload)
        self.assertEqual(
            report_payload["completion_audit_fingerprint_sha256"],
            handoff_payload["completion_audit_fingerprint_sha256"],
        )
        self.assertEqual(
            report_payload["bundle_fingerprint_sha256"],
            handoff_payload["runtime_evidence_bundle_fingerprint_sha256"],
        )
        self.assertTrue(report_payload["completion_audit_ready"], report_payload)
        self.assertEqual(0, handoff_payload["release_blocker_count"])
        self.assertEqual([], handoff_payload["release_blockers"])
        self.assertIsNone(handoff_payload["readiness_summary"])
        self.assertIn("Completion audit ready", markdown)
        self.assertIn("# Wiii Completion Audit Handoff", handoff_markdown)
        self.assertIn("Release blocker count", handoff_markdown)
        self.assertIn("Readiness report", handoff_markdown)
        self.assertIn("Completion audit fingerprint SHA-256", handoff_markdown)
        self.assertRegex(
            report_payload["completion_audit_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )

    def test_generate_handoff_self_validates_written_reports(self) -> None:
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

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
                mock.patch.object(handoff, "_validate_generated_handoff") as validator,
            ):
                result = handoff.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of=self.as_of,
                )

        self.assertTrue(result.ok, result.to_dict())
        validator.assert_called_once_with(out_dir)

    def test_generate_handoff_embeds_pending_setup_gate_summary(self) -> None:
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
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                result = handoff.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of=self.as_of,
                    control_chain_report_path=control_path,
                    setup_gap_report_path=setup_gap_path,
                    setup_gap_markdown_report_path=setup_gap_markdown_path,
                )
            handoff_payload = json.loads(
                (out_dir / handoff.HANDOFF_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )
            handoff_markdown = (out_dir / handoff.HANDOFF_MARKDOWN_REPORT).read_text(
                encoding="utf-8"
            )

        self.assertTrue(handoff_payload["completion_audit_ready"], handoff_payload)
        self.assertFalse(handoff_payload["release_handoff_ready"], handoff_payload)
        self.assertFalse(result.ok, result.to_dict())
        self.assertEqual(
            str(control_path),
            handoff_payload["control_chain_summary"]["path"],
        )
        self.assertEqual(
            2,
            handoff_payload["setup_gap_summary"]["pending_setup_check_count"],
        )
        self.assertEqual(3, handoff_payload["release_blocker_count"])
        self.assertEqual(
            [
                {
                    "kind": "control_chain",
                    "blocker_id": "control_chain_ready",
                    "status": "blocked",
                    "error_codes": [],
                },
                {
                    "kind": "control_chain",
                    "blocker_id": "dispatch_ready",
                    "status": "blocked",
                    "error_codes": [],
                },
                {
                    "kind": "setup_gap",
                    "requirement_id": "lms-test-course-replay",
                    "pending_setup_check_count": 2,
                    "diagnostic_pending_setup_keys": [
                        "credential_slots_required:external_lms_apply_token",
                    ],
                    "non_diagnostic_pending_setup_keys": [
                        "credential_slots_required:lms_backend_bearer_token",
                    ],
                    "resolution_actions": [
                        {
                            "category": "credential_slots_required",
                            "key": "external_lms_apply_token",
                            "evidence_kind": "credential_slot_bound",
                            "binding_token_count": 1,
                            "source_handle_options": ["EXTERNAL_LMS_APPLY_TOKEN"],
                            "attestation_option_count": 1,
                        },
                        {
                            "category": "credential_slots_required",
                            "key": "lms_backend_bearer_token",
                            "evidence_kind": "credential_slot_bound",
                            "binding_token_count": 1,
                            "source_handle_options": ["LMS_BACKEND_BEARER_TOKEN"],
                            "attestation_option_count": 1,
                        },
                    ],
                },
            ],
            handoff_payload["release_blockers"],
        )
        self.assertIn("control_chain:control_chain_ready:blocked:-", handoff_markdown)
        self.assertIn("setup_gap:lms-test-course-replay:pending=2", handoff_markdown)
        self.assertIn("EXTERNAL_LMS_APPLY_TOKEN", handoff_markdown)
        self.assertIn(
            "credential_slots_required:external_lms_apply_token",
            handoff_markdown,
        )
        self.assertIn(
            "credential_slots_required:lms_backend_bearer_token",
            handoff_markdown,
        )

    def test_generate_handoff_embeds_setup_summary_release_blockers(self) -> None:
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
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                handoff.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of=self.as_of,
                    control_chain_report_path=control_path,
                    setup_gap_report_path=setup_gap_path,
                    setup_gap_markdown_report_path=setup_gap_markdown_path,
                )
            handoff_payload = json.loads(
                (out_dir / handoff.HANDOFF_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )
            handoff_markdown = (out_dir / handoff.HANDOFF_MARKDOWN_REPORT).read_text(
                encoding="utf-8"
            )

        self.assertEqual(5, handoff_payload["release_blocker_count"])
        self.assertIn(
            {
                "kind": "setup_gap_summary",
                "blocker_id": "setup_gap_ok",
                "status": "blocked",
                "pending_setup_check_count": 2,
                "diagnostic_present_setup_mismatch_count": 1,
            },
            handoff_payload["release_blockers"],
        )
        self.assertIn(
            {
                "kind": "setup_gap_summary",
                "blocker_id": "setup_diagnostic_mismatch",
                "status": "blocked",
                "pending_setup_check_count": 2,
                "diagnostic_present_setup_mismatch_count": 1,
            },
            handoff_payload["release_blockers"],
        )
        self.assertIn("setup_gap_summary:setup_gap_ok:blocked", handoff_markdown)
        self.assertIn(
            "setup_gap_summary:setup_diagnostic_mismatch:blocked",
            handoff_markdown,
        )

    def test_missing_artifact_writes_not_ready_handoff_report(self) -> None:
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
            _write_json(
                artifact_root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_report_bundle_coverage(report_root, registry)

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                result = handoff.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of=self.as_of,
                )
            report_payload = json.loads(
                (out_dir / handoff.RUNTIME_BUNDLE_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )
            handoff_payload = json.loads(
                (out_dir / handoff.HANDOFF_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(result.ok)
        self.assertFalse(handoff_payload["ok"])
        self.assertFalse(handoff_payload["completion_audit_ready"])
        self.assertEqual(
            [
                {
                    "requirement_id": "sample-b",
                    "artifact": "sample-b.json",
                    "status": "missing",
                    "error_codes": ["missing_artifact"],
                },
            ],
            handoff_payload["runtime_blockers"],
        )
        self.assertEqual(
            [
                {
                    "kind": "runtime_evidence",
                    "requirement_id": "sample-b",
                    "artifact": "sample-b.json",
                    "status": "missing",
                    "error_codes": ["missing_artifact"],
                    "recovery_action": None,
                },
            ],
            handoff_payload["release_blockers"],
        )
        self.assertEqual(1, handoff_payload["release_blocker_count"])
        self.assertFalse(report_payload["completion_audit_ready"])
        self.assertFalse(report_payload["ok"])
        self.assertEqual(["missing_artifact"], report_payload["error_codes"])

    def test_generate_handoff_binds_readiness_recovery_actions(self) -> None:
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
            _write_json(
                artifact_root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_report_bundle_coverage(report_root, registry)
            readiness_path = _write_readiness_report(base)

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                handoff.generate_completion_audit_handoff(
                    artifact_bundle_root=artifact_root,
                    self_harness_report_bundle_root=report_root,
                    out_dir=out_dir,
                    registry_path=registry_path,
                    as_of=self.as_of,
                    readiness_report_path=readiness_path,
                )
            handoff_payload = json.loads(
                (out_dir / handoff.HANDOFF_JSON_REPORT).read_text(
                    encoding="utf-8"
                )
            )
            handoff_markdown = (out_dir / handoff.HANDOFF_MARKDOWN_REPORT).read_text(
                encoding="utf-8"
            )

        self.assertEqual(
            1,
            handoff_payload["readiness_summary"]["scoped_next_action_count"],
        )
        self.assertEqual(1, handoff_payload["release_blocker_count"])
        recovery_action = handoff_payload["release_blockers"][0]["recovery_action"]
        self.assertEqual(".github/workflows/sample.yml", recovery_action["workflow"])
        self.assertEqual(["sample-b-live"], recovery_action["live_guard_tokens"])
        self.assertIn("Readiness report", handoff_markdown)
        self.assertIn(
            "recovery=.github/workflows/sample.yml/"
            "maritime-ai-service/scripts/probe_sample_b.py",
            handoff_markdown,
        )

    def test_cli_json_reports_generated_handoff(self) -> None:
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
            stdout = io.StringIO()

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_dir),
                        "--registry",
                        str(registry_path),
                        "--as-of",
                        self.as_of,
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["completion_audit_ready"], payload)
        self.assertEqual(
            list(handoff.EXPECTED_GENERATED_REPORTS),
            payload["reports"],
        )

    def test_cli_allow_not_ready_returns_zero_for_structural_handoff(self) -> None:
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
            _write_json(
                artifact_root / "sample-a.json",
                {
                    "schema_version": "wiii.sample_a.v1",
                    "status": "pass",
                    "generated_at": "2026-06-01T10:00:00+00:00",
                },
            )
            _write_report_bundle_coverage(report_root, registry)
            stdout = io.StringIO()

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_dir),
                        "--registry",
                        str(registry_path),
                        "--as-of",
                        self.as_of,
                        "--allow-not-ready",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["completion_audit_ready"])
        self.assertFalse(payload["release_handoff_ready"])
        self.assertEqual(["sample-b"], [row["requirement_id"] for row in payload["runtime_blockers"]])
        self.assertEqual(
            list(handoff.EXPECTED_GENERATED_REPORTS),
            payload["reports"],
        )

    def test_cli_json_reports_generated_handoff_self_validation_failure(self) -> None:
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
            stdout = io.StringIO()

            with (
                mock.patch.object(
                    handoff.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
                mock.patch.object(
                    handoff,
                    "_validate_generated_handoff",
                    side_effect=ValueError(
                        handoff.GENERATED_HANDOFF_VALIDATION_ERROR
                        + ": runtime_markdown_document_mismatch"
                    ),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_dir),
                        "--registry",
                        str(registry_path),
                        "--as-of",
                        self.as_of,
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_generated_handoff_invalid"],
            payload["error_codes"],
        )

    def test_cli_json_reports_output_dir_inside_artifact_bundle(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(artifact_root / "completion-audit"),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_output_dir_inside_artifact_bundle"],
            payload["error_codes"],
        )
        self.assertFalse((artifact_root / "completion-audit").exists())

    def test_cli_json_reports_output_dir_inside_self_harness_bundle(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(report_root / "completion-audit"),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_output_dir_inside_self_harness_bundle"],
            payload["error_codes"],
        )
        self.assertFalse((report_root / "completion-audit").exists())

    def test_cli_json_reports_non_empty_output_dir(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            out_dir.mkdir()
            stale_file = out_dir / "operator-note.txt"
            stale_file.write_text("do not mix old handoffs", encoding="utf-8")
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_dir),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            stale_text = stale_file.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_output_dir_not_empty"],
            payload["error_codes"],
        )
        self.assertEqual("do not mix old handoffs", stale_text)

    def test_cli_json_reports_output_path_not_directory(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_path = base / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            out_path.write_text("not a directory", encoding="utf-8")
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_path),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            out_text = out_path.read_text(encoding="utf-8")

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_output_path_not_directory"],
            payload["error_codes"],
        )
        self.assertEqual("not a directory", out_text)

    def test_cli_json_reports_output_dir_symlink(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            target_dir = base / "target-completion-audit"
            out_dir = base / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            target_dir.mkdir()
            try:
                os.symlink(target_dir, out_dir, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_dir),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            target_entries = list(target_dir.iterdir())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_output_dir_symlink"],
            payload["error_codes"],
        )
        self.assertEqual([], target_entries)

    def test_cli_json_reports_output_dir_parent_symlink(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            target_parent = base / "target-parent"
            symlink_parent = base / "linked-parent"
            out_dir = symlink_parent / "completion-audit"
            artifact_root.mkdir()
            report_root.mkdir()
            target_parent.mkdir()
            try:
                os.symlink(target_parent, symlink_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = handoff.main(
                    [
                        str(artifact_root),
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--out-dir",
                        str(out_dir),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_output_dir_parent_symlink"],
            payload["error_codes"],
        )
        self.assertFalse(out_dir.exists())


if __name__ == "__main__":
    unittest.main()
