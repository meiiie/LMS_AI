import contextlib
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_launch_pack as launch_generator
import generate_completion_audit_run_plan as run_plan_generator
from test_generate_completion_audit_run_plan import (
    _sample_readiness_payload,
    _write_json,
)
import validate_completion_audit_readiness as readiness_validator


def _lms_run_plan_item() -> dict:
    required_next = [
        "pass_allow_write",
        "pass_allow_external_lms_write",
        "set_live_lms_test_course_replay_flag",
        "configure_external_lms_apply_url",
        "configure_external_lms_apply_token",
    ]
    return {
        "requirement_id": "lms-test-course-replay",
        "title": "LMS test-course preview/apply replay evidence",
        "current_status": "missing",
        "artifact": "lms-test-course-evidence.json",
        "evidence_schema_version": "wiii.live_lms_test_course_replay.v1",
        "probe": "maritime-ai-service/scripts/probe_live_lms_test_course_replay.py",
        "workflow_execution": {
            "workflow": ".github/workflows/lms-test-course-evidence.yml",
            "artifact_tokens": ["lms-test-course-evidence-${{ github.run_id }}"],
            "diagnostic_artifact_tokens": [
                "lms-test-course-preflight-${{ github.run_id }}"
            ],
        },
        "preflight": {
            "status": "fail",
            "schema_version": "wiii.lms_test_course_preflight.v1",
            "generated_at": "2026-06-02T12:00:00+00:00",
            "required_next": required_next,
            "source_file": "lms-test-course-preflight.json",
            "source_file_sha256": "c" * 64,
            "source_validation_schema_version": (
                "wiii.runtime_evidence_preflight_validation.v1"
            ),
            "source_validation_ok": True,
            "source_validation_error_codes": [],
            "raw_payload_included": False,
            "setup_contract": {
                "version": "wiii.live_evidence_setup_contract.v1",
                "requirement_id": "lms-test-course-replay",
                "required_next": required_next,
                "workflow_inputs_required": [
                    "run_lms_replay",
                    "transport_mode",
                    "base_url",
                    "allow_write",
                    "allow_external_lms_write",
                    "allow_production",
                ],
                "environment_flags_required": [
                    "live_lms_test_course_replay_flag"
                ],
                "credential_slots_required": [
                    "external_lms_apply_token",
                    "lms_backend_bearer_token",
                ],
                "external_setup_required": [
                    "external_lms_apply_endpoint",
                    "staging_or_local_backend",
                ],
                "dispatch_ready": False,
            },
        },
        "required_operator_actions": [
            {
                "token": token,
                "category": "operator_input",
                "instruction": "Satisfy this LMS preflight requirement.",
            }
            for token in required_next
        ],
        "acceptance": {
            "accepted_when": [
                "the expected artifact exists in the downloaded runtime evidence bundle",
                "the artifact schema_version matches expected_schema_version",
                "validate_runtime_evidence_bundle.py passes the registered row checks",
                "the regenerated scoped readiness report no longer lists this requirement as missing or failed",
            ],
        },
    }


def _write_run_plan(root: Path) -> Path:
    readiness_path = root / "readiness.json"
    run_plan_path = root / "run-plan.json"
    _write_json(readiness_path, _sample_readiness_payload())
    run_plan = run_plan_generator.generate_completion_audit_run_plan(readiness_path)
    _write_json(run_plan_path, run_plan.to_dict())
    return run_plan_path


