from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1.wiii_connect import router as wiii_connect_router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(wiii_connect_router)
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
    assert "execution_gateway" in payload["missing_requirements"]


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
async def test_wiii_connect_callback_api_404_for_unknown_provider(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/wiii-connect/providers/not-real/callback")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown_wiii_connect_provider"
