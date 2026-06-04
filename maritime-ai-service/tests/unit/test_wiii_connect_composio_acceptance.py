from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "wiii_connect_composio_acceptance.py"
)
SPEC = importlib.util.spec_from_file_location(
    "wiii_connect_composio_acceptance",
    SCRIPT_PATH,
)
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
assert SPEC.loader is not None
SPEC.loader.exec_module(acceptance)

PREFLIGHT_VALIDATOR_PATH = (
    Path(__file__).parents[3]
    / "tools"
    / "wiii_self_harness"
    / "validate_runtime_evidence_preflight.py"
)
PREFLIGHT_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_runtime_evidence_preflight",
    PREFLIGHT_VALIDATOR_PATH,
)
preflight_validator = importlib.util.module_from_spec(PREFLIGHT_VALIDATOR_SPEC)
sys.modules[PREFLIGHT_VALIDATOR_SPEC.name] = preflight_validator
assert PREFLIGHT_VALIDATOR_SPEC.loader is not None
PREFLIGHT_VALIDATOR_SPEC.loader.exec_module(preflight_validator)


def allowed_read_scope_policy() -> dict[str, object]:
    return {
        "version": acceptance.SCOPE_POLICY_VERSION,
        "status": "allowed",
        "reason": "allowed",
        "provider_slug": "gmail",
        "required_scopes": ["read"],
        "allowed_scopes": ["read"],
    }


def test_join_url_handles_slashes() -> None:
    assert acceptance.join_url("http://localhost:8080/", "/api/v1/health") == (
        "http://localhost:8080/api/v1/health"
    )
    assert acceptance.join_url("http://localhost:8080", "api/v1/health") == (
        "http://localhost:8080/api/v1/health"
    )


def test_parse_json_object_rejects_non_object_payload() -> None:
    with pytest.raises(acceptance.AcceptanceFailure, match="Expected JSON object"):
        acceptance.parse_json_object("[]", source="unit-test")


def test_redact_for_log_removes_tokens_urls_and_connection_ids() -> None:
    payload = {
        "authorization_url": "https://connect.example/callback?wiii_state=abc",
        "connection_id": "ca_secret_123",
        "connection_ref": "wcn_public_ref",
        "nested": {
            "access_token": "secret-token",
            "safe": "visible",
            "items": [{"vault_key_id": "provider-managed://composio/ca_1"}],
        },
    }

    redacted = acceptance.redact_for_log(payload)
    serialized = acceptance.json_for_log(payload)

    assert redacted["authorization_url"] == "[redacted]"
    assert redacted["connection_id"] == "[redacted]"
    assert redacted["connection_ref"] == "[redacted]"
    assert redacted["nested"]["access_token"] == "[redacted]"
    assert redacted["nested"]["items"][0]["vault_key_id"] == "[redacted]"
    assert redacted["nested"]["safe"] == "visible"
    assert "secret-token" not in serialized
    assert "ca_secret_123" not in serialized
    assert "wcn_public_ref" not in serialized
    assert "provider-managed://composio" not in serialized


def test_catalog_helpers_find_adapter_provider_action_and_active_connection() -> None:
    adapter = acceptance.find_adapter(
        {"adapters": [{"provider_kind": "composio", "bound": True}]},
        "composio",
    )
    provider = acceptance.find_provider(
        {"providers": [{"slug": "gmail", "provider_kind": "composio"}]},
        "gmail",
    )
    action = acceptance.find_action(
        {"actions": [{"slug": "GMAIL_FETCH_EMAILS", "mutation": "read"}]},
        "gmail-fetch-emails",
    )
    connection = acceptance.first_connected_connection(
        {
            "connections": [
                {"connection_id": "ca_raw", "state": "connected", "active": True},
                {"connection_id": "ca_old", "state": "disabled", "active": False},
                {"connection_ref": "wcn_live", "state": "connected", "active": True},
            ]
        }
    )

    assert adapter["bound"] is True
    assert provider["provider_kind"] == "composio"
    assert action["mutation"] == "read"
    assert connection["connection_ref"] == "wcn_live"


def test_first_connected_connection_requires_opaque_connection_ref() -> None:
    assert (
        acceptance.first_connected_connection(
            {
                "connections": [
                    {
                        "connection_id": "ca_raw_only",
                        "connection_ref": "ca_raw_only",
                        "state": "connected",
                        "active": True,
                    }
                ]
            }
        )
        is None
    )


def test_catalog_helpers_fail_closed_when_required_items_are_missing() -> None:
    with pytest.raises(acceptance.AcceptanceFailure, match="Adapter kind"):
        acceptance.find_adapter({"adapters": []}, "composio")
    with pytest.raises(acceptance.AcceptanceFailure, match="Provider"):
        acceptance.find_provider({"providers": []}, "gmail")
    with pytest.raises(acceptance.AcceptanceFailure, match="Action"):
        acceptance.find_action({"actions": []}, "GMAIL_FETCH_EMAILS")
    assert acceptance.first_connected_connection({"connections": []}) is None


def test_activation_readiness_helpers_report_blockers() -> None:
    payload = {
        "status": "blocked",
        "ready_to_connect": False,
        "gates": [
            {"key": "provider_adapter", "ready": True, "reason": "ready"},
            {
                "key": "local_connection",
                "ready": False,
                "reason": "connection_missing",
            },
        ],
    }

    assert acceptance.activation_blocker_summary(payload) == (
        "local_connection:connection_missing"
    )
    with pytest.raises(acceptance.AcceptanceFailure, match="ready_to_connect"):
        acceptance.assert_activation_ready(
            payload,
            flag="ready_to_connect",
            label="connect-ready",
        )

    acceptance.assert_activation_ready(
        {"ready_to_connect": True},
        flag="ready_to_connect",
        label="connect-ready",
    )


