from __future__ import annotations

import json


def test_disabled_provider_status_is_fail_closed_and_privacy_safe():
    from app.engine.wiii_connect.connection_sessions import provider_connection_status

    status = provider_connection_status("facebook")
    assert status is not None

    metadata = status.to_public_metadata()
    assert metadata["version"] == "wiii_connect_session.v1"
    assert metadata["provider_slug"] == "facebook"
    assert metadata["can_start_authorization"] is False
    assert metadata["reason"] == "provider_disabled"
    assert "provider_managed_vault_ref" in metadata["missing_requirements"]
    assert "execution_gateway" not in metadata["missing_requirements"]

    serialized = json.dumps(metadata, sort_keys=True)
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
    assert "approval_token" not in serialized


def test_session_start_redacts_sensitive_request_metadata_keys():
    from app.engine.wiii_connect.connection_sessions import (
        WiiiConnectSessionStartRequest,
        begin_connection_session,
        scope_grant_from_mapping,
    )
    from app.engine.wiii_connect.provider_registry import get_wiii_connect_provider_entry

    entry = get_wiii_connect_provider_entry("facebook")
    assert entry is not None

    request = WiiiConnectSessionStartRequest(
        provider_slug="facebook",
        requested_scopes=scope_grant_from_mapping({"read": True, "write": True}),
        redirect_uri_present=True,
        request_metadata_keys=("access_token", "client_secret", "workspace_id"),
    )
    decision = begin_connection_session(entry, request)
    metadata = decision.to_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert decision.ready is False
    assert metadata["status"] == "blocked"
    assert metadata["reason"] == "provider_disabled"
    assert metadata["authorization_url"] == ""
    assert metadata["audit_event"]["request"]["redirect_uri_present"] is True
    assert "redacted_sensitive_field" in serialized
    assert "workspace_id" in serialized
    assert "access_token" not in serialized
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized


def test_ready_session_requires_adapter_authorization_url_not_agent_ready():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectProviderRegistryEntry
    from app.engine.wiii_connect.connection_sessions import (
        WiiiConnectSessionStartRequest,
        begin_connection_session,
        provider_connection_status_for_entry,
    )
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectAuthorizationUrlDecision,
        WiiiConnectProviderAdapterCapability,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="internal_test",
        label="Internal Test",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=False,
        requirements=(),
    )

    status = provider_connection_status_for_entry(entry)
    blocked = begin_connection_session(
        entry,
        WiiiConnectSessionStartRequest(provider_slug="internal_test"),
    )
    direct_url = begin_connection_session(
        entry,
        WiiiConnectSessionStartRequest(provider_slug="internal_test"),
        authorization_url="https://connect.example.test/session/123",
    )
    ready = begin_connection_session(
        entry,
        WiiiConnectSessionStartRequest(provider_slug="internal_test"),
        authorization_decision=WiiiConnectAuthorizationUrlDecision(
            status="ready",
            reason="authorization_url_issued",
            provider_slug="internal_test",
            label="Internal Test",
            provider_kind="composio",
            auth_mode="oauth2",
            authorization_url="https://connect.example.test/session/123",
            adapter=WiiiConnectProviderAdapterCapability(
                provider_kind="composio",
                adapter_name="composio_adapter",
                bound=True,
                configured=True,
                can_create_authorization_url=True,
                reason="ready",
            ),
        ),
    )

    assert status.can_start_authorization is False
    assert status.reason == "provider_adapter_not_bound"
    assert blocked.ready is False
    assert blocked.reason == "provider_adapter_not_bound"
    assert direct_url.ready is False
    assert direct_url.reason == "provider_adapter_not_bound"
    assert ready.ready is True
    assert ready.reason == "authorization_url_issued"
    assert ready.authorization_url == "https://connect.example.test/session/123"
