"""
Sprint 224: Magic Link Email Auth Router.

Endpoints:
  POST /auth/magic-link/request         -- Send magic link to email
  GET  /auth/magic-link/verify/{token}  -- Verify magic link + push JWT via WS
  WS   /auth/magic-link/ws/{session_id} -- WebSocket waiting for verification
"""
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.email_service import send_magic_link_email
from app.auth.organization_context import (
    ensure_user_org_membership,
    resolve_default_login_organization_id,
)
from app.auth.magic_link_service import (
    generate_magic_token,
    get_session_manager,
    hash_token,
    is_token_expired,
    is_token_used,
    validate_email,
)
from app.core.config import settings
from app.core.secret_validation import is_missing_or_placeholder_secret
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_REDACTED_SECRET = "<redacted-secret>"
_MAX_MAGIC_LINK_DIAGNOSTIC_LENGTH = 500


def _magic_link_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_magic_link_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    seen: set[str] = set()
    for raw_secret in secret_values:
        secret = str(raw_secret or "")
        if not secret or secret in seen:
            continue
        seen.add(secret)
        text = text.replace(secret, _REDACTED_SECRET)
    return redact_runtime_secret_text(
        text,
        max_length=_MAX_MAGIC_LINK_DIAGNOSTIC_LENGTH,
    )

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth/magic-link", tags=["auth-magic-link"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MagicLinkRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)


class MagicLinkResponse(BaseModel):
    session_id: str
    message: str
    expires_in: int


# ---------------------------------------------------------------------------
# HTML page helpers
# ---------------------------------------------------------------------------

def _success_page(ws_pushed: bool) -> HTMLResponse:
    """Return Vietnamese success HTML page."""
    if ws_pushed:
        body = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wiii - Xác minh thành công</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 480px; margin: 0 auto; padding: 60px 20px; text-align: center; color: #1a1a1a;">
  <h1 style="font-size: 28px; color: #E8713A;">Xác minh thành công!</h1>
  <p style="font-size: 16px; line-height: 1.6;">Bạn đã đăng nhập thành công. Bạn có thể đóng tab này và quay lại ứng dụng Wiii.</p>
  <p style="font-size: 14px; color: #666; margin-top: 24px;">by The Wiii Lab</p>
</body></html>
"""
    else:
        body = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wiii - Xác minh thành công</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 480px; margin: 0 auto; padding: 60px 20px; text-align: center; color: #1a1a1a;">
  <h1 style="font-size: 28px; color: #E8713A;">Xác minh thành công!</h1>
  <p style="font-size: 16px; line-height: 1.6;">Email đã được xác minh. Vui lòng quay lại ứng dụng Wiii và thử lại đăng nhập.</p>
  <p style="font-size: 14px; color: #999; margin-top: 16px;">(Phiên WebSocket đã hết hạn. Hãy thử lại từ đầu.)</p>
  <p style="font-size: 14px; color: #666; margin-top: 24px;">by The Wiii Lab</p>
</body></html>
"""
    return HTMLResponse(content=body.strip(), status_code=200)


def _error_page(message: str) -> HTMLResponse:
    """Return Vietnamese error HTML page with 400 status."""
    body = f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Wiii - Lỗi xác minh</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 480px; margin: 0 auto; padding: 60px 20px; text-align: center; color: #1a1a1a;">
  <h1 style="font-size: 28px; color: #dc3545;">Lỗi xác minh</h1>
  <p style="font-size: 16px; line-height: 1.6; color: #333;">{message}</p>
  <p style="font-size: 14px; color: #666; margin-top: 24px;">by The Wiii Lab</p>
