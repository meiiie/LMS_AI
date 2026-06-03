"""
Security Module - Authentication and Authorization
Requirements: 1.3

Supports both API Key and JWT Token authentication.
Sprint 192: Org membership validation, API key role restriction, JWT audience.
"""
import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.security_models import AuthenticatedUser, TokenPayload
from app.core.security_roles import (
    DEFAULT_LEGACY_ROLE,
    DEFAULT_PLATFORM_ROLE,
    PLATFORM_ADMIN_ROLE,
    derive_platform_role_from_legacy_role,
    is_platform_admin,
    map_host_role_to_legacy_role,
    normalize_host_role,
    normalize_platform_role,
    resolve_interaction_role,
)

logger = logging.getLogger(__name__)

# Security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def _normalize_optional_header(value: object) -> Optional[str]:
    """Normalize dependency-injected header values for direct-call safety.

    FastAPI replaces Header/Security defaults at request time, but unit tests
    and internal direct calls may invoke this dependency function directly,
    leaving the default dependency marker objects in place. Treat any
    non-string marker as an absent header instead of letting it influence auth
    logic.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _is_strict_identity_org_mode() -> bool:
    env = getattr(settings, "environment", "development")
    return (
        getattr(settings, "enable_multi_tenant", False) is True
        and isinstance(env, str)
        and env in ("production", "staging")
    )


def _resolve_token_authenticated_org_id(
    header_org_id: Optional[str],
    token_org_id: Optional[str],
) -> Optional[str]:
    header_org_id = _normalize_optional_header(header_org_id)
    token_org_id = _normalize_optional_header(token_org_id)

    if not _is_strict_identity_org_mode():
        return header_org_id or token_org_id

    if token_org_id:
        if header_org_id and header_org_id != token_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Active organization does not match authenticated organization.",
            )
        return token_org_id

    if header_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Authenticated token does not carry an active organization; "
                "X-Organization-ID cannot establish tenant context."
            ),
        )

    return None


def _optional_auth_credentials_present(
    api_key: Optional[str],
    credentials: Optional[HTTPAuthorizationCredentials],
) -> bool:
    return bool(
        _normalize_optional_header(api_key)
        or isinstance(credentials, HTTPAuthorizationCredentials)
    )




# =============================================================================
# JWT Token Functions
# =============================================================================
# NOTE: Token creation is handled by app.auth.token_service.create_access_token()
# which includes aud, jti, iss, email, name, role claims.
# This module only provides verify_jwt_token() used by require_auth().

def verify_jwt_token(token: str) -> TokenPayload:
    """
    Verify and decode a JWT token.

    Uses token_service.decode_jwt_payload() for single-source decode logic
    (aud validation, JTI denylist). Builds TokenPayload from raw claims
    (preserving None defaults for missing fields like auth_method).

    Raises:
        HTTPException: If token is invalid, expired, or revoked
    """
    try:
        from app.auth.token_service import decode_jwt_payload
        payload = decode_jwt_payload(token)
        return TokenPayload(**payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("JWT verification failed: %s", e)
        # Preserve specific revocation detail for JTI denylist
        detail = "Token has been revoked" if "revoked" in str(e).lower() else "Invalid or expired token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


# =============================================================================
# API Key Validation
# =============================================================================


def _get_configured_secret(value: object) -> str | None:
    """Normalize configured shared secrets before constant-time comparison."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def verify_api_key(api_key: str) -> bool:
    """
    Verify an API key.

    Args:
        api_key: The API key to verify

    Returns:
        True if valid, False otherwise
    """
    if not isinstance(api_key, str) or not api_key:
        return False

    configured_api_key = _get_configured_secret(
        getattr(settings, "api_key", None)
    )
    if not configured_api_key:
        if settings.environment == "production":
            logger.error(
                "SECURITY: No API key configured in production "
                "— rejecting request"
            )
            return False
        logger.warning(
            "No API key configured — allowing all requests "
            "(development mode)"
        )
        return True

    return hmac.compare_digest(api_key, configured_api_key)


