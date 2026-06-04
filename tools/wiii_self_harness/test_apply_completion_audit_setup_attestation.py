import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import apply_completion_audit_setup_attestation as applier
import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_setup_attestation as attestation_generator
from test_apply_completion_audit_setup_state import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_attestation import _attest_specs_from_state
from test_validate_completion_audit_setup_state import _load_json


def _write_attestation(
    root: Path,
    setup_state_path: Path,
    specs: list[str],
    *,
    launch_pack_path: Path | None = None,
) -> Path:
    attestation = attestation_generator.generate_completion_audit_setup_attestation(
        setup_state_path,
        specs,
        launch_pack_path=launch_pack_path,
    )
    attestation_path = root / "setup-attestation.json"
    _write_json(attestation_path, attestation)
    return attestation_path


def _refresh_attestation_fingerprint(attestation: dict) -> None:
    attestation["setup_attestation_fingerprint_sha256"] = (
        attestation_generator._attestation_fingerprint(attestation["attestations"])
    )


class ApplyCompletionAuditSetupAttestationTests(unittest.TestCase):
    def test_apply_all_attested_setup_handles_unlocks_dispatch_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation_path = _write_attestation(
                root,
                setup_state_path,
                _attest_specs_from_state(setup_payload),
                launch_pack_path=launch_pack_path,
            )
            applied_path = root / "setup-state-applied.json"

            applied = applier.apply_completion_audit_setup_attestation(
                setup_state_path,
                attestation_path,
                launch_pack_path=launch_pack_path,
            )
            _write_json(applied_path, applied)
            gate = gate_generator.generate_completion_audit_dispatch_gate(
                launch_pack_path,
                applied_path,
            ).to_dict()

        self.assertTrue(applied["dispatch_ready"], applied)
        self.assertEqual(applied["requirement_count"], applied["ready_requirement_count"])
        self.assertEqual(0, applied["blocked_requirement_count"])
        self.assertTrue(gate["dispatch_ready"], gate)
        self.assertEqual(2, gate["ready_dispatch_item_count"])
        rendered = json.dumps(applied, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_cli_writes_standard_applied_setup_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation_path = _write_attestation(
                root,
                setup_state_path,
                _attest_specs_from_state(setup_payload)[:1],
                launch_pack_path=launch_pack_path,
            )
            out_path = root / "setup-state-applied.json"

            exit_code = applier.main(
                [
                    str(setup_state_path),
                    str(attestation_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(applier.setup_applier.SETUP_STATE_SCHEMA_VERSION, payload["schema_version"])
        self.assertFalse(payload["dispatch_ready"])
        ready_check_count = sum(
            1
            for requirement in payload["requirements"]
            for check in requirement["setup_checks"]
            if check["present"] is True
        )
        self.assertEqual(1, ready_check_count)

    def test_cli_rejects_stale_attestation_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation_path = _write_attestation(
                root,
                setup_state_path,
                _attest_specs_from_state(setup_payload)[:1],
                launch_pack_path=launch_pack_path,
            )
            attestation = _load_json(attestation_path)
            attestation["setup_state_sha256"] = "0" * 64
            _write_json(attestation_path, attestation)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = applier.main(
                    [
                        str(setup_state_path),
                        str(attestation_path),
                        "--launch-pack",
                        str(launch_pack_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_apply_attestation_invalid"],
            payload["error_codes"],
        )
        self.assertIn("must match setup state source", payload["errors"][0])

    def test_cli_rejects_raw_evidence_ref_through_attestation_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation_path = _write_attestation(
                root,
                setup_state_path,
                _attest_specs_from_state(setup_payload)[:1],
                launch_pack_path=launch_pack_path,
            )
            attestation = _load_json(attestation_path)
            attestation["attestations"][0]["evidence_ref"] = "<raw-recipient-id>"
            _refresh_attestation_fingerprint(attestation)
            _write_json(attestation_path, attestation)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = applier.main(
                    [
                        str(setup_state_path),
                        str(attestation_path),
                        "--launch-pack",
                        str(launch_pack_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_apply_attestation_invalid"],
            payload["error_codes"],
        )
        self.assertIn("safe token handle", payload["errors"][0])

    def test_cli_rejects_unbound_derived_patch_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            attestation_path = _write_attestation(
                root,
                setup_state_path,
                _attest_specs_from_state(setup_payload)[:1],
                launch_pack_path=launch_pack_path,
            )
            attestation = _load_json(attestation_path)
            attestation["attestations"][0]["source_handle"] = "UNBOUND_HANDLE"
            _refresh_attestation_fingerprint(attestation)
            _write_json(attestation_path, attestation)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = applier.main(
                    [
                        str(setup_state_path),
                        str(attestation_path),
                        "--launch-pack",
                        str(launch_pack_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_apply_attestation_invalid"],
            payload["error_codes"],
        )
        self.assertIn("source_handle must match a binding token", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