def test_scope_policy_helper_requires_allowed_read_policy() -> None:
    assert acceptance.assert_scope_policy_allowed(
        {
            "execution_gateway": {
                "status": "allowed",
                "scope_policy": allowed_read_scope_policy(),
            }
        },
        label="activation readiness",
    ) == "scope_policy=allowed required_scopes=read"

    with pytest.raises(acceptance.AcceptanceFailure, match="scope_policy evidence"):
        acceptance.assert_scope_policy_allowed(
            {"execution_gateway": {"status": "allowed"}},
            label="activation readiness",
        )

    with pytest.raises(acceptance.AcceptanceFailure, match="scope policy not allowed"):
        acceptance.assert_scope_policy_allowed(
            {
                "status": "blocked",
                "scope_policy": {
                    **allowed_read_scope_policy(),
                    "status": "blocked",
                    "reason": "scope_policy_denied",
                },
            },
            label="execution gateway",
        )

    with pytest.raises(acceptance.AcceptanceFailure, match="missing required read"):
        acceptance.assert_scope_policy_allowed(
            {
                "status": "allowed",
                "scope_policy": {
                    **allowed_read_scope_policy(),
                    "required_scopes": ["write"],
                },
            },
            label="execution gateway",
        )


def test_activation_readiness_report_lines_are_redacted() -> None:
    payload = {
        "provider_slug": "gmail",
        "status": "blocked",
        "ready_to_connect": False,
        "ready_to_execute_readonly": False,
        "gates": [
            {
                "key": "provider_adapter",
                "ready": False,
                "reason": "missing_composio_api_key",
                "required_next": [
                    "configure_composio_adapter",
                    "https://callback.example/?wiii_state=secret",
                ],
                "metadata": {"api_key": "secret-value"},
            },
            {
                "key": "local_connection",
                "ready": False,
                "reason": "connection_missing",
                "required_next": ["complete_provider_oauth"],
            },
        ],
    }

    report = "\n".join(acceptance.activation_readiness_report_lines(payload))

    assert "provider=gmail" in report
    assert "ready_to_connect=False" in report
    assert "provider_adapter" in report
    assert "configure_composio_adapter" in report
    assert "local_connection: connection_missing" in report
    assert "secret-value" not in report
    assert "wiii_state=secret" not in report
    assert "missing_composio_api_key" not in report


def test_activation_readiness_payload_uses_backend_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def json(self):
            return {
                "ready_to_connect": True,
                "ready_to_execute_readonly": False,
                "gates": [],
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["payload"] = payload
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
        )
    )
    harness.token = "token"

    payload = harness.activation_readiness_payload(connection_ref="wcn_live")

    assert payload["ready_to_connect"] is True
    assert captured["method"] == "GET"
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert captured["payload"] is None
    url = str(captured["url"])
    assert url.startswith(
        "http://localhost:8080/api/v1/wiii-connect/providers/gmail/"
        "activation-readiness?"
    )
    assert "probe_database=true" in url
    assert "action_slug=GMAIL_FETCH_EMAILS" in url
    assert "connection_ref=wcn_live" in url


def test_activation_ready_to_execute_requires_scope_policy_proof(
    monkeypatch,
) -> None:
    class FakeResponse:
        def json(self):
            return {
                "status": "ready",
                "ready_to_execute_readonly": True,
                "execution_gateway": {
                    "status": "allowed",
                    "scope_policy": allowed_read_scope_policy(),
                },
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            connection_ref="wcn_live",
        )
    )
    harness.token = "token"

    detail = harness.check_activation_ready_to_execute()

    assert "ready_to_execute_readonly=true" in detail
    assert "scope_policy=allowed" in detail
    observed = harness.observations["activation_execution"]
    assert observed["selected_connection_hash_present"] is True
    assert observed["scope_policy"]["version"] == acceptance.SCOPE_POLICY_VERSION
    assert observed["scope_policy"]["read_required"] is True
    assert observed["scope_policy"]["read_allowed"] is True


def test_activation_ready_to_execute_rejects_missing_scope_policy(
    monkeypatch,
) -> None:
    class FakeResponse:
        def json(self):
            return {
                "status": "ready",
                "ready_to_execute_readonly": True,
                "execution_gateway": {"status": "allowed"},
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            connection_ref="wcn_live",
        )
    )
    harness.token = "token"

    with pytest.raises(acceptance.AcceptanceFailure, match="scope_policy evidence"):
        harness.check_activation_ready_to_execute()


def test_gateway_fail_closed_check_requires_connection_selection_reason(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def json(self):
            return {
                "status": "blocked",
                "reason": "connection_selection_required",
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            argument_keys="query,access_token",
            arguments_json="{}",
        )
    )
    harness.token = "token"

    detail = harness.check_gateway_blocks_missing_connection()

    assert detail == "blocked reason=connection_selection_required"
    assert captured["method"] == "POST"
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert captured["payload"] == {
        "surface": "acceptance_harness",
        "action_slug": "GMAIL_FETCH_EMAILS",
        "path": "external_app_action",
        "mutation": "read",
        "argument_keys": ["query", "access_token"],
    }


def test_gateway_fail_closed_check_rejects_generic_block_reason(monkeypatch) -> None:
    class FakeResponse:
        def json(self):
            return {
                "status": "blocked",
                "reason": "connection_missing",
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            argument_keys="",
            arguments_json='{"query": "from:me"}',
        )
    )
    harness.token = "token"

    with pytest.raises(
        acceptance.AcceptanceFailure,
        match="explicit connection selection",
    ):
        harness.check_gateway_blocks_missing_connection()


def test_execution_gateway_allowed_requires_scope_policy_proof(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def json(self):
            return {
                "status": "allowed",
                "reason": "allowed",
                "scope_policy": allowed_read_scope_policy(),
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            connection_ref="wcn_live",
            argument_keys="",
            arguments_json='{"query": "from:me"}',
        )
    )
    harness.token = "token"

    detail = harness.check_execution_gateway_allowed()

    assert "allowed scope_policy=allowed" in detail
    observed = harness.observations["execution_gateway"]
    assert observed["status"] == "allowed"
    assert observed["selected_connection_hash_present"] is True
    assert observed["argument_key_count"] == 1
    assert observed["scope_policy"]["required_scope_count"] == 1
    assert observed["provider_execution_attempted"] is False
    assert captured["method"] == "POST"
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert captured["payload"] == {
        "surface": "acceptance_harness",
        "connection_ref": "wcn_live",
        "action_slug": "GMAIL_FETCH_EMAILS",
        "path": "external_app_action",
        "mutation": "read",
        "argument_keys": ["query"],
    }


