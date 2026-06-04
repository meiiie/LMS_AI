import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_plan as plan_generator
import generate_completion_audit_recovery_work_order as work_order_generator
import run_completion_audit_recovery_queue as queue_runner
from test_generate_completion_audit_recovery_plan import (
    _sample_handoff_payload,
    _write_json,
)


def _write_sources(root: Path, handoff_payload: dict) -> tuple[Path, Path, Path]:
    handoff_path = root / "handoff.json"
    plan_path = root / "recovery-plan.json"
    queue_path = root / "recovery-queue.json"
    _write_json(handoff_path, handoff_payload)
    plan = plan_generator.generate_completion_audit_recovery_plan(handoff_path)
    _write_json(plan_path, plan.to_dict())
    queue = queue_runner.run_completion_audit_recovery_queue(
        plan_path,
        handoff_json_path=handoff_path,
    )
    _write_json(queue_path, queue.to_dict())
    return handoff_path, plan_path, queue_path


def _runtime_only_handoff_payload() -> dict:
    payload = _sample_handoff_payload()
    payload["release_blockers"] = [payload["release_blockers"][0]]
    payload["release_blocker_count"] = 1
    return payload


class GenerateCompletionAuditRecoveryWorkOrderTests(unittest.TestCase):
    def test_generates_operator_setup_work_order_from_next_queue_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path = _write_sources(
                root,
                _sample_handoff_payload(),
            )

            work_order = (
                work_order_generator.generate_completion_audit_recovery_work_order(
                    queue_path,
                    recovery_plan_path=plan_path,
                    handoff_json_path=handoff_path,
                )
            )
            payload = work_order.to_dict()

        self.assertTrue(work_order.ok, payload)
        self.assertEqual(
            work_order_generator.RECOVERY_WORK_ORDER_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual("operator_setup_required", payload["work_order_state"])
        self.assertEqual(["setup-resolution"], payload["selected_group_ids"])
        self.assertTrue(payload["operator_setup_required"])
        self.assertFalse(payload["autonomous_dispatch_allowed"])
        self.assertEqual(2, payload["setup_task_count"])
        self.assertEqual(0, payload["runtime_task_count"])
        self.assertEqual(2, payload["selected_action_item_count"])
        self.assertRegex(payload["work_order_fingerprint_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            {"setup_resolution"},
            {task["action_type"] for task in payload["tasks"]},
        )
        self.assertFalse(payload["tasks"][0]["safe_to_execute_autonomously"])
        self.assertTrue(payload["tasks"][0]["operator_setup_required"])
        self.assertIn("attest", payload["tasks"][0]["next_instruction"])
        self.assertFalse(payload["privacy"]["secret_values_included"])

    def test_generates_autonomous_dispatch_work_order_when_runtime_group_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path = _write_sources(
                root,
                _runtime_only_handoff_payload(),
            )

            work_order = (
                work_order_generator.generate_completion_audit_recovery_work_order(
                    queue_path,
                    recovery_plan_path=plan_path,
                    handoff_json_path=handoff_path,
                )
            )
            payload = work_order.to_dict()

        self.assertTrue(work_order.ok, payload)
        self.assertEqual("autonomous_dispatch_ready", payload["work_order_state"])
        self.assertEqual(
            ["runtime-evidence-dispatch"],
            payload["selected_group_ids"],
        )
        self.assertFalse(payload["operator_setup_required"])
        self.assertTrue(payload["autonomous_dispatch_allowed"])
        self.assertEqual(0, payload["setup_task_count"])
        self.assertEqual(1, payload["runtime_task_count"])
        self.assertTrue(payload["tasks"][0]["safe_to_execute_autonomously"])
        self.assertIn(".github/workflows/sample.yml", payload["tasks"][0]["workflow"])

    def test_source_validation_failure_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path = _write_sources(
                root,
                _sample_handoff_payload(),
            )
            queue_payload = json.loads(queue_path.read_text(encoding="utf-8"))
            queue_payload["next_group_ids"] = ["missing-group"]
            _write_json(queue_path, queue_payload)

            work_order = (
                work_order_generator.generate_completion_audit_recovery_work_order(
                    queue_path,
                    recovery_plan_path=plan_path,
                    handoff_json_path=handoff_path,
                )
            )
            payload = work_order.to_dict()

        self.assertFalse(work_order.ok)
        self.assertEqual("invalid", payload["work_order_state"])
        self.assertIn(
            "completion_audit_recovery_work_order_queue_invalid",
            payload["error_codes"],
        )

    def test_cli_writes_work_order_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path = _write_sources(
                root,
                _sample_handoff_payload(),
            )
            out_path = root / "work-order.json"

            exit_code = work_order_generator.main(
                [
                    str(queue_path),
                    "--recovery-plan",
                    str(plan_path),
                    "--handoff-json",
                    str(handoff_path),
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            work_order_generator.RECOVERY_WORK_ORDER_SCHEMA_VERSION,
            payload["schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
