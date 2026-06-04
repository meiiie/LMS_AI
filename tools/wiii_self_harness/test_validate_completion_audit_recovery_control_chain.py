import json
from pathlib import Path
import tempfile
import unittest

from test_generate_completion_audit_recovery_plan import _write_json
from test_validate_completion_audit_recovery_dispatch_run import _write_run
import validate_completion_audit_recovery_control_chain as validator


def _validate(
    paths: tuple[Path, Path, Path, Path, Path, Path, Path, Path, Path, Path | None, dict],
    *,
    repo_root: Path,
) -> validator.RecoveryControlChainValidationResult:
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
    ) = paths
    return validator.validate_recovery_control_chain(
        recovery_plan_path=plan_path,
        recovery_queue_path=queue_path,
        recovery_work_order_path=work_order_path,
        recovery_work_order_status_path=status_path,
        recovery_queue_progress_path=progress_path,
        recovery_dispatch_authorization_path=authorization_path,
        recovery_dispatch_run_path=run_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
        dispatch_gate_path=gate_path,
        repo_root=repo_root,
    )


class ValidateCompletionAuditRecoveryControlChainTests(unittest.TestCase):
    def test_valid_blocked_chain_passes_but_requires_operator_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_run(root, setup_ready=False)

            result = _validate(paths, repo_root=root)
            payload = result.to_dict()

        self.assertTrue(result.ok, payload)
        self.assertEqual("operator_setup_required", payload["chain_state"])
        self.assertFalse(payload["recovery_chain_ready"])
        self.assertFalse(payload["autonomous_dispatch_allowed"])
        self.assertTrue(payload["operator_setup_required"])
        self.assertEqual(["setup-resolution"], payload["next_group_ids"])
        self.assertEqual(["setup-resolution"], payload["blocked_group_ids"])
        self.assertEqual(0, payload["command_count"])
        self.assertRegex(payload["chain_fingerprint_sha256"], r"^[0-9a-f]{64}$")

    def test_valid_ready_chain_passes_and_exposes_recovery_dispatch_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_run(root, setup_ready=True, dispatch_gate=True)

            result = _validate(paths, repo_root=root)
            payload = result.to_dict()

        self.assertTrue(result.ok, payload)
        self.assertEqual("ready_for_recovery_dispatch", payload["chain_state"])
        self.assertTrue(payload["recovery_chain_ready"])
        self.assertTrue(payload["autonomous_dispatch_allowed"])
        self.assertFalse(payload["operator_setup_required"])
        self.assertEqual(["runtime-evidence-dispatch"], payload["authorized_group_ids"])
        self.assertEqual(2, payload["command_count"])

    def test_stale_dispatch_run_authorization_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_run(root, setup_ready=False)
            run_path = paths[8]
            payload = json.loads(run_path.read_text(encoding="utf-8"))
            payload["recovery_dispatch_authorization_sha256"] = "0" * 64
            _write_json(run_path, payload)

            result = _validate(paths, repo_root=root)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_stale_queue_progress_fingerprint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_run(root, setup_ready=False)
            progress_path = paths[6]
            payload = json.loads(progress_path.read_text(encoding="utf-8"))
            payload["queue_progress_fingerprint_sha256"] = "0" * 64
            _write_json(progress_path, payload)

            result = _validate(paths, repo_root=root)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_blocked_chain_cannot_materialize_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_run(root, setup_ready=False)
            run_path = paths[8]
            payload = json.loads(run_path.read_text(encoding="utf-8"))
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
            _write_json(run_path, payload)

            result = _validate(paths, repo_root=root)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_control_chain_child_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_writes_control_chain_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = _write_run(root, setup_ready=False)
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
            ) = paths
            out_path = root / "recovery-control-chain.json"

            exit_code = validator.main(
                [
                    "--recovery-plan",
                    str(plan_path),
                    "--recovery-queue",
                    str(queue_path),
                    "--recovery-work-order",
                    str(work_order_path),
                    "--work-order-status",
                    str(status_path),
                    "--queue-progress",
                    str(progress_path),
                    "--recovery-dispatch-authorization",
                    str(authorization_path),
                    "--recovery-dispatch-run",
                    str(run_path),
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
            validator.RECOVERY_CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual("operator_setup_required", payload["chain_state"])


if __name__ == "__main__":
    unittest.main()
