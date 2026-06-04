"""
Sprint 159: "Cầu Nối Trực Tiếp" — LMS Auth REST Router.

Endpoints:
  POST /auth/lms/token         — Exchange LMS credentials for Wiii JWT
  POST /auth/lms/token/refresh — Refresh token (delegates to token_service)
  GET  /auth/lms/health        — Health check listing configured connectors

Security: HMAC-SHA256 verified BEFORE JSON parsing (same pattern as lms_webhook.py).
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)
_MAX_LMS_AUTH_DIAGNOSTIC_LENGTH = 500

router = APIRouter(prefix="/auth/lms", tags=["auth-lms"])


def _lms_auth_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_lms_auth_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    for secret_value in secret_values:
        secret = str(secret_value or "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    return redact_runtime_secret_text(text, max_length=_MAX_LMS_AUTH_DIAGNOSTIC_LENGTH)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LMSTokenRequest(BaseModel):
    connector_id: str = Field(..., min_length=1, max_length=200)
    lms_user_id: str = Field(..., min_length=1, max_length=500)
    email: Optional[str] = Field(None, max_length=500)
    name: Optional[str] = Field(None, max_length=500)
    role: Optional[str] = Field(None, max_length=100)
    organization_id: Optional[str] = Field(None, max_length=200)
    timestamp: Optional[int] = Field(None, description="Unix epoch seconds for replay protection")


class LMSTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict
    organization_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/token")
@limiter.limit("10/minute")
async def lms_token_exchange(request: Request):
    """
    Exchange LMS user credentials for a Wiii JWT token pair.

    The LMS backend signs the request body with HMAC-SHA256 using the shared secret.
    Header: X-LMS-Signature: sha256=<hex>

    Rate limited to 10 requests/minute per IP.
    """
    from app.auth.lms_token_exchange import (
        validate_lms_signature,
        validate_request_timestamp,
        exchange_lms_token,
    )

    # 1. Read raw body BEFORE parsing (for HMAC verification)
    body_bytes = await request.body()
    signature = request.headers.get("x-lms-signature", "")

    # 2. Extract connector_id from raw JSON for secret lookup
    try:
        raw = json.loads(body_bytes)
        connector_id = raw.get("connector_id")
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not connector_id:
        raise HTTPException(status_code=400, detail="connector_id is required")

    # 3. Verify HMAC signature
    try:
        if not validate_lms_signature(connector_id, body_bytes, signature):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    except ValueError as e:
        logger.warning(
            "LMS token exchange signature rejected connector_ref=%s detail=%s",
            _lms_auth_ref(connector_id),
            _safe_lms_auth_detail(e, connector_id, signature),
        )
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # 4. Parse full request body
    try:
        token_req = LMSTokenRequest(**raw)
    except Exception as e:
        logger.warning(
            "LMS token exchange invalid request connector_ref=%s detail=%s",
            _lms_auth_ref(connector_id),
            _safe_lms_auth_detail(e, connector_id),
        )
        raise HTTPException(status_code=400, detail="Invalid request")

    # 5. Validate timestamp (replay protection)
    try:
        validate_request_timestamp(token_req.timestamp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 6. Exchange
    try:
        result = await exchange_lms_token(
            connector_id=token_req.connector_id,
            lms_user_id=token_req.lms_user_id,
            email=token_req.email,
            name=token_req.name,
            role=token_req.role,
            organization_id=token_req.organization_id,
        )
    except Exception as e:
        safe_error = _safe_lms_auth_detail(
            e,
            token_req.connector_id,
            token_req.lms_user_id,
            token_req.email,
            token_req.organization_id,
        )
        logger.error(
            "LMS token exchange failed connector_ref=%s lms_user_ref=%s org_ref=%s detail=%s",
            _lms_auth_ref(token_req.connector_id),
            _lms_auth_ref(token_req.lms_user_id),
            _lms_auth_ref(token_req.organization_id),
            safe_error,
        )
        # Sprint 176: Audit failed login
        try:
            from app.auth.auth_audit import log_auth_event
            await log_auth_event(
                "login_failed", provider="lms",
                result="failed", reason=safe_error,
                ip_address=request.client.host if request.client else None,
                organization_id=token_req.organization_id,
                metadata={"connector_ref": _lms_auth_ref(token_req.connector_id)},
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Token exchange failed")

    # Sprint 176: Audit successful LMS login
    try:
        from app.auth.auth_audit import log_auth_event
        user_id = result.get("user", {}).get("id") if isinstance(result, dict) else None
        await log_auth_event(
            "login", user_id=user_id, provider="lms",
            ip_address=request.client.host if request.client else None,
            organization_id=token_req.organization_id,
            metadata={"connector_ref": _lms_auth_ref(token_req.connector_id)},
        )
    except Exception:
        pass

    return JSONResponse(result)


@router.post("/token/refresh")
@limiter.limit("30/minute")
async def lms_token_refresh(request: Request):
    """Refresh a Wiii access token using a refresh token (standard flow)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token is required")

    from app.auth.token_service import refresh_access_token

    result = await refresh_access_token(refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return JSONResponse({
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "token_type": "bearer",
        "expires_in": result.expires_in,
    })


@router.get("/health")
async def lms_auth_health():
    """Health check — lists configured LMS connectors (names only, no secrets)."""
    connector_ids = []
    try:
        connectors = json.loads(settings.lms_connectors or "[]")
        connector_ids = [c.get("id", "unknown") for c in connectors if isinstance(c, dict)]
    except (json.JSONDecodeError, TypeError):
        pass

    return JSONResponse({
        "status": "ok",
        "enabled": settings.enable_lms_token_exchange,
        "connectors": connector_ids,
        "has_flat_secret": bool(settings.lms_webhook_secret),
    })
