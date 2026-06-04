"""
Sprint 157: User service — find-or-create users, link identities.
Sprint 158: Generalized find_or_create_by_provider + CRUD operations.

Operates on the `users` and `user_identities` tables.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

logger = logging.getLogger(__name__)

_VALID_ROLES = {"student", "teacher", "admin"}
_VALID_PLATFORM_ROLES = {"user", "platform_admin"}


def _auth_identity_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _derive_platform_role(legacy_role: Optional[str], platform_role: Optional[str] = None) -> str:
    """Normalize persisted platform role with a safe legacy fallback."""
    if isinstance(platform_role, str):
        normalized = platform_role.strip().lower()
        if normalized in _VALID_PLATFORM_ROLES:
            return normalized
    if isinstance(legacy_role, str) and legacy_role.strip().lower() == "admin":
        return "platform_admin"
    return "user"


def _format_user_row(row: dict) -> dict:
    """Normalize user rows returned from SQL queries."""
    result = dict(row)
    result["platform_role"] = _derive_platform_role(
        result.get("role"),
        result.get("platform_role"),
    )
    for key in ("created_at", "updated_at"):
        if result.get(key) and hasattr(result[key], "isoformat"):
            result[key] = result[key].isoformat()
    return result


async def _get_pool() -> asyncpg.Pool:
    """Get the shared asyncpg connection pool."""
    from app.core.database import get_asyncpg_pool
    return await get_asyncpg_pool()


async def find_user_by_provider(
    provider: str,
    provider_sub: str,
    provider_issuer: Optional[str] = None,
) -> Optional[dict]:
    """
    Find a Wiii user by provider identity.

    Returns dict with user fields or None.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                SELECT u.id, u.email, u.name, u.avatar_url, u.role, u.platform_role, u.is_active
                FROM user_identities ui
                JOIN users u ON u.id = ui.user_id
                WHERE ui.provider = $1
                  AND ui.provider_sub = $2
                  AND (ui.provider_issuer = $3 OR ($3 IS NULL AND ui.provider_issuer IS NULL))
                """,
                provider, provider_sub, provider_issuer,
            )
        except Exception as e:
            if "platform_role" not in str(e):
                raise
            row = await conn.fetchrow(
                """
                SELECT u.id, u.email, u.name, u.avatar_url, u.role, u.is_active
                FROM user_identities ui
                JOIN users u ON u.id = ui.user_id
                WHERE ui.provider = $1
                  AND ui.provider_sub = $2
                  AND (ui.provider_issuer = $3 OR ($3 IS NULL AND ui.provider_issuer IS NULL))
                """,
                provider, provider_sub, provider_issuer,
            )
        if row:
            # Update last_used_at
            await conn.execute(
                """
                UPDATE user_identities SET last_used_at = NOW()
                WHERE provider = $1 AND provider_sub = $2
                  AND (provider_issuer = $3 OR ($3 IS NULL AND provider_issuer IS NULL))
                """,
                provider, provider_sub, provider_issuer,
            )
            return _format_user_row(dict(row))
    return None


async def find_user_by_email(email: str) -> Optional[dict]:
    """Find a user by email (case-insensitive)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "SELECT id, email, name, avatar_url, role, platform_role, is_active FROM users WHERE LOWER(email) = LOWER($1)",
                email,
            )
        except Exception as e:
            if "platform_role" not in str(e):
                raise
            row = await conn.fetchrow(
                "SELECT id, email, name, avatar_url, role, is_active FROM users WHERE LOWER(email) = LOWER($1)",
                email,
            )
        return _format_user_row(dict(row)) if row else None