class GenerateCompletionAuditLaunchPackTests(unittest.TestCase):
    def test_lms_launch_item_wires_preflight_and_failure_diagnostics(self) -> None:
        item = launch_generator._build_lms_test_course_launch_item(
            _lms_run_plan_item()
        )
        payload = asdict(item)

        self.assertEqual("lms-test-course-replay", payload["requirement_id"])
        self.assertEqual(
            "lms-test-course-preflight.json",
            payload["preflight_source_file"],
        )
        self.assertIn(
            "lms-test-course-preflight-<run-id>",
            payload["commands"]["download_preflight_artifact"],
        )
        self.assertIn("--preflight-only", payload["commands"]["local_preflight"])
        self.assertIn(
            "--failure-from-preflight",
            payload["commands"]["local_failure_from_preflight"],
        )
        self.assertIn(
            "lms-test-course-preflight.json",
            payload["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertEqual(
            ["WIII_LMS_TEST_COURSE_APPLY_TOKEN"],
            payload["preflight_setup_contract_bindings"][
                "credential_slots_required"
            ]["external_lms_apply_token"],
        )
        self.assertIn(
            "WIII_LMS_TEST_COURSE_APPLY_URL",
            payload["preflight_setup_contract_bindings"][
                "external_setup_required"
            ]["external_lms_apply_endpoint"],
        )
        self.assertNotIn(
            "WIII_LMS_TEST_COURSE_APPLY_TOKEN",
            json.dumps(payload["preflight_setup_contract"], sort_keys=True),
        )

    def test_launch_pack_defaults_setup_contract_when_preflight_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_plan_path = _write_run_plan(Path(temp_dir))
            run_plan_payload = json.loads(run_plan_path.read_text(encoding="utf-8"))
            launch_items = []
            for item in run_plan_payload["run_items"]:
                item["preflight"]["setup_contract"] = {}
                builder = launch_generator.LAUNCH_CONTRACT_BUILDERS[
                    item["requirement_id"]
                ]
                launch_items.append(asdict(builder(item)))

        self.assertTrue(launch_items)
        for item in launch_items:
            self.assertEqual(
                "wiii.live_evidence_setup_contract.v1",
                item["preflight_setup_contract"]["version"],
            )
            self.assertEqual(
                item["requirement_id"],
                item["preflight_setup_contract"]["requirement_id"],
            )
            self.assertTrue(item["preflight_setup_contract_bindings"])
            rendered_contract = json.dumps(
                item["preflight_setup_contract"],
                sort_keys=True,
            )
            self.assertNotIn("TELEGRAM_BOT_TOKEN", rendered_contract)
            self.assertNotIn("WIII_ACCEPTANCE_BEARER_TOKEN", rendered_contract)

    def test_generate_launch_pack_writes_command_templates_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_plan_path = _write_run_plan(Path(temp_dir))

            pack = launch_generator.generate_completion_audit_launch_pack(run_plan_path)
            payload = pack.to_dict()
            markdown = launch_generator.format_markdown(pack)
            run_plan_payload = json.loads(run_plan_path.read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(2, payload["launch_item_count"])
        self.assertEqual(0, payload["unsupported_run_item_count"])
        self.assertEqual(
            run_plan_payload["operator_setup_fingerprint_sha256"],
            payload["run_plan_operator_setup_fingerprint_sha256"],
        )
        self.assertRegex(
            payload["run_plan_operator_setup_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            run_plan_payload["acceptance_contract_fingerprint_sha256"],
            payload["run_plan_acceptance_contract_fingerprint_sha256"],
        )
        self.assertRegex(
            payload["run_plan_acceptance_contract_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            run_plan_payload[
                "post_run_verification_command_specs_fingerprint_sha256"
            ],
            payload[
                "run_plan_post_run_verification_command_specs_fingerprint_sha256"
            ],
        )
        self.assertRegex(
            payload[
                "run_plan_post_run_verification_command_specs_fingerprint_sha256"
            ],
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(
            payload["launch_acceptance_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(
            payload["launch_setup_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(
            payload["launch_command_specs_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertFalse(payload["privacy"]["secret_values_included"])
        proactive = payload["launch_items"][0]
        self.assertEqual("autonomy-proactive-channel", proactive["requirement_id"])
        self.assertEqual("fail", proactive["preflight_status"])
        self.assertEqual("a" * 64, proactive["preflight_source_file_sha256"])
        self.assertEqual(
            "wiii.runtime_evidence_preflight_validation.v1",
            proactive["preflight_source_validation_schema_version"],
        )
        self.assertTrue(proactive["preflight_source_validation_ok"])
        self.assertEqual([], proactive["preflight_source_validation_error_codes"])
        self.assertFalse(proactive["preflight_raw_payload_included"])
        self.assertEqual(
            "wiii.live_evidence_setup_contract.v1",
            proactive["preflight_setup_contract"]["version"],
        )
        self.assertEqual(
            ["selected_channel_credential"],
            proactive["preflight_setup_contract"]["credential_slots_required"],
        )
        self.assertNotIn(
            "TELEGRAM_BOT_TOKEN",
            json.dumps(proactive["preflight_setup_contract"], sort_keys=True),
        )
        self.assertEqual(
            [
                "TELEGRAM_BOT_TOKEN",
                "FACEBOOK_PAGE_ACCESS_TOKEN",
                "ZALO_OA_ACCESS_TOKEN",
            ],
            proactive["preflight_setup_contract_bindings"][
                "credential_slots_required"
            ]["selected_channel_credential"],
        )
        self.assertIn(
            "proactive_recipient_id",
            proactive["preflight_setup_contract_bindings"][
                "external_setup_required"
            ]["approved_recipient"],
        )
        self.assertIn(
            "run_proactive_channel=true",
            proactive["commands"]["workflow_dispatch"],
        )
        self.assertIn(
            "autonomy-proactive-channel-preflight-<run-id>",
            proactive["commands"]["download_preflight_artifact"],
        )
        self.assertNotIn("&&", proactive["commands"]["local_preflight"])
        self.assertEqual(
            "maritime-ai-service",
            proactive["command_specs"]["local_preflight"]["working_directory"],
        )
        self.assertFalse(proactive["command_specs"]["local_preflight"]["uses_shell"])
        self.assertEqual(
            [
                "python",
                "scripts/probe_live_proactive_channel.py",
                "--preflight-only",
            ],
            proactive["command_specs"]["local_preflight"]["argv"][:3],
        )
        self.assertIn(
            "autonomy-proactive-channel-preflight.json",
            proactive["command_specs"]["local_preflight"]["argv"],
        )
        self.assertNotIn("&&", proactive["commands"]["local_failure_from_preflight"])
        self.assertIn(
            "--failure-from-preflight",
            proactive["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "--failure-preflight-json",
            proactive["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "autonomy-proactive-channel-preflight.json",
            proactive["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "autonomy-proactive-channel-evidence.json",
            proactive["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertEqual(
            "maritime-ai-service",
            proactive["command_specs"]["local_failure_from_preflight"][
                "working_directory"
            ],
        )
        self.assertFalse(
            proactive["command_specs"]["local_failure_from_preflight"]["uses_shell"]
        )
        self.assertIn(
            "TELEGRAM_BOT_TOKEN",
            proactive["conditional_github_secrets"],
        )
        self.assertIn(
            {
                "token": "configure_selected_channel_credential",
                "category": "secret_or_credential",
                "instruction": (
                    "Configure the selected channel credential through the approved "
                    "secret store or environment."
                ),
            },
            proactive["required_operator_actions"],
        )
        composio = payload["launch_items"][1]
        self.assertEqual(
            "wiii-connect-composio-acceptance",
            composio["requirement_id"],
        )
        self.assertIn(
            "WIII_ACCEPTANCE_BEARER_TOKEN",
            composio["required_github_secrets"],
        )
        self.assertEqual(
            ["WIII_ACCEPTANCE_BEARER_TOKEN"],
            composio["preflight_setup_contract_bindings"][
                "credential_slots_required"
            ]["acceptance_bearer_token"],
        )
        self.assertIn(
            "wiii-connect-composio-acceptance-preflight-<run-id>",
            composio["commands"]["download_preflight_artifact"],
        )
        self.assertNotIn("&&", composio["commands"]["local_live_probe"])
        self.assertEqual(
            "maritime-ai-service",
            composio["command_specs"]["local_live_probe"]["working_directory"],
        )
        self.assertIn(
            "<readonly-arguments-json>",
            composio["command_specs"]["local_live_probe"]["argv"],
        )
        self.assertNotIn("&&", composio["commands"]["local_failure_from_preflight"])
        self.assertIn(
            "--failure-from-preflight",
            composio["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "--failure-preflight-json",
            composio["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "wiii-connect-composio-acceptance-preflight.json",
            composio["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn(
            "wiii-connect-composio-acceptance-evidence.json",
            composio["command_specs"]["local_failure_from_preflight"]["argv"],
        )
        self.assertIn("<backend-url>", composio["commands"]["workflow_dispatch"])
        self.assertIn("# Wiii Completion Audit Launch Pack", markdown)
        post_commands = "\n".join(payload["post_launch_verification_commands"])
        self.assertGreaterEqual(post_commands.count("--preflight-dir <preflight-dir>"), 5)
        self.assertNotIn("--preflight-dir artifacts", post_commands)
        self.assertEqual(
            len(payload["post_launch_verification_commands"]),
            len(payload["post_launch_verification_command_specs"]),
        )
        self.assertRegex(
            payload["post_launch_verification_command_specs_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        first_post_spec = payload["post_launch_verification_command_specs"][0]
        self.assertEqual(
            "validate_runtime_evidence_bundle",
            first_post_spec["step_id"],
        )
        self.assertEqual(".", first_post_spec["working_directory"])
        self.assertFalse(first_post_spec["uses_shell"])
        self.assertEqual(
            payload["post_launch_verification_commands"][0],
            " ".join(first_post_spec["argv"]),
        )
        self.assertIn(
            "--out <runtime-evidence-bundle-report-json>",
            payload["post_launch_verification_commands"][0],
        )
        self.assertIn("generate_completion_audit_launch_pack.py", post_commands)
        self.assertIn("validate_completion_audit_launch_pack.py", post_commands)
        self.assertIn("generate_completion_audit_setup_state.py", post_commands)
        self.assertIn("validate_completion_audit_setup_state.py", post_commands)
        self.assertIn("generate_completion_audit_dispatch_gate.py", post_commands)
        self.assertIn("validate_completion_audit_dispatch_gate.py", post_commands)
        self.assertIn("run_completion_audit_dispatch_gate.py", post_commands)
        self.assertIn("validate_completion_audit_dispatch_run.py", post_commands)
        self.assertIn("generate_completion_audit_setup_handle_plan.py", post_commands)
        self.assertIn("validate_completion_audit_setup_handle_plan.py", post_commands)
        self.assertIn("probe_completion_audit_setup_handle_evidence.py", post_commands)
        self.assertIn("--runtime-evidence-dir <runtime-evidence-dir>", post_commands)
        self.assertIn(
            "--runtime-evidence-bundle-report <runtime-evidence-bundle-report-json>",
            post_commands,
        )
        self.assertIn("--allow-env-read", post_commands)
        self.assertIn("--allow-network", post_commands)
        self.assertIn("<setup-handle-evidence-json>", post_commands)
        self.assertIn("generate_completion_audit_setup_attestation_from_handles.py", post_commands)
        self.assertIn("<setup-attestation-json>", post_commands)
        self.assertIn("apply_completion_audit_setup_attestation.py", post_commands)
        self.assertIn("<setup-state-attested-json>", post_commands)
        self.assertIn("<dispatch-gate-attested-json>", post_commands)
        self.assertIn("<dispatch-run-attested-json>", post_commands)
        self.assertIn("validate_completion_audit_control_chain.py", post_commands)
        self.assertIn("<readiness-markdown>", post_commands)
        self.assertIn("--markdown-report <readiness-markdown>", post_commands)
        self.assertIn(
            "--self-harness-report-bundle <downloaded-self-harness-reports-dir>",
            post_commands,
        )
        self.assertIn("<launch-pack-json>", post_commands)
        self.assertIn("<launch-pack-markdown>", post_commands)
        self.assertIn("--run-plan <run-plan-json>", post_commands)
        self.assertIn("--markdown-report <launch-pack-markdown>", post_commands)
        self.assertIn(
            "generate_completion_audit_setup_state.py <launch-pack-json> --repo-root . --out <setup-state-json>",
            post_commands,
        )
        self.assertIn("<setup-state-json>", post_commands)
        self.assertIn("<setup-handle-plan-json>", post_commands)
        self.assertIn("<dispatch-gate-json>", post_commands)
        self.assertIn("<dispatch-run-json>", post_commands)
        self.assertIn("run_completion_audit_dispatch_diagnostics.py", post_commands)
        self.assertIn("validate_completion_audit_dispatch_diagnostics.py", post_commands)
        self.assertIn("<dispatch-diagnostics-json>", post_commands)
        self.assertIn("--launch-pack <launch-pack-json>", post_commands)
        self.assertIn("--setup-state <setup-state-json>", post_commands)
        self.assertIn("--dispatch-gate <dispatch-gate-json>", post_commands)
        self.assertIn("--allow-pending-report", post_commands)
        self.assertIn("--readiness-markdown-report <readiness-markdown>", post_commands)
        self.assertIn("--readiness-preflight-dir <preflight-dir>", post_commands)
        self.assertIn("## Setup Requirements", markdown)
        self.assertIn("configure_selected_channel_credential", markdown)
        self.assertIn("Configure the selected channel credential", markdown)
        self.assertIn("Required GitHub vars", markdown)
        self.assertIn("Preflight source SHA-256", markdown)
        self.assertIn("Preflight source validation", markdown)
        self.assertIn("Preflight raw payload included", markdown)
        self.assertIn("## Post-Launch Verification", markdown)
        self.assertIn("## Structured Post-Launch Verification Specs", markdown)
        self.assertIn("## Structured Command Specs", markdown)
        self.assertIn("uses_shell=`false`", markdown)
        self.assertIn("## Acceptance Checks", markdown)
        self.assertIn("validate_runtime_evidence_bundle.py", markdown)
        self.assertIn("--preflight-dir <preflight-dir>", markdown)
        self.assertNotIn("secret-access-token", json.dumps(payload))

    def test_launch_pack_fingerprints_bind_schema_and_run_plan_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_plan_path = _write_run_plan(Path(temp_dir))

            pack = launch_generator.generate_completion_audit_launch_pack(run_plan_path)

        current_items = launch_generator._launch_items_fingerprint(
            pack.launch_items,
            run_plan_schema_version=pack.run_plan_schema_version,
            run_plan_run_items_fingerprint_sha256=(
                pack.run_plan_run_items_fingerprint_sha256
            ),
            run_plan_operator_setup_fingerprint_sha256=(
                pack.run_plan_operator_setup_fingerprint_sha256
            ),
            run_plan_acceptance_contract_fingerprint_sha256=(
                pack.run_plan_acceptance_contract_fingerprint_sha256
            ),
        )
        self.assertEqual(pack.launch_items_fingerprint_sha256, current_items)
        self.assertNotEqual(
            current_items,
            launch_generator._launch_items_fingerprint(
                pack.launch_items,
                schema_version="wiii.completion_audit_launch_pack.v2",
                run_plan_schema_version=pack.run_plan_schema_version,
                run_plan_run_items_fingerprint_sha256=(
                    pack.run_plan_run_items_fingerprint_sha256
                ),
                run_plan_operator_setup_fingerprint_sha256=(
                    pack.run_plan_operator_setup_fingerprint_sha256
                ),
                run_plan_acceptance_contract_fingerprint_sha256=(
                    pack.run_plan_acceptance_contract_fingerprint_sha256
                ),
            ),
        )
        self.assertNotEqual(
            current_items,
            launch_generator._launch_items_fingerprint(
                pack.launch_items,
                run_plan_schema_version="wiii.completion_audit_run_plan.v2",
                run_plan_run_items_fingerprint_sha256=(
                    pack.run_plan_run_items_fingerprint_sha256
                ),
                run_plan_operator_setup_fingerprint_sha256=(
                    pack.run_plan_operator_setup_fingerprint_sha256
                ),
                run_plan_acceptance_contract_fingerprint_sha256=(
                    pack.run_plan_acceptance_contract_fingerprint_sha256
                ),
            ),
        )
        self.assertNotEqual(
            current_items,
            launch_generator._launch_items_fingerprint(
                pack.launch_items,
                run_plan_schema_version=pack.run_plan_schema_version,
                run_plan_run_items_fingerprint_sha256="0" * 64,
                run_plan_operator_setup_fingerprint_sha256=(
                    pack.run_plan_operator_setup_fingerprint_sha256
                ),
                run_plan_acceptance_contract_fingerprint_sha256=(
                    pack.run_plan_acceptance_contract_fingerprint_sha256
                ),
            ),
        )
        self.assertNotEqual(
            pack.launch_setup_fingerprint_sha256,
            launch_generator._launch_setup_fingerprint(
                pack.launch_items,
                run_plan_operator_setup_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            pack.launch_acceptance_fingerprint_sha256,
            launch_generator._launch_acceptance_fingerprint(
                pack.launch_items,
                run_plan_acceptance_contract_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            pack.launch_command_specs_fingerprint_sha256,
            launch_generator._launch_command_specs_fingerprint(
                pack.launch_items,
                run_plan_run_items_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            pack.post_launch_verification_command_specs_fingerprint_sha256,
            launch_generator._verification_command_specs_fingerprint(
                pack.post_launch_verification_command_specs,
                run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                    "0" * 64
                ),
            ),
        )

    def test_generate_launch_pack_uses_command_preflight_output_when_source_is_missing(self) -> None:
        readiness_payload = _sample_readiness_payload()
        readiness_payload["preflight_summary_count"] = 0
        readiness_payload["preflight_summaries"] = []
        readiness_payload["full_live_setup_blocked_count"] = 0
        readiness_payload["full_live_setup_blocked_requirement_ids"] = []
        readiness_payload["scoped_live_setup_blocked_count"] = 0
        readiness_payload["scoped_live_setup_blocked_requirement_ids"] = []
        for action in readiness_payload["scoped_next_actions"]:
            action["blocked_by_live_setup"] = False
            action["preflight_status"] = ""
            action["preflight_schema_version"] = ""
            action["preflight_generated_at"] = ""
            action["preflight_required_next"] = []
            action["preflight_source_file"] = ""
        readiness_payload["scoped_next_actions_fingerprint_sha256"] = (
            readiness_validator._next_actions_fingerprint(
                readiness_payload["scoped_next_actions"]
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            run_plan_path = root / "run-plan.json"
            _write_json(readiness_path, readiness_payload)
            run_plan = run_plan_generator.generate_completion_audit_run_plan(
                readiness_path
            )
            _write_json(run_plan_path, run_plan.to_dict())

            pack = launch_generator.generate_completion_audit_launch_pack(run_plan_path)
            payload = pack.to_dict()

        self.assertEqual(
            "autonomy-proactive-channel-preflight.json",
            payload["launch_items"][0]["preflight_source_file"],
        )
        self.assertEqual(
            "wiii-connect-composio-acceptance-preflight.json",
            payload["launch_items"][1]["preflight_source_file"],
        )
        self.assertEqual("", payload["launch_items"][0]["preflight_source_file_sha256"])
        self.assertFalse(payload["launch_items"][0]["preflight_source_validation_ok"])
        self.assertFalse(payload["launch_items"][0]["preflight_raw_payload_included"])

    def test_generate_launch_pack_rejects_invalid_run_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path = _write_run_plan(root)
            payload = json.loads(run_plan_path.read_text(encoding="utf-8"))
            payload["run_item_count"] = 1
            _write_json(run_plan_path, payload)

            with self.assertRaises(ValueError) as exc:
                launch_generator.generate_completion_audit_launch_pack(run_plan_path)

        self.assertIn(
            launch_generator.LAUNCH_PACK_RUN_PLAN_VALIDATION_ERROR,
            str(exc.exception),
        )

    def test_cli_json_writes_launch_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path = _write_run_plan(root)
            out_path = root / "launch-pack.json"

            exit_code = launch_generator.main(
                [
                    str(run_plan_path),
                    "--format",
                    "json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual(
            launch_generator.LAUNCH_PACK_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertEqual(2, payload["launch_item_count"])

    def test_cli_json_reports_invalid_run_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_plan_path = _write_run_plan(root)
            payload = json.loads(run_plan_path.read_text(encoding="utf-8"))
            payload["privacy"]["secret_values_included"] = True
            _write_json(run_plan_path, payload)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = launch_generator.main(
                    [str(run_plan_path), "--format", "json"]
                )
            output = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(output["ok"])
        self.assertEqual(
            ["completion_audit_launch_pack_run_plan_invalid"],
            output["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
