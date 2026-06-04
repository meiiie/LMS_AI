import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import generate_completion_audit_run_plan as generator
import validate_completion_audit_readiness as readiness_validator


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _preflight_summary(
    *,
    requirement_id: str,
    schema_version: str,
    status: str,
    required_next: list[str],
    source_file: str,
    source_sha: str,
    setup_contract: dict | None = None,
) -> dict:
    return {
        "requirement_id": requirement_id,
        "schema_version": schema_version,
        "status": status,
        "generated_at": "2026-06-02T12:00:00+00:00",
        "required_next": required_next,
        "source_file": source_file,
        "source_file_sha256": source_sha,
        "source_validation_schema_version": (
            "wiii.runtime_evidence_preflight_validation.v1"
        ),
        "source_validation_ok": True,
        "source_validation_error_codes": [],
        "raw_payload_included": False,
        "setup_contract": setup_contract or {},
    }


def _source_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preflight_source_from_summary(summary: dict) -> dict:
    common = {
        "schema_version": summary["schema_version"],
        "generated_at": summary["generated_at"],
        "status": summary["status"],
        "required_next": summary["required_next"],
        "setup_contract": summary["setup_contract"],
    }
    if summary["schema_version"] == "wiii.proactive_channel_preflight.v1":
        return {
            **common,
            "requested_channel": "telegram",
            "allow_send_acknowledged": True,
            "live_env_flag_set": True,
            "recipient_id_present": False,
            "production_environment": False,
            "allow_production_acknowledged": False,
            "live_send_attempted": False,
            "channel_config": {
                "supported": True,
                "enabled": True,
                "credential_present": True,
                "credential_value_included": False,
                "credential_name_included": False,
            },
            "privacy": {
                "secret_values_included": False,
                "credential_names_included": False,
                "raw_recipient_identifier_included": False,
                "raw_organization_identifier_included": False,
                "raw_message_included": False,
                "raw_delivery_payload_included": False,
                "raw_channel_credentials_included": False,
            },
        }
    return {
        **common,
        "requested_provider": "github",
        "requested_action": "readonly",
        "allow_live_acknowledged": True,
        "live_env_flag_set": True,
        "live_backend_call_attempted": False,
        "provider_execution_attempted": False,
        "backend": {
            "valid": False,
            "placeholder": True,
            "scheme": "",
            "host_hash_present": False,
            "origin_hash_present": False,
            "raw_backend_url_included": False,
        },
        "authentication": {
            "mode": "bearer",
            "bearer_token_present": False,
            "bearer_source": "",
            "dev_login_allowed_by_mode": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
        },
        "flags": {
            "expect_connected": True,
            "require_execution_ready": True,
            "execute_readonly": True,
            "skip_connect_link": False,
            "explicit_connection_selection_present": False,
        },
        "arguments": {
            "valid_json_object": True,
            "argument_key_count": 0,
            "arguments_present": False,
            "raw_arguments_included": False,
        },
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
            "raw_backend_url_included": False,
            "raw_connection_selection_included": False,
            "raw_arguments_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
        },
    }


