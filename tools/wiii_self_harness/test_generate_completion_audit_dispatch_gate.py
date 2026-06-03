import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_setup_state as setup_generator
from test_generate_completion_audit_setup_state import _write_launch_pack
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json, _mark_ready


def _write_setup_state(root: Path, *, ready: bool = False) -> tuple[Path, Path]:
    launch_pack_path = _write_launch_pack(root)
    setup_state_path = root / "setup-state.json"
    state = setup_generator.generate_completion_audit_setup_state(launch_pack_path)
    payload = state.to_dict()
    if ready:
        _mark_ready(payload)
    _write_json(setup_state_path, payload)
    return launch_pack_path, setup_state_path


class GenerateCompletionAuditDispatchGateTests(unittest.TestCase):
    def test_generate_pending_dispatch_gate_locks_live_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))

            gate = gate_generator.generate_completion_audit_dispatch_gate(
                launch_pack_path,
                setup_state_path,
            )
            payload = gate.to_dict()

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            gate_generator.DISPATCH_GATE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertFalse(payload["dispatch_ready"])
        self.assertEqual(2, payload["dispatch_item_count"])
        self.assertEqual(0, payload["ready_dispatch_item_count"])
        self.assertEqual(2, payload["blocked_dispatch_item_count"])
        self.assertRegex(
            payload["dispatch_gate_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertFalse(payload["privacy"]["secret_values_included"])
        proactive = payload["dispatch_items"][0]
        self.assertEqual("autonomy-proactive-channel", proactive["requirement_id"])
        self.assertEqual("pending", proactive["setup_status"])
        self.assertFalse(proactive["dispatch_ready"])
        self.assertGreater(proactive["blocked_setup_check_count"], 0)
        self.assertEqual({}, proactive["unlocked_live_command_specs"])
        diagnostic_specs = proactive["blocked_diagnostic_command_specs"]
        self.assertEqual({"local_failure_from_preflight"}, set(diagnostic_specs))
        self.assertFalse(diagnostic_specs["local_failure_from_preflight"]["uses_shell"])
        self.assertIn(
            "--failure-preflight-json",
            diagnostic_specs["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "autonomy-proactive-channel-evidence.json",
            diagnostic_specs["local_failure_from_preflight"]["argv"],
        )
        rendered = json.dumps(payload, sort_keys=True)
        self.assertIn("selected_channel_credential", rendered)
        self.assertNotIn("secret-access-token", rendered)

    def test_generate_ready_dispatch_gate_unlocks_live_command_specs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root, ready=True)

            gate = gate_generator.generate_completion_audit_dispatch_gate(
                launch_pack_path,
                setup_state_path,
            )
            payload = gate.to_dict()

        self.assertTrue(payload["dispatch_ready"], payload)
        self.assertEqual(2, payload["ready_dispatch_item_count"])
        proactive = payload["dispatch_items"][0]
        self.assertEqual("ready", proactive["setup_status"])
        self.assertTrue(proactive["dispatch_ready"])
        self.assertEqual(0, proactive["blocked_setup_check_count"])
        self.assertGreater(proactive["ready_setup_handle_count"], 0)
        specs = proactive["unlocked_live_command_specs"]
        self.assertEqual({"workflow_dispatch", "local_live_probe"}, set(specs))
        self.assertEqual({}, proactive["blocked_diagnostic_command_specs"])
        self.assertFalse(specs["workflow_dispatch"]["uses_shell"])
        self.assertIn("gh", specs["workflow_dispatch"]["argv"])
        self.assertIn("--allow-send", specs["local_live_probe"]["argv"])
        self.assertFalse(payload["privacy"]["raw_identifiers_included"])

    def test_cli_writes_dispatch_gate_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            out_path = root / "dispatch-gate.json"

            exit_code = gate_generator.main(
                [
                    str(launch_pack_path),
                    str(setup_state_path),
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(
            gate_generator.DISPATCH_GATE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertFalse(payload["dispatch_ready"])

    def test_cli_reports_invalid_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            payload = _load_json(setup_state_path)
            payload["privacy"]["raw_identifiers_included"] = True
            _write_json(setup_state_path, payload)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = gate_generator.main(
                    [str(launch_pack_path), str(setup_state_path)]
                )
            output = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(output["ok"])
        self.assertEqual(
            ["completion_audit_dispatch_gate_setup_state_invalid"],
            output["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
