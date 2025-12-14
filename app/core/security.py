"""
Security Module - Authentication and Authorization
Requirements: 1.3

Supports both API Key and JWT Token authentication.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# Security schemes
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    """JWT Token payload structure"""
    sub: str  # Subject (user_id)
    exp: datetime  # Expiration time
    iat: datetime  # Issued at
    type: str = "access"  # Token type


class AuthenticatedUser(BaseModel):
    """
    Authenticated user information.
    
    LMS Integration: Now includes role and session tracking.
    """
    user_id: str
    auth_method: str  # "api_key" or "jwt"
    role: str = "student"  # student / teacher / admin
    session_id: Optional[str] = None  # For LMS session tracking
    organization_id: Optional[str] = None  # For multi-tenant support


# =============================================================================
# JWT Token Functions
# =============================================================================

def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.
    
    Args:
        subject: The subject (usually user_id)
        expires_delta: Optional custom expiration time
    
    Returns:
        Encoded JWT token string
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "type": "access",
    }
    
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)



def verify_jwt_token(token: str) -> TokenPayload:
    """
    Verify and decode a JWT token.
    
    Args:
        token: The JWT token string
    
    Returns:
        TokenPayload with decoded information
    
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return TokenPayload(**payload)
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# =============================================================================
# API Key Validation
# =============================================================================

def verify_api_key(api_key: str) -> bool:
    """
    Verify an API key.
    
    Args:
        api_key: The API key to verify
    
    Returns:
        True if valid, False otherwise
    """
    if not settings.api_key:
        # If no API key configured, allow all (development mode)
        logger.warning("No API key configured - allowing all requests")
        return True
    
    return api_key == settings.api_key


# =============================================================================
# Authentication Dependencies
# =============================================================================

async def get_api_key(
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """
    Extract and validate API key from header.
    Returns None if not provided.
    """
    if api_key and verify_api_key(api_key):
        return api_key
    return None


async def get_jwt_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Optional[TokenPayload]:
    """
    Extract and validate JWT token from Authorization header.
    Returns None if not provided.
    """
    if credentials:
        return verify_jwt_token(credentials.credentials)
    return None


async def require_auth(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    x_org_id: Optional[str] = Header(None, alias="X-Organization-ID"),
) -> AuthenticatedUser:
    """
    Require authentication via API Key OR JWT Token.
    
    LMS Integration: Accepts additional headers for user context.
    - X-User-ID: Real user ID from LMS (required for API key auth)
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
    """
    # Try API Key first
    if api_key:
        if verify_api_key(api_key):
            # LMS Integration: Use headers for user context
            return AuthenticatedUser(
                user_id=x_user_id or "anonymous",
                auth_method="api_key",
                role=x_role or "student",
                session_id=x_session_id,
                organization_id=x_org_id,
            )
        else:
            logger.warning("Invalid API key provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
    
    # Try JWT Token
    if credentials:
        token_payload = verify_jwt_token(credentials.credentials)
        return AuthenticatedUser(
            user_id=token_payload.sub,
            auth_method="jwt",
            role=x_role or "student",  # Allow role override from header
            session_id=x_session_id,
            organization_id=x_org_id,
        )
    
    # No authentication provided
    logger.warning("No authentication credentials provided")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def optional_auth(
    api_key: Optional[str] = Security(api_key_header),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    x_org_id: Optional[str] = Header(None, alias="X-Organization-ID"),
) -> Optional[AuthenticatedUser]:
    """
    Optional authentication - returns None if not authenticated.
    Useful for endpoints that work with or without auth.
    
    LMS Integration: Passes all headers to require_auth.
    """
    try:
        return await require_auth(
            api_key, credentials, 
            x_user_id, x_role, x_session_id, x_org_id
        )
    except HTTPException:
        return None

