"""Wiii Connect registry and connection-session endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.engine.wiii_connect import (
    WiiiConnectAuthorizationUrlRequest,
    WiiiConnectCallbackRequest,
    WiiiConnectSessionStartRequest,
    audit_ledger_status_public_metadata,
    begin_connection_session,
    decide_authorization_url,
    get_wiii_connect_provider_entry,
    provider_adapter_status_public_metadata,
    provider_callback_decision,
    provider_connection_status,
    provider_registry_public_metadata,
    scope_grant_from_mapping,
    vault_status_public_metadata,
)


router = APIRouter(prefix="/wiii-connect", tags=["wiii-connect"])


class WiiiConnectStartSessionBody(BaseModel):
    """Safe request body for a provider authorization attempt."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"
    redirect_uri: str | None = None
    state_present: bool = False
    requested_scopes: dict[str, bool] = Field(default_factory=dict)
    request_metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/providers")
async def list_wiii_connect_providers() -> dict[str, object]:
    """Return the privacy-safe Wiii Connect provider catalog."""

    return provider_registry_public_metadata()


@router.get("/vault/status")
async def get_wiii_connect_vault_status() -> dict[str, object]:
    """Return privacy-safe Wiii Connect vault readiness metadata."""

    return vault_status_public_metadata()


@router.get("/audit-ledger/status")
async def get_wiii_connect_audit_ledger_status() -> dict[str, object]:
    """Return privacy-safe Wiii Connect audit ledger readiness metadata."""

    return audit_ledger_status_public_metadata()


@router.get("/provider-adapters/status")
async def get_wiii_connect_provider_adapter_status() -> dict[str, object]:
    """Return privacy-safe Wiii Connect provider adapter readiness metadata."""

    return provider_adapter_status_public_metadata()


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


@router.post("/providers/{slug}/authorization-url")
async def create_wiii_connect_provider_authorization_url(
    slug: str,
    body: WiiiConnectStartSessionBody | None = None,
) -> dict[str, object]:
    """Return the provider adapter decision before exposing a connect URL."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    body = body or WiiiConnectStartSessionBody()
    request = WiiiConnectAuthorizationUrlRequest(
        provider_slug=entry.slug,
        surface=body.surface,
        requested_scopes=scope_grant_from_mapping(body.requested_scopes),
        state_present=body.state_present,
        redirect_uri_present=bool(body.redirect_uri),
        request_metadata_keys=tuple(body.request_metadata.keys()),
    )
    decision = decide_authorization_url(entry, request)
    return decision.to_public_metadata()


@router.get("/providers/{slug}/callback")
async def receive_wiii_connect_provider_callback(
    slug: str,
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    surface: str = "desktop",
) -> dict[str, object]:
    """Return a fail-closed callback decision without exchanging credentials."""

    callback_request = WiiiConnectCallbackRequest(
        provider_slug=slug.strip().lower().replace("-", "_"),
        surface=surface,
        state_present=bool(state),
        code_present=bool(code),
        error_present=bool(error),
        request_metadata_keys=tuple(request.query_params.keys()),
    )
    decision = provider_callback_decision(slug, callback_request)
    if decision is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    return decision.to_public_metadata()