def _sample_readiness_payload() -> dict:
    proactive_summary = _preflight_summary(
        requirement_id="autonomy-proactive-channel",
        schema_version="wiii.proactive_channel_preflight.v1",
        status="fail",
        required_next=[
            "pass_allow_send",
            "set_live_proactive_channel_probe_env_flag",
            "provide_recipient_id",
            "enable_selected_channel",
            "configure_selected_channel_credential",
        ],
        source_file="proactive-channel-preflight.json",
        source_sha="a" * 64,
        setup_contract={
            "version": "wiii.live_evidence_setup_contract.v1",
            "requirement_id": "autonomy-proactive-channel",
            "required_next": [
                "pass_allow_send",
                "set_live_proactive_channel_probe_env_flag",
                "provide_recipient_id",
                "enable_selected_channel",
                "configure_selected_channel_credential",
            ],
            "workflow_inputs_required": [
                "channel",
                "recipient_id",
                "allow_send",
                "allow_production",
            ],
            "environment_flags_required": ["live_proactive_channel_probe_flag"],
            "credential_slots_required": ["selected_channel_credential"],
            "external_setup_required": [
                "approved_recipient",
                "selected_channel_enabled",
            ],
            "dispatch_ready": False,
        },
    )
    composio_summary = _preflight_summary(
        requirement_id="wiii-connect-composio-acceptance",
        schema_version="wiii.connect_composio_acceptance_preflight.v1",
        status="fail",
        required_next=[
            "pass_allow_live",
            "set_live_composio_acceptance_flag",
            "configure_backend_url",
            "configure_acceptance_bearer_token",
        ],
        source_file="wiii-connect-composio-preflight.json",
        source_sha="b" * 64,
        setup_contract={
            "version": "wiii.live_evidence_setup_contract.v1",
            "requirement_id": "wiii-connect-composio-acceptance",
            "required_next": [
                "pass_allow_live",
                "set_live_composio_acceptance_flag",
                "configure_backend_url",
                "configure_acceptance_bearer_token",
            ],
            "workflow_inputs_required": [
                "backend_url",
                "auth_mode",
                "provider",
                "allow_live",
                "expect_connected",
                "require_execution_ready",
                "execute_readonly",
                "arguments_json",
            ],
            "environment_flags_required": ["live_composio_acceptance_flag"],
            "credential_slots_required": ["acceptance_bearer_token"],
            "external_setup_required": [
                "staging_or_live_backend",
                "connected_provider_account",
                "readonly_action_schema",
                "execution_gateway_scope_policy",
            ],
            "dispatch_ready": False,
        },
    )
    actions = [
        {
            "requirement_id": "autonomy-proactive-channel",
            "title": "Proactive outbound channel evidence",
            "layer": "Wiii Living",
            "artifact": "autonomy-proactive-channel-evidence.json",
            "schema_version": "wiii.live_proactive_channel_probe.v1",
            "status": "failed",
            "workflow": ".github/workflows/autonomy-runtime-evidence.yml",
            "probe": "maritime-ai-service/scripts/probe_live_proactive_channel.py",
            "live_env_flags": ["WIII_LIVE_PROACTIVE_CHANNEL_PROBE"],
            "live_guard_tokens": ["--allow-send"],
            "dispatch_or_schedule_gate_tokens": [
                "run_proactive_channel",
                "WIII_PROACTIVE_CHANNEL_EVIDENCE_ENABLED",
            ],
            "artifact_tokens": [
                "autonomy-proactive-channel-evidence-${{ github.run_id }}"
            ],
            "diagnostic_uploads": [
                {
                    "artifact": "autonomy-proactive-channel-preflight.json",
                    "path": "maritime-ai-service/autonomy-proactive-channel-preflight.json",
                    "artifact_tokens": [
                        "autonomy-proactive-channel-preflight-${{ github.run_id }}"
                    ],
                    "if_no_files_found": "warn",
                    "retention_days": 14,
                }
            ],
            "error_codes": ["payload_check_equals_mismatch"],
            "blocked_by_live_setup": True,
            "preflight_status": proactive_summary["status"],
            "preflight_schema_version": proactive_summary["schema_version"],
            "preflight_generated_at": proactive_summary["generated_at"],
            "preflight_required_next": proactive_summary["required_next"],
            "preflight_source_file": proactive_summary["source_file"],
        },
        {
            "requirement_id": "wiii-connect-composio-acceptance",
            "title": "Credentialed Wiii Connect Composio acceptance evidence",
            "layer": "Wiii Host",
            "artifact": "wiii-connect-composio-acceptance-evidence.json",
            "schema_version": "wiii.live_wiii_connect_composio_acceptance.v1",
            "status": "missing",
            "workflow": (
                ".github/workflows/wiii-connect-composio-acceptance-evidence.yml"
            ),
            "probe": "maritime-ai-service/scripts/wiii_connect_composio_acceptance.py",
            "live_env_flags": ["WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE"],
            "live_guard_tokens": ["--allow-live"],
            "dispatch_or_schedule_gate_tokens": [
                "run_composio_acceptance",
                "WIII_CONNECT_COMPOSIO_ACCEPTANCE_EVIDENCE_ENABLED",
            ],
            "artifact_tokens": [
                "wiii-connect-composio-acceptance-evidence-${{ github.run_id }}"
            ],
            "diagnostic_uploads": [
                {
                    "artifact": "wiii-connect-composio-acceptance-preflight.json",
                    "path": "maritime-ai-service/wiii-connect-composio-acceptance-preflight.json",
                    "artifact_tokens": [
                        "wiii-connect-composio-acceptance-preflight-${{ github.run_id }}"
                    ],
                    "if_no_files_found": "warn",
                    "retention_days": 14,
                }
            ],
            "error_codes": ["missing_artifact"],
            "blocked_by_live_setup": True,
            "preflight_status": composio_summary["status"],
            "preflight_schema_version": composio_summary["schema_version"],
            "preflight_generated_at": composio_summary["generated_at"],
            "preflight_required_next": composio_summary["required_next"],
            "preflight_source_file": composio_summary["source_file"],
        },
    ]
    return {
        "schema_version": "wiii.completion_audit_readiness_report.v1",
        "registry_name": "Wiii Runtime Evidence Registry",
        "registry_version": 1,
        "registry_fingerprint_sha256": "1" * 64,
        "bundle_root": "artifacts/runtime-evidence",
        "bundle_fingerprint_sha256": "2" * 64,
        "completion_audit_fingerprint_sha256": "3" * 64,
        "self_harness_report_bundle_root": "artifacts/wiii-self-harness",
        "self_harness_report_bundle_fingerprint_sha256": "4" * 64,
        "self_harness_report_bundle_validation_schema_version": (
            "wiii.self_harness_report_bundle_validation.v1"
        ),
        "full_completion_audit_ready": False,
        "scoped_completion_audit_ready": False,
        "full_requirement_count": 4,
        "full_passed_count": 1,
        "full_missing_count": 2,
        "full_failed_count": 1,
        "scoped_requirement_count": 3,
        "scoped_passed_count": 1,
        "scoped_missing_count": 1,
        "scoped_failed_count": 1,
        "excluded_requirement_ids": ["lms-test-course-replay"],
        "unknown_excluded_requirement_ids": [],
        "full_missing_requirement_ids": [
            "lms-test-course-replay",
            "wiii-connect-composio-acceptance",
        ],
        "full_failed_requirement_ids": ["autonomy-proactive-channel"],
        "scoped_missing_requirement_ids": ["wiii-connect-composio-acceptance"],
        "scoped_failed_requirement_ids": ["autonomy-proactive-channel"],
        "full_live_setup_blocked_count": 2,
        "full_live_setup_blocked_requirement_ids": [
            "autonomy-proactive-channel",
            "wiii-connect-composio-acceptance",
        ],
        "scoped_live_setup_blocked_count": 2,
        "scoped_live_setup_blocked_requirement_ids": [
            "autonomy-proactive-channel",
            "wiii-connect-composio-acceptance",
        ],
        "readiness_blockers": [
            "failed:autonomy-proactive-channel",
            "missing:lms-test-course-replay",
            "missing:wiii-connect-composio-acceptance",
        ],
        "scoped_readiness_blockers": [
            "failed:autonomy-proactive-channel",
            "missing:wiii-connect-composio-acceptance",
        ],
        "scoped_next_action_count": 2,
        "scoped_next_actions_fingerprint_sha256": (
            readiness_validator._next_actions_fingerprint(actions)
        ),
        "scoped_next_actions": actions,
        "preflight_summary_count": 2,
        "preflight_summaries": [proactive_summary, composio_summary],
        "rows": [
            {
                "requirement_id": "provider-runtime-tool-loop",
                "artifact": "provider-runtime-evidence.json",
                "status": "passed",
                "included_in_scope": True,
                "error_codes": [],
            },
            {
                "requirement_id": "autonomy-proactive-channel",
                "artifact": "autonomy-proactive-channel-evidence.json",
                "status": "failed",
                "included_in_scope": True,
                "error_codes": ["payload_check_equals_mismatch"],
            },
            {
                "requirement_id": "lms-test-course-replay",
                "artifact": "lms-test-course-evidence.json",
                "status": "missing",
                "included_in_scope": False,
                "error_codes": ["missing_artifact"],
            },
            {
                "requirement_id": "wiii-connect-composio-acceptance",
                "artifact": "wiii-connect-composio-acceptance-evidence.json",
                "status": "missing",
                "included_in_scope": True,
                "error_codes": ["missing_artifact"],
            },
        ],
        "errors": [],
        "ok": True,
        "error_codes": [],
        "error_code_counts": {},
    }


