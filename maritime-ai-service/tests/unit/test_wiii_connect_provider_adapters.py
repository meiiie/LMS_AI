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
        parse_composio_readonly_action_allowlist,
    )

    parsed_json = parse_composio_auth_config_map(
        '{"facebook": "authcfg_fb", "google-drive": "authcfg_drive"}',
    )
    parsed_text = parse_composio_auth_config_map(
        "facebook=authcfg_fb,gmail:authcfg_gmail",
    )
    parsed_actions = parse_composio_readonly_action_allowlist(
        "gmail=GMAIL_FETCH_EMAILS",
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
    dynamic_auth_config = build_composio_provider_adapter_capability(
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
        "dynamic_auth_config": dynamic_auth_config.to_public_metadata(),
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
    assert parsed_actions == {"gmail": ("GMAIL_FETCH_EMAILS",)}
    assert disabled.bound is False
    assert disabled.reason == "provider_adapter_not_bound"
    assert missing_key.bound is True
    assert missing_key.configured is False
    assert "missing_composio_api_key" in missing_key.warnings
    assert dynamic_auth_config.configured is True
    assert dynamic_auth_config.can_create_authorization_url is True
    assert (
        "composio_auth_config_will_be_resolved_from_provider"
        in dynamic_auth_config.warnings
    )
    assert configured.bound is True
    assert configured.configured is True
    assert configured.can_create_authorization_url is True
    assert configured.can_exchange_callback is True
    assert configured.can_execute_actions is False
    assert metadata["config"]["auth_config_count"] == 1
    assert metadata["config"]["provider_slugs"] == ["facebook"]
    assert metadata["config"]["readonly_execute_enabled"] is False
    assert metadata["config"]["readonly_action_count"] == 0
    assert "secret-value" not in serialized


def test_composio_readonly_execute_requires_explicit_curated_allowlist():
    from app.engine.wiii_connect.composio_adapter import (
        build_composio_adapter_config,
        build_composio_execution_enabled_entry,
        build_composio_provider_adapter_capability,
    )
    from app.engine.wiii_connect.provider_registry import (
        get_wiii_connect_provider_entry,
    )

    settings_obj = SimpleNamespace(
        enable_wiii_connect_composio=True,
        enable_wiii_connect_composio_readonly_execute=True,
        composio_api_key="secret-value",
        composio_base_url="https://backend.composio.dev",
        composio_api_version="v3.1",
        composio_auth_config_map='{"gmail": "authcfg_gmail"}',
        composio_readonly_action_allowlist='{"gmail": ["GMAIL_FETCH_EMAILS"]}',
    )
    config = build_composio_adapter_config(settings_obj)
    capability = build_composio_provider_adapter_capability(config)
    entry = get_wiii_connect_provider_entry("gmail")
    assert entry is not None
    effective = build_composio_execution_enabled_entry(entry, config)
    serialized = json.dumps(
        {
            "config": config.to_public_metadata(),
            "capability": capability.to_public_metadata(),
            "entry": effective.to_public_metadata(),
        },
        sort_keys=True,
    )

    assert config.readonly_action_slugs_for_provider("gmail") == (
        "GMAIL_FETCH_EMAILS",
    )
    assert capability.can_execute_actions is True
    assert effective.enabled is True
    assert effective.agent_ready is True
    assert effective.action_allowlist == ("GMAIL_FETCH_EMAILS",)
    assert effective.default_scopes.read is True
    assert "secret-value" not in serialized
    assert "authcfg_gmail" not in serialized


def test_composio_apply_execute_requires_explicit_curated_allowlist():
    from app.engine.wiii_connect.composio_adapter import (
        build_composio_adapter_config,
        build_composio_execution_enabled_entry,
        build_composio_provider_adapter_capability,
        parse_composio_apply_action_allowlist,
    )
    from app.engine.wiii_connect.provider_registry import (
        get_wiii_connect_provider_entry,
    )

    parsed_actions = parse_composio_apply_action_allowlist(
        "facebook=FACEBOOK_CREATE_PHOTO_POST|FACEBOOK_CREATE_POST",
    )
    settings_obj = SimpleNamespace(
        enable_wiii_connect_composio=True,
        enable_wiii_connect_composio_apply_execute=True,
        composio_api_key="secret-value",
        composio_base_url="https://backend.composio.dev",
        composio_api_version="v3.1",
        composio_auth_config_map='{"facebook": "authcfg_fb"}',
        composio_apply_action_allowlist=(
            '{"facebook": ["FACEBOOK_CREATE_PHOTO_POST", "FACEBOOK_CREATE_POST"]}'
        ),
    )
    config = build_composio_adapter_config(settings_obj)
    capability = build_composio_provider_adapter_capability(config)
    entry = get_wiii_connect_provider_entry("facebook")
    assert entry is not None
    effective = build_composio_execution_enabled_entry(entry, config)
    serialized = json.dumps(
        {
            "config": config.to_public_metadata(),
            "capability": capability.to_public_metadata(),
            "entry": effective.to_public_metadata(),
        },
        sort_keys=True,
    )

    assert parsed_actions == {
        "facebook": ("FACEBOOK_CREATE_PHOTO_POST", "FACEBOOK_CREATE_POST"),
    }
    assert config.apply_action_slugs_for_provider("facebook") == (
        "FACEBOOK_CREATE_PHOTO_POST",
        "FACEBOOK_CREATE_POST",
    )
    assert capability.can_execute_actions is True
    assert effective.enabled is True
    assert effective.agent_ready is True
    assert set(effective.action_allowlist) == {
        "FACEBOOK_CREATE_PHOTO_POST",
        "FACEBOOK_CREATE_POST",
    }
    assert effective.default_scopes.read is True
    assert effective.default_scopes.preview is True
    assert effective.default_scopes.apply is True
    assert "secret-value" not in serialized
    assert "authcfg_fb" not in serialized


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
async def test_composio_connect_link_resolves_auth_config_like_openhuman_direct_mode():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        create_composio_connect_link,
    )

    captured: list[tuple[str, str, dict[str, object] | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth_configs"):
            captured.append(("GET", str(request.url), None))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "authcfg_disabled", "status": "DISABLED"},
                        {"id": "authcfg_fb_dynamic", "status": "ENABLED"},
                    ]
                },
            )
        captured.append(
            (
                request.method,
                str(request.url),
                json.loads(request.content.decode("utf-8")),
            )
        )
        return httpx.Response(
            201,
            json={"redirect_url": "https://composio.example.test/connect/session"},
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        base_url="https://backend.composio.dev",
        api_version="v3.1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await create_composio_connect_link(
            config=config,
            provider_slug="facebook",
            user_id="wiii_user_hash",
            callback_url="https://wiii.example.test/callback",
            http_client=client,
        )

    assert result.ready is True
    assert captured[0][0] == "GET"
    assert "/auth_configs" in captured[0][1]
    assert "toolkit_slug=facebook" in captured[0][1]
    assert captured[1][2] == {
        "auth_config_id": "authcfg_fb_dynamic",
        "user_id": "wiii_user_hash",
        "callback_url": "https://wiii.example.test/callback",
    }


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


