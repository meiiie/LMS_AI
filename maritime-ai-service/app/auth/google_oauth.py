"""
Sprint 157: Google OAuth 2.0 routes — login, callback, desktop callback.
Sprint 193: Web OAuth — redirect_uri param for hash-based token delivery.

Uses Authlib for OAuth 2.0 Authorization Code + PKCE flow.
Desktop apps use a localhost redirect via tauri-plugin-oauth.
Web apps use redirect_uri with hash fragment tokens.
"""
import logging
from typing import Optional
from urllib.parse import urlencode, urlparse

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.auth.organization_context import (
    ensure_user_org_membership,
    resolve_default_login_organization_id,
)
from app.auth.token_service import create_token_pair, refresh_access_token, revoke_user_tokens
from app.auth.user_service import find_or_create_by_google
from app.core.config import settings
from app.core.security import AuthenticatedUser, require_auth
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_MAX_OAUTH_DIAGNOSTIC_LENGTH = 500

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Authlib OAuth client setup
# ---------------------------------------------------------------------------
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_oauth_client_id or "",
    client_secret=settings.google_oauth_client_secret or "",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


def _get_redirect_uri(request: Request, desktop_port: Optional[int] = None) -> str:
    """Build the callback URL. Uses oauth_redirect_base_url if configured."""
    base = settings.oauth_redirect_base_url or str(request.base_url).rstrip("/")
    prefix = settings.api_v1_prefix.rstrip("/")
    if desktop_port:
        return f"{base}{prefix}/auth/google/callback/desktop?port={desktop_port}"
    return f"{base}{prefix}/auth/google/callback"


