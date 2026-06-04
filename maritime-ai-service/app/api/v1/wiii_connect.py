"""Wiii Connect registry and connection-session endpoints."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import replace
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.security import optional_auth, require_auth
from app.core.security_models import AuthenticatedUser
from app.engine.wiii_connect import (
    DEFAULT_STALE_PENDING_CONNECTION_TTL_SECONDS,
    FACEBOOK_POST_APPROVAL_TOKEN_MAX_AGE_SECONDS,
    WiiiConnectAuthorizationUrlRequest,
    WiiiConnectCallbackRequest,
    WiiiConnectConnectionRecordV1,
    WiiiConnectExecutionRequest,
    WiiiConnectBackendActionPlan,
    WiiiConnectOperationApprovalDecision,
    WiiiConnectSessionStartRequest,
    WiiiConnectScopeGrant,
    WiiiConnectVaultSecretRef,
    action_catalog_public_metadata,
    append_wiii_connect_callback_state,
    audit_ledger_status_public_metadata,
    build_activation_readiness_metadata,
    build_audit_ledger_record,
    build_composio_adapter_config,
    build_composio_connect_enabled_entry,
    build_composio_execution_enabled_entry,
    build_composio_external_user_id,
    build_composio_provider_managed_vault_capability,
    build_composio_provider_adapter_capability,
    build_connection_lifecycle_decision,
    execute_wiii_connect_composio_backend_action,
    build_facebook_post_approval_token,
    build_facebook_post_preview_evidence_id,
    build_wiii_connect_operation_approval_record,
    build_wiii_connect_effective_action_inventory,
    build_wiii_connect_operation_fingerprint,
    build_wiii_connect_snapshot,
    build_wiii_connect_callback_state,
    begin_connection_session,
    connection_ref_matches,
    create_composio_connect_link,
    decide_authorization_url,
    decide_execution_gateway,
    default_persistent_storage_status_metadata,
    disconnect_composio_connected_account,
    get_wiii_connect_provider_entry,
    get_wiii_connect_persistent_storage,
    preflight_wiii_connect_composio_backend_action,
    select_wiii_connect_connection,
    storage_status_metadata,
    unavailable_operation_approval_decision,
    execute_composio_tool,
    facebook_image_sha256,
    get_wiii_connect_curated_action,
    list_wiii_connect_curated_actions,
    list_composio_facebook_pages,
    list_composio_connected_accounts,
    normalize_facebook_image_filename,
    normalize_facebook_image_media_type,
    normalize_facebook_image_url,
    normalize_facebook_page_id,
    normalize_connection_state,
    normalize_facebook_post_message,
    provider_adapter_status_public_metadata,
    provider_callback_decision_for_entry,
    provider_connection_status_for_entry,
    provider_registry_public_metadata,
    resolve_wiii_connect_action_authorization,
    scope_grant_from_mapping,
    scope_policy_for_provider_entry,
    stage_composio_file_upload,
    verify_facebook_post_approval_token,
    verify_composio_tool_schema,
    verify_wiii_connect_callback_state,
    vault_status_public_metadata,
)
from app.engine.wiii_connect.adapter_v1 import ActionMutation
from app.engine.wiii_connect.argument_key_policy import (
    model_visible_arguments,
    safe_public_argument_key,
    safe_public_argument_keys,
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


class WiiiConnectExecutionDecisionBody(BaseModel):
    """Safe request body for an external provider action preflight."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"
    connection_id: str | None = None
    connection_ref: str | None = None
    action_slug: str
    path: str = "external_app_action"
    mutation: str = "read"
    preview_evidence_required: bool = False
    preview_evidence_id: str | None = None
    approval_token_present: bool = False
    argument_keys: list[str] = Field(default_factory=list)


class WiiiConnectExecutionRunBody(WiiiConnectExecutionDecisionBody):
    """Safe request body for a backend-brokered external action call."""

    arguments: dict[str, Any] = Field(default_factory=dict)


class WiiiConnectDisconnectBody(BaseModel):
    """Safe request body for a user-requested connection disconnect."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"


class WiiiConnectConnectionScopeGrantBody(BaseModel):
    """User-approved scope grant for one selected provider account."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"
    scopes: dict[str, bool] = Field(default_factory=dict)


class WiiiConnectFacebookPostPreviewBody(BaseModel):
    """Safe Facebook post preview body."""

    model_config = ConfigDict(extra="ignore")

    surface: str = "desktop"
    connection_ref: str
    page_id: str
    message: str = ""
    image_base64: str | None = None
    image_media_type: str | None = None
    image_filename: str | None = None
    image_url: str | None = None


class WiiiConnectFacebookPostApplyBody(WiiiConnectFacebookPostPreviewBody):
    """Safe Facebook post apply body."""

    approval_token: str
    preview_evidence_id: str


@router.get("/providers")
async def list_wiii_connect_providers() -> dict[str, object]:
    """Return the privacy-safe Wiii Connect provider catalog."""

    return provider_registry_public_metadata()


@router.get("/snapshot")
async def get_wiii_connect_runtime_snapshot(
    query: str = "",
    surface: str | None = None,
    current_user: AuthenticatedUser | None = Depends(optional_auth),
) -> dict[str, object]:
    """Return the privacy-safe runtime connection/path snapshot contract."""

    return build_wiii_connect_snapshot(
        state=_wiii_connect_snapshot_state(current_user),
        query=query,
        surface=surface,
    ).to_metadata()


@router.get("/doctor")
async def get_wiii_connect_runtime_doctor(
    query: str = "",
    surface: str | None = None,
    current_user: AuthenticatedUser | None = Depends(optional_auth),
) -> dict[str, object]:
    """Return a privacy-safe runtime doctor summary derived from the snapshot."""

    snapshot = build_wiii_connect_snapshot(
        state=_wiii_connect_snapshot_state(current_user),
        query=query,
        surface=surface,
    )
    return snapshot.doctor_report().to_metadata()


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

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    status = provider_connection_status_for_entry(
        build_composio_execution_enabled_entry(
            entry,
            build_composio_adapter_config(),
        )
    )
    return status.to_public_metadata()


