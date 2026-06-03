import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_work_order as work_order_generator
import generate_completion_audit_setup_state as setup_state_generator
import report_completion_audit_recovery_work_order_status as reporter
from test_generate_completion_audit_recovery_plan import (
    _sample_handoff_payload,
    _write_json,
)
from test_generate_completion_audit_recovery_work_order import _write_sources


def _write_work_order(root: Path) -> tuple[Path, Path, Path, Path, dict]:
    handoff_path, plan_path, queue_path = _write_sources(
        root,
        _sample_handoff_payload(),
    )
    work_order_path = root / "work-order.json"
    work_order = work_order_generator.generate_completion_audit_recovery_work_order(
        queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
    )
    payload = work_order.to_dict()
    _write_json(work_order_path, payload)
    return handoff_path, plan_path, queue_path, work_order_path, payload


def _setup_state_from_work_order(
    work_order: dict,
    *,
    ready: bool,
) -> dict:
    requirements: dict[str, dict] = {}
    for task in work_order["tasks"]:
        requirement = requirements.setdefault(
            task["requirement_id"],
            {
                "requirement_id": task["requirement_id"],
                "title": f"Setup for {task['requirement_id']}",
                "workflow": "sample.yml",
                "probe": "probe_sample.py",
                "expected_artifact": "sample.json",
                "setup_contract_version": "v1",
                "setup_status": "ready" if ready else "pending",
                "dispatch_ready": ready,
                "setup_checks": [],
            },
        )
        source_handle = task["source_handle_options"][0]
        requirement["setup_checks"].append(
            {
                "category": task["setup_category"],
                "key": task["setup_key"],
                "binding_tokens": task["source_handle_options"],
                "present": ready,
                "source_handle": source_handle if ready else "",
                "secret_value_included": False,
                "raw_identifier_included": False,
            }
        )
    requirement_list = list(requirements.values())
    ready_count = sum(1 for item in requirement_list if item["dispatch_ready"])
    return {
        "schema_version": setup_state_generator.SETUP_STATE_SCHEMA_VERSION,
        "ok": True,
        "launch_pack_path": "launch-pack.json",
        "launch_pack_sha256": "1" * 64,
        "launch_pack_schema_version": "wiii.completion_audit_launch_pack.v1",
        "launch_items_fingerprint_sha256": "2" * 64,
        "launch_setup_fingerprint_sha256": "3" * 64,
        "setup_state_fingerprint_sha256": (
            setup_state_generator._setup_state_fingerprint(requirement_list)
        ),
        "dispatch_ready": ready_count == len(requirement_list) and bool(requirement_list),
        "requirement_count": len(requirement_list),
        "ready_requirement_count": ready_count,
        "blocked_requirement_count": len(requirement_list) - ready_count,
        "requirements": requirement_list,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
        },
        "errors": [],
        "error_codes": [],
        "error_code_counts": {},
    }


class ReportCompletionAuditRecoveryWorkOrderStatusTests(unittest.TestCase):
    def test_status_without_setup_state_marks_operator_evidence_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path, work_order_path, _payload = (
                _write_work_order(root)
            )

            report = reporter.report_completion_audit_recovery_work_order_status(
                work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
            )
            payload = report.to_dict()

        self.assertTrue(report.ok, payload)
        self.assertEqual("operator_setup_evidence_missing", payload["status_state"])
        self.assertFalse(payload["selected_group_complete"])
        self.assertEqual(2, payload["pending_task_count"])
        self.assertEqual(
            {"blocked_by_missing_setup_state"},
            {status["status"] for status in payload["task_statuses"]},
        )

    def test_status_reports_pending_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path, work_order_path, work_order = (
                _write_work_order(root)
            )
            setup_state_path = root / "setup-state.json"
            _write_json(
                setup_state_path,
                _setup_state_from_work_order(work_order, ready=False),
            )

            report = reporter.report_completion_audit_recovery_work_order_status(
                work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )
            payload = report.to_dict()

        self.assertTrue(report.ok, payload)
        self.assertEqual("operator_setup_pending", payload["status_state"])
        self.assertFalse(payload["selected_group_complete"])
        self.assertEqual([], payload["completed_group_ids"])
        self.assertEqual(["setup-resolution"], payload["pending_group_ids"])
        self.assertEqual(0, payload["satisfied_task_count"])
        self.assertEqual(2, payload["pending_task_count"])

    def test_status_reports_complete_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path, work_order_path, work_order = (
                _write_work_order(root)
            )
            setup_state_path = root / "setup-state.json"
            _write_json(
                setup_state_path,
                _setup_state_from_work_order(work_order, ready=True),
            )

            report = reporter.report_completion_audit_recovery_work_order_status(
                work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )
            payload = report.to_dict()

        self.assertTrue(report.ok, payload)
        self.assertEqual("operator_setup_complete", payload["status_state"])
        self.assertTrue(payload["selected_group_complete"])
        self.assertEqual(["setup-resolution"], payload["completed_group_ids"])
        self.assertEqual([], payload["pending_group_ids"])
        self.assertEqual(2, payload["satisfied_task_count"])
        self.assertEqual(2, payload["setup_task_satisfied_count"])
        self.assertEqual(0, payload["pending_task_count"])
        self.assertRegex(payload["task_status_fingerprint_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            {"satisfied"},
            {status["status"] for status in payload["task_statuses"]},
        )

    def test_cli_writes_status_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path, work_order_path, work_order = (
                _write_work_order(root)
            )
            setup_state_path = root / "setup-state.json"
            out_path = root / "status.json"
            _write_json(
                setup_state_path,
                _setup_state_from_work_order(work_order, ready=True),
            )

            exit_code = reporter.main(
                [
                    str(work_order_path),
                    "--recovery-queue",
                    str(queue_path),
                    "--recovery-plan",
                    str(plan_path),
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
            reporter.WORK_ORDER_STATUS_SCHEMA_VERSION,
            payload["schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
