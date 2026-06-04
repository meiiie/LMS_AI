from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.wiii_connect import router as wiii_connect_router
from app.core.security import optional_auth, require_auth
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


@pytest.fixture
def optionally_authenticated_app():
    app = FastAPI()
    app.include_router(wiii_connect_router)
    app.dependency_overrides[optional_auth] = lambda: AuthenticatedUser(
        user_id="user_1",
        auth_method="test",
        role="admin",
        organization_id="org_1",
        session_id="session_1",
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
    assert isinstance(by_slug["facebook"]["enabled"], bool)
    assert isinstance(by_slug["facebook"]["agent_ready"], bool)
    assert by_slug["facebook"]["action_count"] >= 0
    assert isinstance(by_slug["facebook"]["requirements"], list)

    serialized = json.dumps(payload, sort_keys=True)
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized
    assert "approval-secret" not in serialized
    assert "vault://" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_snapshot_api_returns_runtime_contract_without_secrets(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/snapshot",
            params={"query": "đăng facebook", "surface": "desktop"},
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    by_slug = {connection["slug"]: connection for connection in payload["connections"]}
    by_path = {item["path"]: item for item in payload["path_capabilities"]}

    assert payload["version"] == "wiii_connect_snapshot.v0"
    assert payload["surface"] == "desktop"
    assert by_slug["server"]["status"] == "connected"
    assert by_slug["facebook"]["provider_kind"] == "composio"
    assert by_path["external_app_action"]["delegation_policy"] == (
        "delegate_to_integrations_agent"
    )
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized
    assert "approval-secret" not in serialized
    assert "đăng facebook" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_doctor_api_returns_readiness_summary_without_secrets(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/doctor",
            params={"query": "post private secret text", "surface": "desktop"},
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    by_path = {item["path"]: item for item in payload["path_diagnostics"]}
    by_provider = {
        item["provider_slug"]: item for item in payload["provider_diagnostics"]
    }

    assert payload["version"] == "wiii_connect_doctor.v0"
    assert payload["surface"] == "desktop"
    assert payload["summary"]["total_paths"] >= 1
    assert by_path["casual_chat"]["status"] == "ready"
    assert by_path["external_app_action"]["reason"] == (
        "no_agent_ready_external_provider"
    )
    assert by_provider["facebook"]["status"] == "blocked"
    assert by_provider["facebook"]["reason"] == "connection_storage_unavailable"
    assert by_provider["facebook"]["required_next"] == [
        "configure_wiii_connect_storage"
    ]
    assert "post private secret text" not in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized
    assert "approval-secret" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_snapshot_rejects_invalid_optional_api_key(app):
    from unittest.mock import MagicMock, patch

    mock_settings = MagicMock()
    mock_settings.api_key = "valid-api-key"
    mock_settings.lms_service_token = None
    mock_settings.environment = "production"
    mock_settings.enable_auth_audit = False

    with patch("app.core.security.settings", mock_settings):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/wiii-connect/snapshot",
                headers={"X-API-Key": "wrong-api-key"},
            )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


@pytest.mark.asyncio
async def test_wiii_connect_snapshot_and_doctor_use_optional_auth_scope(
    optionally_authenticated_app,
    monkeypatch,
):
    from dataclasses import replace

    from app.engine.wiii_connect import snapshot as snapshot_module
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
    )

    def enable_provider(entry, config):
        return replace(
            entry,
            enabled=True,
            agent_ready=True,
            action_allowlist=("FACEBOOK_CREATE_PAGE_POST",),
            default_scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
            requirements=(),
            connect_requirements=(),
            agent_ready_requirements=(),
            warnings=(),
        )

    class FakeStorage:
        def list_connection_records(self, **kwargs):
            assert kwargs["organization_id"] == "org_1"
            assert kwargs["user_id"] == "user_1"
            if kwargs["provider_slug"] != "facebook":
                return ()
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_private_active",
                    provider_slug="facebook",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
                    account_label="Private Facebook Page",
                    external_account_ref="external-private-ref",
                    reason="provider_connection_list",
                ),
            )

    monkeypatch.setattr(
        snapshot_module,
        "build_composio_execution_enabled_entry",
        enable_provider,
    )
    monkeypatch.setattr(
        snapshot_module,
        "storage_status_metadata",
        lambda: {
            "persistent": True,
            "connection_table_ready": True,
            "audit_ledger_ready": True,
        },
    )
    monkeypatch.setattr(
        snapshot_module,
        "get_wiii_connect_persistent_storage",
        lambda: FakeStorage(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=optionally_authenticated_app),
        base_url="http://test",
    ) as client:
        snapshot_response = await client.get(
            "/wiii-connect/snapshot",
            params={"query": "dang facebook private text", "surface": "desktop"},
        )
        doctor_response = await client.get(
            "/wiii-connect/doctor",
            params={"query": "dang facebook private text", "surface": "desktop"},
        )

    assert snapshot_response.status_code == 200
    assert doctor_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    doctor_payload = doctor_response.json()
    serialized = json.dumps(
        {"snapshot": snapshot_payload, "doctor": doctor_payload},
        ensure_ascii=False,
        sort_keys=True,
    )
    facebook = {
        connection["slug"]: connection
        for connection in snapshot_payload["connections"]
    }["facebook"]
    by_path = {item["path"]: item for item in doctor_payload["path_diagnostics"]}
    by_provider = {
        item["provider_slug"]: item for item in doctor_payload["provider_diagnostics"]
    }

    assert facebook["status"] == "connected"
    assert facebook["agent_ready"] is True
    assert facebook["connection_ref_present"] is True
    assert doctor_payload["summary"]["external_agent_ready_connections"] == 1
    assert by_path["external_app_action"]["status"] == "guarded"
    assert by_path["external_app_action"]["reason"] == (
        "provider_worker_gateway_required"
    )
    assert by_provider["facebook"]["status"] == "guarded"
    assert by_provider["facebook"]["reason"] == "agent_ready_gateway_required"
    assert by_provider["facebook"]["connection_status"] == "connected"
    assert by_provider["facebook"]["required_next"] == [
        "select_action_and_evaluate_gateway"
    ]
    assert "ca_private_active" not in serialized
    assert "Private Facebook Page" not in serialized
    assert "external-private-ref" not in serialized
    assert "dang facebook private text" not in serialized


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
async def test_wiii_connect_session_status_uses_runtime_composio_config(
    app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            apply_execute_enabled=True,
            apply_action_allowlist_by_provider={
                "facebook": ("FACEBOOK_CREATE_POST",),
            },
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        status_response = await client.get("/wiii-connect/providers/facebook/status")
        session_response = await client.post(
            "/wiii-connect/providers/facebook/sessions",
            json={
                "surface": "desktop",
                "redirect_uri": "https://wiii.example.test/callback",
            },
        )

    assert status_response.status_code == 200
    assert session_response.status_code == 200
    status_payload = status_response.json()
    session_payload = session_response.json()
    serialized = json.dumps(
        {"status": status_payload, "session": session_payload},
        sort_keys=True,
    )

    assert status_payload["enabled"] is True
    assert status_payload["agent_ready"] is True
    assert status_payload["reason"] == "provider_adapter_not_bound"
    assert status_payload["missing_requirements"] == []
    assert session_payload["status"] == "blocked"
    assert session_payload["reason"] == "provider_adapter_not_bound"
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_activation_readiness_api_fails_closed_without_config(
    authenticated_app,
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/providers/gmail/activation-readiness",
            params={"probe_database": "false"},
        )

    assert response.status_code == 200
    payload = response.json()
    gates = {gate["key"]: gate for gate in payload["gates"]}
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["version"] == "wiii_connect_activation_readiness.v1"
    assert payload["status"] == "blocked"
    assert payload["provider_slug"] == "gmail"
    assert payload["ready_to_connect"] is False
    assert payload["ready_to_execute_readonly"] is False
    assert gates["provider_registered"]["ready"] is True
    assert gates["provider_adapter"]["ready"] is False
    assert gates["persistent_storage"]["ready"] is False
    assert gates["curated_readonly_action"]["ready"] is False
    assert gates["local_connection"]["reason"] == "connection_missing"
    assert payload["connection"]["present"] is False
    assert payload["connection_lifecycle"]["version"] == (
        "wiii_connect_connection_lifecycle.v1"
    )
    assert payload["connection_lifecycle"]["status"] == "disconnected"
    assert payload["connection_lifecycle"]["connection_present"] is False
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "api_key" not in serialized
    assert "approval_token" not in serialized
    assert "authcfg" not in serialized
    assert "vault://" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_activation_readiness_default_action_is_provider_scoped(
    authenticated_app,
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/wiii-connect/providers/facebook/activation-readiness",
            params={"probe_database": "false"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_slug"] == "facebook"
    assert payload["action"]["provider_slug"] == "facebook"
    assert payload["action"]["slug"] == "FACEBOOK_LIST_MANAGED_PAGES"


@pytest.mark.asyncio
async def test_wiii_connect_activation_readiness_api_reports_ready_without_leaks(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        fetches = 0
        expires = 0
        lists = 0

        def status(self, *, probe_database: bool = True):
            assert probe_database is True
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def expire_stale_pending_connections(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
            ttl_seconds: int,
        ):
            self.expires += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            assert ttl_seconds >= 60
            return 1

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="gmail",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True),
                ),
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
            assert provider_slug == "gmail"
            assert connection_id == "ca_active"
            return WiiiConnectConnectionRecordV1(
                connection_id="ca_active",
                provider_slug="gmail",
                state="connected",
                scopes=WiiiConnectScopeGrant(read=True),
                vault_ref=WiiiConnectVaultSecretRef(
                    provider_slug="gmail",
                    connection_id="ca_active",
                    vault_key_id="provider-managed://composio/ca_active",
                    secret_version="provider_managed",
                ),
                account_label="private-user@example.test",
                external_account_ref="acct_private",
                reason="provider_connection_list",
            )

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
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
        response = await client.get(
            "/wiii-connect/providers/gmail/activation-readiness",
            params={
                "action_slug": "GMAIL_FETCH_EMAILS",
                "connection_ref": public_connection_ref("gmail", "ca_active"),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    gates = {gate["key"]: gate for gate in payload["gates"]}
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "ready"
    assert payload["provider_slug"] == "gmail"
    assert payload["ready_to_connect"] is True
    assert payload["ready_to_execute_readonly"] is True
    assert payload["action"]["slug"] == "GMAIL_FETCH_EMAILS"
    assert payload["action"]["runtime_enabled"] is True
    assert payload["connection"]["present"] is True
    assert payload["connection"]["active"] is True
    assert payload["connection"]["vault_ref_present"] is True
    assert payload["connection_lifecycle"]["status"] == "connected"
    assert payload["connection_lifecycle"]["active"] is True
    assert payload["connection_lifecycle"]["ready_to_execute_action"] is True
    assert payload["execution_gateway"]["status"] == "allowed"
    assert gates["provider_adapter"]["ready"] is True
    assert gates["vault"]["ready"] is True
    assert gates["persistent_storage"]["ready"] is True
    assert gates["audit_ledger"]["ready"] is True
    assert gates["curated_readonly_action"]["ready"] is True
    assert gates["execution_gateway"]["ready"] is True
    assert fake_storage.lists == 1
    assert fake_storage.fetches == 1
    assert fake_storage.expires == 1
    assert "ca_active" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized
    assert "provider-managed://" not in serialized
    assert "private-user@example.test" not in serialized
    assert "acct_private" not in serialized
    assert "access_token" not in serialized
    assert "api_key" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_activation_readiness_requires_selected_connection(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        fetches = 0

        def status(self, *, probe_database: bool = True):
            assert probe_database is True
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def get_connection_record(self, **kwargs):
            self.fetches += 1
            raise AssertionError("readiness must not select latest connection")

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
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
        response = await client.get(
            "/wiii-connect/providers/gmail/activation-readiness",
            params={"action_slug": "GMAIL_FETCH_EMAILS"},
        )

    assert response.status_code == 200
    payload = response.json()
    gates = {gate["key"]: gate for gate in payload["gates"]}
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["status"] == "blocked"
    assert payload["ready_to_connect"] is True
    assert payload["ready_to_execute_readonly"] is False
    assert payload["connection"]["present"] is False
    assert payload["connection_lifecycle"]["status"] == "disconnected"
    assert payload["connection_lifecycle"]["ready_to_connect"] is True
    assert "complete_provider_oauth" in payload["connection_lifecycle"]["required_next"]
    assert payload["execution_gateway"]["reason"] == "connection_selection_required"
    assert (
        "select_provider_connection" in payload["execution_gateway"]["required_next"]
    )
    assert gates["local_connection"]["reason"] == "connection_missing"
    assert gates["execution_gateway"]["reason"] == "connection_selection_required"
    assert fake_storage.fetches == 0
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized


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
async def test_wiii_connect_connections_api_returns_stored_rows_when_provider_disabled(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import WiiiConnectConnectionRecordV1
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        def status(self, *, probe_database: bool = True):
            assert probe_database is True
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "facebook"
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="facebook",
                    state="connected",
                    reason="stored_connection",
                ),
            )

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(enabled=False),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fail_list_connections(**kwargs):
        raise AssertionError("disabled provider must not call provider network")

    monkeypatch.setattr(
        wiii_connect_api,
        "list_composio_connected_accounts",
        fail_list_connections,
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
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_disabled"
    assert payload["connection_count"] == 1
    assert payload["connections"][0]["connection_ref"].startswith("wcn_")
    assert payload["connections"][0]["state"] == "connected"
    assert payload["connections"][0]["connection_lifecycle"]["status"] == "connected"
    assert payload["connection_lifecycle"]["status"] == "connected"
    assert payload["connection_lifecycle"]["reason"] == "provider_disabled"
    assert payload["storage"]["reason"] == "ready"
    assert "ca_active" not in serialized
    assert "connection_id" not in serialized


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

        def get_connection_record(self, **kwargs):
            return None

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
    assert payload["connections"][0]["connection_ref"].startswith("wcn_")
    assert payload["connections"][0]["state"] == "connected"
    assert payload["connections"][0]["connection_lifecycle"]["status"] == "connected"
    assert payload["connection_lifecycle"]["status"] == "connected"
    assert payload["connection_lifecycle"]["connection_present"] is True
    assert fake_storage.upserts == 1
    assert "ca_active" not in serialized
    assert "connection_id" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_connections_api_does_not_reanimate_user_disconnect(
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

        def get_connection_record(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
            connection_id: str | None = None,
        ):
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            assert connection_id == "ca_active"
            return WiiiConnectConnectionRecordV1(
                connection_id="ca_active",
                provider_slug="gmail",
                state="disabled",
                reason="user_disconnect_requested",
            )

        def upsert_connection_record(self, *args, **kwargs):
            self.upserts += 1
            raise AssertionError("poll must not re-enable user-disconnected row")

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_list_connections(**kwargs):
        return WiiiConnectComposioConnectionListResult(
            ready=True,
            reason="ready",
            connections=(
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="gmail",
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
            "/wiii-connect/providers/gmail/connections",
            params={"probe_database": "true"},
        )

    assert response.status_code == 200
    assert fake_storage.upserts == 0


@pytest.mark.asyncio
async def test_wiii_connect_disconnect_api_requires_auth(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.delete(
            "/wiii-connect/providers/gmail/connections/wcn_public_ref",
        )

    assert response.status_code == 401


def test_wiii_connect_openapi_names_disconnect_path_connection_ref(app):
    schema = app.openapi()
    paths = schema["paths"]

    assert "/wiii-connect/providers/{slug}/connections/{connection_ref}" in paths
    assert "/wiii-connect/providers/{slug}/connections/{connection_id}" not in paths


@pytest.mark.asyncio
async def test_wiii_connect_disconnect_api_disables_local_before_provider_delete(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioDisconnectResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        fetches = 0
        lists = 0
        upserts = 0

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
            assert provider_slug == "gmail"
            assert connection_id == "ca_active"
            return WiiiConnectConnectionRecordV1(
                connection_id="ca_active",
                provider_slug="gmail",
                state="connected",
                scopes=WiiiConnectScopeGrant(read=True),
                reason="provider_connection_list",
            )

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            return (
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="gmail",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True),
                ),
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
            assert connection.state == "disabled"
            assert connection.scopes.enabled_scopes() == ()
            assert "disconnected_by_user" in connection.warnings
            return True

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert "secret-api-key" not in serialized
            assert "authcfg_gmail" not in serialized
            assert "access_token" not in serialized
            assert "ca_active" not in serialized
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_disconnect(**kwargs):
        assert fake_storage.upserts == 1
        assert kwargs["provider_slug"] == "gmail"
        assert kwargs["connected_account_id"] == "ca_active"
        return WiiiConnectComposioDisconnectResult(
            ready=True,
            provider_slug="gmail",
            reason="ready",
            status_code=200,
            connection_ref_present=True,
            provider_success=True,
        )

    monkeypatch.setattr(
        wiii_connect_api,
        "disconnect_composio_connected_account",
        fake_disconnect,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.request(
            "DELETE",
            "/wiii-connect/providers/gmail/connections/"
            f"{public_connection_ref('gmail', 'ca_active')}",
            json={"surface": "desktop"},
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_disconnect.v1"
    assert payload["status"] == "succeeded"
    assert payload["reason"] == "ready"
    assert payload["connection_present"] is True
    assert payload["local_disabled"] is True
    assert payload["provider"]["provider_success"] is True
    assert fake_storage.lists == 1
    assert fake_storage.fetches == 1
    assert fake_storage.upserts == 1
    assert fake_storage.audit_appends == 2
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_actions_api_lists_curated_catalog_without_secrets(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/gmail/actions")

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_action_catalog.v1"
    assert payload["provider_slug"] == "gmail"
    assert payload["action_count"] == 1
    assert payload["enabled_action_count"] == 0
    assert payload["actions"][0]["slug"] == "GMAIL_FETCH_EMAILS"
    assert payload["actions"][0]["enabled"] is False
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_actions_api_hides_backend_owned_argument_keys(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/facebook/actions")

    assert response.status_code == 200
    payload = response.json()
    by_slug = {action["slug"]: action for action in payload["actions"]}
    post = by_slug["FACEBOOK_CREATE_POST"]
    serialized = json.dumps(post, sort_keys=True)

    assert post["argument_keys"] == ["message", "link"]
    assert post["model_argument_keys"] == ["message", "link"]
    assert post["hidden_argument_count"] == 3
    assert "page_id" not in serialized
    assert "published" not in serialized
    assert "scheduled_publish_time" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_effective_actions_api_requires_selected_connection(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        fetches = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def get_connection_record(self, **kwargs):
            self.fetches += 1
            raise AssertionError("inventory must not select a connection without a ref")

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
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
        response = await client.get("/wiii-connect/providers/gmail/effective-actions")

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["version"] == "wiii_connect_action_inventory.v1"
    assert payload["status"] == "blocked"
    assert payload["reason"] == "connection_selection_required"
    assert payload["selected_connection_required"] is True
    assert payload["runtime_enabled_action_count"] == 1
    assert payload["visible_action_count"] == 0
    assert payload["actions"][0]["slug"] == "GMAIL_FETCH_EMAILS"
    assert payload["actions"][0]["runtime_enabled"] is True
    assert payload["actions"][0]["visible_to_agent"] is False
    assert payload["actions"][0]["gateway"]["reason"] == "connection_selection_required"
    assert fake_storage.fetches == 0
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_effective_actions_api_projects_ready_read_action(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    connection_ref = public_connection_ref("gmail", "ca_private")

    class FakeStorage:
        fetches = 0
        lists = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def expire_stale_pending_connections(self, **kwargs):
            return 0

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            return [
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_private",
                    provider_slug="gmail",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True),
                    vault_ref=WiiiConnectVaultSecretRef(
                        provider_slug="gmail",
                        connection_id="ca_private",
                        vault_key_id="provider-managed://composio/ca_private",
                    ),
                    account_label="private-user@example.test",
                    external_account_ref="acct_private",
                    reason="provider_connection_list",
                ),
            ]

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
            assert provider_slug == "gmail"
            assert connection_id == "ca_private"
            return self.list_connection_records(
                organization_id=organization_id,
                user_id=user_id,
                provider_slug=provider_slug,
            )[0]

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
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
        response = await client.get(
            "/wiii-connect/providers/gmail/effective-actions",
            params={"connection_ref": connection_ref},
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "ready"
    assert payload["reason"] == "ready"
    assert payload["connection_ref_present"] is True
    assert payload["connection_present"] is True
    assert payload["visible_action_count"] == 1
    assert payload["executable_action_count"] == 1
    assert payload["actions"][0]["gateway"]["status"] == "allowed"
    assert payload["actions"][0]["executable_now"] is True
    assert fake_storage.fetches == 1
    assert fake_storage.lists >= 1
    assert "ca_private" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized
    assert "provider-managed://" not in serialized
    assert "private-user@example.test" not in serialized
    assert "acct_private" not in serialized


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
        public_connection_ref,
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
        lists = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "facebook"
            return [
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="facebook",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True, write=True),
                    reason="provider_connection_list",
                ),
            ]

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
            assert metadata["request"]["request_id"] == "req-wiii-connect-api-1"
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
            headers={"X-Request-ID": "req-wiii-connect-api-1"},
            json={
                "surface": "desktop",
                "connection_ref": public_connection_ref("facebook", "ca_active"),
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
    assert fake_storage.lists == 1
    assert fake_storage.fetches == 1
    assert fake_storage.audit_appends == 1
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "secret-value" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_execution_decision_requires_selected_connection(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        fetches = 0
        lists = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def get_connection_record(self, **kwargs):
            self.fetches += 1
            raise AssertionError(
                "execution preflight must not select latest connection",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["connection_id_present"] is False
            assert metadata["connection_found"] is False
            assert metadata["request"]["action_slug"] == "GMAIL_FETCH_EMAILS"
            assert "secret-api-key" not in serialized
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
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
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
            "/wiii-connect/providers/gmail/execution-decision",
            json={
                "surface": "desktop",
                "connection_id": "ca_active",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "path": "external_app_action",
                "mutation": "read",
                "argument_keys": ["query", "access_token"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "connection_selection_required"
    assert payload["connection_present"] is False
    assert "select_provider_connection" in payload["required_next"]
    assert fake_storage.fetches == 0
    assert fake_storage.audit_appends == 1
    assert "ca_active" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized
    assert "access_token" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_execute_api_runs_readonly_composio_action_safely(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        fetches = 0
        lists = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            return [
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="gmail",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True),
                    reason="provider_connection_list",
                ),
            ]

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
            assert provider_slug == "gmail"
            assert connection_id == "ca_active"
            return WiiiConnectConnectionRecordV1(
                connection_id="ca_active",
                provider_slug="gmail",
                state="connected",
                scopes=WiiiConnectScopeGrant(read=True),
                reason="provider_connection_list",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["request"]["action_slug"] == "GMAIL_FETCH_EMAILS"
            assert metadata["request"]["request_id"] == "req-wiii-connect-execute-1"
            assert "access_token" not in serialized
            assert "client-secret" not in serialized
            assert "private subject" not in serialized
            assert "secret-api-key" not in serialized
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
        ),
    )
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_schema(**kwargs):
        assert kwargs["provider_slug"] == "gmail"
        assert kwargs["action_slug"] == "GMAIL_FETCH_EMAILS"
        assert kwargs["request_id"] == "req-wiii-connect-execute-1"
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug="gmail",
            action_slug="GMAIL_FETCH_EMAILS",
            reason="ready",
            request_id=kwargs["request_id"],
            schema_present=True,
            argument_keys=("query",),
        )

    async def fake_execute(**kwargs):
        assert kwargs["provider_slug"] == "gmail"
        assert kwargs["action_slug"] == "GMAIL_FETCH_EMAILS"
        assert kwargs["connected_account_id"] == "ca_active"
        assert kwargs["request_id"] == "req-wiii-connect-execute-1"
        assert kwargs["arguments"] == {"query": "from:me"}
        return WiiiConnectComposioExecuteResult(
            ready=True,
            provider_slug="gmail",
            action_slug="GMAIL_FETCH_EMAILS",
            reason="ready",
            request_id=kwargs["request_id"],
            successful=True,
            status_code=200,
            data_keys=("messages",),
            log_id_present=True,
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/gmail/execute",
            headers={"X-Request-ID": "req-wiii-connect-execute-1"},
            json={
                "surface": "desktop",
                "connection_ref": public_connection_ref("gmail", "ca_active"),
                "action_slug": "GMAIL_FETCH_EMAILS",
                "path": "external_app_action",
                "mutation": "read",
                "arguments": {
                    "query": "from:me",
                    "access_token": "client-secret",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "succeeded"
    assert payload["reason"] == "ready"
    assert payload["decision"]["outcome"] == "allowed"
    assert payload["schema"]["status"] == "ready"
    assert payload["execution"]["status"] == "succeeded"
    assert payload["execution"]["log_id_present"] is True
    assert payload["argument_policy"]["accepted_argument_keys"] == ["query"]
    assert payload["argument_policy"]["hidden_argument_count"] == 1
    assert payload["operation_policy"]["status"] == "not_required"
    assert fake_storage.lists == 1
    assert fake_storage.fetches == 0
    assert fake_storage.audit_appends == 2
    assert "client-secret" not in serialized
    assert "access_token" not in serialized
    assert "private subject" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_execute_api_ignores_unverified_mutation_authorization(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        lists = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "facebook"
            return [
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_facebook",
                    provider_slug="facebook",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(
                        read=True,
                        preview=True,
                        apply=True,
                    ),
                    reason="provider_connection_list",
                ),
            ]

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["operation_policy"]["status"] == "required"
            assert metadata["operation_policy"]["caller_claim_ignored"] is True
            assert "approval-token" not in serialized
            assert "page_private" not in serialized
            assert "secret-api-key" not in serialized
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
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
            },
            apply_execute_enabled=True,
            apply_action_allowlist_by_provider={
                "facebook": ("FACEBOOK_CREATE_POST",),
            },
        ),
    )
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_schema(**kwargs):
        raise AssertionError("schema probe must not run without verified authorization")

    async def fake_execute(**kwargs):
        raise AssertionError("provider execution must not run without verified authorization")

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/execute",
            json={
                "surface": "desktop",
                "connection_ref": public_connection_ref("facebook", "ca_facebook"),
                "action_slug": "FACEBOOK_CREATE_POST",
                "path": "external_app_action",
                "mutation": "apply",
                "preview_evidence_required": True,
                "preview_evidence_id": "preview_injected",
                "approval_token_present": True,
                "arguments": {
                    "page_id": "page_private",
                    "message": "safe public copy",
                    "published": True,
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "missing_preview_evidence"
    assert payload["operation_policy"]["status"] == "required"
    assert payload["operation_policy"]["caller_claim_ignored"] is True
    assert payload["argument_policy"]["accepted_argument_keys"] == ["message"]
    assert payload["argument_policy"]["hidden_argument_count"] == 2
    assert payload["schema"] is None
    assert payload["execution"] is None
    assert fake_storage.lists == 1
    assert fake_storage.audit_appends == 1
    assert "preview_injected" not in serialized
    assert "approval-token" not in serialized
    assert "page_private" not in serialized
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_execute_blocks_missing_required_schema_arguments(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect import backend_action_executor as executor_module
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioToolSchemaResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )

    class FakeStorage:
        audit_appends = 0
        fetches = 0
        lists = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                reason="ready",
            )

        def list_connection_records(
            self,
            *,
            organization_id: str,
            user_id: str,
            provider_slug: str,
        ):
            self.lists += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert provider_slug == "gmail"
            return [
                WiiiConnectConnectionRecordV1(
                    connection_id="ca_active",
                    provider_slug="gmail",
                    state="connected",
                    scopes=WiiiConnectScopeGrant(read=True),
                    reason="provider_connection_list",
                ),
            ]

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
            assert provider_slug == "gmail"
            assert connection_id == "ca_active"
            return WiiiConnectConnectionRecordV1(
                connection_id="ca_active",
                provider_slug="gmail",
                state="connected",
                scopes=WiiiConnectScopeGrant(read=True),
                reason="provider_connection_list",
            )

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["stage"] == "argument_validation"
            assert metadata["missing_argument_keys"] == [
                "query",
                "redacted_sensitive_field",
            ]
            assert metadata["request"]["action_slug"] == "GMAIL_FETCH_EMAILS"
            assert "client-secret" not in serialized
            assert "private subject" not in serialized
            assert "access_token" not in serialized
            assert "api_key" not in serialized
            return True

    fake_storage = FakeStorage()
    monkeypatch.setattr(
        wiii_connect_api,
        "build_composio_adapter_config",
        lambda: WiiiConnectComposioAdapterConfig(
            enabled=True,
            api_key="secret-api-key",
            api_key_present=True,
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
        ),
    )
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_schema(**kwargs):
        assert kwargs["provider_slug"] == "gmail"
        assert kwargs["action_slug"] == "GMAIL_FETCH_EMAILS"
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug="gmail",
            action_slug="GMAIL_FETCH_EMAILS",
            reason="ready",
            schema_present=True,
            argument_keys=("query",),
            required_argument_keys=("query", "access_token"),
        )

    async def fake_execute(**kwargs):
        raise AssertionError(
            "provider execution must not run with missing required arguments",
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/gmail/execute",
            json={
                "surface": "desktop",
                "connection_ref": public_connection_ref("gmail", "ca_active"),
                "action_slug": "GMAIL_FETCH_EMAILS",
                "path": "external_app_action",
                "mutation": "read",
                "arguments": {
                    "api_key": "client-secret",
                    "subject": "private subject",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "missing_required_arguments"
    assert payload["decision"]["outcome"] == "allowed"
    assert payload["schema"]["status"] == "ready"
    assert payload["execution"] is None
    assert payload["missing_argument_keys"] == ["query", "redacted_sensitive_field"]
    assert fake_storage.lists == 1
    assert fake_storage.fetches == 0
    assert fake_storage.audit_appends == 1
    assert "client-secret" not in serialized
    assert "private subject" not in serialized
    assert "access_token" not in serialized
    assert "api_key" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_gmail" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_execute_requires_selected_connection_before_provider_call(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect import backend_action_executor as executor_module
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

        def get_connection_record(self, **kwargs):
            self.fetches += 1
            raise AssertionError("execute must not select latest connection")

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            metadata = record.to_public_metadata()["metadata"]
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert metadata["stage"] == "api_execute"
            assert metadata["connection_ref_present"] is False
            assert metadata["connection_found"] is False
            assert metadata["request"]["action_slug"] == "GMAIL_FETCH_EMAILS"
            assert "client-secret" not in serialized
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
            auth_config_by_provider={"gmail": "authcfg_gmail"},
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "gmail": ("GMAIL_FETCH_EMAILS",),
            },
        ),
    )
    monkeypatch.setattr(
        executor_module,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_schema(**kwargs):
        raise AssertionError("schema probe must not run without selected connection")

    async def fake_execute(**kwargs):
        raise AssertionError(
            "provider execution must not run without selected connection",
        )

    monkeypatch.setattr(executor_module, "verify_composio_tool_schema", fake_schema)
    monkeypatch.setattr(executor_module, "execute_composio_tool", fake_execute)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/gmail/execute",
            json={
                "surface": "desktop",
                "connection_id": "ca_active",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "path": "external_app_action",
                "mutation": "read",
                "arguments": {
                    "query": "from:me",
                    "access_token": "client-secret",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "connection_selection_required"
    assert payload["connection_present"] is False
    assert payload["schema"] is None
    assert payload["execution"] is None
    assert "select_provider_connection" in payload["required_next"]
    assert fake_storage.fetches == 0
    assert fake_storage.audit_appends == 1
    assert "ca_active" not in serialized
    assert "client-secret" not in serialized
    assert "access_token" not in serialized
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_facebook_post_preview_apply_requires_scope_and_token(
    authenticated_app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.adapter_v1 import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        public_connection_ref,
    )
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )
    from app.engine.wiii_connect.persistent_storage import (
        WiiiConnectPersistentStorageStatus,
    )
    from app.engine.wiii_connect.operation_approval import (
        WiiiConnectOperationApprovalDecision,
    )

    class FakeStorage:
        def __init__(self):
            self.connection = WiiiConnectConnectionRecordV1(
                connection_id="ca_facebook",
                provider_slug="facebook",
                state="connected",
                scopes=WiiiConnectScopeGrant(read=True),
            )
            self.audit_appends = 0
            self.operation_approval_appends = 0
            self.operation_approval_consumes = 0
            self.operation_approvals = {}
            self.upserts = 0

        def status(self, *, probe_database: bool = True):
            return WiiiConnectPersistentStorageStatus(
                enabled=True,
                persistent=True,
                connection_table_ready=True,
                audit_ledger_ready=True,
                operation_approval_table_ready=True,
                reason="ready",
            )

        def expire_stale_pending_connections(self, **kwargs):
            return 0

        def list_connection_records(self, **kwargs):
            return (self.connection,)

        def get_connection_record(self, **kwargs):
            assert kwargs["provider_slug"] == "facebook"
            assert kwargs["connection_id"] == "ca_facebook"
            return self.connection

        def upsert_connection_record(self, connection, **kwargs):
            self.upserts += 1
            self.connection = connection
            return True

        def append_audit_record(self, record, *, organization_id: str, user_id: str):
            self.audit_appends += 1
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert "approval-token" not in serialized
            assert "secret post message" not in serialized
            assert "ca_facebook" not in serialized
            return True

        def append_operation_approval_record(
            self,
            record,
            *,
            organization_id: str,
            user_id: str,
        ):
            self.operation_approval_appends += 1
            serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
            assert organization_id == "org_1"
            assert user_id == "user_1"
            assert "approval-token" not in serialized
            assert "secret post message" not in serialized
            assert "ca_facebook" not in serialized
            assert "123456" not in serialized
            self.operation_approvals[record.preview_evidence_id] = {
                "record": record,
                "consumed": False,
            }
            return True

        def consume_operation_approval_record(
            self,
            *,
            preview_evidence_id: str,
            request_fingerprint: str,
            organization_id: str,
            user_id: str,
            provider_slug: str,
            action_slug: str,
            consumed_at=None,
        ):
            self.operation_approval_consumes += 1
            assert organization_id == "org_1"
            assert user_id == "user_1"
            stored = self.operation_approvals.get(preview_evidence_id)
            if stored is None:
                return WiiiConnectOperationApprovalDecision(
                    status="blocked",
                    reason="approval_record_missing",
                    provider_slug=provider_slug,
                    action_slug=action_slug,
                    preview_evidence_id_present=bool(preview_evidence_id),
                    request_fingerprint_present=bool(request_fingerprint),
                    persistent=True,
                    blocked=True,
                )
            if stored["consumed"]:
                return WiiiConnectOperationApprovalDecision(
                    status="blocked",
                    reason="approval_record_already_consumed",
                    provider_slug=provider_slug,
                    action_slug=action_slug,
                    preview_evidence_id_present=True,
                    request_fingerprint_present=True,
                    persistent=True,
                    blocked=True,
                )
            record = stored["record"]
            if record.request_fingerprint != request_fingerprint:
                return WiiiConnectOperationApprovalDecision(
                    status="blocked",
                    reason="approval_fingerprint_mismatch",
                    provider_slug=provider_slug,
                    action_slug=action_slug,
                    preview_evidence_id_present=True,
                    request_fingerprint_present=True,
                    persistent=True,
                    blocked=True,
                )
            stored["consumed"] = True
            return WiiiConnectOperationApprovalDecision(
                status="consumed",
                reason="approval_consumed",
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id_present=True,
                request_fingerprint_present=True,
                persistent=True,
                consumed=True,
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
            readonly_execute_enabled=True,
            readonly_action_allowlist_by_provider={
                "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
            },
            apply_execute_enabled=True,
            apply_action_allowlist_by_provider={
                "facebook": (
                    "FACEBOOK_CREATE_POST",
                    "FACEBOOK_CREATE_PHOTO_POST",
                ),
            },
        ),
    )
    monkeypatch.setattr(
        wiii_connect_api,
        "get_wiii_connect_persistent_storage",
        lambda: fake_storage,
    )

    async def fake_schema(**kwargs):
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug="facebook",
            action_slug=kwargs["action_slug"],
            reason="ready",
            schema_present=True,
            argument_keys=("page_id", "message", "published"),
            required_argument_keys=("page_id", "message"),
        )

    execute_calls = 0

    async def fake_execute(**kwargs):
        nonlocal execute_calls
        execute_calls += 1
        assert kwargs["provider_slug"] == "facebook"
        assert kwargs["action_slug"] == "FACEBOOK_CREATE_POST"
        assert kwargs["connected_account_id"] == "ca_facebook"
        assert kwargs["arguments"]["page_id"] == "123456"
        assert kwargs["arguments"]["message"] == "secret post message"
        return WiiiConnectComposioExecuteResult(
            ready=True,
            provider_slug="facebook",
            action_slug="FACEBOOK_CREATE_POST",
            reason="ready",
            successful=True,
            status_code=200,
            data_keys=("id",),
        )

    monkeypatch.setattr(wiii_connect_api, "verify_composio_tool_schema", fake_schema)
    monkeypatch.setattr(wiii_connect_api, "execute_composio_tool", fake_execute)

    connection_ref = public_connection_ref("facebook", "ca_facebook")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        blocked_preview = await client.post(
            "/wiii-connect/providers/facebook/facebook-post/preview",
            json={
                "connection_ref": connection_ref,
                "page_id": "123456",
                "message": "secret post message",
            },
        )
        scope_response = await client.post(
            f"/wiii-connect/providers/facebook/connections/{connection_ref}/scope-grant",
            json={"scopes": {"read": True, "preview": True, "apply": True}},
        )
        preview_response = await client.post(
            "/wiii-connect/providers/facebook/facebook-post/preview",
            json={
                "connection_ref": connection_ref,
                "page_id": "123456",
                "message": "secret post message",
            },
        )
        preview_payload = preview_response.json()
        apply_response = await client.post(
            "/wiii-connect/providers/facebook/facebook-post/apply",
            json={
                "connection_ref": connection_ref,
                "page_id": "123456",
                "message": "secret post message",
                "approval_token": preview_payload["approval_token"],
                "preview_evidence_id": preview_payload["preview_evidence_id"],
            },
        )
        replay_response = await client.post(
            "/wiii-connect/providers/facebook/facebook-post/apply",
            json={
                "connection_ref": connection_ref,
                "page_id": "123456",
                "message": "secret post message",
                "approval_token": preview_payload["approval_token"],
                "preview_evidence_id": preview_payload["preview_evidence_id"],
            },
        )

    blocked_payload = blocked_preview.json()
    scope_payload = scope_response.json()
    apply_payload = apply_response.json()
    replay_payload = replay_response.json()
    serialized = json.dumps(
        {
            "scope": scope_payload,
            "preview": preview_payload,
            "apply": apply_payload,
            "replay": replay_payload,
        },
        sort_keys=True,
    )

    assert blocked_payload["status"] == "blocked"
    assert blocked_payload["reason"] == "missing_scope"
    assert scope_payload["status"] == "ready"
    assert scope_payload["connection"]["scopes"]["preview"] is True
    assert scope_payload["connection"]["scopes"]["apply"] is True
    assert preview_payload["status"] == "ready"
    assert preview_payload["preview_evidence_id"].startswith("wcp_")
    assert preview_payload["approval_token"]
    assert preview_payload["approval_ledger"]["status"] == "pending"
    assert preview_payload["approval_ledger"]["persistent"] is True
    assert apply_payload["status"] == "succeeded"
    assert apply_payload["approval_ledger"]["status"] == "consumed"
    assert apply_payload["approval_ledger"]["consumed"] is True
    assert apply_payload["execution"]["status"] == "succeeded"
    assert replay_payload["status"] == "blocked"
    assert replay_payload["reason"] == "approval_record_already_consumed"
    assert replay_payload["approval_ledger"]["blocked"] is True
    assert fake_storage.upserts == 1
    assert fake_storage.audit_appends >= 3
    assert fake_storage.operation_approval_appends == 1
    assert fake_storage.operation_approval_consumes == 2
    assert execute_calls == 1
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "ca_facebook" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_facebook_post_preview_rejects_missing_message(
    authenticated_app,
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/wiii-connect/providers/facebook/facebook-post/preview",
            json={
                "connection_ref": "wcn_placeholder",
                "page_id": "123456",
                "message": "   ",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "validation_failed"
    assert payload["reason"] == "missing_message"


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
async def test_wiii_connect_callback_api_validates_state_before_provider_error(
    app,
    monkeypatch,
):
    from app.api.v1 import wiii_connect as wiii_connect_api
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

        def append_audit_record(self, *args, **kwargs):
            self.audit_appends += 1
            raise AssertionError("invalid state must not append tenant audit")

        def upsert_connection_record(self, *args, **kwargs):
            self.connection_upserts += 1
            raise AssertionError("invalid state must not upsert connection")

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
        missing_state = await client.get(
            "/wiii-connect/providers/facebook/callback",
            params={
                "error": "access_denied",
                "connected_account_id": "ca_secret",
            },
        )
        invalid_state = await client.get(
            "/wiii-connect/providers/facebook/callback",
            params={
                "wiii_state": "tampered-state",
                "error": "access_denied",
                "connected_account_id": "ca_secret",
            },
        )

    missing_payload = missing_state.json()
    invalid_payload = invalid_state.json()
    serialized = json.dumps(
        {
            "missing": missing_payload,
            "invalid": invalid_payload,
        },
        sort_keys=True,
    )

    assert missing_state.status_code == 200
    assert invalid_state.status_code == 200
    assert missing_payload["status"] == "blocked"
    assert missing_payload["reason"] == "missing_state"
    assert invalid_payload["status"] == "blocked"
    assert invalid_payload["reason"] == "invalid_state"
    assert fake_storage.audit_appends == 0
    assert fake_storage.connection_upserts == 0
    assert "access_denied" not in serialized
    assert "tampered-state" not in serialized
    assert "ca_secret" not in serialized
    assert "secret-api-key" not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_callback_api_blocks_valid_state_provider_error(
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
            assert "access_denied" not in serialized
            assert "secret-state-value" not in serialized
            return True

        def upsert_connection_record(self, *args, **kwargs):
            self.connection_upserts += 1
            raise AssertionError("provider error must not upsert connection")

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
                "error": "access_denied",
                "connected_account_id": "ca_secret",
            },
        )

    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)

    assert response.status_code == 200
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_error"
    assert payload["vault_ref_issued"] is False
    assert fake_storage.audit_appends == 1
    assert fake_storage.connection_upserts == 0
    assert "access_denied" not in serialized
    assert "ca_secret" not in serialized
    assert state not in serialized
    assert "secret-api-key" not in serialized


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
    assert payload["connection_ref"] == "pending_connection_ref"
    assert "connection_id" not in serialized
    assert "ca_123" not in serialized
    assert "secret-api-key" not in serialized
    assert "authcfg_fb" not in serialized
    assert "secret-value" not in serialized
    assert state not in serialized


@pytest.mark.asyncio
async def test_wiii_connect_callback_browser_accept_returns_handoff_html(
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
            assert organization_id == "org_1"
            assert user_id == "user_1"
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
            headers={"accept": "text/html,application/xhtml+xml"},
        )

    body = response.text
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Wiii Connect" in body
    assert "Facebook" in body
    assert "Kết nối Facebook đã được ghi nhận" in body
    assert "wiii-connect:callback" in body
    assert fake_storage.audit_appends == 1
    assert fake_storage.connection_upserts == 1
    assert "ca_123" not in body
    assert "connection_id" not in body
    assert "secret-api-key" not in body
    assert "authcfg_fb" not in body
    assert "secret-value" not in body
    assert state not in body


@pytest.mark.asyncio
async def test_wiii_connect_callback_api_404_for_unknown_provider(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/not-real/callback")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown_wiii_connect_provider"
