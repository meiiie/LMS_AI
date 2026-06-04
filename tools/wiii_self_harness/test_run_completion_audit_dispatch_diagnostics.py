import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_launch_pack as launch_pack_generator
import generate_completion_audit_run_plan as run_plan_generator
import generate_completion_audit_setup_state as setup_state_generator
from test_generate_completion_audit_run_plan import _sample_readiness_payload
from test_validate_completion_audit_dispatch_run import _write_dispatch_run
from test_validate_runtime_evidence_preflight import (
    _composio_preflight,
    _proactive_preflight,
)
from test_validate_completion_audit_setup_state import _load_json
import run_completion_audit_dispatch_gate as dispatch_runner
import run_completion_audit_dispatch_diagnostics as runner


def _write_source_bound_dispatch_run(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    source_dir = root / "preflight-sources"
    source_dir.mkdir()
    source_payloads = {
        "proactive-channel-preflight.json": _proactive_preflight(),
        "wiii-connect-composio-preflight.json": _composio_preflight(),
    }
    source_hashes: dict[str, str] = {}
    for name, payload in source_payloads.items():
        path = source_dir / name
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        source_hashes[name] = runner._sha256_file(path)

    readiness = _sample_readiness_payload()
    for summary in readiness["preflight_summaries"]:
        summary["source_file_sha256"] = source_hashes[summary["source_file"]]

    readiness_path = root / "readiness.json"
    run_plan_path = root / "run-plan.json"
    launch_pack_path = root / "launch-pack.json"
    setup_state_path = root / "setup-state.json"
    gate_path = root / "dispatch-gate.json"
    run_path = root / "dispatch-run.json"

    _write_json(readiness_path, readiness)
    run_plan = run_plan_generator.generate_completion_audit_run_plan(readiness_path)
    _write_json(run_plan_path, run_plan.to_dict())
    launch_pack = launch_pack_generator.generate_completion_audit_launch_pack(
        run_plan_path,
        readiness_report_path=readiness_path,
    )
    _write_json(launch_pack_path, launch_pack.to_dict())
    setup_state = setup_state_generator.generate_completion_audit_setup_state(
        launch_pack_path
    )
    _write_json(setup_state_path, setup_state.to_dict())
    gate = gate_generator.generate_completion_audit_dispatch_gate(
        launch_pack_path,
        setup_state_path,
    )
    _write_json(gate_path, gate.to_dict())
    dispatch_run = dispatch_runner.run_completion_audit_dispatch_gate(
        gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        repo_root=root,
    )
    _write_json(run_path, dispatch_run.to_dict())
    return launch_pack_path, setup_state_path, gate_path, run_path, source_dir


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_failed_artifact_from_staged_preflight(argv: list[str], cwd: Path) -> Path:
    preflight_path = cwd / argv[argv.index("--failure-preflight-json") + 1]
    output_path = cwd / argv[argv.index("--out") + 1]
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    script = argv[1]
    if "wiii_connect_composio_acceptance.py" in script:
        payload = {
            "status": "fail",
            "setup_contract": preflight["setup_contract"],
            "preflight_summary": preflight,
        }
    else:
        payload = {
            "status": "fail",
            "setup_contract": preflight["setup_contract"],
            "preflight": preflight,
        }
    output_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return output_path


class RunCompletionAuditDispatchDiagnosticsTests(unittest.TestCase):
    def test_pending_dry_run_materializes_unexecuted_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )

            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertFalse(report["dispatch_ready"])
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["allow_diagnostic_execution"])
        self.assertEqual(2, report["diagnostic_command_count"])
        self.assertEqual(0, report["executed_diagnostic_command_count"])
        self.assertEqual(0, report["failed_diagnostic_command_count"])
        self.assertEqual(0, report["preflight_source_dir_count"])
        self.assertEqual(0, report["preflight_stage_count"])
        self.assertEqual(0, report["staged_preflight_count"])
        self.assertEqual([], report["preflight_stages"])
        self.assertEqual([], report["error_codes"])
        self.assertEqual(
            {"local_failure_from_preflight"},
            {command["command_name"] for command in report["commands"]},
        )
        for command in report["commands"]:
            self.assertEqual("maritime-ai-service", command["working_directory"])
            self.assertIn("--failure-from-preflight", command["argv"])
            self.assertIn("--failure-preflight-json", command["argv"])
            self.assertGreaterEqual(command["unresolved_placeholder_count"], 0)
            self.assertFalse(command["execution_ok"])
            self.assertFalse(command["output_artifact_validated"])
            self.assertFalse(command["uses_shell"])
            self.assertFalse(command["executed"])
            self.assertEqual(-1, command["returncode"])

    def test_dry_run_with_preflight_source_dir_records_source_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path, source_dir = (
                _write_source_bound_dispatch_run(root)
            )

            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                preflight_source_dirs=[source_dir],
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual(1, report["preflight_source_dir_count"])
        self.assertEqual(2, report["preflight_stage_count"])
        self.assertEqual(0, report["staged_preflight_count"])
        self.assertEqual(
            {"autonomy-proactive-channel", "wiii-connect-composio-acceptance"},
            {stage["requirement_id"] for stage in report["preflight_stages"]},
        )
        for stage in report["preflight_stages"]:
            self.assertTrue(stage["validation_ok"])
            self.assertEqual([], stage["validation_error_codes"])
            self.assertFalse(stage["staged"])
            self.assertRegex(stage["source_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(stage["target_sha256"], r"^[0-9a-f]{64}$")
        for command in report["commands"]:
            self.assertTrue(command["argv_rebound"])
            self.assertEqual(0, command["unresolved_placeholder_count"])
            self.assertNotIn("<", " ".join(command["argv"]))
            self.assertNotIn(">", " ".join(command["argv"]))

    def test_ready_dispatch_run_is_not_a_diagnostic_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root, ready=True)
            )

            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertTrue(report["dispatch_ready"])
        self.assertEqual(0, report["diagnostic_command_count"])
        self.assertEqual(
            ["completion_audit_dispatch_diagnostics_not_pending"],
            report["error_codes"],
        )

    def test_execute_requires_explicit_diagnostic_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )

            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertEqual(0, report["diagnostic_command_count"])
        self.assertEqual(
            ["completion_audit_dispatch_diagnostics_execution_not_allowed"],
            report["error_codes"],
        )
        self.assertIn("--allow-diagnostic-execution", runner.build_parser().format_help())

    def test_execute_requires_preflight_source_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )

            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
                allow_diagnostic_execution=True,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertEqual(
            ["completion_audit_dispatch_diagnostics_preflight_source_required"],
            report["error_codes"],
        )
        self.assertIn("--preflight-source-dir", runner.build_parser().format_help())

    def test_execute_records_exit_codes_without_raw_output(self) -> None:
        calls: list[tuple[list[str], Path]] = []
        staged_files_seen: list[str] = []

        def fake_runner(
            argv: list[str],
            cwd: Path,
        ) -> subprocess.CompletedProcess[str]:
            calls.append((argv, cwd))
            preflight_path = cwd / argv[argv.index("--failure-preflight-json") + 1]
            if preflight_path.is_file():
                staged_files_seen.append(preflight_path.name)
            _write_failed_artifact_from_staged_preflight(argv, cwd)
            return subprocess.CompletedProcess(
                args=argv,
                returncode=1,
                stdout="diagnostic secret stdout",
                stderr="diagnostic secret stderr",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "maritime-ai-service").mkdir()
            launch_pack_path, setup_state_path, gate_path, run_path, source_dir = (
                _write_source_bound_dispatch_run(root)
            )

            report = runner.run_completion_audit_dispatch_diagnostics(
                run_path,
                dispatch_gate_path=gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
                allow_diagnostic_execution=True,
                preflight_source_dirs=[source_dir],
                command_runner=fake_runner,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual(2, len(calls))
        self.assertEqual(2, report["executed_diagnostic_command_count"])
        self.assertEqual(0, report["failed_diagnostic_command_count"])
        self.assertEqual(2, report["preflight_stage_count"])
        self.assertEqual(2, report["staged_preflight_count"])
        self.assertEqual(
            {
                "autonomy-proactive-channel-preflight.json",
                "wiii-connect-composio-acceptance-preflight.json",
            },
            set(staged_files_seen),
        )
        self.assertFalse(report["privacy"]["raw_output_included"])
        for command in report["commands"]:
            self.assertTrue(command["executed"])
            self.assertEqual(1, command["returncode"])
            self.assertTrue(command["execution_ok"])
            self.assertTrue(command["argv_rebound"])
            self.assertEqual(0, command["unresolved_placeholder_count"])
            self.assertTrue(command["output_artifact_validated"])
            self.assertRegex(command["output_artifact_sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(command["stdout_included"])
            self.assertFalse(command["stderr_included"])
        for stage in report["preflight_stages"]:
            self.assertTrue(stage["staged"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("diagnostic secret stdout", rendered)
        self.assertNotIn("diagnostic secret stderr", rendered)

    def test_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root)
            )
            out_path = root / "dispatch-diagnostics.json"

            exit_code = runner.main(
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
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(runner.DIAGNOSTICS_SCHEMA_VERSION, payload["schema_version"])
        self.assertEqual(2, payload["diagnostic_command_count"])

    def test_cli_reports_not_pending_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, gate_path, run_path = (
                _write_dispatch_run(root, ready=True)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = runner.main(
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
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            ["completion_audit_dispatch_diagnostics_not_pending"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
