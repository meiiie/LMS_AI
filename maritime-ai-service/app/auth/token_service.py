"""
Sprint 157: Token service — create, refresh, revoke JWT tokens.
Sprint 192: Added `aud` claim, JTI denylist with TTL cleanup.

Access tokens: short-lived (configurable, default 15 min)
Refresh tokens: long-lived (configurable, default 30 days), stored hashed in DB
"""
import hashlib
import json
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from pydantic import BaseModel

from app.core.config import settings
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_REDACTED_SECRET = "<redacted-secret>"
_MAX_AUTH_DIAGNOSTIC_LENGTH = 500


def _auth_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_auth_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    seen: set[str] = set()
    for raw_secret in secret_values:
        secret = str(raw_secret or "")
        if not secret or secret in seen:
            continue
        seen.add(secret)
        text = text.replace(secret, _REDACTED_SECRET)
    return redact_runtime_secret_text(text, max_length=_MAX_AUTH_DIAGNOSTIC_LENGTH)

# =============================================================================
# Sprint 192: In-memory JTI denylist with TTL
# =============================================================================
_jti_denylist: dict[str, float] = {}  # jti -> expiry timestamp
_jti_lock = threading.Lock()


def deny_jti(jti: str, ttl_seconds: Optional[int] = None) -> None:
    """Add a JTI to the denylist. TTL defaults to jwt_expire_minutes."""
    if not jti:
        return
    if ttl_seconds is None:
        ttl_seconds = settings.jwt_expire_minutes * 60
    expiry = time.time() + ttl_seconds
    with _jti_lock:
        _jti_denylist[jti] = expiry
        # Opportunistic cleanup: remove expired entries
        now = time.time()
        expired = [k for k, v in _jti_denylist.items() if v < now]
        for k in expired:
            del _jti_denylist[k]


def is_jti_denied(jti: str) -> bool:
    """Check if a JTI has been denied (revoked)."""
    with _jti_lock:
        expiry = _jti_denylist.get(jti)
        if expiry is None:
            return False
        if expiry < time.time():
            # Expired entry — clean up
            del _jti_denylist[jti]
            return False
        return True


def _clear_jti_denylist() -> None:
    """Clear the JTI denylist (for testing)."""
    with _jti_lock:
        _jti_denylist.clear()


class TokenPair(BaseModel):
    """Access + refresh token pair returned after authentication."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class AccessTokenPayload(BaseModel):
    """Decoded access token claims."""
    sub: str  # Wiii user ID
    email: Optional[str] = None
    name: Optional[str] = None
    role: str = "student"
    platform_role: Optional[str] = None
    organization_role: Optional[str] = None
    host_role: Optional[str] = None
    role_source: Optional[str] = None
    active_organization_id: Optional[str] = None
    connector_id: Optional[str] = None
    identity_version: Optional[str] = None
    auth_method: str = "google"  # google, lti, api_key
    type: str = "access"
    exp: datetime
    iat: datetime
    iss: str = "wiii"
    jti: Optional[str] = None  # Sprint 176: unique token ID


def _hash_token(token: str) -> str:
    """SHA-256 hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _build_identity_snapshot(
    *,
    role: str,
    platform_role: Optional[str] = None,
    organization_role: Optional[str] = None,
    host_role: Optional[str] = None,
    role_source: Optional[str] = None,
    active_organization_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    identity_version: Optional[str] = None,
) -> dict:
    """Build a compact identity snapshot for refresh-token continuity."""
    snapshot = {
        "role": role,
        "platform_role": platform_role,
        "organization_role": organization_role,
        "host_role": host_role,
        "role_source": role_source,
        "active_organization_id": active_organization_id,
        "connector_id": connector_id,
        "identity_version": identity_version,
    }
    return {key: value for key, value in snapshot.items() if value is not None}


