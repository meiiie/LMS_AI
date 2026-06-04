import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_queue_progress as progress_generator
import generate_completion_audit_recovery_work_order as work_order_generator
import report_completion_audit_recovery_work_order_status as status_reporter
from test_generate_completion_audit_recovery_plan import (
    _sample_handoff_payload,
    _write_json,
)
from test_generate_completion_audit_recovery_work_order import _write_sources
from test_report_completion_audit_recovery_work_order_status import (
    _setup_state_from_work_order,
)


def _write_progress_sources(
    root: Path,
    *,
    setup_ready: bool,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    handoff_path, plan_path, queue_path = _write_sources(
        root,
        _sample_handoff_payload(),
    )
    work_order_path = root / "work-order.json"
    setup_state_path = root / "setup-state.json"
    status_path = root / "work-order-status.json"
    work_order = work_order_generator.generate_completion_audit_recovery_work_order(
        queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
    )
    work_order_payload = work_order.to_dict()
    _write_json(work_order_path, work_order_payload)
    _write_json(
        setup_state_path,
        _setup_state_from_work_order(work_order_payload, ready=setup_ready),
    )
    status = status_reporter.report_completion_audit_recovery_work_order_status(
        work_order_path,
        recovery_queue_path=queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    _write_json(status_path, status.to_dict())
    return handoff_path, plan_path, queue_path, work_order_path, setup_state_path, status_path


class GenerateCompletionAuditRecoveryQueueProgressTests(unittest.TestCase):
    def test_pending_setup_keeps_queue_blocked_on_external_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
            ) = _write_progress_sources(root, setup_ready=False)

            progress = progress_generator.generate_completion_audit_recovery_queue_progress(
                queue_path,
                recovery_plan_path=plan_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )
            payload = progress.to_dict()

        self.assertTrue(progress.ok, payload)
        self.assertEqual("blocked_on_external_setup", payload["queue_state"])
        self.assertFalse(payload["advancement_applied"])
        self.assertEqual([], payload["completed_group_ids"])
        self.assertEqual(["setup-resolution"], payload["next_group_ids"])
        self.assertEqual(
            [
                "blocked_by_external_setup",
                "blocked_by_dependency",
                "blocked_by_dependency",
            ],
            [status["status"] for status in payload["group_statuses"]],
        )

    def test_complete_setup_advances_runtime_dispatch_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
            ) = _write_progress_sources(root, setup_ready=True)

            progress = progress_generator.generate_completion_audit_recovery_queue_progress(
                queue_path,
                recovery_plan_path=plan_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )
            payload = progress.to_dict()

        self.assertTrue(progress.ok, payload)
        self.assertEqual("ready_for_autonomous_dispatch", payload["queue_state"])
        self.assertTrue(payload["advancement_applied"])
        self.assertEqual(["setup-resolution"], payload["completed_group_ids"])
        self.assertEqual(["runtime-evidence-dispatch"], payload["next_group_ids"])
        self.assertEqual(1, payload["complete_group_count"])
        self.assertEqual(1, payload["ready_group_count"])
        self.assertEqual(1, payload["ready_for_autonomous_dispatch_count"])
        self.assertEqual(
            [
                "complete",
                "ready",
                "blocked_by_dependency",
            ],
            [status["status"] for status in payload["group_statuses"]],
        )
        self.assertRegex(payload["queue_progress_fingerprint_sha256"], r"^[0-9a-f]{64}$")

    def test_invalid_status_source_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
            ) = _write_progress_sources(root, setup_ready=True)
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            status_payload["completed_group_ids"] = []
            _write_json(status_path, status_payload)

            progress = progress_generator.generate_completion_audit_recovery_queue_progress(
                queue_path,
                recovery_plan_path=plan_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )
            payload = progress.to_dict()

        self.assertFalse(progress.ok)
        self.assertEqual("invalid", payload["queue_state"])
        self.assertIn(
            "completion_audit_recovery_queue_progress_status_invalid",
            payload["error_codes"],
        )

    def test_cli_writes_queue_progress_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
            ) = _write_progress_sources(root, setup_ready=True)
            out_path = root / "progress.json"

            exit_code = progress_generator.main(
                [
                    str(queue_path),
                    "--recovery-plan",
                    str(plan_path),
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
            progress_generator.QUEUE_PROGRESS_SCHEMA_VERSION,
            payload["schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