@router.get("/providers/{slug}/activation-readiness")
async def get_wiii_connect_provider_activation_readiness(
    slug: str,
    connection_id: str | None = None,
    connection_ref: str | None = None,
    action_slug: str = "",
    probe_database: bool = True,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Return one privacy-safe readiness projection for enabling a provider.

    This endpoint performs no provider network calls and does not issue Connect
    Links. It only aggregates local Wiii Connect policy, storage, action, and
    connection readiness for the authenticated org/user boundary.
    """

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")

    composio_config = build_composio_adapter_config()
    connect_entry = build_composio_connect_enabled_entry(entry, composio_config)
    execution_entry = build_composio_execution_enabled_entry(entry, composio_config)
    action = _safe_action_slug(action_slug) or _default_activation_action_slug_for_provider(
        execution_entry.slug,
    )
    adapter_capability = build_composio_provider_adapter_capability(composio_config)
    vault_capability = build_composio_provider_managed_vault_capability(
        composio_config,
    )
    storage = _wiii_connect_storage_status_metadata(
        probe_database=probe_database,
    )
    storage_ready = _connection_storage_ready(storage)
    selected_connection_ref = _safe_public_connection_ref(
        connection_ref or connection_id,
    )
    safe_connection_id = _resolve_provider_connection_id(
        storage,
        current_user=current_user,
        provider_slug=execution_entry.slug,
        connection_ref_or_id=selected_connection_ref,
    )
    _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=execution_entry.slug,
    )
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=execution_entry.slug,
            connection_id=safe_connection_id,
        )
        if storage_ready and safe_connection_id
        else None
    )
    curated_action = get_wiii_connect_curated_action(execution_entry.slug, action)
    runtime_enabled_actions = composio_config.executable_action_slugs_for_provider(
        execution_entry.slug,
    )
    action_runtime_enabled = bool(
        curated_action is not None and curated_action.slug in runtime_enabled_actions
    )
    request = WiiiConnectExecutionRequest(
        provider_slug=execution_entry.slug,
        action_slug=action,
        path=curated_action.path
        if curated_action is not None
        else "external_app_action",
        mutation=curated_action.mutation if curated_action is not None else "read",
        preview_evidence_required=bool(
            curated_action.requires_preview if curated_action is not None else False
        ),
        argument_keys=tuple(
            curated_action.argument_keys if curated_action is not None else ()
        ),
    )
    gateway = decide_execution_gateway(
        execution_entry,
        connection,
        request,
        adapter_capability=adapter_capability,
        audit_ledger_metadata={
            "persistent": bool(
                storage.get("persistent") and storage.get("audit_ledger_ready")
            ),
        },
        connection_selection_required=not bool(selected_connection_ref),
        scope_policy=scope_policy_for_provider_entry(execution_entry),
    )
    return build_activation_readiness_metadata(
        provider_slug=connect_entry.slug,
        connect_entry=connect_entry,
        execution_entry=execution_entry,
        adapter_capability=adapter_capability,
        vault_capability=vault_capability,
        storage_metadata=storage,
        action=curated_action,
        action_runtime_enabled=action_runtime_enabled,
        connection=connection,
        execution_gateway=gateway,
    )


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
    effective_entry = build_composio_connect_enabled_entry(
        entry,
        build_composio_adapter_config(),
    )
    request = WiiiConnectSessionStartRequest(
        provider_slug=effective_entry.slug,
        surface=body.surface,
        requested_scopes=scope_grant_from_mapping(body.requested_scopes),
        redirect_uri_present=bool(body.redirect_uri),
        request_metadata_keys=tuple(body.request_metadata.keys()),
    )
    decision = begin_connection_session(effective_entry, request)
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
    stale_pending_expired = _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
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
            metadata={
                "stage": "preflight",
                "stale_pending_expired": stale_pending_expired,
            },
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
            "stale_pending_expired": stale_pending_expired,
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


@router.get("/providers/{slug}/connections")
async def list_wiii_connect_provider_connections(
    slug: str,
    probe_database: bool = True,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """List sanitized connected accounts for the authenticated Wiii user."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_connect_enabled_entry(entry, composio_config)
    adapter_capability = build_composio_provider_adapter_capability(composio_config)
    storage = _wiii_connect_storage_status_metadata(
        probe_database=probe_database,
    )
    stored_connections = _stored_wiii_connect_connections(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
    )
    stored_lifecycle_connection = stored_connections[0] if stored_connections else None
    if not effective_entry.enabled or not adapter_capability.authorization_ready:
        blocked_reason = (
            "provider_disabled"
            if not effective_entry.enabled
            else adapter_capability.reason
        )
        return {
            "version": "wiii_connect_connection_list.v1",
            "status": "blocked",
            "reason": blocked_reason,
            "provider_slug": effective_entry.slug,
            "provider_kind": effective_entry.provider_kind,
            "connection_count": len(stored_connections),
            "connections": [
                connection.to_public_metadata()
                for connection in stored_connections
            ],
            "connection_lifecycle": build_connection_lifecycle_decision(
                provider_slug=effective_entry.slug,
                connection=stored_lifecycle_connection,
                reason=blocked_reason,
                ready_to_connect=False,
            ).to_public_metadata(),
            "provider": None,
            "storage": storage,
        }

    _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
    )
    provider_result = await list_composio_connected_accounts(
        config=composio_config,
        provider_slug=effective_entry.slug,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
    )
    if provider_result.ready:
        _upsert_listed_connections(
            provider_result.connections,
            effective_entry,
            current_user=current_user,
            storage_metadata=storage,
        )
    lifecycle_connection = (
        provider_result.connections[0]
        if provider_result.connections
        else stored_lifecycle_connection
    )
    return {
        "version": "wiii_connect_connection_list.v1",
        "status": "ready" if provider_result.ready else "blocked",
        "reason": provider_result.reason,
        "provider_slug": effective_entry.slug,
        "provider_kind": effective_entry.provider_kind,
        "connection_count": len(provider_result.connections),
        "connections": [
            connection.to_public_metadata()
            for connection in provider_result.connections
        ],
        "connection_lifecycle": build_connection_lifecycle_decision(
            provider_slug=effective_entry.slug,
            connection=lifecycle_connection,
            reason=provider_result.reason if provider_result.connections else "",
            ready_to_connect=bool(
                effective_entry.enabled and adapter_capability.authorization_ready
            ),
        ).to_public_metadata(),
        "provider": provider_result.to_public_metadata(),
        "storage": storage,
    }


