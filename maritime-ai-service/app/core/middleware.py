"""
Wiii Middleware — Request-ID Correlation & Organization Context

Generates a unique request ID for every inbound request when the caller
does not supply one via X-Request-ID.  The ID is:
  1. Bound to structlog context vars (auto-attached to every log line).
  2. Returned in the response X-Request-ID header.

Sprint 24: OrgContextMiddleware propagates X-Organization-ID into ContextVar.
Sprint 175: Subdomain → org_id extraction (fallback when no header).

SOTA 2026: Every production service must propagate correlation IDs.
"""

import logging
import re
import uuid
from pathlib import Path

from fastapi import HTTPException
import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

logger = logging.getLogger(__name__)

# Subdomains that should NOT be treated as org slugs
_RESERVED_SUBDOMAINS = frozenset({"www", "api", "admin", "app", "mail", "static", "cdn"})
_EMBED_HASHED_ASSET_RE = re.compile(r"^(?P<prefix>.+)-(?P<hash>[A-Za-z0-9_-]+)\.(?P<ext>js|css)$")


def extract_org_from_subdomain(host: str, base_domain: str) -> str | None:
    """
    Extract org slug from Host header using the configured base domain.

    Example: 'phuong-luu-kiem.holilihu.online' with base_domain='holilihu.online' → 'phuong-luu-kiem'

    Returns None if:
    - base_domain is empty/not configured
    - Host doesn't end with base_domain
    - Extracted subdomain is reserved (www, api, admin, etc.)
    - No subdomain present (bare domain)
    """
    if not base_domain or not host:
        return None

    # Strip port (e.g. 'org.holilihu.online:8080' → 'org.holilihu.online')
    hostname = host.split(":")[0].lower()
    base = base_domain.lower()

    # Host must end with '.{base_domain}' — not just equal to base_domain
    suffix = f".{base}"
    if not hostname.endswith(suffix):
        return None

    subdomain = hostname[: -len(suffix)]
    if not subdomain or subdomain in _RESERVED_SUBDOMAINS:
        return None

    return subdomain


def _embed_asset_roots() -> list[Path]:
    return [
        Path("/app-embed"),
        Path(__file__).resolve().parents[3] / "wiii-desktop" / "dist-embed",
    ]


def _find_embed_asset_replacement(path: str, roots: list[Path] | None = None) -> Path | None:
    """Find the current dev asset for a stale hashed embed chunk request."""
    filename = path.rsplit("/", 1)[-1]
    match = _EMBED_HASHED_ASSET_RE.match(filename)
    if not match:
        return None

    prefix = match.group("prefix")
    extension = match.group("ext")
    candidates: list[Path] = []
    for root in roots or _embed_asset_roots():
        assets_dir = root / "assets"
        if not assets_dir.exists():
            continue
        matches = sorted(assets_dir.glob(f"{prefix}-*.{extension}"))
        existing = [candidate for candidate in matches if candidate.is_file()]
        candidates.extend(existing)
    return candidates[0] if len(candidates) == 1 else None


def _normalize_optional_org_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _is_strict_middleware_org_mode(settings_obj: object) -> bool:
    env = getattr(settings_obj, "environment", "development")
    return (
        getattr(settings_obj, "enable_multi_tenant", False) is True
        and isinstance(env, str)
        and env in ("production", "staging")
    )


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not isinstance(authorization, str):
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _validate_header_org_against_bearer_token(
    request: Request,
    org_id: str | None,
    settings_obj: object,
) -> JSONResponse | None:
    org_id = _normalize_optional_org_id(org_id)
    if not org_id or not _is_strict_middleware_org_mode(settings_obj):
        return None

    bearer_token = _extract_bearer_token(request)
    if not bearer_token:
        return None

    try:
        from app.core.security import verify_jwt_token

        token_payload = verify_jwt_token(bearer_token)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    token_org_id = _normalize_optional_org_id(token_payload.active_organization_id)
    if token_org_id and token_org_id == org_id:
        return None

    if token_org_id:
        detail = "Active organization does not match authenticated organization."
    else:
        detail = (
            "Authenticated token does not carry an active organization; "
            "X-Organization-ID cannot establish tenant context."
        )

    return JSONResponse(
        status_code=403,
        content={"detail": detail},
    )