def test_execution_gateway_allowed_rejects_blocked_scope_policy(monkeypatch) -> None:
    class FakeResponse:
        def json(self):
            return {
                "status": "allowed",
                "reason": "allowed",
                "scope_policy": {
                    **allowed_read_scope_policy(),
                    "status": "blocked",
                    "reason": "scope_policy_denied",
                },
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            connection_ref="wcn_live",
            argument_keys="",
            arguments_json="{}",
        )
    )
    harness.token = "token"

    with pytest.raises(acceptance.AcceptanceFailure, match="scope policy not allowed"):
        harness.check_execution_gateway_allowed()


def test_readonly_execution_records_schema_execution_and_privacy_proof(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def json(self):
            return {
                "status": "succeeded",
                "reason": "succeeded",
                "schema": {
                    "status": "ready",
                    "provider_slug": "gmail",
                    "action_slug": "GMAIL_FETCH_EMAILS",
                    "schema_present": True,
                    "argument_keys": ["max_results", "query"],
                    "required_argument_keys": ["max_results"],
                },
                "execution": {
                    "status": "succeeded",
                    "successful": True,
                    "provider_slug": "gmail",
                    "action_slug": "GMAIL_FETCH_EMAILS",
                    "status_code": 200,
                    "data_keys": ["messages"],
                    "error_present": False,
                    "session_info_present": False,
                    "log_id_present": True,
                },
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            execution_timeout=11.0,
            org_id="",
            connection_ref="wcn_live",
            argument_keys="",
            arguments_json='{"max_results": 1, "query": "from:me"}',
        )
    )
    harness.token = "token"

    detail = harness.check_readonly_execution()

    observed = harness.observations["readonly_execution"]
    assert "succeeded" in detail
    assert observed["status"] == "succeeded"
    assert observed["selected_connection_hash_present"] is True
    assert observed["schema"]["status"] == "ready"
    assert observed["schema"]["schema_present"] is True
    assert observed["schema"]["required_argument_keys_present"] is True
    assert observed["execution"]["status"] == "succeeded"
    assert observed["execution"]["successful"] is True
    assert observed["execution"]["data_key_count"] == 1
    assert observed["provider_payload_included"] is False
    assert captured["payload"] == {
        "surface": "acceptance_harness",
        "connection_ref": "wcn_live",
        "action_slug": "GMAIL_FETCH_EMAILS",
        "path": "external_app_action",
        "mutation": "read",
        "argument_keys": ["max_results", "query"],
        "arguments": {"max_results": 1, "query": "from:me"},
    }


def test_readonly_execution_requires_schema_proof(monkeypatch) -> None:
    class FakeResponse:
        def json(self):
            return {
                "status": "succeeded",
                "reason": "succeeded",
                "schema": {"status": "blocked", "schema_present": False},
                "execution": {"status": "succeeded", "successful": True},
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            execution_timeout=11.0,
            org_id="",
            connection_ref="wcn_live",
            argument_keys="",
            arguments_json='{"max_results": 1}',
        )
    )
    harness.token = "token"

    with pytest.raises(acceptance.AcceptanceFailure, match="schema readiness"):
        harness.check_readonly_execution()


def test_connection_listing_rejects_raw_connection_id_fallback(monkeypatch) -> None:
    class FakeResponse:
        def json(self):
            return {
                "status": "ready",
                "connections": [
                    {
                        "connection_id": "ca_raw_only",
                        "state": "connected",
                        "active": True,
                    }
                ],
            }

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        return FakeResponse()

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            expect_connected=True,
            require_execution_ready=False,
            execute_readonly=False,
            disconnect=False,
        )
    )
    harness.token = "token"

    with pytest.raises(acceptance.AcceptanceFailure, match="No active connected"):
        harness.check_connections()
    assert harness.selected_connection_ref == ""


def test_validate_evidence_path_rejects_secret_and_generated_locations() -> None:
    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden"):
        acceptance.validate_evidence_path(".env.composio.json")
    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden"):
        acceptance.validate_evidence_path("coverage/wiii-connect.json")
    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden"):
        acceptance.validate_evidence_path("logs/wiii-connect/evidence.json")
    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden"):
        acceptance.validate_evidence_path("screenshots/wiii-connect/evidence.json")
    with pytest.raises(acceptance.AcceptanceFailure, match="must end with .json"):
        acceptance.validate_evidence_path("artifacts/wiii-connect.txt")

    assert (
        acceptance.validate_evidence_path("artifacts/wiii-connect/evidence.json").name
        == "evidence.json"
    )


def test_evidence_payload_redacts_sensitive_details() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="https://wiii.example.com/api?token=secret",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            auth_mode="bearer",
            target_env="staging",
            commit_sha="abc1234",
            readiness_report_only=False,
            skip_connect_link=False,
            print_connect_url=True,
            expect_connected=True,
            require_execution_ready=True,
            execute_readonly=False,
            disconnect=False,
            connection_ref="wcn_secret",
            arguments_json='{"max_results": 1}',
        )
    )
    harness.passed = 1
    harness.failed = 0
    harness.check_records.append(
        harness.check_record(
            "connect link",
            status="passed",
            elapsed=0.2,
            detail=(
                "authorization_url=https://connect.example/callback"
                "?wiii_state=secret connection_ref=wcn_secret"
            ),
        )
    )

    payload = harness.evidence_payload()
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == acceptance.SCHEMA_VERSION
    assert payload["schema"] == "wiii_connect_composio_acceptance_evidence.v1"
    assert payload["status"] == "pass"
    assert payload["backend_origin"] == "https://wiii.example.com"
    assert payload["target_env"] == "staging"
    assert payload["commit_sha"] == "abc1234"
    assert payload["flags"]["explicit_connection_selected"] is True
    assert payload["flags"]["connection_selected_for_action"] is True
    assert payload["flags"]["arguments_present"] is True
    assert payload["evidence_contract"]["external_provider_execution"] is False
    assert payload["privacy"]["raw_content_included"] is False
    assert payload["privacy"]["bearer_env_name_included"] is False
    assert "token=secret" not in serialized
    assert "wiii_state=secret" not in serialized
    assert "wcn_secret" not in serialized
    assert "connection_ref" not in serialized
    assert "WIII_ACCEPTANCE_BEARER_TOKEN" not in serialized
    assert "authorization_url=" not in serialized


