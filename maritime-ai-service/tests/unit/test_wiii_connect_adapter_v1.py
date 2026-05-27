from __future__ import annotations


def test_composio_connection_state_normalization_and_agent_ready_gate():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectProviderRegistryEntry,
        is_connection_agent_ready,
        normalize_connection_state,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="facebook",
        label="Facebook",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        action_allowlist=("FACEBOOK_CREATE_POST",),
    )

    pending = WiiiConnectConnectionRecordV1(
        connection_id="conn_1",
        provider_slug="facebook",
        state=normalize_connection_state("PENDING"),
    )

    assert pending.state == "waiting"
    assert normalize_connection_state("ACTIVE") == "connected"
    assert normalize_connection_state("FAILED") == "error"
    assert is_connection_agent_ready(entry, pending) is False


def test_external_execute_requires_connection_action_path_scope_and_approval():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectExecutionRequest,
        WiiiConnectProviderRegistryEntry,
        WiiiConnectScopeGrant,
        decide_external_execution,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="facebook",
        label="Facebook",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        allowed_paths=("external_app_action",),
        action_allowlist=("FACEBOOK_CREATE_POST",),
    )
    connection = WiiiConnectConnectionRecordV1(
        connection_id="conn_1",
        provider_slug="facebook",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True, write=True, apply=True),
    )

    uncurated = decide_external_execution(
        entry,
        connection,
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_DELETE_PAGE",
            path="external_app_action",
            mutation="write",
        ),
    )
    assert uncurated.allowed is False
    assert uncurated.reason == "action_not_allowed"

    wrong_path = decide_external_execution(
        entry,
        connection,
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            path="casual_chat",
            mutation="write",
        ),
    )
    assert wrong_path.allowed is False
    assert wrong_path.reason == "path_not_allowed"

    missing_approval = decide_external_execution(
        entry,
        connection,
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            path="external_app_action",
            mutation="apply",
            preview_evidence_required=True,
            preview_evidence_id="preview_1",
        ),
    )
    assert missing_approval.allowed is False
    assert missing_approval.reason == "missing_approval_token"

    allowed = decide_external_execution(
        entry,
        connection,
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            path="external_app_action",
            mutation="apply",
            preview_evidence_required=True,
            preview_evidence_id="preview_1",
            approval_token_present=True,
        ),
    )
    assert allowed.allowed is True
    assert allowed.reason == "allowed"


def test_public_metadata_does_not_expose_vault_key_or_raw_secret_values():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectProviderRegistryEntry,
        WiiiConnectRequiredField,
        WiiiConnectVaultSecretRef,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="gmail",
        label="Gmail",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=False,
        agent_ready=False,
        required_fields=(
            WiiiConnectRequiredField(
                key="client_secret",
                label="Client secret",
                secret=True,
            ),
        ),
    )
    connection = WiiiConnectConnectionRecordV1(
        connection_id="conn_1",
        provider_slug="gmail",
        state="connected",
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug="gmail",
            connection_id="conn_1",
            vault_key_id="vault://tenant/private/oauth-token-secret",
            secret_version="v1",
        ),
    )

    serialized = str(
        {
            "entry": entry.to_public_metadata(),
            "connection": connection.to_public_metadata(),
            "vault": connection.vault_ref.to_public_metadata(),
        }
    )

    assert "oauth-token-secret" not in serialized
    assert "vault://tenant/private" not in serialized
    assert "vault_ref_present" in serialized
    assert "client_secret" in serialized
