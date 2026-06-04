import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_attestation_template as generator
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_attestation_template import (
    _write_setup_handle_plan,
)
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_attestation_template as validator


def _write_template(root: Path) -> tuple[Path, Path, Path, Path]:
    launch_pack_path, setup_state_path, plan_path = _write_setup_handle_plan(root)
    template = generator.generate_completion_audit_setup_attestation_template(
        plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    template_path = root / "setup-attestation-template.json"
    _write_json(template_path, template)
    return launch_pack_path, setup_state_path, plan_path, template_path


class ValidateCompletionAuditSetupAttestationTemplateTests(unittest.TestCase):
    def test_valid_template_passes_with_source_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path = (
                _write_template(root)
            )

            result = validator.validate_setup_attestation_template(
                template_path,
                setup_handle_plan_path=plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_selected_attestation_spec_must_remain_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _plan_path, template_path = (
                _write_template(root)
            )
            payload = _load_json(template_path)
            check = payload["requirements"][0]["setup_checks"][0]
            check["selected_attestation_spec"] = check["attestation_spec_options"][0]
            payload["setup_attestation_template_fingerprint_sha256"] = (
                generator._template_fingerprint(payload["requirements"])
            )
            _write_json(template_path, payload)

            result = validator.validate_setup_attestation_template(template_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_attestation_template_selected_spec_not_empty",
            result.to_dict()["error_codes"],
        )

    def test_raw_source_handle_option_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, _plan_path, template_path = (
                _write_template(root)
            )
            payload = _load_json(template_path)
            payload["requirements"][0]["setup_checks"][0][
                "source_handle_options"
            ] = ["<raw-recipient-id>"]
            payload["setup_attestation_template_fingerprint_sha256"] = (
                generator._template_fingerprint(payload["requirements"])
            )
            _write_json(template_path, payload)

            result = validator.validate_setup_attestation_template(template_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_attestation_template_unsafe_token",
            result.to_dict()["error_codes"],
        )

    def test_source_parity_rejects_stale_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path = (
                _write_template(root)
            )
            payload = _load_json(template_path)
            payload["requirements"][0]["setup_checks"][0]["attestation_spec_options"] = (
                payload["requirements"][0]["setup_checks"][0]["attestation_spec_options"][:1]
            )
            payload["attestation_option_count"] -= 1
            payload["setup_attestation_template_fingerprint_sha256"] = (
                generator._template_fingerprint(payload["requirements"])
            )
            _write_json(template_path, payload)

            result = validator.validate_setup_attestation_template(
                template_path,
                setup_handle_plan_path=plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_attestation_template_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path = (
                _write_template(root)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(template_path),
                        "--setup-handle-plan",
                        str(plan_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.SETUP_ATTESTATION_TEMPLATE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
