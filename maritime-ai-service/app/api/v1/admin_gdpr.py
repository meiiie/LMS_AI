"""
Sprint 178: GDPR Compliance API — Phase 3

Endpoints:
  POST /admin/users/{user_id}/export  — Export all user data (GDPR Article 15)
  POST /admin/users/{user_id}/forget  — Right to be forgotten (GDPR Article 17)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.admin_security import check_admin_module as _check_admin_module
from app.api.deps import RequireAdmin
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-gdpr"])


async def _get_pool():
    from app.core.database import get_asyncpg_pool
    return await get_asyncpg_pool()


def _resolve_gdpr_memory_org(auth: RequireAdmin) -> Optional[str]:
    """Resolve active org for GDPR semantic-memory export/delete SQL."""
    if not settings.enable_multi_tenant:
        return None
    org_id = getattr(auth, "organization_id", None)
    if isinstance(org_id, str) and org_id.strip():
        return org_id.strip()
    raise HTTPException(
        status_code=403,
        detail="Active organization is required for GDPR memory operations.",
    )


# =============================================================================
# POST /admin/users/{user_id}/export
# =============================================================================

@router.post(
    "/users/{user_id}/export",
    dependencies=[Depends(_check_admin_module)],
)
async def gdpr_export(user_id: str, request: Request, auth: RequireAdmin):
    """Export all data for a user (GDPR Article 15 — Right of Access)."""
    memory_org_id = _resolve_gdpr_memory_org(auth)
    pool = await _get_pool()

    async with pool.acquire() as conn:
        # Profile
        try:
            profile = await conn.fetchrow(
                "SELECT id, email, name, role, platform_role, is_active, created_at FROM users WHERE id = $1",
                user_id,
            )
        except Exception as exc:
            if "platform_role" not in str(exc):
                raise
            profile = await conn.fetchrow(
                "SELECT id, email, name, role, is_active, created_at FROM users WHERE id = $1",
                user_id,
            )
        if not profile:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")

        profile_data = {
            "id": str(profile["id"]),
            "email": profile["email"],
            "name": profile["name"],
            "role": profile["role"],
            "platform_role": profile.get(
                "platform_role",
                "platform_admin" if str(profile["role"]).lower() == "admin" else "user",
            ),
            "is_active": profile["is_active"],
            "created_at": profile["created_at"].isoformat() if profile["created_at"] else None,
        }

        # Identities
        identities = []
        try:
            id_rows = await conn.fetch(
                "SELECT provider, provider_user_id, email, created_at "
                "FROM user_identities WHERE user_id = $1",
                user_id,
            )
            identities = [
                {
                    "provider": r["provider"],
                    "provider_user_id": r["provider_user_id"],
                    "email": r["email"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in id_rows
            ]
        except Exception as exc:
            logger.warning("[GDPR] Data collection partial failure: %s", exc)

        # Memories
        memories = []
        try:
            mem_query = (
                "SELECT memory_type, content, importance, created_at "
                "FROM semantic_memories WHERE user_id = $1"
            )
            mem_params = [user_id]
            if memory_org_id:
                mem_query += " AND organization_id = $2"
                mem_params.append(memory_org_id)
            mem_query += " ORDER BY created_at DESC LIMIT 500"
            mem_rows = await conn.fetch(mem_query, *mem_params)
            memories = [
                {
                    "memory_type": r["memory_type"],
                    "content": r["content"],
                    "importance": float(r["importance"]) if r["importance"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in mem_rows
            ]
        except Exception as exc:
            logger.warning("[GDPR] Data collection partial failure: %s", exc)

        # Auth events
        auth_events = []
        try:
            ae_rows = await conn.fetch(
                "SELECT event_type, provider, result, reason, ip_address, created_at "
                "FROM auth_events WHERE user_id = $1 ORDER BY created_at DESC LIMIT 500",
                user_id,
            )
            auth_events = [
                {
                    "event_type": r["event_type"],
                    "provider": r["provider"],
                    "result": r["result"],
                    "reason": r["reason"],
                    "ip_address": r["ip_address"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in ae_rows
            ]
        except Exception as exc:
            logger.warning("[GDPR] Data collection partial failure: %s", exc)

        # Admin audit entries related to this user
        audit_entries = []
        try:
            audit_rows = await conn.fetch(
                "SELECT action, target_type, target_id, occurred_at "
                "FROM admin_audit_log WHERE actor_id = $1 OR target_id = $1 "
                "ORDER BY occurred_at DESC LIMIT 500",
                user_id,
            )
            audit_entries = [
                {
                    "action": r["action"],
                    "target_type": r["target_type"],
                    "target_id": r["target_id"],
                    "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
                }
                for r in audit_rows
            ]
        except Exception as exc:
            logger.warning("[GDPR] Data collection partial failure: %s", exc)

    # Audit the export itself
    from app.services.admin_audit import log_admin_action, extract_audit_context
    ctx = extract_audit_context(request)
    await log_admin_action(
        actor_id=auth.user_id,
        action="gdpr.export",
        target_type="user",
        target_id=user_id,
        **ctx,
    )

    return {
        "user_id": user_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "profile": profile_data,
            "identities": identities,
            "memories": memories,
            "auth_events": auth_events,
            "audit_entries": audit_entries,
        },
    }


# =============================================================================
# POST /admin/users/{user_id}/forget
# =============================================================================

class ForgetBody(BaseModel):
    confirm: bool


@router.post(
    "/users/{user_id}/forget",
    dependencies=[Depends(_check_admin_module)],
)
async def gdpr_forget(user_id: str, body: ForgetBody, request: Request, auth: RequireAdmin):
    """Right to be forgotten (GDPR Article 17). Requires confirm=true."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Must set confirm=true to proceed with data deletion")

    memory_org_id = _resolve_gdpr_memory_org(auth)
    pool = await _get_pool()

    async with pool.acquire() as conn:
        # Check user exists
        user = await conn.fetchrow("SELECT id, name, email FROM users WHERE id = $1", user_id)
        if not user:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")

        # All deletions in a single transaction — partial deletion is worse than no deletion
        async with conn.transaction():
            # 1. Anonymize profile
            await conn.execute(
                """
                UPDATE users SET name = '[Deleted User]', email = NULL, avatar_url = NULL,
                                 is_active = false WHERE id = $1
                """,
                user_id,
            )

            # 2. Delete user identities
            identities_deleted = await conn.execute(
                "DELETE FROM user_identities WHERE user_id = $1", user_id
            )

            # 3. Revoke refresh tokens
            tokens_deleted = await conn.execute(
                "DELETE FROM refresh_tokens WHERE user_id = $1", user_id
            )

            # 4. Delete semantic memories
            if memory_org_id:
                memories_deleted = await conn.execute(
                    "DELETE FROM semantic_memories WHERE user_id = $1 AND organization_id = $2",
                    user_id,
                    memory_org_id,
                )
            else:
                memories_deleted = await conn.execute(
                    "DELETE FROM semantic_memories WHERE user_id = $1",
                    user_id,
                )

    # 5. Log audit (does NOT delete audit logs — regulatory requirement)
    from app.services.admin_audit import log_admin_action, extract_audit_context
    ctx = extract_audit_context(request)
    await log_admin_action(
        actor_id=auth.user_id,
        action="gdpr.forget",
        target_type="user",
        target_id=user_id,
        target_name=user["name"],
        **ctx,
    )

    def _count(result_str):
        try:
            return int(result_str.split()[-1])
        except Exception:
            return 0

    return {
        "user_id": user_id,
        "status": "forgotten",
        "profile_anonymized": True,
        "identities_deleted": _count(identities_deleted),
        "tokens_revoked": _count(tokens_deleted),
        "memories_deleted": _count(memories_deleted),
        "audit_logs_preserved": True,
    }
