import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_launch_pack as launch_generator
from test_generate_completion_audit_launch_pack import _write_run_plan
from test_generate_completion_audit_run_plan import _write_json
import validate_completion_audit_launch_pack as validator


def _write_launch_pack(root: Path) -> tuple[Path, Path]:
    run_plan_path = _write_run_plan(root)
    launch_pack_path = root / "launch-pack.json"
    pack = launch_generator.generate_completion_audit_launch_pack(run_plan_path)
    _write_json(launch_pack_path, pack.to_dict())
    return run_plan_path, launch_pack_path


def _write_launch_pack_markdown(root: Path, run_plan_path: Path) -> Path:
    markdown_path = root / "launch-pack.md"
    exit_code = launch_generator.main(
        [
            str(run_plan_path),
            "--format",
            "markdown",
            "--out",
            str(markdown_path),
        ]
    )
    if exit_code != 0:
        raise AssertionError("launch-pack markdown generation failed")
    return markdown_path


def _write_repo_sources(repo_root: Path, launch_payload: dict) -> None:
    required_handle_field = next(
        key
        for key in launch_payload["launch_items"][0]
        if key.startswith("required_github_")
        and key not in {"required_github_inputs", "required_github_vars"}
    )
    conditional_handle_field = next(
        key
        for key in launch_payload["launch_items"][0]
        if key.startswith("conditional_github_")
    )
    for item in launch_payload["launch_items"]:
        workflow_path = repo_root / item["workflow"]
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_required_handles = [
            *item["required_github_inputs"],
            *item["required_github_vars"],
            *item[required_handle_field],
            *item[conditional_handle_field],
            *item["artifact_tokens"],
            *item["diagnostic_artifact_tokens"],
            item["expected_artifact"],
        ]
        workflow_path.write_text("\n".join(workflow_required_handles), encoding="utf-8")
        probe_path = repo_root / item["probe"]
        probe_path.parent.mkdir(parents=True, exist_ok=True)
        probe_path.write_text("# probe placeholder\n", encoding="utf-8")