@router.delete("/providers/{slug}/connections/{connection_ref}")
async def disconnect_wiii_connect_provider_connection(
    slug: str,
    connection_ref: str,
    body: WiiiConnectDisconnectBody | None = None,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Disconnect one stored provider account through Wiii backend policy."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    body = body or WiiiConnectDisconnectBody()
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_connect_enabled_entry(entry, composio_config)
    adapter_capability = build_composio_provider_adapter_capability(composio_config)
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    selected_connection_ref = _safe_public_connection_ref(connection_ref)
    safe_connection_id = _resolve_provider_connection_id(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
        connection_ref_or_id=selected_connection_ref,
    )
    if not _connection_storage_ready(storage):
        payload = _disconnect_payload(
            effective_entry,
            status="blocked",
            reason="storage_not_ready",
            storage=storage,
            connection_present=False,
            local_disabled=False,
        )
        _append_provider_lifecycle_audit(
            effective_entry.slug,
            storage,
            current_user=current_user,
            status="blocked",
            reason="storage_not_ready",
            surface=body.surface,
            metadata=payload,
        )
        return payload

    storage_adapter = get_wiii_connect_persistent_storage()
    connection = storage_adapter.get_connection_record(
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_slug=effective_entry.slug,
        connection_id=safe_connection_id,
    )
    if not safe_connection_id or connection is None:
        payload = _disconnect_payload(
            effective_entry,
            status="blocked",
            reason="connection_missing",
            storage=storage,
            connection_present=False,
            local_disabled=False,
        )
        _append_provider_lifecycle_audit(
            effective_entry.slug,
            storage,
            current_user=current_user,
            status="blocked",
            reason="connection_missing",
            surface=body.surface,
            metadata=payload,
        )
        return payload
    if connection.provider_slug != effective_entry.slug:
        payload = _disconnect_payload(
            effective_entry,
            status="blocked",
            reason="connection_provider_mismatch",
            storage=storage,
            connection_present=True,
            local_disabled=False,
        )
        _append_provider_lifecycle_audit(
            effective_entry.slug,
            storage,
            current_user=current_user,
            status="blocked",
            reason="connection_provider_mismatch",
            surface=body.surface,
            metadata=payload,
        )
        return payload
    if not effective_entry.enabled or not adapter_capability.authorization_ready:
        reason = (
            "provider_disabled"
            if not effective_entry.enabled
            else adapter_capability.reason
        )
        payload = _disconnect_payload(
            effective_entry,
            status="blocked",
            reason=reason,
            storage=storage,
            connection_present=True,
            local_disabled=False,
        )
        _append_provider_lifecycle_audit(
            effective_entry.slug,
            storage,
            current_user=current_user,
            status="blocked",
            reason=reason,
            surface=body.surface,
            metadata=payload,
        )
        return payload

    disabled_connection = _disabled_connection_record(
        connection,
        reason="user_disconnect_requested",
    )
    local_disabled = storage_adapter.upsert_connection_record(
        disabled_connection,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_kind=effective_entry.provider_kind,
    )
    if not local_disabled:
        payload = _disconnect_payload(
            effective_entry,
            status="blocked",
            reason="local_state_update_failed",
            storage=storage,
            connection_present=True,
            local_disabled=False,
        )
        _append_provider_lifecycle_audit(
            effective_entry.slug,
            storage,
            current_user=current_user,
            status="blocked",
            reason="local_state_update_failed",
            surface=body.surface,
            metadata=payload,
        )
        return payload

    _append_provider_lifecycle_audit(
        effective_entry.slug,
        storage,
        current_user=current_user,
        status="started",
        reason="provider_disconnect_started",
        surface=body.surface,
        metadata={
            "connection_present": True,
            "local_disabled": True,
            "provider_slug": effective_entry.slug,
        },
    )
    provider_result = await disconnect_composio_connected_account(
        config=composio_config,
        provider_slug=effective_entry.slug,
        connected_account_id=connection.connection_id,
    )
    payload = _disconnect_payload(
        effective_entry,
        status=provider_result.status,
        reason=provider_result.reason,
        storage=storage,
        connection_present=True,
        local_disabled=True,
        provider=provider_result.to_public_metadata(),
    )
    _append_provider_lifecycle_audit(
        effective_entry.slug,
        storage,
        current_user=current_user,
        status=provider_result.status,
        reason=provider_result.reason,
        surface=body.surface,
        metadata=payload,
    )
    return payload


@router.post("/providers/{slug}/connections/{connection_ref}/scope-grant")
async def grant_wiii_connect_provider_connection_scopes(
    slug: str,
    connection_ref: str,
    body: WiiiConnectConnectionScopeGrantBody | None = None,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Persist user-approved scopes for one selected provider account."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    body = body or WiiiConnectConnectionScopeGrantBody()
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    selected_connection_ref = _safe_public_connection_ref(connection_ref)
    safe_connection_id = _resolve_provider_connection_id(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
        connection_ref_or_id=selected_connection_ref,
    )
    storage_adapter = get_wiii_connect_persistent_storage()
    connection = (
        storage_adapter.get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=effective_entry.slug,
            connection_id=safe_connection_id,
        )
        if _connection_storage_ready(storage) and safe_connection_id
        else None
    )
    if connection is None or not connection.active:
        payload = _scope_grant_payload(
            effective_entry,
            status="blocked",
            reason="connection_missing",
            storage=storage,
            connection=None,
        )
        _append_provider_lifecycle_audit(
            effective_entry.slug,
            storage,
            current_user=current_user,
            status="blocked",
            reason="scope_grant_connection_missing",
            surface=body.surface,
            metadata=payload,
        )
        return payload

    requested = scope_grant_from_mapping(body.scopes)
    granted_scopes = _merge_scope_grants(
        connection.scopes,
        _scope_grant_limited_to_policy(requested, effective_entry.default_scopes),
    )
    updated_connection = replace(
        connection,
        scopes=granted_scopes,
        reason="user_scope_grant_updated",
        warnings=tuple(
            sorted(
                set(
                    connection.warnings
                    + (
                        (
                            "user_enabled_external_apply_scope"
                            if granted_scopes.apply
                            else "user_scope_grant_updated"
                        ),
                    )
                )
            )
        ),
    )
    saved = storage_adapter.upsert_connection_record(
        updated_connection,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_kind=effective_entry.provider_kind,
    )
    payload = _scope_grant_payload(
        effective_entry,
        status="ready" if saved else "blocked",
        reason="scope_grant_updated" if saved else "scope_grant_update_failed",
        storage=storage,
        connection=updated_connection if saved else connection,
    )
    _append_provider_lifecycle_audit(
        effective_entry.slug,
        storage,
        current_user=current_user,
        status=payload["status"],
        reason=payload["reason"],
        surface=body.surface,
        metadata={
            "connection_ref_present": bool(selected_connection_ref),
            "requested_scopes": requested.to_metadata(),
            "granted_scopes": granted_scopes.to_metadata(),
        },
    )
    return payload


@router.get("/providers/{slug}/facebook/pages")
async def list_wiii_connect_facebook_pages(
    slug: str,
    connection_ref: str,
    http_request: Request,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """List sanitized Facebook Page choices for a connected account."""

    request_id = _request_id_from_http_request(http_request)
    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    if entry.slug != "facebook":
        raise HTTPException(status_code=404, detail="unsupported_provider_pages")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage, connection, selected_connection_ref, safe_connection_id = (
        _load_selected_wiii_connect_connection(
            effective_entry,
            current_user=current_user,
            connection_ref=connection_ref,
        )
    )
    request = WiiiConnectExecutionRequest(
        provider_slug=effective_entry.slug,
        action_slug="FACEBOOK_LIST_MANAGED_PAGES",
        path="external_app_action",
        mutation="read",
        argument_keys=("fields", "limit"),
        request_id=request_id or "",
    )
    gateway = decide_execution_gateway(
        effective_entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(
            composio_config,
        ),
        audit_ledger_metadata={
            "persistent": bool(
                storage.get("persistent") and storage.get("audit_ledger_ready")
            ),
        },
        connection_selection_required=not bool(selected_connection_ref),
        scope_policy=scope_policy_for_provider_entry(effective_entry),
    )
    audit_base = {
        "surface": "desktop",
        "connection_ref_present": bool(selected_connection_ref),
        "connection_id_present": bool(safe_connection_id),
        "connection_found": connection is not None,
        "stage": "page_list",
    }
    if not gateway.allowed or connection is None:
        _append_execution_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            metadata=audit_base,
        )
        return {
            "version": "wiii_connect_facebook_pages.v1",
            "status": "blocked",
            "reason": gateway.reason,
            "provider_slug": effective_entry.slug,
            "gateway": gateway.to_public_metadata(),
            "pages": [],
            "page_count": 0,
        }
    result = await list_composio_facebook_pages(
        config=composio_config,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
        connected_account_id=connection.connection_id,
        request_id=request.request_id,
    )
    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status="succeeded" if result.ready else "blocked",
        reason=result.reason,
        metadata={**audit_base, "page_list": result.to_public_metadata()},
    )
    payload = result.to_public_metadata()
    payload["gateway"] = gateway.to_public_metadata()
    return payload


