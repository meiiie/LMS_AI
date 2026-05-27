"""Durable Wiii Connect connection and audit storage adapter.

The adapter stores only privacy-safe control-plane metadata. It does not store
OAuth codes, access tokens, refresh tokens, API keys, provider payloads, or raw
vault paths.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import text

from .adapter_v1 import WiiiConnectConnectionRecordV1
from .audit_ledger import WiiiConnectAuditLedgerRecord


logger = logging.getLogger(__name__)

WIII_CONNECT_PERSISTENT_STORAGE_VERSION = "wiii_connect_persistent_storage.v1"


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
    "WIII_CONNECT_PERSISTENT_STORAGE_VERSION",
    "WiiiConnectPersistentStorage",
    "WiiiConnectPersistentStorageStatus",
    "default_persistent_storage_status_metadata",
    "get_wiii_connect_persistent_storage",
]