def _coerce_identity_snapshot(raw: object) -> dict:
    """Normalize identity snapshots read back from refresh-token storage."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _is_refresh_identity_schema_error(exc: Exception) -> bool:
    """Return True when refresh_tokens lacks Identity V2 columns."""
    message = str(exc)
    return "identity_snapshot" in message or "organization_id" in message


def _is_strict_refresh_identity_mode() -> bool:
    """Production/staging multi-tenant refresh tokens must carry org context."""
    return (
        bool(getattr(settings, "enable_multi_tenant", False))
        and getattr(settings, "environment", "production") in {"production", "staging"}
    )


def create_access_token(
    user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "student",
    platform_role: Optional[str] = None,
    organization_role: Optional[str] = None,
    host_role: Optional[str] = None,
    role_source: Optional[str] = None,
    active_organization_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    identity_version: Optional[str] = None,
    auth_method: str = "google",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived JWT access token.

    Sprint 192: Added `aud` claim for audience validation.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))

    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "role": role,
        "platform_role": platform_role,
        "organization_role": organization_role,
        "host_role": host_role,
        "role_source": role_source,
        "active_organization_id": active_organization_id,
        "connector_id": connector_id,
        "identity_version": identity_version,
        "auth_method": auth_method,
        "type": "access",
        "iss": "wiii",
        "aud": settings.jwt_audience,  # Sprint 192: audience claim
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),  # Sprint 176: unique token ID
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> str:
    """Create a cryptographically random refresh token."""
    return secrets.token_urlsafe(64)


def create_stateless_refresh_token(
    user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "student",
    platform_role: Optional[str] = None,
    organization_role: Optional[str] = None,
    host_role: Optional[str] = None,
    role_source: Optional[str] = None,
    active_organization_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    identity_version: Optional[str] = None,
    auth_method: str = "google",
) -> str:
    """Create a signed refresh token for degraded local/dev operation."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "role": role,
        "platform_role": platform_role,
        "organization_role": organization_role,
        "host_role": host_role,
        "role_source": role_source,
        "active_organization_id": active_organization_id,
        "connector_id": connector_id,
        "identity_version": identity_version,
        "auth_method": auth_method,
        "type": "refresh",
        "stateless": True,
        "iss": "wiii",
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_stateless_refresh_payload(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except jwt.PyJWTError:
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"verify_aud": False},
            )
        except jwt.PyJWTError:
            return None

    if payload.get("type") != "refresh" or payload.get("stateless") is not True:
        return None
    return payload


def _stateless_refresh_allowed(payload: dict) -> bool:
    """Keep signed refresh fallback scoped to safe degraded/dev contexts."""
    if (
        payload.get("auth_method") == "dev"
        and getattr(settings, "enable_dev_login", False)
        and getattr(settings, "environment", "production") != "production"
    ):
        return True

    try:
        from app.core.database import is_shared_database_temporarily_unavailable

        return is_shared_database_temporarily_unavailable()
    except Exception:
        return False


def decode_jwt_payload(token: str) -> dict:
    """Decode and validate a JWT token, returning the raw claims dict.

    Single-source decode logic: audience fallback + JTI denylist check.
    Raises jwt.PyJWTError on failure. Used by both verify_access_token() and
    security.verify_jwt_token().
    """
    audience = settings.jwt_audience
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=audience,
        )
    except jwt.PyJWTError:
        # Backward compat: retry without audience for legacy tokens
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )

    # Sprint 192: Check JTI denylist
    jti = payload.get("jti")
    if settings.enable_jti_denylist and jti:
        if is_jti_denied(jti):
            raise jwt.PyJWTError("Token has been revoked (jti denied)")

    return payload


def verify_access_token(token: str) -> AccessTokenPayload:
    """Verify and decode an access token. Raises JWTError on failure."""
    payload = decode_jwt_payload(token)
    return AccessTokenPayload(**payload)


