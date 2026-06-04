import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_recovery_plan as generator


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sample_handoff_payload() -> dict:
    return {
        "schema_version": generator.COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION,
        "ok": False,
        "completion_audit_ready": False,
        "release_handoff_ready": False,
        "release_blocker_count": 3,
        "release_blockers": [
            {
                "kind": "runtime_evidence",
                "requirement_id": "sample-runtime",
                "artifact": "sample-runtime.json",
                "status": "failed",
                "error_codes": ["payload_check_min_mismatch"],
                "recovery_action": {
                    "requirement_id": "sample-runtime",
                    "artifact": "sample-runtime.json",
                    "status": "failed",
                    "workflow": ".github/workflows/sample.yml",
                    "probe": "scripts/probe_sample.py",
                    "blocked_by_live_setup": True,
                    "live_env_flags": ["WIII_LIVE_SAMPLE"],
                    "live_guard_tokens": ["--allow-sample"],
                    "dispatch_or_schedule_gate_tokens": ["run_sample"],
                    "artifact_tokens": ["sample-runtime-${{ github.run_id }}"],
                    "preflight_required_next": ["configure_sample"],
                    "error_codes": ["payload_check_min_mismatch"],
                },
            },
            {
                "kind": "setup_gap",
                "requirement_id": "sample-runtime",
                "pending_setup_check_count": 2,
                "diagnostic_pending_setup_keys": [
                    "environment_flags_required:live_sample_flag"
                ],
                "non_diagnostic_pending_setup_keys": [
                    "credential_slots_required:sample_token"
                ],
                "resolution_actions": [
                    {
                        "category": "environment_flags_required",
                        "key": "live_sample_flag",
                        "evidence_kind": "environment_flag_bound",
                        "binding_token_count": 1,
                        "source_handle_options": ["WIII_LIVE_SAMPLE"],
                        "attestation_option_count": 1,
                    },
                    {
                        "category": "credential_slots_required",
                        "key": "sample_token",
                        "evidence_kind": "github_secret_present",
                        "binding_token_count": 1,
                        "source_handle_options": ["SAMPLE_TOKEN"],
                        "attestation_option_count": 1,
                    },
                ],
            },
            {
                "kind": "control_chain",
                "blocker_id": "dispatch_ready",
                "status": "blocked",
                "error_codes": [],
            },
        ],
    }


class GenerateCompletionAuditRecoveryPlanTests(unittest.TestCase):
    def test_generate_recovery_plan_materializes_handoff_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path = root / "handoff.json"
            _write_json(handoff_path, _sample_handoff_payload())

            plan = generator.generate_completion_audit_recovery_plan(handoff_path)
            payload = plan.to_dict()
            markdown = generator.format_markdown(plan)

        self.assertTrue(plan.ok, payload)
        self.assertEqual(4, payload["action_item_count"])
        self.assertEqual(1, payload["runtime_recovery_action_count"])
        self.assertEqual(2, payload["setup_resolution_action_count"])
        self.assertEqual(1, payload["gate_dependency_count"])
        self.assertEqual(3, payload["execution_group_count"])
        self.assertEqual(
            [
                "setup-resolution",
                "runtime-evidence-dispatch",
                "release-gate-validation",
            ],
            [group["group_id"] for group in payload["execution_groups"]],
        )
        self.assertFalse(
            payload["execution_groups"][1]["ready_for_autonomous_dispatch"]
        )
        self.assertIn(
            "workflow_probe_recovery",
            {item["action_type"] for item in payload["action_items"]},
        )
        self.assertRegex(payload["action_items_fingerprint_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            payload["execution_groups_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertFalse(payload["privacy"]["secret_values_included"])
        self.assertIn(".github/workflows/sample.yml", markdown)
        self.assertIn("credential_slots_required:sample_token", markdown)

    def test_missing_runtime_recovery_action_is_visible_failure(self) -> None:
        payload = _sample_handoff_payload()
        payload["release_blockers"][0]["recovery_action"] = None
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_path = Path(temp_dir) / "handoff.json"
            _write_json(handoff_path, payload)

            plan = generator.generate_completion_audit_recovery_plan(handoff_path)
            plan_payload = plan.to_dict()

        self.assertFalse(plan.ok)
        self.assertIn(
            "completion_audit_recovery_plan_runtime_action_missing",
            plan_payload["error_codes"],
        )
        self.assertEqual(
            "missing_recovery_action",
            plan_payload["action_items"][0]["action_type"],
        )
        self.assertFalse(
            plan_payload["execution_groups"][1]["ready_for_autonomous_dispatch"]
        )

    def test_cli_json_writes_recovery_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path = root / "handoff.json"
            out_path = root / "recovery-plan.json"
            _write_json(handoff_path, _sample_handoff_payload())

            exit_code = generator.main(
                [str(handoff_path), "--format", "json", "--out", str(out_path)]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(generator.RECOVERY_PLAN_SCHEMA_VERSION, payload["schema_version"])

    def test_cli_json_writes_not_ready_recovery_plan_without_generation_failure(
        self,
    ) -> None:
        payload = _sample_handoff_payload()
        payload["release_blockers"][0]["recovery_action"] = None
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path = root / "handoff.json"
            out_path = root / "recovery-plan.json"
            _write_json(handoff_path, payload)

            exit_code = generator.main(
                [str(handoff_path), "--format", "json", "--out", str(out_path)]
            )
            plan_payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertFalse(plan_payload["ok"])
        self.assertIn(
            "completion_audit_recovery_plan_runtime_action_missing",
            plan_payload["error_codes"],
        )

    def test_cli_markdown_writes_recovery_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            handoff_path = root / "handoff.json"
            _write_json(handoff_path, _sample_handoff_payload())
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main([str(handoff_path), "--format", "markdown"])

        self.assertEqual(0, exit_code)
        self.assertIn("# Wiii Completion Audit Recovery Plan", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