class GenerateCompletionAuditRunPlanTests(unittest.TestCase):
    def test_generate_run_plan_preserves_blockers_and_preflight_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            readiness_path = Path(temp_dir) / "readiness.json"
            _write_json(readiness_path, _sample_readiness_payload())

            plan = generator.generate_completion_audit_run_plan(readiness_path)
            payload = plan.to_dict()
            rendered = generator.format_markdown(plan)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["readiness_scoped_completion_audit_ready"])
        self.assertEqual("blocked_on_live_setup", payload["execution_state"])
        self.assertEqual(2, payload["run_item_count"])
        self.assertEqual(2, payload["blocked_by_live_setup_count"])
        self.assertRegex(
            payload["acceptance_contract_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(
            payload["operator_setup_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            ["lms-test-course-replay"],
            payload["excluded_requirement_ids"],
        )
        first_item = payload["run_items"][0]
        self.assertEqual("autonomy-proactive-channel", first_item["requirement_id"])
        self.assertEqual("a" * 64, first_item["preflight"]["source_file_sha256"])
        self.assertEqual(
            "wiii.live_evidence_setup_contract.v1",
            first_item["preflight"]["setup_contract"]["version"],
        )
        self.assertEqual(
            ["selected_channel_credential"],
            first_item["preflight"]["setup_contract"]["credential_slots_required"],
        )
        self.assertEqual(
            ["autonomy-proactive-channel-preflight-${{ github.run_id }}"],
            first_item["workflow_execution"]["diagnostic_artifact_tokens"],
        )
        self.assertIn(
            "configure_selected_channel_credential",
            first_item["credential_or_external_setup_tokens"],
        )
        self.assertFalse(payload["privacy"]["secret_values_included"])
        post_commands = "\n".join(payload["post_run_verification_commands"])
        self.assertGreaterEqual(post_commands.count("--preflight-dir <preflight-dir>"), 5)
        self.assertNotIn("--preflight-dir artifacts", post_commands)
        self.assertEqual(
            len(payload["post_run_verification_commands"]),
            len(payload["post_run_verification_command_specs"]),
        )
        self.assertRegex(
            payload["post_run_verification_command_specs_fingerprint_sha256"],
            r"^[0-9a-f]{64}$",
        )
        first_spec = payload["post_run_verification_command_specs"][0]
        self.assertEqual("validate_runtime_evidence_bundle", first_spec["step_id"])
        self.assertEqual(".", first_spec["working_directory"])
        self.assertFalse(first_spec["uses_shell"])
        self.assertEqual(
            payload["post_run_verification_commands"][0],
            " ".join(first_spec["argv"]),
        )
        self.assertIn(
            "--out <runtime-evidence-bundle-report-json>",
            payload["post_run_verification_commands"][0],
        )
        self.assertIn("generate_completion_audit_launch_pack.py", post_commands)
        self.assertIn("validate_completion_audit_launch_pack.py", post_commands)
        self.assertIn("generate_completion_audit_setup_state.py", post_commands)
        self.assertIn("validate_completion_audit_setup_state.py", post_commands)
        self.assertIn("generate_completion_audit_dispatch_gate.py", post_commands)
        self.assertIn("validate_completion_audit_dispatch_gate.py", post_commands)
        self.assertIn("run_completion_audit_dispatch_gate.py", post_commands)
        self.assertIn("validate_completion_audit_dispatch_run.py", post_commands)
        self.assertIn("run_completion_audit_dispatch_diagnostics.py", post_commands)
        self.assertIn("validate_completion_audit_dispatch_diagnostics.py", post_commands)
        self.assertIn("<dispatch-diagnostics-json>", post_commands)
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
        self.assertIn("--allow-pending-report", post_commands)
        self.assertIn("<setup-handle-plan-json>", post_commands)
        self.assertIn("<dispatch-run-json>", post_commands)
        self.assertIn("--dispatch-gate <dispatch-gate-json>", post_commands)
        self.assertIn("<readiness-markdown>", post_commands)
        self.assertIn("--markdown-report <readiness-markdown>", post_commands)
        self.assertIn(
            "--self-harness-report-bundle <downloaded-self-harness-reports-dir>",
            post_commands,
        )
        self.assertIn("<run-plan-markdown>", post_commands)
        self.assertIn("--markdown-report <run-plan-markdown>", post_commands)
        self.assertIn("--readiness-markdown-report <readiness-markdown>", post_commands)
        self.assertIn("--readiness-preflight-dir <preflight-dir>", post_commands)
        self.assertIn("<launch-pack-json>", post_commands)
        self.assertIn("--run-plan <run-plan-json>", post_commands)
        self.assertIn(
            "generate_completion_audit_setup_state.py <launch-pack-json> --repo-root . --out <setup-state-json>",
            post_commands,
        )
        self.assertIn("<setup-state-json>", post_commands)
        self.assertIn("<dispatch-gate-json>", post_commands)
        self.assertIn("--launch-pack <launch-pack-json>", post_commands)
        self.assertIn("--setup-state <setup-state-json>", post_commands)
        self.assertIn("# Wiii Completion Audit Run Plan", rendered)
        self.assertIn("## Structured Verification Specs", rendered)
        self.assertIn("uses_shell=`false`", rendered)
        self.assertIn("autonomy-proactive-channel", rendered)

    def test_run_plan_fingerprints_bind_schema_and_readiness_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            readiness_path = Path(temp_dir) / "readiness.json"
            _write_json(readiness_path, _sample_readiness_payload())

            plan = generator.generate_completion_audit_run_plan(readiness_path)

        current_run_items = generator._run_items_fingerprint(
            plan.run_items,
            readiness_schema_version=plan.readiness_schema_version,
            readiness_scoped_next_actions_fingerprint_sha256=(
                plan.readiness_scoped_next_actions_fingerprint_sha256
            ),
        )
        self.assertEqual(plan.run_items_fingerprint_sha256, current_run_items)
        self.assertNotEqual(
            current_run_items,
            generator._run_items_fingerprint(
                plan.run_items,
                schema_version="wiii.completion_audit_run_plan.v2",
                readiness_schema_version=plan.readiness_schema_version,
                readiness_scoped_next_actions_fingerprint_sha256=(
                    plan.readiness_scoped_next_actions_fingerprint_sha256
                ),
            ),
        )
        self.assertNotEqual(
            current_run_items,
            generator._run_items_fingerprint(
                plan.run_items,
                readiness_schema_version="wiii.completion_audit_readiness_report.v2",
                readiness_scoped_next_actions_fingerprint_sha256=(
                    plan.readiness_scoped_next_actions_fingerprint_sha256
                ),
            ),
        )
        self.assertNotEqual(
            current_run_items,
            generator._run_items_fingerprint(
                plan.run_items,
                readiness_schema_version=plan.readiness_schema_version,
                readiness_scoped_next_actions_fingerprint_sha256="0" * 64,
            ),
        )
        self.assertNotEqual(
            plan.operator_setup_fingerprint_sha256,
            generator._operator_setup_fingerprint(
                plan.run_items,
                schema_version="wiii.completion_audit_run_plan.v2",
            ),
        )
        self.assertNotEqual(
            plan.acceptance_contract_fingerprint_sha256,
            generator._acceptance_contract_fingerprint(
                plan.run_items,
                schema_version="wiii.completion_audit_run_plan.v2",
            ),
        )
        self.assertNotEqual(
            plan.post_run_verification_command_specs_fingerprint_sha256,
            generator._verification_command_specs_fingerprint(
                plan.post_run_verification_command_specs,
                schema_version="wiii.completion_audit_run_plan.v2",
            ),
        )

    def test_generate_run_plan_rejects_invalid_readiness_report(self) -> None:
        payload = _sample_readiness_payload()
        payload["scoped_next_action_count"] = 1
        with tempfile.TemporaryDirectory() as temp_dir:
            readiness_path = Path(temp_dir) / "readiness.json"
            _write_json(readiness_path, payload)

            with self.assertRaises(ValueError) as exc:
                generator.generate_completion_audit_run_plan(readiness_path)

        self.assertIn(
            generator.RUN_PLAN_READINESS_VALIDATION_ERROR,
            str(exc.exception),
        )

    def test_generate_run_plan_accepts_multiple_preflight_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_dir = root / "first"
            second_dir = root / "second"
            payload = _sample_readiness_payload()
            for index, preflight_dir in enumerate((first_dir, second_dir)):
                summary = payload["preflight_summaries"][index]
                source_path = preflight_dir / summary["source_file"]
                _write_json(source_path, _preflight_source_from_summary(summary))
                summary["source_file_sha256"] = _source_sha(source_path)
            readiness_path = root / "readiness.json"
            _write_json(readiness_path, payload)

            plan = generator.generate_completion_audit_run_plan(
                readiness_path,
                preflight_dirs=[first_dir, second_dir],
            )

        self.assertTrue(plan.ok, plan.to_dict())
        self.assertEqual(2, plan.readiness_preflight_summary_count)

    def test_cli_json_writes_run_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readiness_path = root / "readiness.json"
            out_path = root / "run-plan.json"
            _write_json(readiness_path, _sample_readiness_payload())

            exit_code = generator.main(
                [
                    str(readiness_path),
                    "--format",
                    "json",
                    "--out",
                    str(out_path),
                ]
            )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertEqual(generator.RUN_PLAN_SCHEMA_VERSION, payload["schema_version"])
        self.assertEqual("blocked_on_live_setup", payload["execution_state"])

    def test_cli_json_reports_invalid_readiness(self) -> None:
        payload = _sample_readiness_payload()
        payload["rows"][0]["status"] = "warning"
        with tempfile.TemporaryDirectory() as temp_dir:
            readiness_path = Path(temp_dir) / "readiness.json"
            _write_json(readiness_path, payload)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = generator.main(
                    [str(readiness_path), "--format", "json"]
                )
            output = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertFalse(output["ok"])
        self.assertEqual(
            ["completion_audit_run_plan_readiness_invalid"],
            output["error_codes"],
        )


if __name__ == "__main__":
    unittest.main()