def verify_lms_service_token(service_token: str) -> bool:
    """Verify the dedicated LMS service token for proxied backend requests."""
    if not isinstance(service_token, str) or not service_token:
        return False

    configured_service_token = _get_configured_secret(
        getattr(settings, "lms_service_token", None)
    )
    if not configured_service_token:
        return False

    return hmac.compare_digest(service_token, configured_service_token)


# =============================================================================
# Sprint 192: Org Membership Validation
# =============================================================================

async def _validate_org_membership(
    user_id: str,
    org_id: str,
    role: str,
    platform_role: Optional[str] = None,
) -> bool:
    """Check if user is a member of the specified organization.

    Platform admins bypass the check.
    Fail-open on DB error (log warning, don't reject).
    """
    if (
        normalize_platform_role(platform_role) == PLATFORM_ADMIN_ROLE
        or derive_platform_role_from_legacy_role(role) == PLATFORM_ADMIN_ROLE
    ):
        return True

    try:
        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool(create=True)
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                (
                    "SELECT 1 FROM user_organizations "
                    "WHERE user_id = $1 AND organization_id = $2"
                ),
                user_id,
                org_id,
            )
            return row is not None
    except Exception as e:
        logger.warning("Org membership check failed (fail-closed): %s", e)
        return False


# =============================================================================
# Authentication Dependencies
# =============================================================================