@router.post("/providers/{slug}/facebook-post/preview")
async def preview_wiii_connect_facebook_post(
    slug: str,
    body: WiiiConnectFacebookPostPreviewBody,
    http_request: Request,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Create a preview approval token for a Facebook Page post."""

    request_id = _request_id_from_http_request(http_request)
    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    if entry.slug != "facebook":
        raise HTTPException(status_code=404, detail="unsupported_provider_post")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    image_bytes, image_media_type, image_filename, image_error = (
        _decode_facebook_image_payload(body)
    )
    image_url = normalize_facebook_image_url(body.image_url)
    message = normalize_facebook_post_message(body.message)
    page_id = normalize_facebook_page_id(body.page_id)
    action_slug = _facebook_post_action_slug(
        image_bytes=image_bytes,
        image_url=image_url,
    )
    if image_error or not page_id or not message:
        reason = image_error or (
            "missing_page_id" if not page_id else "missing_message"
        )
        return _facebook_post_validation_payload(
            reason=reason,
        )
    storage, connection, selected_connection_ref, safe_connection_id = (
        _load_selected_wiii_connect_connection(
            effective_entry,
            current_user=current_user,
            connection_ref=body.connection_ref,
        )
    )
    request = WiiiConnectExecutionRequest(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        path="external_app_action",
        mutation="preview",
        argument_keys=_facebook_post_argument_keys(
            action_slug=action_slug,
            image_bytes=image_bytes,
            image_url=image_url,
        ),
        request_id=request_id or "",
    )
    gateway = decide_execution_gateway(
        effective_entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(
            composio_config,
        ),
        audit_ledger_metadata={
            "persistent": bool(
                storage.get("persistent") and storage.get("audit_ledger_ready")
            ),
        },
        connection_selection_required=not bool(selected_connection_ref),
        scope_policy=scope_policy_for_provider_entry(effective_entry),
    )
    image_hash = facebook_image_sha256(image_bytes)
    preview_evidence_id = build_facebook_post_preview_evidence_id(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_hash,
        image_url=image_url,
    )
    operation_fingerprint = build_wiii_connect_operation_fingerprint(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_hash,
        image_url=image_url,
    )
    _append_execution_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        metadata={
            "surface": body.surface,
            "stage": "preview",
            "connection_ref_present": bool(selected_connection_ref),
            "connection_id_present": bool(safe_connection_id),
            "connection_found": connection is not None,
            "message_length": len(message),
            "image_present": bool(image_bytes or image_url),
            "image_size_bytes": len(image_bytes),
            "preview_evidence_id_present": bool(preview_evidence_id),
        },
    )
    if not gateway.allowed:
        return _facebook_post_gateway_payload(
            effective_entry,
            status="blocked",
            reason=gateway.reason,
            gateway=gateway,
            storage=storage,
        )
    operation_approval = _record_facebook_post_operation_approval(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        preview_evidence_id=preview_evidence_id,
        request_fingerprint=operation_fingerprint,
        selected_connection_ref=selected_connection_ref,
        page_selected=bool(page_id),
        message_length=len(message),
        image_present=bool(image_bytes or image_url),
        image_size_bytes=len(image_bytes),
        image_url_present=bool(image_url),
    )
    approval_token = build_facebook_post_approval_token(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_hash,
        image_url=image_url,
        secret_key=settings.session_secret_key,
    )
    return {
        "version": "wiii_connect_facebook_post_preview.v1",
        "status": "ready",
        "reason": "preview_ready",
        "provider_slug": effective_entry.slug,
        "action_slug": action_slug,
        "preview_evidence_id": preview_evidence_id,
        "approval_token": approval_token,
        "preview": {
            "page_id": page_id,
            "message": message,
            "image_present": bool(image_bytes or image_url),
            "image_media_type": image_media_type,
            "image_filename": image_filename,
            "image_url_present": bool(image_url),
        },
        "gateway": gateway.to_public_metadata(),
        "approval_ledger": operation_approval.to_public_metadata(),
        "storage": storage,
    }


@router.post("/providers/{slug}/facebook-post/apply")
async def apply_wiii_connect_facebook_post(
    slug: str,
    body: WiiiConnectFacebookPostApplyBody,
    http_request: Request,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Post to Facebook only after preview evidence and approval token match."""

    request_id = _request_id_from_http_request(http_request)
    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    if entry.slug != "facebook":
        raise HTTPException(status_code=404, detail="unsupported_provider_post")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    image_bytes, image_media_type, image_filename, image_error = (
        _decode_facebook_image_payload(body)
    )
    image_url = normalize_facebook_image_url(body.image_url)
    message = normalize_facebook_post_message(body.message)
    page_id = normalize_facebook_page_id(body.page_id)
    action_slug = _facebook_post_action_slug(
        image_bytes=image_bytes,
        image_url=image_url,
    )
    if image_error or not page_id or not message:
        reason = image_error or (
            "missing_page_id" if not page_id else "missing_message"
        )
        return _facebook_post_validation_payload(
            reason=reason,
        )
    selected_connection_ref = _safe_public_connection_ref(body.connection_ref)
    image_hash = facebook_image_sha256(image_bytes)
    token_check = verify_facebook_post_approval_token(
        body.approval_token,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_hash,
        image_url=image_url,
        secret_key=settings.session_secret_key,
        preview_evidence_id=_safe_public_id(body.preview_evidence_id) or "",
    )
    if not token_check.valid:
        return {
            "version": "wiii_connect_facebook_post_apply.v1",
            "status": "blocked",
            "reason": token_check.reason,
            "provider_slug": effective_entry.slug,
            "token": token_check.to_public_metadata(),
            "execution": None,
        }

    storage, connection, selected_connection_ref, safe_connection_id = (
        _load_selected_wiii_connect_connection(
            effective_entry,
            current_user=current_user,
            connection_ref=body.connection_ref,
        )
    )
    operation_fingerprint = build_wiii_connect_operation_fingerprint(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_hash,
        image_url=image_url,
    )
    operation_approval = _consume_facebook_post_operation_approval(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        preview_evidence_id=token_check.preview_evidence_id,
        request_fingerprint=operation_fingerprint,
    )
    if operation_approval.blocked:
        return {
            "version": "wiii_connect_facebook_post_apply.v1",
            "status": "blocked",
            "reason": operation_approval.reason,
            "provider_slug": effective_entry.slug,
            "action_slug": action_slug,
            "token": token_check.to_public_metadata(),
            "approval_ledger": operation_approval.to_public_metadata(),
            "gateway": None,
            "schema": None,
            "upload": None,
            "execution": None,
            "storage": storage,
        }
    argument_keys = _facebook_post_argument_keys(
        action_slug=action_slug,
        image_bytes=image_bytes,
        image_url=image_url,
    )
    request = WiiiConnectExecutionRequest(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        path="external_app_action",
        mutation="apply",
        approval_token_present=True,
        preview_evidence_id=token_check.preview_evidence_id,
        preview_evidence_required=True,
        argument_keys=argument_keys,
        request_id=request_id or "",
    )
    gateway = decide_execution_gateway(
        effective_entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(
            composio_config,
        ),
        audit_ledger_metadata={
            "persistent": bool(
                storage.get("persistent") and storage.get("audit_ledger_ready")
            ),
        },
        connection_selection_required=not bool(selected_connection_ref),
        scope_policy=scope_policy_for_provider_entry(effective_entry),
    )
    audit_base = {
        "surface": body.surface,
        "connection_ref_present": bool(selected_connection_ref),
        "connection_id_present": bool(safe_connection_id),
        "connection_found": connection is not None,
        "preview_evidence_id_present": bool(token_check.preview_evidence_id),
        "approval_token_present": True,
        "message_length": len(message),
        "image_present": bool(image_bytes or image_url),
        "image_size_bytes": len(image_bytes),
        "approval_ledger": operation_approval.to_public_metadata(),
    }
    if not gateway.allowed or connection is None:
        _append_execution_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            metadata={**audit_base, "stage": "gateway"},
        )
        return _facebook_post_gateway_payload(
            effective_entry,
            status="blocked",
            reason=gateway.reason,
            gateway=gateway,
            storage=storage,
            approval_ledger=operation_approval.to_public_metadata(),
        )
    schema = await verify_composio_tool_schema(
        config=composio_config,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        request_id=request.request_id,
    )
    if not schema.ready:
        _append_execution_stage_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            status="blocked",
            reason=schema.reason,
            metadata={
                **audit_base,
                "stage": "schema",
                "schema": schema.to_public_metadata(),
            },
        )
        return _facebook_post_gateway_payload(
            effective_entry,
            status="blocked",
            reason=schema.reason,
            gateway=gateway,
            storage=storage,
            schema=schema.to_public_metadata(),
            approval_ledger=operation_approval.to_public_metadata(),
        )

    arguments: dict[str, Any] = {
        "page_id": page_id,
        "message": message,
        "published": True,
    }
    upload_metadata: dict[str, Any] | None = None
    if image_bytes:
        upload = await stage_composio_file_upload(
            config=composio_config,
            provider_slug=effective_entry.slug,
            action_slug=action_slug,
            filename=image_filename,
            mimetype=image_media_type,
            content=image_bytes,
            request_id=request.request_id,
        )
        upload_metadata = upload.to_public_metadata()
        if not upload.ready:
            _append_execution_stage_audit(
                gateway,
                request,
                storage,
                current_user=current_user,
                status="blocked",
                reason=upload.reason,
                metadata={**audit_base, "stage": "file_upload", "upload": upload_metadata},
            )
            return _facebook_post_gateway_payload(
                effective_entry,
                status="blocked",
                reason=upload.reason,
                gateway=gateway,
                storage=storage,
                schema=schema.to_public_metadata(),
                upload=upload_metadata,
                approval_ledger=operation_approval.to_public_metadata(),
            )
        arguments["photo"] = upload.file_descriptor
    elif image_url:
        arguments["url"] = image_url

    missing_argument_keys = _missing_required_argument_keys(
        required_keys=schema.required_argument_keys,
        arguments=arguments,
    )
    if missing_argument_keys:
        _append_execution_stage_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            status="blocked",
            reason="missing_required_arguments",
            metadata={
                **audit_base,
                "stage": "schema",
                "schema": schema.to_public_metadata(),
                "missing_required_arguments": list(missing_argument_keys),
            },
        )
        return _facebook_post_gateway_payload(
            effective_entry,
            status="blocked",
            reason="missing_required_arguments",
            gateway=gateway,
            storage=storage,
            schema=schema.to_public_metadata(),
            upload=upload_metadata,
            missing_argument_keys=list(missing_argument_keys),
            approval_ledger=operation_approval.to_public_metadata(),
        )

    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status="started",
        reason="provider_execution_started",
        metadata={
            **audit_base,
            "stage": "execute",
            "schema": schema.to_public_metadata(),
            "upload": upload_metadata,
        },
    )
    execution = await execute_composio_tool(
        config=composio_config,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
        connected_account_id=connection.connection_id,
        arguments=arguments,
        request_id=request.request_id,
    )
    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status=execution.status,
        reason=execution.reason,
        metadata={
            **audit_base,
            "stage": "execute_result",
            "schema": schema.to_public_metadata(),
            "upload": upload_metadata,
            "execution": execution.to_public_metadata(),
        },
    )
    return {
        "version": "wiii_connect_facebook_post_apply.v1",
        "status": execution.status,
        "reason": execution.reason,
        "provider_slug": effective_entry.slug,
        "action_slug": action_slug,
        "gateway": gateway.to_public_metadata(),
        "schema": schema.to_public_metadata(),
        "upload": upload_metadata,
        "execution": execution.to_public_metadata(),
        "approval_ledger": operation_approval.to_public_metadata(),
        "storage": storage,
    }


