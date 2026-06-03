import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_dispatch_authorization as generator
from test_generate_completion_audit_recovery_dispatch_authorization import (
    _write_authorization_sources,
)
from test_generate_completion_audit_recovery_plan import _write_json
import validate_completion_audit_recovery_dispatch_authorization as validator


def _write_authorization(
    root: Path,
    *,
    setup_ready: bool = True,
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path, dict]:
    (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
    ) = _write_authorization_sources(root, setup_ready=setup_ready)
    authorization_path = root / "authorization.json"
    authorization = generator.generate_completion_audit_recovery_dispatch_authorization(
        progress_path,
        recovery_plan_path=plan_path,
        source_recovery_queue_path=queue_path,
        work_order_status_path=status_path,
        recovery_work_order_path=work_order_path,
        handoff_json_path=handoff_path,
        setup_state_path=setup_state_path,
    )
    payload = authorization.to_dict()
    _write_json(authorization_path, payload)
    return (
        handoff_path,
        plan_path,
        queue_path,
        work_order_path,
        setup_state_path,
        status_path,
        progress_path,
        authorization_path,
        payload,
    )


class ValidateCompletionAuditRecoveryDispatchAuthorizationTests(unittest.TestCase):
    def test_valid_authorization_passes_with_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                authorization_path,
                _payload,
            ) = _write_authorization(Path(temp_dir))

            result = validator.validate_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_authorization_must_match_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                handoff_path,
                plan_path,
                queue_path,
                work_order_path,
                setup_state_path,
                status_path,
                progress_path,
                authorization_path,
                payload,
            ) = _write_authorization(Path(temp_dir))
            payload["authorized_group_ids"] = []
            _write_json(authorization_path, payload)

            result = validator.validate_recovery_dispatch_authorization(
                authorization_path,
                recovery_queue_progress_path=progress_path,
                recovery_plan_path=plan_path,
                source_recovery_queue_path=queue_path,
                work_order_status_path=status_path,
                recovery_work_order_path=work_order_path,
                handoff_json_path=handoff_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_authorization_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_authorization_fingerprint_must_match_dispatch_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_paths, authorization_path, payload = _write_authorization(Path(temp_dir))
            payload["dispatch_items"][0]["recovery_status"] = "rerun_requested"
            _write_json(authorization_path, payload)

            result = validator.validate_recovery_dispatch_authorization(
                authorization_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_authorization_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_dispatch_item_schema_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            *_paths, authorization_path, payload = _write_authorization(Path(temp_dir))
            payload["dispatch_items"][0]["operator_note"] = "not allowed"
            _write_json(authorization_path, payload)

            result = validator.validate_recovery_dispatch_authorization(
                authorization_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_dispatch_authorization_dispatch_item_invalid",
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
                authorization_path,
                _payload,
            ) = _write_authorization(root)
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
                    str(authorization_path),
                    "--queue-progress",
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
                    "--json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.RECOVERY_DISPATCH_AUTHORIZATION_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
