from __future__ import annotations

import json


def test_provider_registry_exposes_disabled_composio_catalog_without_secrets():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.provider_registry import (
        provider_registry_public_metadata,
    )

    metadata = provider_registry_public_metadata(
        composio_config=WiiiConnectComposioAdapterConfig(),
    )
    providers = metadata["providers"]
    by_slug = {item["slug"]: item for item in providers}

    assert metadata["version"] == "wiii_connect_provider_registry.v1"
    assert by_slug["facebook"]["provider_kind"] == "composio"
    assert by_slug["facebook"]["action_catalog"]["catalog_action_count"] == 3
    assert by_slug["facebook"]["action_catalog"]["enabled_action_count"] == 0
    assert by_slug["gmail"]["action_catalog"]["catalog_action_count"] == 1
    assert by_slug["gmail"]["action_catalog"]["enabled_action_count"] == 0
    assert by_slug["gmail"]["enabled"] is False
    assert by_slug["gmail"]["agent_ready"] is False
    assert by_slug["github"]["requirements"] == [
        "oauth_or_connect_link",
        "provider_managed_vault_ref",
        "audit_ledger",
        "scope_policy",
        "curated_action_catalog",
        "execution_gateway",
    ]
    assert by_slug["github"]["connect_requirements"] == [
        "oauth_or_connect_link",
        "provider_managed_vault_ref",
        "audit_ledger",
    ]
    assert by_slug["github"]["agent_ready_requirements"] == [
        "scope_policy",
        "curated_action_catalog",
        "execution_gateway",
    ]

    serialized = json.dumps(metadata, sort_keys=True)
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized
    assert "approval_token" not in serialized
    assert "vault://" not in serialized


def test_provider_registry_projects_runtime_composio_readiness_without_secrets():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.provider_registry import (
        provider_registry_public_metadata,
    )

    metadata = provider_registry_public_metadata(
        composio_config=WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={
                "facebook": "authcfg_fb",
                "gmail": "authcfg_gmail",
            },
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
        ),
    )
    by_slug = {item["slug"]: item for item in metadata["providers"]}

    assert by_slug["facebook"]["enabled"] is True
    assert by_slug["facebook"]["agent_ready"] is False
    assert by_slug["facebook"]["connect_requirements"] == []
    assert by_slug["facebook"]["requirements"] == [
        "scope_policy",
        "curated_action_catalog",
        "execution_gateway",
    ]
    assert "adapter_disabled" not in by_slug["facebook"]["warnings"]
    assert "agent_actions_disabled_until_gateway_ready" in by_slug["facebook"]["warnings"]

    assert by_slug["gmail"]["enabled"] is True
    assert by_slug["gmail"]["agent_ready"] is True
    assert by_slug["gmail"]["requirements"] == []
    assert by_slug["gmail"]["agent_ready_requirements"] == []
    assert by_slug["gmail"]["action_count"] == 1
    assert by_slug["gmail"]["action_catalog"]["enabled_action_count"] == 1
    assert by_slug["gmail"]["action_catalog"]["enabled_action_slugs"] == [
        "GMAIL_FETCH_EMAILS",
    ]

    serialized = json.dumps(metadata, sort_keys=True)
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "authcfg_gmail" not in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized


def test_disabled_composio_registry_entries_remain_execution_denied():
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectExecutionRequest,
        WiiiConnectScopeGrant,
        decide_external_execution,
    )
    from app.engine.wiii_connect.provider_registry import (
        get_wiii_connect_provider_entry,
    )

    entry = get_wiii_connect_provider_entry("facebook")
    assert entry is not None

    decision = decide_external_execution(
        entry,
        WiiiConnectConnectionRecordV1(
            connection_id="conn_fake",
            provider_slug="facebook",
            state="connected",
            scopes=WiiiConnectScopeGrant(read=True, write=True, apply=True),
        ),
        WiiiConnectExecutionRequest(
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            path="external_app_action",
            mutation="write",
        ),
    )

    assert decision.allowed is False
    assert decision.reason == "provider_disabled"


def test_snapshot_projects_external_provider_registry_fail_closed(monkeypatch):
    from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot, settings

    monkeypatch.setattr(settings, "living_agent_enable_weather", False, raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "", raising=False)

    snapshot = build_wiii_connect_snapshot(state={"context": {}}, query="")
    status = snapshot.connection_status_map()
    metadata = snapshot.to_metadata()
    facebook = next(item for item in metadata["connections"] if item["slug"] == "facebook")

    assert status["facebook"]["active"] is False
    assert status["facebook"]["status"] == "not_connected"
    assert status["facebook"]["reason"] == "connection_storage_unavailable"
    assert status["facebook"]["agent_ready"] is False
    assert status["facebook"]["adapter_bound"] is False
    assert "adapter_disabled" in status["facebook"]["warnings"]
    assert "connection_storage_unavailable" in status["facebook"]["warnings"]
    assert facebook["provider_kind"] == "composio"
    assert facebook["requirement_count"] == 6
