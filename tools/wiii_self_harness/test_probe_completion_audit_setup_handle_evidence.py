import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import generate_completion_audit_setup_attestation_from_handles as attestation_from_handles
import probe_completion_audit_setup_handle_evidence as probe
from test_generate_completion_audit_run_plan import _write_json
from test_generate_completion_audit_setup_attestation_from_handles import _write_plan
from test_validate_completion_audit_setup_state import _load_json


def _env_for_pending_checks(plan_payload: dict) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in plan_payload["plan_items"]:
        for check in item["setup_checks"]:
            if check["present"]:
                continue
            kind = check["recommended_evidence_kinds"][0]
            token = check["binding_tokens"][0]
            if kind in {
                "environment_flag_bound",
                "github_variable_present",
                "runtime_channel_enabled",
            }:
                env[token] = "1"
            elif kind == "backend_health_checked":
                env[token] = "https://backend.example"
            else:
                env[token] = f"private-{token}-value"
    return env


def _allowed_scope_policy_summary() -> dict:
    return {
        "version": "wiii.connect.scope_policy.v1",
        "status": "allowed",
        "reason": "allowed",
        "read_required": True,
        "read_allowed": True,
        "required_scope_count": 1,
        "allowed_scope_count": 1,
    }


def _composio_pass_payload() -> dict:
    return {
        "schema_version": probe.COMPOSIO_ACCEPTANCE_SCHEMA_VERSION,
        "schema": probe.COMPOSIO_ACCEPTANCE_LEGACY_SCHEMA,
        "generated_at": "2026-06-03T00:00:00+00:00",
        "status": "pass",
        "provider": "gmail",
        "action": "GMAIL_FETCH_EMAILS",
        "auth_mode": "bearer",
        "backend_origin": "https://wiii.example.com",
        "target_env": "staging",
        "commit_sha": "abc1234",
        "summary": {
            "passed": 12,
            "failed": 0,
            "total": 12,
            "success": True,
        },
        "flags": {
            "expect_connected": True,
            "require_execution_ready": True,
            "execute_readonly": True,
            "connection_selected_for_action": True,
            "explicit_connection_selected": False,
        },
        "runtime": {
            "path": "external_app_action",
            "mutation": "read",
            "argument_key_count": 1,
            "arguments_present": True,
            "check_count": 12,
            "observed_section_count": 12,
        },
        "evidence_contract": {
            "backend_only_harness": True,
            "external_provider_execution": True,
            "requires_connected_account": True,
            "requires_readonly_execution": True,
        },
        "check_statuses": {
            "connection_listing": "passed",
            "activation_readiness_execution": "passed",
            "execution_gateway_allowed": "passed",
            "read_only_provider_execution": "passed",
        },
        "connection_selection": {
            "list_status": "ready",
            "account_count": 1,
            "active_connection_found": True,
            "selected_connection_hash_present": True,
            "selected_connection_source": "listing",
            "opaque_connection_included": False,
        },
        "activation": {
            "execution": {
                "status": "ready",
                "ready_to_execute_readonly": True,
                "selected_connection_hash_present": True,
                "scope_policy": _allowed_scope_policy_summary(),
            },
        },
        "execution_gateway": {
            "status": "allowed",
            "reason": "allowed",
            "selected_connection_hash_present": True,
            "argument_key_count": 1,
            "scope_policy": _allowed_scope_policy_summary(),
            "provider_execution_attempted": False,
        },
        "readonly_execution": {
            "status": "succeeded",
            "reason": "succeeded",
            "provider_slug": "gmail",
            "action_slug": "GMAIL_FETCH_EMAILS",
            "selected_connection_hash_present": True,
            "schema": {
                "status": "ready",
                "schema_present": True,
                "provider_slug": "gmail",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "argument_key_count": 2,
                "required_argument_key_count": 1,
                "required_argument_keys_present": True,
                "raw_schema_included": False,
            },
            "execution": {
                "status": "succeeded",
                "successful": True,
                "provider_slug": "gmail",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "status_code": 200,
                "data_key_count": 1,
                "error_present": False,
                "session_info_present": False,
                "log_id_present": True,
                "provider_response_included": False,
            },
            "provider_payload_included": False,
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "opaque_connection_included": False,
            "provider_payload_included": False,
            "provider_arguments_included": False,
            "provider_response_included": False,
            "raw_schema_included": False,
            "connect_link_included": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
            "raw_backend_url_included": False,
            "raw_connection_locator_included": False,
        },
        "checks": [],
    }