class EmbedCSPMiddleware(BaseHTTPMiddleware):
    """
    Sprint 220b: Set CSP frame-ancestors on /embed routes to allow iframe embedding.

    Without this, browsers block iframing due to X-Frame-Options: DENY (default).
    Local development also disables browser caching for embed assets. Rebuilding
    dist-embed changes hashed chunk filenames, and stale cached entry chunks can
    otherwise request deleted dynamic chunks and break answer rendering.
    Only applies to /embed paths — other routes remain unaffected.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)

        if request.url.path.startswith("/embed"):
            from app.core.config import settings

            if (
                settings.environment != "production"
                and response.status_code == 404
                and request.url.path.startswith("/embed/assets/")
                and (replacement := _find_embed_asset_replacement(request.url.path))
            ):
                response = FileResponse(replacement)

            origins = settings.embed_allowed_origins.strip()
            if origins:
                # Space-separated origins → CSP frame-ancestors directive
                frame_ancestors = f"frame-ancestors 'self' {origins}"
            else:
                frame_ancestors = "frame-ancestors 'self'"

            response.headers["Content-Security-Policy"] = frame_ancestors
            if settings.environment != "production":
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            # Remove X-Frame-Options — it conflicts with CSP frame-ancestors
            # and older browsers use it to block iframes
            if "X-Frame-Options" in response.headers:
                del response.headers["X-Frame-Options"]

        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject / propagate X-Request-ID for every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

        # Bind to structlog context so all log lines include request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Store on request state for access in route handlers
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class OrgContextMiddleware(BaseHTTPMiddleware):
    """
    Propagate organization context into ContextVar for multi-tenant isolation.

    Resolution priority (Sprint 175):
      1. X-Organization-ID header (explicit — from client or Nginx proxy)
      2. Subdomain extraction from Host header (when subdomain_base_domain configured)
      3. None (no org context — personal workspace)

    Sprint 24: Feature-gated by settings.enable_multi_tenant.
    When disabled, this middleware is a no-op pass-through.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        from app.core.config import settings

        if not settings.enable_multi_tenant:
            return await call_next(request)

        from app.core.org_context import current_org_id, current_org_allowed_domains

        # Sprint 175: Priority — header first, then subdomain fallback
        org_id = request.headers.get("X-Organization-ID")
        if not org_id and settings.subdomain_base_domain:
            host = request.headers.get("host", "")
            org_id = extract_org_from_subdomain(host, settings.subdomain_base_domain)

        org_rejection = _validate_header_org_against_bearer_token(
            request,
            org_id,
            settings,
        )
        if org_rejection is not None:
            return org_rejection

        token_org = None
        token_domains = None

        if org_id:
            token_org = current_org_id.set(org_id)
            structlog.contextvars.bind_contextvars(organization_id=org_id)

            # Load allowed_domains from repository
            # Sprint 194c (B6): Fail-closed — if DB lookup fails, clear org context
            # entirely rather than proceeding with org_id set but no domain restrictions.
            try:
                from app.repositories.organization_repository import get_organization_repository
                repo = get_organization_repository()
                org = repo.get_organization(org_id)
                if org and org.allowed_domains:
                    token_domains = current_org_allowed_domains.set(org.allowed_domains)
            except Exception as e:
                logger.warning(
                    "[MIDDLEWARE] Failed to load org for %s: %s — rejecting request (fail-closed)",
                    org_id, e,
                )
                # Fail-closed: reject request since we can't verify org permissions
                if token_org is not None:
                    current_org_id.reset(token_org)
                    token_org = None
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Không thể xác minh tổ chức. Vui lòng thử lại sau."},
                )

        try:
            response: Response = await call_next(request)
        finally:
            if token_org is not None:
                current_org_id.reset(token_org)
            if token_domains is not None:
                current_org_allowed_domains.reset(token_domains)

        return response
