import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_attestation_from_template as generator
from test_generate_completion_audit_setup_attestation_template import (
    _write_setup_handle_plan,
)
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import generate_completion_audit_setup_attestation_template as template_generator
import validate_completion_audit_setup_attestation as attestation_validator


def _write_template(root: Path) -> tuple[Path, Path, Path, Path, dict]:
    launch_pack_path, setup_state_path, plan_path = _write_setup_handle_plan(root)
    template = template_generator.generate_completion_audit_setup_attestation_template(
        plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    template_path = root / "setup-attestation-template.json"
    _write_json(template_path, template)
    return launch_pack_path, setup_state_path, plan_path, template_path, template


def _first_option_per_check(template: dict) -> list[str]:
    result: list[str] = []
    for requirement in template["requirements"]:
        for check in requirement["setup_checks"]:
            result.append(check["attestation_spec_options"][0])
    return result


class GenerateCompletionAuditSetupAttestationFromTemplateTests(unittest.TestCase):
    def test_selected_template_option_writes_strict_attestation_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path, template = (
                _write_template(root)
            )
            attestation_path = root / "setup-attestation.json"
            patch_path = root / "setup-handle-patch.json"
            selected = _first_option_per_check(template)[:1]

            exit_code = generator.main(
                [
                    str(template_path),
                    "--setup-state",
                    str(setup_state_path),
                    "--setup-handle-plan",
                    str(plan_path),
                    "--launch-pack",
                    str(launch_pack_path),
                    "--select",
                    selected[0],
                    "--out",
                    str(attestation_path),
                    "--patch-out",
                    str(patch_path),
                ]
            )
            attestation = _load_json(attestation_path)
            validation = attestation_validator.validate_setup_attestation(
                attestation_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
                patch_path=patch_path,
            )

        self.assertEqual(0, exit_code)
        self.assertTrue(validation.ok, validation.to_dict())
        self.assertEqual(1, attestation["attestation_count"])
        self.assertEqual(selected[0].split("@", 1)[0].split("=", 1)[1], attestation["attestations"][0]["source_handle"])
        rendered = json.dumps(attestation, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_require_all_pending_accepts_one_selection_per_pending_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path, template = (
                _write_template(root)
            )
            selections = _first_option_per_check(template)

            attestation = generator.generate_completion_audit_setup_attestation_from_template(
                template_path,
                selections,
                setup_state_path=setup_state_path,
                setup_handle_plan_path=plan_path,
                launch_pack_path=launch_pack_path,
                require_all_pending=True,
            )

        self.assertEqual(template["pending_setup_check_count"], attestation["attestation_count"])

    def test_require_all_pending_rejects_partial_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path, template = (
                _write_template(root)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(template_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--setup-handle-plan",
                        str(plan_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--select",
                        _first_option_per_check(template)[0],
                        "--require-all-pending",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_from_template_incomplete_selection"],
            payload["error_codes"],
        )

    def test_rejects_selection_outside_template_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path, _template = (
                _write_template(root)
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(template_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--setup-handle-plan",
                        str(plan_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--select",
                        (
                            "autonomy-proactive-channel:external_setup_required:"
                            "approved_recipient=UNBOUND_HANDLE@"
                            "operator_approved_recipient:UNBOUND_HANDLE"
                        ),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_from_template_unknown_selection"],
            payload["error_codes"],
        )

    def test_rejects_multiple_selections_for_same_setup_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path, template_path, template = (
                _write_template(root)
            )
            multi_option_check = next(
                check
                for requirement in template["requirements"]
                for check in requirement["setup_checks"]
                if len(check["attestation_spec_options"]) > 1
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [
                        str(template_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--setup-handle-plan",
                        str(plan_path),
                        "--launch-pack",
                        str(launch_pack_path),
                        "--select",
                        multi_option_check["attestation_spec_options"][0],
                        "--select",
                        multi_option_check["attestation_spec_options"][1],
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_attestation_from_template_duplicate_check"],
            payload["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