@router.get("/providers/{slug}/actions")
async def list_wiii_connect_provider_actions(slug: str) -> dict[str, object]:
    """Return the privacy-safe curated action catalog for a provider."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    enabled_slugs = composio_config.executable_action_slugs_for_provider(entry.slug)
    return action_catalog_public_metadata(
        provider_slug=entry.slug,
        enabled_slugs=enabled_slugs,
    )


@router.get("/providers/{slug}/effective-actions")
async def list_wiii_connect_provider_effective_actions(
    slug: str,
    connection_ref: str | None = None,
    probe_database: bool = True,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Return the OpenHuman-style effective action inventory for a provider.

    This endpoint performs no provider network call and exposes no tool schema.
    It only projects which curated actions can be seen by the agent, which are
    executable now, and which policy stage is blocking the rest.
    """

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = _wiii_connect_storage_status_metadata(probe_database=probe_database)
    selected_connection_ref = _safe_public_connection_ref(connection_ref)
    safe_connection_id = _resolve_provider_connection_id(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
        connection_ref_or_id=selected_connection_ref,
    )
    _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
    )
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=effective_entry.slug,
            connection_id=safe_connection_id,
        )
        if _connection_storage_ready(storage) and safe_connection_id
        else None
    )
    inventory = build_wiii_connect_effective_action_inventory(
        entry=effective_entry,
        connection=connection,
        adapter_capability=build_composio_provider_adapter_capability(composio_config),
        runtime_enabled_action_slugs=composio_config.executable_action_slugs_for_provider(
            effective_entry.slug,
        ),
        audit_ledger_metadata={
            "persistent": bool(
                storage.get("persistent") and storage.get("audit_ledger_ready")
            ),
        },
        connection_ref_present=bool(selected_connection_ref),
        connection_selection_required=not bool(selected_connection_ref),
        storage_metadata=storage,
        scope_policy=scope_policy_for_provider_entry(effective_entry),
    )
    return inventory.to_public_metadata()


@router.post("/providers/{slug}/execution-decision")
async def decide_wiii_connect_provider_execution(
    slug: str,
    body: WiiiConnectExecutionDecisionBody,
    http_request: Request,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Return the audited fail-closed decision for one provider action.

    This endpoint is a gateway preflight only. It does not execute provider
    actions and it never accepts raw provider arguments, provider payloads, or
    approval token values.
    """

    request_id = _request_id_from_http_request(http_request)
    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    storage_ready = _connection_storage_ready(storage)
    selected_connection_ref = _safe_public_connection_ref(
        body.connection_ref or body.connection_id,
    )
    safe_connection_id = _resolve_provider_connection_id(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
        connection_ref_or_id=selected_connection_ref,
    )
    _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
    )
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=effective_entry.slug,
            connection_id=safe_connection_id,
        )
        if storage_ready and safe_connection_id
        else None
    )
    request = WiiiConnectExecutionRequest(
        provider_slug=effective_entry.slug,
        action_slug=_safe_action_slug(body.action_slug),
        path=_safe_path(body.path),
        mutation=_safe_mutation(body.mutation),
        approval_token_present=bool(body.approval_token_present),
        preview_evidence_id=_safe_public_id(body.preview_evidence_id),
        preview_evidence_required=bool(body.preview_evidence_required),
        argument_keys=tuple(_safe_argument_keys(body.argument_keys)),
        request_id=request_id or "",
    )
    gateway = decide_execution_gateway(
        effective_entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(
            composio_config,
        ),
        audit_ledger_metadata={
            "persistent": bool(storage.get("persistent") and storage.get("audit_ledger_ready")),
        },
        connection_selection_required=not bool(selected_connection_ref),
        scope_policy=scope_policy_for_provider_entry(effective_entry),
    )
    _append_execution_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        metadata={
            "surface": body.surface,
            "connection_ref_present": bool(selected_connection_ref),
            "connection_id_present": bool(safe_connection_id),
            "connection_found": connection is not None,
            "storage": storage,
        },
    )
    payload = gateway.to_public_metadata()
    payload["provider_slug"] = effective_entry.slug
    payload["storage"] = storage
    return payload


@router.post("/providers/{slug}/execute")
async def execute_wiii_connect_provider_action(
    slug: str,
    body: WiiiConnectExecutionRunBody,
    http_request: Request,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Run one provider action through the shared Wiii Connect executor."""

    request_id = _request_id_from_http_request(http_request)
    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = storage_status_metadata()
    selected_connection_ref = _safe_public_connection_ref(
        body.connection_ref or body.connection_id,
    )
    _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=effective_entry.slug,
    )
    connection = (
        select_wiii_connect_connection(
            effective_entry.slug,
            current_user=current_user,
            storage=storage,
            connection_ref=selected_connection_ref,
        )
        if selected_connection_ref
        else None
    )
    action_slug = _safe_action_slug(body.action_slug)
    mutation = _safe_mutation(body.mutation)
    sanitized_arguments = model_visible_arguments(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        arguments=body.arguments,
    )
    authorization = resolve_wiii_connect_action_authorization(
        mutation=mutation,
        preview_evidence_id=_safe_public_id(body.preview_evidence_id),
        approval_token_present=bool(body.approval_token_present),
        authorization_verified=False,
    )
    argument_policy = _argument_policy_metadata(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        raw_arguments=body.arguments,
        safe_arguments=sanitized_arguments,
    )
    argument_keys = tuple(_safe_argument_keys(list(sanitized_arguments.keys())))
    plan = WiiiConnectBackendActionPlan(
        entry=effective_entry,
        config=composio_config,
        current_user=current_user,
        connection=connection,
        storage=storage,
        action_slug=action_slug,
        mutation=mutation,
        path=_safe_path(body.path),
        arguments=sanitized_arguments,
        argument_keys=argument_keys,
        approval_token_present=authorization.trusted_approval_token_present,
        preview_evidence_id=authorization.trusted_preview_evidence_id,
        preview_evidence_required=bool(body.preview_evidence_required),
        connection_selection_required=not bool(selected_connection_ref),
        surface=body.surface,
        stage="api_execute",
        request_id=request_id,
        audit_metadata={
            "connection_ref_present": bool(selected_connection_ref),
            "connection_found": connection is not None,
            "operation_policy": authorization.to_public_metadata(),
            "argument_policy": argument_policy,
            "storage": storage,
        },
    )
    preflight = await preflight_wiii_connect_composio_backend_action(plan)
    if preflight.status != "ready":
        payload = preflight.gateway.to_public_metadata()
        payload["status"] = "blocked"
        payload["reason"] = preflight.reason
        payload["provider_slug"] = effective_entry.slug
        payload["storage"] = storage
        payload["schema"] = (
            preflight.schema.to_public_metadata() if preflight.schema else None
        )
        payload["execution"] = None
        payload["operation_policy"] = authorization.to_public_metadata()
        payload["argument_policy"] = argument_policy
        return payload

    result = await execute_wiii_connect_composio_backend_action(
        plan,
        preflight=preflight,
    )
    payload = result.gateway.to_public_metadata()
    payload["status"] = result.status
    payload["reason"] = result.reason
    payload["provider_slug"] = effective_entry.slug
    payload["storage"] = storage
    payload["schema"] = result.schema.to_public_metadata() if result.schema else None
    payload["execution"] = (
        result.execution.to_public_metadata() if result.execution else None
    )
    payload["operation_policy"] = authorization.to_public_metadata()
    payload["argument_policy"] = argument_policy
    if result.missing_argument_keys:
        payload["missing_argument_keys"] = list(result.missing_argument_keys)
    return payload


