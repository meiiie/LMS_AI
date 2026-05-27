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
