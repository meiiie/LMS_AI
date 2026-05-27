from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest


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


def test_composio_adapter_config_parses_without_exposing_secret_values():
    from app.engine.wiii_connect.composio_adapter import (
        build_composio_adapter_config,
        build_composio_provider_adapter_capability,
        parse_composio_auth_config_map,
    )

    parsed_json = parse_composio_auth_config_map(
        '{"facebook": "authcfg_fb", "google-drive": "authcfg_drive"}',
    )
    parsed_text = parse_composio_auth_config_map(
        "facebook=authcfg_fb,gmail:authcfg_gmail",
    )
    disabled = build_composio_provider_adapter_capability(
        settings_obj=SimpleNamespace(
            enable_wiii_connect_composio=False,
            composio_api_key="secret-value",
            composio_auth_config_map='{"facebook": "authcfg_fb"}',
        ),
    )
    missing_key = build_composio_provider_adapter_capability(
        settings_obj=SimpleNamespace(
            enable_wiii_connect_composio=True,
            composio_api_key="",
            composio_auth_config_map='{"facebook": "authcfg_fb"}',
        ),
    )
    missing_auth_config = build_composio_provider_adapter_capability(
        settings_obj=SimpleNamespace(
            enable_wiii_connect_composio=True,
            composio_api_key="secret-value",
            composio_auth_config_map="",
        ),
    )
    configured_settings = SimpleNamespace(
        enable_wiii_connect_composio=True,
        composio_api_key="secret-value",
        composio_base_url="https://backend.composio.dev/",
        composio_api_version="v3.1",
        composio_auth_config_map='{"facebook": "authcfg_fb"}',
    )
    config = build_composio_adapter_config(configured_settings)
    configured = build_composio_provider_adapter_capability(config)
    metadata = {
        "config": config.to_public_metadata(),
        "disabled": disabled.to_public_metadata(),
        "missing_key": missing_key.to_public_metadata(),
        "missing_auth_config": missing_auth_config.to_public_metadata(),
        "configured": configured.to_public_metadata(),
    }
    serialized = json.dumps(metadata, sort_keys=True)

    assert parsed_json == {
        "facebook": "authcfg_fb",
        "google_drive": "authcfg_drive",
    }
    assert parsed_text == {
        "facebook": "authcfg_fb",
        "gmail": "authcfg_gmail",
    }
    assert disabled.bound is False
    assert disabled.reason == "provider_adapter_not_bound"
    assert missing_key.bound is True
    assert missing_key.configured is False
    assert "missing_composio_api_key" in missing_key.warnings
    assert missing_auth_config.configured is False
    assert "missing_composio_auth_config_map" in missing_auth_config.warnings
    assert configured.bound is True
    assert configured.configured is True
    assert configured.can_create_authorization_url is True
    assert configured.can_exchange_callback is True
    assert configured.can_execute_actions is False
    assert metadata["config"]["auth_config_count"] == 1
    assert metadata["config"]["provider_slugs"] == ["facebook"]
    assert "secret-value" not in serialized


@pytest.mark.asyncio
async def test_composio_connect_link_client_uses_v31_and_redacts_payload():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        create_composio_connect_link,
    )

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            201,
            json={
                "link_token": "secret-link-token",
                "redirect_url": "https://composio.example.test/connect/session",
                "expires_at": "2026-05-28T00:00:00Z",
                "connected_account_id": "ca_secret",
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        base_url="https://backend.composio.dev",
        api_version="v3.1",
        auth_config_by_provider={"facebook": "authcfg_fb"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await create_composio_connect_link(
            config=config,
            provider_slug="facebook",
            user_id="wiii_user_hash",
            callback_url="https://wiii.example.test/callback",
            http_client=client,
        )

    metadata = result.to_audit_metadata()
    serialized = json.dumps(
        {"metadata": metadata, "public_config": config.to_public_metadata()},
        sort_keys=True,
    )

    assert captured["url"] == (
        "https://backend.composio.dev/api/v3.1/connected_accounts/link"
    )
    assert captured["api_key"] == "secret-api-key"
    assert captured["body"] == {
        "auth_config_id": "authcfg_fb",
        "user_id": "wiii_user_hash",
        "callback_url": "https://wiii.example.test/callback",
    }
    assert result.ready is True
    assert result.redirect_url == "https://composio.example.test/connect/session"
    assert metadata["redirect_url_present"] is True
    assert metadata["connected_account_ref_present"] is True
    assert "secret-api-key" not in serialized
    assert "secret-link-token" not in serialized
    assert "ca_secret" not in serialized
    assert "authcfg_fb" not in serialized


@pytest.mark.asyncio
async def test_composio_connect_link_client_sanitizes_provider_errors():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        create_composio_connect_link,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "Invalid API key secret-api-key",
                    "access_token": "secret-token",
                }
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await create_composio_connect_link(
            config=config,
            provider_slug="facebook",
            user_id="wiii_user_hash",
            callback_url="https://wiii.example.test/callback",
            http_client=client,
        )

    serialized = json.dumps(result.to_audit_metadata(), sort_keys=True)

    assert result.ready is False
    assert result.redirect_url == ""
    assert result.reason == "provider_response_rejected"
    assert "secret-api-key" not in serialized
    assert "secret-token" not in serialized


def test_provider_adapter_status_accepts_backend_capability_override():
    from app.engine.wiii_connect.provider_adapters import (
        WiiiConnectProviderAdapterCapability,
        provider_adapter_status_public_metadata,
    )

    metadata = provider_adapter_status_public_metadata(
        adapter_capabilities=(
            WiiiConnectProviderAdapterCapability(
                provider_kind="composio",
                adapter_name="composio_adapter",
                bound=True,
                configured=True,
                can_create_authorization_url=True,
                can_exchange_callback=True,
                reason="ready",
            ),
        ),
    )
    by_kind = {adapter["provider_kind"]: adapter for adapter in metadata["adapters"]}

    assert by_kind["composio"]["bound"] is True
    assert by_kind["composio"]["configured"] is True
    assert by_kind["composio"]["authorization_ready"] is True
    assert by_kind["mcp"]["bound"] is False


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
        agent_ready=False,
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
