from __future__ import annotations

import json


def test_default_vault_status_is_disabled_and_secret_free():
    from app.engine.wiii_connect.vault import vault_status_public_metadata

    metadata = vault_status_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert metadata["version"] == "wiii_connect_vault.v1"
    assert metadata["enabled"] is False
    assert metadata["can_store_external_secret"] is False
    assert metadata["reason"] == "vault_disabled"
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized


def test_vault_write_decision_blocks_disabled_provider_and_redacts_keys():
    from app.engine.wiii_connect.provider_registry import get_wiii_connect_provider_entry
    from app.engine.wiii_connect.vault import (
        WiiiConnectVaultCapability,
        WiiiConnectVaultSecretWriteRequest,
        decide_vault_secret_write,
    )

    entry = get_wiii_connect_provider_entry("facebook")
    assert entry is not None
    decision = decide_vault_secret_write(
        entry,
        WiiiConnectVaultSecretWriteRequest(
            provider_slug="facebook",
            connection_id="conn_1",
            secret_kind="oauth_token",
            secret_material_present=True,
            metadata_keys=("access_token", "refresh_token", "account_id"),
        ),
        WiiiConnectVaultCapability(
            enabled=True,
            backend="provider_managed",
            accepts_secret_material=True,
            provider_managed=True,
            key_namespace="wiii_test",
            reason="ready",
        ),
    )
    metadata = decision.to_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert decision.ready is False
    assert metadata["reason"] == "provider_disabled"
    assert metadata["connection_ref_present"] is True
    assert metadata["vault_ref"] is None
    assert "redacted_sensitive_field" in serialized
    assert "account_id" in serialized
    assert "conn_1" not in serialized
    assert "connection_id" not in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "secret-value" not in serialized


def test_vault_write_decision_issues_only_opaque_ref_when_ready():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectProviderRegistryEntry
    from app.engine.wiii_connect.vault import (
        WiiiConnectVaultCapability,
        WiiiConnectVaultSecretWriteRequest,
        decide_vault_secret_write,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="internal_test",
        label="Internal Test",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
    )
    decision = decide_vault_secret_write(
        entry,
        WiiiConnectVaultSecretWriteRequest(
            provider_slug="internal_test",
            connection_id="conn_1",
            secret_kind="oauth_token",
            secret_material_present=True,
            metadata_keys=("account_id",),
        ),
        WiiiConnectVaultCapability(
            enabled=True,
            backend="external_kms",
            accepts_secret_material=True,
            key_namespace="tenant_1",
            reason="ready",
        ),
    )
    metadata = decision.to_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert decision.ready is True
    assert metadata["reason"] == "ready_to_store"
    assert metadata["connection_ref_present"] is True
    assert metadata["vault_ref"]["vault_ref_present"] is True
    assert metadata["vault_ref"]["connection_ref_present"] is True
    assert metadata["vault_ref"]["secret_version"] == "pending"
    assert "conn_1" not in serialized
    assert "connection_id" not in serialized
    assert "tenant_1/composio/internal_test/conn_1/oauth_token" not in serialized


def test_audit_ledger_sanitizes_sensitive_metadata_recursively():
    from app.engine.wiii_connect.audit_ledger import (
        WiiiConnectInMemoryAuditLedger,
        build_audit_ledger_record,
    )

    ledger = WiiiConnectInMemoryAuditLedger()
    record = build_audit_ledger_record(
        event_kind="vault",
        provider_slug="facebook",
        status="blocked",
        reason="provider failed Bearer raw-reason-token-123",
        metadata={
            "account_id": "page_1",
            "access_token": "secret-value",
            "connection_ref": "wcn_facebook_private",
            "page_id": "123456",
            "argument_keys": ["query", "access_token", "page_id"],
            "error": (
                "provider rejected Authorization: Bearer raw-bearer-token-123 "
                "api_key=raw-api-key-inline"
            ),
            "nested": {"client_secret": "secret-value", "safe": "ok"},
        },
    )
    ledger.append(record)

    metadata = ledger.recent_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)
    record_serialized = json.dumps(record.metadata, sort_keys=True)

    assert metadata[0]["version"] == "wiii_connect_audit_ledger.v1"
    assert "<redacted-secret>" in metadata[0]["reason"]
    assert metadata[0]["metadata"]["account_id"] == "page_1"
    assert metadata[0]["metadata"]["nested"]["safe"] == "ok"
    assert metadata[0]["metadata"]["argument_keys"] == [
        "query",
        "redacted_sensitive_field",
        "backend_owned_field",
    ]
    assert "<redacted-secret>" in metadata[0]["metadata"]["error"]
    assert "redacted_sensitive_field" in serialized
    assert "access_token" not in serialized
    assert "client_secret" not in serialized
    assert "connection_ref" not in serialized
    assert "wcn_facebook_private" not in serialized
    assert "page_id" not in serialized
    assert "123456" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "raw-api-key-inline" not in serialized
    assert "raw-reason-token-123" not in serialized
    assert "secret-value" not in serialized
    assert "secret-value" not in record_serialized
    assert "wcn_facebook_private" not in record_serialized
    assert "raw-bearer-token-123" not in record_serialized