def test_evidence_payload_marks_connection_selected_from_listing() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="https://wiii.example.com",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            auth_mode="bearer",
            target_env="staging",
            commit_sha="abc1234",
            readiness_report_only=False,
            skip_connect_link=False,
            print_connect_url=False,
            expect_connected=True,
            require_execution_ready=True,
            execute_readonly=True,
            disconnect=False,
            connection_ref="",
            arguments_json='{"max_results": 1}',
        )
    )
    harness.selected_connection_ref = "wcn_selected_from_listing"

    payload = harness.evidence_payload()
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["flags"]["explicit_connection_selected"] is False
    assert payload["flags"]["connection_selected_for_action"] is True
    assert "wcn_selected_from_listing" not in serialized
    assert "connection_ref" not in serialized


def test_check_status_key_normalizes_acceptance_check_names() -> None:
    assert acceptance.check_status_key("read-only provider execution") == (
        "read_only_provider_execution"
    )
    assert acceptance.check_status_key("execution gateway allowed") == (
        "execution_gateway_allowed"
    )


def test_run_writes_redacted_evidence_json(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    printed: list[str] = []
    evidence_path = tmp_path / "wiii-connect-evidence.json"
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            readiness_report_only=True,
            connection_ref="",
            auth_mode="bearer",
            target_env="local",
            commit_sha="abc1234",
            evidence_json=str(evidence_path),
        )
    )

    def backend_health() -> str:
        calls.append("health")
        return "ok"

    def authenticate() -> str:
        calls.append("auth")
        harness.token = "secret-token"
        return "bearer token"

    def report_payload(*, connection_ref: str = ""):
        calls.append(f"report:{connection_ref or 'none'}")
        return {
            "provider_slug": "gmail",
            "status": "blocked",
            "ready_to_connect": False,
            "ready_to_execute_readonly": False,
            "gates": [
                {
                    "key": "provider_adapter",
                    "ready": False,
                    "reason": "missing_composio_api_key",
                    "required_next": [
                        "configure_composio_adapter",
                        "https://callback.example/?wiii_state=secret",
                    ],
                }
            ],
        }

    monkeypatch.setattr(harness, "check_backend_health", backend_health)
    monkeypatch.setattr(harness, "authenticate", authenticate)
    monkeypatch.setattr(harness, "activation_readiness_payload", report_payload)
    monkeypatch.setattr(
        builtins,
        "print",
        lambda *values, **kwargs: printed.append(
            " ".join(str(value) for value in values)
        ),
    )

    assert harness.run() == 0

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)
    output = "\n".join(printed)

    assert calls == ["health", "auth", "report:none"]
    assert payload["summary"] == {"failed": 0, "passed": 3, "success": True, "total": 3}
    assert [item["name"] for item in payload["checks"]] == [
        "backend health",
        "authentication",
        "activation readiness report",
    ]
    assert "secret-token" not in serialized
    assert "missing_composio_api_key" not in serialized
    assert "wiii_state=secret" not in serialized
    assert "Wrote redacted evidence JSON" in output


