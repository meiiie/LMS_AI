import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import generate_completion_audit_dispatch_gate as gate_generator
import generate_completion_audit_recovery_dispatch_authorization as auth_generator
from test_generate_completion_audit_recovery_dispatch_authorization import (
    _write_authorization_sources,
)
from test_generate_completion_audit_recovery_plan import _write_json
import run_completion_audit_recovery_dispatch_authorization as runner


def _write_authorization(
    root: Path,
    *,
    setup_ready: bool,
    dispatch_gate: bool = False,
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path, Path | None]:
    (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
    ) = _write_authorization_sources(root, setup_ready=setup_ready)
    gate_path = _write_sample_dispatch_gate(root) if dispatch_gate else None
    authorization_path = root / "authorization.json"
    authorization = auth_generator.generate_completion_audit_recovery_dispatch_authorization(
        progress_path,
        recovery_plan_path=plan_path,
        dispatch_gate_path=gate_path,
        source_recovery_queue_path=queue_path,
        work_order_status_path=status_path,
        recovery_work_order_path=work_order_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    _write_json(authorization_path, authorization.to_dict())
    return (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
        authorization_path,
        gate_path,
    )


def _write_sample_dispatch_gate(root: Path) -> Path:
    gate_path = root / "dispatch-gate.json"
    dispatch_items = [
        {
            "requirement_id": "sample-runtime",
            "title": "Sample runtime recovery",
            "workflow": ".github/workflows/sample.yml",
            "probe": "scripts/probe_sample.py",
            "expected_artifact": "sample-runtime.json",
            "setup_status": "ready",
            "dispatch_ready": True,
            "ready_setup_handle_count": 1,
            "ready_setup_handles": [
                {
                    "category": "environment_flags_required",
                    "key": "live_sample_flag",
                    "binding_tokens": ["WIII_LIVE_SAMPLE"],
                    "source_handle": "WIII_LIVE_SAMPLE",
                }
            ],
            "blocked_setup_check_count": 0,
            "blocked_setup_checks": [],
            "unlocked_live_command_specs": {
                "workflow_dispatch": {
                    "working_directory": ".",
                    "argv": [
                        "gh",
                        "workflow",
                        "run",
                        "sample.yml",
                        "-f",
                        "run_sample=true",
                    ],
                    "uses_shell": False,
                },
                "local_live_probe": {
                    "working_directory": ".",
                    "argv": [
                        "python",
                        "scripts/probe_sample.py",
                        "--allow-sample",
                        "--out",
                        "sample-runtime.json",
                    ],
                    "uses_shell": False,
                },
            },
            "blocked_diagnostic_command_specs": {},
        }
    ]
    payload = {
        "schema_version": gate_generator.DISPATCH_GATE_SCHEMA_VERSION,
        "ok": True,
        "launch_pack_path": "launch-pack.json",
        "launch_pack_sha256": "a" * 64,
        "launch_pack_schema_version": "wiii.completion_audit_launch_pack.v1",
        "launch_items_fingerprint_sha256": "b" * 64,
        "launch_setup_fingerprint_sha256": "c" * 64,
        "setup_state_path": "setup-state.json",
        "setup_state_sha256": "d" * 64,
        "setup_state_schema_version": "wiii.completion_audit_setup_state.v1",
        "setup_state_fingerprint_sha256": "e" * 64,
        "dispatch_gate_fingerprint_sha256": gate_generator._dispatch_gate_fingerprint(
            dispatch_items
        ),
        "dispatch_ready": True,
        "dispatch_item_count": 1,
        "ready_dispatch_item_count": 1,
        "blocked_dispatch_item_count": 0,
        "dispatch_items": dispatch_items,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        "errors": [],
        "error_codes": [],
        "error_code_counts": {},
    }
    _write_json(gate_path, payload)
    return gate_path


class RunCompletionAuditRecoveryDispatchAuthorizationTests(unittest.TestCase):
    def test_blocked_authorization_reports_without_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                authorization_path,
                _gate_path,
            ) = _write_authorization(root, setup_ready=False)

            report = runner.run_completion_audit_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertEqual("blocked_by_authorization", report["run_state"])
        self.assertEqual(0, report["command_count"])
        self.assertEqual(["setup-resolution"], report["blocked_group_ids"])
        self.assertEqual(
            ["completion_audit_recovery_dispatch_run_authorization_not_ready"],
            report["error_codes"],
        )

    def test_authorized_without_gate_blocks_command_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                authorization_path,
                _gate_path,
            ) = _write_authorization(root, setup_ready=True)

            report = runner.run_completion_audit_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertEqual("blocked_by_missing_live_command_specs", report["run_state"])
        self.assertTrue(report["autonomous_dispatch_allowed"])
        self.assertFalse(report["live_command_specs_included"])
        self.assertEqual(0, report["command_count"])
        self.assertEqual(
            ["completion_audit_recovery_dispatch_run_missing_live_command_specs"],
            report["error_codes"],
        )

    def test_authorized_gate_dry_run_materializes_unexecuted_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                authorization_path,
                gate_path,
            ) = _write_authorization(root, setup_ready=True, dispatch_gate=True)

            report = runner.run_completion_audit_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                dispatch_gate_path=gate_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual("ready", report["run_state"])
        self.assertEqual(2, report["command_count"])
        self.assertEqual(0, report["executed_command_count"])
        self.assertEqual({"workflow_dispatch", "local_live_probe"}, {command["command_name"] for command in report["commands"]})
        for command in report["commands"]:
            self.assertFalse(command["uses_shell"])
            self.assertFalse(command["executed"])
            self.assertEqual(-1, command["returncode"])
            self.assertFalse(command["stdout_included"])
            self.assertFalse(command["stderr_included"])

    def test_execute_requires_explicit_live_dispatch_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            *source_paths, authorization_path, gate_path = _write_authorization(
                root,
                setup_ready=True,
                dispatch_gate=True,
            )
            handoff_path, plan_path, queue_path, work_order_path, setup_state_path, status_path, progress_path = source_paths

            report = runner.run_completion_audit_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                dispatch_gate_path=gate_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
            ).to_dict()

        self.assertFalse(report["ok"], report)
        self.assertEqual("live_dispatch_not_allowed", report["run_state"])
        self.assertEqual(0, report["command_count"])
        self.assertEqual(
            ["completion_audit_recovery_dispatch_run_live_dispatch_not_allowed"],
            report["error_codes"],
        )
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
            *source_paths, authorization_path, gate_path = _write_authorization(
                root,
                setup_ready=True,
                dispatch_gate=True,
            )
            handoff_path, plan_path, queue_path, work_order_path, setup_state_path, status_path, progress_path = source_paths

            report = runner.run_completion_audit_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                dispatch_gate_path=gate_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
                execute=True,
                allow_live_dispatch=True,
                command_runner=fake_runner,
            ).to_dict()

        self.assertTrue(report["ok"], report)
        self.assertEqual("executed", report["run_state"])
        self.assertEqual(2, len(calls))
        self.assertEqual(2, report["executed_command_count"])
        self.assertFalse(report["privacy"]["raw_output_included"])
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("secret-ish stdout", rendered)
        self.assertNotIn("secret-ish stderr", rendered)

    def test_cli_allow_blocked_report_writes_json_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                authorization_path,
                _gate_path,
            ) = _write_authorization(root, setup_ready=False)
            out_path = root / "recovery-dispatch-run.json"

            exit_code = runner.main(
                [
                    str(authorization_path),
                    "--queue-progress",
                    str(progress_path),
                    "--recovery-plan",
                    str(plan_path),
                    "--source-recovery-queue",
                    str(queue_path),
                    "--work-order-status",
                    str(status_path),
                    "--recovery-work-order",
                    str(work_order_path),
                    "--handoff-json",
                    str(handoff_path),
                    "--setup-state",
                    str(setup_state_path),
                    "--repo-root",
                    str(root),
                    "--allow-blocked-report",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertFalse(payload["ok"])
        self.assertEqual("blocked_by_authorization", payload["run_state"])
        self.assertEqual(
            runner.RECOVERY_DISPATCH_RUN_SCHEMA_VERSION,
            payload["schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
