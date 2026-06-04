from __future__ import annotations

import json


def test_composio_connection_state_normalization_and_baseline_gate():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectProviderRegistryEntry,
        is_connection_baseline_ready,
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
    assert is_connection_baseline_ready(entry, pending) is False


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
    connect_only_entry = WiiiConnectProviderRegistryEntry(
        slug="facebook",
        label="Facebook",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=False,
        allowed_paths=("external_app_action",),
        action_allowlist=("FACEBOOK_CREATE_POST",),
    )

    not_agent_ready = decide_external_execution(
        connect_only_entry,
        connection,
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            path="external_app_action",
            mutation="write",
        ),
    )
    assert not_agent_ready.allowed is False
    assert not_agent_ready.reason == "provider_not_agent_ready"

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

    missing_scope_connection = WiiiConnectConnectionRecordV1(
        connection_id="conn_2",
        provider_slug="facebook",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True, write=False, apply=False),
    )
    missing_scope = decide_external_execution(
        entry,
        missing_scope_connection,
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            path="external_app_action",
            mutation="apply",
        ),
    )
    assert missing_scope.allowed is False
    assert missing_scope.reason == "missing_scope"
    assert missing_scope.required_scopes == ("apply",)

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


def test_wildcard_only_action_allowlist_stays_fail_closed():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectProviderRegistryEntry

    entry = WiiiConnectProviderRegistryEntry(
        slug="github",
        label="GitHub",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        action_allowlist=("*", "GITHUB_GET_*"),
    )

    assert entry.allows_action("GITHUB_GET_REPO") is True
    assert entry.allows_action("SLACK_SEND_MESSAGE") is False


def test_execution_gateway_requires_adapter_execution_and_persistent_audit():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectExecutionRequest,
        WiiiConnectProviderRegistryEntry,
        WiiiConnectScopeGrant,
    )
    from app.engine.wiii_connect.execution_gateway import decide_execution_gateway
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectProviderAdapterCapability,
    )

    entry = WiiiConnectProviderRegistryEntry(
        slug="facebook",
        label="Facebook",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        allowed_paths=("external_app_action",),
        action_allowlist=("FACEBOOK_GET_PAGE",),
    )
    connection = WiiiConnectConnectionRecordV1(
        connection_id="conn_1",
        provider_slug="facebook",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True),
    )
    request = WiiiConnectExecutionRequest(
        provider_slug="facebook",
        action_slug="FACEBOOK_GET_PAGE",
        path="external_app_action",
        mutation="read",
        argument_keys=("page_id", "access_token"),
    )
    adapter_without_execute = WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=False,
        reason="ready",
    )
    adapter_with_execute = WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=True,
        reason="ready",
    )

    blocked_adapter = decide_execution_gateway(
        entry,
        connection,
        request,
        adapter_capability=adapter_without_execute,
        audit_ledger_metadata={"persistent": True},
    )
    blocked_audit = decide_execution_gateway(
        entry,
        connection,
        request,
        adapter_capability=adapter_with_execute,
        audit_ledger_metadata={"persistent": False},
    )
    allowed = decide_execution_gateway(
        entry,
        connection,
        request,
        adapter_capability=adapter_with_execute,
        audit_ledger_metadata={"persistent": True},
    )
    serialized = json.dumps(allowed.to_public_metadata(), sort_keys=True)

    assert blocked_adapter.allowed is False
    assert blocked_adapter.reason == "provider_adapter_cannot_execute"
    assert blocked_audit.allowed is False
    assert blocked_audit.reason == "audit_ledger_not_persistent"
    assert allowed.allowed is True
    assert allowed.reason == "allowed"
    assert "redacted_sensitive_field" in serialized
    assert "access_token" not in serialized


