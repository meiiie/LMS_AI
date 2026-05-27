from __future__ import annotations

import json


def test_default_provider_adapter_status_is_unbound_and_secret_free():
    from app.engine.wiii_connect.provider_adapters import (
        provider_adapter_status_public_metadata,
    )

    metadata = provider_adapter_status_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)
    by_kind = {adapter["provider_kind"]: adapter for adapter in metadata["adapters"]}

    assert metadata["version"] == "wiii_connect_provider_adapter.v1"
    assert by_kind["composio"]["bound"] is False
    assert by_kind["composio"]["configured"] is False
    assert by_kind["composio"]["authorization_ready"] is False
    assert by_kind["composio"]["reason"] == "provider_adapter_not_bound"
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized


def test_disabled_provider_authorization_url_decision_blocks_and_redacts_keys():
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectAuthorizationUrlRequest,
        decide_authorization_url,
    )
    from app.engine.wiii_connect.provider_registry import get_wiii_connect_provider_entry

    entry = get_wiii_connect_provider_entry("facebook")
    assert entry is not None

    decision = decide_authorization_url(
        entry,
        WiiiConnectAuthorizationUrlRequest(
            provider_slug="facebook",
            state_present=True,
            redirect_uri_present=True,
            request_metadata_keys=("access_token", "client_secret", "workspace_id"),
        ),
    )
    metadata = decision.to_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert decision.ready is False
    assert metadata["status"] == "blocked"
    assert metadata["reason"] == "provider_disabled"
    assert metadata["authorization_url"] == ""
    assert "redacted_sensitive_field" in serialized
    assert "workspace_id" in serialized
    assert "access_token" not in serialized
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized


def test_authorization_url_requires_shape_adapter_vault_audit_and_url():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectProviderRegistryEntry
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectAuthorizationUrlRequest,
        WiiiConnectProviderAdapterCapability,
        decide_authorization_url,
    )
    from app.engine.wiii_connect.vault import WiiiConnectVaultCapability

    entry = WiiiConnectProviderRegistryEntry(
        slug="internal_test",
        label="Internal Test",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        requirements=(),
    )
    valid_request = WiiiConnectAuthorizationUrlRequest(
        provider_slug="internal_test",
        state_present=True,
        redirect_uri_present=True,
    )
    ready_adapter = WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        reason="ready",
    )
    ready_vault = WiiiConnectVaultCapability(
        enabled=True,
        backend="provider_managed",
        accepts_secret_material=True,
        provider_managed=True,
        reason="ready",
    )

    missing_state = decide_authorization_url(
        entry,
        WiiiConnectAuthorizationUrlRequest(
            provider_slug="internal_test",
            redirect_uri_present=True,
        ),
    )
    missing_redirect = decide_authorization_url(
        entry,
        WiiiConnectAuthorizationUrlRequest(
            provider_slug="internal_test",
            state_present=True,
        ),
    )
    missing_adapter = decide_authorization_url(entry, valid_request)
    adapter_not_configured = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=WiiiConnectProviderAdapterCapability(
            provider_kind="composio",
            bound=True,
            configured=False,
            reason="missing_config",
        ),
    )
    adapter_cannot_authorize = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=WiiiConnectProviderAdapterCapability(
            provider_kind="composio",
            bound=True,
            configured=True,
            can_create_authorization_url=False,
            reason="authorization_not_implemented",
        ),
    )
    adapter_mismatch = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=WiiiConnectProviderAdapterCapability(
            provider_kind="custom_oauth",
            bound=True,
            configured=True,
            can_create_authorization_url=True,
            reason="ready",
        ),
    )
    missing_vault = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=ready_adapter,
    )
    missing_persistent_audit = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=ready_adapter,
        vault_capability=ready_vault,
    )
    missing_url = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=ready_adapter,
        vault_capability=ready_vault,
        audit_ledger_metadata={"persistent": True},
    )
    ready = decide_authorization_url(
        entry,
        valid_request,
        adapter_capability=ready_adapter,
        vault_capability=ready_vault,
        audit_ledger_metadata={"persistent": True},
        authorization_url="https://connect.example.test/session/123",
    )

    assert missing_state.reason == "missing_state"
    assert missing_redirect.reason == "missing_redirect_uri"
    assert missing_adapter.reason == "provider_adapter_not_bound"
    assert adapter_not_configured.reason == "provider_adapter_not_configured"
    assert adapter_cannot_authorize.reason == "provider_adapter_cannot_authorize"
    assert adapter_mismatch.reason == "provider_adapter_mismatch"
    assert missing_vault.reason == "vault_not_configured"
    assert missing_persistent_audit.reason == "audit_ledger_not_persistent"
    assert missing_url.reason == "authorization_url_missing"
    assert ready.ready is True
    assert ready.reason == "authorization_url_issued"
    assert ready.authorization_url == "https://connect.example.test/session/123"
