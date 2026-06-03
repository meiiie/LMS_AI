import json
from pathlib import Path
import tempfile
import unittest

from test_generate_completion_audit_recovery_plan import _write_json
from test_run_completion_audit_recovery_dispatch_authorization import (
    _write_authorization,
)
import run_completion_audit_recovery_dispatch_authorization as runner
import validate_completion_audit_recovery_dispatch_run as validator


def _write_run(
    root: Path,
    *,
    setup_ready: bool,
    dispatch_gate: bool = False,
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path, Path, Path | None, dict]:
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
    ) = _write_authorization(
        root,
        setup_ready=setup_ready,
        dispatch_gate=dispatch_gate,
    )
    run_path = root / "recovery-dispatch-run.json"
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
    )
    payload = report.to_dict()
    _write_json(run_path, payload)
    return (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
        authorization_path,
        run_path,
        gate_path,
        payload,
    )


def _refresh_run_fingerprint(payload: dict) -> None:
    payload["recovery_dispatch_run_fingerprint_sha256"] = (
        runner._recovery_dispatch_run_fingerprint(
            mode=payload["mode"],
            allow_live_dispatch=payload["allow_live_dispatch"],
            run_state=payload["run_state"],
            commands=payload["commands"],
            denied_items=payload["denied_items"],
            errors=payload["errors"],
        )
    )


class ValidateCompletionAuditRecoveryDispatchRunTests(unittest.TestCase):
    def test_valid_blocked_run_passes_with_sources(self) -> None:
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
                run_path,
                _gate_path,
                _payload,
            ) = _write_run(root, setup_ready=False)

            result = validator.validate_recovery_dispatch_run(
                run_path,
                recovery_dispatch_authorization_path=authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_valid_ready_run_passes_with_sources(self) -> None:
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
                run_path,
                gate_path,
                _payload,
            ) = _write_run(root, setup_ready=True, dispatch_gate=True)

            result = validator.validate_recovery_dispatch_run(
                run_path,
                recovery_dispatch_authorization_path=authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                dispatch_gate_path=gate_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_source_parity_rejects_stale_run_report(self) -> None:
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
                run_path,
                gate_path,
                payload,
            ) = _write_run(root, setup_ready=True, dispatch_gate=True)
            payload["command_count"] = 0
            _write_json(run_path, payload)

            result = validator.validate_recovery_dispatch_run(
                run_path,
                recovery_dispatch_authorization_path=authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                dispatch_gate_path=gate_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_run_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_fingerprint_must_match_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            *_paths, run_path, _gate_path, payload = _write_run(
                root,
                setup_ready=True,
                dispatch_gate=True,
            )
            payload["commands"][0]["argv"] = ["gh", "workflow", "run", "changed.yml"]
            _write_json(run_path, payload)

            result = validator.validate_recovery_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_run_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_blocked_run_must_not_materialize_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            *_paths, run_path, _gate_path, payload = _write_run(root, setup_ready=False)
            payload["commands"] = [
                {
                    "item_id": "runtime:sample-runtime",
                    "group_id": "runtime-evidence-dispatch",
                    "requirement_id": "sample-runtime",
                    "command_name": "workflow_dispatch",
                    "working_directory": ".",
                    "argv": ["gh", "workflow", "run", "sample.yml"],
                    "uses_shell": False,
                    "executed": False,
                    "returncode": -1,
                    "stdout_included": False,
                    "stderr_included": False,
                }
            ]
            payload["command_count"] = 1
            _refresh_run_fingerprint(payload)
            _write_json(run_path, payload)

            result = validator.validate_recovery_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_run_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_command_schema_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            *_paths, run_path, _gate_path, payload = _write_run(
                root,
                setup_ready=True,
                dispatch_gate=True,
            )
            payload["commands"][0]["operator_note"] = "not allowed"
            _refresh_run_fingerprint(payload)
            _write_json(run_path, payload)

            result = validator.validate_recovery_dispatch_run(run_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_run_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
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
                run_path,
                _gate_path,
                _payload,
            ) = _write_run(root, setup_ready=False)
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
                    str(run_path),
                    "--recovery-dispatch-authorization",
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
                    "--json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.RECOVERY_DISPATCH_RUN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
