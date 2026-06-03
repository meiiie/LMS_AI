import json
from pathlib import Path
import tempfile
import unittest

import run_completion_audit_recovery_queue as queue_runner
from test_generate_completion_audit_recovery_plan import _write_json
from test_run_completion_audit_recovery_queue import _write_recovery_plan
import validate_completion_audit_recovery_queue as validator


def _write_queue(root: Path) -> tuple[Path, Path, Path, dict]:
    handoff_path, plan_path, _plan_payload = _write_recovery_plan(root)
    queue_path = root / "queue.json"
    report = queue_runner.run_completion_audit_recovery_queue(
        plan_path,
        handoff_json_path=handoff_path,
    )
    payload = report.to_dict()
    _write_json(queue_path, payload)
    return handoff_path, plan_path, queue_path, payload


class ValidateCompletionAuditRecoveryQueueTests(unittest.TestCase):
    def test_valid_recovery_queue_passes_with_recovery_plan_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, queue_path, _payload = _write_queue(
                Path(temp_dir)
            )

            result = validator.validate_recovery_queue(
                queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_recovery_queue_must_match_recovery_plan_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, queue_path, payload = _write_queue(Path(temp_dir))
            payload["recovery_plan_path"] = "stale-recovery-plan.json"
            _write_json(queue_path, payload)

            result = validator.validate_recovery_queue(
                queue_path,
                recovery_plan_path=plan_path,
                handoff_json_path=handoff_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_queue_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_group_status_fingerprint_must_match_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, _plan_path, queue_path, payload = _write_queue(
                Path(temp_dir)
            )
            payload["group_statuses"][0]["next_action"] = "manual override"
            _write_json(queue_path, payload)

            result = validator.validate_recovery_queue(queue_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_queue_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_next_group_ids_must_match_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, _plan_path, queue_path, payload = _write_queue(
                Path(temp_dir)
            )
            payload["next_group_ids"] = []
            _write_json(queue_path, payload)

            result = validator.validate_recovery_queue(queue_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_queue_group_status_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, queue_path, _payload = _write_queue(root)
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
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
            validator.RECOVERY_QUEUE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
