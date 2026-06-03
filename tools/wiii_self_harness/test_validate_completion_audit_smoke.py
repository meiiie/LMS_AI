import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from generate_completion_audit_handoff import EXPECTED_GENERATED_REPORTS
import validate_completion_audit_smoke as validator


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _structural_validation_payload() -> dict:
    return {
        "ok": True,
        "require_completion_audit_ready": False,
        "bundle_fingerprint_sha256": "a" * 64,
        "error_codes": [],
        "error_code_counts": {},
    }


def _release_gate_validation_payload() -> dict:
    return {
        "ok": False,
        "require_completion_audit_ready": True,
        "bundle_fingerprint_sha256": "b" * 64,
        "error_codes": ["handoff_completion_audit_not_ready"],
        "error_code_counts": {"handoff_completion_audit_not_ready": 1},
    }


def _smoke_payload() -> dict:
    return {
        "schema_version": validator.SMOKE_SCHEMA_VERSION,
        "ok": True,
        "handoff_ok": False,
        "completion_audit_ready": False,
        "handoff_root": "artifacts/wiii-completion-audit-smoke",
        "artifact_bundle_root": "artifacts/runtime-evidence-empty",
        "self_harness_report_bundle_root": "artifacts/wiii-self-harness",
        "reports": list(EXPECTED_GENERATED_REPORTS),
        "handoff_validation": _structural_validation_payload(),
        "release_gate_validation": _release_gate_validation_payload(),
        "runtime_evidence_bundle_report": {
            "ok": False,
            "completion_audit_ready": False,
            "error_codes": ["missing_artifact"],
            "requirement_count": 2,
            "missing_count": 2,
        },
    }


def _write_valid_sidecars(base: Path) -> tuple[Path, Path, Path]:
    payload = _smoke_payload()
    smoke_json = base / "completion-audit-smoke.json"
    release_gate_json = base / "completion-audit-smoke-release-gate-validation.json"
    structural_json = base / "completion-audit-smoke-validation.json"
    _write_json(smoke_json, payload)
    _write_json(release_gate_json, payload["release_gate_validation"])
    _write_json(structural_json, payload["handoff_validation"])
    return smoke_json, release_gate_json, structural_json


def _validation_result(payload: dict):
    return mock.Mock(to_dict=mock.Mock(return_value=payload))


class ValidateCompletionAuditSmokeTests(unittest.TestCase):
    def test_valid_sidecars_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )

            result = validator.validate_completion_audit_smoke_sidecars(
                smoke_json_path=smoke_json,
                release_gate_json_path=release_gate_json,
                structural_validation_json_path=structural_json,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.errors)
        self.assertEqual([], result.to_dict()["error_codes"])
        self.assertEqual({}, result.to_dict()["error_code_counts"])

    def test_release_gate_sidecar_must_match_smoke_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )
            tampered = _release_gate_validation_payload()
            tampered["error_codes"] = []
            _write_json(release_gate_json, tampered)

            result = validator.validate_completion_audit_smoke_sidecars(
                smoke_json_path=smoke_json,
                release_gate_json_path=release_gate_json,
                structural_validation_json_path=structural_json,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "smoke_release_gate_sidecar_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_handoff_root_source_revalidation_can_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )

            with mock.patch.object(
                validator,
                "validate_handoff_bundle",
                side_effect=[
                    _validation_result(_structural_validation_payload()),
                    _validation_result(_release_gate_validation_payload()),
                ],
            ) as validate_handoff:
                result = validator.validate_completion_audit_smoke_sidecars(
                    smoke_json_path=smoke_json,
                    release_gate_json_path=release_gate_json,
                    structural_validation_json_path=structural_json,
                    require_handoff_root_source=True,
                )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(2, validate_handoff.call_count)

    def test_handoff_root_source_revalidation_rejects_stale_structural_sidecar(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )
            stale_structural = _structural_validation_payload()
            stale_structural["bundle_fingerprint_sha256"] = "c" * 64

            with mock.patch.object(
                validator,
                "validate_handoff_bundle",
                side_effect=[
                    _validation_result(stale_structural),
                    _validation_result(_release_gate_validation_payload()),
                ],
            ):
                result = validator.validate_completion_audit_smoke_sidecars(
                    smoke_json_path=smoke_json,
                    release_gate_json_path=release_gate_json,
                    structural_validation_json_path=structural_json,
                    require_handoff_root_source=True,
                )

        self.assertFalse(result.ok)
        self.assertIn(
            "smoke_structural_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_structural_sidecar_must_match_smoke_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )
            tampered = _structural_validation_payload()
            tampered["require_completion_audit_ready"] = True
            _write_json(structural_json, tampered)

            result = validator.validate_completion_audit_smoke_sidecars(
                smoke_json_path=smoke_json,
                release_gate_json_path=release_gate_json,
                structural_validation_json_path=structural_json,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "smoke_structural_sidecar_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_validation_policy_modes_and_fingerprints_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = _smoke_payload()
            payload["handoff_validation"]["require_completion_audit_ready"] = True
            payload["release_gate_validation"]["bundle_fingerprint_sha256"] = "a" * 64
            smoke_json = base / "completion-audit-smoke.json"
            release_gate_json = base / "release-gate.json"
            _write_json(smoke_json, payload)
            _write_json(release_gate_json, payload["release_gate_validation"])

            result = validator.validate_completion_audit_smoke_sidecars(
                smoke_json_path=smoke_json,
                release_gate_json_path=release_gate_json,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "smoke_structural_policy_mode_mismatch",
            result.to_dict()["error_codes"],
        )
        self.assertIn(
            "smoke_validation_fingerprint_policy_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_runtime_report_must_be_empty_evidence_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = _smoke_payload()
            payload["runtime_evidence_bundle_report"]["missing_count"] = 1
            smoke_json = base / "completion-audit-smoke.json"
            release_gate_json = base / "release-gate.json"
            _write_json(smoke_json, payload)
            _write_json(release_gate_json, payload["release_gate_validation"])

            result = validator.validate_completion_audit_smoke_sidecars(
                smoke_json_path=smoke_json,
                release_gate_json_path=release_gate_json,
            )

        self.assertFalse(result.ok)
        self.assertIn("smoke_runtime_report_mismatch", result.to_dict()["error_codes"])

    def test_cli_returns_nonzero_for_mismatched_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )
            tampered = _release_gate_validation_payload()
            tampered["ok"] = True
            _write_json(release_gate_json, tampered)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = validator.main(
                    [
                        str(smoke_json),
                        "--release-gate-json",
                        str(release_gate_json),
                        "--structural-validation-json",
                        str(structural_json),
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn(
            "release-gate sidecar JSON must match smoke payload",
            stderr.getvalue(),
        )

    def test_cli_can_print_json_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_json, release_gate_json, structural_json = _write_valid_sidecars(
                Path(temp_dir)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(smoke_json),
                        "--release-gate-json",
                        str(release_gate_json),
                        "--structural-validation-json",
                        str(structural_json),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            validator.SMOKE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
