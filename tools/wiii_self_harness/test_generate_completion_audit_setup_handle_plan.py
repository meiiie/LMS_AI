import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_handle_plan as generator
from test_generate_completion_audit_dispatch_gate import _write_setup_state
from test_validate_completion_audit_setup_state import _load_json


class GenerateCompletionAuditSetupHandlePlanTests(unittest.TestCase):
    def test_generate_pending_plan_lists_safe_recommended_handle_specs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)

            plan = generator.generate_completion_audit_setup_handle_plan(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            ).to_dict()

        self.assertTrue(plan["ok"], plan)
        self.assertEqual(generator.SETUP_HANDLE_PLAN_SCHEMA_VERSION, plan["schema_version"])
        self.assertFalse(plan["privacy"]["secret_values_included"])
        self.assertEqual(2, plan["blocked_requirement_count"])
        self.assertGreater(plan["pending_setup_check_count"], 0)
        first_check = plan["plan_items"][0]["setup_checks"][0]
        self.assertFalse(first_check["present"])
        self.assertGreater(first_check["recommended_handle_specs"], [])
        self.assertEqual(["workflow_input_bound"], first_check["recommended_evidence_kinds"])
        self.assertGreater(first_check["recommended_attestation_specs"], [])
        self.assertIn(
            "@workflow_input_bound:",
            first_check["recommended_attestation_specs"][0],
        )
        proactive_credential_check = next(
            check
            for item in plan["plan_items"]
            for check in item["setup_checks"]
            if item["requirement_id"] == "autonomy-proactive-channel"
            and check["category"] == "credential_slots_required"
            and check["key"] == "selected_channel_credential"
        )
        self.assertEqual(
            ["runtime_channel_credential_validated"],
            proactive_credential_check["recommended_evidence_kinds"],
        )
        self.assertIn(
            "@runtime_channel_credential_validated:",
            proactive_credential_check["recommended_attestation_specs"][0],
        )
        proactive_channel_check = next(
            check
            for item in plan["plan_items"]
            for check in item["setup_checks"]
            if item["requirement_id"] == "autonomy-proactive-channel"
            and check["category"] == "external_setup_required"
            and check["key"] == "selected_channel_enabled"
        )
        self.assertEqual(
            ["runtime_channel_enabled"],
            proactive_channel_check["recommended_evidence_kinds"],
        )
        composio_credential_check = next(
            check
            for item in plan["plan_items"]
            for check in item["setup_checks"]
            if item["requirement_id"] == "wiii-connect-composio-acceptance"
            and check["category"] == "credential_slots_required"
            and check["key"] == "acceptance_bearer_token"
        )
        self.assertEqual(
            ["github_secret_present"],
            composio_credential_check["recommended_evidence_kinds"],
        )
        self.assertIn(
            "@github_secret_present:",
            composio_credential_check["recommended_attestation_specs"][0],
        )
        rendered = json.dumps(plan, sort_keys=True)
        self.assertIn("autonomy-proactive-channel:", rendered)
        self.assertIn("@operator_approved_recipient:", rendered)
        self.assertIn("selected_channel_credential", rendered)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_generate_ready_plan_omits_recommended_specs_for_ready_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root, ready=True)

            plan = generator.generate_completion_audit_setup_handle_plan(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            ).to_dict()

        self.assertEqual(0, plan["pending_setup_check_count"])
        self.assertGreater(plan["ready_setup_check_count"], 0)
        for item in plan["plan_items"]:
            for check in item["setup_checks"]:
                self.assertTrue(check["present"])
                self.assertEqual([], check["recommended_handle_specs"])
                self.assertEqual([], check["recommended_evidence_kinds"])
                self.assertEqual([], check["recommended_attestation_specs"])

    def test_cli_writes_setup_handle_plan_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            out_path = root / "setup-handle-plan.json"

            exit_code = generator.main(
                [
                    str(setup_state_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(generator.SETUP_HANDLE_PLAN_SCHEMA_VERSION, payload["schema_version"])
        self.assertGreater(payload["pending_setup_check_count"], 0)

    def test_cli_reports_invalid_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path = _write_setup_state(root)
            payload = _load_json(setup_state_path)
            payload["privacy"]["secret_values_included"] = True
            setup_state_path.write_text(json.dumps(payload), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main([str(setup_state_path)])
            output = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_plan_setup_state_invalid"],
            output["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
