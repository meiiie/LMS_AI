import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_launch_pack as launch_generator
import generate_completion_audit_setup_state as setup_generator
from test_generate_completion_audit_launch_pack import _write_run_plan
from test_generate_completion_audit_run_plan import _write_json


def _write_launch_pack(root: Path) -> Path:
    run_plan_path = _write_run_plan(root)
    launch_pack_path = root / "launch-pack.json"
    pack = launch_generator.generate_completion_audit_launch_pack(run_plan_path)
    _write_json(launch_pack_path, pack.to_dict())
    return launch_pack_path


class GenerateCompletionAuditSetupStateTests(unittest.TestCase):
    def test_generate_setup_state_writes_pending_template_without_secret_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path = _write_launch_pack(Path(temp_dir))

            state = setup_generator.generate_completion_audit_setup_state(
                launch_pack_path
            )
            payload = state.to_dict()

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            setup_generator.SETUP_STATE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertFalse(payload["dispatch_ready"])
        self.assertEqual(2, payload["requirement_count"])
        self.assertEqual(0, payload["ready_requirement_count"])
        self.assertEqual(2, payload["blocked_requirement_count"])
        self.assertRegex(payload["launch_pack_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            payload["setup_state_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            {
                "secret_values_included": False,
                "credential_values_included": False,
                "raw_identifiers_included": False,
            },
            payload["privacy"],
        )
        proactive = payload["requirements"][0]
        self.assertEqual("autonomy-proactive-channel", proactive["requirement_id"])
        self.assertEqual("pending", proactive["setup_status"])
        self.assertFalse(proactive["dispatch_ready"])
        credential_check = next(
            check
            for check in proactive["setup_checks"]
            if check["category"] == "credential_slots_required"
            and check["key"] == "selected_channel_credential"
        )
        self.assertIn("TELEGRAM_BOT_TOKEN", credential_check["binding_tokens"])
        self.assertFalse(credential_check["present"])
        self.assertEqual("", credential_check["source_handle"])
        self.assertFalse(credential_check["secret_value_included"])
        self.assertFalse(credential_check["raw_identifier_included"])
        rendered = json.dumps(payload, sort_keys=True)
        self.assertNotIn("secret-access-token", rendered)
        self.assertNotIn("<approved-recipient-id>", rendered)

    def test_generate_with_repo_root_marks_only_repo_proven_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            launch_pack_path = _write_launch_pack(Path(temp_dir))

            state = setup_generator.generate_completion_audit_setup_state(
                launch_pack_path,
                repo_root=Path.cwd(),
            )
            payload = state.to_dict()

        self.assertFalse(payload["dispatch_ready"])
        self.assertEqual(0, payload["ready_requirement_count"])
        self.assertEqual(2, payload["blocked_requirement_count"])
        setup_checks = [
            check
            for requirement in payload["requirements"]
            for check in requirement["setup_checks"]
        ]
        ready_checks = [check for check in setup_checks if check["present"]]
        pending_checks = [check for check in setup_checks if not check["present"]]
        self.assertEqual(12, len(ready_checks))
        self.assertEqual(10, len(pending_checks))

        proactive = payload["requirements"][0]
        allow_send = next(
            check
            for check in proactive["setup_checks"]
            if check["category"] == "workflow_inputs_required"
            and check["key"] == "allow_send"
        )
        proactive_flag = next(
            check
            for check in proactive["setup_checks"]
            if check["category"] == "environment_flags_required"
        )
        credential_check = next(
            check
            for check in proactive["setup_checks"]
            if check["category"] == "credential_slots_required"
        )
        approved_recipient = next(
            check
            for check in proactive["setup_checks"]
            if check["category"] == "external_setup_required"
            and check["key"] == "approved_recipient"
        )

        self.assertTrue(allow_send["present"])
        self.assertEqual("run_proactive_channel", allow_send["source_handle"])
        self.assertFalse(proactive_flag["present"])
        self.assertEqual("", proactive_flag["source_handle"])
        self.assertIn(
            "WIII_LIVE_PROACTIVE_CHANNEL_PROBE",
            proactive_flag["binding_tokens"],
        )
        self.assertFalse(credential_check["present"])
        self.assertEqual("", credential_check["source_handle"])
        self.assertFalse(approved_recipient["present"])
        self.assertEqual("", approved_recipient["source_handle"])

        composio = payload["requirements"][1]
        expect_connected = next(
            check
            for check in composio["setup_checks"]
            if check["category"] == "workflow_inputs_required"
            and check["key"] == "expect_connected"
        )
        composio_flag = next(
            check
            for check in composio["setup_checks"]
            if check["category"] == "environment_flags_required"
        )
        self.assertTrue(expect_connected["present"])
        self.assertEqual("--expect-connected", expect_connected["source_handle"])
        self.assertFalse(composio_flag["present"])
        self.assertEqual("", composio_flag["source_handle"])
        self.assertIn(
            "WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE",
            composio_flag["binding_tokens"],
        )

    def test_cli_writes_setup_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path = _write_launch_pack(root)
            out_path = root / "setup-state.json"

            exit_code = setup_generator.main(
                [str(launch_pack_path), "--out", str(out_path)]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual(
            setup_generator.SETUP_STATE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual(2, payload["blocked_requirement_count"])

    def test_cli_accepts_repo_root_for_repo_proven_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path = _write_launch_pack(root)
            out_path = root / "setup-state.json"

            exit_code = setup_generator.main(
                [
                    str(launch_pack_path),
                    "--repo-root",
                    str(Path.cwd()),
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertFalse(payload["dispatch_ready"])
        self.assertEqual(2, payload["blocked_requirement_count"])
        ready_checks = [
            check
            for requirement in payload["requirements"]
            for check in requirement["setup_checks"]
            if check["present"]
        ]
        self.assertEqual(12, len(ready_checks))

    def test_cli_reports_invalid_launch_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["privacy"]["secret_values_included"] = True
            _write_json(launch_pack_path, payload)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = setup_generator.main([str(launch_pack_path)])
            output = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(output["ok"])
        self.assertEqual(
            ["completion_audit_setup_state_launch_pack_invalid"],
            output["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
