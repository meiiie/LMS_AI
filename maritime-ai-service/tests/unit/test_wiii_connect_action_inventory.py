from __future__ import annotations

import json
from dataclasses import replace


def _adapter_capability():
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectProviderAdapterCapability,
    )

    return WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=True,
        reason="ready",
    )


def _connection(provider_slug: str, connection_id: str = "ca_private"):
    from app.engine.wiii_connect import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
    )

    return WiiiConnectConnectionRecordV1(
        connection_id=connection_id,
        provider_slug=provider_slug,
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug=provider_slug,
            connection_id=connection_id,
            vault_key_id=f"provider-managed://composio/{connection_id}",
        ),
        account_label="private@example.test",
        external_account_ref="external-private-ref",
    )


def test_effective_action_inventory_marks_read_action_ready_without_secrets():
    from app.engine.wiii_connect import (
        WiiiConnectScopeGrant,
        build_wiii_connect_effective_action_inventory,
        get_wiii_connect_provider_entry,
    )

    entry = replace(
        get_wiii_connect_provider_entry("gmail"),
        enabled=True,
        agent_ready=True,
        action_allowlist=("GMAIL_FETCH_EMAILS",),
        default_scopes=WiiiConnectScopeGrant(read=True),
        requirements=(),
        connect_requirements=(),
        agent_ready_requirements=(),
        warnings=(),
    )

    inventory = build_wiii_connect_effective_action_inventory(
        entry=entry,
        connection=_connection("gmail"),
        adapter_capability=_adapter_capability(),
        runtime_enabled_action_slugs=("GMAIL_FETCH_EMAILS",),
        audit_ledger_metadata={"persistent": True},
        connection_ref_present=True,
        storage_metadata={"persistent": True, "audit_ledger_ready": True},
    )

    payload = inventory.to_public_metadata()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_action_inventory.v1"
    assert payload["status"] == "ready"
    assert payload["visible_action_count"] == 1
    assert payload["executable_action_count"] == 1
    assert payload["actions"][0]["slug"] == "GMAIL_FETCH_EMAILS"
    assert payload["actions"][0]["visible_to_agent"] is True
    assert payload["actions"][0]["executable_now"] is True
    assert payload["actions"][0]["gateway"]["status"] == "allowed"
    assert "ca_private" not in serialized
    assert "private@example.test" not in serialized
    assert "provider-managed://" not in serialized
    assert "external-private-ref" not in serialized


def test_effective_action_inventory_guards_apply_until_preview_and_approval():
    from app.engine.wiii_connect import (
        WiiiConnectScopeGrant,
        build_wiii_connect_effective_action_inventory,
        get_wiii_connect_provider_entry,
    )

    entry = replace(
        get_wiii_connect_provider_entry("facebook"),
        enabled=True,
        agent_ready=True,
        action_allowlist=("FACEBOOK_CREATE_POST",),
        default_scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
        requirements=(),
        connect_requirements=(),
        agent_ready_requirements=(),
        warnings=(),
    )

    inventory = build_wiii_connect_effective_action_inventory(
        entry=entry,
        connection=_connection("facebook"),
        adapter_capability=_adapter_capability(),
        runtime_enabled_action_slugs=("FACEBOOK_CREATE_POST",),
        audit_ledger_metadata={"persistent": True},
        connection_ref_present=True,
        storage_metadata={"persistent": True, "audit_ledger_ready": True},
    )

    payload = inventory.to_public_metadata()
    by_slug = {action["slug"]: action for action in payload["actions"]}
    post = by_slug["FACEBOOK_CREATE_POST"]
    stages = {stage["key"]: stage for stage in post["stages"]}
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "guarded"
    assert post["status"] == "guarded"
    assert post["reason"] == "missing_preview_evidence"
    assert post["visible_to_agent"] is True
    assert post["executable_now"] is False
    assert post["argument_keys"] == ["message", "link"]
    assert post["model_argument_keys"] == ["message", "link"]
    assert post["hidden_argument_count"] == 3
    assert stages["gateway"]["status"] == "pending"
    assert stages["gateway"]["required_next"] == ["create_preview_evidence"]
    assert "page_id" not in serialized
    assert "published" not in serialized
    assert "scheduled_publish_time" not in serialized


def test_effective_action_inventory_hides_runtime_disabled_actions_from_agent():
    from app.engine.wiii_connect import (
        WiiiConnectScopeGrant,
        build_wiii_connect_effective_action_inventory,
        get_wiii_connect_provider_entry,
    )

    entry = replace(
        get_wiii_connect_provider_entry("facebook"),
        enabled=True,
        agent_ready=True,
        action_allowlist=(),
        default_scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
        requirements=(),
        connect_requirements=(),
        agent_ready_requirements=(),
        warnings=(),
    )

    inventory = build_wiii_connect_effective_action_inventory(
        entry=entry,
        connection=_connection("facebook"),
        adapter_capability=_adapter_capability(),
        runtime_enabled_action_slugs=(),
        audit_ledger_metadata={"persistent": True},
        connection_ref_present=True,
    )

    payload = inventory.to_public_metadata()
    assert payload["status"] == "blocked"
    assert payload["reason"] == "no_runtime_enabled_actions"
    assert payload["visible_action_count"] == 0
    assert payload["executable_action_count"] == 0
    assert all(action["visible_to_agent"] is False for action in payload["actions"])
