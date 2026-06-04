"""Per-request Facebook cookie context.

Sprint 154: "Dang Nhap Facebook"

Follows org_context.py pattern — set in API layer, read in adapter.
ContextVar is request-scoped in asyncio: each request gets its own value.
"""
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

current_facebook_cookie: ContextVar[str] = ContextVar(
    "current_facebook_cookie", default=""
)


def set_facebook_cookie(cookie: str) -> Token[str]:
    """Set Facebook cookie for the current request."""
    return current_facebook_cookie.set(cookie or "")


def reset_facebook_cookie(token: Token[str]) -> None:
    """Restore the previous Facebook cookie context."""
    current_facebook_cookie.reset(token)


@contextmanager
def facebook_cookie_scope(cookie: str) -> Iterator[None]:
    """Bind a Facebook cookie for one request scope and always restore it."""
    token = set_facebook_cookie(cookie)
    try:
        yield
    finally:
        reset_facebook_cookie(token)


def get_facebook_cookie() -> str:
    """Get Facebook cookie for the current request (empty string if not set)."""
    return current_facebook_cookie.get()
