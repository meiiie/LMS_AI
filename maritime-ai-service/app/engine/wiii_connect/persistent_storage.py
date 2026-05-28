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
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


class WiiiConnectPersistentStorage:
    """Small repository for Wiii Connect durable control-plane records."""

    CONNECTIONS_TABLE = "wiii_connect_connections"
    AUDIT_TABLE = "wiii_connect_audit_ledger"

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
                        "to_regclass(:audit_table)"
                    ),
                    {
                        "connections_table": self.CONNECTIONS_TABLE,
                        "audit_table": self.AUDIT_TABLE,
                    },
                ).fetchone()
        except Exception as exc:
            logger.warning("Wiii Connect storage status check failed: %s", exc)
            return WiiiConnectPersistentStorageStatus(
                reason="database_unavailable",
                warnings=("status_probe_failed",),
            )

        connection_ready = bool(row and row[0])
        audit_ready = bool(row and row[1])
        ready = connection_ready and audit_ready
        return WiiiConnectPersistentStorageStatus(
            enabled=ready,
            persistent=ready,
            connection_table_ready=connection_ready,
            audit_ledger_ready=audit_ready,
            reason="ready" if ready else "migration_not_applied",
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
        metadata = connection.to_public_metadata()
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
                        "scopes": _json_dumps(metadata.get("scopes", {})),
                        "vault_ref": _json_dumps(
                            connection.vault_ref.to_public_metadata()
                            if connection.vault_ref is not None
                            else {}
                        ),
                        "account_label": metadata.get("account_label") or None,
                        "external_account_ref": (
                            metadata.get("external_account_ref") or None
                        ),
                        "reason": metadata.get("reason") or None,
                        "warnings": _json_dumps(metadata.get("warnings", [])),
                        "updated_at": datetime.now(UTC),
                        "last_checked_at": _parse_datetime(
                            metadata.get("last_checked_at")
                        ),
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

        if row is None:
            return None
        scopes = _decode_json_object(_row_value(row, "scopes"), default={})
        vault_ref = _decode_json_object(_row_value(row, "vault_ref"), default={})
        warnings = _decode_json_list(_row_value(row, "warnings"))
        connection_id_value = str(_row_value(row, "id") or "").strip()
        has_vault_ref = bool(vault_ref.get("vault_ref_present"))
        return WiiiConnectConnectionRecordV1(
            connection_id=connection_id_value,
            provider_slug=str(_row_value(row, "provider_slug") or slug).strip(),
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
                    provider_slug=slug,
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
