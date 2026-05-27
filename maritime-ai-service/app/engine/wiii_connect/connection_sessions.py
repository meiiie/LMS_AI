"""Wiii Connect connection-session control contract.

This module owns the provider authorization/session boundary before any real
OAuth broker, vault, or external execution adapter is allowed to run. It is
intentionally network-free and fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .adapter_v1 import (
    WiiiConnectProviderRegistryEntry,
    WiiiConnectScopeGrant,
)
from .provider_adapters import WiiiConnectAuthorizationUrlDecision
from .provider_registry import get_wiii_connect_provider_entry


WIII_CONNECT_SESSION_CONTRACT_VERSION = "wiii_connect_session.v1"

SessionDecisionStatus = Literal["blocked", "ready"]
SessionDecisionReason = Literal[
    "provider_disabled",
    "missing_connect_prerequisites",
    "provider_adapter_not_bound",
    "provider_adapter_mismatch",
    "provider_adapter_not_configured",
    "provider_adapter_cannot_authorize",
    "missing_state",
    "missing_redirect_uri",
    "vault_not_configured",
    "audit_ledger_not_persistent",
    "authorization_url_missing",
    "authorization_url_issued",
]
SessionAuditStage = Literal["status_checked", "start_requested"]

_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")


@dataclass(frozen=True, slots=True)
class WiiiConnectSessionStartRequest:
    """User request to begin a provider authorization session.

    The request deliberately stores only safe control-plane metadata. Raw
    request/provider values must not enter chat lifecycle or public API output.
    """

    provider_slug: str
    surface: str = "desktop"
    requested_scopes: WiiiConnectScopeGrant = field(default_factory=WiiiConnectScopeGrant)
    redirect_uri_present: bool = False
    request_metadata_keys: tuple[str, ...] = ()

    def to_audit_metadata(self) -> dict[str, Any]:
        return {
            "provider_slug": self.provider_slug,
            "surface": self.surface,
            "requested_scopes": self.requested_scopes.to_metadata(),
            "redirect_uri_present": self.redirect_uri_present,
            "request_metadata_keys": [
                _safe_metadata_key(key) for key in self.request_metadata_keys
            ],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectConnectionSessionAuditEvent:
    """Privacy-safe audit event for connection-session control-plane decisions."""

    stage: SessionAuditStage
    reason: SessionDecisionReason
    request: WiiiConnectSessionStartRequest
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_SESSION_CONTRACT_VERSION,
            "stage": self.stage,
            "reason": self.reason,
            "created_at": self.created_at,
            "request": self.request.to_audit_metadata(),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectProviderConnectionStatus:
    """Provider authorization readiness projected to UI/API surfaces."""

    provider_slug: str
    label: str
    provider_kind: str
    auth_mode: str
    enabled: bool
    agent_ready: bool
    can_start_authorization: bool
    reason: SessionDecisionReason
    missing_requirements: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_SESSION_CONTRACT_VERSION,
            "provider_slug": self.provider_slug,
            "label": self.label,
            "provider_kind": self.provider_kind,
            "auth_mode": self.auth_mode,
            "enabled": self.enabled,
            "agent_ready": self.agent_ready,
            "can_start_authorization": self.can_start_authorization,
            "reason": self.reason,
            "missing_requirements": list(self.missing_requirements),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectSessionStartDecision:
    """Decision returned after a session-start attempt."""

    status: SessionDecisionStatus
    reason: SessionDecisionReason
    provider_slug: str
    label: str
    provider_kind: str
    auth_mode: str
    authorization_url: str = ""
    required_next: tuple[str, ...] = ()
    audit_event: WiiiConnectConnectionSessionAuditEvent | None = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_SESSION_CONTRACT_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "label": self.label,
            "provider_kind": self.provider_kind,
            "auth_mode": self.auth_mode,
            "authorization_url": self.authorization_url,
            "required_next": list(self.required_next),
            "audit_event": (
                self.audit_event.to_metadata() if self.audit_event is not None else None
            ),
        }


def provider_connection_status(
    slug: str,
) -> WiiiConnectProviderConnectionStatus | None:
    """Return the current authorization-readiness status for a provider."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        return None
    return provider_connection_status_for_entry(entry)