def test_run_writes_structured_credentialed_evidence(monkeypatch, tmp_path) -> None:
    evidence_path = tmp_path / "wiii-connect-composio-acceptance-evidence.json"

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self):
            return self.payload

    def fake_request_bytes(method, url, *, headers=None, payload=None, timeout=15.0):
        url_text = str(url)
        if url_text.endswith("/api/v1/health"):
            return FakeResponse({"status": "ok"})
        if url_text.endswith("/api/v1/wiii-connect/providers"):
            return FakeResponse(
                {"providers": [{"slug": "gmail", "provider_kind": "composio"}]}
            )
        if url_text.endswith("/api/v1/wiii-connect/provider-adapters/status"):
            return FakeResponse(
                {
                    "adapters": [
                        {
                            "provider_kind": "composio",
                            "bound": True,
                            "configured": True,
                            "authorization_ready": True,
                            "can_execute_actions": True,
                        }
                    ]
                }
            )
        if "storage/status" in url_text:
            return FakeResponse(
                {
                    "persistent": True,
                    "connection_table_ready": True,
                    "audit_ledger_ready": True,
                }
            )
        if "audit-ledger/status" in url_text:
            return FakeResponse({"persistent": True})
        if url_text.endswith("/api/v1/wiii-connect/providers/gmail/actions"):
            return FakeResponse(
                {
                    "actions": [
                        {
                            "slug": "GMAIL_FETCH_EMAILS",
                            "mutation": "read",
                            "enabled": True,
                        }
                    ]
                }
            )
        if "activation-readiness" in url_text:
            if "connection_ref=" in url_text:
                return FakeResponse(
                    {
                        "status": "ready",
                        "ready_to_connect": True,
                        "ready_to_execute_readonly": True,
                        "execution_gateway": {
                            "status": "allowed",
                            "scope_policy": allowed_read_scope_policy(),
                        },
                    }
                )
            return FakeResponse(
                {
                    "status": "ready",
                    "ready_to_connect": True,
                    "ready_to_execute_readonly": False,
                }
            )
        if url_text.endswith("/api/v1/wiii-connect/providers/gmail/connections?probe_database=true"):
            return FakeResponse(
                {
                    "status": "ready",
                    "connections": [
                        {
                            "connection_ref": "wcn_live_secret",
                            "connected_account_id": "ca_private",
                            "state": "connected",
                            "active": True,
                        }
                    ],
                }
            )
        if url_text.endswith("/api/v1/wiii-connect/providers/gmail/execution-decision"):
            if payload and payload.get("connection_ref"):
                return FakeResponse(
                    {
                        "status": "allowed",
                        "reason": "allowed",
                        "scope_policy": allowed_read_scope_policy(),
                    }
                )
            return FakeResponse(
                {
                    "status": "blocked",
                    "reason": "connection_selection_required",
                }
            )
        if url_text.endswith("/api/v1/wiii-connect/providers/gmail/execute"):
            return FakeResponse(
                {
                    "status": "succeeded",
                    "reason": "succeeded",
                    "schema": {
                        "status": "ready",
                        "provider_slug": "gmail",
                        "action_slug": "GMAIL_FETCH_EMAILS",
                        "schema_present": True,
                        "argument_keys": ["max_results", "query"],
                        "required_argument_keys": ["max_results"],
                    },
                    "execution": {
                        "status": "succeeded",
                        "successful": True,
                        "provider_slug": "gmail",
                        "action_slug": "GMAIL_FETCH_EMAILS",
                        "status_code": 200,
                        "data_keys": ["messages"],
                        "error_present": False,
                        "session_info_present": False,
                        "log_id_present": True,
                    },
                }
            )
        raise AssertionError(f"unexpected request: {method} {url_text}")

    monkeypatch.setattr(acceptance, "request_bytes", fake_request_bytes)
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="https://wiii.example.com",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            execution_timeout=11.0,
            org_id="",
            auth_mode="bearer",
            bearer_token="secret-token",
            readiness_report_only=False,
            skip_connect_link=True,
            print_connect_url=False,
            expect_connected=True,
            require_execution_ready=True,
            execute_readonly=True,
            disconnect=False,
            connection_ref="",
            argument_keys="",
            arguments_json='{"max_results": 1, "query": "from:me"}',
            target_env="staging",
            commit_sha="abc1234",
            evidence_json=str(evidence_path),
        )
    )

    assert harness.run() == 0

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "pass"
    assert payload["runtime"]["observed_section_count"] >= 11
    assert payload["authentication"]["bearer_value_included"] is False
    assert payload["authentication"]["bearer_env_name_included"] is False
    assert payload["connection_selection"]["selected_connection_hash_present"] is True
    assert payload["gateway_fail_closed"]["provider_execution_attempted"] is False
    assert payload["execution_gateway"]["scope_policy"]["read_allowed"] is True
    assert payload["readonly_execution"]["schema"]["schema_present"] is True
    assert (
        payload["readonly_execution"]["schema"]["required_argument_keys_present"]
        is True
    )
    assert payload["readonly_execution"]["execution"]["successful"] is True
    assert (
        payload["readonly_execution"]["execution"]["provider_response_included"]
        is False
    )
    assert "secret-token" not in serialized
    assert "WIII_ACCEPTANCE_BEARER_TOKEN" not in serialized
    assert "connection_ref" not in serialized
    assert "wcn_live_secret" not in serialized
    assert "ca_private" not in serialized
    assert "provider_payload" not in serialized or "provider_payload_included" in serialized


def test_out_runtime_evidence_requires_guard_flag_and_env(monkeypatch, tmp_path) -> None:
    parser = acceptance.build_parser()
    out_path = tmp_path / "wiii-connect-composio-acceptance-evidence.json"

    monkeypatch.setenv(acceptance.ENV_FLAG, "1")
    with pytest.raises(SystemExit, match="--allow-live"):
        acceptance.prepare_acceptance_args(
            parser.parse_args(["--out", str(out_path)])
        )

    monkeypatch.delenv(acceptance.ENV_FLAG, raising=False)
    with pytest.raises(SystemExit, match=acceptance.ENV_FLAG):
        acceptance.prepare_acceptance_args(
            parser.parse_args(["--allow-live", "--out", str(out_path)])
        )


def test_out_runtime_evidence_alias_sets_evidence_json(monkeypatch, tmp_path) -> None:
    parser = acceptance.build_parser()
    out_path = tmp_path / "wiii-connect-composio-acceptance-evidence.json"
    monkeypatch.setenv(acceptance.ENV_FLAG, "1")

    args = acceptance.prepare_acceptance_args(
        parser.parse_args(["--allow-live", "--out", str(out_path)])
    )

    assert args.evidence_json == str(out_path)
    assert acceptance.evidence_output_path(args) == str(out_path)


def test_readiness_report_only_does_not_run_live_connect_or_execute(monkeypatch) -> None:
    calls: list[str] = []
    printed: list[str] = []
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            readiness_report_only=True,
            connection_ref="",
        )
    )

    def backend_health() -> str:
        calls.append("health")
        return "ok"

    def authenticate() -> str:
        calls.append("auth")
        harness.token = "token"
        return "bearer"

    def report_payload(*, connection_ref: str = ""):
        calls.append(f"report:{connection_ref or 'none'}")
        return {
            "provider_slug": "gmail",
            "status": "blocked",
            "ready_to_connect": False,
            "ready_to_execute_readonly": False,
            "gates": [
                {
                    "key": "local_connection",
                    "ready": False,
                    "reason": "connection_missing",
                    "required_next": ["complete_provider_oauth"],
                }
            ],
        }

    def forbidden(*args, **kwargs):
        raise AssertionError("live connect/execution path should not run")

    monkeypatch.setattr(harness, "check_backend_health", backend_health)
    monkeypatch.setattr(harness, "authenticate", authenticate)
    monkeypatch.setattr(harness, "activation_readiness_payload", report_payload)
    monkeypatch.setattr(harness, "check_connect_link", forbidden)
    monkeypatch.setattr(harness, "check_connections", forbidden)
    monkeypatch.setattr(harness, "check_execution_gateway_allowed", forbidden)
    monkeypatch.setattr(harness, "check_readonly_execution", forbidden)
    monkeypatch.setattr(harness, "check_disconnect", forbidden)
    monkeypatch.setattr(
        builtins,
        "print",
        lambda *values, **kwargs: printed.append(
            " ".join(str(value) for value in values)
        ),
    )

    assert harness.run() == 0

    output = "\n".join(printed)
    assert calls == ["health", "auth", "report:none"]
    assert "[REPORT] activation readiness" in output
    assert "complete_provider_oauth" in output


