import json
from pathlib import Path
import tempfile
import unittest

import report_completion_audit_recovery_work_order_status as reporter
from test_generate_completion_audit_recovery_plan import _write_json
from test_report_completion_audit_recovery_work_order_status import (
    _setup_state_from_work_order,
    _write_work_order,
)
import validate_completion_audit_recovery_work_order_status as validator


def _write_status(root: Path) -> tuple[Path, Path, Path, Path, Path, Path, dict]:
    handoff_path, plan_path, queue_path, work_order_path, work_order = (
        _write_work_order(root)
    )
    setup_state_path = root / "setup-state.json"
    status_path = root / "status.json"
    _write_json(setup_state_path, _setup_state_from_work_order(work_order, ready=True))
    status = reporter.report_completion_audit_recovery_work_order_status(
        work_order_path,
        recovery_queue_path=queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    payload = status.to_dict()
    _write_json(status_path, payload)
    return (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        payload,
    )


class ValidateCompletionAuditRecoveryWorkOrderStatusTests(unittest.TestCase):
    def test_valid_status_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                _payload,
            ) = _write_status(Path(temp_dir))

            result = validator.validate_recovery_work_order_status(
                status_path,
                recovery_work_order_path=work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_status_must_match_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                payload,
            ) = _write_status(Path(temp_dir))
            payload["completed_group_ids"] = []
            _write_json(status_path, payload)

            result = validator.validate_recovery_work_order_status(
                status_path,
                recovery_work_order_path=work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_work_order_status_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_task_status_fingerprint_must_match_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_paths, status_path, payload = _write_status(Path(temp_dir))
            payload["task_statuses"][0]["next_action"] = "manual override"
            _write_json(status_path, payload)

            result = validator.validate_recovery_work_order_status(status_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_work_order_status_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_task_status_schema_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_paths, status_path, payload = _write_status(Path(temp_dir))
            payload["task_statuses"][0]["operator_note"] = "not allowed"
            _write_json(status_path, payload)

            result = validator.validate_recovery_work_order_status(status_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_work_order_status_task_invalid",
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
                _payload,
            ) = _write_status(root)
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
                    str(status_path),
                    "--recovery-work-order",
                    str(work_order_path),
                    "--recovery-queue",
                    str(queue_path),
                    "--recovery-plan",
                    str(plan_path),
                    "--handoff-json",
                    str(handoff_path),
                    "--setup-state",
                    str(setup_state_path),
                    "--json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.WORK_ORDER_STATUS_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
