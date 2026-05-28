"""Wiii Connect registry and connection-session endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.security import require_auth
from app.core.security_models import AuthenticatedUser
from app.engine.wiii_connect import (
    WiiiConnectAuthorizationUrlRequest,
    WiiiConnectCallbackRequest,
    WiiiConnectConnectionRecordV1,
    WiiiConnectSessionStartRequest,
    WiiiConnectVaultSecretRef,
    append_wiii_connect_callback_state,
    audit_ledger_status_public_metadata,
    build_audit_ledger_record,
    build_composio_adapter_config,
    build_composio_connect_enabled_entry,
    build_composio_external_user_id,
    build_composio_provider_managed_vault_capability,
    build_composio_provider_adapter_capability,
    build_wiii_connect_callback_state,
    begin_connection_session,
    create_composio_connect_link,
    decide_authorization_url,
    default_persistent_storage_status_metadata,
    get_wiii_connect_provider_entry,
    get_wiii_connect_persistent_storage,
    normalize_connection_state,
    provider_adapter_status_public_metadata,
    provider_callback_decision,
    provider_callback_decision_for_entry,
    provider_connection_status,
    provider_registry_public_metadata,
    scope_grant_from_mapping,
    verify_wiii_connect_callback_state,
    vault_status_public_metadata,
)


router = APIRouter(prefix="/wiii-connect", tags=["wiii-connect"])


class WiiiConnectStartSessionBody(BaseModel):
    """Safe request body for a provider authorization attempt."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"
    redirect_uri: str | None = None
    state_present: bool = False
    probe_database: bool = False
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
async def get_wiii_connect_audit_ledger_status(
    probe_database: bool = False,
) -> dict[str, object]:
    """Return privacy-safe Wiii Connect audit ledger readiness metadata."""

    storage = _wiii_connect_storage_status_metadata(probe_database=probe_database)
    persistent = bool(storage.get("persistent") and storage.get("audit_ledger_ready"))
    metadata = audit_ledger_status_public_metadata(
        persistent=persistent,
        backend=str(storage.get("backend") or "memory_contract")
        if probe_database
        else "memory_contract",
    )
    metadata["storage"] = storage
    return metadata


@router.get("/storage/status")
async def get_wiii_connect_storage_status(
    probe_database: bool = False,
) -> dict[str, object]:
    """Return Wiii Connect durable storage status.

    Database probing is opt-in so normal UI renders do not block on local or
    production database connectivity checks.
    """

    return _wiii_connect_storage_status_metadata(probe_database=probe_database)


@router.get("/provider-adapters/status")
async def get_wiii_connect_provider_adapter_status() -> dict[str, object]:
    """Return privacy-safe Wiii Connect provider adapter readiness metadata."""

    return provider_adapter_status_public_metadata(
        adapter_capabilities=(build_composio_provider_adapter_capability(),),
    )


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
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Return the provider adapter decision before exposing a connect URL."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    body = body or WiiiConnectStartSessionBody()
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_connect_enabled_entry(entry, composio_config)
    redirect_uri = _safe_redirect_uri(body.redirect_uri)
    callback_state = build_wiii_connect_callback_state(
        provider_slug=effective_entry.slug,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        secret_key=settings.session_secret_key,
    )
    callback_url = append_wiii_connect_callback_state(
        redirect_uri,
        callback_state,
    )
    request = WiiiConnectAuthorizationUrlRequest(
        provider_slug=effective_entry.slug,
        surface=body.surface,
        requested_scopes=scope_grant_from_mapping(body.requested_scopes),
        state_present=bool(callback_state),
        redirect_uri_present=bool(callback_url),
        request_metadata_keys=tuple(body.request_metadata.keys()),
    )
    storage = _wiii_connect_storage_status_metadata(
        probe_database=body.probe_database,
    )
    audit_ledger_metadata = {
        "persistent": bool(
            storage.get("persistent") and storage.get("audit_ledger_ready")
        )
    }
    adapter_capability = build_composio_provider_adapter_capability(composio_config)
    vault_capability = build_composio_provider_managed_vault_capability(
        composio_config,
    )
    preflight = decide_authorization_url(
        effective_entry,
        request,
        adapter_capability=adapter_capability,
        vault_capability=vault_capability,
        audit_ledger_metadata=audit_ledger_metadata,
        authorization_url="wiii-connect://preflight",
    )
    if not preflight.ready:
        _append_authorization_audit(
            preflight,
            storage,
            current_user=current_user,
            metadata={"stage": "preflight"},
        )
        return preflight.to_public_metadata()

    link = await create_composio_connect_link(
        config=composio_config,
        provider_slug=effective_entry.slug,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
        callback_url=callback_url,
    )
    decision = decide_authorization_url(
        effective_entry,
        request,
        adapter_capability=adapter_capability,
        vault_capability=vault_capability,
        audit_ledger_metadata=audit_ledger_metadata,
        authorization_url=link.redirect_url if link.ready else "",
    )
    _append_authorization_audit(
        decision,
        storage,
        current_user=current_user,
        metadata={
            "stage": "connect_link",
            "connect_link": link.to_audit_metadata(),
        },
    )
    if decision.ready:
        _upsert_authorizing_connection(
            link,
            effective_entry,
            request,
            current_user=current_user,
            storage_metadata=storage,
        )
    return decision.to_public_metadata()


