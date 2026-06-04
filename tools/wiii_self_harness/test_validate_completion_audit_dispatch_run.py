import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_generate_completion_audit_run_plan import _write_json
from test_run_completion_audit_dispatch_gate import _write_dispatch_gate
from test_validate_completion_audit_setup_state import _load_json
import run_completion_audit_dispatch_gate as runner
import validate_completion_audit_dispatch_run as validator


def _write_dispatch_run(
    root: Path,
    *,
    ready: bool = False,
) -> tuple[Path, Path, Path, Path]:
    launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
        root,
        ready=ready,
    )
    run_path = root / "dispatch-run.json"
    report = runner.run_completion_audit_dispatch_gate(
        gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=root,
    )
    _write_json(run_path, report.to_dict())
    return launch_pack_path, setup_state_path, gate_path, run_path


def _refresh_dispatch_run_fingerprint(payload: dict) -> None:
    payload["dispatch_run_fingerprint_sha256"] = runner._dispatch_run_fingerprint(
        payload["commands"],
        payload["errors"],
        payload["diagnostic_commands"],
    )


class ValidateCompletionAuditDispatchRunTests(unittest.TestCase):
    def test_valid_pending_dispatch_run_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )

            result = validator.validate_dispatch_run(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_valid_ready_dry_run_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root, ready=True)
            )

            result = validator.validate_dispatch_run(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_source_parity_rejects_stale_dispatch_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )
            payload = _load_json(run_path)
            payload["dispatch_gate_sha256"] = "0" * 64
            _write_json(run_path, payload)

            result = validator.validate_dispatch_run(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_run_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_pending_dispatch_run_must_not_materialize_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _gate_path, run_path = (
                _write_dispatch_run(root)
            )
            payload = _load_json(run_path)
            payload["commands"] = [
                {
                    "requirement_id": "autonomy-proactive-channel",
                    "command_name": "workflow_dispatch",
                    "working_directory": ".",
                    "argv": ["gh", "workflow", "run", "x.yml"],
                    "uses_shell": False,
                    "executed": False,
                    "returncode": -1,
                    "stdout_included": False,
                    "stderr_included": False,
                }
            ]
            payload["command_count"] = 1
            _refresh_dispatch_run_fingerprint(payload)
            _write_json(run_path, payload)

            result = validator.validate_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_run_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_pending_diagnostic_commands_must_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _gate_path, run_path = (
                _write_dispatch_run(root)
            )
            payload = _load_json(run_path)
            payload["diagnostic_commands"][0]["executed"] = True
            payload["diagnostic_commands"][0]["returncode"] = 0
            _refresh_dispatch_run_fingerprint(payload)
            _write_json(run_path, payload)

            result = validator.validate_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_run_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_ready_dispatch_run_must_not_carry_diagnostic_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _gate_path, run_path = (
                _write_dispatch_run(root, ready=True)
            )
            payload = _load_json(run_path)
            payload["diagnostic_commands"] = [
                {
                    "requirement_id": "autonomy-proactive-channel",
                    "command_name": "local_failure_from_preflight",
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
                    "executed": False,
                    "returncode": -1,
                    "stdout_included": False,
                    "stderr_included": False,
                }
            ]
            payload["diagnostic_command_count"] = 1
            _refresh_dispatch_run_fingerprint(payload)
            _write_json(run_path, payload)

            result = validator.validate_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_run_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_raw_output_flags_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _gate_path, run_path = (
                _write_dispatch_run(root, ready=True)
            )
            payload = _load_json(run_path)
            payload["commands"][0]["stdout_included"] = True
            payload["privacy"]["raw_output_included"] = True
            _refresh_dispatch_run_fingerprint(payload)
            _write_json(run_path, payload)

            result = validator.validate_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_dispatch_run_privacy_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(run_path),
                        "--dispatch-gate",
                        str(gate_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--repo-root",
                        str(root),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.DISPATCH_RUN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(run_path), payload["dispatch_run_path"])


if __name__ == "__main__":
    unittest.main()
