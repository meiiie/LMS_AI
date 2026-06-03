import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import generate_completion_audit_dispatch_gate as gate_generator
from test_generate_completion_audit_dispatch_gate import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import run_completion_audit_dispatch_gate as runner


def _write_dispatch_gate(root: Path, *, ready: bool = False) -> tuple[Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root, ready=ready)
    gate_path = root / "dispatch-gate.json"
    gate = gate_generator.generate_completion_audit_dispatch_gate(
        launch_pack_path,
        setup_state_path,
    )
    _write_json(gate_path, gate.to_dict())
    return launch_pack_path, setup_state_path, gate_path


class RunCompletionAuditDispatchGateTests(unittest.TestCase):
    def test_pending_gate_reports_not_ready_without_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(root)

            report = runner.run_completion_audit_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertFalse(report["dispatch_ready"])
        self.assertEqual(0, report["command_count"])
        self.assertEqual(2, report["diagnostic_command_count"])
        self.assertEqual([], report["commands"])
        self.assertEqual(
            {"local_failure_from_preflight"},
            {command["command_name"] for command in report["diagnostic_commands"]},
        )
        for command in report["diagnostic_commands"]:
            self.assertEqual("maritime-ai-service", command["working_directory"])
            self.assertIn("--failure-from-preflight", command["argv"])
            self.assertIn("--failure-preflight-json", command["argv"])
            self.assertFalse(command["uses_shell"])
            self.assertFalse(command["executed"])
            self.assertEqual(-1, command["returncode"])
        self.assertEqual(
            ["completion_audit_dispatch_run_gate_not_ready"],
            report["error_codes"],
        )

    def test_ready_gate_dry_run_materializes_unexecuted_allowlisted_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                root,
                ready=True,
            )

            report = runner.run_completion_audit_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertTrue(report["dispatch_ready"])
        self.assertTrue(report["dry_run"])
        self.assertEqual(4, report["command_count"])
        self.assertEqual(0, report["executed_command_count"])
        self.assertEqual(0, report["failed_command_count"])
        self.assertEqual(0, report["diagnostic_command_count"])
        self.assertEqual([], report["diagnostic_commands"])
        self.assertEqual([], report["error_codes"])
        self.assertEqual(
            {"workflow_dispatch", "local_live_probe"},
            {command["command_name"] for command in report["commands"]},
        )
        for command in report["commands"]:
            self.assertFalse(command["uses_shell"])
            self.assertFalse(command["executed"])
            self.assertEqual(-1, command["returncode"])
            self.assertFalse(command["stdout_included"])
            self.assertFalse(command["stderr_included"])

    def test_execute_requires_explicit_live_dispatch_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                root,
                ready=True,
            )

            report = runner.run_completion_audit_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertEqual(
            ["completion_audit_dispatch_run_live_dispatch_not_allowed"],
            report["error_codes"],
        )
        self.assertEqual(0, report["command_count"])
        self.assertIn("--allow-live-dispatch", runner.build_parser().format_help())

    def test_execute_records_exit_codes_without_raw_output(self) -> None:
        calls: list[tuple[list[str], Path]] = []

        def fake_runner(
            argv: list[str],
            cwd: Path,
        ) -> subprocess.CompletedProcess[str]:
            calls.append((argv, cwd))
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="secret-ish stdout",
                stderr="secret-ish stderr",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(
                root,
                ready=True,
            )

            report = runner.run_completion_audit_dispatch_gate(
                gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
                allow_live_dispatch=True,
                command_runner=fake_runner,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual(4, len(calls))
        self.assertEqual(4, report["executed_command_count"])
        self.assertEqual(0, report["failed_command_count"])
        self.assertFalse(report["privacy"]["raw_output_included"])
        for command in report["commands"]:
            self.assertTrue(command["executed"])
            self.assertEqual(0, command["returncode"])
            self.assertFalse(command["stdout_included"])
            self.assertFalse(command["stderr_included"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("secret-ish stdout", rendered)
        self.assertNotIn("secret-ish stderr", rendered)

    def test_cli_allow_pending_report_writes_json_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(root)
            out_path = root / "dispatch-run.json"

            exit_code = runner.main(
                [
                    str(gate_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--setup-state",
                    str(setup_state_path),
                    "--repo-root",
                    str(root),
                    "--allow-pending-report",
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(0, payload["command_count"])
        self.assertEqual(2, payload["diagnostic_command_count"])
        self.assertEqual(
            runner.DISPATCH_RUN_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual(
            ["completion_audit_dispatch_run_gate_not_ready"],
            payload["error_codes"],
        )

    def test_cli_pending_report_exits_nonzero_without_allow_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path = _write_dispatch_gate(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = runner.main(
                    [
                        str(gate_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--repo-root",
                        str(root),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(0, payload["command_count"])
        self.assertEqual(2, payload["diagnostic_command_count"])


if __name__ == "__main__":
    unittest.main()
