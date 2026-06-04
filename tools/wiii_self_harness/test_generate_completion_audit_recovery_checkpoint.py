import json
from pathlib import Path
import tempfile
import unittest

from test_generate_completion_audit_recovery_plan import _write_json
from test_validate_completion_audit_recovery_dispatch_run import _write_run
import generate_completion_audit_recovery_checkpoint as generator
import validate_completion_audit_recovery_control_chain as control_chain_validator


def _write_control_chain(
    root: Path,
    *,
    setup_ready: bool,
    dispatch_gate: bool = False,
) -> tuple[Path, tuple[Path, Path, Path, Path, Path, Path, Path, Path, Path, Path | None, dict]]:
    paths = _write_run(root, setup_ready=setup_ready, dispatch_gate=dispatch_gate)
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
    control_chain = control_chain_validator.validate_recovery_control_chain(
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
        repo_root=root,
    )
    control_chain_path = root / "recovery-control-chain.json"
    _write_json(control_chain_path, control_chain.to_dict())
    return control_chain_path, paths


class GenerateCompletionAuditRecoveryCheckpointTests(unittest.TestCase):
    def test_blocked_chain_generates_operator_setup_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control_chain_path, _paths = _write_control_chain(root, setup_ready=False)

            report = generator.generate_completion_audit_recovery_checkpoint(
                control_chain_path,
                repo_root=root,
            )
            payload = report.to_dict()

        self.assertTrue(report.ok, payload)
        self.assertEqual(generator.RECOVERY_CHECKPOINT_SCHEMA_VERSION, payload["schema_version"])
        self.assertEqual("operator_setup_required", payload["chain_state"])
        self.assertEqual("collect_operator_setup", payload["resume_state"])
        self.assertTrue(payload["operator_setup_required"])
        self.assertFalse(payload["recovery_chain_ready"])
        self.assertEqual(["setup-resolution"], payload["next_group_ids"])
        self.assertEqual(
            [
                "setup_attestation",
                "attested_setup_state",
                "attested_dispatch_gate",
                "recovery_control_chain_replay",
            ],
            payload["required_resume_inputs"],
        )
        self.assertFalse(payload["privacy"]["raw_output_included"])
        self.assertFalse(payload["privacy"]["raw_evidence_payload_included"])
        self.assertRegex(payload["recovery_control_chain_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(payload["resume_checkpoint_fingerprint_sha256"], r"^[0-9a-f]{64}$")

    def test_ready_chain_generates_dispatch_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control_chain_path, _paths = _write_control_chain(
                root,
                setup_ready=True,
                dispatch_gate=True,
            )

            payload = generator.generate_completion_audit_recovery_checkpoint(
                control_chain_path,
                repo_root=root,
            ).to_dict()

        self.assertTrue(payload["ok"], payload)
        self.assertEqual("ready_for_recovery_dispatch", payload["chain_state"])
        self.assertEqual("dispatch_recovery", payload["resume_state"])
        self.assertTrue(payload["recovery_chain_ready"])
        self.assertTrue(payload["autonomous_dispatch_allowed"])
        self.assertEqual(["runtime-evidence-dispatch"], payload["authorized_group_ids"])
        self.assertEqual(
            ["operator_dispatch_approval", "live_command_specs", "recovery_dispatch_run"],
            payload["required_resume_inputs"],
        )

    def test_source_drift_makes_checkpoint_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control_chain_path, paths = _write_control_chain(root, setup_ready=False)
            run_path = paths[8]
            run_payload = json.loads(run_path.read_text(encoding="utf-8"))
            run_payload["command_count"] = 1
            _write_json(run_path, run_payload)

            payload = generator.generate_completion_audit_recovery_checkpoint(
                control_chain_path,
                repo_root=root,
            ).to_dict()

        self.assertFalse(payload["ok"])
        self.assertEqual("invalid", payload["resume_state"])
        self.assertIn(
            "completion_audit_recovery_checkpoint_source_invalid",
            payload["error_codes"],
        )

    def test_control_chain_state_drift_makes_checkpoint_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control_chain_path, _paths = _write_control_chain(root, setup_ready=False)
            payload = json.loads(control_chain_path.read_text(encoding="utf-8"))
            payload["chain_state"] = "release_ready"
            _write_json(control_chain_path, payload)

            checkpoint = generator.generate_completion_audit_recovery_checkpoint(
                control_chain_path,
                repo_root=root,
            ).to_dict()

        self.assertFalse(checkpoint["ok"])
        self.assertIn(
            "completion_audit_recovery_checkpoint_source_mismatch",
            checkpoint["error_codes"],
        )

    def test_cli_json_writes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            control_chain_path, _paths = _write_control_chain(root, setup_ready=False)
            out_path = root / "checkpoint.json"

            exit_code = generator.main(
                [
                    str(control_chain_path),
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
        self.assertEqual("collect_operator_setup", payload["resume_state"])


if __name__ == "__main__":
    unittest.main()
