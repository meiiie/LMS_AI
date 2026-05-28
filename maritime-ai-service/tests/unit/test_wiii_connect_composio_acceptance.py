from __future__ import annotations

import builtins
import importlib.util
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
    assert redacted["nested"]["access_token"] == "[redacted]"
    assert redacted["nested"]["items"][0]["vault_key_id"] == "[redacted]"
    assert redacted["nested"]["safe"] == "visible"
    assert "secret-token" not in serialized
    assert "ca_secret_123" not in serialized
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
                {"connection_id": "ca_old", "state": "disabled", "active": False},
                {"connection_id": "ca_live", "state": "connected", "active": True},
            ]
        }
    )

    assert adapter["bound"] is True
    assert provider["provider_kind"] == "composio"
    assert action["mutation"] == "read"
    assert connection["connection_id"] == "ca_live"


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

    payload = harness.activation_readiness_payload(connection_id="ca_live")

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
    assert "connection_id=ca_live" in url


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
            connection_id="",
        )
    )

    def backend_health() -> str:
        calls.append("health")
        return "ok"

    def authenticate() -> str:
        calls.append("auth")
        harness.token = "token"
        return "bearer"

    def report_payload(*, connection_id: str = ""):
        calls.append(f"report:{connection_id or 'none'}")
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


def test_connection_id_for_action_requires_selected_or_explicit_connection() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(connection_id="", selected_connection_id="")
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="No connected account"):
        harness.connection_id_for_action()

    harness.selected_connection_id = "ca_live"
    assert harness.connection_id_for_action() == "ca_live"
