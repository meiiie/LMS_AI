"""
Sprint 176: Auth audit event logging.

Fire-and-forget INSERT into auth_events table.
No-op when enable_auth_audit=False. Never raises.
"""
import json
import logging
from typing import Optional

from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_MAX_AUTH_AUDIT_DIAGNOSTIC_LENGTH = 500
_MAX_AUTH_AUDIT_SECRET_DEPTH = 4
_MAX_AUTH_AUDIT_SECRET_ITEMS = 32
_REDACTED_SECRET = "<redacted-secret>"


def _auth_audit_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _iter_auth_audit_secret_values(value: object, *, _depth: int = 0):
    if _depth > _MAX_AUTH_AUDIT_SECRET_DEPTH:
        return
    if isinstance(value, dict):
        for item in list(value.values())[:_MAX_AUTH_AUDIT_SECRET_ITEMS]:
            yield from _iter_auth_audit_secret_values(item, _depth=_depth + 1)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in list(value)[:_MAX_AUTH_AUDIT_SECRET_ITEMS]:
            yield from _iter_auth_audit_secret_values(item, _depth=_depth + 1)
        return
    if isinstance(value, str):
        yield value


def _safe_auth_audit_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    seen: set[str] = set()
    for raw_secret in secret_values:
        for secret_value in _iter_auth_audit_secret_values(raw_secret):
            secret = str(secret_value or "")
            if not secret or secret in seen:
                continue
            seen.add(secret)
            text = text.replace(secret, _REDACTED_SECRET)
    return redact_runtime_secret_text(
        text,
        max_length=_MAX_AUTH_AUDIT_DIAGNOSTIC_LENGTH,
    )


async def log_auth_event(
    event_type: str,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    result: str = "success",
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    organization_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Fire-and-forget auth event logging. No-op when enable_auth_audit=False."""
    try:
        from app.core.config import settings
        if not settings.enable_auth_audit:
            return

        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO auth_events (event_type, user_id, provider, result, reason,
                                         ip_address, user_agent, organization_id, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                event_type,
                user_id,
                provider,
                result,
                reason,
                ip_address,
                user_agent,
                organization_id,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
            )
    except Exception as e:
        logger.warning(
            "Failed to log auth event event=%s user_ref=%s org_ref=%s "
            "provider=%s result=%s detail=%s",
            event_type,
            _auth_audit_ref(user_id),
            _auth_audit_ref(organization_id),
            provider,
            result,
            _safe_auth_audit_detail(
                e,
                user_id,
                organization_id,
                ip_address,
                user_agent,
                reason,
                metadata,
            ),
        )
