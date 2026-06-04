import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_queue_progress as generator
from test_generate_completion_audit_recovery_plan import _write_json
from test_generate_completion_audit_recovery_queue_progress import (
    _write_progress_sources,
)
import validate_completion_audit_recovery_queue_progress as validator


def _write_progress(root: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, dict]:
    (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
    ) = _write_progress_sources(root, setup_ready=True)
    progress_path = root / "progress.json"
    progress = generator.generate_completion_audit_recovery_queue_progress(
        queue_path,
        recovery_plan_path=plan_path,
        work_order_status_path=status_path,
        recovery_work_order_path=work_order_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    payload = progress.to_dict()
    _write_json(progress_path, payload)
    return (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
        payload,
    )


class ValidateCompletionAuditRecoveryQueueProgressTests(unittest.TestCase):
    def test_valid_progress_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                _payload,
            ) = _write_progress(Path(temp_dir))

            result = validator.validate_recovery_queue_progress(
                progress_path,
                source_recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_progress_must_match_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                payload,
            ) = _write_progress(Path(temp_dir))
            payload["next_group_ids"] = ["setup-resolution"]
            _write_json(progress_path, payload)

            result = validator.validate_recovery_queue_progress(
                progress_path,
                source_recovery_queue_path=queue_path,
                recovery_plan_path=plan_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_queue_progress_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_progress_fingerprint_must_match_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_paths, progress_path, payload = _write_progress(Path(temp_dir))
            payload["group_statuses"][1]["next_action"] = "manual override"
            _write_json(progress_path, payload)

            result = validator.validate_recovery_queue_progress(progress_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_queue_progress_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_group_status_schema_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_paths, progress_path, payload = _write_progress(Path(temp_dir))
            payload["group_statuses"][1]["operator_note"] = "not allowed"
            _write_json(progress_path, payload)

            result = validator.validate_recovery_queue_progress(progress_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_queue_progress_group_status_invalid",
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
                _payload,
            ) = _write_progress(root)
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
                    str(progress_path),
                    "--source-recovery-queue",
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
                    "--json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.QUEUE_PROGRESS_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