def test_connect_phase_run_issues_connect_link(monkeypatch) -> None:
    calls: list[str] = []
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            readiness_report_only=False,
            skip_connect_link=False,
            expect_connected=False,
            require_execution_ready=False,
            execute_readonly=False,
            disconnect=False,
        )
    )

    monkeypatch.setattr(
        harness,
        "check_backend_health",
        lambda: calls.append("health") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "authenticate",
        lambda: calls.append("auth") or setattr(harness, "token", "token") or "auth",
    )
    monkeypatch.setattr(
        harness,
        "check_provider_registry",
        lambda: calls.append("registry") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_adapter_readiness",
        lambda: calls.append("adapter") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_storage_readiness",
        lambda: calls.append("storage") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_audit_readiness",
        lambda: calls.append("audit") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_curated_actions",
        lambda: (_ for _ in ()).throw(
            AssertionError("connect-only acceptance should not require actions")
        ),
    )
    monkeypatch.setattr(
        harness,
        "check_activation_ready_to_connect",
        lambda: calls.append("connect_ready") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_gateway_blocks_missing_connection",
        lambda: (_ for _ in ()).throw(
            AssertionError("connect-only acceptance should not require execution policy")
        ),
    )
    monkeypatch.setattr(
        harness,
        "check_connect_link",
        lambda: calls.append("connect_link") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_connections",
        lambda: calls.append("connections") or "ok",
    )

    assert harness.run() == 0

    assert "connect_link" in calls
    assert calls == [
        "health",
        "auth",
        "registry",
        "adapter",
        "storage",
        "audit",
        "connect_ready",
        "connect_link",
        "connections",
    ]


def test_facebook_connect_only_run_does_not_require_curated_actions(
    monkeypatch,
) -> None:
    calls: list[str] = []
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="facebook",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            readiness_report_only=False,
            skip_connect_link=False,
            expect_connected=False,
            require_execution_ready=False,
            execute_readonly=False,
            disconnect=False,
        )
    )

    monkeypatch.setattr(
        harness,
        "check_backend_health",
        lambda: calls.append("health") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "authenticate",
        lambda: calls.append("auth") or setattr(harness, "token", "token") or "auth",
    )
    monkeypatch.setattr(
        harness,
        "check_provider_registry",
        lambda: calls.append("registry") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_adapter_readiness",
        lambda: calls.append("adapter") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_storage_readiness",
        lambda: calls.append("storage") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_audit_readiness",
        lambda: calls.append("audit") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_curated_actions",
        lambda: (_ for _ in ()).throw(
            AssertionError("facebook connect-only should not require an action")
        ),
    )
    monkeypatch.setattr(
        harness,
        "check_gateway_blocks_missing_connection",
        lambda: (_ for _ in ()).throw(
            AssertionError("facebook connect-only should not check execution gateway")
        ),
    )
    monkeypatch.setattr(
        harness,
        "check_activation_ready_to_connect",
        lambda: calls.append("connect_ready") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_connect_link",
        lambda: calls.append("connect_link") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_connections",
        lambda: calls.append("connections") or "ok",
    )

    assert harness.run() == 0

    assert calls == [
        "health",
        "auth",
        "registry",
        "adapter",
        "storage",
        "audit",
        "connect_ready",
        "connect_link",
        "connections",
    ]


def test_post_oauth_run_does_not_issue_new_connect_link(monkeypatch) -> None:
    calls: list[str] = []
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8080",
            provider="gmail",
            action="GMAIL_FETCH_EMAILS",
            timeout=7.0,
            org_id="",
            readiness_report_only=False,
            skip_connect_link=False,
            expect_connected=True,
            require_execution_ready=True,
            execute_readonly=False,
            disconnect=False,
        )
    )

    def forbidden_connect_link() -> str:
        raise AssertionError("post-OAuth acceptance must not create a new link")

    monkeypatch.setattr(
        harness,
        "check_backend_health",
        lambda: calls.append("health") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "authenticate",
        lambda: calls.append("auth") or setattr(harness, "token", "token") or "auth",
    )
    monkeypatch.setattr(
        harness,
        "check_provider_registry",
        lambda: calls.append("registry") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_adapter_readiness",
        lambda: calls.append("adapter") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_storage_readiness",
        lambda: calls.append("storage") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_audit_readiness",
        lambda: calls.append("audit") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_curated_actions",
        lambda: calls.append("actions") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_activation_ready_to_connect",
        lambda: calls.append("connect_ready") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_gateway_blocks_missing_connection",
        lambda: calls.append("gateway_block") or "ok",
    )
    monkeypatch.setattr(harness, "check_connect_link", forbidden_connect_link)
    monkeypatch.setattr(
        harness,
        "check_connections",
        lambda: calls.append("connections") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_activation_ready_to_execute",
        lambda: calls.append("execute_ready") or "ok",
    )
    monkeypatch.setattr(
        harness,
        "check_execution_gateway_allowed",
        lambda: calls.append("gateway_allowed") or "ok",
    )

    assert harness.run() == 0

    assert "connect_link" not in calls
    assert calls == [
        "health",
        "auth",
        "registry",
        "adapter",
        "storage",
        "audit",
        "connect_ready",
        "actions",
        "gateway_block",
        "connections",
        "execute_ready",
        "gateway_allowed",
    ]


def test_check_record_redacts_connection_ref_query_strings() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(connection_ref="", selected_connection_ref="")
    )

    record = harness.check_record(
        "activation readiness",
        status="failed",
        elapsed=0.1,
        detail=(
            "GET http://localhost:8080/api/v1/wiii-connect/providers/gmail/"
            "activation-readiness?connection_ref=wcn_public_ref failed"
        ),
    )
    serialized = json.dumps(record, sort_keys=True)

    assert record["detail"] == "[redacted]"
    assert "wcn_public_ref" not in serialized
    assert "connection_ref=" not in serialized