@router.get("/providers/{slug}/callback")
async def receive_wiii_connect_provider_callback(
    slug: str,
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    connected_account_id: str | None = None,
    status: str | None = None,
    surface: str = "desktop",
) -> dict[str, object]:
    """Return a fail-closed callback decision without exchanging credentials."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_connect_enabled_entry(entry, composio_config)
    callback_state = state or request.query_params.get("wiii_state")
    state_claims = verify_wiii_connect_callback_state(
        callback_state,
        provider_slug=effective_entry.slug,
        secret_key=settings.session_secret_key,
    )
    provider_connection_id = _safe_provider_connection_id(
        connected_account_id
        or request.query_params.get("connection_id")
        or request.query_params.get("connectedAccountId")
        or request.query_params.get("id")
    )
    callback_request = WiiiConnectCallbackRequest(
        provider_slug=effective_entry.slug,
        surface=surface,
        state_present=bool(callback_state),
        code_present=bool(code),
        connection_ref_present=bool(provider_connection_id),
        error_present=bool(error),
        state_valid=state_claims.valid,
        request_metadata_keys=tuple(request.query_params.keys()),
    )
    adapter_capability = build_composio_provider_adapter_capability(composio_config)
    vault_capability = build_composio_provider_managed_vault_capability(
        composio_config,
    )
    decision = provider_callback_decision_for_entry(
        effective_entry,
        callback_request,
        vault_capability=vault_capability,
        provider_adapter_bound=adapter_capability.bound,
    )
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    _append_callback_audit(
        decision,
        storage,
        state_claims=state_claims,
        metadata={
            "state": state_claims.to_audit_metadata(),
            "provider_status_present": bool(status),
            "provider_connection_ref_present": bool(provider_connection_id),
        },
    )
    if decision.accepted:
        _upsert_callback_connection(
            provider_connection_id=provider_connection_id,
            provider_status=status,
            entry=effective_entry,
            request=callback_request,
            state_claims=state_claims,
            storage_metadata=storage,
        )
    return decision.to_public_metadata()


def _wiii_connect_storage_status_metadata(
    *,
    probe_database: bool,
) -> dict[str, Any]:
    if not probe_database:
        return default_persistent_storage_status_metadata()
    return (
        get_wiii_connect_persistent_storage()
        .status(probe_database=True)
        .to_public_metadata()
    )


def _append_authorization_audit(
    decision: Any,
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    metadata: dict[str, Any],
) -> None:
    if not bool(storage_metadata.get("persistent") and storage_metadata.get("audit_ledger_ready")):
        return
    record = build_audit_ledger_record(
        event_kind="provider",
        provider_slug=decision.provider_slug,
        status=decision.status,
        reason=decision.reason,
        surface=decision.audit_event.request.surface if decision.audit_event else "backend",
        metadata={
            "request": (
                decision.audit_event.request.to_audit_metadata()
                if decision.audit_event
                else {}
            ),
            **metadata,
        },
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
    )


def _append_callback_audit(
    decision: Any,
    storage_metadata: dict[str, Any],
    *,
    state_claims: Any,
    metadata: dict[str, Any],
) -> None:
    if (
        not state_claims.valid
        or not bool(
            storage_metadata.get("persistent")
            and storage_metadata.get("audit_ledger_ready")
        )
    ):
        return
    record = build_audit_ledger_record(
        event_kind="callback",
        provider_slug=decision.provider_slug,
        status=decision.status,
        reason=decision.reason,
        surface=decision.audit_event.request.surface if decision.audit_event else "backend",
        metadata={
            "request": (
                decision.audit_event.request.to_audit_metadata()
                if decision.audit_event
                else {}
            ),
            **metadata,
        },
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=state_claims.organization_id,
        user_id=state_claims.user_id,
    )


def _upsert_authorizing_connection(
    link: Any,
    entry: Any,
    request: WiiiConnectAuthorizationUrlRequest,
    *,
    current_user: AuthenticatedUser,
    storage_metadata: dict[str, Any],
) -> None:
    connection_id = _safe_provider_connection_id(
        getattr(link, "connected_account_id", ""),
    )
    if not connection_id or not _connection_storage_ready(storage_metadata):
        return
    connection = WiiiConnectConnectionRecordV1(
        connection_id=connection_id,
        provider_slug=entry.slug,
        state="authorizing",
        scopes=request.requested_scopes,
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug=entry.slug,
            connection_id=connection_id,
            vault_key_id=f"provider-managed://composio/{connection_id}",
            secret_version="provider_managed",
        ),
        reason="connect_link_issued",
        warnings=("awaiting_provider_callback_or_poll",),
    )
    get_wiii_connect_persistent_storage().upsert_connection_record(
        connection,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_kind=entry.provider_kind,
    )


def _upsert_callback_connection(
    *,
    provider_connection_id: str,
    provider_status: str | None,
    entry: Any,
    request: WiiiConnectCallbackRequest,
    state_claims: Any,
    storage_metadata: dict[str, Any],
) -> None:
    if not provider_connection_id or not _connection_storage_ready(storage_metadata):
        return
    provider_state = provider_status or "PENDING"
    connection = WiiiConnectConnectionRecordV1(
        connection_id=provider_connection_id,
        provider_slug=entry.slug,
        state=normalize_connection_state(provider_state),
        scopes=scope_grant_from_mapping({"read": True}),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug=entry.slug,
            connection_id=provider_connection_id,
            vault_key_id=f"provider-managed://composio/{provider_connection_id}",
            secret_version="provider_managed",
        ),
        reason=f"callback_{request.surface}",
        warnings=()
        if normalize_connection_state(provider_state) == "connected"
        else ("awaiting_connection_poll",),
    )
    get_wiii_connect_persistent_storage().upsert_connection_record(
        connection,
        organization_id=state_claims.organization_id,
        user_id=state_claims.user_id,
        provider_kind=entry.provider_kind,
    )


def _connection_storage_ready(storage_metadata: dict[str, Any]) -> bool:
    return bool(
        storage_metadata.get("persistent")
        and storage_metadata.get("connection_table_ready")
        and storage_metadata.get("audit_ledger_ready")
    )


def _wiii_connect_owner_organization_id(user: AuthenticatedUser) -> str:
    if user.organization_id:
        return user.organization_id
    return build_composio_external_user_id(
        organization_id=None,
        user_id=user.user_id,
    )


def _safe_redirect_uri(value: str | None) -> str:
    text = str(value or "").strip()
    if text.startswith(("https://", "http://")):
        return text
    return ""


def _safe_provider_connection_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(marker in text.lower() for marker in ("token", "secret", "password")):
        return ""
    return text[:160]