async def create_user(
    email: Optional[str],
    name: Optional[str],
    avatar_url: Optional[str] = None,
    role: str = "student",
    platform_role: Optional[str] = None,
) -> dict:
    """Create a new Wiii user. Returns user dict with id."""
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    effective_platform_role = _derive_platform_role(role, platform_role)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO users (id, email, name, avatar_url, role, platform_role, is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, true, $7, $7)
                """,
                user_id, email, name, avatar_url, role, effective_platform_role, now,
            )
        except Exception as e:
            if "platform_role" not in str(e):
                raise
            await conn.execute(
                """
                INSERT INTO users (id, email, name, avatar_url, role, is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, true, $6, $6)
                """,
                user_id, email, name, avatar_url, role, now,
            )
    logger.info(
        "Created user user_ref=%s email_ref=%s",
        _auth_identity_ref(user_id),
        _auth_identity_ref(email),
    )
    return {
        "id": user_id,
        "email": email,
        "name": name,
        "avatar_url": avatar_url,
        "role": role,
        "platform_role": effective_platform_role,
        "is_active": True,
    }


async def link_identity(
    user_id: str,
    provider: str,
    provider_sub: str,
    provider_issuer: Optional[str] = None,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> str:
    """Link an external identity to a Wiii user. Returns identity ID."""
    identity_id = str(uuid.uuid4())
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_identities (id, user_id, provider, provider_sub, provider_issuer, email, display_name, avatar_url, linked_at, last_used_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
            ON CONFLICT (provider, provider_sub, provider_issuer) DO UPDATE
              SET last_used_at = NOW(), email = EXCLUDED.email, display_name = EXCLUDED.display_name, avatar_url = EXCLUDED.avatar_url
            """,
            identity_id, user_id, provider, provider_sub, provider_issuer, email, display_name, avatar_url,
        )
    logger.info(
        "Linked identity provider=%s provider_sub_ref=%s user_ref=%s",
        provider,
        _auth_identity_ref(provider_sub),
        _auth_identity_ref(user_id),
    )

    # Sprint 176: Audit event
    try:
        from app.auth.auth_audit import log_auth_event
        await log_auth_event(
            "identity_linked", user_id=user_id, provider=provider,
            metadata={"provider_sub_ref": _auth_identity_ref(provider_sub)},
        )
    except Exception:
        pass

    return identity_id


# ---------------------------------------------------------------------------
# Sprint 158: Generalized provider federation
# ---------------------------------------------------------------------------

async def find_or_create_by_provider(
    provider: str,
    provider_sub: str,
    provider_issuer: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    role: str = "student",
    auto_create: bool = True,
    email_verified: bool = False,
) -> Optional[dict]:
    """
    Find existing user by provider identity or create a new one.

    Strategy:
    1. Look up by (provider, provider_sub, provider_issuer) → exact match
    2. Look up by email → auto-link provider identity (only when email_verified)
    3. Create new user + link provider identity (if auto_create=True)

    Sprint 160b: email_verified guard — only auto-link to existing accounts when the
    provider has verified the email address. Prevents account hijacking via unverified email.

    Returns user dict or None (only when auto_create=False and not found).
    """
    # 1. Exact provider match
    user = await find_user_by_provider(provider, provider_sub, provider_issuer)
    if user:
        logger.debug(
            "%s login: existing user_ref=%s",
            provider,
            _auth_identity_ref(user["id"]),
        )
        return user

    # 2. Email match → auto-link (only when email is verified by provider)
    if email:
        user = await find_user_by_email(email)
        if user:
            if email_verified:
                await link_identity(
                    user_id=user["id"],
                    provider=provider,
                    provider_sub=provider_sub,
                    provider_issuer=provider_issuer,
                    email=email,
                    display_name=name,
                    avatar_url=avatar_url,
                )
                logger.info(
                    "%s login: auto-linked existing user_ref=%s email_ref=%s",
                    provider,
                    _auth_identity_ref(user["id"]),
                    _auth_identity_ref(email),
                )
                return user
            else:
                logger.warning(
                    "SECURITY: %s login attempted auto-link "
                    "UNVERIFIED email user_ref=%s email_ref=%s "
                    "email_verified=false blocked",
                    provider,
                    _auth_identity_ref(user["id"]),
                    _auth_identity_ref(email),
                )
                # Fall through to step 3 (create new account)

    # 3. New user
    if not auto_create:
        return None

    user = await create_user(email=email, name=name, avatar_url=avatar_url, role=role)
    await link_identity(
        user_id=user["id"],
        provider=provider,
        provider_sub=provider_sub,
        provider_issuer=provider_issuer,
        email=email,
        display_name=name,
        avatar_url=avatar_url,
    )
    logger.info(
        "%s login: created new user_ref=%s email_ref=%s",
        provider,
        _auth_identity_ref(user["id"]),
        _auth_identity_ref(email),
    )
    return user


async def find_or_create_by_google(
    google_sub: str,
    email: str,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    email_verified: bool = True,
) -> dict:
    """
    Backward-compatible wrapper — delegates to find_or_create_by_provider.

    Sprint 160b: Passes email_verified through for auto-link security.
    Google emails are verified by default (Google OIDC guarantees this).
    """
    result = await find_or_create_by_provider(
        provider="google",
        provider_sub=google_sub,
        email=email,
        name=name,
        avatar_url=avatar_url,
        email_verified=email_verified,
    )
    # find_or_create_by_provider always returns a user when auto_create=True (default)
    assert result is not None
    return result


