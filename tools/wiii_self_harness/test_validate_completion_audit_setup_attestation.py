import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_attestation as generator
from test_apply_completion_audit_setup_state import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_attestation import (
    _attest_specs_from_state,
)
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_attestation as validator


def _write_valid_attestation_bundle(root: Path) -> tuple[Path, Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root)
    setup_payload = _load_json(setup_state_path)
    attestation = generator.generate_completion_audit_setup_attestation(
        setup_state_path,
        _attest_specs_from_state(setup_payload)[:1],
        launch_pack_path=launch_pack_path,
    )
    attestation_path = root / "setup-attestation.json"
    patch_path = root / "setup-handle-patch.json"
    _write_json(attestation_path, attestation)
    _write_json(patch_path, generator.setup_handle_patch_from_attestation(attestation))
    return launch_pack_path, setup_state_path, attestation_path, patch_path


def _refresh_attestation_fingerprint(attestation: dict) -> None:
    attestation["setup_attestation_fingerprint_sha256"] = (
        generator._attestation_fingerprint(attestation["attestations"])
    )


class ValidateCompletionAuditSetupAttestationTests(unittest.TestCase):
    def test_cli_json_accepts_matching_attestation_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, attestation_path, patch_path = (
                _write_valid_attestation_bundle(root)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(attestation_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--patch",
                        str(patch_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.SETUP_ATTESTATION_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual([], payload["error_codes"])

    def test_cli_json_reports_patch_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, attestation_path, patch_path = (
                _write_valid_attestation_bundle(root)
            )
            patch = _load_json(patch_path)
            patch["checks"][0]["source_handle"] = "UNBOUND_HANDLE"
            _write_json(patch_path, patch)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(attestation_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--patch",
                        str(patch_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(
            ["completion_audit_setup_attestation_patch_mismatch"],
            payload["error_codes"],
        )

    def test_validator_rejects_raw_evidence_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, attestation_path, _patch_path = (
                _write_valid_attestation_bundle(root)
            )
            attestation = _load_json(attestation_path)
            attestation["attestations"][0]["evidence_ref"] = "<raw-recipient-id>"
            _refresh_attestation_fingerprint(attestation)
            _write_json(attestation_path, attestation)

            result = validator.validate_setup_attestation(
                attestation_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertEqual(
            ["completion_audit_setup_attestation_unsafe_token"],
            result.to_dict()["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
