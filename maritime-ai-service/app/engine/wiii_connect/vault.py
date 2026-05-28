"""Wiii Connect vault policy and secret-write decision contract.

This module is the safety boundary between OAuth/provider callbacks and any
credential storage. It does not persist secrets. It decides whether a future
vault adapter is allowed to store secret material and returns only opaque vault
references in public metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .adapter_v1 import (
    WiiiConnectProviderRegistryEntry,
    WiiiConnectVaultSecretRef,
)


WIII_CONNECT_VAULT_CONTRACT_VERSION = "wiii_connect_vault.v1"

VaultBackendKind = Literal["disabled", "provider_managed", "external_kms"]
VaultDecisionStatus = Literal["blocked", "ready"]
VaultDecisionReason = Literal[
    "vault_disabled",
    "provider_disabled",
    "missing_secret_material",
    "unsupported_secret_kind",
    "secret_material_not_accepted",
    "ready_to_store",
]
SecretKind = Literal["oauth_token", "api_key", "provider_session", "webhook_secret"]

_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")
_SUPPORTED_SECRET_KINDS: tuple[SecretKind, ...] = (
    "oauth_token",
    "api_key",
    "provider_session",
    "webhook_secret",
)


@dataclass(frozen=True, slots=True)
class WiiiConnectVaultCapability:
    """Runtime capability of the configured vault backend."""

    enabled: bool = False
    backend: VaultBackendKind = "disabled"
    accepts_secret_material: bool = False
    provider_managed: bool = False
    key_namespace: str = ""
    reason: str = "vault_disabled"
    warnings: tuple[str, ...] = ()

    @property
    def can_store_external_secret(self) -> bool:
        return bool(self.enabled and self.accepts_secret_material)

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_VAULT_CONTRACT_VERSION,
            "enabled": self.enabled,
            "backend": self.backend,
            "provider_managed": self.provider_managed,
            "can_store_external_secret": self.can_store_external_secret,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectVaultSecretWriteRequest:
    """Sanitized request to store provider credential material."""

    provider_slug: str
    connection_id: str
    secret_kind: str
    secret_material_present: bool = False
    metadata_keys: tuple[str, ...] = ()

    def to_audit_metadata(self) -> dict[str, Any]:
        return {
            "provider_slug": self.provider_slug,
            "connection_ref_present": bool(self.connection_id),
            "secret_kind": self.secret_kind,
            "secret_material_present": self.secret_material_present,
            "metadata_keys": [_safe_metadata_key(key) for key in self.metadata_keys],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectVaultAuditEvent:
    """Privacy-safe audit event for a vault decision."""

    reason: VaultDecisionReason
    request: WiiiConnectVaultSecretWriteRequest
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_VAULT_CONTRACT_VERSION,
            "stage": "vault_write_decided",
            "reason": self.reason,
            "created_at": self.created_at,
            "request": self.request.to_audit_metadata(),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectVaultSecretWriteDecision:
    """Decision returned before secret material can enter a vault adapter."""

    status: VaultDecisionStatus
    reason: VaultDecisionReason
    provider_slug: str
    connection_id: str
    secret_kind: str
    vault_ref: WiiiConnectVaultSecretRef | None = None
    audit_event: WiiiConnectVaultAuditEvent | None = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_VAULT_CONTRACT_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "connection_ref_present": bool(self.connection_id),
            "secret_kind": self.secret_kind,
            "vault_ref": (
                self.vault_ref.to_public_metadata() if self.vault_ref is not None else None
            ),
            "audit_event": (
                self.audit_event.to_metadata() if self.audit_event is not None else None
            ),
        }


def default_wiii_connect_vault_capability() -> WiiiConnectVaultCapability:
    """Return the default fail-closed vault capability."""

    return WiiiConnectVaultCapability(
        enabled=False,
        backend="disabled",
        accepts_secret_material=False,
        provider_managed=False,
        reason="vault_disabled",
    )


def decide_vault_secret_write(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectVaultSecretWriteRequest,
    capability: WiiiConnectVaultCapability | None = None,
) -> WiiiConnectVaultSecretWriteDecision:
    """Decide whether a provider secret can be stored by Wiii Connect."""

    capability = capability or default_wiii_connect_vault_capability()
    reason = _vault_decision_reason(entry, request, capability)
    status: VaultDecisionStatus = "ready" if reason == "ready_to_store" else "blocked"
    vault_ref = (
        _build_vault_ref(entry, request, capability)
        if status == "ready"
        else None
    )
    audit_event = WiiiConnectVaultAuditEvent(reason=reason, request=request)
    return WiiiConnectVaultSecretWriteDecision(
        status=status,
        reason=reason,
        provider_slug=entry.slug,
        connection_id=request.connection_id,
        secret_kind=request.secret_kind,
        vault_ref=vault_ref,
        audit_event=audit_event,
    )


def vault_status_public_metadata(
    capability: WiiiConnectVaultCapability | None = None,
) -> dict[str, Any]:
    """Return privacy-safe vault readiness metadata for UI/API."""

    return (capability or default_wiii_connect_vault_capability()).to_public_metadata()


def _vault_decision_reason(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectVaultSecretWriteRequest,
    capability: WiiiConnectVaultCapability,
) -> VaultDecisionReason:
    if not entry.enabled:
        return "provider_disabled"
    if not capability.enabled:
        return "vault_disabled"
    if request.secret_kind not in _SUPPORTED_SECRET_KINDS:
        return "unsupported_secret_kind"
    if not request.secret_material_present:
        return "missing_secret_material"
    if not capability.accepts_secret_material:
        return "secret_material_not_accepted"
    return "ready_to_store"


def _build_vault_ref(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectVaultSecretWriteRequest,
    capability: WiiiConnectVaultCapability,
) -> WiiiConnectVaultSecretRef:
    namespace = capability.key_namespace or "wiii_connect"
    vault_key_id = (
        f"{namespace}/{entry.provider_kind}/{entry.slug}/{request.connection_id}/"
        f"{request.secret_kind}"
    )
    return WiiiConnectVaultSecretRef(
        provider_slug=entry.slug,
        connection_id=request.connection_id,
        vault_key_id=vault_key_id,
        secret_version="pending",
    )


def _safe_metadata_key(key: str) -> str:
    normalized = str(key).strip().lower()
    if not normalized:
        return "empty"
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_field"
    return normalized[:80]