async def create_token_pair(
    user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "student",
    platform_role: Optional[str] = None,
    organization_role: Optional[str] = None,
    host_role: Optional[str] = None,
    role_source: Optional[str] = None,
    active_organization_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    identity_version: Optional[str] = None,
    auth_method: str = "google",
    family_id: Optional[str] = None,
) -> TokenPair:
    """Create access + refresh token pair and store refresh token hash in DB.

    Sprint 176: family_id groups refresh tokens for replay detection.
    If None, generates a new family (new login = new family).
    """
    access_token = create_access_token(
        user_id=user_id,
        email=email,
        name=name,
        role=role,
        platform_role=platform_role,
        organization_role=organization_role,
        host_role=host_role,
        role_source=role_source,
        active_organization_id=active_organization_id,
        connector_id=connector_id,
        identity_version=identity_version,
        auth_method=auth_method,
    )
    refresh_token = create_refresh_token()

    try:
        from app.core.database import is_shared_database_temporarily_unavailable

        if is_shared_database_temporarily_unavailable():
            logger.warning("Skipping refresh-token persistence because database is in degraded cooldown")
            return TokenPair(
                access_token=access_token,
                refresh_token=create_stateless_refresh_token(
                    user_id=user_id,
                    email=email,
                    name=name,
                    role=role,
                    platform_role=platform_role,
                    organization_role=organization_role,
                    host_role=host_role,
                    role_source=role_source,
                    active_organization_id=active_organization_id,
                    connector_id=connector_id,
                    identity_version=identity_version,
                    auth_method=auth_method,
                ),
                token_type="bearer",
                expires_in=settings.jwt_expire_minutes * 60,
            )
    except Exception:
        pass

    # Store refresh token hash in DB
    token_id = str(uuid.uuid4())
    token_hash = _hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    effective_family_id = family_id or str(uuid.uuid4())

    try:
        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            identity_snapshot = _build_identity_snapshot(
                role=role,
                platform_role=platform_role,
                organization_role=organization_role,
                host_role=host_role,
                role_source=role_source,
                active_organization_id=active_organization_id,
                connector_id=connector_id,
                identity_version=identity_version,
            )
            try:
                await conn.execute(
                    """
                    INSERT INTO refresh_tokens (
                        id,
                        user_id,
                        token_hash,
                        auth_method,
                        expires_at,
                        created_at,
                        family_id,
                        organization_id,
                        identity_snapshot
                    )
                    VALUES ($1, $2, $3, $4, $5, NOW(), $6, $7, $8::jsonb)
                    """,
                    token_id,
                    user_id,
                    token_hash,
                    auth_method,
                    expires_at,
                    effective_family_id,
                    active_organization_id,
                    json.dumps(identity_snapshot, ensure_ascii=False),
                )
            except Exception as exc:
                if not _is_refresh_identity_schema_error(exc):
                    raise
                if _is_strict_refresh_identity_mode() and active_organization_id:
                    logger.error(
                        "Refresh-token Identity V2 columns are required in strict "
                        "multi-tenant mode; refusing legacy refresh-token insert"
                    )
                    raise
                logger.warning(
                    "Refresh-token schema missing Identity V2 columns; falling back to legacy insert"
                )
                await conn.execute(
                    """
                    INSERT INTO refresh_tokens (
                        id,
                        user_id,
                        token_hash,
                        auth_method,
                        expires_at,
                        created_at,
                        family_id
                    )
                    VALUES ($1, $2, $3, $4, $5, NOW(), $6)
                    """,
                    token_id,
                    user_id,
                    token_hash,
                    auth_method,
                    expires_at,
                    effective_family_id,
                )
    except Exception as exc:
        try:
            from app.core.database import mark_shared_database_unavailable

            mark_shared_database_unavailable(exc)
        except Exception:
            pass
        logger.warning("Failed to store refresh token; issuing signed stateless fallback")
        return TokenPair(
            access_token=access_token,
            refresh_token=create_stateless_refresh_token(
                user_id=user_id,
                email=email,
                name=name,
                role=role,
                platform_role=platform_role,
                organization_role=organization_role,
                host_role=host_role,
                role_source=role_source,
                active_organization_id=active_organization_id,
                connector_id=connector_id,
                identity_version=identity_version,
                auth_method=auth_method,
            ),
            token_type="bearer",
            expires_in=settings.jwt_expire_minutes * 60,
        )

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
    )