</body></html>
"""
    return HTMLResponse(content=body.strip(), status_code=400)


# ---------------------------------------------------------------------------
# Core logic -- extracted for testability
# ---------------------------------------------------------------------------

async def _create_magic_link(email: str, conn) -> dict:
    """Create a magic link token, store in DB, and send email.

    Args:
        email: Validated email address.
        conn: asyncpg connection (passed in for testability).

    Returns:
        dict with session_id, message, expires_in.

    Raises:
        HTTPException: on rate limit, email send failure, etc.
    """
    # ---- Rate-limit check (per-email, last hour) ----
    count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM magic_link_tokens
        WHERE email = $1 AND created_at > NOW() - INTERVAL '1 hour'
        """,
        email,
    )
    if count >= settings.magic_link_max_per_hour:
        raise HTTPException(
            status_code=429,
            detail="Too many magic link requests. Vui lòng thử lại sau.",
        )

    # ---- Generate token + session ----
    raw_token, token_hash = generate_magic_token()
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.magic_link_expires_seconds)

    # ---- Store in DB ----
    await conn.execute(
        """
        INSERT INTO magic_link_tokens (token_hash, email, ws_session_id, expires_at, created_at)
        VALUES ($1, $2, $3, $4, NOW())
        """,
        token_hash, email, session_id, expires_at,
    )

    # ---- Build verify URL and send email ----
    base_url = settings.magic_link_base_url.rstrip("/")
    prefix = settings.api_v1_prefix.rstrip("/")
    verify_url = f"{base_url}{prefix}/auth/magic-link/verify/{raw_token}"

    sent = await send_magic_link_email(email, verify_url)
    if not sent:
        raise HTTPException(
            status_code=500,
            detail="Failed to send magic link email. Vui lòng thử lại.",
        )

    logger.info(
        "Magic link created email_ref=%s session_ref=%s",
        _magic_link_ref(email),
        _magic_link_ref(session_id),
    )

    response: dict = {
        "session_id": session_id,
        "message": "Magic link đã được gửi đến email của bạn.",
        "expires_in": settings.magic_link_expires_seconds,
    }

    # Development-only convenience: surface the verify URL when Resend is not
    # usable locally. Production never exposes raw verification URLs.
    resend_missing_or_placeholder = is_missing_or_placeholder_secret(
        getattr(settings, "resend_api_key", "")
    )
    if (
        settings.environment != "production"
        and resend_missing_or_placeholder
    ):
        response["dev_verify_url"] = verify_url
        response["message"] = (
            "Resend chưa cấu hình — Wiii sẽ tự mở tab xác minh giúp bạn."
        )

    return response


# ---------------------------------------------------------------------------
# POST /auth/magic-link/request -- send magic link email
# ---------------------------------------------------------------------------

@router.post("/request", response_model=MagicLinkResponse)
@limiter.limit("5/minute")
async def request_magic_link(body: MagicLinkRequest, request: Request):
    """Send a magic link email for passwordless authentication."""
    from app.core.database import get_asyncpg_pool

    email = body.email.strip().lower()

    if not validate_email(email):
        raise HTTPException(status_code=422, detail="Invalid email format.")

    pool = await get_asyncpg_pool()
    async with pool.acquire() as conn:
        result = await _create_magic_link(email, conn)

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# GET /auth/magic-link/verify/{token} -- verify token, issue JWT
# ---------------------------------------------------------------------------

async def _audit_verify_failure(reason: str, request: Optional[Request], email: Optional[str] = None) -> None:
    """Fire-and-forget auth audit log for a failed verify attempt.

    Defense-in-depth: only successes were audited before. Failures are now
    captured so abuse patterns (brute-force, replay) are detectable.
    """
    try:
        from app.auth.auth_audit import log_auth_event
        ip = request.client.host if (request and request.client) else None
        await log_auth_event(
            "login_failed",
            provider="magic_link",
            result="failed",
            reason=reason,
            ip_address=ip,
            metadata={"email_ref": _magic_link_ref(email)} if email else None,
        )
    except Exception:
        pass