def test_execution_gateway_enforces_wiii_scope_policy_after_connection_scope():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectExecutionRequest,
        WiiiConnectProviderRegistryEntry,
        WiiiConnectScopeGrant,
    )
    from app.engine.wiii_connect.execution_gateway import decide_execution_gateway
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectProviderAdapterCapability,
    )
    from app.engine.wiii_connect.scope_policy import scope_policy_for_provider_entry

    adapter = WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=True,
        reason="ready",
    )
    connection = WiiiConnectConnectionRecordV1(
        connection_id="conn_1",
        provider_slug="gmail",
        state="connected",
        scopes=WiiiConnectScopeGrant(
            read=True,
            write=True,
            apply=True,
            admin=True,
        ),
    )
    request = WiiiConnectExecutionRequest(
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        path="external_app_action",
        mutation="read",
    )
    connected_but_policy_closed = WiiiConnectProviderRegistryEntry(
        slug="gmail",
        label="Gmail",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        action_allowlist=("GMAIL_FETCH_EMAILS",),
        default_scopes=WiiiConnectScopeGrant(),
    )
    read_policy_entry = WiiiConnectProviderRegistryEntry(
        slug="gmail",
        label="Gmail",
        provider_kind="composio",
        auth_mode="oauth2",
        enabled=True,
        agent_ready=True,
        action_allowlist=("GMAIL_FETCH_EMAILS",),
        default_scopes=WiiiConnectScopeGrant(read=True),
    )

    blocked = decide_execution_gateway(
        connected_but_policy_closed,
        connection,
        request,
        adapter_capability=adapter,
        audit_ledger_metadata={"persistent": True},
        scope_policy=scope_policy_for_provider_entry(connected_but_policy_closed),
    )
    allowed = decide_execution_gateway(
        read_policy_entry,
        connection,
        request,
        adapter_capability=adapter,
        audit_ledger_metadata={"persistent": True},
        scope_policy=scope_policy_for_provider_entry(read_policy_entry),
    )
    mutating_blocks = []
    for mutation in ("write", "apply", "admin"):
        mutating_blocks.append(
            decide_execution_gateway(
                read_policy_entry,
                connection,
                WiiiConnectExecutionRequest(
                    provider_slug="gmail",
                    action_slug="GMAIL_FETCH_EMAILS",
                    path="external_app_action",
                    mutation=mutation,  # type: ignore[arg-type]
                    approval_token_present=mutation == "apply",
                ),
                adapter_capability=adapter,
                audit_ledger_metadata={"persistent": True},
                scope_policy=scope_policy_for_provider_entry(read_policy_entry),
            )
        )
    serialized = json.dumps(blocked.to_public_metadata(), sort_keys=True)

    assert blocked.allowed is False
    assert blocked.reason == "scope_policy_denied"
    assert blocked.decision.required_scopes == ("read",)
    assert blocked.scope_policy is not None
    assert blocked.scope_policy.allowed_scopes == ()
    assert "grant_required_scope_policy" in blocked.required_next
    assert allowed.allowed is True
    assert allowed.scope_policy is not None
    assert allowed.scope_policy.allowed_scopes == ("read",)
    assert [decision.reason for decision in mutating_blocks] == [
        "scope_policy_denied",
        "scope_policy_denied",
        "scope_policy_denied",
    ]
    assert [decision.decision.required_scopes for decision in mutating_blocks] == [
        ("write",),
        ("apply",),
        ("admin",),
    ]
    assert "access_token" not in serialized
    assert "conn_1" not in serialized


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

    metadata = {
        "entry": entry.to_public_metadata(),
        "connection": connection.to_public_metadata(),
        "vault": connection.vault_ref.to_public_metadata(),
    }
    serialized = json.dumps(metadata, sort_keys=True)
    vault_serialized = json.dumps(metadata["vault"], sort_keys=True)

    assert metadata["connection"]["vault_ref_present"] is True
    assert metadata["connection"]["connection_ref"].startswith("wcn_")
    assert metadata["vault"]["vault_ref_present"] is True
    assert metadata["vault"]["connection_ref_present"] is True
    assert metadata["entry"]["required_fields"][0]["key"] == "client_secret"
    assert "oauth-token-secret" not in serialized
    assert "vault://tenant/private" not in serialized
    assert "conn_1" not in serialized
    assert "connection_id" not in serialized
    assert "conn_1" not in vault_serialized
    assert "connection_id" not in vault_serialized


def test_execution_audit_event_reports_connection_presence_only():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectAuditEvent,
        WiiiConnectExecutionDecision,
        WiiiConnectExecutionRequest,
    )

    request = WiiiConnectExecutionRequest(
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        path="external_app_action",
    )
    decision = WiiiConnectExecutionDecision(
        outcome="allowed",
        reason="allowed",
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        path="external_app_action",
    )
    event = WiiiConnectAuditEvent(
        stage="started",
        request=request,
        decision=decision,
        connection_id="ca_secret_provider_ref",
    )

    metadata = event.to_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert metadata["connection_ref_present"] is True
    assert "ca_secret_provider_ref" not in serialized
    assert "connection_id" not in serialized


def test_execution_request_audit_metadata_includes_sanitized_request_id():
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectExecutionRequest

    metadata = WiiiConnectExecutionRequest(
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        path="external_app_action",
        request_id="req-wiii-connect-1",
    ).to_audit_metadata()
    redacted = WiiiConnectExecutionRequest(
        provider_slug="gmail",
        action_slug="GMAIL_FETCH_EMAILS",
        path="external_app_action",
        request_id="Bearer abcdefgh123456",
    ).to_audit_metadata()

    assert metadata["request_id"] == "req-wiii-connect-1"
    assert redacted["request_id"] == "Bearer <redacted-secret>"
