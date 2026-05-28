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
    WiiiConnectExecutionRequest,
    WiiiConnectSessionStartRequest,
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
    build_wiii_connect_callback_state,
    begin_connection_session,
    create_composio_connect_link,
    decide_authorization_url,
    decide_execution_gateway,
    default_persistent_storage_status_metadata,
    disconnect_composio_connected_account,
    get_wiii_connect_provider_entry,
    get_wiii_connect_persistent_storage,
    execute_composio_tool,
    get_wiii_connect_curated_action,
    list_composio_connected_accounts,
    normalize_connection_state,
    provider_adapter_status_public_metadata,
    provider_callback_decision,
    provider_callback_decision_for_entry,
    provider_connection_status,
    provider_registry_public_metadata,
    scope_grant_from_mapping,
    verify_composio_tool_schema,
    verify_wiii_connect_callback_state,
    vault_status_public_metadata,
)
from app.engine.wiii_connect.adapter_v1 import ActionMutation


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


@router.get("/providers/{slug}/activation-readiness")
async def get_wiii_connect_provider_activation_readiness(
    slug: str,
    connection_id: str | None = None,
    action_slug: str = "GMAIL_FETCH_EMAILS",
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

    action = _safe_action_slug(action_slug)
    composio_config = build_composio_adapter_config()
    connect_entry = build_composio_connect_enabled_entry(entry, composio_config)
    execution_entry = build_composio_execution_enabled_entry(entry, composio_config)
    adapter_capability = build_composio_provider_adapter_capability(composio_config)
    vault_capability = build_composio_provider_managed_vault_capability(
        composio_config,
    )
    storage = _wiii_connect_storage_status_metadata(
        probe_database=probe_database,
    )
    storage_ready = _connection_storage_ready(storage)
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=execution_entry.slug,
            connection_id=_safe_provider_connection_id(connection_id),
        )
        if storage_ready
        else None
    )
    curated_action = get_wiii_connect_curated_action(execution_entry.slug, action)
    runtime_enabled_actions = (
        composio_config.readonly_action_slugs_for_provider(execution_entry.slug)
        if composio_config.readonly_execute_enabled
        else ()
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
    if not effective_entry.enabled or not adapter_capability.authorization_ready:
        return {
            "version": "wiii_connect_connection_list.v1",
            "status": "blocked",
            "reason": (
                "provider_disabled"
                if not effective_entry.enabled
                else adapter_capability.reason
            ),
            "provider_slug": effective_entry.slug,
            "provider_kind": effective_entry.provider_kind,
            "connection_count": 0,
            "connections": [],
            "provider": None,
            "storage": default_persistent_storage_status_metadata(),
        }

    provider_result = await list_composio_connected_accounts(
        config=composio_config,
        provider_slug=effective_entry.slug,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
    )
    storage = _wiii_connect_storage_status_metadata(
        probe_database=probe_database,
    )
    if provider_result.ready:
        _upsert_listed_connections(
            provider_result.connections,
            effective_entry,
            current_user=current_user,
            storage_metadata=storage,
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
        "provider": provider_result.to_public_metadata(),
        "storage": storage,
    }


@router.delete("/providers/{slug}/connections/{connection_id}")
async def disconnect_wiii_connect_provider_connection(
    slug: str,
    connection_id: str,
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
    safe_connection_id = _safe_provider_connection_id(connection_id)
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


@router.get("/providers/{slug}/actions")
async def list_wiii_connect_provider_actions(slug: str) -> dict[str, object]:
    """Return the privacy-safe curated action catalog for a provider."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    enabled_slugs = (
        composio_config.readonly_action_slugs_for_provider(entry.slug)
        if composio_config.readonly_execute_enabled
        else ()
    )
    return action_catalog_public_metadata(
        provider_slug=entry.slug,
        enabled_slugs=enabled_slugs,
    )


@router.post("/providers/{slug}/execution-decision")
async def decide_wiii_connect_provider_execution(
    slug: str,
    body: WiiiConnectExecutionDecisionBody,
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Return the audited fail-closed decision for one provider action.

    This endpoint is a gateway preflight only. It does not execute provider
    actions and it never accepts raw provider arguments, provider payloads, or
    approval token values.
    """

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    storage_ready = _connection_storage_ready(storage)
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=effective_entry.slug,
            connection_id=body.connection_id,
        )
        if storage_ready
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
    )
    _append_execution_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        metadata={
            "surface": body.surface,
            "connection_id_present": bool(body.connection_id),
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
    current_user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, object]:
    """Run one read-only provider action through Wiii policy and audit."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_wiii_connect_provider")
    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = _wiii_connect_storage_status_metadata(probe_database=True)
    storage_ready = _connection_storage_ready(storage)
    connection = (
        get_wiii_connect_persistent_storage().get_connection_record(
            organization_id=_wiii_connect_owner_organization_id(current_user),
            user_id=current_user.user_id,
            provider_slug=effective_entry.slug,
            connection_id=body.connection_id,
        )
        if storage_ready
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
        argument_keys=tuple(
            _safe_argument_keys(body.argument_keys or list(body.arguments.keys())),
        ),
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
    )
    audit_base = {
        "surface": body.surface,
        "connection_id_present": bool(body.connection_id),
        "connection_found": connection is not None,
        "storage": storage,
    }
    if not gateway.allowed or connection is None:
        _append_execution_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            metadata={**audit_base, "stage": "gateway"},
        )
        payload = gateway.to_public_metadata()
        payload["provider_slug"] = effective_entry.slug
        payload["storage"] = storage
        payload["schema"] = None
        payload["execution"] = None
        return payload

    schema = await verify_composio_tool_schema(
        config=composio_config,
        provider_slug=effective_entry.slug,
        action_slug=request.action_slug,
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
        payload = gateway.to_public_metadata()
        payload["status"] = "blocked"
        payload["reason"] = schema.reason
        payload["provider_slug"] = effective_entry.slug
        payload["storage"] = storage
        payload["schema"] = schema.to_public_metadata()
        payload["execution"] = None
        return payload

    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status="started",
        reason="provider_execution_started",
        metadata={
            **audit_base,
            "schema": schema.to_public_metadata(),
        },
    )
    execution = await execute_composio_tool(
        config=composio_config,
        provider_slug=effective_entry.slug,
        action_slug=request.action_slug,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
        connected_account_id=connection.connection_id,
        arguments=body.arguments,
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
            "schema": schema.to_public_metadata(),
            "execution": execution.to_public_metadata(),
        },
    )
    payload = gateway.to_public_metadata()
    payload["status"] = execution.status
    payload["reason"] = execution.reason
    payload["provider_slug"] = effective_entry.slug
    payload["storage"] = storage
    payload["schema"] = schema.to_public_metadata()
    payload["execution"] = execution.to_public_metadata()
    return payload


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
        storage.upsert_connection_record(
            connection,
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


def _safe_action_slug(value: str) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_path(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:120]


def _safe_mutation(value: str) -> ActionMutation:
    normalized = str(value or "").strip().lower()
    if normalized in {"read", "preview", "write", "apply", "admin"}:
        return normalized  # type: ignore[return-value]
    return "read"


def _safe_argument_keys(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values[:50]:
        key = str(value or "").strip()
        if key:
            result.append(key[:120])
    return result


def _safe_public_id(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if any(marker in text.lower() for marker in ("token", "secret", "password")):
        return None
    return text[:160]


def _safe_surface(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text[:80] or "backend"
