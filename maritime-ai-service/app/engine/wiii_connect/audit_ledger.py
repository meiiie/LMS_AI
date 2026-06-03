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

from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text

from .argument_key_policy import safe_public_argument_key

WIII_CONNECT_AUDIT_LEDGER_VERSION = "wiii_connect_audit_ledger.v1"

AuditRecordKind = Literal["session", "callback", "vault", "execution", "provider"]

_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "bearer",
    "connection_id",
    "connection_ref",
    "credential",
    "external_account_ref",
    "page_id",
    "password",
    "provider_payload",
    "raw_provider",
    "secret",
    "token",
    "vault_ref",
)
_SAFE_STRUCTURAL_KEY_NAMES = frozenset(
    {
        "argument_keys",
        "required_argument_keys",
        "missing_argument_keys",
        "data_keys",
    },
)
_SAFE_PRESENCE_KEY_NAMES = frozenset(
    {
        "code_present",
        "connection_id_present",
        "connection_ref_present",
        "preview_evidence_present",
        "provider_connection_ref_present",
        "state_present",
        "vault_ref_present",
    }
)
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

    def __post_init__(self) -> None:
        safe_metadata = _sanitize_metadata(self.metadata)
        object.__setattr__(
            self,
            "metadata",
            dict(safe_metadata) if isinstance(safe_metadata, dict) else {},
        )

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_AUDIT_LEDGER_VERSION,
            "event_kind": _safe_public_token(self.event_kind),
            "provider_slug": _safe_public_token(self.provider_slug),
            "status": _safe_public_token(self.status),
            "reason": _safe_public_token(self.reason),
            "surface": _safe_public_token(self.surface),
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
            if _is_structural_key_name(key):
                sanitized[key] = _sanitize_structural_key_values(raw_value)
                continue
            sanitized[key] = _sanitize_metadata(raw_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        return redact_runtime_secret_text(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    if _is_structural_key_name(normalized):
        return False
    if normalized in _SAFE_PRESENCE_KEY_NAMES:
        return False
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _is_structural_key_name(key: str) -> bool:
    return key.strip().lower() in _SAFE_STRUCTURAL_KEY_NAMES


def _sanitize_structural_key_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        values = (value,)
    result: list[str] = []
    for item in values:
        safe_key = safe_public_argument_key(item)
        if safe_key not in result:
            result.append(safe_key)
        if len(result) >= 50:
            break
    return result


def _safe_public_token(value: Any, *, max_length: int = 120) -> str:
    text = redact_runtime_secret_text(value)
    text = " ".join(text.split())
    return text[:max_length]
