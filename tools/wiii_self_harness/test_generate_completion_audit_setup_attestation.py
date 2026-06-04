import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import apply_completion_audit_setup_state as applier
import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_setup_attestation as generator
from test_apply_completion_audit_setup_state import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_attestation as validator


def _attest_specs_from_state(payload: dict) -> list[str]:
    specs: list[str] = []
    for requirement in payload["requirements"]:
        for check in requirement["setup_checks"]:
            token = check["binding_tokens"][0]
            specs.append(
                (
                    f"{requirement['requirement_id']}:{check['category']}:"
                    f"{check['key']}={token}@"
                    f"{_evidence_kind(check['category'])}:{token}"
                )
            )
    return specs


def _evidence_kind(category: str) -> str:
    if category == "workflow_inputs_required":
        return "workflow_input_bound"
    if category == "environment_flags_required":
        return "environment_flag_bound"
    if category == "credential_slots_required":
        return "github_secret_present"
    return "operator_approved_recipient"


class GenerateCompletionAuditSetupAttestationTests(unittest.TestCase):
    def test_generate_attestation_patch_can_unlock_dispatch_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation = generator.generate_completion_audit_setup_attestation(
                setup_state_path,
                _attest_specs_from_state(setup_payload),
                launch_pack_path=launch_pack_path,
            )
            attestation_path = root / "setup-attestation.json"
            patch_path = root / "setup-handle-patch.json"
            applied_path = root / "setup-state-applied.json"
            _write_json(attestation_path, attestation)
            patch = generator.setup_handle_patch_from_attestation(attestation)
            _write_json(patch_path, patch)

            validation = validator.validate_setup_attestation(
                attestation_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
                patch_path=patch_path,
            )
            applied = applier.apply_completion_audit_setup_state(
                setup_state_path,
                patch_path,
                launch_pack_path=launch_pack_path,
            )
            _write_json(applied_path, applied)
            gate = gate_generator.generate_completion_audit_dispatch_gate(
                launch_pack_path,
                applied_path,
            ).to_dict()

        self.assertTrue(validation.ok, validation.to_dict())
        self.assertEqual(
            generator.SETUP_ATTESTATION_SCHEMA_VERSION,
            attestation["schema_version"],
        )
        self.assertEqual(len(patch["checks"]), attestation["attestation_count"])
        self.assertTrue(applied["dispatch_ready"], applied)
        self.assertTrue(gate["dispatch_ready"], gate)
        rendered = json.dumps(attestation, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_cli_writes_attestation_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation_path = root / "setup-attestation.json"
            patch_path = root / "setup-handle-patch.json"

            exit_code = generator.main(
                [
                    str(setup_state_path),
                    "--attest",
                    _attest_specs_from_state(setup_payload)[0],
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(attestation_path),
                    "--patch-out",
                    str(patch_path),
                ]
            )
            attestation = _load_json(attestation_path)
            patch = _load_json(patch_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(1, attestation["attestation_count"])
        self.assertEqual(1, len(patch["checks"]))

    def test_cli_rejects_raw_evidence_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(setup_state_path),
                        "--attest",
                        (
                            "autonomy-proactive-channel:external_setup_required:"
                            "approved_recipient=proactive_recipient_id@"
                            "operator_approved_recipient:<raw-recipient-id>"
                        ),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_unsafe_token"],
            payload["error_codes"],
        )

    def test_validator_rejects_stale_setup_state_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation = generator.generate_completion_audit_setup_attestation(
                setup_state_path,
                _attest_specs_from_state(setup_payload)[:1],
                launch_pack_path=launch_pack_path,
            )
            attestation["setup_state_sha256"] = "0" * 64
            attestation_path = root / "setup-attestation.json"
            _write_json(attestation_path, attestation)

            result = validator.validate_setup_attestation(
                attestation_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_attestation_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_validator_rejects_patch_not_matching_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
            patch = generator.setup_handle_patch_from_attestation(attestation)
            patch["checks"][0]["source_handle"] = "UNBOUND_HANDLE"
            _write_json(patch_path, patch)

            result = validator.validate_setup_attestation(
                attestation_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
                patch_path=patch_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_attestation_patch_mismatch",
            result.to_dict()["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