def provider_connection_status_for_entry(
    entry: WiiiConnectProviderRegistryEntry,
) -> WiiiConnectProviderConnectionStatus:
    """Project one registry entry into connection-session readiness metadata."""

    missing_requirements = entry.connection_requirements()
    reason = _session_block_reason(entry, missing_requirements)
    if reason == "authorization_url_issued":
        reason = "provider_adapter_not_bound"
    can_start = False
    return WiiiConnectProviderConnectionStatus(
        provider_slug=entry.slug,
        label=entry.label,
        provider_kind=entry.provider_kind,
        auth_mode=entry.auth_mode,
        enabled=entry.enabled,
        agent_ready=entry.agent_ready,
        can_start_authorization=can_start,
        reason=reason,
        missing_requirements=missing_requirements,
        warnings=entry.warnings,
    )


def begin_connection_session(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectSessionStartRequest,
    *,
    authorization_decision: WiiiConnectAuthorizationUrlDecision | None = None,
    authorization_url: str | None = None,
) -> WiiiConnectSessionStartDecision:
    """Decide whether Wiii may start provider authorization for this request."""

    missing_requirements = entry.connection_requirements()
    reason = _session_block_reason(entry, missing_requirements)
    required_next = missing_requirements
    session_authorization_url = ""

    if reason == "authorization_url_issued":
        if authorization_decision is None:
            reason = "provider_adapter_not_bound"
            required_next = ("bind_provider_adapter",)
        elif not authorization_decision.ready:
            reason = _session_reason_from_authorization_decision(
                authorization_decision
            )
            required_next = tuple(authorization_decision.required_next)
        else:
            session_authorization_url = authorization_decision.authorization_url
            if not session_authorization_url:
                reason = "authorization_url_missing"
                required_next = ("adapter_return_authorization_url",)

    status: SessionDecisionStatus = (
        "ready"
        if reason == "authorization_url_issued" and session_authorization_url
        else "blocked"
    )
    audit_event = WiiiConnectConnectionSessionAuditEvent(
        stage="start_requested",
        reason=reason,
        request=request,
    )
    return WiiiConnectSessionStartDecision(
        status=status,
        reason=reason,
        provider_slug=entry.slug,
        label=entry.label,
        provider_kind=entry.provider_kind,
        auth_mode=entry.auth_mode,
        authorization_url=session_authorization_url if status == "ready" else "",
        required_next=required_next,
        audit_event=audit_event,
    )


def scope_grant_from_mapping(value: dict[str, Any] | None) -> WiiiConnectScopeGrant:
    """Normalize user-requested scopes and ignore unknown fields."""

    scopes = value or {}
    return WiiiConnectScopeGrant(
        read=bool(scopes.get("read", False)),
        preview=bool(scopes.get("preview", False)),
        write=bool(scopes.get("write", False)),
        apply=bool(scopes.get("apply", False)),
        admin=bool(scopes.get("admin", False)),
    )


def _session_block_reason(
    entry: WiiiConnectProviderRegistryEntry,
    missing_requirements: tuple[str, ...],
) -> SessionDecisionReason:
    if not entry.enabled:
        return "provider_disabled"
    if missing_requirements:
        return "missing_connect_prerequisites"
    return "authorization_url_issued"


def _session_reason_from_authorization_decision(
    decision: WiiiConnectAuthorizationUrlDecision,
) -> SessionDecisionReason:
    if decision.reason in {
        "provider_disabled",
        "provider_adapter_mismatch",
        "provider_adapter_not_bound",
        "provider_adapter_not_configured",
        "provider_adapter_cannot_authorize",
        "missing_state",
        "missing_redirect_uri",
        "vault_not_configured",
        "audit_ledger_not_persistent",
        "authorization_url_missing",
    }:
        return decision.reason
    return "provider_adapter_not_bound"


def _safe_metadata_key(key: str) -> str:
    normalized = str(key).strip().lower()
    if not normalized:
        return "empty"
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_field"
    return normalized[:80]