async def require_auth(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(
        bearer_scheme
    ),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    x_org_id: Optional[str] = Header(None, alias="X-Organization-ID"),
    x_host_role: Optional[str] = Header(None, alias="X-Host-Role"),
) -> AuthenticatedUser:
    """
    Require authentication via API Key, LMS service token, or JWT Token.

    Auth modes:
    - API key: server-to-server client identity only
    - LMS service token: trusted proxied LMS request carrying end-user context
    - JWT: end-user identity

    LMS Integration: Accepts additional headers for proxied user context.
    - X-User-ID: Real user ID from LMS (required for LMS service auth)
    - X-Role: User role (student/teacher/admin)
    - X-Session-ID: Session tracking for analytics
    - X-Organization-ID: Multi-tenant support

    Requirements: 1.3

    Args:
        api_key: API key from X-API-Key header
        credentials: JWT token from Authorization header
        x_user_id: User ID from LMS
        x_role: User role from LMS
        x_session_id: Session ID for tracking
        x_org_id: Organization ID for multi-tenant

    Returns:
        AuthenticatedUser with user information

    Raises:
        HTTPException 401: If no valid authentication provided
        HTTPException 403: If user is not a member of the specified org
    """
    api_key = _normalize_optional_header(api_key)
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        credentials = None
    x_user_id = _normalize_optional_header(x_user_id)
    x_role = _normalize_optional_header(x_role)
    x_session_id = _normalize_optional_header(x_session_id)
    x_org_id = _normalize_optional_header(x_org_id)
    x_host_role = _normalize_optional_header(x_host_role)

    # Track whether an API key was supplied but failed verification, so we can
    # still attempt a Bearer fallback before returning 401. This follows the
    # "try all provided credentials before failing" pattern used by AWS SDK,
    # GitHub, and Cloudflare Access. A stale API key in a browser that also
    # holds a valid JWT must not silently break every request.
    api_key_attempted = False

    # Try API Key or LMS service token first
    if api_key:
        api_key_attempted = True
        if verify_api_key(api_key):
            effective_host_role = normalize_host_role(x_host_role or x_role)
            effective_role = (
                x_role
                if x_role in ("student", "teacher", "admin")
                else map_host_role_to_legacy_role(effective_host_role)
            )

            # Sprint 192: Restrict role escalation via API key in production
            if (
                settings.enforce_api_key_role_restriction
                and settings.environment == "production"
                and effective_role not in ("student", "teacher")
            ):
                logger.warning(
                    "SECURITY: API key auth attempted role=%s for "
                    "user=%s — downgraded to student",
                    effective_role,
                    x_user_id or "anonymous",
                )
                # Audit event (fire-and-forget)
                if settings.enable_auth_audit:
                    try:
                        import asyncio
                        from app.auth.auth_audit import log_auth_event
                        asyncio.get_running_loop().create_task(log_auth_event(
                            "role_downgrade",
                            provider="api_key",
                            user_id=x_user_id or "anonymous",
                            reason=(
                                f"Attempted role={effective_role} "
                                "via API key in production"
                            ),
                        ))
                    except Exception as _audit_err:
                        logger.debug("Auth audit log failed (role_downgrade): %s", _audit_err)
                effective_role = "student"

            # Sprint 194b (C2): In production, general API key auth does NOT
            # trust X-User-ID. End-user identity must come from JWT or the
            # dedicated LMS service token path below.
            if settings.environment == "production":
                effective_user_id = "api-client"
                if x_user_id and x_user_id != "api-client":
                    logger.warning(
                        "SECURITY: Ignoring X-User-ID=%s for API key auth in production — "
                        "use JWT or LMS service token for end-user identity",
                        x_user_id,
                    )
            else:
                effective_user_id = x_user_id or "anonymous"

            user = AuthenticatedUser(
                user_id=effective_user_id,
                auth_method="api_key",
                role=effective_role,
                platform_role=derive_platform_role_from_legacy_role(
                    effective_role,
                    auth_method="api_key",
                    role_source="api_key",
                ),
                host_role=effective_host_role,
                role_source="api_key",
                session_id=x_session_id,
                organization_id=x_org_id,
                identity_version="2",
            )

            # Sprint 192: Validate org membership
            if x_org_id and settings.enable_org_membership_check:
                is_member = await _validate_org_membership(
                    user.user_id,
                    x_org_id,
                    user.role,
                    user.platform_role,
                )
                if not is_member:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"User is not a member of organization '{x_org_id}'",
                    )

            return user
        elif verify_lms_service_token(api_key):
            if not x_user_id and not credentials:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="LMS service authentication requires X-User-ID header.",
                )

            token_payload: Optional[TokenPayload] = None
            if credentials:
                token_payload = verify_jwt_token(credentials.credentials)
                if x_user_id and token_payload.sub != x_user_id:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="LMS service identity mismatch between JWT and X-User-ID",
                    )

            effective_host_role = (
                normalize_host_role(token_payload.host_role)
                if token_payload and token_payload.host_role
                else normalize_host_role(x_host_role or x_role)
            )
            effective_role = (
                token_payload.role
                if token_payload and token_payload.role in ("student", "teacher")
                else map_host_role_to_legacy_role(effective_host_role)
            )
            if (
                settings.enforce_api_key_role_restriction
                and settings.environment == "production"
                and effective_role not in ("student", "teacher")
            ):
                logger.warning(
                    "SECURITY: LMS service auth attempted role=%s for "
                    "user=%s — downgraded to student",
                    effective_role,
                    x_user_id,
                )
                effective_role = "student"

            organization_id = (
                _resolve_token_authenticated_org_id(
                    x_org_id,
                    token_payload.active_organization_id,
                )
                if token_payload
                else x_org_id
            )

            user = AuthenticatedUser(
                user_id=token_payload.sub if token_payload else x_user_id,
                auth_method="lms_service",
                role=effective_role,
                platform_role=(
                    normalize_platform_role(token_payload.platform_role)
                    if token_payload and token_payload.platform_role
                    else DEFAULT_PLATFORM_ROLE
                ),
                organization_role=token_payload.organization_role if token_payload else None,
                host_role=effective_host_role,
                role_source=(
                    token_payload.role_source
                    if token_payload and token_payload.role_source
                    else "lms_host"
                ),
                session_id=x_session_id,
                organization_id=organization_id,
                connector_id=token_payload.connector_id if token_payload else None,
                identity_version=(
                    token_payload.identity_version
                    if token_payload and token_payload.identity_version
                    else "2"
                ),
            )

            if user.organization_id and settings.enable_org_membership_check:
                is_member = await _validate_org_membership(
                    user.user_id,
                    user.organization_id,
                    user.role,
                    user.platform_role,
                )
                if not is_member:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"User is not a member of organization '{user.organization_id}'",
                    )

            return user
        # API key was present but neither path verified. Fall through to the
        # Bearer/JWT check — if the caller also supplied a valid JWT we honour
        # it. The final 401 at the bottom of the function still raises
        # "Invalid API key" if no alternative credential succeeds.

    # Try JWT Token
    if credentials:
        token_payload = verify_jwt_token(credentials.credentials)
        # Sprint 28 SECURITY: JWT role from token payload, NOT from X-Role header
        # X-Role override is only allowed for API key auth (trusted LMS backend)
        jwt_role = token_payload.role or DEFAULT_LEGACY_ROLE
        # Sprint 157: OAuth tokens carry auth_method; legacy tokens default to "jwt"
        auth_method = token_payload.auth_method or "jwt"
        platform_role = (
            normalize_platform_role(token_payload.platform_role)
            if token_payload.platform_role
            else derive_platform_role_from_legacy_role(
                token_payload.role,
                auth_method=auth_method,
                role_source=token_payload.role_source,
            )
        )
        organization_id = _resolve_token_authenticated_org_id(
            x_org_id,
            token_payload.active_organization_id,
        )

        user = AuthenticatedUser(
            user_id=token_payload.sub,
            auth_method=auth_method,
            role=jwt_role,
            platform_role=platform_role,
            organization_role=token_payload.organization_role,
            host_role=normalize_host_role(token_payload.host_role),
            role_source=token_payload.role_source or (
                "platform" if platform_role == PLATFORM_ADMIN_ROLE else "jwt"
            ),
            session_id=x_session_id,
            organization_id=organization_id,
            connector_id=token_payload.connector_id,
            identity_version=token_payload.identity_version,
        )

        # Sprint 192: Validate org membership
        if organization_id and settings.enable_org_membership_check:
            is_member = await _validate_org_membership(
                user.user_id,
                organization_id,
                user.role,
                user.platform_role,
            )
            if not is_member:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User is not a member of organization '{organization_id}'",
                )

        return user

    # All provided credentials failed (or none were provided).
    if api_key_attempted:
        logger.warning("Invalid API key provided")
        # Sprint 176: Audit event (fire-and-forget, non-blocking). Logged at
        # final-failure time so legitimate callers whose stale API key was
        # superseded by a valid JWT do not spam the audit log.
        if settings.enable_auth_audit:
            try:
                import asyncio
                from app.auth.auth_audit import log_auth_event
                asyncio.get_running_loop().create_task(log_auth_event(
                    "auth_failed", provider="api_key", result="failed",
                    reason="Invalid API key",
                ))
            except Exception as _audit_err:
                logger.debug("Auth audit log failed (auth_failed): %s", _audit_err)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    logger.warning("No authentication credentials provided")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def optional_auth(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(
        bearer_scheme
    ),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    x_org_id: Optional[str] = Header(None, alias="X-Organization-ID"),
    x_host_role: Optional[str] = Header(None, alias="X-Host-Role"),
) -> Optional[AuthenticatedUser]:
    """
    Optional authentication - returns None if not authenticated.
    Useful for endpoints that work with or without auth.

    LMS Integration: Passes all headers to require_auth.
    """
    credentials_present = _optional_auth_credentials_present(api_key, credentials)
    try:
        return await require_auth(
            api_key,
            credentials,
            x_user_id, x_role, x_session_id, x_org_id, x_host_role
        )
    except HTTPException as exc:
        if credentials_present:
            raise exc
        return None
