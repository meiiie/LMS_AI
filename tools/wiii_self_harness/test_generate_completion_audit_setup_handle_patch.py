import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import apply_completion_audit_setup_state as applier
import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_setup_handle_patch as generator
from test_apply_completion_audit_setup_state import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_handle_patch as patch_validator


def _handle_specs_from_state(payload: dict) -> list[str]:
    specs: list[str] = []
    for requirement in payload["requirements"]:
        for check in requirement["setup_checks"]:
            specs.append(
                (
                    f"{requirement['requirement_id']}:{check['category']}:"
                    f"{check['key']}={check['binding_tokens'][0]}"
                )
            )
    return specs


class GenerateCompletionAuditSetupHandlePatchTests(unittest.TestCase):
    def test_generate_source_bound_patch_validates_against_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)

            patch = generator.generate_completion_audit_setup_handle_patch(
                setup_state_path,
                _handle_specs_from_state(setup_payload)[:1],
                launch_pack_path=launch_pack_path,
            )
            expected_setup_state_sha256 = applier._sha256_file(setup_state_path)
            patch_path = root / "setup-handle-patch.json"
            _write_json(patch_path, patch)
            validation = patch_validator.validate_setup_handle_patch(
                patch_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertTrue(validation.ok, validation.to_dict())
        self.assertEqual(
            applier.SETUP_HANDLE_PATCH_SCHEMA_VERSION,
            patch["schema_version"],
        )
        self.assertEqual(
            expected_setup_state_sha256,
            patch["setup_state_sha256"],
        )
        self.assertEqual(1, len(patch["checks"]))
        rendered = json.dumps(patch, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_generated_all_handles_patch_can_unlock_dispatch_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            patch_path = root / "setup-handle-patch.json"
            applied_path = root / "setup-state-applied.json"
            patch = generator.generate_completion_audit_setup_handle_patch(
                setup_state_path,
                _handle_specs_from_state(setup_payload),
                launch_pack_path=launch_pack_path,
            )
            _write_json(patch_path, patch)

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

        self.assertTrue(applied["dispatch_ready"], applied)
        self.assertTrue(gate["dispatch_ready"], gate)
        self.assertEqual(2, gate["ready_dispatch_item_count"])

    def test_cli_writes_setup_handle_patch_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            patch_path = root / "setup-handle-patch.json"

            exit_code = generator.main(
                [
                    str(setup_state_path),
                    "--handle",
                    _handle_specs_from_state(setup_payload)[0],
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(patch_path),
                ]
            )
            payload = _load_json(patch_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(
            applier.SETUP_HANDLE_PATCH_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual(1, len(payload["checks"]))

    def test_cli_rejects_malformed_handle_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [str(setup_state_path), "--handle", "not-a-valid-spec"]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_patch_handle_spec_invalid"],
            payload["error_codes"],
        )

    def test_cli_rejects_unbound_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            setup_payload = _load_json(setup_state_path)
            spec = _handle_specs_from_state(setup_payload)[0]
            left, _source = spec.split("=", 1)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [str(setup_state_path), "--handle", f"{left}=UNBOUND_HANDLE"]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_patch_unbound_handle"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
