import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_dispatch_authorization as generator
import generate_completion_audit_recovery_queue_progress as progress_generator
from test_generate_completion_audit_recovery_plan import _write_json
from test_generate_completion_audit_recovery_queue_progress import (
    _write_progress_sources,
)


def _write_authorization_sources(
    root: Path,
    *,
    setup_ready: bool,
) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
    ) = _write_progress_sources(root, setup_ready=setup_ready)
    progress_path = root / "queue-progress.json"
    progress = progress_generator.generate_completion_audit_recovery_queue_progress(
        queue_path,
        recovery_plan_path=plan_path,
        work_order_status_path=status_path,
        recovery_work_order_path=work_order_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    _write_json(progress_path, progress.to_dict())
    return (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
    )


class GenerateCompletionAuditRecoveryDispatchAuthorizationTests(unittest.TestCase):
    def test_pending_setup_blocks_recovery_dispatch_authorization(self) -> None:
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
            ) = _write_authorization_sources(root, setup_ready=False)

            authorization = (
                generator.generate_completion_audit_recovery_dispatch_authorization(
                    progress_path,
                    recovery_plan_path=plan_path,
                    source_recovery_queue_path=queue_path,
                    work_order_status_path=status_path,
                    recovery_work_order_path=work_order_path,
                    handoff_json_path=handoff_path,
                    setup_state_path=setup_state_path,
                )
            )
            payload = authorization.to_dict()

        self.assertTrue(authorization.ok, payload)
        self.assertEqual("blocked_on_external_setup", payload["queue_state"])
        self.assertEqual("blocked_by_queue", payload["authorization_state"])
        self.assertFalse(payload["autonomous_dispatch_allowed"])
        self.assertEqual(["setup-resolution"], payload["blocked_group_ids"])
        self.assertEqual([], payload["authorized_group_ids"])
        self.assertEqual([], payload["dispatch_items"])

    def test_complete_setup_authorizes_runtime_recovery_item(self) -> None:
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
            ) = _write_authorization_sources(root, setup_ready=True)

            authorization = (
                generator.generate_completion_audit_recovery_dispatch_authorization(
                    progress_path,
                    recovery_plan_path=plan_path,
                    source_recovery_queue_path=queue_path,
                    work_order_status_path=status_path,
                    recovery_work_order_path=work_order_path,
                    handoff_json_path=handoff_path,
                    setup_state_path=setup_state_path,
                )
            )
            payload = authorization.to_dict()

        self.assertTrue(authorization.ok, payload)
        self.assertEqual("ready_for_autonomous_dispatch", payload["queue_state"])
        self.assertEqual("authorized", payload["authorization_state"])
        self.assertTrue(payload["autonomous_dispatch_allowed"])
        self.assertEqual(["runtime-evidence-dispatch"], payload["authorized_group_ids"])
        self.assertEqual([], payload["blocked_group_ids"])
        self.assertEqual(1, payload["authorization_item_count"])
        item = payload["dispatch_items"][0]
        self.assertEqual("runtime:sample-runtime", item["item_id"])
        self.assertEqual(".github/workflows/sample.yml", item["workflow"])
        self.assertEqual("scripts/probe_sample.py", item["probe"])
        self.assertEqual(["WIII_LIVE_SAMPLE"], item["live_env_flags"])
        self.assertEqual(["--allow-sample"], item["live_guard_tokens"])
        self.assertEqual("not_supplied", item["dispatch_gate_status"])
        self.assertTrue(item["authorization_ready"])
        self.assertRegex(payload["authorization_fingerprint_sha256"], r"^[0-9a-f]{64}$")

    def test_invalid_progress_source_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                _handoff_path,
                plan_path,
                _queue_path,
                _work_order_path,
                _setup_state_path,
                _status_path,
                progress_path,
            ) = _write_authorization_sources(root, setup_ready=True)
            progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
            progress_payload["next_group_ids"] = ["setup-resolution"]
            _write_json(progress_path, progress_payload)

            authorization = (
                generator.generate_completion_audit_recovery_dispatch_authorization(
                    progress_path,
                    recovery_plan_path=plan_path,
                )
            )
            payload = authorization.to_dict()

        self.assertFalse(authorization.ok)
        self.assertEqual("invalid", payload["authorization_state"])
        self.assertIn(
            "completion_audit_recovery_dispatch_authorization_progress_invalid",
            payload["error_codes"],
        )

    def test_cli_writes_authorization_json(self) -> None:
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
            ) = _write_authorization_sources(root, setup_ready=True)
            out_path = root / "authorization.json"

            exit_code = generator.main(
                [
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
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            generator.RECOVERY_DISPATCH_AUTHORIZATION_SCHEMA_VERSION,
            payload["schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
