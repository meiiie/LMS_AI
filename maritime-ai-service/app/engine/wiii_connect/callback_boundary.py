"""Wiii Connect OAuth callback and vault boundary contract.

The real OAuth callback path must never exchange or store credentials until the
provider adapter and vault are explicitly ready. This module models that
decision without making network calls or persisting secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .adapter_v1 import WiiiConnectProviderRegistryEntry
from .provider_registry import get_wiii_connect_provider_entry
from .vault import WiiiConnectVaultCapability


WIII_CONNECT_CALLBACK_CONTRACT_VERSION = "wiii_connect_callback.v1"

CallbackDecisionStatus = Literal["blocked", "accepted"]
CallbackDecisionReason = Literal[
    "provider_disabled",
    "provider_error",
    "missing_state",
    "invalid_state",
    "missing_code",
    "missing_connection_ref",
    "vault_not_configured",
    "provider_adapter_not_bound",
    "accepted",
]

_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")


@dataclass(frozen=True, slots=True)
class WiiiConnectCallbackRequest:
    """Sanitized shape of an OAuth callback request."""

    provider_slug: str
    surface: str = "desktop"
    state_present: bool = False
    code_present: bool = False
    connection_ref_present: bool = False
    error_present: bool = False
    state_valid: bool = False
    request_metadata_keys: tuple[str, ...] = ()

    def to_audit_metadata(self) -> dict[str, Any]:
        return {
            "provider_slug": self.provider_slug,
            "surface": self.surface,
            "state_present": self.state_present,
            "code_present": self.code_present,
            "connection_ref_present": self.connection_ref_present,
            "error_present": self.error_present,
            "state_valid": self.state_valid,
            "request_metadata_keys": [
                _safe_metadata_key(key) for key in self.request_metadata_keys
            ],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectCallbackAuditEvent:
    """Privacy-safe audit event around a callback decision."""

    reason: CallbackDecisionReason
    request: WiiiConnectCallbackRequest
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_CALLBACK_CONTRACT_VERSION,
            "stage": "callback_received",
            "reason": self.reason,
            "created_at": self.created_at,
            "request": self.request.to_audit_metadata(),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectCallbackDecision:
    """Decision returned after an OAuth callback reaches Wiii."""

    status: CallbackDecisionStatus
    reason: CallbackDecisionReason
    provider_slug: str
    label: str
    provider_kind: str
    auth_mode: str
    vault_ref_issued: bool = False
    connection_ref: str = ""
    audit_event: WiiiConnectCallbackAuditEvent | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_CALLBACK_CONTRACT_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "label": self.label,
            "provider_kind": self.provider_kind,
            "auth_mode": self.auth_mode,
            "vault_ref_issued": self.vault_ref_issued,
            "connection_ref": self.connection_ref,
            "connection_ref_present": bool(self.connection_ref),
            "audit_event": (
                self.audit_event.to_metadata() if self.audit_event is not None else None
            ),
        }


def provider_callback_decision(
    slug: str,
    request: WiiiConnectCallbackRequest,
    *,
    vault_ready: bool = False,
    vault_capability: WiiiConnectVaultCapability | None = None,
    provider_adapter_bound: bool = False,
) -> WiiiConnectCallbackDecision | None:
    """Return a callback decision for a registry provider slug."""

    entry = get_wiii_connect_provider_entry(slug)
    if entry is None:
        return None
    return provider_callback_decision_for_entry(
        entry,
        request,
        vault_ready=vault_ready,
        vault_capability=vault_capability,
        provider_adapter_bound=provider_adapter_bound,
    )


def provider_callback_decision_for_entry(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectCallbackRequest,
    *,
    vault_ready: bool = False,
    vault_capability: WiiiConnectVaultCapability | None = None,
    provider_adapter_bound: bool = False,
) -> WiiiConnectCallbackDecision:
    """Decide whether a callback may be exchanged and persisted."""

    reason = _callback_reason(
        entry,
        request,
        vault_ready=_resolved_vault_ready(vault_ready, vault_capability),
        provider_adapter_bound=provider_adapter_bound,
    )
    status: CallbackDecisionStatus = "accepted" if reason == "accepted" else "blocked"
    audit_event = WiiiConnectCallbackAuditEvent(reason=reason, request=request)
    return WiiiConnectCallbackDecision(
        status=status,
        reason=reason,
        provider_slug=entry.slug,
        label=entry.label,
        provider_kind=entry.provider_kind,
        auth_mode=entry.auth_mode,
        vault_ref_issued=status == "accepted",
        connection_ref="pending_connection_ref" if status == "accepted" else "",
        audit_event=audit_event,
    )


def _callback_reason(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectCallbackRequest,
    *,
    vault_ready: bool,
    provider_adapter_bound: bool,
) -> CallbackDecisionReason:
    if not entry.enabled:
        return "provider_disabled"
    if not request.state_present:
        return "missing_state"
    if not request.state_valid:
        return "invalid_state"
    if request.error_present:
        return "provider_error"
    if not request.code_present and not request.connection_ref_present:
        return "missing_code"
    if not request.connection_ref_present:
        return "missing_connection_ref"
    if not vault_ready:
        return "vault_not_configured"
    if not provider_adapter_bound:
        return "provider_adapter_not_bound"
    return "accepted"


def _resolved_vault_ready(
    vault_ready: bool,
    vault_capability: WiiiConnectVaultCapability | None,
) -> bool:
    return bool(vault_ready or (vault_capability and vault_capability.can_store_external_secret))


def _safe_metadata_key(key: str) -> str:
    normalized = str(key).strip().lower()
    if not normalized:
        return "empty"
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_field"
    return normalized[:80]
