"""Wiii Connect provider adapter contract.

Provider adapters are the only layer allowed to turn a Wiii registry entry into
an external authorization URL, callback exchange, or action execution. This
module intentionally performs no network calls and defaults every adapter to an
unbound, fail-closed state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Literal

from .adapter_v1 import (
    ProviderKind,
    WiiiConnectProviderRegistryEntry,
    WiiiConnectScopeGrant,
)
from .audit_ledger import audit_ledger_status_public_metadata
from .vault import (
    WiiiConnectVaultCapability,
    default_wiii_connect_vault_capability,
)


WIII_CONNECT_PROVIDER_ADAPTER_VERSION = "wiii_connect_provider_adapter.v1"

AdapterDecisionStatus = Literal["blocked", "ready"]
AdapterDecisionReason = Literal[
    "provider_disabled",
    "missing_state",
    "missing_redirect_uri",
    "provider_adapter_mismatch",
    "provider_adapter_not_bound",
    "provider_adapter_not_configured",
    "provider_adapter_cannot_authorize",
    "vault_not_configured",
    "audit_ledger_not_persistent",
    "authorization_url_missing",
    "authorization_url_issued",
]

_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")
_DEFAULT_PROVIDER_KINDS: tuple[ProviderKind, ...] = (
    "composio",
    "custom_oauth",
    "mcp",
    "workflow",
)


@dataclass(frozen=True, slots=True)
class WiiiConnectProviderAdapterCapability:
    """Runtime capability for one external provider adapter implementation."""

    provider_kind: ProviderKind
    adapter_name: str = ""
    bound: bool = False
    configured: bool = False
    can_create_authorization_url: bool = False
    can_exchange_callback: bool = False
    can_execute_actions: bool = False
    reason: str = "provider_adapter_not_bound"
    warnings: tuple[str, ...] = ()

    @property
    def authorization_ready(self) -> bool:
        return bool(
            self.bound and self.configured and self.can_create_authorization_url
        )

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_PROVIDER_ADAPTER_VERSION,
            "provider_kind": self.provider_kind,
            "adapter_name": self.adapter_name or f"{self.provider_kind}_adapter",
            "bound": self.bound,
            "configured": self.configured,
            "can_create_authorization_url": self.can_create_authorization_url,
            "can_exchange_callback": self.can_exchange_callback,
            "can_execute_actions": self.can_execute_actions,
            "authorization_ready": self.authorization_ready,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectAuthorizationUrlRequest:
    """Sanitized request shape for issuing a provider authorization URL."""

    provider_slug: str
    surface: str = "desktop"
    requested_scopes: WiiiConnectScopeGrant = field(default_factory=WiiiConnectScopeGrant)
    state_present: bool = False
    redirect_uri_present: bool = False
    request_metadata_keys: tuple[str, ...] = ()

    def to_audit_metadata(self) -> dict[str, Any]:
        return {
            "provider_slug": self.provider_slug,
            "surface": self.surface,
            "requested_scopes": self.requested_scopes.to_metadata(),
            "state_present": self.state_present,
            "redirect_uri_present": self.redirect_uri_present,
            "request_metadata_keys": [
                _safe_metadata_key(key) for key in self.request_metadata_keys
            ],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectAuthorizationUrlAuditEvent:
    """Privacy-safe audit event around authorization URL decisions."""

    reason: AdapterDecisionReason
    request: WiiiConnectAuthorizationUrlRequest
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_PROVIDER_ADAPTER_VERSION,
            "stage": "authorization_url_decided",
            "reason": self.reason,
            "created_at": self.created_at,
            "request": self.request.to_audit_metadata(),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectAuthorizationUrlDecision:
    """Decision returned before UI may navigate to a provider connect URL."""

    status: AdapterDecisionStatus
    reason: AdapterDecisionReason
    provider_slug: str
    label: str
    provider_kind: ProviderKind
    auth_mode: str
    authorization_url: str = ""
    adapter: WiiiConnectProviderAdapterCapability | None = None
    required_next: tuple[str, ...] = ()
    audit_event: WiiiConnectAuthorizationUrlAuditEvent | None = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_PROVIDER_ADAPTER_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "label": self.label,
            "provider_kind": self.provider_kind,
            "auth_mode": self.auth_mode,
            "authorization_url": self.authorization_url if self.ready else "",
            "adapter": (
                self.adapter.to_public_metadata() if self.adapter is not None else None
            ),
            "required_next": list(self.required_next),
            "audit_event": (
                self.audit_event.to_metadata() if self.audit_event is not None else None
            ),
        }


def default_provider_adapter_capability(
    provider_kind: ProviderKind = "composio",
) -> WiiiConnectProviderAdapterCapability:
    """Return the default unbound adapter capability for a provider kind."""

    return WiiiConnectProviderAdapterCapability(
        provider_kind=provider_kind,
        adapter_name=f"{provider_kind}_adapter",
        bound=False,
        configured=False,
        can_create_authorization_url=False,
        can_exchange_callback=False,
        can_execute_actions=False,
        reason="provider_adapter_not_bound",
    )


def provider_adapter_status_public_metadata(
    provider_kinds: Iterable[ProviderKind] | None = None,
    adapter_capabilities: Iterable[WiiiConnectProviderAdapterCapability] | None = None,
) -> dict[str, Any]:
    """Return privacy-safe adapter readiness metadata for UI/API."""

    kinds = tuple(provider_kinds or _DEFAULT_PROVIDER_KINDS)
    overrides = {
        capability.provider_kind: capability
        for capability in (adapter_capabilities or ())
    }
    return {
        "version": WIII_CONNECT_PROVIDER_ADAPTER_VERSION,
        "adapters": [
            overrides.get(kind, default_provider_adapter_capability(kind)).to_public_metadata()
            for kind in kinds
        ],
    }


def decide_authorization_url(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectAuthorizationUrlRequest,
    *,
    adapter_capability: WiiiConnectProviderAdapterCapability | None = None,
    vault_capability: WiiiConnectVaultCapability | None = None,
    audit_ledger_metadata: dict[str, Any] | None = None,
    authorization_url: str | None = None,
    require_persistent_audit: bool = True,
) -> WiiiConnectAuthorizationUrlDecision:
    """Decide whether a provider adapter may issue an authorization URL."""

    adapter = adapter_capability or default_provider_adapter_capability(
        entry.provider_kind
    )
    vault = vault_capability or default_wiii_connect_vault_capability()
    ledger = audit_ledger_metadata or audit_ledger_status_public_metadata()
    reason = _authorization_reason(
        entry,
        request,
        adapter=adapter,
        vault=vault,
        audit_ledger_metadata=ledger,
        authorization_url=authorization_url,
        require_persistent_audit=require_persistent_audit,
    )
    status: AdapterDecisionStatus = (
        "ready" if reason == "authorization_url_issued" else "blocked"
    )
    audit_event = WiiiConnectAuthorizationUrlAuditEvent(
        reason=reason,
        request=request,
    )
    return WiiiConnectAuthorizationUrlDecision(
        status=status,
        reason=reason,
        provider_slug=entry.slug,
        label=entry.label,
        provider_kind=entry.provider_kind,
        auth_mode=entry.auth_mode,
        authorization_url=(authorization_url or "") if status == "ready" else "",
        adapter=adapter,
        required_next=_required_next_for_reason(reason),
        audit_event=audit_event,
    )


def _authorization_reason(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectAuthorizationUrlRequest,
    *,
    adapter: WiiiConnectProviderAdapterCapability,
    vault: WiiiConnectVaultCapability,
    audit_ledger_metadata: dict[str, Any],
    authorization_url: str | None,
    require_persistent_audit: bool,
) -> AdapterDecisionReason:
    if not entry.enabled:
        return "provider_disabled"
    if not request.state_present:
        return "missing_state"
    if not request.redirect_uri_present:
        return "missing_redirect_uri"
    if adapter.provider_kind != entry.provider_kind:
        return "provider_adapter_mismatch"
    if not adapter.bound:
        return "provider_adapter_not_bound"
    if not adapter.configured:
        return "provider_adapter_not_configured"
    if not adapter.can_create_authorization_url:
        return "provider_adapter_cannot_authorize"
    if not vault.can_store_external_secret:
        return "vault_not_configured"
    if require_persistent_audit and not bool(audit_ledger_metadata.get("persistent")):
        return "audit_ledger_not_persistent"
    if not authorization_url:
        return "authorization_url_missing"
    return "authorization_url_issued"


def _required_next_for_reason(reason: AdapterDecisionReason) -> tuple[str, ...]:
    if reason == "provider_disabled":
        return ("enable_provider_registry_entry",)
    if reason == "missing_state":
        return ("create_backend_state_nonce",)
    if reason == "missing_redirect_uri":
        return ("bind_backend_redirect_uri",)
    if reason == "provider_adapter_mismatch":
        return ("bind_matching_provider_adapter",)
    if reason == "provider_adapter_not_bound":
        return ("bind_provider_adapter",)
    if reason == "provider_adapter_not_configured":
        return ("configure_provider_adapter",)
    if reason == "provider_adapter_cannot_authorize":
        return ("implement_authorization_url_provider",)
    if reason == "vault_not_configured":
        return ("configure_vault",)
    if reason == "audit_ledger_not_persistent":
        return ("configure_persistent_audit_ledger",)
    if reason == "authorization_url_missing":
        return ("adapter_return_authorization_url",)
    return ()


def _safe_metadata_key(key: str) -> str:
    normalized = str(key).strip().lower()
    if not normalized:
        return "empty"
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_field"
    return normalized[:80]
