import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_attestation_template as template_generator
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_attestation_template import (
    _write_setup_handle_plan,
)
from test_validate_completion_audit_setup_state import _load_json
import smoke_completion_audit_setup_attestation as smoke


def _write_template(root: Path) -> tuple[Path, Path, Path, Path]:
    launch_pack_path, setup_state_path, setup_handle_plan_path = (
        _write_setup_handle_plan(root)
    )
    template = template_generator.generate_completion_audit_setup_attestation_template(
        setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    template_path = root / "setup-attestation-template.json"
    _write_json(template_path, template)
    return launch_pack_path, setup_state_path, setup_handle_plan_path, template_path


class SmokeCompletionAuditSetupAttestationTests(unittest.TestCase):
    def test_smoke_selects_template_options_and_unlocks_dispatch_dry_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, setup_handle_plan_path, template_path = (
                _write_template(root)
            )
            out_dir = root / "setup-attestation-smoke"
            json_out = root / "setup-attestation-smoke.json"

            payload = smoke.run_completion_audit_setup_attestation_smoke(
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                setup_handle_plan_path=setup_handle_plan_path,
                template_path=template_path,
                out_dir=out_dir,
                json_out=json_out,
                repo_root=root,
            )
            persisted_payload = _load_json(json_out)
            generated_reports_exist = {
                report_name: (out_dir / report_name).is_file()
                for report_name in payload["generated_reports"]
            }

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            smoke.SETUP_ATTESTATION_SMOKE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertTrue(payload["dry_run_only"])
        self.assertGreater(payload["template_pending_setup_check_count"], 0)
        self.assertEqual(
            payload["template_pending_setup_check_count"],
            payload["selected_attestation_count"],
        )
        self.assertEqual(
            payload["selected_attestation_count"],
            payload["attestation_count"],
        )
        self.assertTrue(payload["attested_setup_dispatch_ready"])
        self.assertTrue(payload["dispatch_gate_ready"])
        self.assertTrue(payload["dispatch_run_ok"])
        self.assertTrue(payload["dispatch_run_dry_run"])
        self.assertGreater(payload["dispatch_run_command_count"], 0)
        self.assertEqual(0, payload["dispatch_run_executed_command_count"])
        self.assertEqual(payload, persisted_payload)
        for report_name, exists in generated_reports_exist.items():
            self.assertTrue(exists, report_name)
        for validation in payload["validation"].values():
            self.assertTrue(validation["ok"], validation)
        rendered = json.dumps(payload, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)
        self.assertFalse(payload["privacy"]["raw_output_included"])

    def test_cli_writes_smoke_report_without_live_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, setup_handle_plan_path, template_path = (
                _write_template(root)
            )
            out_dir = root / "setup-attestation-smoke"
            json_out = root / "setup-attestation-smoke.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = smoke.main(
                    [
                        "--launch-pack",
                        str(launch_pack_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--setup-handle-plan",
                        str(setup_handle_plan_path),
                        "--template",
                        str(template_path),
                        "--out-dir",
                        str(out_dir),
                        "--json-out",
                        str(json_out),
                        "--repo-root",
                        str(root),
                    ]
                )
            payload = _load_json(json_out)

        self.assertEqual(0, exit_code)
        self.assertIn(
            "Wiii Completion Audit Setup Attestation Smoke: PASS",
            stdout.getvalue(),
        )
        self.assertTrue(payload["dispatch_run_ok"])
        self.assertEqual(0, payload["dispatch_run_executed_command_count"])

    def test_json_out_must_stay_outside_generated_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, setup_handle_plan_path, template_path = (
                _write_template(root)
            )
            out_dir = root / "setup-attestation-smoke"

            with self.assertRaises(ValueError) as context:
                smoke.run_completion_audit_setup_attestation_smoke(
                    launch_pack_path=launch_pack_path,
                    setup_state_path=setup_state_path,
                    setup_handle_plan_path=setup_handle_plan_path,
                    template_path=template_path,
                    out_dir=out_dir,
                    json_out=out_dir / "sidecar.json",
                    repo_root=root,
                )

        self.assertIn(
            smoke.SMOKE_JSON_OUTPUT_PATH_INSIDE_OUT_DIR_ERROR,
            str(context.exception),
        )


if __name__ == "__main__":
    unittest.main()