class ValidateCompletionAuditLaunchPackTests(unittest.TestCase):
    def test_valid_launch_pack_passes_with_matching_run_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_markdown_report_must_match_generated_launch_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            markdown_path = _write_launch_pack_markdown(root, run_plan_path)

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
                markdown_report_path=markdown_path,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual([], result.to_dict()["error_codes"])

    def test_markdown_report_rejects_stale_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            markdown_path = _write_launch_pack_markdown(root, run_plan_path)
            markdown_path.write_text(
                markdown_path.read_text(encoding="utf-8").replace(
                    "autonomy-proactive-channel",
                    "stale-autonomy-proactive-channel",
                    1,
                ),
                encoding="utf-8",
            )

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
                markdown_report_path=markdown_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_markdown_invalid",
            result.to_dict()["error_codes"],
        )

    def test_run_plan_hash_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["run_plan_sha256"] = "0" * 64
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_run_plan_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_run_plan_acceptance_fingerprint_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["run_plan_acceptance_contract_fingerprint_sha256"] = "0" * 64
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_run_plan_setup_fingerprint_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["run_plan_operator_setup_fingerprint_sha256"] = "0" * 64
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_run_plan_verification_fingerprint_must_match_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload[
                "run_plan_post_run_verification_command_specs_fingerprint_sha256"
            ] = "0" * 64
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_launch_item_fingerprint_must_match_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["title"] = "Operator supplied title"
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_launch_item_fingerprint_must_bind_run_plan_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["run_plan_run_items_fingerprint_sha256"] = "0" * 64
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_launch_fingerprint_helpers_bind_schema_and_run_plan_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))

        current_items = validator._launch_items_fingerprint(
            payload["launch_items"],
            run_plan_schema_version=payload["run_plan_schema_version"],
            run_plan_run_items_fingerprint_sha256=payload[
                "run_plan_run_items_fingerprint_sha256"
            ],
            run_plan_operator_setup_fingerprint_sha256=payload[
                "run_plan_operator_setup_fingerprint_sha256"
            ],
            run_plan_acceptance_contract_fingerprint_sha256=payload[
                "run_plan_acceptance_contract_fingerprint_sha256"
            ],
        )
        self.assertEqual(payload["launch_items_fingerprint_sha256"], current_items)
        self.assertNotEqual(
            current_items,
            validator._launch_items_fingerprint(
                payload["launch_items"],
                schema_version="wiii.completion_audit_launch_pack.v2",
                run_plan_schema_version=payload["run_plan_schema_version"],
                run_plan_run_items_fingerprint_sha256=payload[
                    "run_plan_run_items_fingerprint_sha256"
                ],
                run_plan_operator_setup_fingerprint_sha256=payload[
                    "run_plan_operator_setup_fingerprint_sha256"
                ],
                run_plan_acceptance_contract_fingerprint_sha256=payload[
                    "run_plan_acceptance_contract_fingerprint_sha256"
                ],
            ),
        )
        self.assertNotEqual(
            current_items,
            validator._launch_items_fingerprint(
                payload["launch_items"],
                run_plan_schema_version="wiii.completion_audit_run_plan.v2",
                run_plan_run_items_fingerprint_sha256=payload[
                    "run_plan_run_items_fingerprint_sha256"
                ],
                run_plan_operator_setup_fingerprint_sha256=payload[
                    "run_plan_operator_setup_fingerprint_sha256"
                ],
                run_plan_acceptance_contract_fingerprint_sha256=payload[
                    "run_plan_acceptance_contract_fingerprint_sha256"
                ],
            ),
        )
        self.assertNotEqual(
            payload["launch_setup_fingerprint_sha256"],
            validator._launch_setup_fingerprint(
                payload["launch_items"],
                run_plan_operator_setup_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            payload["launch_acceptance_fingerprint_sha256"],
            validator._launch_acceptance_fingerprint(
                payload["launch_items"],
                run_plan_acceptance_contract_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            payload["launch_command_specs_fingerprint_sha256"],
            validator._launch_command_specs_fingerprint(
                payload["launch_items"],
                run_plan_run_items_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            payload["post_launch_verification_command_specs_fingerprint_sha256"],
            validator._verification_command_specs_fingerprint(
                payload["post_launch_verification_command_specs"],
                run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                    "0" * 64
                ),
            ),
        )

    def test_launch_setup_fingerprint_must_match_setup_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["required_github_vars"].append(
                "WIII_ADDED_SETUP_VAR"
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_privacy_flags_must_remain_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["privacy"]["raw_identifiers_included"] = True
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_privacy_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_must_use_preflight_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"] = [
                command.replace("<preflight-dir>", "artifacts")
                for command in payload["post_launch_verification_commands"]
            ]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_must_validate_regenerated_launch_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"] = [
                command
                for command in payload["post_launch_verification_commands"]
                if "validate_completion_audit_launch_pack.py" not in command
            ]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_must_validate_setup_state_and_dispatch_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"] = [
                command
                for command in payload["post_launch_verification_commands"]
                if "completion_audit_setup_state.py" not in command
                and "completion_audit_dispatch_gate.py" not in command
            ]
            payload["post_launch_verification_command_specs"] = [
                spec
                for spec in payload["post_launch_verification_command_specs"]
                if "setup_state" not in spec["step_id"]
                and "dispatch_gate" not in spec["step_id"]
            ]
            payload["post_launch_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_launch_verification_command_specs"],
                    run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                        payload[
                            "run_plan_post_run_verification_command_specs_fingerprint_sha256"
                        ]
                    ),
                )
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_must_validate_readiness_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"] = [
                command.replace(" --markdown-report <readiness-markdown>", "")
                if "validate_completion_audit_readiness.py" in command
                else command
                for command in payload["post_launch_verification_commands"]
            ]
            for spec in payload["post_launch_verification_command_specs"]:
                if spec["step_id"] == "validate_completion_audit_readiness":
                    spec["argv"] = [
                        arg
                        for arg in spec["argv"]
                        if arg not in {"--markdown-report", "<readiness-markdown>"}
                    ]
            payload["post_launch_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_launch_verification_command_specs"],
                    run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                        payload[
                            "run_plan_post_run_verification_command_specs_fingerprint_sha256"
                        ]
                    ),
                )
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_must_validate_readiness_self_harness_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"] = [
                command.replace(
                    " --self-harness-report-bundle "
                    "<downloaded-self-harness-reports-dir>",
                    "",
                )
                if "validate_completion_audit_readiness.py" in command
                else command
                for command in payload["post_launch_verification_commands"]
            ]
            for spec in payload["post_launch_verification_command_specs"]:
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
            payload["post_launch_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_launch_verification_command_specs"],
                    run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                        payload[
                            "run_plan_post_run_verification_command_specs_fingerprint_sha256"
                        ]
                    ),
                )
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_must_validate_run_plan_readiness_sources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"] = [
                command.replace(
                    " --readiness-markdown-report <readiness-markdown> "
                    "--readiness-preflight-dir <preflight-dir> "
                    "--self-harness-report-bundle "
                    "<downloaded-self-harness-reports-dir>",
                    "",
                )
                if "validate_completion_audit_run_plan.py" in command
                else command
                for command in payload["post_launch_verification_commands"]
            ]
            for spec in payload["post_launch_verification_command_specs"]:
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
            payload["post_launch_verification_command_specs_fingerprint_sha256"] = (
                validator._verification_command_specs_fingerprint(
                    payload["post_launch_verification_command_specs"],
                    run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                        payload[
                            "run_plan_post_run_verification_command_specs_fingerprint_sha256"
                        ]
                    ),
                )
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_commands_must_keep_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            commands = payload["post_launch_verification_commands"]
            commands[-2], commands[-1] = commands[-1], commands[-2]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_commands_must_not_include_extra_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"].append(
                "python tools/wiii_self_harness/validate_completion_audit_launch_pack.py "
                "<launch-pack-json>"
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_order_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_commands_must_not_use_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"][0] += " ; echo unsafe"
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_command_unsafe",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_command_specs_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload.pop("post_launch_verification_command_specs")
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_missing_required_fields",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_command_specs_must_not_use_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_command_specs"][0]["argv"].append(";")
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_command_unsafe",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_commands_must_match_specs_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_commands"][0] = (
                payload["post_launch_verification_commands"][0].replace(
                    "--format json",
                    "--format markdown",
                )
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_post_launch_verification_spec_invalid",
            result.to_dict()["error_codes"],
        )

    def test_post_launch_verification_command_specs_fingerprint_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["post_launch_verification_command_specs"][0]["step_id"] = (
                "changed_step"
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_workflow_dispatch_must_bind_required_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            commands = payload["launch_items"][0]["commands"]
            commands["workflow_dispatch"] = commands["workflow_dispatch"].replace(
                " -f proactive_recipient_id=<approved-recipient-id>",
                "",
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_validate_preflight_must_match_local_preflight_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            commands = payload["launch_items"][0]["commands"]
            commands["validate_preflight"] = commands["validate_preflight"].replace(
                "maritime-ai-service/autonomy-proactive-channel-preflight.json",
                "maritime-ai-service/other-preflight.json",
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_command_templates_must_not_use_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            commands = payload["launch_items"][0]["commands"]
            commands["local_preflight"] += " && echo unsafe"
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_unsafe",
            result.to_dict()["error_codes"],
        )

    def test_command_specs_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0].pop("command_specs")
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_command_specs_must_not_use_shell_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            spec = payload["launch_items"][0]["command_specs"]["local_live_probe"]
            spec["argv"].append(";")
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_unsafe",
            result.to_dict()["error_codes"],
        )

    def test_command_templates_must_match_command_specs_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            commands = payload["launch_items"][0]["commands"]
            commands["local_live_probe"] = commands["local_live_probe"].replace(
                "--organization-id autonomy-runtime-evidence",
                "--organization-id other-org",
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_command_specs_must_match_local_probe_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            spec = payload["launch_items"][0]["command_specs"]["local_live_probe"]
            out_index = spec["argv"].index("--out") + 1
            spec["argv"][out_index] = "wrong-artifact.json"
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_failure_from_preflight_must_bind_preflight_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            spec = payload["launch_items"][0]["command_specs"][
                "local_failure_from_preflight"
            ]
            flag_index = spec["argv"].index("--failure-preflight-json")
            del spec["argv"][flag_index : flag_index + 2]
            payload["launch_items"][0]["commands"][
                "local_failure_from_preflight"
            ] = " ".join(spec["argv"])
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_failure_from_preflight_must_write_expected_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            spec = payload["launch_items"][0]["command_specs"][
                "local_failure_from_preflight"
            ]
            out_index = spec["argv"].index("--out") + 1
            spec["argv"][out_index] = "wrong-artifact.json"
            payload["launch_items"][0]["commands"][
                "local_failure_from_preflight"
            ] = " ".join(spec["argv"])
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_command_invalid",
            result.to_dict()["error_codes"],
        )

    def test_launch_command_specs_fingerprint_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            spec = payload["launch_items"][0]["command_specs"]["local_live_probe"]
            spec["argv"].append("--extra-placeholder")
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_acceptance_checks_must_include_bundle_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["acceptance_checks"] = [
                check
                for check in payload["launch_items"][0]["acceptance_checks"]
                if "validate_runtime_evidence_bundle.py" not in check
            ]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_acceptance_invalid",
            result.to_dict()["error_codes"],
        )

    def test_launch_acceptance_fingerprint_must_match_acceptance_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["acceptance_checks"].append(
                "operator added an untracked acceptance clause"
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_fingerprint_invalid",
            result.to_dict()["error_codes"],
        )

    def test_operator_actions_must_cover_preflight_required_next(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["required_operator_action_tokens"].remove(
                "configure_selected_channel_credential"
            )
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_operator_requirements_invalid",
            result.to_dict()["error_codes"],
        )

    def test_operator_actions_must_include_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["required_operator_actions"][0]["instruction"] = ""
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_operator_requirements_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_provenance_must_be_validated_when_setup_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["preflight_source_validation_ok"] = False
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_preflight_provenance_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_setup_contract_must_match_required_next(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["preflight_setup_contract"][
                "required_next"
            ] = ["different_setup_hint"]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_preflight_provenance_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_setup_contract_bindings_must_cover_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            del payload["launch_items"][0]["preflight_setup_contract_bindings"][
                "credential_slots_required"
            ]["selected_channel_credential"]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_preflight_provenance_invalid",
            result.to_dict()["error_codes"],
        )

    def test_preflight_setup_contract_bindings_must_reference_launch_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_plan_path, launch_pack_path = _write_launch_pack(Path(temp_dir))
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            payload["launch_items"][0]["preflight_setup_contract_bindings"][
                "credential_slots_required"
            ]["selected_channel_credential"] = ["UNBOUND_SECRET_HANDLE"]
            _write_json(launch_pack_path, payload)

            result = validator.validate_launch_pack(launch_pack_path)

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_preflight_provenance_invalid",
            result.to_dict()["error_codes"],
        )

    def test_repo_root_validates_workflow_and_probe_source_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            repo_root = root / "repo"
            _write_repo_sources(repo_root, payload)

            result = validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
                repo_root=repo_root,
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_repo_root_rejects_workflow_token_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _run_plan_path, launch_pack_path = _write_launch_pack(root)
            payload = json.loads(launch_pack_path.read_text(encoding="utf-8"))
            repo_root = root / "repo"
            _write_repo_sources(repo_root, payload)
            workflow_path = repo_root / payload["launch_items"][0]["workflow"]
            workflow_path.write_text(
                workflow_path.read_text(encoding="utf-8").replace(
                    "TELEGRAM_BOT_TOKEN",
                    "",
                ),
                encoding="utf-8",
            )

            result = validator.validate_launch_pack(
                launch_pack_path,
                repo_root=repo_root,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "completion_audit_launch_pack_repo_source_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_reports_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path, launch_pack_path = _write_launch_pack(root)
            markdown_path = _write_launch_pack_markdown(root, run_plan_path)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(launch_pack_path),
                        "--run-plan",
                        str(run_plan_path),
                        "--repo-root",
                        str(Path.cwd()),
                        "--markdown-report",
                        str(markdown_path),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(
            validator.LAUNCH_PACK_VALIDATION_SCHEMA_VERSION,
            payload["validation_schema_version"],
        )
        self.assertEqual(str(markdown_path), payload["markdown_report_path"])


if __name__ == "__main__":
    unittest.main()