def _oauth_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_oauth_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    for secret_value in secret_values:
        secret = str(secret_value or "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    return redact_runtime_secret_text(text, max_length=_MAX_OAUTH_DIAGNOSTIC_LENGTH)


# ---------------------------------------------------------------------------
# Web login flow
# ---------------------------------------------------------------------------

def _validate_redirect_origin(redirect_uri: str) -> bool:
    """Validate redirect_uri against allowed origins whitelist.

    Sprint 193: Prevents open redirect attacks by only allowing
    pre-configured origins.
    """
    allowed_raw = settings.oauth_allowed_redirect_origins
    if not allowed_raw:
        return False
    allowed = [o.strip().rstrip("/") for o in allowed_raw.split(",") if o.strip()]
    parsed = urlparse(redirect_uri)
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return origin in allowed


@router.get("/google/login")
async def google_login(
    request: Request,
    port: Optional[int] = Query(None, description="Desktop app localhost port for OAuth redirect"),
    redirect_uri: Optional[str] = Query(None, description="Web app redirect URI (Sprint 193)"),
):
    """
    Initiate Google OAuth flow.

    For desktop apps: pass ?port=XXXXX — callback will redirect to localhost:{port}.
    For web apps: pass ?redirect_uri=https://... — callback redirects with hash tokens.
    Fallback: returns JSON with tokens.
    """
    if not settings.enable_google_oauth:
        raise HTTPException(status_code=404, detail="Google OAuth is not enabled")

    # Sprint 193: Validate redirect_uri against whitelist
    if redirect_uri:
        if not _validate_redirect_origin(redirect_uri):
            raise HTTPException(
                status_code=400,
                detail="redirect_uri origin not in allowed list",
            )
        request.session["web_redirect_uri"] = redirect_uri

    # Store desktop port in session for callback
    if port:
        request.session["desktop_port"] = port

    redirect_uri_for_google = _get_redirect_uri(request, desktop_port=None)  # Always callback to server first
    return await oauth.google.authorize_redirect(request, redirect_uri_for_google)


@router.get("/google/callback")
async def google_callback(request: Request):
    """
    Handle Google OAuth callback.

    For desktop: redirects to localhost:{port} with token.
    For web: returns JSON with token pair.
    """
    if not settings.enable_google_oauth:
        raise HTTPException(status_code=404, detail="Google OAuth is not enabled")

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        logger.error("OAuth token exchange failed")
        # Sprint 176: Audit failed login
        try:
            from app.auth.auth_audit import log_auth_event
            await log_auth_event(
                "login_failed", provider="google", result="failed",
                reason="google_oauth_exchange_failed",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Xác thực Google thất bại. Vui lòng thử lại.")

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Không lấy được thông tin từ Google. Vui lòng thử lại.")

    google_sub = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name", "")
    picture = userinfo.get("picture", "")
    email_verified = userinfo.get("email_verified", False)

    if not email:
        raise HTTPException(status_code=400, detail="Tài khoản Google không có email. Vui lòng dùng tài khoản khác.")

    # Find or create Wiii user (Sprint 160b: pass email_verified for auto-link security)
    user = await find_or_create_by_google(
        google_sub=google_sub,
        email=email,
        name=name,
        avatar_url=picture,
        email_verified=bool(email_verified),
    )

    assigned_org_id = resolve_default_login_organization_id(settings)
    if assigned_org_id:
        ensured = await ensure_user_org_membership(user["id"], assigned_org_id)
        if ensured:
            logger.info("Auto-assigned Google OAuth user to default organization")

    # Create token pair
    token_pair = await create_token_pair(
        user_id=user["id"],
        email=user.get("email"),
        name=user.get("name"),
        role=user.get("role", "student"),
        platform_role=user.get("platform_role"),
        role_source="platform",
        active_organization_id=assigned_org_id,
        auth_method="google",
    )

    # Sprint 176: Audit successful login
    try:
        from app.auth.auth_audit import log_auth_event
        await log_auth_event(
            "login", user_id=user["id"], provider="google",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception:
        pass

    # Sprint 193b: organization_id for frontend mirrors the token claim.
    assigned_org_id = assigned_org_id or ""

    # Build common token params (reused by desktop + web redirect flows)
    token_params = urlencode({
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "expires_in": token_pair.expires_in,
        "user_id": user["id"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "avatar_url": user.get("avatar_url", ""),
        "role": user.get("role", "student"),  # Sprint 192: role from backend
        "legacy_role": user.get("role", "student"),
        "platform_role": user.get("platform_role", "user"),
        "role_source": "platform",
        "active_organization_id": assigned_org_id,
        "organization_id": assigned_org_id,  # Sprint 193b: org context for frontend
    })

    # Check if this is a desktop OAuth flow
    desktop_port = request.session.pop("desktop_port", None)
    if desktop_port:
        # Redirect to Tauri localhost server
        # Sprint 160b: Use URL fragment (#) instead of query (?) — fragments are never
        # sent to the server in HTTP requests, preventing token leakage to logs/proxies.
        redirect_url = f"http://127.0.0.1:{desktop_port}#{token_params}"
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wiii — Đăng nhập thành công</title></head>
<body style="font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;background:#faf9f7">
<div style="text-align:center">
<h2 style="color:#c75b1e">Đăng nhập thành công!</h2>
<p style="color:#666">Đang quay lại Wiii...</p>
<script>window.location.href="{redirect_url}";</script>
</div></body></html>""")

    # Sprint 193: Check web redirect URI flow
    web_redirect_uri = request.session.pop("web_redirect_uri", None)
    if web_redirect_uri:
        # Redirect back to web app with hash fragment tokens
        redirect_url = f"{web_redirect_uri.rstrip('/')}#{token_params}"
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wiii — Đăng nhập thành công</title></head>
<body style="font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;background:#faf9f7">
<div style="text-align:center">
<h2 style="color:#c75b1e">Đăng nhập thành công!</h2>
<p style="color:#666">Đang quay lại Wiii...</p>
<script>window.location.href="{redirect_url}";</script>
</div></body></html>""")

    # Fallback: return JSON
    return JSONResponse({
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "token_type": "bearer",
        "expires_in": token_pair.expires_in,
        "organization_id": assigned_org_id,  # Sprint 193b
        "user": {
            "id": user["id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "avatar_url": user.get("avatar_url"),
            "role": user.get("role", "student"),
            "legacy_role": user.get("role", "student"),
            "platform_role": user.get("platform_role"),
            "role_source": "platform",
            "active_organization_id": assigned_org_id,
        },
    })


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/token/refresh")
async def token_refresh(body: RefreshTokenRequest):
    """Refresh an access token using a refresh token."""
    result = await refresh_access_token(body.refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return JSONResponse({
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "token_type": "bearer",
        "expires_in": result.expires_in,
    })


@router.post("/logout")
async def logout(
    request: Request,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Revoke all refresh tokens for the authenticated user (logout everywhere).

    Sprint 192: Also denies the current access token's JTI so it cannot be
    reused for the remainder of its lifetime.
    """
    count = await revoke_user_tokens(auth.user_id)

    # Sprint 192: Deny current access token's JTI (JWT auth only)
    if settings.enable_jti_denylist and auth.auth_method != "api_key":
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from app.auth.token_service import verify_access_token, deny_jti
                payload = verify_access_token(auth_header.split(" ", 1)[1])
                if payload.jti:
                    deny_jti(payload.jti)
            except Exception:
                pass  # JTI denial is best-effort

    # Sprint 176: Audit logout
    try:
        from app.auth.auth_audit import log_auth_event
        await log_auth_event(
            "logout", user_id=auth.user_id, provider=auth.auth_method,
            ip_address=request.client.host if request.client else None,
            metadata={"revoked_count": count},
        )
    except Exception:
        pass

    return JSONResponse({"revoked": count, "message": "Logged out successfully"})


@router.get("/me")
async def get_current_user(
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Get the current authenticated user's profile."""
    # Fetch full user from DB
    try:
        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, name, avatar_url, role, platform_role, is_active, created_at FROM users WHERE id = $1",
                auth.user_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            if not row["is_active"]:
                raise HTTPException(status_code=403, detail="Tài khoản đã bị vô hiệu hóa.")
            return JSONResponse({
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
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            })
    except HTTPException:
        raise
    except Exception:
        # Fallback to auth claims
        return JSONResponse({
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
        })
