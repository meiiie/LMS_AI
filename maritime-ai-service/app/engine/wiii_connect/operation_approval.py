"""Operation approval ledger contract for Wiii Connect mutations.

Preview/apply tokens prove that a request matches a preview, but an autonomous
operator also needs a backend replay ledger. This module records only hashes and
presence flags so approval state can be audited without storing post text,
provider account IDs, page IDs, media, or approval tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any, Literal


WIII_CONNECT_OPERATION_APPROVAL_VERSION = "wiii_connect_operation_approval.v1"

OperationApprovalStatus = Literal[
    "pending",
    "consumed",
    "expired",
    "unavailable",
    "blocked",
]
OperationApprovalReason = Literal[
    "preview_recorded",
    "approval_consumed",
    "approval_ledger_not_persistent",
    "approval_record_missing",
    "approval_record_expired",
    "approval_record_already_consumed",
    "approval_fingerprint_mismatch",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class WiiiConnectOperationApprovalRecord:
    """Privacy-safe persisted approval row."""

    preview_evidence_id: str
    provider_slug: str
    action_slug: str
    request_fingerprint: str
    status: OperationApprovalStatus = "pending"
    reason: OperationApprovalReason = "preview_recorded"
    issued_at: str = field(default_factory=_now_iso)
    expires_at: str = ""
    consumed_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_OPERATION_APPROVAL_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": _provider_slug(self.provider_slug),
            "action_slug": _action_slug(self.action_slug),
            "preview_evidence_id_present": bool(self.preview_evidence_id),
            "request_fingerprint_present": bool(self.request_fingerprint),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "consumed_at_present": bool(self.consumed_at),
            "metadata": _safe_metadata(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectOperationApprovalDecision:
    """Result of recording or consuming a mutation approval row."""

    status: OperationApprovalStatus
    reason: OperationApprovalReason
    provider_slug: str = ""
    action_slug: str = ""
    preview_evidence_id_present: bool = False
    request_fingerprint_present: bool = False
    persistent: bool = False
    consumed: bool = False
    blocked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_OPERATION_APPROVAL_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": _provider_slug(self.provider_slug),
            "action_slug": _action_slug(self.action_slug),
            "preview_evidence_id_present": self.preview_evidence_id_present,
            "request_fingerprint_present": self.request_fingerprint_present,
            "persistent": self.persistent,
            "consumed": self.consumed,
            "blocked": self.blocked,
            "metadata": _safe_metadata(self.metadata),
        }


def build_wiii_connect_operation_approval_record(
    *,
    provider_slug: str,
    action_slug: str,
    preview_evidence_id: str,
    request_fingerprint: str,
    ttl_seconds: int,
    metadata: dict[str, Any] | None = None,
    issued_at: datetime | None = None,
) -> WiiiConnectOperationApprovalRecord:
    """Build a pending approval row from sanitized request fingerprints."""

    issued = issued_at or datetime.now(UTC)
    expires = issued + timedelta(seconds=max(60, int(ttl_seconds or 0)))
    return WiiiConnectOperationApprovalRecord(
        preview_evidence_id=_safe_public_id(preview_evidence_id),
        provider_slug=_provider_slug(provider_slug),
        action_slug=_action_slug(action_slug),
        request_fingerprint=_safe_fingerprint(request_fingerprint),
        issued_at=issued.isoformat(),
        expires_at=expires.isoformat(),
        metadata=metadata or {},
    )


def build_wiii_connect_operation_fingerprint(
    *,
    provider_slug: str,
    action_slug: str,
    connection_ref: str,
    page_id: str,
    message: str,
    image_sha256: str = "",
    image_url: str = "",
) -> str:
    """Return a stable hash for preview/apply equality without raw values."""

    payload = {
        "provider_slug": _provider_slug(provider_slug),
        "action_slug": _action_slug(action_slug),
        "connection_ref_hash": _sha256_text(_safe_connection_ref(connection_ref)),
        "page_id_hash": _sha256_text(_safe_public_id(page_id)),
        "message_hash": _sha256_text(message),
        "image_hash": _safe_fingerprint(image_sha256),
        "image_url_hash": _sha256_text(_safe_url(image_url)),
    }
    return _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def unavailable_operation_approval_decision(
    *,
    provider_slug: str,
    action_slug: str,
    preview_evidence_id: str = "",
    request_fingerprint: str = "",
    reason: OperationApprovalReason = "approval_ledger_not_persistent",
) -> WiiiConnectOperationApprovalDecision:
    return WiiiConnectOperationApprovalDecision(
        status="unavailable",
        reason=reason,
        provider_slug=provider_slug,
        action_slug=action_slug,
        preview_evidence_id_present=bool(preview_evidence_id),
        request_fingerprint_present=bool(request_fingerprint),
        persistent=False,
    )


def consumed_operation_approval_decision(
    *,
    provider_slug: str,
    action_slug: str,
    preview_evidence_id: str,
    request_fingerprint: str,
) -> WiiiConnectOperationApprovalDecision:
    return WiiiConnectOperationApprovalDecision(
        status="consumed",
        reason="approval_consumed",
        provider_slug=provider_slug,
        action_slug=action_slug,
        preview_evidence_id_present=bool(preview_evidence_id),
        request_fingerprint_present=bool(request_fingerprint),
        persistent=True,
        consumed=True,
    )


def blocked_operation_approval_decision(
    *,
    provider_slug: str,
    action_slug: str,
    preview_evidence_id: str,
    request_fingerprint: str,
    reason: OperationApprovalReason,
) -> WiiiConnectOperationApprovalDecision:
    return WiiiConnectOperationApprovalDecision(
        status="blocked",
        reason=reason,
        provider_slug=provider_slug,
        action_slug=action_slug,
        preview_evidence_id_present=bool(preview_evidence_id),
        request_fingerprint_present=bool(request_fingerprint),
        persistent=True,
        blocked=True,
    )


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "selected_connection_present",
        "page_selected",
        "message_length",
        "image_present",
        "image_size_bytes",
        "image_url_present",
    }
    return {
        key: raw_value
        for key, raw_value in value.items()
        if key in allowed_keys
        and (raw_value is None or isinstance(raw_value, (str, int, float, bool)))
    }


def _provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_public_id(value: Any) -> str:
    text = str(value or "").strip()
    if any(marker in text.lower() for marker in ("token", "secret", "password")):
        return ""
    return text[:180]


def _safe_connection_ref(value: Any) -> str:
    text = _safe_public_id(value)
    return text if text.startswith("wcn_") else ""


def _safe_url(value: Any) -> str:
    text = str(value or "").strip()
    return text[:2000] if text.startswith("https://") else ""


def _safe_fingerprint(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 64 and all(char in "0123456789abcdef" for char in text):
        return text
    return ""


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


__all__ = [
    "WIII_CONNECT_OPERATION_APPROVAL_VERSION",
    "WiiiConnectOperationApprovalDecision",
    "WiiiConnectOperationApprovalRecord",
    "blocked_operation_approval_decision",
    "build_wiii_connect_operation_approval_record",
    "build_wiii_connect_operation_fingerprint",
    "consumed_operation_approval_decision",
    "unavailable_operation_approval_decision",
]
