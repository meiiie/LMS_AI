import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_attestation_template as generator
import generate_completion_audit_setup_handle_plan as plan_generator
from test_generate_completion_audit_dispatch_gate import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json


def _write_setup_handle_plan(root: Path, *, ready: bool = False) -> tuple[Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root, ready=ready)
    plan = plan_generator.generate_completion_audit_setup_handle_plan(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    plan_path = root / "setup-handle-plan.json"
    _write_json(plan_path, plan)
    return launch_pack_path, setup_state_path, plan_path


class GenerateCompletionAuditSetupAttestationTemplateTests(unittest.TestCase):
    def test_generate_pending_template_lists_safe_operator_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_setup_handle_plan(root)

            template = generator.generate_completion_audit_setup_attestation_template(
                plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            ).to_dict()

        self.assertTrue(template["ok"], template)
        self.assertEqual(
            generator.SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION,
            template["schema_version"],
        )
        self.assertEqual(2, template["requirement_count"])
        self.assertGreater(template["pending_setup_check_count"], 0)
        self.assertGreater(template["attestation_option_count"], 0)
        first_check = template["requirements"][0]["setup_checks"][0]
        self.assertEqual("pending_operator_attestation", first_check["status"])
        self.assertEqual("", first_check["selected_attestation_spec"])
        self.assertEqual("", first_check["operator_evidence_ref_handle"])
        self.assertGreater(first_check["source_handle_options"], [])
        self.assertGreater(first_check["attestation_spec_options"], [])
        self.assertFalse(template["privacy"]["secret_values_included"])
        rendered = json.dumps(template, sort_keys=True)
        self.assertIn("@operator_approved_recipient:", rendered)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_ready_plan_generates_empty_template_without_unlocking_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_setup_handle_plan(
                root,
                ready=True,
            )

            template = generator.generate_completion_audit_setup_attestation_template(
                plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            ).to_dict()

        self.assertEqual(0, template["requirement_count"])
        self.assertEqual(0, template["pending_setup_check_count"])
        self.assertEqual(0, template["attestation_option_count"])
        self.assertEqual([], template["requirements"])

    def test_cli_writes_template_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_setup_handle_plan(root)
            out_path = root / "setup-attestation-template.json"

            exit_code = generator.main(
                [
                    str(plan_path),
                    "--setup-state",
                    str(setup_state_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--out",
                    str(out_path),
                ]
            )
            payload = _load_json(out_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(
            generator.SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertGreater(payload["pending_setup_check_count"], 0)

    def test_cli_reports_invalid_setup_handle_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_setup_handle_plan(root)
            payload = _load_json(plan_path)
            payload["privacy"]["secret_values_included"] = True
            _write_json(plan_path, payload)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main([str(plan_path)])
            output = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_template_plan_invalid"],
            output["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
