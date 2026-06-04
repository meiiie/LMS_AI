"""Durable Wiii Connect connection and audit storage adapter.

The adapter stores only privacy-safe control-plane metadata. It does not store
OAuth codes, access tokens, refresh tokens, API keys, provider payloads, or raw
vault paths.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import text

from .adapter_v1 import (
    WiiiConnectConnectionRecordV1,
    WiiiConnectScopeGrant,
    WiiiConnectVaultSecretRef,
    normalize_connection_state,
)
from .audit_ledger import WiiiConnectAuditLedgerRecord
from .operation_approval import (
    WiiiConnectOperationApprovalDecision,
    WiiiConnectOperationApprovalRecord,
    blocked_operation_approval_decision,
    consumed_operation_approval_decision,
    unavailable_operation_approval_decision,
)


logger = logging.getLogger(__name__)

WIII_CONNECT_PERSISTENT_STORAGE_VERSION = "wiii_connect_persistent_storage.v1"
DEFAULT_STALE_PENDING_CONNECTION_TTL_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class WiiiConnectPersistentStorageStatus:
    """Readiness of the durable Wiii Connect storage boundary."""

    enabled: bool = False
    persistent: bool = False
    backend: str = "postgres"
    connection_table_ready: bool = False
    audit_ledger_ready: bool = False
    operation_approval_table_ready: bool = False
    reason: str = "database_probe_not_requested"
    warnings: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_PERSISTENT_STORAGE_VERSION,
            "enabled": self.enabled,
            "persistent": self.persistent,
            "backend": self.backend,
            "connection_table_ready": self.connection_table_ready,
            "audit_ledger_ready": self.audit_ledger_ready,
            "operation_approval_table_ready": self.operation_approval_table_ready,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


class WiiiConnectPersistentStorage:
    """Small repository for Wiii Connect durable control-plane records."""

    CONNECTIONS_TABLE = "wiii_connect_connections"
    AUDIT_TABLE = "wiii_connect_audit_ledger"
    OPERATION_APPROVALS_TABLE = "wiii_connect_operation_approvals"

    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory
        self._initialized = session_factory is not None

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            from app.core.database import get_shared_session_factory

            self._session_factory = get_shared_session_factory()
            self._initialized = True
        except Exception as exc:
            logger.warning("Wiii Connect storage init failed: %s", exc)

    def status(self, *, probe_database: bool = True) -> WiiiConnectPersistentStorageStatus:
        """Return storage status without raising on DB/migration failures."""

        if not probe_database:
            return WiiiConnectPersistentStorageStatus()
        self._ensure_initialized()
        if self._session_factory is None:
            return WiiiConnectPersistentStorageStatus(
                reason="database_unavailable",
                warnings=("session_factory_unavailable",),
            )

        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(
                        "SELECT to_regclass(:connections_table), "
                        "to_regclass(:audit_table), "
                        "to_regclass(:operation_approvals_table)"
                    ),
                    {
                        "connections_table": self.CONNECTIONS_TABLE,
                        "audit_table": self.AUDIT_TABLE,
                        "operation_approvals_table": self.OPERATION_APPROVALS_TABLE,
                    },
                ).fetchone()
        except Exception as exc:
            logger.warning("Wiii Connect storage status check failed: %s", exc)
            return WiiiConnectPersistentStorageStatus(
                reason="database_unavailable",
                warnings=("status_probe_failed",),
            )

        connection_ready = bool(row and _row_index_value(row, 0))
        audit_ready = bool(row and _row_index_value(row, 1))
        operation_approval_ready = bool(row and _row_index_value(row, 2))
        ready = connection_ready and audit_ready
        warnings: tuple[str, ...] = ()
        if ready and not operation_approval_ready:
            warnings = ("operation_approval_table_missing",)
        return WiiiConnectPersistentStorageStatus(
            enabled=ready,
            persistent=ready,
            connection_table_ready=connection_ready,
            audit_ledger_ready=audit_ready,
            operation_approval_table_ready=operation_approval_ready,
            reason="ready" if ready else "migration_not_applied",
            warnings=warnings,
        )

    def append_audit_record(
        self,
        record: WiiiConnectAuditLedgerRecord,
        *,
        organization_id: str,
        user_id: str,
    ) -> bool:
        """Append one sanitized audit record for a user/org boundary."""

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        if owner is None:
            return False
        payload = record.to_public_metadata()
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        self._ensure_initialized()
        if self._session_factory is None:
            return False

        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        f"INSERT INTO {self.AUDIT_TABLE} "
                        f"(organization_id, user_id, provider_slug, event_kind, "
                        f"status, reason, surface, metadata, created_at) "
                        f"VALUES (:organization_id, :user_id, :provider_slug, "
                        f":event_kind, :status, :reason, :surface, "
                        f"CAST(:metadata AS jsonb), :created_at)"
                    ),
                    {
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": payload["provider_slug"],
                        "event_kind": payload["event_kind"],
                        "status": payload["status"],
                        "reason": payload["reason"],
                        "surface": payload["surface"],
                        "metadata": _json_dumps(metadata),
                        "created_at": _parse_datetime(payload.get("created_at")),
                    },
                )
                session.commit()
            return True
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info("Wiii Connect audit storage unavailable; skipping append.")
                return False
            logger.warning("Wiii Connect audit append failed: %s", exc)
            return False

    def append_operation_approval_record(
        self,
        record: WiiiConnectOperationApprovalRecord,
        *,
        organization_id: str,
        user_id: str,
    ) -> bool:
        """Persist one pending preview approval without raw request values."""

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        if owner is None or not record.preview_evidence_id:
            return False
        self._ensure_initialized()
        if self._session_factory is None:
            return False

        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        f"INSERT INTO {self.OPERATION_APPROVALS_TABLE} "
                        f"(organization_id, user_id, provider_slug, action_slug, "
                        f"preview_evidence_id, request_fingerprint, status, reason, "
                        f"metadata, issued_at, expires_at, consumed_at, updated_at) "
                        f"VALUES (:organization_id, :user_id, :provider_slug, "
                        f":action_slug, :preview_evidence_id, :request_fingerprint, "
                        f":status, :reason, CAST(:metadata AS jsonb), :issued_at, "
                        f":expires_at, :consumed_at, :updated_at) "
                        f"ON CONFLICT (organization_id, user_id, provider_slug, "
                        f"preview_evidence_id) DO UPDATE SET "
                        f"action_slug = EXCLUDED.action_slug, "
                        f"request_fingerprint = EXCLUDED.request_fingerprint, "
                        f"status = 'pending', "
                        f"reason = EXCLUDED.reason, "
                        f"metadata = EXCLUDED.metadata, "
                        f"issued_at = EXCLUDED.issued_at, "
                        f"expires_at = EXCLUDED.expires_at, "
                        f"consumed_at = NULL, "
                        f"updated_at = EXCLUDED.updated_at"
                    ),
                    {
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": record.provider_slug,
                        "action_slug": record.action_slug,
                        "preview_evidence_id": record.preview_evidence_id,
                        "request_fingerprint": record.request_fingerprint,
                        "status": record.status,
                        "reason": record.reason,
                        "metadata": _json_dumps(record.to_public_metadata()["metadata"]),
                        "issued_at": _parse_datetime(record.issued_at)
                        or datetime.now(UTC),
                        "expires_at": _parse_datetime(record.expires_at)
                        or datetime.now(UTC),
                        "consumed_at": _parse_datetime(record.consumed_at),
                        "updated_at": datetime.now(UTC),
                    },
                )
                session.commit()
            return True
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info(
                    "Wiii Connect operation approval storage unavailable; "
                    "skipping append."
                )
                return False
            logger.warning("Wiii Connect operation approval append failed: %s", exc)
            return False

    def consume_operation_approval_record(
        self,
        *,
        preview_evidence_id: str,
        request_fingerprint: str,
        organization_id: str,
        user_id: str,
        provider_slug: str,
        action_slug: str,
        consumed_at: datetime | None = None,
    ) -> WiiiConnectOperationApprovalDecision:
        """Consume one pending approval row for an apply request."""

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        if owner is None:
            return unavailable_operation_approval_decision(
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id=preview_evidence_id,
                request_fingerprint=request_fingerprint,
            )
        safe_preview_evidence_id = str(preview_evidence_id or "").strip()
        safe_request_fingerprint = str(request_fingerprint or "").strip().lower()
        if not safe_preview_evidence_id or not safe_request_fingerprint:
            return blocked_operation_approval_decision(
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id=safe_preview_evidence_id,
                request_fingerprint=safe_request_fingerprint,
                reason="approval_record_missing",
            )
        self._ensure_initialized()
        if self._session_factory is None:
            return unavailable_operation_approval_decision(
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id=safe_preview_evidence_id,
                request_fingerprint=safe_request_fingerprint,
            )

        now = consumed_at or datetime.now(UTC)
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        f"SELECT provider_slug, action_slug, request_fingerprint, "
                        f"status, expires_at "
                        f"FROM {self.OPERATION_APPROVALS_TABLE} "
                        f"WHERE organization_id = :organization_id "
                        f"AND user_id = :user_id "
                        f"AND provider_slug = :provider_slug "
                        f"AND preview_evidence_id = :preview_evidence_id "
                        f"FOR UPDATE"
                    ),
                    {
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": str(provider_slug or "")
                        .strip()
                        .lower()
                        .replace("-", "_"),
                        "preview_evidence_id": safe_preview_evidence_id,
                    },
                )
                row = _fetch_mapping_row(result)
                if row is None:
                    return blocked_operation_approval_decision(
                        provider_slug=provider_slug,
                        action_slug=action_slug,
                        preview_evidence_id=safe_preview_evidence_id,
                        request_fingerprint=safe_request_fingerprint,
                        reason="approval_record_missing",
                    )

                row_status = str(_row_value(row, "status") or "").strip().lower()
                expires_at = _parse_datetime(_row_value(row, "expires_at"))
                if row_status != "pending":
                    reason = (
                        "approval_record_expired"
                        if row_status == "expired"
                        else "approval_record_already_consumed"
                    )
                    return blocked_operation_approval_decision(
                        provider_slug=provider_slug,
                        action_slug=action_slug,
                        preview_evidence_id=safe_preview_evidence_id,
                        request_fingerprint=safe_request_fingerprint,
                        reason=reason,
                    )
                if expires_at is not None and expires_at < now:
                    session.execute(
                        text(
                            f"UPDATE {self.OPERATION_APPROVALS_TABLE} "
                            f"SET status = 'expired', "
                            f"reason = 'approval_record_expired', "
                            f"updated_at = :updated_at "
                            f"WHERE organization_id = :organization_id "
                            f"AND user_id = :user_id "
                            f"AND provider_slug = :provider_slug "
                            f"AND preview_evidence_id = :preview_evidence_id"
                        ),
                        {
                            "updated_at": now,
                            "organization_id": owner["organization_id"],
                            "user_id": owner["user_id"],
                            "provider_slug": str(provider_slug or "")
                            .strip()
                            .lower()
                            .replace("-", "_"),
                            "preview_evidence_id": safe_preview_evidence_id,
                        },
                    )
                    session.commit()
                    return blocked_operation_approval_decision(
                        provider_slug=provider_slug,
                        action_slug=action_slug,
                        preview_evidence_id=safe_preview_evidence_id,
                        request_fingerprint=safe_request_fingerprint,
                        reason="approval_record_expired",
                    )
                row_fingerprint = str(
                    _row_value(row, "request_fingerprint") or ""
                ).strip().lower()
                if row_fingerprint != safe_request_fingerprint:
                    return blocked_operation_approval_decision(
                        provider_slug=provider_slug,
                        action_slug=action_slug,
                        preview_evidence_id=safe_preview_evidence_id,
                        request_fingerprint=safe_request_fingerprint,
                        reason="approval_fingerprint_mismatch",
                    )

                session.execute(
                    text(
                        f"UPDATE {self.OPERATION_APPROVALS_TABLE} "
                        f"SET status = 'consumed', "
                        f"reason = 'approval_consumed', "
                        f"consumed_at = :consumed_at, "
                        f"updated_at = :updated_at "
                        f"WHERE organization_id = :organization_id "
                        f"AND user_id = :user_id "
                        f"AND provider_slug = :provider_slug "
                        f"AND preview_evidence_id = :preview_evidence_id "
                        f"AND status = 'pending'"
                    ),
                    {
                        "consumed_at": now,
                        "updated_at": now,
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": str(provider_slug or "")
                        .strip()
                        .lower()
                        .replace("-", "_"),
                        "preview_evidence_id": safe_preview_evidence_id,
                    },
                )
                session.commit()
            return consumed_operation_approval_decision(
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id=safe_preview_evidence_id,
                request_fingerprint=safe_request_fingerprint,
            )
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info(
                    "Wiii Connect operation approval storage unavailable; "
                    "skipping consume."
                )
                return unavailable_operation_approval_decision(
                    provider_slug=provider_slug,
                    action_slug=action_slug,
                    preview_evidence_id=safe_preview_evidence_id,
                    request_fingerprint=safe_request_fingerprint,
                )
            logger.warning("Wiii Connect operation approval consume failed: %s", exc)
            return unavailable_operation_approval_decision(
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id=safe_preview_evidence_id,
                request_fingerprint=safe_request_fingerprint,
            )

    def upsert_connection_record(
        self,
        connection: WiiiConnectConnectionRecordV1,
        *,
        organization_id: str,
        user_id: str,
        provider_kind: str = "unknown",
    ) -> bool:
        """Upsert one sanitized connection record for a user/org boundary."""

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        if owner is None or not connection.connection_id or not connection.provider_slug:
            return False
        self._ensure_initialized()
        if self._session_factory is None:
            return False

        try:
            with self._session_factory() as session:
                session.execute(
                    text(
                        f"INSERT INTO {self.CONNECTIONS_TABLE} "
                        f"(id, organization_id, user_id, provider_slug, "
                        f"provider_kind, state, scopes, vault_ref, account_label, "
                        f"external_account_ref, reason, warnings, updated_at, "
                        f"last_checked_at, last_used_at) "
                        f"VALUES (:id, :organization_id, :user_id, :provider_slug, "
                        f":provider_kind, :state, CAST(:scopes AS jsonb), "
                        f"CAST(:vault_ref AS jsonb), :account_label, "
                        f":external_account_ref, :reason, CAST(:warnings AS jsonb), "
                        f":updated_at, :last_checked_at, :last_used_at) "
                        f"ON CONFLICT (id) DO UPDATE SET "
                        f"organization_id = EXCLUDED.organization_id, "
                        f"user_id = EXCLUDED.user_id, "
                        f"provider_slug = EXCLUDED.provider_slug, "
                        f"provider_kind = EXCLUDED.provider_kind, "
                        f"state = EXCLUDED.state, "
                        f"scopes = EXCLUDED.scopes, "
                        f"vault_ref = EXCLUDED.vault_ref, "
                        f"account_label = EXCLUDED.account_label, "
                        f"external_account_ref = EXCLUDED.external_account_ref, "
                        f"reason = EXCLUDED.reason, "
                        f"warnings = EXCLUDED.warnings, "
                        f"updated_at = EXCLUDED.updated_at, "
                        f"last_checked_at = EXCLUDED.last_checked_at, "
                        f"last_used_at = EXCLUDED.last_used_at"
                    ),
                    {
                        "id": connection.connection_id,
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": connection.provider_slug,
                        "provider_kind": str(provider_kind or "unknown").strip()
                        or "unknown",
                        "state": connection.state,
                        "scopes": _json_dumps(connection.scopes.to_metadata()),
                        "vault_ref": _json_dumps(
                            connection.vault_ref.to_public_metadata()
                            if connection.vault_ref is not None
                            else {}
                        ),
                        "account_label": connection.account_label or None,
                        "external_account_ref": connection.external_account_ref
                        or None,
                        "reason": connection.reason or None,
                        "warnings": _json_dumps(list(connection.warnings)),
                        "updated_at": datetime.now(UTC),
                        "last_checked_at": _parse_datetime(connection.last_checked_at),
                        "last_used_at": datetime.now(UTC)
                        if connection.active
                        else None,
                    },
                )
                session.commit()
            return True
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info("Wiii Connect connection storage unavailable; skipping upsert.")
                return False
            logger.warning("Wiii Connect connection upsert failed: %s", exc)
            return False

    def get_connection_record(
        self,
        *,
        organization_id: str,
        user_id: str,
        provider_slug: str,
        connection_id: str | None = None,
    ) -> WiiiConnectConnectionRecordV1 | None:
        """Fetch the latest sanitized connection row for an org/user/provider."""

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        slug = str(provider_slug or "").strip().lower().replace("-", "_")
        safe_connection_id = str(connection_id or "").strip()
        if owner is None or not slug:
            return None
        self._ensure_initialized()
        if self._session_factory is None:
            return None

        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        f"SELECT id, provider_slug, state, scopes, vault_ref, "
                        f"account_label, external_account_ref, reason, warnings, "
                        f"last_checked_at "
                        f"FROM {self.CONNECTIONS_TABLE} "
                        f"WHERE organization_id = :organization_id "
                        f"AND user_id = :user_id "
                        f"AND provider_slug = :provider_slug "
                        f"AND (:connection_id = '' OR id = :connection_id) "
                        f"ORDER BY updated_at DESC "
                        f"LIMIT 1"
                    ),
                    {
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": slug,
                        "connection_id": safe_connection_id,
                    },
                )
                row = _fetch_mapping_row(result)
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info("Wiii Connect connection storage unavailable; skipping fetch.")
                return None
            logger.warning("Wiii Connect connection fetch failed: %s", exc)
            return None

        return _connection_record_from_row(row, fallback_provider_slug=slug)

    def list_connection_records(
        self,
        *,
        organization_id: str,
        user_id: str,
        provider_slug: str,
        limit: int = 100,
    ) -> tuple[WiiiConnectConnectionRecordV1, ...]:
        """Fetch sanitized connection rows for resolving opaque public refs."""

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        slug = str(provider_slug or "").strip().lower().replace("-", "_")
        if owner is None or not slug:
            return ()
        self._ensure_initialized()
        if self._session_factory is None:
            return ()

        safe_limit = max(1, min(int(limit or 100), 500))
        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        f"SELECT id, provider_slug, state, scopes, vault_ref, "
                        f"account_label, external_account_ref, reason, warnings, "
                        f"last_checked_at "
                        f"FROM {self.CONNECTIONS_TABLE} "
                        f"WHERE organization_id = :organization_id "
                        f"AND user_id = :user_id "
                        f"AND provider_slug = :provider_slug "
                        f"ORDER BY updated_at DESC "
                        f"LIMIT :limit"
                    ),
                    {
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": slug,
                        "limit": safe_limit,
                    },
                )
                mappings = getattr(result, "mappings", None)
                rows = mappings().all() if callable(mappings) else result.fetchall()
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info("Wiii Connect connection storage unavailable; skipping list.")
                return ()
            logger.warning("Wiii Connect connection list failed: %s", exc)
            return ()

        records: list[WiiiConnectConnectionRecordV1] = []
        for row in rows:
            record = _connection_record_from_row(row, fallback_provider_slug=slug)
            if record is not None:
                records.append(record)
        return tuple(records)

    def expire_stale_pending_connections(
        self,
        *,
        organization_id: str,
        user_id: str,
        provider_slug: str,
        ttl_seconds: int = DEFAULT_STALE_PENDING_CONNECTION_TTL_SECONDS,
    ) -> int:
        """Mark stale non-active OAuth connection rows as expired.

        This lifecycle cleanup is deliberately scoped to one org/user/provider
        boundary and only affects rows that cannot authorize execution:
        authorizing, waiting, or error.
        """

        owner = _normalize_owner(organization_id=organization_id, user_id=user_id)
        slug = str(provider_slug or "").strip().lower().replace("-", "_")
        if owner is None or not slug:
            return 0
        safe_ttl = max(60, int(ttl_seconds or 0))
        expires_before = datetime.now(UTC) - timedelta(seconds=safe_ttl)
        self._ensure_initialized()
        if self._session_factory is None:
            return 0

        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        f"UPDATE {self.CONNECTIONS_TABLE} "
                        f"SET state = 'expired', "
                        f"reason = 'stale_oauth_connection_expired', "
                        f"warnings = COALESCE(warnings, '[]'::jsonb) || "
                        f"CAST(:expiry_warning AS jsonb), "
                        f"updated_at = :updated_at "
                        f"WHERE organization_id = :organization_id "
                        f"AND user_id = :user_id "
                        f"AND provider_slug = :provider_slug "
                        f"AND state IN ('authorizing', 'waiting', 'error') "
                        f"AND updated_at < :expires_before"
                    ),
                    {
                        "organization_id": owner["organization_id"],
                        "user_id": owner["user_id"],
                        "provider_slug": slug,
                        "expiry_warning": _json_dumps(
                            ["expired_by_wiii_connect_cleanup"],
                        ),
                        "updated_at": datetime.now(UTC),
                        "expires_before": expires_before,
                    },
                )
                session.commit()
                return max(0, int(getattr(result, "rowcount", 0) or 0))
        except Exception as exc:
            if _is_missing_storage_table_error(exc):
                logger.info("Wiii Connect connection storage unavailable; skipping expiry.")
                return 0
            logger.warning("Wiii Connect stale connection expiry failed: %s", exc)
            return 0


def default_persistent_storage_status_metadata() -> dict[str, Any]:
    """Return default non-probed persistent storage status metadata."""

    return WiiiConnectPersistentStorageStatus().to_public_metadata()


def _normalize_owner(*, organization_id: str, user_id: str) -> dict[str, str] | None:
    org = str(organization_id or "").strip()
    user = str(user_id or "").strip()
    if not org or not user:
        return None
    return {"organization_id": org, "user_id": user}


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _datetime_to_iso(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _fetch_mapping_row(result: Any) -> Any | None:
    mappings = getattr(result, "mappings", None)
    if callable(mappings):
        try:
            return mappings().fetchone()
        except Exception:
            return None
    fetchone = getattr(result, "fetchone", None)
    if callable(fetchone):
        return fetchone()
    return None


def _connection_record_from_row(
    row: Any | None,
    *,
    fallback_provider_slug: str,
) -> WiiiConnectConnectionRecordV1 | None:
    if row is None:
        return None
    slug = str(fallback_provider_slug or "").strip().lower().replace("-", "_")
    scopes = _decode_json_object(_row_value(row, "scopes"), default={})
    vault_ref = _decode_json_object(_row_value(row, "vault_ref"), default={})
    warnings = _decode_json_list(_row_value(row, "warnings"))
    connection_id_value = str(_row_value(row, "id") or "").strip()
    if not connection_id_value:
        return None
    provider_slug = str(_row_value(row, "provider_slug") or slug).strip()
    normalized_provider = provider_slug.lower().replace("-", "_") or slug
    has_vault_ref = bool(vault_ref.get("vault_ref_present"))
    return WiiiConnectConnectionRecordV1(
        connection_id=connection_id_value,
        provider_slug=normalized_provider,
        state=normalize_connection_state(str(_row_value(row, "state") or "")),
        scopes=WiiiConnectScopeGrant(
            read=bool(scopes.get("read")),
            preview=bool(scopes.get("preview")),
            write=bool(scopes.get("write")),
            apply=bool(scopes.get("apply")),
            admin=bool(scopes.get("admin")),
        ),
        vault_ref=(
            WiiiConnectVaultSecretRef(
                provider_slug=normalized_provider,
                connection_id=connection_id_value,
                vault_key_id="stored_opaque_ref",
                secret_version=str(vault_ref.get("secret_version") or ""),
            )
            if has_vault_ref
            else None
        ),
        account_label=str(_row_value(row, "account_label") or ""),
        external_account_ref=str(_row_value(row, "external_account_ref") or ""),
        last_checked_at=_datetime_to_iso(_row_value(row, "last_checked_at")),
        reason=str(_row_value(row, "reason") or ""),
        warnings=tuple(warnings),
    )


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(key)
    try:
        return row[key]
    except Exception:
        return None


def _row_index_value(row: Any, index: int) -> Any:
    try:
        return row[index]
    except Exception:
        return None


def _decode_json_object(value: Any, *, default: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return dict(default)
        return parsed if isinstance(parsed, dict) else dict(default)
    return dict(default)


def _decode_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return []


def _is_missing_storage_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "wiii_connect_" in message and (
        "does not exist" in message or "undefinedtable" in message
    )


_persistent_storage: WiiiConnectPersistentStorage | None = None


def get_wiii_connect_persistent_storage() -> WiiiConnectPersistentStorage:
    global _persistent_storage
    if _persistent_storage is None:
        _persistent_storage = WiiiConnectPersistentStorage()
    return _persistent_storage


__all__ = [
    "DEFAULT_STALE_PENDING_CONNECTION_TTL_SECONDS",
    "WIII_CONNECT_PERSISTENT_STORAGE_VERSION",
    "WiiiConnectPersistentStorage",
    "WiiiConnectPersistentStorageStatus",
    "default_persistent_storage_status_metadata",
    "get_wiii_connect_persistent_storage",
]
