"""Wiii Connect registry and connection-session endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.engine.wiii_connect import (
    WiiiConnectSessionStartRequest,
    begin_connection_session,
    get_wiii_connect_provider_entry,
    provider_connection_status,
    provider_registry_public_metadata,
    scope_grant_from_mapping,
)


router = APIRouter(prefix="/wiii-connect", tags=["wiii-connect"])


class WiiiConnectStartSessionBody(BaseModel):
    """Safe request body for a provider authorization attempt."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"
    redirect_uri: str | None = None
    requested_scopes: dict[str, bool] = Field(default_factory=dict)
    request_metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/providers")
async def list_wiii_connect_providers() -> dict[str, object]:
    """Return the privacy-safe Wiii Connect provider catalog."""

    return provider_registry_public_metadata()


@router.get("/providers/{slug}/status")
async def get_wiii_connect_provider_connection_status(slug: str) -> dict[str, object]:
    """Return fail-closed provider authorization readiness."""

    status = provider_connection_status(slug)
    if status is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    return status.to_public_metadata()


@router.post("/providers/{slug}/sessions")
async def start_wiii_connect_provider_session(
    slug: str,
    body: WiiiConnectStartSessionBody | None = None,
) -> dict[str, object]:
    """Return the session-start decision for a provider.

    This endpoint does not call Composio or any OAuth provider yet. It only
    exposes the backend control-plane decision that the frontend can render.
    """

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    body = body or WiiiConnectStartSessionBody()
    request = WiiiConnectSessionStartRequest(
        provider_slug=entry.slug,
        surface=body.surface,
        requested_scopes=scope_grant_from_mapping(body.requested_scopes),
        redirect_uri_present=bool(body.redirect_uri),
        request_metadata_keys=tuple(body.request_metadata.keys()),
    )
    decision = begin_connection_session(entry, request)
    return decision.to_public_metadata()
