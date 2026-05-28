from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.wiii_connect import router as wiii_connect_router
from app.core.security import require_auth
from app.core.security_models import AuthenticatedUser


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(wiii_connect_router)
    return app


@pytest.fixture
def authenticated_app():
    app = FastAPI()
    app.include_router(wiii_connect_router)
    app.dependency_overrides[require_auth] = lambda: AuthenticatedUser(
        user_id="user_1",
        auth_method="test",
        role="admin",
        organization_id="org_1",
    )
    return app


@pytest.mark.asyncio
async def test_wiii_connect_provider_registry_api_is_privacy_safe(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers")

    assert response.status_code == 200
    payload = response.json()
    providers = payload["providers"]
    by_slug = {provider["slug"]: provider for provider in providers}

    assert payload["version"] == "wiii_connect_provider_registry.v1"
    assert payload["adapter_version"] == "wiii_connect_adapter.v1"
    assert by_slug["facebook"]["provider_kind"] == "composio"
    assert by_slug["facebook"]["enabled"] is False
    assert by_slug["facebook"]["agent_ready"] is False
    assert by_slug["facebook"]["action_count"] == 0
    assert "execution_gateway" in by_slug["facebook"]["requirements"]

    serialized = json.dumps(payload, sort_keys=True)
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized
    assert "approval_token" not in serialized
    assert "vault://" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_vault_and_audit_status_apis_are_privacy_safe(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        vault_response = await client.get("/wiii-connect/vault/status")
        audit_response = await client.get("/wiii-connect/audit-ledger/status")

    assert vault_response.status_code == 200
    assert audit_response.status_code == 200
    vault_payload = vault_response.json()
    audit_payload = audit_response.json()
    serialized = json.dumps(
        {"vault": vault_payload, "audit": audit_payload},
        sort_keys=True,
    )

    assert vault_payload["version"] == "wiii_connect_vault.v1"
    assert vault_payload["enabled"] is False
    assert vault_payload["can_store_external_secret"] is False
    assert audit_payload["version"] == "wiii_connect_audit_ledger.v1"
    assert audit_payload["enabled"] is True
    assert audit_payload["persistent"] is False
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_storage_status_api_does_not_probe_by_default(
    app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api

    def _raise_if_called():
        raise AssertionError("storage probe should be opt-in")

    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        _raise_if_called,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/storage/status")
        audit_response = await client.get("/wiii-connect/audit-ledger/status")

    assert response.status_code == 200
    assert audit_response.status_code == 200
    payload = response.json()
    audit_payload = audit_response.json()

    assert payload["version"] == "wiii_connect_persistent_storage.v1"
    assert payload["persistent"] is False
    assert payload["reason"] == "database_probe_not_requested"
    assert audit_payload["persistent"] is False
    assert audit_payload["storage"]["reason"] == "database_probe_not_requested"


@pytest.mark.asyncio
async def test_wiii_connect_storage_probe_is_explicit_and_privacy_safe(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        calls = 0
        audit_appends = 0

        def status(self, *, probe_database: bool = True):
            self.calls += 1
            assert probe_database is True
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        storage_response = await client.get(
            "/wiii-connect/storage/status",
            params={"probe_database": "true"},
        )
        audit_response = await client.get(
            "/wiii-connect/audit-ledger/status",
            params={"probe_database": "true"},
        )
        authorization_response = await client.post(
            "/wiii-connect/providers/facebook/authorization-url",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
                "state_present": True,
                "probe_database": True,
            },
        )

    assert storage_response.status_code == 200
    assert audit_response.status_code == 200
    assert authorization_response.status_code == 200
    assert fake_storage.calls == 3
    assert fake_storage.audit_appends == 1

    storage_payload = storage_response.json()
    audit_payload = audit_response.json()
    authorization_payload = authorization_response.json()
    serialized = json.dumps(
        {
            "storage": storage_payload,
            "audit": audit_payload,
            "authorization": authorization_payload,
        },
        sort_keys=True,
    )

    assert storage_payload["persistent"] is True
    assert storage_payload["reason"] == "ready"
    assert audit_payload["persistent"] is True
    assert audit_payload["storage"]["audit_ledger_ready"] is True
    assert authorization_payload["reason"] == "provider_disabled"
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_provider_adapter_status_api_is_fail_closed(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/provider-adapters/status")

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    by_kind = {adapter["provider_kind"]: adapter for adapter in payload["adapters"]}

    assert payload["version"] == "wiii_connect_provider_adapter.v1"
    assert by_kind["composio"]["bound"] is False
    assert by_kind["composio"]["configured"] is False
    assert by_kind["composio"]["authorization_ready"] is False
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_provider_status_api_is_fail_closed(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/facebook/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "wiii_connect_session.v1"
    assert payload["provider_slug"] == "facebook"
    assert payload["can_start_authorization"] is False
    assert payload["reason"] == "provider_disabled"
    assert "provider_managed_vault_ref" in payload["missing_requirements"]
    assert "execution_gateway" not in payload["missing_requirements"]


@pytest.mark.asyncio
async def test_wiii_connect_session_start_api_blocks_without_leaking_secrets(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/sessions",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
                "requested_scopes": {"read": True, "write": True},
                "request_metadata": {
                    "access_token": "secret-value",
                    "client_secret": "secret-value",
                    "workspace_id": "workspace_1",
                },
                "refresh_token": "secret-value",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_session.v1"
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_disabled"
    assert payload["authorization_url"] == ""
    assert payload["audit_event"]["request"]["requested_scopes"]["write"] is True
    assert "redacted_sensitive_field" in serialized
    assert "workspace_id" in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_session_api_404_for_unknown_provider(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/wiii-connect/providers/not-real/sessions")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown_wiii_connect_provider"


@pytest.mark.asyncio
async def test_wiii_connect_authorization_url_api_blocks_without_leaking_secrets(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/authorization-url",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
                "state_present": True,
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wiii_connect_authorization_url_api_blocks_without_leaking_secrets_when_authenticated(
    authenticated_app,
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/authorization-url",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
                "state_present": True,
                "requested_scopes": {"read": True},
                "request_metadata": {
                    "access_token": "secret-value",
                    "client_secret": "secret-value",
                    "workspace_id": "workspace_1",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_provider_adapter.v1"
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_disabled"
    assert payload["authorization_url"] == ""
    assert "redacted_sensitive_field" in serialized
    assert "workspace_id" in serialized
    assert "access_token" not in serialized
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_authorization_url_api_issues_sanitized_composio_link(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioConnectLinkResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        connection_upserts = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(metadata, sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["connect_link"]["ready"] is True
            assert "link_token" not in serialized
            assert "ca_secret" not in serialized
            return True

        def upsert_connection_record(
            self,
            connection,
            *,
            organization_id: str,
            user_id: str,
            provider_kind: str,
        ):
            self.connection_upserts += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_kind == "composio"
            assert connection.connection_id == "ca_123"
            assert connection.state == "authorizing"
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"facebook": "authcfg_fb"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_connect_link(**kwargs):
        assert kwargs["provider_slug"] == "facebook"
        callback = urlsplit(kwargs["callback_url"])
        assert callback.scheme == "https"
        assert callback.netloc == "wiii.example.test"
        assert callback.path == "/callback"
        assert "wiii_state" in parse_qs(callback.query)
        assert kwargs["user_id"].startswith("wiii_")
        return WiiiConnectComposioConnectLinkResult(
            ready=True,
            redirect_url="https://composio.example.test/connect/session",
            connected_account_id="ca_123",
            connected_account_ref_present=True,
            reason="ready",
        )

    monkeypatch.setattr(
        wiii_connect_api,
        "create_composio_connect_link",
        fake_connect_link,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/authorization-url",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
                "state_present": True,
                "probe_database": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "ready"
    assert payload["reason"] == "authorization_url_issued"
    assert payload["authorization_url"] == "https://composio.example.test/connect/session"
    assert payload["adapter"]["can_execute_actions"] is False
    assert fake_storage.audit_appends == 1
    assert fake_storage.connection_upserts == 1
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "link_token" not in serialized
    assert "ca_secret" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_authorization_url_api_sanitizes_composio_failure(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioConnectLinkResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert "provider raw error with secret-api-key" not in serialized
            return True

    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"facebook": "authcfg_fb"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: FakeStorage(),
    )

    async def fake_connect_link(**kwargs):
        return WiiiConnectComposioConnectLinkResult(
            ready=False,
            reason="provider raw error with secret-api-key",
        )

    monkeypatch.setattr(
        wiii_connect_api,
        "create_composio_connect_link",
        fake_connect_link,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/authorization-url",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
                "state_present": True,
                "probe_database": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "authorization_url_missing"
    assert payload["authorization_url"] == ""
    assert "secret-api-key" not in serialized
    assert "provider raw error" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_connections_api_requires_auth(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/facebook/connections")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wiii_connect_connections_api_lists_and_persists_safely(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectConnectionRecordV1
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioConnectionListResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        upserts = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def upsert_connection_record(
            self,
            connection,
            *,
            organization_id: str,
            user_id: str,
            provider_kind: str,
        ):
            self.upserts += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_kind == "composio"
            assert connection.connection_id == "ca_active"
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"facebook": "authcfg_fb"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_list_connections(**kwargs):
        assert kwargs["provider_slug"] == "facebook"
        assert kwargs["user_id"].startswith("wiii_")
        return WiiiConnectComposioConnectionListResult(
            ready=True,
            reason="ready",
            connections=(
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="facebook",
                    state="connected",
                    reason="provider_connection_list",
                ),
            ),
        )

    monkeypatch.setattr(
        wiii_connect_api,
        "list_composio_connected_accounts",
        fake_list_connections,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/providers/facebook/connections",
            params={"probe_database": "true"},
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "ready"
    assert payload["reason"] == "ready"
    assert payload["connection_count"] == 1
    assert payload["connections"][0]["connection_id"] == "ca_active"
    assert payload["connections"][0]["state"] == "connected"
    assert fake_storage.upserts == 1
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_execution_decision_api_requires_auth(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/execution-decision",
            json={"action_slug": "FACEBOOK_GET_PAGE"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wiii_connect_execution_decision_api_audits_fail_closed(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        fetches = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def get_connection_record(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
            connection_id: str | None = None,
        ):
            self.fetches += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "facebook"
            assert connection_id == "ca_active"
            return WiiiConnectConnectionRecordV1(
                connection_id="ca_active",
                provider_slug="facebook",
                state="connected",
                scopes=WiiiConnectScopeGrant(read=True, write=True),
                reason="provider_connection_list",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["request"]["action_slug"] == "FACEBOOK_GET_PAGE"
            assert metadata["connection_found"] is True
            assert "approval_token" not in serialized
            assert "secret-value" not in serialized
            assert "access_token" not in serialized
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"facebook": "authcfg_fb"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/execution-decision",
            json={
                "surface": "desktop",
                "connection_id": "ca_active",
                "action_slug": "FACEBOOK_GET_PAGE",
                "path": "external_app_action",
                "mutation": "read",
                "argument_keys": ["page_id", "access_token"],
                "approval_token": "secret-value",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_execution_gateway.v1"
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_not_agent_ready"
    assert payload["connection_present"] is True
    assert payload["adapter"]["can_execute_actions"] is False
    assert fake_storage.fetches == 1
    assert fake_storage.audit_appends == 1
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "secret-value" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_authorization_url_api_404_for_unknown_provider(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/not-real/authorization-url",
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wiii_connect_authorization_url_api_404_for_unknown_provider_when_authenticated(
    authenticated_app,
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/not-real/authorization-url",
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown_wiii_connect_provider"


@pytest.mark.asyncio
async def test_wiii_connect_callback_api_blocks_and_redacts_oauth_values(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/providers/facebook/callback",
            params={
                "state": "secret-state-value",
                "code": "oauth-code-value",
                "client_secret": "secret-value",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_callback.v1"
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_disabled"
    assert payload["vault_ref_issued"] is False
    assert payload["audit_event"]["request"]["state_present"] is True
    assert payload["audit_event"]["request"]["code_present"] is True
    assert "redacted_sensitive_field" in serialized
    assert "secret-state-value" not in serialized
    assert "oauth-code-value" not in serialized
    assert "client_secret" not in serialized
    assert "secret-value" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_callback_api_reconciles_signed_composio_connection(
    app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.core.config import settings
    from app.engine.wiii_connect.callback_state import (
        build_wiii_connect_callback_state,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        connection_upserts = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(metadata, sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["state"]["valid"] is True
            assert "secret-state-value" not in serialized
            return True

        def upsert_connection_record(
            self,
            connection,
            *,
            organization_id: str,
            user_id: str,
            provider_kind: str,
        ):
            self.connection_upserts += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_kind == "composio"
            assert connection.connection_id == "ca_123"
            assert connection.state == "connected"
            return True

    state = build_wiii_connect_callback_state(
        provider_slug="facebook",
        organization_id="org_1",
        user_id="user_1",
        secret_key=settings.session_secret_key,
    )
    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"facebook": "authcfg_fb"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/providers/facebook/callback",
            params={
                "wiii_state": state,
                "connected_account_id": "ca_123",
                "status": "ACTIVE",
                "client_secret": "secret-value",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "accepted"
    assert payload["reason"] == "accepted"
    assert payload["vault_ref_issued"] is True
    assert fake_storage.audit_appends == 1
    assert fake_storage.connection_upserts == 1
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "secret-value" not in serialized
    assert state not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_callback_api_404_for_unknown_provider(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/not-real/callback")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown_wiii_connect_provider"
