"""
Issue #88: Tests for the /auth/dev-login local-development endpoint.

Coverage:
  - Status probe reports the flag accurately
  - Endpoint returns 404 when flag is off (no fingerprint in production)
  - Endpoint mints a token pair when flag is on + private source
  - Endpoint refuses non-private source IPs (defense in depth)
  - Production validator hard-fails when enable_dev_login is True
  - Override fields (email/name/role) are honoured
  - Invalid role is rejected
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_db_degraded_cooldown():
    from app.core.database import clear_shared_database_unavailable

    clear_shared_database_unavailable()
    yield
    clear_shared_database_unavailable()


def _user_dict(**overrides):
    base = {
        "id": "dev-user-1",
        "email": "dev@localhost",
        "name": "Dev User",
        "avatar_url": None,
        "role": "admin",
        "platform_role": "platform_admin",
    }
    base.update(overrides)
    return base


def _token_pair():
    pair = MagicMock()
    pair.access_token = "ACCESS"
    pair.refresh_token = "REFRESH"
    pair.expires_in = 900
    return pair


def _mock_request(host: str | None = "127.0.0.1"):
    req = MagicMock()
    req.client = MagicMock(host=host) if host else None
    req.headers = {"user-agent": "pytest"}
    return req


# ---------------------------------------------------------------------------
# Status probe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_reports_flag_when_enabled():
    s = MagicMock()
    s.enable_dev_login = True
    with patch("app.auth.dev_login_router.settings", s):
        from app.auth.dev_login_router import dev_login_status
        result = await dev_login_status()
    assert result == {"enabled": True}


@pytest.mark.asyncio
async def test_status_reports_flag_when_disabled():
    s = MagicMock()
    s.enable_dev_login = False
    with patch("app.auth.dev_login_router.settings", s):
        from app.auth.dev_login_router import dev_login_status
        result = await dev_login_status()
    assert result == {"enabled": False}


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dev_login_404_when_flag_disabled():
    """Flag off → 404 so production probes get no fingerprint of the endpoint."""
    from fastapi import HTTPException
    s = MagicMock()
    s.enable_dev_login = False
    with patch("app.auth.dev_login_router.settings", s):
        from app.auth.dev_login_router import dev_login
        with pytest.raises(HTTPException) as exc:
            await dev_login(_mock_request("127.0.0.1"), body=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_dev_login_403_when_source_not_private():
    """Non-private source IP refused even with flag on.

    Use 8.8.8.8 (Google DNS) — TEST-NET ranges like 203.0.113/24 are
    classified as private by Python's ipaddress module since they're
    reserved for documentation, not real internet routing.
    """
    from fastapi import HTTPException
    s = MagicMock()
    s.enable_dev_login = True
    s.dev_login_default_email = "dev@localhost"
    s.dev_login_default_role = "admin"
    with patch("app.auth.dev_login_router.settings", s):
        from app.auth.dev_login_router import dev_login
        with pytest.raises(HTTPException) as exc:
            await dev_login(_mock_request("8.8.8.8"), body=None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_dev_login_success_returns_token_pair_shape():
    """Happy path: minted JWT + refresh + user object matches OAuth callback shape."""
    s = MagicMock()
    s.enable_dev_login = True
    s.dev_login_default_email = "dev@localhost"
    s.dev_login_default_role = "admin"
    s.enable_multi_tenant = False
    s.default_organization_id = ""

    with (
        patch("app.auth.dev_login_router.settings", s),
        patch(
            "app.auth.dev_login_router.find_or_create_by_provider",
            new=AsyncMock(return_value=_user_dict()),
        ),
        patch(
            "app.auth.dev_login_router.create_token_pair",
            new=AsyncMock(return_value=_token_pair()),
        ),
    ):
        from app.auth.dev_login_router import dev_login
        response = await dev_login(_mock_request("127.0.0.1"), body=None)

    # JSONResponse — inspect the body bytes via .body attribute
    import json
    payload = json.loads(response.body)
    assert payload["access_token"] == "ACCESS"
    assert payload["refresh_token"] == "REFRESH"
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == 900
    assert payload["user"]["id"] == "dev-user-1"
    assert payload["user"]["email"] == "dev@localhost"
    assert payload["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_dev_login_logs_hash_refs_without_raw_identity(caplog):
    """Successful dev-login diagnostics should not expose raw user IDs or email."""
    raw_user_id = "dev-user-private"
    raw_email = "private-dev@example.local"

    s = MagicMock()
    s.enable_dev_login = True
    s.dev_login_default_email = raw_email
    s.dev_login_default_role = "admin"
    s.enable_multi_tenant = False
    s.default_organization_id = ""

    from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

    with (
        patch("app.auth.dev_login_router.settings", s),
        patch(
            "app.auth.dev_login_router.find_or_create_by_provider",
            new=AsyncMock(return_value=_user_dict(id=raw_user_id, email=raw_email)),
        ),
        patch(
            "app.auth.dev_login_router.create_token_pair",
            new=AsyncMock(return_value=_token_pair()),
        ),
        patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock),
    ):
        from app.auth.dev_login_router import dev_login

        with caplog.at_level(logging.INFO, logger="app.auth.dev_login_router"):
            await dev_login(_mock_request("127.0.0.1"), body=None)

    assert raw_user_id not in caplog.text
    assert raw_email not in caplog.text
    assert f"user_ref={hash_runtime_identifier(raw_user_id)}" in caplog.text
    assert f"email_ref={hash_runtime_identifier(raw_email)}" in caplog.text


@pytest.mark.asyncio
async def test_dev_login_mints_token_with_default_org_claim():
    """Multi-tenant dev login must embed the same org it returns to the client."""
    s = MagicMock()
    s.enable_dev_login = True
    s.dev_login_default_email = "dev@localhost"
    s.dev_login_default_role = "admin"
    s.enable_multi_tenant = True
    s.default_organization_id = "default"

    create_pair = AsyncMock(return_value=_token_pair())

    with (
        patch("app.auth.dev_login_router.settings", s),
        patch(
            "app.auth.dev_login_router.find_or_create_by_provider",
            new=AsyncMock(return_value=_user_dict()),
        ),
        patch("app.auth.dev_login_router.create_token_pair", new=create_pair),
        patch(
            "app.auth.dev_login_router.ensure_user_org_membership",
            new=AsyncMock(return_value=True),
        ) as ensure_membership,
    ):
        from app.auth.dev_login_router import dev_login
        response = await dev_login(_mock_request("127.0.0.1"), body=None)

    import json
    payload = json.loads(response.body)
    kwargs = create_pair.call_args.kwargs
    assert kwargs["active_organization_id"] == "default"
    assert kwargs["role_source"] == "platform"
    assert payload["organization_id"] == "default"
    assert payload["user"]["active_organization_id"] == "default"
    ensure_membership.assert_awaited_once_with("dev-user-1", "default")


@pytest.mark.asyncio
async def test_dev_login_honours_body_overrides():
    """Custom email/name/role in the body are passed to user creation."""
    from app.auth.dev_login_router import DevLoginRequest

    s = MagicMock()
    s.enable_dev_login = True
    s.dev_login_default_email = "dev@localhost"
    s.dev_login_default_role = "admin"
    s.enable_multi_tenant = False
    s.default_organization_id = ""

    captured: dict = {}

    async def _fake_find_or_create(**kwargs):
        captured.update(kwargs)
        return _user_dict(email=kwargs["email"], name=kwargs["name"], role=kwargs["role"])

    with (
        patch("app.auth.dev_login_router.settings", s),
        patch(
            "app.auth.dev_login_router.find_or_create_by_provider",
            new=_fake_find_or_create,
        ),
        patch(
            "app.auth.dev_login_router.create_token_pair",
            new=AsyncMock(return_value=_token_pair()),
        ),
    ):
        from app.auth.dev_login_router import dev_login
        body = DevLoginRequest(
            email="alice@localhost", name="Alice", role="teacher"
        )
        await dev_login(_mock_request("127.0.0.1"), body=body)

    assert captured["email"] == "alice@localhost"
    assert captured["name"] == "Alice"
    assert captured["role"] == "teacher"
    assert captured["provider"] == "dev"


@pytest.mark.asyncio
async def test_dev_login_rejects_invalid_role():
    """Roles outside the allowed set must be rejected with 400."""
    from fastapi import HTTPException
    from app.auth.dev_login_router import DevLoginRequest

    s = MagicMock()
    s.enable_dev_login = True
    s.dev_login_default_email = "dev@localhost"
    s.dev_login_default_role = "admin"

    with patch("app.auth.dev_login_router.settings", s):
        from app.auth.dev_login_router import dev_login
        body = DevLoginRequest(role="superuser")
        with pytest.raises(HTTPException) as exc:
            await dev_login(_mock_request("127.0.0.1"), body=body)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Production safety validator
# ---------------------------------------------------------------------------

def test_production_validator_rejects_dev_login_enabled():
    """Settings refuses to construct when enable_dev_login=True in production."""
    from app.core.config._settings_validation import build_validate_production_security

    config_logger = MagicMock()
    validator = build_validate_production_security(config_logger)

    settings_mock = MagicMock()
    settings_mock.environment = "production"
    settings_mock.jwt_secret_key = "a-very-real-prod-secret-32-chars-long-x"
    settings_mock.cors_origins = ["https://wiii.holilihu.online"]
    settings_mock.api_key = "a-real-prod-key-with-enough-bytes"
    settings_mock.enable_magic_link_auth = False
    settings_mock.resend_api_key = ""
    settings_mock.enable_google_oauth = False
    settings_mock.google_oauth_client_id = ""
    settings_mock.google_oauth_client_secret = ""
    settings_mock.enable_dev_login = True

    with pytest.raises(ValueError, match="enable_dev_login=True is forbidden"):
        validator(settings_mock)


def test_production_validator_passes_when_dev_login_off():
    """Default off in production → validator passes (assuming other fields valid)."""
    from app.core.config._settings_validation import build_validate_production_security

    config_logger = MagicMock()
    validator = build_validate_production_security(config_logger)

    settings_mock = MagicMock()
    settings_mock.environment = "production"
    settings_mock.jwt_secret_key = "a-very-real-prod-secret-32-chars-long-x"
    settings_mock.cors_origins = ["https://wiii.holilihu.online"]
    settings_mock.api_key = "a-real-prod-key-with-enough-bytes"
    settings_mock.enable_magic_link_auth = False
    settings_mock.resend_api_key = ""
    settings_mock.enable_google_oauth = False
    settings_mock.google_oauth_client_id = ""
    settings_mock.google_oauth_client_secret = ""
    settings_mock.enable_dev_login = False

    # No raise = pass
    result = validator(settings_mock)
    assert result is settings_mock


def test_dev_login_allowed_in_development_environment():
    """Validator permits enable_dev_login=True when environment != production."""
    from app.core.config._settings_validation import build_validate_production_security

    config_logger = MagicMock()
    validator = build_validate_production_security(config_logger)

    settings_mock = MagicMock()
    settings_mock.environment = "development"
    settings_mock.enable_dev_login = True

    # Not production → validator skips entirely
    result = validator(settings_mock)
    assert result is settings_mock
