import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_handle_plan as generator
from test_generate_completion_audit_dispatch_gate import _write_setup_state
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_handle_plan as validator


def _write_plan(root: Path) -> tuple[Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root)
    plan_path = root / "setup-handle-plan.json"
    plan = generator.generate_completion_audit_setup_handle_plan(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    _write_json(plan_path, plan.to_dict())
    return launch_pack_path, setup_state_path, plan_path


class ValidateCompletionAuditSetupHandlePlanTests(unittest.TestCase):
    def test_valid_plan_passes_with_setup_state_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)

            result = validator.validate_setup_handle_plan(
                plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_fingerprint_must_match_plan_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            payload = _load_json(plan_path)
            payload["plan_items"][0]["setup_checks"][0]["recommended_handle_specs"].append(
                "extra:credential_slots_required:token=HANDLE"
            )
            _write_json(plan_path, payload)

            result = validator.validate_setup_handle_plan(plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_source_parity_rejects_stale_plan_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            payload = _load_json(plan_path)
            payload["plan_items"][0]["setup_checks"][0][
                "recommended_handle_specs"
            ] = []
            payload["setup_handle_plan_fingerprint_sha256"] = (
                generator._setup_handle_plan_fingerprint(payload["plan_items"])
            )
            _write_json(plan_path, payload)

            result = validator.validate_setup_handle_plan(
                plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_plan_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_pending_check_requires_attestation_spec_for_each_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            payload = _load_json(plan_path)
            payload["plan_items"][0]["setup_checks"][0][
                "recommended_attestation_specs"
            ] = []
            payload["setup_handle_plan_fingerprint_sha256"] = (
                generator._setup_handle_plan_fingerprint(payload["plan_items"])
            )
            _write_json(plan_path, payload)

            result = validator.validate_setup_handle_plan(plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_plan_check_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
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
            validator.SETUP_HANDLE_PLAN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(setup_state_path), payload["setup_state_path"])


if __name__ == "__main__":
    unittest.main()
