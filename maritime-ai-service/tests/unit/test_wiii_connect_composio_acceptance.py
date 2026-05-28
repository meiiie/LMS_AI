from __future__ import annotations

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


def test_connection_id_for_action_requires_selected_or_explicit_connection() -> None:
    harness = acceptance.WiiiConnectComposioAcceptance(
        SimpleNamespace(connection_id="", selected_connection_id="")
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="No connected account"):
        harness.connection_id_for_action()

    harness.selected_connection_id = "ca_live"
    assert harness.connection_id_for_action() == "ca_live"
