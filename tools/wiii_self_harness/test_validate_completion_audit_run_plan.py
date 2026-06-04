import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_run_plan as generator
from test_generate_completion_audit_run_plan import (
    _sample_readiness_payload,
    _write_json,
)
from test_validate_completion_audit_readiness import (
    _payload_with_preflight_next_action,
    _source_sha,
    _write_matching_proactive_preflight,
)
import validate_completion_audit_run_plan as validator


def _write_run_plan_markdown(root: Path, readiness_path: Path) -> Path:
    markdown_path = root / "run-plan.md"
    plan = generator.generate_completion_audit_run_plan(readiness_path)
    markdown_path.write_text(
        generator.format_markdown(plan).rstrip("\n") + "\n",
        encoding="utf-8",
    )
    return markdown_path


def _write_readiness_markdown(root: Path, payload: dict) -> Path:
    markdown_path = root / "readiness.md"
    markdown_path.write_text(
        validator.readiness_validator.format_markdown(
            validator.readiness_validator._report_from_payload(payload)
        ).rstrip("\n")
        + "\n",
        encoding="utf-8",
    )
    return markdown_path


class ValidateCompletionAuditRunPlanTests(unittest.TestCase):
    def test_valid_run_plan_passes_with_matching_readiness_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            plan = generator.generate_completion_audit_run_plan(readiness_path)
            _write_json(run_plan_path, plan.to_dict())

            result = validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_markdown_report_must_match_generated_run_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            plan = generator.generate_completion_audit_run_plan(readiness_path)
            _write_json(run_plan_path, plan.to_dict())
            markdown_path = _write_run_plan_markdown(root, readiness_path)

            result = validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_path,
                markdown_report_path=markdown_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_markdown_report_rejects_stale_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            plan = generator.generate_completion_audit_run_plan(readiness_path)
            _write_json(run_plan_path, plan.to_dict())
            markdown_path = _write_run_plan_markdown(root, readiness_path)
            markdown_path.write_text(
                markdown_path.read_text(encoding="utf-8").replace(
                    "autonomy-proactive-channel",
                    "stale-autonomy-proactive-channel",
                    1,
                ),
                encoding="utf-8",
            )

            result = validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_path,
                markdown_report_path=markdown_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_markdown_invalid",
            result.to_dict()["error_codes"],
        )

    def test_readiness_report_hash_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["readiness_report_sha256"] = "0" * 64
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_readiness_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_readiness_markdown_source_must_validate_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            payload = _sample_readiness_payload()
            _write_json(readiness_path, payload)
            run_plan = generator.generate_completion_audit_run_plan(readiness_path)
            _write_json(run_plan_path, run_plan.to_dict())
            readiness_markdown_path = _write_readiness_markdown(root, payload)
            readiness_markdown_path.write_text(
                readiness_markdown_path.read_text(encoding="utf-8").replace(
                    "autonomy-proactive-channel",
                    "stale-autonomy-proactive-channel",
                    1,
                ),
                encoding="utf-8",
            )

            result = validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_path,
                readiness_markdown_report_path=readiness_markdown_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_readiness_invalid",
            result.to_dict()["error_codes"],
        )

    def test_readiness_source_accepts_multiple_preflight_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            empty_dir = root / "empty"
            empty_dir.mkdir()
            preflight_dir = root / "preflight"
            _write_matching_proactive_preflight(preflight_dir)
            payload = _payload_with_preflight_next_action()
            source_path = preflight_dir / "proactive-channel-preflight.json"
            payload["preflight_summaries"][0]["source_file_sha256"] = _source_sha(
                source_path
            )
            _write_json(readiness_path, payload)
            run_plan = generator.generate_completion_audit_run_plan(readiness_path)
            _write_json(run_plan_path, run_plan.to_dict())

            result = validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_path,
                readiness_preflight_dirs=[empty_dir, preflight_dir],
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(
            [str(empty_dir), str(preflight_dir)],
            result.to_dict()["readiness_preflight_dirs"],
        )

    def test_run_items_fingerprint_must_match_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["run_items"][0]["title"] = "Operator supplied title"
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_run_items_fingerprint_must_bind_readiness_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["readiness_scoped_next_actions_fingerprint_sha256"] = "0" * 64
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_run_plan_fingerprint_helpers_bind_schema_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()

        current_run_items = validator._run_items_fingerprint(
            payload["run_items"],
            readiness_schema_version=payload["readiness_schema_version"],
            readiness_scoped_next_actions_fingerprint_sha256=payload[
                "readiness_scoped_next_actions_fingerprint_sha256"
            ],
        )
        self.assertEqual(payload["run_items_fingerprint_sha256"], current_run_items)
        self.assertNotEqual(
            current_run_items,
            validator._run_items_fingerprint(
                payload["run_items"],
                schema_version="wiii.completion_audit_run_plan.v2",
                readiness_schema_version=payload["readiness_schema_version"],
                readiness_scoped_next_actions_fingerprint_sha256=payload[
                    "readiness_scoped_next_actions_fingerprint_sha256"
                ],
            ),
        )
        self.assertNotEqual(
            current_run_items,
            validator._run_items_fingerprint(
                payload["run_items"],
                readiness_schema_version="wiii.completion_audit_readiness_report.v2",
                readiness_scoped_next_actions_fingerprint_sha256=payload[
                    "readiness_scoped_next_actions_fingerprint_sha256"
                ],
            ),
        )
        self.assertNotEqual(
            payload["operator_setup_fingerprint_sha256"],
            validator._operator_setup_fingerprint(
                payload["run_items"],
                schema_version="wiii.completion_audit_run_plan.v2",
            ),
        )
        self.assertNotEqual(
            payload["acceptance_contract_fingerprint_sha256"],
            validator._acceptance_contract_fingerprint(
                payload["run_items"],
                schema_version="wiii.completion_audit_run_plan.v2",
            ),
        )
        self.assertNotEqual(
            payload["post_run_verification_command_specs_fingerprint_sha256"],
            validator._verification_command_specs_fingerprint(
                payload["post_run_verification_command_specs"],
                schema_version="wiii.completion_audit_run_plan.v2",
            ),
        )

    def test_operator_setup_fingerprint_must_match_setup_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["run_items"][0]["required_operator_actions"][0]["instruction"] = (
                "Changed setup instruction"
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_setup_contract_must_match_preflight_required_next(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["run_items"][0]["preflight"]["setup_contract"][
                "required_next"
            ] = ["different_setup_hint"]
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_preflight_invalid",
            result.to_dict()["error_codes"],
        )

    def test_acceptance_contract_fingerprint_must_match_acceptance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["run_items"][0]["acceptance"]["accepted_when"].append(
                "operator added an untracked acceptance clause"
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_privacy_flags_must_remain_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["privacy"]["secret_values_included"] = True
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_privacy_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_must_use_preflight_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"] = [
                command.replace("<preflight-dir>", "artifacts")
                for command in payload["post_run_verification_commands"]
            ]
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_preflight_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_must_validate_regenerated_launch_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"] = [
                command
                for command in payload["post_run_verification_commands"]
                if "validate_completion_audit_launch_pack.py" not in command
            ]
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_must_validate_setup_state_and_dispatch_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"] = [
                command
                for command in payload["post_run_verification_commands"]
                if "completion_audit_setup_state.py" not in command
                and "completion_audit_dispatch_gate.py" not in command
            ]
            payload["post_run_verification_command_specs"] = [
                spec
                for spec in payload["post_run_verification_command_specs"]
                if "setup_state" not in spec["step_id"]
                and "dispatch_gate" not in spec["step_id"]
            ]
            payload["post_run_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_run_verification_command_specs"]
                )
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_must_validate_readiness_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"] = [
                command.replace(" --markdown-report <readiness-markdown>", "")
                if "validate_completion_audit_readiness.py" in command
                else command
                for command in payload["post_run_verification_commands"]
            ]
            for spec in payload["post_run_verification_command_specs"]:
                if spec["step_id"] == "validate_completion_audit_readiness":
                    spec["argv"] = [
                        arg
                        for arg in spec["argv"]
                        if arg not in {"--markdown-report", "<readiness-markdown>"}
                    ]
            payload["post_run_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_run_verification_command_specs"]
                )
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_readiness_verification_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_must_validate_readiness_self_harness_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"] = [
                command.replace(
                    " --self-harness-report-bundle "
                    "<downloaded-self-harness-reports-dir>",
                    "",
                )
                if "validate_completion_audit_readiness.py" in command
                else command
                for command in payload["post_run_verification_commands"]
            ]
            for spec in payload["post_run_verification_command_specs"]:
                if spec["step_id"] == "validate_completion_audit_readiness":
                    spec["argv"] = [
                        arg
                        for arg in spec["argv"]
                        if arg
                        not in {
                            "--self-harness-report-bundle",
                            "<downloaded-self-harness-reports-dir>",
                        }
                    ]
            payload["post_run_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_run_verification_command_specs"]
                )
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_readiness_verification_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_must_validate_run_plan_readiness_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"] = [
                command.replace(
                    " --readiness-markdown-report <readiness-markdown> "
                    "--readiness-preflight-dir <preflight-dir> "
                    "--self-harness-report-bundle "
                    "<downloaded-self-harness-reports-dir>",
                    "",
                )
                if "validate_completion_audit_run_plan.py" in command
                else command
                for command in payload["post_run_verification_commands"]
            ]
            for spec in payload["post_run_verification_command_specs"]:
                if spec["step_id"] == "validate_completion_audit_run_plan":
                    spec["argv"] = [
                        arg
                        for arg in spec["argv"]
                        if arg
                        not in {
                            "--readiness-markdown-report",
                            "<readiness-markdown>",
                            "--readiness-preflight-dir",
                            "<preflight-dir>",
                            "--self-harness-report-bundle",
                            "<downloaded-self-harness-reports-dir>",
                        }
                    ]
            payload["post_run_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_run_verification_command_specs"]
                )
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_readiness_verification_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_commands_must_keep_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            commands = payload["post_run_verification_commands"]
            commands[-2], commands[-1] = commands[-1], commands[-2]
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_commands_must_not_include_extra_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"].append(
                "python tools/wiii_self_harness/validate_completion_audit_run_plan.py "
                "<run-plan-json>"
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_commands_must_not_use_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"][0] += " ; echo unsafe"
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_command_unsafe",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_command_specs_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload.pop("post_run_verification_command_specs")
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_missing_required_fields",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_command_specs_must_not_use_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_command_specs"][0]["argv"].append(";")
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_command_unsafe",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_commands_must_match_specs_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_commands"][0] = (
                payload["post_run_verification_commands"][0].replace(
                    "--format json",
                    "--format markdown",
                )
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_post_run_verification_spec_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_run_verification_command_specs_fingerprint_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            payload = generator.generate_completion_audit_run_plan(
                readiness_path
            ).to_dict()
            payload["post_run_verification_command_specs"][0]["step_id"] = (
                "changed_step"
            )
            _write_json(run_plan_path, payload)

            result = validator.validate_run_plan(run_plan_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_run_plan_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())
            markdown_path = _write_run_plan_markdown(root, readiness_path)
            _write_json(
                run_plan_path,
                generator.generate_completion_audit_run_plan(readiness_path).to_dict(),
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(run_plan_path),
                        "--readiness-report",
                        str(readiness_path),
                        "--markdown-report",
                        str(markdown_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.RUN_PLAN_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(markdown_path), payload["markdown_report_path"])


if __name__ == "__main__":
    unittest.main()