@pytest.mark.asyncio
async def test_composio_connection_list_client_filters_and_sanitizes_accounts():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        list_composio_connected_accounts,
    )

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["request_id"] = request.headers.get("X-Request-ID")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "ca_active",
                        "status": "ACTIVE",
                        "state": {"val": {"access_token": "secret-token"}},
                    },
                    {
                        "id": "ca_pending",
                        "status": "INITIATED",
                        "state": {"val": {"refresh_token": "secret-token"}},
                    },
                ],
                "cursor": "secret-cursor-value",
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await list_composio_connected_accounts(
            config=config,
            provider_slug="facebook",
            user_id="wiii_user_hash",
            http_client=client,
        )

    public = result.to_public_metadata()
    serialized = json.dumps(public, sort_keys=True)

    assert captured["url"].startswith(
        "https://backend.composio.dev/api/v3.1/connected_accounts?"
    )
    assert "user_ids=wiii_user_hash" in captured["url"]
    assert "auth_config_ids=authcfg_fb" in captured["url"]
    assert "account_type=PRIVATE" in captured["url"]
    assert captured["api_key"] == "secret-api-key"
    assert result.ready is True
    assert public["connection_count"] == 2
    assert public["connections"][0]["connection_ref"].startswith("wcn_")
    assert public["connections"][0]["state"] == "connected"
    assert public["connections"][1]["state"] == "waiting"
    assert "ca_active" not in serialized
    assert "ca_pending" not in serialized
    assert "connection_id" not in serialized
    assert "secret-api-key" not in serialized
    assert "secret-token" not in serialized
    assert "secret-cursor-value" not in serialized


