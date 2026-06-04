import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_plan as generator
from test_generate_completion_audit_recovery_plan import (
    _sample_handoff_payload,
    _write_json,
)
import validate_completion_audit_recovery_plan as validator


def _write_recovery_plan(root: Path) -> tuple[Path, Path, dict]:
    handoff_path = root / "handoff.json"
    plan_path = root / "recovery-plan.json"
    _write_json(handoff_path, _sample_handoff_payload())
    plan = generator.generate_completion_audit_recovery_plan(handoff_path)
    payload = plan.to_dict()
    _write_json(plan_path, payload)
    return handoff_path, plan_path, payload


class ValidateCompletionAuditRecoveryPlanTests(unittest.TestCase):
    def test_valid_recovery_plan_passes_with_handoff_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, _payload = _write_recovery_plan(Path(temp_dir))

            result = validator.validate_recovery_plan(
                plan_path,
                handoff_json_path=handoff_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_recovery_plan_must_match_handoff_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, payload = _write_recovery_plan(Path(temp_dir))
            payload["action_items"][0]["workflow"] = ".github/workflows/stale.yml"
            payload["action_items_fingerprint_sha256"] = (
                generator._action_items_fingerprint(payload["action_items"])
            )
            _write_json(plan_path, payload)

            result = validator.validate_recovery_plan(
                plan_path,
                handoff_json_path=handoff_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_plan_handoff_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_action_items_fingerprint_must_match_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, plan_path, payload = _write_recovery_plan(Path(temp_dir))
            payload["action_items"][0]["workflow"] = ".github/workflows/stale.yml"
            _write_json(plan_path, payload)

            result = validator.validate_recovery_plan(plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_action_item_schema_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, plan_path, payload = _write_recovery_plan(Path(temp_dir))
            payload["action_items"][0]["operator_note"] = "manual override"
            _write_json(plan_path, payload)

            result = validator.validate_recovery_plan(plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_plan_action_item_invalid",
            result.to_dict()["error_codes"],
        )

    def test_execution_groups_fingerprint_must_match_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, plan_path, payload = _write_recovery_plan(Path(temp_dir))
            payload["execution_groups"][0]["item_ids"] = []
            _write_json(plan_path, payload)

            result = validator.validate_recovery_plan(plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_execution_group_items_must_reference_action_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _handoff_path, plan_path, payload = _write_recovery_plan(Path(temp_dir))
            payload["execution_groups"][0]["item_ids"] = ["missing:item"]
            payload["execution_groups_fingerprint_sha256"] = (
                generator._execution_groups_fingerprint(payload["execution_groups"])
            )
            _write_json(plan_path, payload)

            result = validator.validate_recovery_plan(plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_recovery_plan_execution_group_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, _payload = _write_recovery_plan(root)
            out_path = root / "validation.json"

            exit_code = validator.main(
                [
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
            validator.RECOVERY_PLAN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
