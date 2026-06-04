import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import apply_completion_audit_setup_state as applier
import generate_completion_audit_dispatch_gate as gate_generator
import validate_completion_audit_setup_state as setup_validator
from test_generate_completion_audit_setup_state import _write_launch_pack
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import generate_completion_audit_setup_state as setup_generator


def _write_setup_state(root: Path) -> tuple[Path, Path]:
    launch_pack_path = _write_launch_pack(root)
    setup_state_path = root / "setup-state.json"
    state = setup_generator.generate_completion_audit_setup_state(launch_pack_path)
    _write_json(setup_state_path, state.to_dict())
    return launch_pack_path, setup_state_path


def _ready_patch_from_state(payload: dict, setup_state_path: Path) -> dict:
    checks = []
    for requirement in payload["requirements"]:
        for check in requirement["setup_checks"]:
            checks.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "category": check["category"],
                    "key": check["key"],
                    "source_handle": check["binding_tokens"][0],
                }
            )
    return {
        "schema_version": applier.SETUP_HANDLE_PATCH_SCHEMA_VERSION,
        "ok": True,
        "setup_state_sha256": applier._sha256_file(setup_state_path),
        "setup_state_schema_version": payload["schema_version"],
        "setup_state_fingerprint_sha256": payload[
            "setup_state_fingerprint_sha256"
        ],
        "checks": checks,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
        },
    }


class ApplyCompletionAuditSetupStateTests(unittest.TestCase):
    def test_apply_all_setup_handles_unlocks_dispatch_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            patch_path = root / "setup-handle-patch.json"
            applied_path = root / "setup-state-applied.json"
            patch = _ready_patch_from_state(_load_json(setup_state_path), setup_state_path)
            _write_json(patch_path, patch)

            applied = applier.apply_completion_audit_setup_state(
                setup_state_path,
                patch_path,
                launch_pack_path=launch_pack_path,
            )
            _write_json(applied_path, applied)
            setup_validation = setup_validator.validate_setup_state(
                applied_path,
                launch_pack_path=launch_pack_path,
            )
            gate = gate_generator.generate_completion_audit_dispatch_gate(
                launch_pack_path,
                applied_path,
            ).to_dict()

        self.assertTrue(setup_validation.ok, setup_validation.to_dict())
        self.assertTrue(applied["dispatch_ready"], applied)
        self.assertEqual(applied["requirement_count"], applied["ready_requirement_count"])
        self.assertEqual(0, applied["blocked_requirement_count"])
        self.assertTrue(gate["dispatch_ready"], gate)
        self.assertEqual(2, gate["ready_dispatch_item_count"])
        specs = gate["dispatch_items"][0]["unlocked_live_command_specs"]
        self.assertEqual({"workflow_dispatch", "local_live_probe"}, set(specs))
        rendered = json.dumps(applied, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_apply_partial_setup_handles_keeps_dispatch_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            patch = _ready_patch_from_state(_load_json(setup_state_path), setup_state_path)
            patch["checks"] = patch["checks"][:1]
            patch_path = root / "setup-handle-patch.json"
            _write_json(patch_path, patch)

            applied = applier.apply_completion_audit_setup_state(
                setup_state_path,
                patch_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(applied["dispatch_ready"])
        self.assertGreater(applied["blocked_requirement_count"], 0)
        self.assertEqual(0, applied["ready_requirement_count"])

    def test_cli_writes_applied_setup_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            patch_path = root / "setup-handle-patch.json"
            out_path = root / "setup-state-applied.json"
            _write_json(
                patch_path,
                _ready_patch_from_state(_load_json(setup_state_path), setup_state_path),
            )

            exit_code = applier.main(
                [
                    str(setup_state_path),
                    str(patch_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(setup_generator.SETUP_STATE_SCHEMA_VERSION, payload["schema_version"])
        self.assertTrue(payload["dispatch_ready"])

    def test_cli_rejects_raw_source_handle_in_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            patch = _ready_patch_from_state(_load_json(setup_state_path), setup_state_path)
            patch["checks"][0]["source_handle"] = "<raw-recipient-id>"
            patch_path = root / "setup-handle-patch.json"
            _write_json(patch_path, patch)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = applier.main([str(setup_state_path), str(patch_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_state_apply_patch_invalid"],
            payload["error_codes"],
        )

    def test_cli_rejects_patch_bound_to_stale_setup_state_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            patch = _ready_patch_from_state(
                _load_json(setup_state_path),
                setup_state_path,
            )
            patch["setup_state_sha256"] = "0" * 64
            patch_path = root / "setup-handle-patch.json"
            _write_json(patch_path, patch)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = applier.main([str(setup_state_path), str(patch_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_state_apply_patch_source_mismatch"],
            payload["error_codes"],
        )

    def test_cli_rejects_unbound_source_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            patch = _ready_patch_from_state(_load_json(setup_state_path), setup_state_path)
            patch["checks"][0]["source_handle"] = "UNBOUND_HANDLE"
            patch_path = root / "setup-handle-patch.json"
            _write_json(patch_path, patch)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = applier.main([str(setup_state_path), str(patch_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_state_apply_unbound_handle"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
