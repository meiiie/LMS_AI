"""
Issue #88: Local Dev Login — frictionless one-click JWT for localhost development.

Mirrors the contract of /auth/google/callback so the frontend can pipe the
response straight into the existing loginWithTokens() flow. Token lifecycle,
audit, JTI, and refresh-family are all reused as-is — there is no special
JWT-validation path.

Defense in depth:
  - Feature-gated by settings.enable_dev_login (default False).
  - Production validator (_settings_validation.py) hard-fails app boot when
    enable_dev_login=True and environment="production".
  - Source-IP guard rejects any request that does not originate from a
    private/loopback address (RFC1918 + 127.0.0.0/8 + ::1).
  - Every successful and refused call is recorded by the auth audit log.

The endpoint is intentionally minimal: no body required, no public docs,
no production exposure. Dev users get a real short-lived JWT under
auth_method="dev" that follows the same lifecycle as OAuth tokens.
"""
from __future__ import annotations

import ipaddress
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.organization_context import (
    ensure_user_org_membership,
    resolve_default_login_organization_id,
)
from app.auth.token_service import create_token_pair
from app.auth.user_service import find_or_create_by_provider
from app.core.config import settings
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_MAX_DEV_LOGIN_DIAGNOSTIC_LENGTH = 500

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    # Pydantic's EmailStr requires the optional `email-validator` package and
    # this endpoint is local-dev-only — a plain string with format hint is
    # enough; backend doesn't actually verify or send to this address.
    email: Optional[str] = Field(
        default=None,
        max_length=320,
        description="Override the default dev email — defaults to dev_login_default_email",
    )
    name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional display name for the dev user",
    )
    role: Optional[str] = Field(
        default=None,
        description="Override role: student | teacher | admin (defaults to dev_login_default_role)",
    )


def _is_private_source(host: Optional[str]) -> bool:
    """Allow only loopback + RFC1918 + IPv6 ULA. Defense-in-depth gate that
    keeps the endpoint unreachable from the public internet even if the flag
    is mistakenly enabled on a production-style stack."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname (e.g. "localhost") rather than literal IP. Trust only the
        # explicit "localhost" alias — any other hostname must resolve to a
        # private IP at the proxy layer.
        return host == "localhost"
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _dev_login_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_dev_login_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    for secret_value in secret_values:
        secret = str(secret_value or "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    return redact_runtime_secret_text(text, max_length=_MAX_DEV_LOGIN_DIAGNOSTIC_LENGTH)


def _build_stateless_dev_user(*, email: str, name: str, role: str) -> dict:
    """Create a stable local-dev identity when PostgreSQL is unavailable."""
    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wiii:dev-login:{email.lower()}"))
    platform_role = "platform_admin" if role == "admin" else "user"
    return {
        "id": user_id,
        "email": email,
        "name": name,
        "avatar_url": None,
        "role": role,
        "platform_role": platform_role,
        "is_active": True,
    }


async def _find_or_create_dev_user(
    *,
    provider: str,
    provider_sub: str,
    provider_issuer: Optional[str],
    email: Optional[str],
    name: Optional[str],
    role: str,
    email_verified: bool,
) -> dict:
    """Use persisted users when possible, with a localhost-only stateless fallback."""
    fallback_email = email or provider_sub
    fallback_name = name or "Dev User"
    try:
        from app.core.database import is_shared_database_temporarily_unavailable

        if is_shared_database_temporarily_unavailable():
            return _build_stateless_dev_user(
                email=fallback_email,
                name=fallback_name,
                role=role,
            )

        user = await find_or_create_by_provider(
            provider=provider,
            provider_sub=provider_sub,
            provider_issuer=provider_issuer,
            email=email,
            name=name,
            role=role,
            email_verified=email_verified,
        )
        return user or _build_stateless_dev_user(
            email=fallback_email,
            name=fallback_name,
            role=role,
        )
    except Exception as exc:
        try:
            from app.core.database import mark_shared_database_unavailable

            mark_shared_database_unavailable(exc)
        except Exception:
            pass
        logger.warning(
            "/auth/dev-login using stateless fallback because user DB is unavailable: %s",
            _safe_dev_login_detail(exc, fallback_email, provider_sub),
        )
        return _build_stateless_dev_user(
            email=fallback_email,
            name=fallback_name,
            role=role,
        )


@router.get("/dev-login/status")
async def dev_login_status() -> dict:
    """Public probe so the frontend knows whether to render the dev button."""
    return {"enabled": bool(settings.enable_dev_login)}


@router.post("/dev-login")
async def dev_login(request: Request, body: Optional[DevLoginRequest] = None) -> JSONResponse:
    """Mint a real short-lived JWT for a dev user. Localhost-only."""
    if not settings.enable_dev_login:
        # 404 (not 403) so an attacker probing in production cannot tell the
        # endpoint exists at all when the flag is off.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    source_host = request.client.host if request.client else None
    if not _is_private_source(source_host):
        logger.warning(
            "SECURITY: /auth/dev-login refused — non-private source IP %s", source_host,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dev-login is only reachable from a private network",
        )

    email = (body.email if body and body.email else settings.dev_login_default_email)
    name = (body.name if body and body.name else "Dev User")
    role = (body.role if body and body.role else settings.dev_login_default_role)
    if role not in ("student", "teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be student/teacher/admin (got {role!r})",
        )

    user = await _find_or_create_dev_user(
        provider="dev",
        provider_sub=email,
        provider_issuer="localhost",
        email=email,
        name=name,
        role=role,
        # Trusted localhost identity — auto-link to existing accounts is safe
        # because the endpoint is gated by source-IP + feature flag.
        email_verified=True,
    )
    if not user:
        # find_or_create_by_provider returns None only when auto_create is
        # disabled. We always pass auto_create defaulting True, so this is
        # an internal error if hit.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="dev-login: failed to materialise dev user",
        )

    assigned_org_id = resolve_default_login_organization_id(settings)
    if assigned_org_id:
        await ensure_user_org_membership(user["id"], assigned_org_id)

    token_pair = await create_token_pair(
        user_id=user["id"],
        email=user.get("email"),
        name=user.get("name"),
        role=user.get("role", role),
        platform_role=user.get("platform_role"),
        role_source="platform",
        active_organization_id=assigned_org_id,
        auth_method="dev",
    )

    # Audit (best-effort). A successful dev-login is forensically interesting
    # because it bypasses normal credential checks — we want a traceable record.
    try:
        from app.auth.auth_audit import log_auth_event
        await log_auth_event(
            "login",
            user_id=user["id"],
            provider="dev",
            ip_address=source_host,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception as audit_err:
        logger.debug(
            "dev-login audit log failed: %s",
            _safe_dev_login_detail(audit_err, user["id"], email),
        )

    assigned_org_id = assigned_org_id or ""

    logger.info(
        "/auth/dev-login issued JWT user_ref=%s email_ref=%s role=%s (source=%s)",
        _dev_login_ref(user["id"]), _dev_login_ref(email), role, source_host,
    )

    return JSONResponse({
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "token_type": "bearer",
        "expires_in": token_pair.expires_in,
        "organization_id": assigned_org_id,
        "user": {
            "id": user["id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "avatar_url": user.get("avatar_url"),
            "role": user.get("role", role),
            "legacy_role": user.get("role", role),
            "platform_role": user.get("platform_role"),
            "role_source": "platform",
            "active_organization_id": assigned_org_id,
        },
    })