def test_connection_ref_for_action_requires_selected_or_explicit_connection() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(connection_ref="", selected_connection_ref="")
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="No connected account"):
        harness.connection_ref_for_action()

    harness.selected_connection_ref = "wcn_live"
    assert harness.connection_ref_for_action() == "wcn_live"


def test_connection_ref_for_action_rejects_raw_provider_connection_ids() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(connection_ref="ca_raw_provider_id", selected_connection_ref="")
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="not a Wiii opaque ref"):
        harness.connection_ref_for_action()


def test_parser_accepts_connection_ref_and_rejects_legacy_connection_id() -> None:
    parser = acceptance.build_parser()

    preferred = parser.parse_args(["--connection-ref", "wcn_live"])
    help_text = parser.format_help()

    assert preferred.connection_ref == "wcn_live"
    with pytest.raises(SystemExit):
        parser.parse_args(["--connection-id", "wcn_legacy"])
    assert "--connection-ref" in help_text
    assert "--connection-id" not in help_text


def test_acceptance_parser_defaults_action_to_selected_provider() -> None:
    parser = acceptance.build_parser()

    facebook = acceptance.normalize_acceptance_args(
        parser.parse_args(["--provider", "facebook"])
    )
    gmail = acceptance.normalize_acceptance_args(parser.parse_args(["--provider", "gmail"]))
    explicit = acceptance.normalize_acceptance_args(
        parser.parse_args(["--provider", "facebook", "--action", "facebook_create_post"])
    )

    assert facebook.action == "FACEBOOK_LIST_MANAGED_PAGES"
    assert gmail.action == "GMAIL_FETCH_EMAILS"
    assert explicit.action == "FACEBOOK_CREATE_POST"


def test_composio_acceptance_preflight_reports_missing_live_setup(
    monkeypatch,
) -> None:
    parser = acceptance.build_parser()
    monkeypatch.delenv(acceptance.ENV_FLAG, raising=False)
    monkeypatch.delenv(acceptance.TOKEN_ENV, raising=False)

    args = acceptance.prepare_acceptance_args(
        parser.parse_args(
            [
                "--preflight-only",
                "--backend-url",
                "https://wiii.example.com/path?token=secret",
                "--auth-mode",
                "bearer",
                "--provider",
                "gmail",
                "--expect-connected",
                "--require-execution-ready",
                "--execute-readonly",
                "--arguments-json",
                "{not-json",
            ]
        )
    )
    payload = acceptance.build_composio_acceptance_preflight(args)
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == acceptance.PREFLIGHT_SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["live_backend_call_attempted"] is False
    assert payload["provider_execution_attempted"] is False
    assert payload["backend"]["placeholder"] is True
    assert payload["backend"]["raw_backend_url_included"] is False
    assert payload["authentication"]["bearer_token_present"] is False
    assert payload["authentication"]["bearer_env_name_included"] is False
    assert payload["arguments"]["valid_json_object"] is False
    assert "pass_allow_live" in payload["required_next"]
    assert "set_live_composio_acceptance_flag" in payload["required_next"]
    assert "configure_backend_url" in payload["required_next"]
    assert "configure_acceptance_bearer_token" in payload["required_next"]
    assert "fix_arguments_json" in payload["required_next"]
    assert payload["setup_contract"]["version"] == acceptance.SETUP_CONTRACT_VERSION
    assert payload["setup_contract"]["requirement_id"] == (
        "wiii-connect-composio-acceptance"
    )
    assert payload["setup_contract"]["required_next"] == payload["required_next"]
    assert payload["setup_contract"]["dispatch_ready"] is False
    assert "acceptance_bearer_token" in payload["setup_contract"]["credential_slots_required"]
    assert "connected_provider_account" in payload["setup_contract"]["external_setup_required"]
    assert "token=secret" not in rendered
    assert acceptance.TOKEN_ENV not in rendered
    assert "WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE" not in rendered


def test_composio_acceptance_preflight_passes_with_required_setup(
    monkeypatch,
) -> None:
    parser = acceptance.build_parser()
    monkeypatch.setenv(acceptance.ENV_FLAG, "1")
    monkeypatch.setenv(acceptance.TOKEN_ENV, "secret-token")

    args = acceptance.prepare_acceptance_args(
        parser.parse_args(
            [
                "--preflight-only",
                "--allow-live",
                "--backend-url",
                "https://staging.wiii.test",
                "--auth-mode",
                "bearer",
                "--provider",
                "gmail",
                "--expect-connected",
                "--require-execution-ready",
                "--execute-readonly",
                "--skip-connect-link",
                "--arguments-json",
                '{"query":"from:me","max_results":1}',
            ]
        )
    )
    payload = acceptance.build_composio_acceptance_preflight(args)
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "pass"
    assert payload["requested_provider"] == "gmail"
    assert payload["requested_action"] == "GMAIL_FETCH_EMAILS"
    assert payload["allow_live_acknowledged"] is True
    assert payload["live_env_flag_set"] is True
    assert payload["backend"]["valid"] is True
    assert payload["backend"]["placeholder"] is False
    assert payload["authentication"]["bearer_token_present"] is True
    assert payload["arguments"]["argument_key_count"] == 2
    assert payload["required_next"] == []
    assert payload["setup_contract"]["dispatch_ready"] is True
    assert payload["setup_contract"]["required_next"] == []
    assert "secret-token" not in rendered
    assert acceptance.TOKEN_ENV not in rendered


def test_preflight_main_writes_diagnostics_without_live_harness(
    monkeypatch,
    tmp_path,
) -> None:
    out_path = tmp_path / "composio-preflight.json"

    class ForbiddenHarness:
        def __init__(self, *args, **kwargs):
            raise AssertionError("preflight must not construct live harness")

    monkeypatch.setenv(acceptance.ENV_FLAG, "1")
    monkeypatch.setenv(acceptance.TOKEN_ENV, "secret-token")
    monkeypatch.setattr(acceptance, "WiiiConnectComposioAcceptance", ForbiddenHarness)

    rc = acceptance.main(
        [
            "--preflight-only",
            "--allow-live",
            "--backend-url",
            "https://staging.wiii.test",
            "--auth-mode",
            "bearer",
            "--expect-connected",
            "--require-execution-ready",
            "--execute-readonly",
            "--skip-connect-link",
            "--arguments-json",
            '{"query":"from:me","max_results":1}',
            "--out",
            str(out_path),
        ]
    )
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["schema_version"] == acceptance.PREFLIGHT_SCHEMA_VERSION
    assert payload["status"] == "pass"
    assert payload["live_backend_call_attempted"] is False


