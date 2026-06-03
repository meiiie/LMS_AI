"""Organization helpers shared by auth token issuers."""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def normalize_organization_id(value: Optional[str]) -> Optional[str]:
    """Return a trimmed organization id or None for empty/non-string values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def resolve_default_login_organization_id(config=settings) -> Optional[str]:
    """Resolve the org assigned to first-party login flows."""
    if not bool(getattr(config, "enable_multi_tenant", False)):
        return None
    return normalize_organization_id(getattr(config, "default_organization_id", None))


async def ensure_user_org_membership(
    user_id: str,
    organization_id: Optional[str],
    *,
    role: str = "member",
) -> bool:
    """Best-effort org membership insert for first-party login flows."""
    org_id = normalize_organization_id(organization_id)
    if not user_id or not org_id:
        return False

    try:
        from app.core.database import get_asyncpg_pool

        pool = await get_asyncpg_pool(create=True)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_organizations (user_id, organization_id, role, joined_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (user_id, organization_id) DO NOTHING
                """,
                user_id,
                org_id,
                role,
            )
        return True
    except Exception as exc:
        logger.warning(
            "Failed to ensure user %s membership in org %s: %s",
            user_id,
            org_id,
            exc,
        )
        return False
