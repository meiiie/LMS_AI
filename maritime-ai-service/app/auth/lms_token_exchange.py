"""
Sprint 159: "Cầu Nối Trực Tiếp" — LMS Backend Token Exchange.

Core service for HMAC-signed backend-to-backend token exchange.
Spring Boot LMS sends signed request → Wiii returns JWT token pair.

Security:
  - HMAC-SHA256 signature verification (reuses app.integrations.lms.base)
  - Replay protection via timestamp validation
  - Identity federation via find_or_create_by_provider (Sprint 158)
"""
import json
import logging
import time
from typing import Optional

from app.core.config import settings
from app.core.security import map_host_role_to_legacy_role, normalize_host_role
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_MAX_LMS_TOKEN_DIAGNOSTIC_LENGTH = 500


def _lms_token_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_lms_token_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    for secret_value in secret_values:
        secret = str(secret_value or "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    return redact_runtime_secret_text(text, max_length=_MAX_LMS_TOKEN_DIAGNOSTIC_LENGTH)

# ---------------------------------------------------------------------------
# Role mapping: LMS roles → Wiii roles
# ---------------------------------------------------------------------------
_LMS_HOST_ROLE_MAP = {
    # Teacher variants
    "teacher": "teacher",
    "instructor": "teacher",
    "professor": "teacher",
    "lecturer": "teacher",
    "ta": "teacher",
    "teaching_assistant": "teacher",
    # Admin variants
    "admin": "admin",
    "org_admin": "org_admin",
    "administrator": "admin",
    "manager": "admin",
    # Student is default
    "student": "student",
    "learner": "student",
}


def map_lms_host_role(lms_role: Optional[str]) -> str:
    """Map an LMS role string to a host-local role."""
    if not lms_role or not isinstance(lms_role, str):
        return "student"
    raw = lms_role.lower().strip()
    return normalize_host_role(_LMS_HOST_ROLE_MAP.get(raw, raw))


def map_lms_role(lms_role: Optional[str]) -> str:
    """Map an LMS role string to the legacy compatibility role used today."""
    return map_host_role_to_legacy_role(map_lms_host_role(lms_role))


# ---------------------------------------------------------------------------
# Connector secret resolution (3-level fallback)
# ---------------------------------------------------------------------------

def _resolve_connector_secret(connector_id: Optional[str]) -> Optional[str]:
    """
    Resolve the HMAC secret for a given connector.

    Fallback chain:
    1. settings.lms_connectors JSON array (by connector_id)
    2. LMSConnectorRegistry singleton (if available)
    3. settings.lms_webhook_secret (flat single-LMS compat)
    """
    # 1. JSON connectors config
    if connector_id:
        try:
            connectors = json.loads(settings.lms_connectors or "[]")
            for c in connectors:
                if c.get("id") == connector_id:
                    secret = c.get("webhook_secret")
                    if secret:
                        return secret
        except (json.JSONDecodeError, TypeError):
            pass

        # 2. Registry fallback
        try:
            from app.integrations.lms.base import LMSConnectorRegistry
            registry = LMSConnectorRegistry.get_instance()
            config = registry.get_connector(connector_id)
            if config and config.webhook_secret:
                return config.webhook_secret
        except Exception:
            pass

    # 3. Flat secret fallback
    return settings.lms_webhook_secret


# ---------------------------------------------------------------------------
# HMAC validation
# ---------------------------------------------------------------------------

def validate_lms_signature(
    connector_id: Optional[str],
    body_bytes: bytes,
    signature: str,
) -> bool:
    """
    Validate HMAC-SHA256 signature for an LMS token exchange request.

    Args:
        connector_id: LMS connector identifier (for secret lookup)
        body_bytes: Raw request body
        signature: Value of X-LMS-Signature header (format: "sha256=<hex>")

    Returns:
        True if valid.

    Raises:
        ValueError if no secret is configured or signature format is wrong.
    """
    secret = _resolve_connector_secret(connector_id)
    if not secret:
        raise ValueError(f"No HMAC secret configured for connector '{connector_id}'")

    if not signature:
        raise ValueError("Missing signature")

    from app.integrations.lms.base import verify_hmac_sha256
    return verify_hmac_sha256(body_bytes, signature, secret)


# ---------------------------------------------------------------------------
# Timestamp / replay protection
# ---------------------------------------------------------------------------

def validate_request_timestamp(timestamp: Optional[int]) -> bool:
    """
    Validate that the request timestamp is within max_age window.

    Args:
        timestamp: Unix epoch seconds from the request body. None = skip check.

    Returns:
        True if valid (or timestamp is None for backward compat).

    Raises:
        ValueError if timestamp is too old or too far in the future.
    """
    if timestamp is None:
        if settings.environment == "production":
            raise ValueError("timestamp is required in production (replay protection)")
        logger.warning("Token exchange without timestamp — allowed in dev only")
        return True

    now = int(time.time())
    max_age = settings.lms_token_exchange_max_age
    diff = abs(now - timestamp)

    if diff > max_age:
        raise ValueError(
            f"Request timestamp too far from server time: {diff}s difference (max {max_age}s)"
        )
    return True


# ---------------------------------------------------------------------------
# Connector → Organization resolution
# ---------------------------------------------------------------------------

def _resolve_connector_org(connector_id: Optional[str]) -> Optional[str]:
    """Resolve the Wiii organization_id for a connector.

    Fallback chain:
    1. Connector config's organization_id field (explicit mapping)
    2. Connector id itself (convention: connector id = org id)

    This eliminates hardcoding on the LMS side — Wiii is SSOT for org mapping.
    """
    if not connector_id:
        return None

    # 1. Check connector config for explicit organization_id
    try:
        connectors = json.loads(settings.lms_connectors or "[]")
        for c in connectors:
            if c.get("id") == connector_id:
                org = c.get("organization_id")
                if org:
                    return org
                break  # Found connector but no org configured — fall through
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Registry fallback (adapter instance may have org configured)
    try:
        from app.integrations.lms.registry import get_lms_connector_registry
        registry = get_lms_connector_registry()
        adapter = registry.get(connector_id)
        if adapter:
            config = adapter.get_config()
            if config.organization_id:
                return config.organization_id
    except Exception:
        pass

    # 3. Convention: connector id IS the org id
    return connector_id


def _resolve_connector_name(connector_id: Optional[str]) -> Optional[str]:
    """Resolve a human-readable connector/workspace name when available."""
    if not connector_id:
        return None

    try:
        connectors = json.loads(settings.lms_connectors or "[]")
        for c in connectors:
            if c.get("id") == connector_id:
                return c.get("display_name") or c.get("name") or connector_id
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        from app.integrations.lms.registry import get_lms_connector_registry

        registry = get_lms_connector_registry()
        adapter = registry.get(connector_id)
        if adapter:
            config = adapter.get_config()
            return getattr(config, "display_name", None) or getattr(config, "name", None) or connector_id
    except Exception:
        pass

    return connector_id


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

async def exchange_lms_token(
    connector_id: str,
    lms_user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> dict:
    """
    Exchange LMS user credentials for a Wiii JWT token pair.

    1. find_or_create_by_provider("lms", lms_user_id, issuer=connector_id)
    2. Optional: ensure org membership
    3. create_token_pair(auth_method="lms")

    Returns dict with: access_token, refresh_token, token_type, expires_in, user
    """
    from app.auth.user_service import find_or_create_by_provider
    from app.auth.token_service import create_token_pair

    host_role = map_lms_host_role(role)
    wiii_role = map_lms_role(role)

    # Find or create user
    # email_verified=True: LMS backend is a trusted source (HMAC-signed request),
    # and the email comes from the LMS's own authenticated user database.
    # This allows identity federation to auto-link to existing Wiii accounts by email.
    user = await find_or_create_by_provider(
        provider="lms",
        provider_sub=lms_user_id,
        provider_issuer=connector_id,
        email=email,
        name=name,
        role=wiii_role,
        email_verified=True,
    )
    assert user is not None  # auto_create=True (default)

    # Resolve org: explicit request → connector config → connector id (convention)
    resolved_org = organization_id or _resolve_connector_org(connector_id)
    if resolved_org:
        await _ensure_org_membership(user["id"], resolved_org)

    # Create token pair
    token_pair = await create_token_pair(
        user_id=user["id"],
        email=user.get("email"),
        name=user.get("name"),
        role=wiii_role,
        platform_role="user",
        host_role=host_role,
        role_source="lms_host",
        active_organization_id=resolved_org,
        connector_id=connector_id,
        identity_version="2",
        auth_method="lms",
    )

    try:
        from app.repositories.connector_grant_repository import upsert_connector_grant

        await upsert_connector_grant(
            user_id=user["id"],
            connector_id=connector_id,
            host_type="lms",
            host_name=_resolve_connector_name(connector_id),
            host_user_id=lms_user_id,
            host_workspace_id=resolved_org or connector_id,
            host_organization_id=resolved_org,
            organization_id=resolved_org,
            granted_capabilities={
                "chat": True,
                "host_context": True,
                "host_actions": True,
                "course_generation": True,
            },
            auth_metadata={
                "role_source": "lms_host",
                "last_host_role": host_role,
                "email": user.get("email"),
            },
            status="active",
        )
    except Exception as exc:
        logger.warning(
            "Could not refresh connector grant user_ref=%s connector_ref=%s org_ref=%s: %s",
            _lms_token_ref(user["id"]),
            _lms_token_ref(connector_id),
            _lms_token_ref(resolved_org),
            _safe_lms_token_detail(exc, user["id"], connector_id, resolved_org),
        )

    return {
        "access_token": token_pair.access_token,
        "refresh_token": token_pair.refresh_token,
        "token_type": "bearer",
        "expires_in": token_pair.expires_in,
        "user": {
            "id": user["id"],
            "email": user.get("email"),
            "name": user.get("name"),
            "role": wiii_role,
            "platform_role": "user",
            "host_role": host_role,
            "role_source": "lms_host",
            "identity_version": "2",
        },
        "organization_id": resolved_org,
    }


async def _ensure_org_membership(user_id: str, organization_id: str) -> None:
    """Add user to organization if not already a member. Safe no-op on conflict."""
    try:
        from app.core.database import get_asyncpg_pool
        pool = await get_asyncpg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_organizations (user_id, organization_id, role, joined_at)
                VALUES ($1, $2, 'member', NOW())
                ON CONFLICT (user_id, organization_id) DO NOTHING
                """,
                user_id, organization_id,
            )
    except Exception:
        logger.warning(
            "Could not ensure org membership user_ref=%s org_ref=%s",
            _lms_token_ref(user_id),
            _lms_token_ref(organization_id),
        )
