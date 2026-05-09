"""Authentication token management routes.

These endpoints are intentionally independent from Google OAuth registration.
Local dev-login, magic-link, LMS, and OAuth sessions all need refresh/logout/me
even when optional provider SDKs such as authlib are not installed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.token_service import refresh_access_token, revoke_user_tokens
from app.core.config import settings
from app.core.security import AuthenticatedUser, require_auth

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/token/refresh")
async def token_refresh(body: RefreshTokenRequest) -> JSONResponse:
    """Refresh an access token using a persisted or signed fallback refresh token."""
    result = await refresh_access_token(body.refresh_token)
    if not result:
        return JSONResponse(
            {"detail": "Invalid or expired refresh token"},
            status_code=401,
        )

    return JSONResponse(
        {
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": "bearer",
            "expires_in": result.expires_in,
        }
    )


@router.post("/logout")
async def logout(
    request: Request,
    auth: AuthenticatedUser = Depends(require_auth),
) -> JSONResponse:
    """Revoke persisted refresh tokens and deny the current access-token JTI."""
    count = await revoke_user_tokens(auth.user_id)

    if settings.enable_jti_denylist and auth.auth_method != "api_key":
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.auth.token_service import deny_jti, verify_access_token

                payload = verify_access_token(auth_header.split(" ", 1)[1])
                if payload.jti:
                    deny_jti(payload.jti)
            except Exception:
                pass

    try:
        from app.auth.auth_audit import log_auth_event

        await log_auth_event(
            "logout",
            user_id=auth.user_id,
            provider=auth.auth_method,
            ip_address=request.client.host if request.client else None,
            metadata={"revoked_count": count},
        )
    except Exception:
        pass

    return JSONResponse({"revoked": count, "message": "Logged out successfully"})


@router.get("/me")
async def get_current_user(
    auth: AuthenticatedUser = Depends(require_auth),
) -> JSONResponse:
    """Get the current authenticated user's profile."""
    try:
        from app.core.database import get_asyncpg_pool

        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, name, avatar_url, role, platform_role, is_active, created_at FROM users WHERE id = $1",
                auth.user_id,
            )
            if not row:
                return JSONResponse({"detail": "User not found"}, status_code=404)
            if not row["is_active"]:
                return JSONResponse(
                    {"detail": "Tai khoan da bi vo hieu hoa."},
                    status_code=403,
                )
            return JSONResponse(
                {
                    "id": row["id"],
                    "email": row["email"],
                    "name": row["name"],
                    "avatar_url": row["avatar_url"],
                    "role": row["role"],
                    "legacy_role": row["role"],
                    "platform_role": auth.platform_role or row.get("platform_role"),
                    "organization_role": auth.organization_role,
                    "host_role": auth.host_role,
                    "role_source": auth.role_source,
                    "active_organization_id": auth.organization_id,
                    "connector_id": auth.connector_id,
                    "identity_version": auth.identity_version,
                    "is_active": row["is_active"],
                    "created_at": row["created_at"].isoformat()
                    if row["created_at"]
                    else None,
                }
            )
    except Exception:
        return JSONResponse(
            {
                "id": auth.user_id,
                "role": auth.role,
                "legacy_role": auth.role,
                "platform_role": auth.platform_role,
                "organization_role": auth.organization_role,
                "host_role": auth.host_role,
                "role_source": auth.role_source,
                "active_organization_id": auth.organization_id,
                "connector_id": auth.connector_id,
                "identity_version": auth.identity_version,
            }
        )
