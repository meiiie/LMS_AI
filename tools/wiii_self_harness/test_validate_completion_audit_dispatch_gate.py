import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_dispatch_gate as gate_generator
from test_generate_completion_audit_dispatch_gate import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_dispatch_gate as validator


def _write_dispatch_gate(root: Path, *, ready: bool = False) -> tuple[Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root, ready=ready)
    gate_path = root / "dispatch-gate.json"
    gate = gate_generator.generate_completion_audit_dispatch_gate(
        launch_pack_path,
        setup_state_path,
    )
    _write_json(gate_path, gate.to_dict())
    return launch_pack_path, setup_state_path, gate_path


def _write_gate(path: Path, payload: dict) -> None:
    payload["dispatch_gate_fingerprint_sha256"] = (
        gate_generator._dispatch_gate_fingerprint(payload["dispatch_items"])
    )
    _write_json(path, payload)


class ValidateCompletionAuditDispatchGateTests(unittest.TestCase):
    def test_valid_pending_dispatch_gate_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir)
            )

            result = validator.validate_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_valid_ready_dispatch_gate_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir),
                ready=True,
            )

            result = validator.validate_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_pending_dispatch_gate_must_not_unlock_live_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, _setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir)
            )
            payload = _load_json(gate_path)
            payload["dispatch_items"][0]["unlocked_live_command_specs"] = {
                "workflow_dispatch": {
                    "working_directory": ".",
                    "argv": ["gh", "workflow", "run", "x.yml"],
                    "uses_shell": False,
                },
                "local_live_probe": {
                    "working_directory": "maritime-ai-service",
                    "argv": ["python", "probe.py", "--allow-run"],
                    "uses_shell": False,
                },
            }
            _write_gate(gate_path, payload)

            result = validator.validate_dispatch_gate(gate_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_pending_dispatch_gate_requires_diagnostic_failure_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, _setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir)
            )
            payload = _load_json(gate_path)
            payload["dispatch_items"][0]["blocked_diagnostic_command_specs"] = {}
            _write_gate(gate_path, payload)

            result = validator.validate_dispatch_gate(gate_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_ready_dispatch_gate_must_not_keep_blocked_diagnostic_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, _setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir),
                ready=True,
            )
            payload = _load_json(gate_path)
            payload["dispatch_items"][0]["blocked_diagnostic_command_specs"] = {
                "local_failure_from_preflight": {
                    "working_directory": "maritime-ai-service",
                    "argv": [
                        "python",
                        "scripts/probe_live_proactive_channel.py",
                        "--failure-from-preflight",
                        "--failure-preflight-json",
                        "autonomy-proactive-channel-preflight.json",
                        "--out",
                        "autonomy-proactive-channel-evidence.json",
                    ],
                    "uses_shell": False,
                }
            }
            _write_gate(gate_path, payload)

            result = validator.validate_dispatch_gate(gate_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_ready_dispatch_gate_requires_live_command_specs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, _setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir),
                ready=True,
            )
            payload = _load_json(gate_path)
            payload["dispatch_items"][0]["unlocked_live_command_specs"].pop(
                "local_live_probe"
            )
            _write_gate(gate_path, payload)

            result = validator.validate_dispatch_gate(gate_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_ready_setup_handle_must_be_safe_binding_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, _setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir),
                ready=True,
            )
            payload = _load_json(gate_path)
            payload["dispatch_items"][0]["ready_setup_handles"][0][
                "source_handle"
            ] = "<raw-recipient-id>"
            _write_gate(gate_path, payload)

            result = validator.validate_dispatch_gate(gate_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_setup_check_invalid",
            result.to_dict()["error_codes"],
        )

    def test_setup_state_hash_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir)
            )
            payload = _load_json(gate_path)
            payload["setup_state_sha256"] = "0" * 64
            _write_json(gate_path, payload)

            result = validator.validate_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_source_parity_rejects_changed_unlocked_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                Path(temp_dir),
                ready=True,
            )
            payload = _load_json(gate_path)
            payload["dispatch_items"][0]["unlocked_live_command_specs"][
                "local_live_probe"
            ]["argv"].append("--extra")
            _write_gate(gate_path, payload)

            result = validator.validate_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_gate_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(gate_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.DISPATCH_GATE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(setup_state_path), payload["setup_state_path"])


if __name__ == "__main__":
    unittest.main()