# ---------------------------------------------------------------------------
# Sprint 158: CRUD operations
# ---------------------------------------------------------------------------

async def get_user(user_id: str) -> Optional[dict]:
    """Get a user by ID. Returns full user dict or None."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "SELECT id, email, name, avatar_url, role, platform_role, is_active, created_at, updated_at FROM users WHERE id = $1",
                user_id,
            )
        except Exception as e:
            if "platform_role" not in str(e):
                raise
            row = await conn.fetchrow(
                "SELECT id, email, name, avatar_url, role, is_active, created_at, updated_at FROM users WHERE id = $1",
                user_id,
            )
        if row:
            return _format_user_row(dict(row))
    return None


async def update_user(user_id: str, name: Optional[str] = None, avatar_url: Optional[str] = None) -> Optional[dict]:
    """Update user profile fields. Returns updated user or None if not found."""
    sets = []
    params = []
    idx = 1

    if name is not None:
        sets.append(f"name = ${idx}")
        params.append(name)
        idx += 1

    if avatar_url is not None:
        sets.append(f"avatar_url = ${idx}")
        params.append(avatar_url)
        idx += 1

    if not sets:
        return await get_user(user_id)

    sets.append(f"updated_at = ${idx}")
    params.append(datetime.now(timezone.utc))
    idx += 1

    params.append(user_id)

    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ${idx}",
            *params,
        )
        if result == "UPDATE 0":
            return None
    return await get_user(user_id)


async def update_user_role(
    user_id: str,
    new_role: Optional[str] = None,
    platform_role: Optional[str] = None,
) -> Optional[dict]:
    """Update compatibility role and/or platform role for a user."""
    if new_role is None and platform_role is None:
        raise ValueError("At least one of role or platform_role is required")
    if new_role is not None and new_role not in _VALID_ROLES:
        raise ValueError(f"Invalid role '{new_role}'. Must be one of: {', '.join(sorted(_VALID_ROLES))}")
    if platform_role is not None:
        normalized_platform_role = platform_role.strip().lower()
        if normalized_platform_role not in _VALID_PLATFORM_ROLES:
            raise ValueError(
                f"Invalid platform_role '{platform_role}'. Must be one of: {', '.join(sorted(_VALID_PLATFORM_ROLES))}"
            )
        platform_role = normalized_platform_role

    sets = []
    params = []
    idx = 1

    if new_role is not None:
        sets.append(f"role = ${idx}")
        params.append(new_role)
        idx += 1
    if platform_role is not None:
        sets.append(f"platform_role = ${idx}")
        params.append(platform_role)
        idx += 1

    sets.append(f"updated_at = ${idx}")
    params.append(datetime.now(timezone.utc))
    idx += 1
    params.append(user_id)

    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            result = await conn.execute(
                f"UPDATE users SET {', '.join(sets)} WHERE id = ${idx}",
                *params,
            )
        except Exception as e:
            if "platform_role" not in str(e) or platform_role is None:
                raise
            if new_role is None:
                if platform_role == "platform_admin":
                    new_role = "admin"
                else:
                    raise ValueError(
                        "Legacy schema requires an explicit compatibility role when platform_role='user'"
                    )
            legacy_sets = []
            legacy_params = []
            legacy_idx = 1
            if new_role is not None:
                legacy_sets.append(f"role = ${legacy_idx}")
                legacy_params.append(new_role)
                legacy_idx += 1
            legacy_sets.append(f"updated_at = ${legacy_idx}")
            legacy_params.append(datetime.now(timezone.utc))
            legacy_idx += 1
            legacy_params.append(user_id)
            result = await conn.execute(
                f"UPDATE users SET {', '.join(legacy_sets)} WHERE id = ${legacy_idx}",
                *legacy_params,
            )
        if result == "UPDATE 0":
            return None
    return await get_user(user_id)


async def deactivate_user(user_id: str) -> Optional[dict]:
    """Soft-delete a user (set is_active=false) and revoke all tokens."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET is_active = false, updated_at = $1 WHERE id = $2",
            datetime.now(timezone.utc), user_id,
        )
        if result == "UPDATE 0":
            return None

    # Revoke all refresh tokens
    from app.auth.token_service import revoke_user_tokens
    await revoke_user_tokens(user_id)
    logger.info("Deactivated user user_ref=%s", _auth_identity_ref(user_id))

    return await get_user(user_id)