async def refresh_access_token(refresh_token: str) -> Optional[TokenPair]:
    """
    Validate a refresh token and issue a new token pair.

    Returns new TokenPair or None if refresh token is invalid/expired/revoked.
    Implements refresh token rotation (old token revoked, new one issued).

    Sprint 176: Replay detection via family_id — if a revoked token with
    an active sibling is reused, ALL tokens in that family are purged.
    """
    stateless_payload = _decode_stateless_refresh_payload(refresh_token)
    if stateless_payload is not None:
        if not _stateless_refresh_allowed(stateless_payload):
            logger.warning("Rejected stateless refresh token outside degraded/dev context")
            return None
        return TokenPair(
            access_token=create_access_token(
                user_id=stateless_payload["sub"],
                email=stateless_payload.get("email"),
                name=stateless_payload.get("name"),
                role=stateless_payload.get("role", "student"),
                platform_role=stateless_payload.get("platform_role"),
                organization_role=stateless_payload.get("organization_role"),
                host_role=stateless_payload.get("host_role"),
                role_source=stateless_payload.get("role_source"),
                active_organization_id=stateless_payload.get("active_organization_id"),
                connector_id=stateless_payload.get("connector_id"),
                identity_version=stateless_payload.get("identity_version"),
                auth_method=stateless_payload.get("auth_method") or "google",
            ),
            refresh_token=create_stateless_refresh_token(
                user_id=stateless_payload["sub"],
                email=stateless_payload.get("email"),
                name=stateless_payload.get("name"),
                role=stateless_payload.get("role", "student"),
                platform_role=stateless_payload.get("platform_role"),
                organization_role=stateless_payload.get("organization_role"),
                host_role=stateless_payload.get("host_role"),
                role_source=stateless_payload.get("role_source"),
                active_organization_id=stateless_payload.get("active_organization_id"),
                connector_id=stateless_payload.get("connector_id"),
                identity_version=stateless_payload.get("identity_version"),
                auth_method=stateless_payload.get("auth_method") or "google",
            ),
            token_type="bearer",
            expires_in=settings.jwt_expire_minutes * 60,
        )

    token_hash = _hash_token(refresh_token)

    try:
        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    SELECT rt.id, rt.user_id, rt.expires_at, rt.revoked_at, rt.auth_method,
                           rt.family_id, rt.organization_id, rt.identity_snapshot,
                           u.email, u.name, u.role, u.platform_role
                    FROM refresh_tokens rt
                    JOIN users u ON u.id = rt.user_id
                    WHERE rt.token_hash = $1
                    """,
                    token_hash,
                )
            except Exception as exc:
                if not _is_refresh_identity_schema_error(exc):
                    raise
                if _is_strict_refresh_identity_mode():
                    logger.warning(
                        "Rejected refresh rotation because refresh-token Identity V2 "
                        "columns are missing in strict multi-tenant mode"
                    )
                    return None
                logger.warning(
                    "Refresh-token schema missing Identity V2 columns; falling back to legacy lookup"
                )
                row = await conn.fetchrow(
                    """
                    SELECT rt.id, rt.user_id, rt.expires_at, rt.revoked_at, rt.auth_method,
                           rt.family_id, u.email, u.name, u.role
                    FROM refresh_tokens rt
                    JOIN users u ON u.id = rt.user_id
                    WHERE rt.token_hash = $1
                    """,
                    token_hash,
                )

            if not row:
                logger.warning("Refresh token not found")
                return None

            # Sprint 176: Replay detection — revoked token reuse
            if row["revoked_at"] is not None:
                family_id = row.get("family_id")
                if family_id:
                    # Check for active siblings in the same family
                    active_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM refresh_tokens WHERE family_id = $1 AND revoked_at IS NULL",
                        family_id,
                    )
                    if active_count > 0:
                        # REPLAY ATTACK — purge entire family
                        logger.warning(
                            "REPLAY ATTACK DETECTED: revoked refresh token reused "
                            "user_ref=%s family_ref=%s purging %d active tokens",
                            _auth_ref(row["user_id"]),
                            _auth_ref(family_id),
                            active_count,
                        )
                        await conn.execute(
                            "UPDATE refresh_tokens SET revoked_at = NOW() WHERE family_id = $1 AND revoked_at IS NULL",
                            family_id,
                        )
                        # Fire audit event (non-blocking)
                        try:
                            from app.auth.auth_audit import log_auth_event
                            await log_auth_event(
                                "token_replay_detected",
                                user_id=row["user_id"],
                                result="blocked",
                                reason=(
                                    f"family_ref={_auth_ref(family_id)}, "
                                    f"purged={active_count}"
                                ),
                            )
                        except Exception as _audit_err:
                            logger.debug(
                                "Auth audit log failed (token_replay_detected): %s",
                                _safe_auth_detail(
                                    _audit_err,
                                    row["user_id"],
                                    family_id,
                                ),
                            )
                logger.warning(
                    "Refresh token already revoked user_ref=%s",
                    _auth_ref(row["user_id"]),
                )
                return None

            if row["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                logger.warning(
                    "Refresh token expired user_ref=%s",
                    _auth_ref(row["user_id"]),
                )
                return None

            # Revoke the old refresh token (rotation)
            await conn.execute(
                "UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = $1",
                row["id"],
            )

            # Issue new pair (propagate family_id)
            identity_snapshot = _coerce_identity_snapshot(row.get("identity_snapshot"))
            new_pair = await create_token_pair(
                user_id=row["user_id"],
                email=row["email"],
                name=row["name"],
                role=identity_snapshot.get("role", row["role"]),
                platform_role=identity_snapshot.get("platform_role", row.get("platform_role")),
                organization_role=identity_snapshot.get("organization_role"),
                host_role=identity_snapshot.get("host_role"),
                role_source=identity_snapshot.get("role_source"),
                active_organization_id=identity_snapshot.get(
                    "active_organization_id",
                    row.get("organization_id"),
                ),
                connector_id=identity_snapshot.get("connector_id"),
                identity_version=identity_snapshot.get("identity_version"),
                auth_method=row.get("auth_method") or "google",
                family_id=row.get("family_id"),
            )

            # Audit event
            try:
                from app.auth.auth_audit import log_auth_event
                await log_auth_event("token_refresh", user_id=row["user_id"])
            except Exception as _audit_err:
                logger.debug(
                    "Auth audit log failed (token_refresh): %s",
                    _safe_auth_detail(_audit_err, row["user_id"], row.get("family_id")),
                )

            return new_pair
    except Exception:
        logger.exception("Error during token refresh")
        return None


async def revoke_user_tokens(user_id: str) -> int:
    """Revoke all refresh tokens for a user (logout everywhere). Returns count revoked."""
    try:
        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE refresh_tokens SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL",
                user_id,
            )
            count = int(result.split()[-1])
            logger.info(
                "Revoked %d refresh tokens user_ref=%s",
                count,
                _auth_ref(user_id),
            )

            # Sprint 176: Audit event
            try:
                from app.auth.auth_audit import log_auth_event
                await log_auth_event(
                    "token_revoked", user_id=user_id,
                    metadata={"count": count},
                )
            except Exception as _audit_err:
                logger.debug(
                    "Auth audit log failed (token_revoked): %s",
                    _safe_auth_detail(_audit_err, user_id),
                )

            return count
    except Exception:
        logger.exception("Error revoking tokens user_ref=%s", _auth_ref(user_id))
        return 0