@pytest.mark.asyncio
async def test_composio_connection_list_client_sanitizes_provider_errors():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        list_composio_connected_accounts,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid key secret-api-key"}},
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await list_composio_connected_accounts(
            config=config,
            provider_slug="facebook",
            user_id="wiii_user_hash",
            http_client=client,
        )

    serialized = json.dumps(result.to_public_metadata(), sort_keys=True)

    assert result.ready is False
    assert result.reason == "provider_response_rejected"
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_composio_connection_list_resolves_auth_config_without_static_map():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        list_composio_connected_accounts,
    )

    captured: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        if request.url.path.endswith("/auth_configs"):
            return httpx.Response(
                200,
                json={"items": [{"id": "authcfg_fb_dynamic", "enabled": True}]},
            )
        return httpx.Response(
            200,
            json={"items": [{"id": "ca_active", "status": "ACTIVE"}]},
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await list_composio_connected_accounts(
            config=config,
            provider_slug="facebook",
            user_id="wiii_user_hash",
            http_client=client,
        )

    assert result.ready is True
    assert result.connections[0].state == "connected"
    assert "/auth_configs" in captured[0]
    assert "auth_config_ids=authcfg_fb_dynamic" in captured[1]


@pytest.mark.asyncio
async def test_composio_tool_schema_client_uses_v31_and_redacts_shape():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        verify_composio_tool_schema,
    )

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["request_id"] = request.headers.get("X-Request-ID")
        return httpx.Response(
            200,
            json={
                "slug": "GMAIL_FETCH_EMAILS",
                "toolkit": {"slug": "gmail"},
                "input_parameters": {
                    "query": {"type": "string", "required": True},
                    "max_results": {"type": "number"},
                    "access_token": {"type": "string"},
                },
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"gmail": "authcfg_gmail"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await verify_composio_tool_schema(
            config=config,
            provider_slug="gmail",
            action_slug="GMAIL_FETCH_EMAILS",
            request_id="req-composio-schema-1",
            http_client=client,
        )

    public = result.to_public_metadata()
    serialized = json.dumps(public, sort_keys=True)

    assert captured["url"] == (
        "https://backend.composio.dev/api/v3.1/tools/GMAIL_FETCH_EMAILS"
        "?toolkit_versions=latest"
    )
    assert captured["api_key"] == "secret-api-key"
    assert captured["request_id"] == "req-composio-schema-1"
    assert public["status"] == "ready"
    assert public["reason"] == "ready"
    assert public["request_id"] == "req-composio-schema-1"
    assert public["schema_present"] is True
    assert "query" in public["argument_keys"]
    assert "max_results" in public["argument_keys"]
    assert "redacted_sensitive_field" in public["argument_keys"]
    assert "access_token" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized


@pytest.mark.asyncio
async def test_composio_execute_client_uses_allowlist_and_redacts_provider_data():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        execute_composio_tool,
    )

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["request_id"] = request.headers.get("X-Request-ID")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "data": {
                    "messages": [{"subject": "private subject"}],
                    "access_token": "secret-provider-token",
                },
                "error": None,
                "successful": True,
                "session_info": {"session_id": "session-secret"},
                "log_id": "log-secret",
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"gmail": "authcfg_gmail"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_composio_tool(
            config=config,
            provider_slug="gmail",
            action_slug="GMAIL_FETCH_EMAILS",
            user_id="wiii_user_hash",
            connected_account_id="ca_active",
            arguments={"query": "from:me", "access_token": "client-secret"},
            request_id="req-composio-execute-1",
            http_client=client,
        )

    public = result.to_public_metadata()
    serialized = json.dumps(public, sort_keys=True)

    assert captured["url"] == (
        "https://backend.composio.dev/api/v3.1/tools/execute/GMAIL_FETCH_EMAILS"
    )
    assert captured["api_key"] == "secret-api-key"
    assert captured["request_id"] == "req-composio-execute-1"
    assert captured["body"] == {
        "user_id": "wiii_user_hash",
        "connected_account_id": "ca_active",
        "arguments": {"query": "from:me", "access_token": "client-secret"},
    }
    assert public["status"] == "succeeded"
    assert public["reason"] == "ready"
    assert public["request_id"] == "req-composio-execute-1"
    assert "messages" in public["data_keys"]
    assert "redacted_sensitive_field" in public["data_keys"]
    assert public["session_info_present"] is True
    assert public["log_id_present"] is True
    assert "private subject" not in serialized
    assert "secret-provider-token" not in serialized
    assert "session-secret" not in serialized
    assert "log-secret" not in serialized
    assert "client-secret" not in serialized
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_composio_file_upload_stages_descriptor_without_leaking_s3_key():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        stage_composio_file_upload,
    )

    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (
                request.method,
                str(request.url),
                request.headers.get("x-api-key"),
                request.headers.get("X-Request-ID"),
            )
        )
        if request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            assert body["toolkit_slug"] == "facebook"
            assert body["tool_slug"] == "FACEBOOK_CREATE_PHOTO_POST"
            assert body["filename"] == "post.png"
            assert body["mimetype"] == "image/png"
            assert len(body["md5"]) == 32
            return httpx.Response(
                200,
                json={
                    "key": "secret-s3-key",
                    "new_presigned_url": "https://upload.example.test/file",
                },
            )
        assert request.method == "PUT"
        assert request.content == b"fake-image"
        assert request.headers.get("Content-Type") == "image/png"
        return httpx.Response(200)

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
        apply_execute_enabled=True,
        apply_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_CREATE_PHOTO_POST",),
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await stage_composio_file_upload(
            config=config,
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_PHOTO_POST",
            filename="post.png",
            mimetype="image/png",
            content=b"fake-image",
            request_id="req-composio-upload-1",
            http_client=client,
        )

    public = result.to_public_metadata()
    serialized = json.dumps(public, sort_keys=True)

    assert len(calls) == 2
    assert calls[0][1] == "https://backend.composio.dev/api/v3/files/upload/request"
    assert calls[0][2] == "secret-api-key"
    assert calls[0][3] == "req-composio-upload-1"
    assert calls[1][1] == "https://upload.example.test/file"
    assert calls[1][3] is None
    assert result.ready is True
    assert result.file_descriptor == {
        "name": "post.png",
        "mimetype": "image/png",
        "s3key": "secret-s3-key",
    }
    assert public["file_ref_present"] is True
    assert public["request_id"] == "req-composio-upload-1"
    assert "secret-s3-key" not in serialized
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_composio_facebook_pages_client_strips_tokens():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        list_composio_facebook_pages,
    )

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["request_id"] = request.headers.get("X-Request-ID")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "successful": True,
                "data": {
                    "data": [
                        {
                            "id": "123456",
                            "name": "Wiii Page",
                            "category": "Education",
                            "link": "https://facebook.com/wiii",
                            "access_token": "secret-page-token",
                        }
                    ]
                },
                "log_id": "secret-log",
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"facebook": "authcfg_fb"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await list_composio_facebook_pages(
            config=config,
            user_id="wiii_user_hash",
            connected_account_id="ca_active",
            request_id="req-composio-pages-1",
            http_client=client,
        )

    public = result.to_public_metadata()
    serialized = json.dumps(public, sort_keys=True)

    assert captured["url"] == (
        "https://backend.composio.dev/api/v3.1/tools/execute/FACEBOOK_LIST_MANAGED_PAGES"
    )
    assert captured["body"]["user_id"] == "wiii_user_hash"
    assert captured["body"]["connected_account_id"] == "ca_active"
    assert captured["request_id"] == "req-composio-pages-1"
    assert result.ready is True
    assert public["page_count"] == 1
    assert public["request_id"] == "req-composio-pages-1"
    assert public["pages"][0]["page_id"] == "123456"
    assert public["pages"][0]["name"] == "Wiii Page"
    assert "secret-page-token" not in serialized
    assert "secret-api-key" not in serialized
    assert "secret-log" not in serialized


