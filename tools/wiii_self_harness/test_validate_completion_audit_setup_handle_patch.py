import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from test_apply_completion_audit_setup_state import (
    _ready_patch_from_state,
    _write_setup_state,
)
from test_generate_completion_audit_run_plan import _write_json
from test_validate_completion_audit_setup_state import _load_json
import validate_completion_audit_setup_handle_patch as validator


def _write_patch(root: Path) -> tuple[Path, Path, Path]:
    launch_pack_path, setup_state_path = _write_setup_state(root)
    patch_path = root / "setup-handle-patch.json"
    _write_json(
        patch_path,
        _ready_patch_from_state(_load_json(setup_state_path), setup_state_path),
    )
    return launch_pack_path, setup_state_path, patch_path


class ValidateCompletionAuditSetupHandlePatchTests(unittest.TestCase):
    def test_valid_source_bound_patch_passes_with_setup_state_and_launch_pack(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, patch_path = _write_patch(root)

            result = validator.validate_setup_handle_patch(
                patch_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_stale_setup_state_source_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path, patch_path = _write_patch(root)
            payload = _load_json(patch_path)
            payload["setup_state_sha256"] = "0" * 64
            _write_json(patch_path, payload)

            result = validator.validate_setup_handle_patch(
                patch_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_patch_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_unknown_setup_check_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path, patch_path = _write_patch(root)
            payload = _load_json(patch_path)
            payload["checks"][0]["key"] = "unknown_setup_key"
            _write_json(patch_path, payload)

            result = validator.validate_setup_handle_patch(
                patch_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_patch_unknown_check",
            result.to_dict()["error_codes"],
        )

    def test_unbound_source_handle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path, patch_path = _write_patch(root)
            payload = _load_json(patch_path)
            payload["checks"][0]["source_handle"] = "UNBOUND_HANDLE"
            _write_json(patch_path, payload)

            result = validator.validate_setup_handle_patch(
                patch_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_patch_unbound_handle",
            result.to_dict()["error_codes"],
        )

    def test_raw_source_handle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path, patch_path = _write_patch(root)
            payload = _load_json(patch_path)
            payload["checks"][0]["source_handle"] = "<raw-recipient-id>"
            _write_json(patch_path, payload)

            result = validator.validate_setup_handle_patch(
                patch_path,
                setup_state_path=setup_state_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_handle_patch_check_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, patch_path = _write_patch(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(patch_path),
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
            validator.SETUP_HANDLE_PATCH_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(setup_state_path), payload["setup_state_path"])

    def test_cli_out_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, setup_state_path, patch_path = _write_patch(root)
            out_path = root / "validation-out"
            out_path.mkdir()
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = validator.main(
                    [
                        str(patch_path),
                        "--setup-state",
                        str(setup_state_path),
                        "--json",
                        "--out",
                        str(out_path),
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("report output path must not be a directory", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