async def reactivate_user(user_id: str) -> Optional[dict]:
    """Re-enable a deactivated user (set is_active=true)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET is_active = true, updated_at = $1 WHERE id = $2",
            datetime.now(timezone.utc), user_id,
        )
        if result == "UPDATE 0":
            return None
    logger.info("Reactivated user user_ref=%s", _auth_identity_ref(user_id))
    return await get_user(user_id)


async def list_user_identities(user_id: str) -> list[dict]:
    """List all linked identities for a user."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, provider, provider_sub, provider_issuer, email, display_name, avatar_url, linked_at, last_used_at
            FROM user_identities
            WHERE user_id = $1
            ORDER BY linked_at
            """,
            user_id,
        )
        result = []
        for row in rows:
            d = dict(row)
            for key in ("linked_at", "last_used_at"):
                if d.get(key) and hasattr(d[key], "isoformat"):
                    d[key] = d[key].isoformat()
            result.append(d)
        return result


async def unlink_identity(user_id: str, identity_id: str) -> bool:
    """
    Unlink an identity from a user.

    Safety: refuses to unlink if it's the user's last identity.
    Returns True if unlinked, False if not found.
    Raises ValueError if it's the last identity.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Count identities
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM user_identities WHERE user_id = $1",
            user_id,
        )
        if count <= 1:
            raise ValueError("Cannot unlink the last identity — user would be orphaned")

        result = await conn.execute(
            "DELETE FROM user_identities WHERE id = $1 AND user_id = $2",
            identity_id, user_id,
        )
        deleted = int(result.split()[-1])
        if deleted == 0:
            return False

        logger.info(
            "Unlinked identity identity_ref=%s user_ref=%s",
            _auth_identity_ref(identity_id),
            _auth_identity_ref(user_id),
        )

        # Sprint 176: Audit event
        try:
            from app.auth.auth_audit import log_auth_event
            await log_auth_event(
                "identity_unlinked", user_id=user_id,
                metadata={"identity_ref": _auth_identity_ref(identity_id)},
            )
        except Exception:
            pass

        return True


# ---------------------------------------------------------------------------
# Sprint 220c: Reverse-lookup (Wiii UUID → external identity)
# ---------------------------------------------------------------------------

async def find_external_identity(
    user_id: str,
    provider: str,
    provider_issuer: Optional[str] = None,
) -> Optional[dict]:
    """
    Reverse-lookup: Wiii UUID → external identity.

    Used to resolve the original LMS user ID from a Wiii user,
    so LMS APIs can be called with the ID they recognize.

    Returns dict with {provider_sub, provider_issuer, email, display_name} or None.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if provider_issuer:
            row = await conn.fetchrow(
                """
                SELECT provider_sub, provider_issuer, email, display_name
                FROM user_identities
                WHERE user_id = $1 AND provider = $2 AND provider_issuer = $3
                ORDER BY last_used_at DESC
                LIMIT 1
                """,
                user_id, provider, provider_issuer,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT provider_sub, provider_issuer, email, display_name
                FROM user_identities
                WHERE user_id = $1 AND provider = $2
                ORDER BY last_used_at DESC
                LIMIT 1
                """,
                user_id, provider,
            )
        if row:
            return dict(row)
    return None


async def list_users(
    org_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Paginated user list. Optionally filtered by organization.
    Returns (users, total_count).
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if org_id:
            total = await conn.fetchval(
                """
                SELECT COUNT(*) FROM users u
                JOIN user_organizations uo ON uo.user_id = u.id
                WHERE uo.organization_id = $1
                """,
                org_id,
            )
            try:
                rows = await conn.fetch(
                    """
                    SELECT u.id, u.email, u.name, u.avatar_url, u.role, u.platform_role, u.is_active, u.created_at
                    FROM users u
                    JOIN user_organizations uo ON uo.user_id = u.id
                    WHERE uo.organization_id = $1
                    ORDER BY u.created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    org_id, limit, offset,
                )
            except Exception as e:
                if "platform_role" not in str(e):
                    raise
                rows = await conn.fetch(
                    """
                    SELECT u.id, u.email, u.name, u.avatar_url, u.role, u.is_active, u.created_at
                    FROM users u
                    JOIN user_organizations uo ON uo.user_id = u.id
                    WHERE uo.organization_id = $1
                    ORDER BY u.created_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    org_id, limit, offset,
                )
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM users")
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, email, name, avatar_url, role, platform_role, is_active, created_at
                    FROM users
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit, offset,
                )
            except Exception as e:
                if "platform_role" not in str(e):
                    raise
                rows = await conn.fetch(
                    """
                    SELECT id, email, name, avatar_url, role, is_active, created_at
                    FROM users
                    ORDER BY created_at DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit, offset,
                )

        users = []
        for row in rows:
            users.append(_format_user_row(dict(row)))
        return users, total