def test_failure_from_preflight_writes_failed_registered_evidence_without_live_harness(
    monkeypatch,
    tmp_path,
) -> None:
    out_path = tmp_path / "wiii-connect-composio-acceptance-evidence.json"
    preflight_path = tmp_path / "wiii-connect-composio-acceptance-preflight.json"

    class ForbiddenHarness:
        def __init__(self, *args, **kwargs):
            raise AssertionError("failed evidence must not construct live harness")

    parser = acceptance.build_parser()
    monkeypatch.setenv(acceptance.ENV_FLAG, "1")
    monkeypatch.delenv(acceptance.TOKEN_ENV, raising=False)
    monkeypatch.setattr(acceptance, "WiiiConnectComposioAcceptance", ForbiddenHarness)
    preflight_args = acceptance.prepare_acceptance_args(
        parser.parse_args(
            [
                "--preflight-only",
                "--allow-live",
                "--backend-url",
                "https://wiii.example.com/path?token=secret",
                "--auth-mode",
                "bearer",
                "--provider",
                "facebook",
            ]
        )
    )
    preflight_payload = acceptance.build_composio_acceptance_preflight(preflight_args)
    assert preflight_payload["status"] == "fail"
    preflight_path.write_text(
        json.dumps(preflight_payload, sort_keys=True),
        encoding="utf-8",
    )

    rc = acceptance.main(
        [
            "--failure-from-preflight",
            "--failure-preflight-json",
            str(preflight_path),
            "--allow-live",
            "--backend-url",
            "https://staging.wiii.test",
            "--auth-mode",
            "bearer",
            "--provider",
            "gmail",
            "--expect-connected",
            "--require-execution-ready",
            "--execute-readonly",
            "--skip-connect-link",
            "--arguments-json",
            '{"query":"private-query","max_results":1}',
            "--out",
            str(out_path),
        ]
    )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, sort_keys=True)

    assert rc == 1
    assert payload["schema_version"] == acceptance.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert payload["provider"] == "facebook"
    assert payload["action"] == "FACEBOOK_LIST_MANAGED_PAGES"
    assert payload["summary"]["success"] is False
    assert payload["live_backend_call_attempted"] is False
    assert payload["provider_execution_attempted"] is False
    assert payload["preflight_summary"]["schema_version"] == (
        acceptance.PREFLIGHT_SCHEMA_VERSION
    )
    preflight_summary_path = tmp_path / "composio-preflight-summary.json"
    preflight_summary_path.write_text(
        json.dumps(payload["preflight_summary"]),
        encoding="utf-8",
    )
    preflight_validation = preflight_validator.validate_preflight(
        preflight_summary_path,
        requirement_id="wiii-connect-composio-acceptance",
    )
    assert preflight_validation.ok, preflight_validation.to_dict()
    assert (
        payload["preflight_summary"]["flags"]["explicit_connection_selection_present"]
        is False
    )
    assert "explicit_connection_supplied" not in payload["preflight_summary"]["flags"]
    assert (
        payload["preflight_summary"]["privacy"]["raw_connection_selection_included"]
        is False
    )
    assert payload["preflight_summary"]["setup_contract"] == payload["setup_contract"]
    assert payload["setup_contract"]["required_next"] == payload["required_next"]
    assert payload["required_next"] == preflight_payload["required_next"]
    assert "configure_backend_url" in payload["required_next"]
    assert "configure_acceptance_bearer_token" in payload["required_next"]
    assert "pass_allow_live" not in payload["required_next"]
    assert "set_live_composio_acceptance_flag" not in payload["required_next"]
    assert payload["privacy"]["raw_backend_url_included"] is False
    assert payload["privacy"]["raw_connection_locator_included"] is False
    assert "token=secret" not in rendered
    assert "private-query" not in rendered
    assert "connection_ref" not in rendered
    assert acceptance.TOKEN_ENV not in rendered
    assert acceptance.ENV_FLAG not in rendered


def test_guard_failure_main_writes_failed_registered_evidence(
    monkeypatch,
    tmp_path,
) -> None:
    out_path = tmp_path / "wiii-connect-composio-acceptance-evidence.json"
    monkeypatch.delenv(acceptance.ENV_FLAG, raising=False)

    rc = acceptance.main(["--out", str(out_path)])
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, sort_keys=True)

    assert rc == 1
    assert payload["schema_version"] == acceptance.SCHEMA_VERSION
    assert payload["status"] == "fail"
    assert "pass_allow_live" in payload["required_next"]
    assert payload["setup_contract"]["dispatch_ready"] is False
    preflight_path = tmp_path / "composio-guard-preflight-summary.json"
    preflight_path.write_text(
        json.dumps(payload["preflight_summary"]),
        encoding="utf-8",
    )
    preflight_validation = preflight_validator.validate_preflight(
        preflight_path,
        requirement_id="wiii-connect-composio-acceptance",
    )
    assert preflight_validation.ok, preflight_validation.to_dict()
    assert (
        payload["preflight_summary"]["flags"]["explicit_connection_selection_present"]
        is False
    )
    assert "explicit_connection_supplied" not in payload["preflight_summary"]["flags"]
    assert (
        payload["preflight_summary"]["privacy"]["raw_connection_selection_included"]
        is False
    )
    assert payload["preflight_summary"]["setup_contract"] == payload["setup_contract"]
    assert payload["privacy"]["bearer_value_included"] is False
    assert acceptance.TOKEN_ENV not in rendered
    assert "Bearer " not in rendered
    assert "connection_ref" not in rendered
