"""
Rate Limiting Module
Requirements: 9.2

Implements rate limiting using slowapi to prevent API abuse.
Returns HTTP 429 with retry-after header when limit exceeded.
"""
import logging
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.models.schemas import RateLimitResponse

logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    """
    Get unique client identifier for rate limiting.
    Uses API key if present, otherwise falls back to IP address.
    """
    # Try to get API key first
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api_key:{api_key[:8]}..."  # Use partial key for privacy
    
    # Try to get user from JWT (if already authenticated)
    # This would require parsing the token, so we use IP as fallback
    
    # Fall back to IP address
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_client_identifier,
    default_limits=[f"{settings.rate_limit_requests}/{settings.rate_limit_window_seconds}seconds"],
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom handler for rate limit exceeded errors.
    Requirements: 9.2 - Returns HTTP 429 with retry-after header.
    """
    # Parse retry-after from the exception
    retry_after = settings.rate_limit_window_seconds
    
    # Try to extract actual retry time from exception
    if hasattr(exc, "detail") and exc.detail:
        try:
            # slowapi includes retry info in detail
            parts = str(exc.detail).split()
            for i, part in enumerate(parts):
                if part.isdigit():
                    retry_after = int(part)
                    break
        except (ValueError, IndexError):
            pass
    
    logger.warning(
        f"Rate limit exceeded for {get_client_identifier(request)}: {exc.detail}"
    )
    
    response = RateLimitResponse(
        error="rate_limited",
        message=f"Rate limit exceeded. Try again in {retry_after} seconds.",
        retry_after=retry_after,
    )
    
    return JSONResponse(
        status_code=429,
        content=response.model_dump(mode="json"),
        headers={"Retry-After": str(retry_after)},
    )


# =============================================================================
# Rate Limit Decorators
# =============================================================================

def rate_limit(limit: str) -> Callable:
    """
    Decorator for custom rate limits on specific endpoints.
    
    Usage:
        @rate_limit("10/minute")
        async def my_endpoint():
            ...
    
    Args:
        limit: Rate limit string (e.g., "10/minute", "100/hour")
    """
    return limiter.limit(limit)


# Default rate limit decorator using settings
default_rate_limit = limiter.limit(
    f"{settings.rate_limit_requests}/{settings.rate_limit_window_seconds}seconds"
)

# Stricter rate limit for expensive operations (like chat)
chat_rate_limit = limiter.limit("30/minute")

# Very strict rate limit for auth endpoints
auth_rate_limit = limiter.limit("5/minute")