@pytest.mark.asyncio
async def test_composio_disconnect_client_soft_deletes_and_redacts_payload():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        disconnect_composio_connected_account,
    )

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        return httpx.Response(
            200,
            json={
                "success": True,
                "access_token": "secret-provider-token",
                "log_id": "secret-log",
            },
        )

    config = WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="secret-api-key",
        api_key_present=True,
        auth_config_by_provider={"gmail": "authcfg_gmail"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await disconnect_composio_connected_account(
            config=config,
            provider_slug="gmail",
            connected_account_id="ca_active",
            http_client=client,
        )

    public = result.to_public_metadata()
    serialized = json.dumps(public, sort_keys=True)

    assert captured["url"] == (
        "https://backend.composio.dev/api/v3.1/connected_accounts/ca_active"
    )
    assert captured["api_key"] == "secret-api-key"
    assert public["status"] == "succeeded"
    assert public["reason"] == "ready"
    assert public["connection_ref_present"] is True
    assert public["provider_success"] is True
    assert "secret-api-key" not in serialized
    assert "secret-provider-token" not in serialized
    assert "secret-log" not in serialized
    assert "authcfg_gmail" not in serialized


@pytest.mark.asyncio
async def test_composio_disconnect_client_sanitizes_provider_errors():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        disconnect_composio_connected_account,
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
        auth_config_by_provider={"gmail": "authcfg_gmail"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await disconnect_composio_connected_account(
            config=config,
            provider_slug="gmail",
            connected_account_id="ca_active",
            http_client=client,
        )

    serialized = json.dumps(result.to_public_metadata(), sort_keys=True)

    assert result.ready is False
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