def _proactive_pass_payload() -> dict:
    return {
        "schema_version": probe.PROACTIVE_CHANNEL_SCHEMA_VERSION,
        "generated_at": "2026-06-03T00:00:00+00:00",
        "status": "pass",
        "channel": "telegram",
        "delivered": True,
        "recipient_id_hash": "recipient-hash",
        "recipient_id_hash_present": True,
        "organization_id_hash": "org-hash",
        "organization_id_hash_present": True,
        "message_hash": "message-hash",
        "message_hash_present": True,
        "message_char_count": 42,
        "trigger": "operator_live_channel_probe",
        "evidence_contract": {
            "single_outbound_send": True,
            "uses_proactive_messenger": True,
            "requires_live_channel_credentials": True,
            "requires_database_guardrail": True,
            "delivery_adapter_boundary": "configured_channel_sender",
            "identifier_strategy": "hash_or_count_only",
        },
        "database": {
            "connection_verified": True,
            "opt_out_lookup_verifiable": True,
            "send_audit_verifiable": True,
            "opt_out_scope_request_org": True,
            "send_audit_scope_request_org": True,
            "raw_connection_details_included": False,
        },
        "org_scope": {
            "context_token_set": True,
            "organization_id_hash_present": True,
            "write_scope_expected": "request_scoped",
            "raw_organization_identifier_included": False,
        },
        "operator_approval": {
            "allow_send_acknowledged": True,
            "approved_recipient_hash_present": True,
            "raw_recipient_identifier_included": False,
            "raw_message_included": False,
        },
        "guardrail": {
            "allowed": True,
            "reason_allowed": True,
            "blocked_metric_count": 0,
            "decision_source": "ProactiveMessenger.can_send",
            "database_opt_out_check_used": True,
            "opt_out_checked_via_database": True,
        },
        "delivery": {
            "channel": "telegram",
            "delivered": True,
            "status": "delivered",
            "channel_matches_request": True,
            "duration_observed": True,
            "duration_ms_min": 12.5,
            "duration_ms_count": 1,
            "raw_delivery_payload_included": False,
        },
        "send_attempt": {
            "channel": "telegram",
            "channel_supported": True,
            "trigger": "operator_live_channel_probe",
            "priority": 0.1,
            "single_send_attempt": True,
            "recipient_id_hash_present": True,
            "organization_id_hash_present": True,
            "message_hash_present": True,
            "raw_message_included": False,
        },
        "channel_contract": {
            "requested_channel": "telegram",
            "requested_channel_supported": True,
            "requested_channel_matches_delivery": True,
            "supported_channel_count": 3,
            "credential_configured": True,
            "credential_value_included": False,
            "credential_name_value_pair_included": False,
        },
        "channel_config": {
            "supported": True,
            "enabled": True,
            "credential_present": True,
            "credential_name": "TELEGRAM_BOT_TOKEN",
            "credential_value_included": False,
        },
        "metrics": {
            "can_send_event_count": 1,
            "sends_event_count": 1,
            "can_send_allowed_count": 1,
            "send_delivered_count": 1,
            "send_duration_count": 1,
            "send_duration_observed": True,
            "send_duration_ms_min": 12.5,
            "duration_metric_label_status_delivered_seen": True,
            "metric_labels_include_identifiers": False,
            "metric_label_strategy": "bounded_status_reason_channel_only",
            "raw_metric_payload_included": False,
            "can_send_allowed_seen": True,
            "send_delivered_seen": True,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_message_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_channel_credentials_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "credential_name_value_pair_included": False,
            "raw_trigger_target_included": False,
            "metric_labels_include_identifiers": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def _bundle_report_for_artifacts(
    artifact_paths: dict[str, Path],
    *,
    status_by_artifact: dict[str, str] | None = None,
    sha_by_artifact: dict[str, str] | None = None,
) -> dict:
    status_by_artifact = status_by_artifact or {}
    sha_by_artifact = sha_by_artifact or {}
    rows = []
    for artifact, path in artifact_paths.items():
        rows.append(
            {
                "requirement_id": artifact.removesuffix(".json"),
                "artifact": artifact,
                "status": status_by_artifact.get(artifact, "passed"),
                "path": str(path),
                "artifact_sha256": sha_by_artifact.get(
                    artifact,
                    probe.attestation_generator._sha256_file(path),
                ),
                "checks_passed": 12,
                "generated_at": "2026-06-03T00:00:00+00:00",
                "max_age_hours": 72,
                "age_hours": 1.0,
                "errors": [],
                "error_codes": [],
            }
        )
    return {
        "schema_version": probe.RUNTIME_EVIDENCE_BUNDLE_REPORT_SCHEMA_VERSION,
        "registry_name": "Wiii Runtime Evidence Registry",
        "registry_version": 1,
        "bundle_root": "runtime-evidence",
        "validated_at": "2026-06-03T00:00:00+00:00",
        "registry_fingerprint_sha256": "registry",
        "bundle_fingerprint_sha256": "bundle",
        "completion_audit_fingerprint_sha256": "completion",
        "self_harness_report_bundle_root": "self-harness",
        "self_harness_report_bundle_fingerprint_sha256": "self-harness-sha",
        "self_harness_report_bundle_validation_schema_version": (
            "wiii.self_harness_report_bundle_validation.v1"
        ),
        "requirement_count": len(rows),
        "row_count": len(rows),
        "passed_count": sum(1 for row in rows if row["status"] == "passed"),
        "missing_count": 0,
        "failed_count": sum(1 for row in rows if row["status"] != "passed"),
        "unexpected_count": 0,
        "error_codes": [],
        "error_code_counts": {},
        "rows": rows,
        "ok": all(row["status"] == "passed" for row in rows),
        "completion_audit_ready": True,
    }


class ProbeCompletionAuditSetupHandleEvidenceTests(unittest.TestCase):
    def test_env_probe_writes_evidence_consumed_by_attestation_generator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            plan_payload = _load_json(plan_path)
            evidence_path = root / "setup-handle-evidence.json"
            attestation_path = root / "setup-attestation.json"
            env = _env_for_pending_checks(plan_payload)

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(probe, "_backend_health_check", return_value=True),
            ):
                evidence = probe.probe_completion_audit_setup_handle_evidence(
                    plan_path,
                    allow_env_read=True,
                    allow_network=True,
                )
            _write_json(evidence_path, evidence)
            attestation = (
                attestation_from_handles.generate_completion_audit_setup_attestation_from_handles(
                    plan_path,
                    evidence_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
            _write_json(attestation_path, attestation)
            rendered = json.dumps(evidence, sort_keys=True)

        self.assertGreater(evidence["handle_count"], 0)
        self.assertLess(evidence["handle_count"], plan_payload["pending_setup_check_count"])
        self.assertEqual(evidence["handle_count"], attestation["attestation_count"])
        self.assertNotIn("private-", rendered)
        self.assertNotIn("https://backend.example", rendered)
        self.assertFalse(evidence["privacy"]["secret_values_included"])
        self.assertFalse(evidence["privacy"]["raw_identifiers_included"])
        self.assertTrue(
            any(
                handle["evidence_kind"] == "environment_flag_bound"
                for handle in evidence["handles"]
            )
        )

    def test_cli_writes_handle_evidence_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            env = _env_for_pending_checks(_load_json(plan_path))
            evidence_path = root / "setup-handle-evidence.json"

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(probe, "_backend_health_check", return_value=True),
            ):
                exit_code = probe.main(
                    [
                        str(plan_path),
                        "--allow-env-read",
                        "--allow-network",
                        "--out",
                        str(evidence_path),
                    ]
                )
            payload = _load_json(evidence_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(
            probe.handle_generator.SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION,
            payload["schema_version"],
        )
        self.assertGreater(payload["handle_count"], 0)

    def test_cli_requires_explicit_env_read_ack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            env = _env_for_pending_checks(_load_json(plan_path))
            stdout = io.StringIO()

            with (
                mock.patch.dict(os.environ, env, clear=True),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = probe.main([str(plan_path)])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_evidence_probe_no_handles"],
            payload["error_codes"],
        )

    def test_backend_health_handle_requires_network_ack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            plan_payload = _load_json(plan_path)
            backend_token = next(
                check["binding_tokens"][0]
                for item in plan_payload["plan_items"]
                for check in item["setup_checks"]
                if not check["present"]
                and check["recommended_evidence_kinds"] == ["backend_health_checked"]
            )
            env = {backend_token: "https://backend.example"}

            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError) as exc:
                    probe.probe_completion_audit_setup_handle_evidence(
                        plan_path,
                        allow_env_read=True,
                        allow_network=False,
                    )
            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(probe, "_backend_health_check", return_value=True),
            ):
                evidence = probe.probe_completion_audit_setup_handle_evidence(
                    plan_path,
                    allow_env_read=True,
                    allow_network=True,
                )

        self.assertIn("found no valid handles", str(exc.exception))
        self.assertEqual(1, evidence["handle_count"])
        self.assertEqual("backend_health_checked", evidence["handles"][0]["evidence_kind"])

    def test_composio_pass_evidence_adds_runtime_setup_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            composio_path = root / "wiii-connect-composio-acceptance-evidence.json"
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(composio_path, _composio_pass_payload())

            evidence = probe.probe_completion_audit_setup_handle_evidence(
                plan_path,
                composio_acceptance_evidence_path=composio_path,
            )
            _write_json(evidence_path, evidence)
            attestation = (
                attestation_from_handles.generate_completion_audit_setup_attestation_from_handles(
                    plan_path,
                    evidence_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
            rendered = json.dumps(evidence, sort_keys=True)

        handles_by_key = {handle["key"]: handle for handle in evidence["handles"]}
        self.assertEqual(3, evidence["handle_count"])
        self.assertEqual(
            {
                "connected_provider_account",
                "execution_gateway_scope_policy",
                "readonly_action_schema",
            },
            set(handles_by_key),
        )
        self.assertEqual(
            "--expect-connected",
            handles_by_key["connected_provider_account"]["source_handle"],
        )
        self.assertEqual(
            "--require-execution-ready",
            handles_by_key["execution_gateway_scope_policy"]["source_handle"],
        )
        self.assertEqual(
            "--execute-readonly",
            handles_by_key["readonly_action_schema"]["source_handle"],
        )
        self.assertEqual(3, attestation["attestation_count"])
        for handle in evidence["handles"]:
            self.assertIn("composio_acceptance_sha256", handle["evidence_ref"])
        self.assertNotIn("gmail", rendered)
        self.assertNotIn("GMAIL_FETCH_EMAILS", rendered)
        self.assertNotIn("wiii.example.com", rendered)
        self.assertFalse(evidence["privacy"]["raw_payload_included"])

    def test_proactive_pass_evidence_adds_runtime_setup_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            proactive_path = root / "autonomy-proactive-channel-evidence.json"
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(proactive_path, _proactive_pass_payload())

            evidence = probe.probe_completion_audit_setup_handle_evidence(
                plan_path,
                proactive_channel_evidence_path=proactive_path,
            )
            _write_json(evidence_path, evidence)
            attestation = (
                attestation_from_handles.generate_completion_audit_setup_attestation_from_handles(
                    plan_path,
                    evidence_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
            rendered = json.dumps(evidence, sort_keys=True)

        handles_by_key = {handle["key"]: handle for handle in evidence["handles"]}
        self.assertEqual(3, evidence["handle_count"])
        self.assertEqual(
            {
                "selected_channel_credential",
                "approved_recipient",
                "selected_channel_enabled",
            },
            set(handles_by_key),
        )
        self.assertEqual(
            "TELEGRAM_BOT_TOKEN",
            handles_by_key["selected_channel_credential"]["source_handle"],
        )
        self.assertEqual(
            "proactive_recipient_id",
            handles_by_key["approved_recipient"]["source_handle"],
        )
        self.assertEqual(
            "ENABLE_TELEGRAM",
            handles_by_key["selected_channel_enabled"]["source_handle"],
        )
        self.assertEqual(
            "runtime_channel_credential_validated",
            handles_by_key["selected_channel_credential"]["evidence_kind"],
        )
        self.assertEqual(
            "runtime_channel_enabled",
            handles_by_key["selected_channel_enabled"]["evidence_kind"],
        )
        self.assertEqual(3, attestation["attestation_count"])
        for handle in evidence["handles"]:
            self.assertIn("proactive_channel_sha256", handle["evidence_ref"])
        self.assertNotIn("recipient-hash", rendered)
        self.assertNotIn("org-hash", rendered)
        self.assertNotIn("message-hash", rendered)
        self.assertFalse(evidence["privacy"]["raw_payload_included"])

    def test_cli_reads_composio_acceptance_evidence_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            composio_path = root / "wiii-connect-composio-acceptance-evidence.json"
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(composio_path, _composio_pass_payload())

            exit_code = probe.main(
                [
                    str(plan_path),
                    "--composio-acceptance-evidence",
                    str(composio_path),
                    "--out",
                    str(evidence_path),
                ]
            )
            payload = _load_json(evidence_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(3, payload["handle_count"])

    def test_cli_reads_proactive_channel_evidence_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            proactive_path = root / "autonomy-proactive-channel-evidence.json"
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(proactive_path, _proactive_pass_payload())

            exit_code = probe.main(
                [
                    str(plan_path),
                    "--proactive-channel-evidence",
                    str(proactive_path),
                    "--out",
                    str(evidence_path),
                ]
            )
            payload = _load_json(evidence_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(3, payload["handle_count"])

    def test_runtime_evidence_dir_discovers_canonical_pass_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            bundle_dir.mkdir()
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(
                bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME,
                _proactive_pass_payload(),
            )
            _write_json(
                bundle_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME,
                _composio_pass_payload(),
            )

            evidence = probe.probe_completion_audit_setup_handle_evidence(
                plan_path,
                runtime_evidence_dir=bundle_dir,
            )
            _write_json(evidence_path, evidence)
            attestation = (
                attestation_from_handles.generate_completion_audit_setup_attestation_from_handles(
                    plan_path,
                    evidence_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
            rendered = json.dumps(evidence, sort_keys=True)

        self.assertEqual(6, evidence["handle_count"])
        self.assertEqual(6, attestation["attestation_count"])
        self.assertIn("proactive_channel_sha256", rendered)
        self.assertIn("composio_acceptance_sha256", rendered)
        self.assertNotIn("recipient-hash", rendered)
        self.assertNotIn("gmail", rendered)

    def test_runtime_evidence_dir_discovers_nested_downloaded_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            proactive_dir = bundle_dir / "autonomy-proactive-channel"
            composio_dir = bundle_dir / "wiii-connect-composio-acceptance"
            proactive_dir.mkdir(parents=True)
            composio_dir.mkdir(parents=True)
            _write_json(
                proactive_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME,
                _proactive_pass_payload(),
            )
            _write_json(
                composio_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME,
                _composio_pass_payload(),
            )

            evidence = probe.probe_completion_audit_setup_handle_evidence(
                plan_path,
                runtime_evidence_dir=bundle_dir,
            )

        self.assertEqual(6, evidence["handle_count"])
        self.assertEqual(
            {
                "selected_channel_credential",
                "approved_recipient",
                "selected_channel_enabled",
                "connected_provider_account",
                "execution_gateway_scope_policy",
                "readonly_action_schema",
            },
            {handle["key"] for handle in evidence["handles"]},
        )

    def test_runtime_evidence_dir_requires_matching_bundle_report_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            bundle_dir.mkdir()
            proactive_path = bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME
            composio_path = bundle_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME
            report_path = root / "runtime-evidence-bundle-report.json"
            _write_json(proactive_path, _proactive_pass_payload())
            _write_json(composio_path, _composio_pass_payload())
            _write_json(
                report_path,
                _bundle_report_for_artifacts(
                    {
                        probe.PROACTIVE_CHANNEL_ARTIFACT_NAME: proactive_path,
                        probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME: composio_path,
                    }
                ),
            )

            evidence = probe.probe_completion_audit_setup_handle_evidence(
                plan_path,
                runtime_evidence_dir=bundle_dir,
                runtime_evidence_bundle_report_path=report_path,
            )

        self.assertEqual(6, evidence["handle_count"])

    def test_cli_rejects_failed_bundle_report_artifact_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            bundle_dir.mkdir()
            proactive_path = bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME
            composio_path = bundle_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME
            report_path = root / "runtime-evidence-bundle-report.json"
            _write_json(proactive_path, _proactive_pass_payload())
            _write_json(composio_path, _composio_pass_payload())
            _write_json(
                report_path,
                _bundle_report_for_artifacts(
                    {
                        probe.PROACTIVE_CHANNEL_ARTIFACT_NAME: proactive_path,
                        probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME: composio_path,
                    },
                    status_by_artifact={
                        probe.PROACTIVE_CHANNEL_ARTIFACT_NAME: "failed",
                    },
                ),
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = probe.main(
                    [
                        str(plan_path),
                        "--runtime-evidence-dir",
                        str(bundle_dir),
                        "--runtime-evidence-bundle-report",
                        str(report_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            [
                "completion_audit_setup_handle_evidence_probe_runtime_artifact_unvalidated"
            ],
            payload["error_codes"],
        )

    def test_cli_rejects_bundle_report_artifact_sha_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            bundle_dir.mkdir()
            proactive_path = bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME
            composio_path = bundle_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME
            report_path = root / "runtime-evidence-bundle-report.json"
            _write_json(proactive_path, _proactive_pass_payload())
            _write_json(composio_path, _composio_pass_payload())
            _write_json(
                report_path,
                _bundle_report_for_artifacts(
                    {
                        probe.PROACTIVE_CHANNEL_ARTIFACT_NAME: proactive_path,
                        probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME: composio_path,
                    },
                    sha_by_artifact={
                        probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME: "not-the-real-sha",
                    },
                ),
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = probe.main(
                    [
                        str(plan_path),
                        "--runtime-evidence-dir",
                        str(bundle_dir),
                        "--runtime-evidence-bundle-report",
                        str(report_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            [
                "completion_audit_setup_handle_evidence_probe_runtime_artifact_sha_mismatch"
            ],
            payload["error_codes"],
        )

    def test_cli_reads_runtime_evidence_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            bundle_dir.mkdir()
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(
                bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME,
                _proactive_pass_payload(),
            )
            _write_json(
                bundle_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME,
                _composio_pass_payload(),
            )

            exit_code = probe.main(
                [
                    str(plan_path),
                    "--runtime-evidence-dir",
                    str(bundle_dir),
                    "--out",
                    str(evidence_path),
                ]
            )
            payload = _load_json(evidence_path)

        self.assertEqual(0, exit_code)
        self.assertEqual(6, payload["handle_count"])

    def test_cli_rejects_duplicate_runtime_evidence_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            bundle_dir = root / "runtime-evidence"
            nested_dir = bundle_dir / "nested"
            nested_dir.mkdir(parents=True)
            _write_json(
                bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME,
                _proactive_pass_payload(),
            )
            _write_json(
                nested_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME,
                _proactive_pass_payload(),
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = probe.main(
                    [
                        str(plan_path),
                        "--runtime-evidence-dir",
                        str(bundle_dir),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            [
                "completion_audit_setup_handle_evidence_probe_runtime_artifact_duplicate"
            ],
            payload["error_codes"],
        )

    def test_cli_rejects_invalid_runtime_evidence_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            not_dir = root / "not-a-dir.json"
            not_dir.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = probe.main(
                    [
                        str(plan_path),
                        "--runtime-evidence-dir",
                        str(not_dir),
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(1, exit_code)
        self.assertEqual(
            ["completion_audit_setup_handle_evidence_probe_runtime_dir_invalid"],
            payload["error_codes"],
        )

    def test_composio_failure_and_preflight_artifacts_do_not_unlock_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            failure = _composio_pass_payload()
            failure["status"] = "fail"
            failure["summary"] = {
                "passed": 11,
                "failed": 1,
                "total": 12,
                "success": False,
            }
            preflight = {
                "schema_version": "wiii.connect_composio_acceptance_preflight.v1",
                "status": "pass",
                "summary": {"success": True, "failed": 0},
            }

            for name, payload in {
                "failure": failure,
                "preflight": preflight,
            }.items():
                composio_path = root / f"{name}.json"
                _write_json(composio_path, payload)
                with self.subTest(name=name):
                    with self.assertRaises(ValueError) as exc:
                        probe.probe_completion_audit_setup_handle_evidence(
                            plan_path,
                            composio_acceptance_evidence_path=composio_path,
                        )
                    self.assertIn("found no valid handles", str(exc.exception))

    def test_proactive_failure_preflight_and_missing_approval_do_not_unlock_handles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            failure = _proactive_pass_payload()
            failure["status"] = "fail"
            failure["delivered"] = False
            preflight = {
                "schema_version": "wiii.proactive_channel_preflight.v1",
                "status": "pass",
                "delivered": True,
            }
            missing_approval = _proactive_pass_payload()
            missing_approval.pop("operator_approval")

            for name, payload in {
                "failure": failure,
                "preflight": preflight,
                "missing_approval": missing_approval,
            }.items():
                proactive_path = root / f"{name}.json"
                _write_json(proactive_path, payload)
                with self.subTest(name=name):
                    with self.assertRaises(ValueError) as exc:
                        probe.probe_completion_audit_setup_handle_evidence(
                            plan_path,
                            proactive_channel_evidence_path=proactive_path,
                        )
                    self.assertIn("found no valid handles", str(exc.exception))

    def test_composio_gateway_handle_requires_scope_policy_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _launch_pack_path, _setup_state_path, plan_path = _write_plan(root)
            composio_path = root / "wiii-connect-composio-acceptance-evidence.json"
            payload = _composio_pass_payload()
            payload["execution_gateway"]["scope_policy"]["read_allowed"] = False
            _write_json(composio_path, payload)

            evidence = probe.probe_completion_audit_setup_handle_evidence(
                plan_path,
                composio_acceptance_evidence_path=composio_path,
            )

        keys = {handle["key"] for handle in evidence["handles"]}
        self.assertEqual(
            {
                "connected_provider_account",
                "readonly_action_schema",
            },
            keys,
        )
        self.assertEqual(2, evidence["handle_count"])

    def test_env_and_runtime_pass_handles_cover_operator_setup_handles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            launch_pack_path, setup_state_path, plan_path = _write_plan(root)
            plan_payload = _load_json(plan_path)
            bundle_dir = root / "runtime-evidence"
            bundle_dir.mkdir()
            evidence_path = root / "setup-handle-evidence.json"
            _write_json(
                bundle_dir / probe.COMPOSIO_ACCEPTANCE_ARTIFACT_NAME,
                _composio_pass_payload(),
            )
            _write_json(
                bundle_dir / probe.PROACTIVE_CHANNEL_ARTIFACT_NAME,
                _proactive_pass_payload(),
            )
            env = _env_for_pending_checks(plan_payload)

            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(probe, "_backend_health_check", return_value=True),
            ):
                evidence = probe.probe_completion_audit_setup_handle_evidence(
                    plan_path,
                    allow_env_read=True,
                    allow_network=True,
                    runtime_evidence_dir=bundle_dir,
                )
            _write_json(evidence_path, evidence)
            attestation = (
                attestation_from_handles.generate_completion_audit_setup_attestation_from_handles(
                    plan_path,
                    evidence_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
            covered = {
                (handle["category"], handle["key"])
                for handle in evidence["handles"]
            }

        self.assertEqual(10, evidence["handle_count"])
        self.assertEqual(
            {
                ("environment_flags_required", "live_proactive_channel_probe_flag"),
                ("credential_slots_required", "selected_channel_credential"),
                ("external_setup_required", "approved_recipient"),
                ("external_setup_required", "selected_channel_enabled"),
                ("environment_flags_required", "live_composio_acceptance_flag"),
                ("credential_slots_required", "acceptance_bearer_token"),
                ("external_setup_required", "connected_provider_account"),
                ("external_setup_required", "execution_gateway_scope_policy"),
                ("external_setup_required", "readonly_action_schema"),
                ("external_setup_required", "staging_or_live_backend"),
            },
            covered,
        )
        self.assertEqual(evidence["handle_count"], attestation["attestation_count"])


if __name__ == "__main__":
    unittest.main()
