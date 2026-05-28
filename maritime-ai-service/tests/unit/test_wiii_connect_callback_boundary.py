from __future__ import annotations

import json


def test_disabled_provider_callback_is_blocked_and_redacted():
    from app.engine.wiii_connect.callback_boundary import (
        WiiiConnectCallbackRequest,
        provider_callback_decision,
    )

    decision = provider_callback_decision(
        "facebook",
        WiiiConnectCallbackRequest(
            provider_slug="facebook",
            state_present=True,
            code_present=True,
            request_metadata_keys=("state", "code", "client_secret"),
        ),
    )
    assert decision is not None

    metadata = decision.to_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert metadata["version"] == "wiii_connect_callback.v1"
    assert metadata["status"] == "blocked"
    assert metadata["reason"] == "provider_disabled"
    assert metadata["vault_ref_issued"] is False
    assert "redacted_sensitive_field" in serialized
    assert "client_secret" not in serialized
    assert "oauth-code-value" not in serialized
    assert "access_token" not in serialized


def test_callback_requires_state_code_vault_and_adapter_before_accepting():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectProviderRegistryEntry
    from app.engine.wiii_connect.callback_boundary import (
        WiiiConnectCallbackRequest,
        provider_callback_decision_for_entry,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="internal_test",
        label="Internal Test",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        requirements=(),
    )

    missing_state = provider_callback_decision_for_entry(
        entry,
        WiiiConnectCallbackRequest(provider_slug="internal_test", code_present=True),
    )
    missing_code = provider_callback_decision_for_entry(
        entry,
        WiiiConnectCallbackRequest(
            provider_slug="internal_test",
            state_present=True,
            state_valid=True,
        ),
    )
    missing_vault = provider_callback_decision_for_entry(
        entry,
        WiiiConnectCallbackRequest(
            provider_slug="internal_test",
            state_present=True,
            state_valid=True,
            code_present=True,
            connection_ref_present=True,
        ),
    )
    missing_adapter = provider_callback_decision_for_entry(
        entry,
        WiiiConnectCallbackRequest(
            provider_slug="internal_test",
            state_present=True,
            state_valid=True,
            code_present=True,
            connection_ref_present=True,
        ),
        vault_ready=True,
    )
    accepted = provider_callback_decision_for_entry(
        entry,
        WiiiConnectCallbackRequest(
            provider_slug="internal_test",
            state_present=True,
            state_valid=True,
            code_present=True,
            connection_ref_present=True,
        ),
        vault_ready=True,
        provider_adapter_bound=True,
    )

    assert missing_state.reason == "missing_state"
    assert missing_code.reason == "missing_code"
    assert missing_vault.reason == "vault_not_configured"
    assert missing_adapter.reason == "provider_adapter_not_bound"
    assert accepted.accepted is True
    assert accepted.vault_ref_issued is True
    assert accepted.connection_ref == "pending_connection_ref"
    assert "connection_id" not in accepted.to_public_metadata()


def test_callback_accepts_vault_capability_without_boolean_override():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectProviderRegistryEntry
    from app.engine.wiii_connect.callback_boundary import (
        WiiiConnectCallbackRequest,
        provider_callback_decision_for_entry,
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
    decision = provider_callback_decision_for_entry(
        entry,
        WiiiConnectCallbackRequest(
            provider_slug="internal_test",
            state_present=True,
            state_valid=True,
            code_present=True,
            connection_ref_present=True,
        ),
        vault_capability=WiiiConnectVaultCapability(
            enabled=True,
            backend="provider_managed",
            accepts_secret_material=True,
            provider_managed=True,
            reason="ready",
        ),
        provider_adapter_bound=True,
    )

    assert decision.accepted is True
    assert decision.reason == "accepted"
