import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import generate_completion_audit_handoff as handoff_module
import smoke_completion_audit_handoff as smoke


def _sample_registry() -> dict:
    return {
        "registry": handoff_module.bundle_validator.REGISTRY_NAME,
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
            }
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
                handoff_module.bundle_validator._registry_fingerprint(registry)
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


class SmokeCompletionAuditHandoffTests(unittest.TestCase):
    def test_json_out_must_stay_outside_generated_handoff_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit-smoke"
            release_gate_json_out = base / "completion-audit-smoke-release-gate.json"

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_INSIDE_BUNDLE_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=report_root,
                    artifact_bundle_root=artifact_root,
                    out_dir=out_dir,
                    json_out=out_dir / "completion-audit-smoke.json",
                    release_gate_json_out=release_gate_json_out,
                )

        self.assertFalse((out_dir / "completion-audit-smoke.json").exists())

    def test_release_gate_json_out_must_stay_outside_input_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit-smoke"

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_INSIDE_BUNDLE_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=report_root,
                    artifact_bundle_root=artifact_root,
                    out_dir=out_dir,
                    json_out=base / "completion-audit-smoke.json",
                    release_gate_json_out=artifact_root
                    / "completion-audit-smoke-release-gate.json",
                )

        self.assertFalse(
            (artifact_root / "completion-audit-smoke-release-gate.json").exists()
        )

    def test_json_out_must_stay_outside_self_harness_report_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit-smoke"

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_INSIDE_BUNDLE_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=report_root,
                    artifact_bundle_root=artifact_root,
                    out_dir=out_dir,
                    json_out=report_root / "completion-audit-smoke.json",
                    release_gate_json_out=base
                    / "completion-audit-smoke-release-gate.json",
                )

        self.assertFalse((report_root / "completion-audit-smoke.json").exists())

    def test_sidecar_output_must_not_be_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            sidecar_dir = base / "completion-audit-smoke.json"
            sidecar_dir.mkdir()

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_DIRECTORY_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=base / "self-harness-reports",
                    artifact_bundle_root=base / "runtime-artifacts",
                    out_dir=base / "completion-audit-smoke",
                    json_out=sidecar_dir,
                    release_gate_json_out=base
                    / "completion-audit-smoke-release-gate.json",
                )

            self.assertTrue(sidecar_dir.is_dir())

    def test_sidecar_output_must_not_be_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            sidecar_target = base / "sidecar-target.json"
            sidecar_link = base / "completion-audit-smoke.json"
            try:
                os.symlink(sidecar_target, sidecar_link)
            except (OSError, NotImplementedError) as exc:
                raise unittest.SkipTest(f"symlink not available: {exc}") from exc

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_SYMLINK_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=base / "self-harness-reports",
                    artifact_bundle_root=base / "runtime-artifacts",
                    out_dir=base / "completion-audit-smoke",
                    json_out=sidecar_link,
                    release_gate_json_out=base
                    / "completion-audit-smoke-release-gate.json",
                )

            self.assertFalse(sidecar_target.exists())

    def test_sidecar_output_must_not_have_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            real_parent = base / "real-sidecar-parent"
            parent_link = base / "linked-sidecar-parent"
            real_parent.mkdir()
            try:
                os.symlink(real_parent, parent_link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                raise unittest.SkipTest(f"symlink not available: {exc}") from exc
            sidecar_path = parent_link / "completion-audit-smoke.json"

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_PARENT_SYMLINK_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=base / "self-harness-reports",
                    artifact_bundle_root=base / "runtime-artifacts",
                    out_dir=base / "completion-audit-smoke",
                    json_out=sidecar_path,
                    release_gate_json_out=base
                    / "completion-audit-smoke-release-gate.json",
                )

            self.assertFalse((real_parent / "completion-audit-smoke.json").exists())

    def test_sidecar_outputs_must_be_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            sidecar_path = base / "completion-audit-smoke.json"

            with self.assertRaisesRegex(
                ValueError,
                smoke.SMOKE_SIDECAR_OUTPUT_PATH_DUPLICATE_ERROR,
            ):
                smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=base / "self-harness-reports",
                    artifact_bundle_root=base / "runtime-artifacts",
                    out_dir=base / "completion-audit-smoke",
                    json_out=sidecar_path,
                    release_gate_json_out=sidecar_path,
                )

        self.assertFalse(sidecar_path.exists())

    def test_cli_rejects_sidecar_inside_handoff_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = smoke.main(
                    [
                        "--self-harness-report-bundle",
                        str(base / "self-harness-reports"),
                        "--artifact-bundle-root",
                        str(base / "runtime-artifacts"),
                        "--out-dir",
                        str(base / "completion-audit-smoke"),
                        "--json-out",
                        str(base / "completion-audit-smoke" / "smoke.json"),
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn(
            smoke.SMOKE_SIDECAR_OUTPUT_PATH_INSIDE_BUNDLE_ERROR,
            stderr.getvalue(),
        )

    def test_smoke_passes_when_empty_evidence_handoff_is_not_ready(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit-smoke"
            json_out = base / "completion-audit-smoke.json"
            release_gate_json_out = base / "completion-audit-smoke-release-gate.json"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_report_bundle_coverage(report_root, registry)

            with (
                mock.patch.object(
                    handoff_module.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff_module.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
            ):
                payload = smoke.run_completion_audit_handoff_smoke(
                    self_harness_report_bundle_root=report_root,
                    artifact_bundle_root=artifact_root,
                    out_dir=out_dir,
                    json_out=json_out,
                    release_gate_json_out=release_gate_json_out,
                    registry_path=registry_path,
                    as_of="2026-06-01T12:00:00+00:00",
                )
            persisted = json.loads(json_out.read_text(encoding="utf-8"))
            release_gate_persisted = json.loads(
                release_gate_json_out.read_text(encoding="utf-8")
            )

        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["handoff_validation"]["ok"], payload)
        self.assertFalse(payload["release_gate_validation"]["ok"], payload)
        self.assertFalse(
            payload["handoff_validation"]["require_completion_audit_ready"],
            payload,
        )
        self.assertTrue(
            payload["release_gate_validation"]["require_completion_audit_ready"],
            payload,
        )
        self.assertNotEqual(
            payload["handoff_validation"]["bundle_fingerprint_sha256"],
            payload["release_gate_validation"]["bundle_fingerprint_sha256"],
        )
        self.assertFalse(payload["handoff_ok"])
        self.assertFalse(payload["completion_audit_ready"])
        self.assertIn(
            "handoff_completion_audit_not_ready",
            payload["release_gate_validation"]["error_codes"],
        )
        self.assertEqual(payload["release_gate_validation"], release_gate_persisted)
        self.assertEqual(payload, persisted)
        self.assertEqual(
            ["missing_artifact"],
            payload["runtime_evidence_bundle_report"]["error_codes"],
        )
        self.assertEqual(
            payload["runtime_evidence_bundle_report"]["requirement_count"],
            payload["runtime_evidence_bundle_report"]["missing_count"],
        )

    def test_cli_writes_json_out_for_successful_smoke(self) -> None:
        registry = _sample_registry()
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            artifact_root = base / "runtime-artifacts"
            report_root = base / "self-harness-reports"
            out_dir = base / "completion-audit-smoke"
            json_out = base / "completion-audit-smoke.json"
            release_gate_json_out = base / "completion-audit-smoke-release-gate.json"
            artifact_root.mkdir()
            report_root.mkdir()
            registry_path = base / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            _write_report_bundle_coverage(report_root, registry)
            stdout = io.StringIO()

            with (
                mock.patch.object(
                    handoff_module.bundle_validator,
                    "require_valid_registry_contract",
                ),
                mock.patch.object(
                    handoff_module.bundle_validator,
                    "validate_self_harness_report_bundle_contract",
                    return_value=_valid_report_bundle_result(fingerprint="a" * 64),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = smoke.main(
                    [
                        "--self-harness-report-bundle",
                        str(report_root),
                        "--artifact-bundle-root",
                        str(artifact_root),
                        "--out-dir",
                        str(out_dir),
                        "--json-out",
                        str(json_out),
                        "--release-gate-json-out",
                        str(release_gate_json_out),
                        "--registry",
                        str(registry_path),
                        "--as-of",
                        "2026-06-01T12:00:00+00:00",
                    ]
                )
            persisted = json.loads(json_out.read_text(encoding="utf-8"))
            release_gate_persisted = json.loads(
                release_gate_json_out.read_text(encoding="utf-8")
            )

        self.assertEqual(0, exit_code)
        self.assertIn("Wiii Completion Audit Handoff Smoke: PASS", stdout.getvalue())
        self.assertTrue(persisted["ok"], persisted)
        self.assertTrue(persisted["handoff_validation"]["ok"], persisted)
        self.assertFalse(persisted["release_gate_validation"]["ok"], persisted)
        self.assertFalse(
            persisted["handoff_validation"]["require_completion_audit_ready"],
            persisted,
        )
        self.assertTrue(
            persisted["release_gate_validation"]["require_completion_audit_ready"],
            persisted,
        )
        self.assertNotEqual(
            persisted["handoff_validation"]["bundle_fingerprint_sha256"],
            persisted["release_gate_validation"]["bundle_fingerprint_sha256"],
        )
        self.assertFalse(persisted["completion_audit_ready"])
        self.assertIn(
            "handoff_completion_audit_not_ready",
            persisted["release_gate_validation"]["error_codes"],
        )
        self.assertEqual(
            persisted["release_gate_validation"],
            release_gate_persisted,
        )


if __name__ == "__main__":
    unittest.main()
