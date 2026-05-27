"""Privacy-safe Wiii Connect audit ledger contract.

The ledger contract normalizes audit records from registry/session/callback,
vault, and execution decisions. This module is intentionally storage-agnostic;
database persistence can be added behind this shape without changing public
metadata or agent-facing contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


WIII_CONNECT_AUDIT_LEDGER_VERSION = "wiii_connect_audit_ledger.v1"

AuditRecordKind = Literal["session", "callback", "vault", "execution", "provider"]

_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")
_REDACTED = "[redacted]"


@dataclass(frozen=True, slots=True)
class WiiiConnectAuditLedgerRecord:
    """One privacy-safe audit ledger record."""

    event_kind: AuditRecordKind
    provider_slug: str
    status: str
    reason: str
    surface: str = "backend"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_AUDIT_LEDGER_VERSION,
            "event_kind": self.event_kind,
            "provider_slug": self.provider_slug,
            "status": self.status,
            "reason": self.reason,
            "surface": self.surface,
            "created_at": self.created_at,
            "metadata": _sanitize_metadata(self.metadata),
        }


@dataclass(slots=True)
class WiiiConnectInMemoryAuditLedger:
    """Small storage-agnostic collector used by tests and future adapters."""

    records: list[WiiiConnectAuditLedgerRecord] = field(default_factory=list)

    def append(self, record: WiiiConnectAuditLedgerRecord) -> WiiiConnectAuditLedgerRecord:
        self.records.append(record)
        return record

    def recent_public_metadata(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(0, min(limit, 200))
        return [record.to_public_metadata() for record in self.records[-safe_limit:]]


def build_audit_ledger_record(
    *,
    event_kind: AuditRecordKind,
    provider_slug: str,
    status: str,
    reason: str,
    surface: str = "backend",
    metadata: dict[str, Any] | None = None,
) -> WiiiConnectAuditLedgerRecord:
    """Build a ledger record from already-sanitized or raw-ish metadata."""

    return WiiiConnectAuditLedgerRecord(
        event_kind=event_kind,
        provider_slug=provider_slug,
        status=status,
        reason=reason,
        surface=surface,
        metadata=metadata or {},
    )


def audit_ledger_status_public_metadata(
    *,
    persistent: bool = False,
    backend: str = "memory_contract",
) -> dict[str, Any]:
    """Return privacy-safe metadata describing current ledger readiness."""

    return {
        "version": WIII_CONNECT_AUDIT_LEDGER_VERSION,
        "enabled": True,
        "persistent": persistent,
        "backend": backend,
        "reason": "persistent_store_not_configured" if not persistent else "ready",
    }


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _is_sensitive_key(key):
                sanitized["redacted_sensitive_field"] = _REDACTED
                continue
            sanitized[key] = _sanitize_metadata(raw_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)