@router.get("/providers/{slug}/callback", response_model=None)
async def receive_wiii_connect_provider_callback(
    slug: str,
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    connected_account_id: str | None = None,
    status: str | None = None,
    surface: str = "desktop",
) -> dict[str, object] | HTMLResponse:
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
    payload = decision.to_public_metadata()
    if _wiii_connect_callback_wants_html(request):
        return _wiii_connect_callback_html(payload)
    return payload


def _wiii_connect_callback_wants_html(request: Request) -> bool:
    accept = str(request.headers.get("accept") or "").lower()
    return "text/html" in accept and "application/json" not in accept


def _wiii_connect_callback_html(payload: dict[str, object]) -> HTMLResponse:
    provider_slug = _safe_callback_html_text(payload.get("provider_slug"))
    label = _safe_callback_html_text(payload.get("label") or provider_slug)
    status = _safe_callback_html_text(payload.get("status"))
    reason = _safe_callback_html_text(payload.get("reason"))
    accepted = status == "accepted"
    title = (
        f"Kết nối {label} đã được ghi nhận"
        if accepted
        else f"Kết nối {label} chưa hoàn tất"
    )
    detail = (
        "Wiii đã nhận callback từ provider. Quay lại Wiii Connect và bấm "
        "Làm mới trạng thái nếu danh sách account chưa tự cập nhật."
        if accepted
        else "Wiii đã chặn callback này theo policy. Quay lại Wiii Connect để "
        "xem lý do và thử kết nối lại nếu cần."
    )
    message = {
        "type": "wiii-connect:callback",
        "providerSlug": provider_slug,
        "status": status,
        "reason": reason,
    }
    message_json = json.dumps(message, ensure_ascii=False)
    html = f"""<!doctype html>
<html lang="vi">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Wiii Connect</title>
    <style>
      :root {{ color-scheme: light; }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f7f6ef;
        color: #1f2933;
      }}
      main {{
        width: min(520px, calc(100vw - 32px));
        border: 1px solid #dfddd2;
        border-radius: 12px;
        background: #fffefa;
        box-shadow: 0 20px 50px rgba(31, 41, 51, 0.12);
        padding: 28px;
      }}
      .badge {{
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        border: 1px solid { "#a7f3d0" if accepted else "#fed7aa" };
        background: { "#ecfdf5" if accepted else "#fff7ed" };
        color: { "#047857" if accepted else "#9a3412" };
        padding: 6px 10px;
        font-size: 13px;
        font-weight: 600;
      }}
      h1 {{
        margin: 18px 0 10px;
        font-size: 26px;
        line-height: 1.2;
      }}
      p {{
        margin: 0;
        color: #52616b;
        line-height: 1.6;
      }}
      dl {{
        margin: 18px 0 0;
        display: grid;
        gap: 8px;
        font-size: 14px;
      }}
      div.row {{
        display: flex;
        justify-content: space-between;
        gap: 16px;
        border-radius: 8px;
        background: #f4f1e8;
        padding: 10px 12px;
      }}
      dt {{ color: #6b7280; }}
      dd {{ margin: 0; font-weight: 600; }}
      button {{
        margin-top: 20px;
        border: 0;
        border-radius: 8px;
        background: #111827;
        color: white;
        cursor: pointer;
        font: inherit;
        font-weight: 700;
        padding: 11px 14px;
      }}
    </style>
  </head>
  <body>
    <main>
      <span class="badge">{escape(status)}</span>
      <h1>{escape(title)}</h1>
      <p>{escape(detail)}</p>
      <dl>
        <div class="row"><dt>Provider</dt><dd>{escape(label)}</dd></div>
        <div class="row"><dt>Lý do</dt><dd>{escape(reason)}</dd></div>
      </dl>
      <button type="button" onclick="window.close()">Đóng tab này</button>
    </main>
    <script>
      window.opener?.postMessage({message_json}, "*");
      window.history?.replaceState(null, document.title, window.location.pathname + "?status={escape(status)}&provider={escape(provider_slug)}");
    </script>
  </body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


def _load_selected_wiii_connect_connection(
    entry: Any,
    *,
    current_user: AuthenticatedUser,
    connection_ref: str | None,
) -> tuple[dict[str, Any], WiiiConnectConnectionRecordV1 | None, str, str]:
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    storage_ready = _connection_storage_ready(storage)
    selected_connection_ref = _safe_public_connection_ref(connection_ref)
    safe_connection_id = _resolve_provider_connection_id(
        storage,
        current_user=current_user,
        provider_slug=entry.slug,
        connection_ref_or_id=selected_connection_ref,
    )
    _expire_stale_pending_connections(
        storage,
        current_user=current_user,
        provider_slug=entry.slug,
    )
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=entry.slug,
            connection_id=safe_connection_id,
        )
        if storage_ready and safe_connection_id
        else None
    )
    return storage, connection, selected_connection_ref, safe_connection_id


def _scope_grant_limited_to_policy(
    requested: WiiiConnectScopeGrant,
    allowed: WiiiConnectScopeGrant,
) -> WiiiConnectScopeGrant:
    return WiiiConnectScopeGrant(
        read=bool(requested.read and allowed.read),
        preview=bool(requested.preview and allowed.preview),
        write=bool(requested.write and allowed.write),
        apply=bool(requested.apply and allowed.apply),
        admin=False,
    )


def _merge_scope_grants(
    base: WiiiConnectScopeGrant,
    granted: WiiiConnectScopeGrant,
) -> WiiiConnectScopeGrant:
    return WiiiConnectScopeGrant(
        read=bool(base.read or granted.read),
        preview=bool(base.preview or granted.preview),
        write=bool(base.write or granted.write),
        apply=bool(base.apply or granted.apply),
        admin=False,
    )


def _scope_grant_payload(
    entry: Any,
    *,
    status: str,
    reason: str,
    storage: dict[str, Any],
    connection: WiiiConnectConnectionRecordV1 | None,
) -> dict[str, object]:
    return {
        "version": "wiii_connect_scope_grant.v1",
        "status": _safe_surface(status),
        "reason": _safe_surface(reason),
        "provider_slug": entry.slug,
        "provider_kind": entry.provider_kind,
        "connection": connection.to_public_metadata() if connection else None,
        "storage": storage,
    }


def _decode_facebook_image_payload(
    body: WiiiConnectFacebookPostPreviewBody,
) -> tuple[bytes, str, str, str]:
    raw = str(body.image_base64 or "").strip()
    if not raw:
        return b"", "", "", ""
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    media_type = normalize_facebook_image_media_type(body.image_media_type)
    if not media_type:
        return b"", "", "", "unsupported_image_type"
    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return b"", "", "", "invalid_image_base64"
    if not image_bytes:
        return b"", "", "", "missing_image"
    if len(image_bytes) > 10 * 1024 * 1024:
        return b"", "", "", "image_too_large"
    filename = normalize_facebook_image_filename(
        body.image_filename,
        media_type=media_type,
    )
    return image_bytes, media_type, filename, ""


def _facebook_post_action_slug(
    *,
    image_bytes: bytes,
    image_url: str,
) -> str:
    if image_bytes or image_url:
        return "FACEBOOK_CREATE_PHOTO_POST"
    return "FACEBOOK_CREATE_POST"


def _facebook_post_argument_keys(
    *,
    action_slug: str,
    image_bytes: bytes,
    image_url: str,
) -> tuple[str, ...]:
    if action_slug == "FACEBOOK_CREATE_PHOTO_POST":
        if image_bytes:
            return ("page_id", "message", "photo", "published")
        if image_url:
            return ("page_id", "message", "url", "published")
        return ("page_id", "message", "published")
    return ("page_id", "message", "published")


def _facebook_post_validation_payload(*, reason: str) -> dict[str, object]:
    return {
        "version": "wiii_connect_facebook_post_validation.v1",
        "status": "validation_failed",
        "reason": _safe_surface(reason),
        "provider_slug": "facebook",
        "gateway": None,
        "execution": None,
    }


def _record_facebook_post_operation_approval(
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    provider_slug: str,
    action_slug: str,
    preview_evidence_id: str,
    request_fingerprint: str,
    selected_connection_ref: str,
    page_selected: bool,
    message_length: int,
    image_present: bool,
    image_size_bytes: int,
    image_url_present: bool,
) -> WiiiConnectOperationApprovalDecision:
    if not _operation_approval_storage_ready(storage_metadata):
        return unavailable_operation_approval_decision(
            provider_slug=provider_slug,
            action_slug=action_slug,
            preview_evidence_id=preview_evidence_id,
            request_fingerprint=request_fingerprint,
        )
    storage = get_wiii_connect_persistent_storage()
    append_record = getattr(storage, "append_operation_approval_record", None)
    if not callable(append_record):
        return unavailable_operation_approval_decision(
            provider_slug=provider_slug,
            action_slug=action_slug,
            preview_evidence_id=preview_evidence_id,
            request_fingerprint=request_fingerprint,
        )

    record = build_wiii_connect_operation_approval_record(
        provider_slug=provider_slug,
        action_slug=action_slug,
        preview_evidence_id=preview_evidence_id,
        request_fingerprint=request_fingerprint,
        ttl_seconds=FACEBOOK_POST_APPROVAL_TOKEN_MAX_AGE_SECONDS,
        metadata={
            "selected_connection_present": bool(selected_connection_ref),
            "page_selected": bool(page_selected),
            "message_length": int(message_length),
            "image_present": bool(image_present),
            "image_size_bytes": int(image_size_bytes),
            "image_url_present": bool(image_url_present),
        },
    )
    saved = bool(
        append_record(
            record,
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
        )
    )
    if not saved:
        return unavailable_operation_approval_decision(
            provider_slug=provider_slug,
            action_slug=action_slug,
            preview_evidence_id=preview_evidence_id,
            request_fingerprint=request_fingerprint,
        )
    return WiiiConnectOperationApprovalDecision(
        status="pending",
        reason="preview_recorded",
        provider_slug=provider_slug,
        action_slug=action_slug,
        preview_evidence_id_present=bool(preview_evidence_id),
        request_fingerprint_present=bool(request_fingerprint),
        persistent=True,
        metadata={
            "selected_connection_present": bool(selected_connection_ref),
            "page_selected": bool(page_selected),
            "message_length": int(message_length),
            "image_present": bool(image_present),
            "image_size_bytes": int(image_size_bytes),
            "image_url_present": bool(image_url_present),
        },
    )


def _consume_facebook_post_operation_approval(
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    provider_slug: str,
    action_slug: str,
    preview_evidence_id: str,
    request_fingerprint: str,
) -> WiiiConnectOperationApprovalDecision:
    if not _operation_approval_storage_ready(storage_metadata):
        return unavailable_operation_approval_decision(
            provider_slug=provider_slug,
            action_slug=action_slug,
            preview_evidence_id=preview_evidence_id,
            request_fingerprint=request_fingerprint,
        )
    storage = get_wiii_connect_persistent_storage()
    consume_record = getattr(storage, "consume_operation_approval_record", None)
    if not callable(consume_record):
        return unavailable_operation_approval_decision(
            provider_slug=provider_slug,
            action_slug=action_slug,
            preview_evidence_id=preview_evidence_id,
            request_fingerprint=request_fingerprint,
        )
    return consume_record(
        preview_evidence_id=preview_evidence_id,
        request_fingerprint=request_fingerprint,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_slug=provider_slug,
        action_slug=action_slug,
    )


def _facebook_post_gateway_payload(
    entry: Any,
    *,
    status: str,
    reason: str,
    gateway: Any,
    storage: dict[str, Any],
    schema: dict[str, Any] | None = None,
    upload: dict[str, Any] | None = None,
    missing_argument_keys: list[str] | None = None,
    approval_ledger: dict[str, Any] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "wiii_connect_facebook_post_apply.v1",
        "status": _safe_surface(status),
        "reason": _safe_surface(reason),
        "provider_slug": entry.slug,
        "gateway": gateway.to_public_metadata(),
        "schema": schema,
        "upload": upload,
        "execution": None,
        "storage": storage,
    }
    if approval_ledger is not None:
        payload["approval_ledger"] = approval_ledger
    if missing_argument_keys:
        payload["missing_argument_keys"] = missing_argument_keys
    return payload


def _safe_callback_html_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(marker in text.lower() for marker in ("token", "secret", "password")):
        return "redacted"
    return text[:120]


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


def _append_execution_audit(
    gateway: Any,
    request: WiiiConnectExecutionRequest,
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    metadata: dict[str, Any],
) -> None:
    if not bool(storage_metadata.get("persistent") and storage_metadata.get("audit_ledger_ready")):
        return
    record = build_audit_ledger_record(
        event_kind="execution",
        provider_slug=gateway.decision.provider_slug,
        status=gateway.status,
        reason=gateway.reason,
        surface=_safe_surface(metadata.get("surface") or "backend"),
        metadata={
            "request": request.to_audit_metadata(),
            "decision": gateway.decision.to_metadata(),
            **metadata,
        },
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
    )


def _append_execution_stage_audit(
    gateway: Any,
    request: WiiiConnectExecutionRequest,
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    status: str,
    reason: str,
    metadata: dict[str, Any],
) -> None:
    if not bool(storage_metadata.get("persistent") and storage_metadata.get("audit_ledger_ready")):
        return
    record = build_audit_ledger_record(
        event_kind="execution",
        provider_slug=gateway.decision.provider_slug,
        status=_safe_surface(status),
        reason=_safe_surface(reason),
        surface=_safe_surface(metadata.get("surface") or "backend"),
        metadata={
            "request": request.to_audit_metadata(),
            "decision": gateway.decision.to_metadata(),
            **metadata,
        },
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
    )


def _append_provider_lifecycle_audit(
    provider_slug: str,
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    status: str,
    reason: str,
    surface: str,
    metadata: dict[str, Any],
) -> None:
    if not bool(storage_metadata.get("persistent") and storage_metadata.get("audit_ledger_ready")):
        return
    record = build_audit_ledger_record(
        event_kind="provider",
        provider_slug=provider_slug,
        status=_safe_surface(status),
        reason=_safe_surface(reason),
        surface=_safe_surface(surface),
        metadata=metadata,
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
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


def _upsert_listed_connections(
    connections: tuple[WiiiConnectConnectionRecordV1, ...],
    entry: Any,
    *,
    current_user: AuthenticatedUser,
    storage_metadata: dict[str, Any],
) -> None:
    if not _connection_storage_ready(storage_metadata):
        return
    storage = get_wiii_connect_persistent_storage()
    for connection in connections:
        if _provider_poll_would_reanimate_user_disconnect(
            storage,
            connection,
            current_user=current_user,
        ):
            continue
        connection_to_save = _provider_connection_with_preserved_user_scopes(
            storage,
            connection,
            current_user=current_user,
        )
        storage.upsert_connection_record(
            connection_to_save,
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_kind=entry.provider_kind,
        )


def _provider_poll_would_reanimate_user_disconnect(
    storage: Any,
    connection: WiiiConnectConnectionRecordV1,
    *,
    current_user: AuthenticatedUser,
) -> bool:
    existing = storage.get_connection_record(
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_slug=connection.provider_slug,
        connection_id=connection.connection_id,
    )
    return bool(
        existing is not None
        and existing.state == "disabled"
        and existing.reason == "user_disconnect_requested"
        and connection.active
    )


def _provider_connection_with_preserved_user_scopes(
    storage: Any,
    connection: WiiiConnectConnectionRecordV1,
    *,
    current_user: AuthenticatedUser,
) -> WiiiConnectConnectionRecordV1:
    existing = storage.get_connection_record(
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_slug=connection.provider_slug,
        connection_id=connection.connection_id,
    )
    if existing is None:
        return connection
    return replace(
        connection,
        scopes=_merge_scope_grants(connection.scopes, existing.scopes),
        warnings=tuple(sorted(set(connection.warnings + existing.warnings))),
    )


def _disabled_connection_record(
    connection: WiiiConnectConnectionRecordV1,
    *,
    reason: str,
) -> WiiiConnectConnectionRecordV1:
    return WiiiConnectConnectionRecordV1(
        connection_id=connection.connection_id,
        provider_slug=connection.provider_slug,
        state="disabled",
        scopes=scope_grant_from_mapping({}),
        vault_ref=connection.vault_ref,
        account_label=connection.account_label,
        external_account_ref=connection.external_account_ref,
        last_checked_at=connection.last_checked_at,
        reason=reason,
        warnings=tuple(
            sorted(set(connection.warnings + ("disconnected_by_user",)))
        ),
    )


def _disconnect_payload(
    entry: Any,
    *,
    status: str,
    reason: str,
    storage: dict[str, Any],
    connection_present: bool,
    local_disabled: bool,
    provider: dict[str, Any] | None = None,
) -> dict[str, object]:
    return {
        "version": "wiii_connect_disconnect.v1",
        "status": _safe_surface(status),
        "reason": _safe_surface(reason),
        "provider_slug": entry.slug,
        "provider_kind": entry.provider_kind,
        "connection_present": connection_present,
        "local_disabled": local_disabled,
        "provider": provider,
        "storage": storage,
    }


def _connection_storage_ready(storage_metadata: dict[str, Any]) -> bool:
    return bool(
        storage_metadata.get("persistent")
        and storage_metadata.get("connection_table_ready")
        and storage_metadata.get("audit_ledger_ready")
    )


def _connection_listing_storage_ready(storage_metadata: dict[str, Any]) -> bool:
    return bool(
        storage_metadata.get("persistent")
        and storage_metadata.get("connection_table_ready")
    )


def _operation_approval_storage_ready(storage_metadata: dict[str, Any]) -> bool:
    return bool(
        storage_metadata.get("persistent")
        and storage_metadata.get("audit_ledger_ready")
        and storage_metadata.get("operation_approval_table_ready")
    )


def _stored_wiii_connect_connections(
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    provider_slug: str,
) -> tuple[WiiiConnectConnectionRecordV1, ...]:
    """Return sanitized local connection rows without implying agent readiness."""

    if not _connection_listing_storage_ready(storage_metadata):
        return ()
    try:
        return get_wiii_connect_persistent_storage().list_connection_records(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=provider_slug,
        )
    except Exception:
        return ()


def _expire_stale_pending_connections(
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    provider_slug: str,
) -> int:
    if not _connection_storage_ready(storage_metadata):
        return 0
    storage = get_wiii_connect_persistent_storage()
    expire = getattr(storage, "expire_stale_pending_connections", None)
    if not callable(expire):
        return 0
    try:
        return int(
            expire(
                organization_id=_wiii_connect_owner_organization_id(current_user),
                user_id=current_user.user_id,
                provider_slug=provider_slug,
                ttl_seconds=DEFAULT_STALE_PENDING_CONNECTION_TTL_SECONDS,
            )
            or 0
        )
    except Exception:
        return 0


def _wiii_connect_owner_organization_id(user: AuthenticatedUser) -> str:
    if user.organization_id:
        return user.organization_id
    return build_composio_external_user_id(
        organization_id=None,
        user_id=user.user_id,
    )


def _wiii_connect_snapshot_state(
    current_user: AuthenticatedUser | None,
) -> dict[str, Any]:
    """Build the sanitized state slice needed for user-scoped snapshots."""

    context: dict[str, Any] = {}
    state: dict[str, Any] = {"context": context}
    if current_user is None:
        return state

    user_id = str(current_user.user_id or "").strip()
    organization_id = str(current_user.organization_id or "").strip()
    session_id = str(current_user.session_id or "").strip()
    role = str(current_user.role or "").strip()

    if user_id:
        state["user_id"] = user_id
        context["user_id"] = user_id
    if organization_id:
        state["organization_id"] = organization_id
        context["organization_id"] = organization_id
    if session_id:
        state["session_id"] = session_id
        context["session_id"] = session_id
    if role:
        state["user_role"] = role
        context["user_role"] = role
    return state


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


def _safe_public_connection_ref(value: str | None) -> str:
    candidate = _safe_provider_connection_id(value)
    if candidate.startswith("wcn_"):
        return candidate
    return ""


def _resolve_provider_connection_id(
    storage_metadata: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    provider_slug: str,
    connection_ref_or_id: str | None,
) -> str:
    """Resolve an opaque public connection ref inside one org/user boundary."""

    candidate = _safe_provider_connection_id(connection_ref_or_id)
    if not candidate:
        return ""
    if not candidate.startswith("wcn_"):
        return ""
    if not _connection_storage_ready(storage_metadata):
        return candidate

    storage = get_wiii_connect_persistent_storage()
    for connection in storage.list_connection_records(
        organization_id=_wiii_connect_owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_slug=provider_slug,
    ):
        if connection_ref_matches(
            provider_slug=connection.provider_slug,
            connection_id=connection.connection_id,
            candidate=candidate,
        ):
            return connection.connection_id
    return candidate


def _safe_action_slug(value: str) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _default_activation_action_slug_for_provider(provider_slug: str) -> str:
    """Return a provider-scoped default action for readiness diagnostics."""

    actions = list_wiii_connect_curated_actions(
        provider_slug=provider_slug,
        include_disabled=True,
    )
    readonly = [action for action in actions if action.mutation == "read"]
    candidates = readonly or list(actions)
    return candidates[0].slug if candidates else ""


def _safe_path(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:120]


def _safe_mutation(value: str) -> ActionMutation:
    normalized = str(value or "").strip().lower()
    if normalized in {"read", "preview", "write", "apply", "admin"}:
        return normalized  # type: ignore[return-value]
    return "read"


def _safe_argument_keys(values: list[str]) -> list[str]:
    return list(safe_public_argument_keys(values[:50]))


def _argument_policy_metadata(
    *,
    provider_slug: str,
    action_slug: str,
    raw_arguments: dict[str, Any],
    safe_arguments: dict[str, Any],
) -> dict[str, Any]:
    raw_keys = tuple(raw_arguments.keys()) if isinstance(raw_arguments, dict) else ()
    accepted_keys = tuple(safe_arguments.keys()) if isinstance(safe_arguments, dict) else ()
    return {
        "version": "wiii_connect_argument_filter.v1",
        "provider_slug": _safe_surface(provider_slug),
        "action_slug": _safe_action_slug(action_slug),
        "provided_argument_count": len(raw_keys),
        "accepted_argument_count": len(accepted_keys),
        "accepted_argument_keys": sorted(safe_public_argument_keys(accepted_keys)),
        "hidden_argument_count": max(0, len(raw_keys) - len(accepted_keys)),
    }


def _missing_required_argument_keys(
    *,
    required_keys: tuple[str, ...],
    arguments: dict[str, Any],
) -> tuple[str, ...]:
    provided = {str(key or "").strip() for key in (arguments or {}).keys()}
    missing: list[str] = []
    for raw_key in required_keys:
        key = str(raw_key or "").strip()
        if not key or key in provided:
            continue
        safe_key = _safe_public_argument_key(key)
        if safe_key not in missing:
            missing.append(safe_key)
    return tuple(missing[:50])


def _safe_public_argument_key(value: str) -> str:
    return safe_public_argument_key(value)


def _safe_public_id(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if any(marker in text.lower() for marker in ("token", "secret", "password")):
        return None
    return text[:160]


def _request_id_from_http_request(request: Request) -> str | None:
    state_request_id = str(getattr(request.state, "request_id", "") or "").strip()
    if state_request_id:
        return state_request_id
    header_request_id = str(request.headers.get("X-Request-ID") or "").strip()
    return header_request_id or None


def _safe_surface(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text[:80] or "backend"
