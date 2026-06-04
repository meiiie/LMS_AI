import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import validate_runtime_evidence_preflight as validator


GENERATED_AT = "2026-06-02T12:00:00+00:00"
SETUP_CONTRACT_VERSION = "wiii.live_evidence_setup_contract.v1"


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _provider_preflight() -> dict:
    return {
        "schema_version": "wiii.provider_runtime_preflight.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "requested_provider": "auto",
        "selected_provider": None,
        "tier": "premium",
        "allow_call_acknowledged": True,
        "live_env_flag_set": True,
        "include_stream_ledger": False,
        "allow_stream_write_acknowledged": False,
        "production_environment": False,
        "allow_production_acknowledged": False,
        "provider_status_counts": {
            "total": 1,
            "configured": 1,
            "request_selectable": 1,
        },
        "providers": [
            {
                "provider": "nvidia",
                "configured": True,
                "request_selectable": True,
            }
        ],
        "required_next": [],
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "raw_request_identifiers_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
        },
    }


def _proactive_preflight() -> dict:
    required_next = [
        "provide_recipient_id",
        "enable_selected_channel",
        "configure_selected_channel_credential",
    ]
    return {
        "schema_version": "wiii.proactive_channel_preflight.v1",
        "generated_at": GENERATED_AT,
        "status": "fail",
        "requested_channel": "telegram",
        "allow_send_acknowledged": True,
        "live_env_flag_set": True,
        "recipient_id_present": False,
        "production_environment": False,
        "allow_production_acknowledged": False,
        "live_send_attempted": False,
        "channel_config": {
            "supported": True,
            "enabled": False,
            "credential_present": False,
            "credential_value_included": False,
            "credential_name_included": False,
        },
        "required_next": required_next,
        "setup_contract": {
            "version": SETUP_CONTRACT_VERSION,
            "requirement_id": "autonomy-proactive-channel",
            "required_next": required_next,
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


def _composio_preflight() -> dict:
    required_next = [
        "configure_backend_url",
        "configure_acceptance_bearer_token",
    ]
    return {
        "schema_version": "wiii.connect_composio_acceptance_preflight.v1",
        "generated_at": GENERATED_AT,
        "status": "fail",
        "requested_provider": "gmail",
        "requested_action": "gmail_search",
        "allow_live_acknowledged": True,
        "live_env_flag_set": True,
        "live_backend_call_attempted": False,
        "provider_execution_attempted": False,
        "backend": {
            "valid": False,
            "placeholder": True,
            "scheme": "https",
            "host_hash_present": True,
            "origin_hash_present": True,
            "raw_backend_url_included": False,
        },
        "authentication": {
            "mode": "bearer",
            "bearer_token_present": False,
            "bearer_source": "none",
            "dev_login_allowed_by_mode": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
        },
        "flags": {
            "expect_connected": True,
            "require_execution_ready": True,
            "execute_readonly": True,
            "skip_connect_link": True,
            "explicit_connection_selection_present": False,
        },
        "arguments": {
            "valid_json_object": True,
            "argument_key_count": 2,
            "arguments_present": True,
            "raw_arguments_included": False,
        },
        "required_next": required_next,
        "setup_contract": {
            "version": SETUP_CONTRACT_VERSION,
            "requirement_id": "wiii-connect-composio-acceptance",
            "required_next": required_next,
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


def _lms_preflight() -> dict:
    required_next = [
        "pass_allow_write",
        "pass_allow_external_lms_write",
        "set_live_lms_test_course_replay_flag",
        "configure_external_lms_apply_url",
        "configure_external_lms_apply_token",
    ]
    return {
        "schema_version": "wiii.lms_test_course_preflight.v1",
        "generated_at": GENERATED_AT,
        "status": "fail",
        "allow_write_acknowledged": False,
        "allow_external_lms_write_acknowledged": False,
        "live_env_flag_set": False,
        "production_environment": False,
        "allow_production_acknowledged": False,
        "live_write_attempted": False,
        "external_lms_write_attempted": False,
        "backend": {
            "transport_mode": "asgi",
            "base_url_local": True,
            "raw_base_url_included": False,
        },
        "authentication": {
            "auth_mode": "auto",
            "bearer_token_present": False,
            "bearer_value_included": False,
        },
        "external_lms": {
            "apply_url_present": False,
            "apply_token_present": False,
            "endpoint_hash_present": False,
            "raw_endpoint_included": False,
            "raw_token_included": False,
        },
        "required_next": required_next,
        "setup_contract": {
            "version": SETUP_CONTRACT_VERSION,
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
            "environment_flags_required": ["live_lms_test_course_replay_flag"],
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
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "bearer_value_included": False,
            "raw_backend_url_included": False,
            "raw_external_lms_endpoint_included": False,
            "raw_external_lms_token_included": False,
            "raw_request_identifiers_included": False,
            "raw_lms_document_included": False,
        },
    }


class RuntimeEvidencePreflightValidationTests(unittest.TestCase):
    def test_provider_preflight_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "provider-preflight.json", _provider_preflight())

            result = validator.validate_preflight(
                path,
                requirement_id="provider-runtime-tool-loop",
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("provider-runtime-tool-loop", result.requirement_id)

    def test_proactive_fail_preflight_passes_when_required_next_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "proactive-preflight.json", _proactive_preflight())

            result = validator.validate_preflight(
                path,
                requirement_id="autonomy-proactive-channel",
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_composio_fail_preflight_passes_when_privacy_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "composio-preflight.json", _composio_preflight())

            result = validator.validate_preflight(
                path,
                requirement_id="wiii-connect-composio-acceptance",
            )

        self.assertTrue(result.ok, result.to_dict())

    def test_lms_fail_preflight_passes_when_privacy_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "lms-preflight.json", _lms_preflight())

            result = validator.validate_preflight(
                path,
                requirement_id="lms-test-course-replay",
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual("lms-test-course-replay", result.requirement_id)

    def test_requirement_id_must_match_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "provider-preflight.json", _provider_preflight())

            result = validator.validate_preflight(
                path,
                requirement_id="autonomy-proactive-channel",
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_evidence_preflight_requirement_mismatch",
            result.to_dict()["error_codes"],
        )

    def test_pass_status_requires_empty_required_next(self) -> None:
        payload = _provider_preflight()
        payload["required_next"] = ["configure_request_selectable_provider"]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "provider-preflight.json", payload)

            result = validator.validate_preflight(path)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_evidence_preflight_required_next_invalid",
            result.to_dict()["error_codes"],
        )

    def test_sensitive_privacy_flags_must_be_false(self) -> None:
        payload = _proactive_preflight()
        payload["privacy"]["raw_message_included"] = True
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "proactive-preflight.json", payload)

            result = validator.validate_preflight(path)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_evidence_preflight_privacy_invalid",
            result.to_dict()["error_codes"],
        )

    def test_unsupported_fields_are_rejected(self) -> None:
        payload = _composio_preflight()
        payload["raw_backend_url"] = "https://wiii.example.com"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "composio-preflight.json", payload)

            result = validator.validate_preflight(path)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_evidence_preflight_closed_schema_invalid",
            result.to_dict()["error_codes"],
        )

    def test_setup_contract_must_match_required_next(self) -> None:
        payload = _proactive_preflight()
        payload["setup_contract"]["required_next"] = ["different_step"]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "proactive-preflight.json", payload)

            result = validator.validate_preflight(path)

        self.assertFalse(result.ok)
        self.assertIn(
            "runtime_evidence_preflight_required_next_invalid",
            result.to_dict()["error_codes"],
        )

    def test_cli_json_outputs_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "provider-preflight.json", _provider_preflight())
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = validator.main(
                    [
                        str(path),
                        "--requirement-id",
                        "provider-runtime-tool-loop",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual([], payload["error_codes"])


if __name__ == "__main__":
    unittest.main()
