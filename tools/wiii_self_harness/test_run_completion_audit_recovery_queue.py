import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_plan as recovery_plan_generator
import run_completion_audit_recovery_queue as queue_runner
from test_generate_completion_audit_recovery_plan import (
    _sample_handoff_payload,
    _write_json,
)


def _write_recovery_plan(root: Path) -> tuple[Path, Path, dict]:
    handoff_path = root / "handoff.json"
    plan_path = root / "recovery-plan.json"
    _write_json(handoff_path, _sample_handoff_payload())
    plan = recovery_plan_generator.generate_completion_audit_recovery_plan(
        handoff_path
    )
    payload = plan.to_dict()
    _write_json(plan_path, payload)
    return handoff_path, plan_path, payload


class RunCompletionAuditRecoveryQueueTests(unittest.TestCase):
    def test_recovery_queue_materializes_next_blocked_setup_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path, plan_path, _plan_payload = _write_recovery_plan(
                Path(temp_dir)
            )

            report = queue_runner.run_completion_audit_recovery_queue(
                plan_path,
                handoff_json_path=handoff_path,
            )
            payload = report.to_dict()

        self.assertTrue(report.ok, payload)
        self.assertEqual(
            queue_runner.RECOVERY_QUEUE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertTrue(payload["dry_run"])
        self.assertEqual("blocked_on_external_setup", payload["queue_state"])
        self.assertEqual(3, payload["execution_group_count"])
        self.assertEqual(0, payload["ready_group_count"])
        self.assertEqual(3, payload["blocked_group_count"])
        self.assertEqual(1, payload["blocked_by_external_setup_count"])
        self.assertEqual(2, payload["blocked_by_dependency_count"])
        self.assertEqual(0, payload["ready_for_autonomous_dispatch_count"])
        self.assertEqual(["setup-resolution"], payload["next_group_ids"])
        self.assertRegex(payload["group_status_fingerprint_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            [
                "blocked_by_external_setup",
                "blocked_by_dependency",
                "blocked_by_dependency",
            ],
            [status["status"] for status in payload["group_statuses"]],
        )
        self.assertEqual(
            "Resolve external setup and credential handles",
            payload["group_statuses"][0]["next_action"],
        )
        self.assertFalse(payload["privacy"]["secret_values_included"])

    def test_recovery_queue_surfaces_source_validation_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, payload = _write_recovery_plan(root)
            payload["action_items"][0]["workflow"] = ".github/workflows/stale.yml"
            payload["action_items_fingerprint_sha256"] = (
                recovery_plan_generator._action_items_fingerprint(
                    payload["action_items"]
                )
            )
            _write_json(plan_path, payload)

            report = queue_runner.run_completion_audit_recovery_queue(
                plan_path,
                handoff_json_path=handoff_path,
            )
            result = report.to_dict()

        self.assertFalse(report.ok)
        self.assertEqual("invalid", result["queue_state"])
        self.assertIn(
            "completion_audit_recovery_queue_plan_invalid",
            result["error_codes"],
        )

    def test_cli_writes_recovery_queue_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path, plan_path, _payload = _write_recovery_plan(root)
            out_path = root / "queue.json"

            exit_code = queue_runner.main(
                [
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
            queue_runner.RECOVERY_QUEUE_SCHEMA_VERSION,
            payload["schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
