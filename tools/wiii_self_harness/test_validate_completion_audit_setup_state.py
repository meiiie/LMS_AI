import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_setup_state as setup_generator
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_state import _write_launch_pack
import validate_completion_audit_setup_state as validator


def _write_setup_state(root: Path) -> tuple[Path, Path]:
    launch_pack_path = _write_launch_pack(root)
    setup_state_path = root / "setup-state.json"
    state = setup_generator.generate_completion_audit_setup_state(launch_pack_path)
    _write_json(setup_state_path, state.to_dict())
    return launch_pack_path, setup_state_path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(path: Path, payload: dict) -> None:
    payload["setup_state_fingerprint_sha256"] = (
        setup_generator._setup_state_fingerprint(payload["requirements"])
    )
    _write_json(path, payload)


def _mark_ready(payload: dict) -> None:
    for requirement in payload["requirements"]:
        for check in requirement["setup_checks"]:
            check["present"] = True
            check["source_handle"] = check["binding_tokens"][0]
        requirement["dispatch_ready"] = True
        requirement["setup_status"] = "ready"
    payload["dispatch_ready"] = True
    payload["ready_requirement_count"] = payload["requirement_count"]
    payload["blocked_requirement_count"] = 0
    payload["setup_state_fingerprint_sha256"] = (
        setup_generator._setup_state_fingerprint(payload["requirements"])
    )


class ValidateCompletionAuditSetupStateTests(unittest.TestCase):
    def test_valid_pending_setup_state_passes_with_matching_launch_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))

            result = validator.validate_setup_state(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_ready_setup_state_passes_with_safe_source_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            _mark_ready(payload)
            _write_json(setup_state_path, payload)

            result = validator.validate_setup_state(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_present_check_requires_bound_source_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            check = payload["requirements"][0]["setup_checks"][0]
            check["present"] = True
            check["source_handle"] = "UNBOUND_HANDLE"
            _write_state(setup_state_path, payload)

            result = validator.validate_setup_state(setup_state_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_check_invalid",
            result.to_dict()["error_codes"],
        )

    def test_absent_check_requires_empty_source_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            check = payload["requirements"][0]["setup_checks"][0]
            check["source_handle"] = check["binding_tokens"][0]
            _write_state(setup_state_path, payload)

            result = validator.validate_setup_state(setup_state_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_check_invalid",
            result.to_dict()["error_codes"],
        )

    def test_setup_check_privacy_flags_must_remain_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            check = payload["requirements"][0]["setup_checks"][0]
            check["secret_value_included"] = True
            check["raw_identifier_included"] = True
            _write_state(setup_state_path, payload)

            result = validator.validate_setup_state(setup_state_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_privacy_invalid",
            result.to_dict()["error_codes"],
        )

    def test_source_handle_must_be_safe_token_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            check = payload["requirements"][0]["setup_checks"][0]
            check["present"] = True
            check["source_handle"] = "<raw-recipient-id>"
            _write_state(setup_state_path, payload)

            result = validator.validate_setup_state(setup_state_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_check_invalid",
            result.to_dict()["error_codes"],
        )

    def test_launch_pack_source_hash_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            payload["launch_pack_sha256"] = "0" * 64
            _write_json(setup_state_path, payload)

            result = validator.validate_setup_state(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_launch_pack_source_rejects_dropped_setup_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            payload["requirements"][0]["setup_checks"].pop()
            _write_state(setup_state_path, payload)

            result = validator.validate_setup_state(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_launch_pack_source_rejects_changed_binding_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path, setup_state_path = _write_setup_state(Path(temp_dir))
            payload = _load_json(setup_state_path)
            payload["requirements"][0]["setup_checks"][0]["binding_tokens"] = [
                "UNBOUND_HANDLE"
            ]
            _write_state(setup_state_path, payload)

            result = validator.validate_setup_state(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_setup_state_source_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path = _write_setup_state(root)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
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
            validator.SETUP_STATE_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(launch_pack_path), payload["launch_pack_path"])


if __name__ == "__main__":
    unittest.main()