@router.get("/verify/{token}")
@limiter.limit("30/hour")
async def verify_magic_link(token: str, request: Request):
    """Verify a magic link token, create user/JWT, and push via WebSocket.

    Per-IP rate-limited to ``30/hour`` (defense-in-depth — the 288-bit token
    space already makes brute force infeasible, but no auth endpoint should be
    unlimited).
    """
    from app.auth.token_service import create_token_pair
    from app.auth.user_service import find_or_create_by_provider
    from app.core.database import get_asyncpg_pool

    token_hash = hash_token(token)

    pool = await get_asyncpg_pool()
    async with pool.acquire() as conn:
        # ---- Look up token ----
        row = await conn.fetchrow(
            """
            SELECT email, ws_session_id, expires_at, used_at
            FROM magic_link_tokens
            WHERE token_hash = $1
            """,
            token_hash,
        )

        if not row:
            await _audit_verify_failure("invalid_token", request)
            return _error_page("Link không hợp lệ hoặc đã hết hạn.")

        if is_token_used(row["used_at"]):
            await _audit_verify_failure("token_already_used", request, row["email"])
            return _error_page("Link này đã được sử dụng.")

        if is_token_expired(row["expires_at"]):
            await _audit_verify_failure("token_expired", request, row["email"])
            return _error_page("Link đã hết hạn. Vui lòng yêu cầu link mới.")

        # ---- Mark as used ----
        await conn.execute(
            "UPDATE magic_link_tokens SET used_at = NOW() WHERE token_hash = $1",
            token_hash,
        )

    # ---- Find or create user ----
    email = row["email"]
    user = await find_or_create_by_provider(
        provider="magic_link",
        provider_sub=email,
        email=email,
        email_verified=True,
        auto_create=True,
    )

    if not user:
        return _error_page("Không thể tạo tài khoản.")

    assigned_org_id = resolve_default_login_organization_id(settings)
    if assigned_org_id:
        await ensure_user_org_membership(user["id"], assigned_org_id)

    # ---- Create JWT pair ----
    token_pair = await create_token_pair(
        user_id=user["id"],
        email=user.get("email"),
        name=user.get("name"),
        role=user.get("role", "student"),
        platform_role=user.get("platform_role"),
        role_source="platform",
        active_organization_id=assigned_org_id,
        auth_method="magic_link",
    )

    # ---- Push tokens via WebSocket ----
    session_id = row["ws_session_id"]
    payload = {
        "type": "auth_success",
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "token_type": token_pair.token_type,
        "expires_in": token_pair.expires_in,
        "organization_id": assigned_org_id or "",
        "user": {
            "id": user["id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role", "student"),
            "legacy_role": user.get("role", "student"),
            "platform_role": user.get("platform_role"),
            "role_source": "platform",
            "active_organization_id": assigned_org_id or "",
        },
    }

    mgr = get_session_manager()
    ws_pushed = await mgr.push_tokens(session_id, payload)

    if not ws_pushed:
        logger.warning(
            "Magic link WS session not found session_ref=%s",
            _magic_link_ref(session_id),
        )

    # ---- Audit log ----
    try:
        from app.auth.auth_audit import log_auth_event
        await log_auth_event(
            "login", user_id=user["id"], provider="magic_link",
            metadata={"email_ref": _magic_link_ref(email)},
        )
    except Exception:
        pass

    logger.info(
        "Magic link verified email_ref=%s ws_pushed=%s user_ref=%s",
        _magic_link_ref(email),
        ws_pushed,
        _magic_link_ref(user["id"]),
    )

    return _success_page(ws_pushed)


# ---------------------------------------------------------------------------
# WS /auth/magic-link/ws/{session_id} -- wait for token delivery
# ---------------------------------------------------------------------------

@router.websocket("/ws/{session_id}")
async def magic_link_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint -- client waits here for magic link verification."""
    mgr = get_session_manager()
    await mgr.register(session_id, websocket)

    timeout = settings.magic_link_ws_timeout_seconds

    try:
        # Keep alive: wait for messages or timeout
        # The push_tokens() call will send data and close the socket
        await asyncio.wait_for(
            _ws_keepalive(websocket),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.info(
            "Magic link WS session timed out session_ref=%s",
            _magic_link_ref(session_id),
        )
        try:
            await websocket.send_json({"type": "timeout", "message": "Session expired"})
            await websocket.close()
        except Exception:
            pass
    except WebSocketDisconnect:
        logger.info(
            "Magic link WS client disconnected session_ref=%s",
            _magic_link_ref(session_id),
        )
    except Exception as e:
        logger.error(
            "Magic link WS error session_ref=%s: %s",
            _magic_link_ref(session_id),
            _safe_magic_link_detail(e, session_id),
        )
    finally:
        mgr.remove(session_id)


async def _ws_keepalive(websocket: WebSocket):
    """Keep WebSocket alive by receiving messages until close."""
    while True:
        try:
            await websocket.receive_text()
        except WebSocketDisconnect:
            break
        except Exception:
            break
