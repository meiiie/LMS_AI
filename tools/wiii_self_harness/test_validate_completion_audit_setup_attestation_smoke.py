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
import smoke_completion_audit_setup_attestation as smoke_generator
import validate_completion_audit_setup_attestation_smoke as validator


def _write_smoke_fixture(root: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
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
    out_dir = root / "setup-attestation-smoke"
    smoke_json = root / "setup-attestation-smoke.json"
    smoke_generator.run_completion_audit_setup_attestation_smoke(
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        setup_handle_plan_path=setup_handle_plan_path,
        template_path=template_path,
        out_dir=out_dir,
        json_out=smoke_json,
        repo_root=root,
    )
    return (
        launch_pack_path,
        setup_state_path,
        setup_handle_plan_path,
        template_path,
        out_dir,
        smoke_json,
    )


class ValidateCompletionAuditSetupAttestationSmokeTests(unittest.TestCase):
    def test_valid_smoke_sidecar_passes_with_source_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                launch_pack_path,
                setup_state_path,
                setup_handle_plan_path,
                template_path,
                out_dir,
                smoke_json,
            ) = _write_smoke_fixture(root)

            result = validator.validate_completion_audit_setup_attestation_smoke(
                smoke_json,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                setup_handle_plan_path=setup_handle_plan_path,
                template_path=template_path,
                out_dir=out_dir,
                repo_root=root,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.errors)
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_payload_rejects_executed_dry_run_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            *_sources, smoke_json = _write_smoke_fixture(root)
            payload = _load_json(smoke_json)
            payload["dispatch_run_executed_command_count"] = 1
            _write_json(smoke_json, payload)

            result = validator.validate_completion_audit_setup_attestation_smoke(
                smoke_json
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "setup_attestation_smoke_count_invalid",
            result.to_dict()["error_codes"],
        )

    def test_source_validation_rejects_tampered_embedded_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                launch_pack_path,
                setup_state_path,
                setup_handle_plan_path,
                template_path,
                out_dir,
                smoke_json,
            ) = _write_smoke_fixture(root)
            payload = _load_json(smoke_json)
            payload["validation"]["dispatch_run"]["ok"] = False
            _write_json(smoke_json, payload)

            result = validator.validate_completion_audit_setup_attestation_smoke(
                smoke_json,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                setup_handle_plan_path=setup_handle_plan_path,
                template_path=template_path,
                out_dir=out_dir,
                repo_root=root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "setup_attestation_smoke_validation_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                launch_pack_path,
                setup_state_path,
                setup_handle_plan_path,
                template_path,
                out_dir,
                smoke_json,
            ) = _write_smoke_fixture(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(smoke_json),
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
                        "--repo-root",
                        str(root),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            validator.SETUP_ATTESTATION_SMOKE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )


if __name__ == "__main__":
    unittest.main()
