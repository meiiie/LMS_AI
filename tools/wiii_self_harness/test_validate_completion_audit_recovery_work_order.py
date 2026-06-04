import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_work_order as generator
from test_generate_completion_audit_recovery_plan import _write_json
from test_generate_completion_audit_recovery_work_order import _write_sources
from test_generate_completion_audit_recovery_plan import _sample_handoff_payload
import validate_completion_audit_recovery_work_order as validator


def _write_work_order(root: Path) -> tuple[Path, Path, Path, Path, dict]:
    handoff_path, plan_path, queue_path = _write_sources(
        root,
        _sample_handoff_payload(),
    )
    work_order_path = root / "work-order.json"
    work_order = generator.generate_completion_audit_recovery_work_order(
        queue_path,
        recovery_plan_path=plan_path,
        handoff_json_path=handoff_path,
    )
    payload = work_order.to_dict()
    _write_json(work_order_path, payload)
    return handoff_path, plan_path, queue_path, work_order_path, payload


class ValidateCompletionAuditRecoveryWorkOrderTests(unittest.TestCase):
    def test_valid_work_order_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, queue_path, work_order_path, _payload = (
                _write_work_order(Path(temp_dir))
            )

            result = validator.validate_recovery_work_order(
                work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_work_order_must_match_source_queue_and_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, queue_path, work_order_path, payload = (
                _write_work_order(Path(temp_dir))
            )
            payload["selected_group_ids"] = ["stale-group"]
            _write_json(work_order_path, payload)

            result = validator.validate_recovery_work_order(
                work_order_path,
                recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_work_order_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_work_order_fingerprint_must_match_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, _plan_path, _queue_path, work_order_path, payload = (
                _write_work_order(Path(temp_dir))
            )
            payload["tasks"][0]["next_instruction"] = "manual override"
            _write_json(work_order_path, payload)

            result = validator.validate_recovery_work_order(work_order_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_work_order_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_task_schema_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, _plan_path, _queue_path, work_order_path, payload = (
                _write_work_order(Path(temp_dir))
            )
            payload["tasks"][0]["operator_note"] = "not part of contract"
            _write_json(work_order_path, payload)

            result = validator.validate_recovery_work_order(work_order_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_work_order_task_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path, work_order_path, _payload = (
                _write_work_order(root)
            )
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
                    str(work_order_path),
                    "--recovery-queue",
                    str(queue_path),
                    "--recovery-plan",
                    str(plan_path),
                    "--handoff-json",
                    str(handoff_path),
                    "--json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.RECOVERY_WORK_ORDER_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
