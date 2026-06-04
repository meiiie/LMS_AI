"""
Sprint 159: "Cầu Nối Trực Tiếp" — LMS Token Exchange tests.

Tests:
  - Config integration (2 tests)
  - Connector secret resolution (4 tests)
  - HMAC validation (4 tests)
  - Timestamp validation (4 tests)
  - Role mapping (5 tests)
  - Token exchange (3 tests)

Total: 22 tests
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_hmac(body_bytes: bytes, secret: str) -> str:
    """Create a valid HMAC-SHA256 signature."""
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _mock_settings(**overrides):
    """Create a mock settings object with defaults."""
    defaults = {
        "enable_lms_token_exchange": False,
        "lms_token_exchange_max_age": 300,
        "lms_webhook_secret": None,
        "lms_connectors": "[]",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _mock_lms_request(payload: dict, signature: str = "sha256=test") -> MagicMock:
    from starlette.requests import Request

    body = json.dumps(payload).encode("utf-8")

    async def _receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/lms/token",
            "headers": [(b"x-lms-signature", signature.encode("utf-8"))],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        },
        _receive,
    )


# ===========================================================================
# TestConfigIntegration
# ===========================================================================


class TestConfigIntegration:
    """Test config fields."""

    def test_feature_flag_default_false(self):
        """enable_lms_token_exchange defaults to False (without .env)."""
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test", _env_file=None)
        assert s.enable_lms_token_exchange is False

    def test_max_age_has_range(self):
        """lms_token_exchange_max_age has ge=30, le=600."""
        from app.core.config import Settings
        field = Settings.model_fields["lms_token_exchange_max_age"]
        metadata = field.metadata
        # Check from pydantic Field constraints
        assert field.default == 300
        # ge and le are stored in field metadata
        has_ge = any(getattr(m, "ge", None) == 30 for m in metadata)
        has_le = any(getattr(m, "le", None) == 600 for m in metadata)
        assert has_ge, "Should have ge=30"
        assert has_le, "Should have le=600"


# ===========================================================================
# TestConnectorSecretResolution
# ===========================================================================


class TestConnectorSecretResolution:
    """Test _resolve_connector_secret fallback chain."""

    def test_json_priority(self):
        """JSON connectors take priority over flat secret."""
        connectors = json.dumps([{"id": "lms-1", "webhook_secret": "json-secret"}])
        with patch("app.auth.lms_token_exchange.settings", _mock_settings(
            lms_connectors=connectors,
            lms_webhook_secret="flat-secret",
        )):
            from app.auth.lms_token_exchange import _resolve_connector_secret
            assert _resolve_connector_secret("lms-1") == "json-secret"

    def test_registry_fallback(self):
        """When JSON has no match, falls back to LMSConnectorRegistry."""
        mock_config = MagicMock()
        mock_config.webhook_secret = "registry-secret"
        mock_registry = MagicMock()
        mock_registry.get_connector.return_value = mock_config

        MockRegistryClass = MagicMock()
        MockRegistryClass.get_instance.return_value = mock_registry

        with (
            patch("app.auth.lms_token_exchange.settings", _mock_settings()),
            patch.dict("sys.modules", {}),
            patch("app.integrations.lms.base.LMSConnectorRegistry", MockRegistryClass, create=True),
        ):
            from app.auth.lms_token_exchange import _resolve_connector_secret
            assert _resolve_connector_secret("lms-2") == "registry-secret"

    def test_flat_fallback(self):
        """When no connector match, falls back to flat lms_webhook_secret."""
        with patch("app.auth.lms_token_exchange.settings", _mock_settings(
            lms_webhook_secret="flat-secret",
        )):
            from app.auth.lms_token_exchange import _resolve_connector_secret
            assert _resolve_connector_secret("unknown") == "flat-secret"

    def test_none_when_no_secret(self):
        """Returns None when no secret is configured anywhere."""
        with patch("app.auth.lms_token_exchange.settings", _mock_settings()):
            from app.auth.lms_token_exchange import _resolve_connector_secret
            assert _resolve_connector_secret("unknown") is None


# ===========================================================================
# TestHMACValidation
# ===========================================================================


class TestHMACValidation:
    """Test HMAC signature validation."""

    def test_valid_passes(self):
        """Valid HMAC signature passes."""
        secret = "test-secret"
        body = b'{"connector_id":"lms-1","lms_user_id":"s1"}'
        sig = _make_hmac(body, secret)

        with patch("app.auth.lms_token_exchange._resolve_connector_secret", return_value=secret):
            from app.auth.lms_token_exchange import validate_lms_signature
            assert validate_lms_signature("lms-1", body, sig) is True

    def test_invalid_raises(self):
        """Invalid HMAC signature returns False."""
        secret = "test-secret"
        body = b'{"connector_id":"lms-1"}'

        with patch("app.auth.lms_token_exchange._resolve_connector_secret", return_value=secret):
            from app.auth.lms_token_exchange import validate_lms_signature
            assert validate_lms_signature("lms-1", body, "sha256=wrong") is False

    def test_missing_signature_raises(self):
        """Missing signature raises ValueError."""
        with patch("app.auth.lms_token_exchange._resolve_connector_secret", return_value="secret"):
            from app.auth.lms_token_exchange import validate_lms_signature
            with pytest.raises(ValueError, match="Missing signature"):
                validate_lms_signature("lms-1", b"{}", "")

    def test_no_secret_raises(self):
        """No configured secret raises ValueError."""
        with patch("app.auth.lms_token_exchange._resolve_connector_secret", return_value=None):
            from app.auth.lms_token_exchange import validate_lms_signature
            with pytest.raises(ValueError, match="No HMAC secret"):
                validate_lms_signature("lms-1", b"{}", "sha256=abc")


# ===========================================================================
# TestTimestampValidation
# ===========================================================================


class TestTimestampValidation:
    """Test timestamp replay protection."""

    def test_recent_passes(self):
        """Timestamp within max_age passes."""
        with patch("app.auth.lms_token_exchange.settings", _mock_settings(lms_token_exchange_max_age=300)):
            from app.auth.lms_token_exchange import validate_request_timestamp
            assert validate_request_timestamp(int(time.time())) is True

    def test_old_rejected(self):
        """Timestamp too old is rejected."""
        with patch("app.auth.lms_token_exchange.settings", _mock_settings(lms_token_exchange_max_age=300)):
            from app.auth.lms_token_exchange import validate_request_timestamp
            old_ts = int(time.time()) - 600
            with pytest.raises(ValueError, match="too far"):
                validate_request_timestamp(old_ts)

    def test_future_rejected(self):
        """Timestamp too far in the future is rejected."""
        with patch("app.auth.lms_token_exchange.settings", _mock_settings(lms_token_exchange_max_age=300)):
            from app.auth.lms_token_exchange import validate_request_timestamp
            future_ts = int(time.time()) + 600
            with pytest.raises(ValueError, match="too far"):
                validate_request_timestamp(future_ts)

    def test_none_passes_backward_compat(self):
        """None timestamp passes (backward compat)."""
        from app.auth.lms_token_exchange import validate_request_timestamp
        assert validate_request_timestamp(None) is True


# ===========================================================================
# TestRoleMapping
# ===========================================================================


class TestRoleMapping:
    """Test LMS → Wiii role mapping."""

    def test_student(self):
        from app.auth.lms_token_exchange import map_lms_role
        assert map_lms_role("student") == "student"

    def test_teacher_variants(self):
        from app.auth.lms_token_exchange import map_lms_host_role, map_lms_role
        assert map_lms_host_role("teacher") == "teacher"
        assert map_lms_role("instructor") == "teacher"
        assert map_lms_role("professor") == "teacher"
        assert map_lms_role("Lecturer") == "teacher"  # case-insensitive

    def test_admin_variants(self):
        from app.auth.lms_token_exchange import map_lms_host_role, map_lms_role
        assert map_lms_host_role("admin") == "admin"
        assert map_lms_host_role("ORG_ADMIN") == "org_admin"
        assert map_lms_role("admin") == "teacher"
        assert map_lms_role("Administrator") == "teacher"
        assert map_lms_role("ORG_ADMIN") == "teacher"

    def test_unknown_defaults_to_student(self):
        from app.auth.lms_token_exchange import map_lms_role
        assert map_lms_role("unknown_role") == "student"
        assert map_lms_role("superadmin") == "student"

    def test_none_defaults_to_student(self):
        from app.auth.lms_token_exchange import map_lms_role
        assert map_lms_role(None) == "student"


# ===========================================================================
# TestTokenExchange
# ===========================================================================


class TestTokenExchange:
    """Test end-to-end token exchange flow."""

    @pytest.mark.asyncio
    async def test_new_user_created(self):
        """Token exchange creates new user when not found."""
        new_user = {"id": "u1", "email": "s@lms.edu", "name": "Student 1", "role": "student"}
        mock_token = MagicMock(
            access_token="at", refresh_token="rt",
            token_type="bearer", expires_in=1800,
        )

        with (
            patch("app.auth.user_service.find_or_create_by_provider", new_callable=AsyncMock, return_value=new_user) as mock_find,
            patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock, return_value=mock_token),
            patch("app.auth.lms_token_exchange._ensure_org_membership", new_callable=AsyncMock),
        ):
            from app.auth.lms_token_exchange import exchange_lms_token
            result = await exchange_lms_token(
                connector_id="maritime-lms",
                lms_user_id="student-42",
                email="s@lms.edu",
                name="Student 1",
                role="student",
            )
            assert result["access_token"] == "at"
            assert result["user"]["id"] == "u1"
            assert result["user"]["platform_role"] == "user"
            assert result["user"]["host_role"] == "student"
            mock_find.assert_called_once()
            assert mock_find.call_args.kwargs["provider"] == "lms"
            assert mock_find.call_args.kwargs["provider_issuer"] == "maritime-lms"
            assert mock_find.call_args.kwargs["role"] == "student"

    @pytest.mark.asyncio
    async def test_existing_user_found(self):
        """Token exchange returns existing user without creating."""
        existing = {"id": "u1", "email": "s@lms.edu", "name": "Student 1", "role": "student"}
        mock_token = MagicMock(
            access_token="at", refresh_token="rt",
            token_type="bearer", expires_in=1800,
        )

        with (
            patch("app.auth.user_service.find_or_create_by_provider", new_callable=AsyncMock, return_value=existing),
            patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock, return_value=mock_token) as mock_create,
            patch("app.auth.lms_token_exchange._ensure_org_membership", new_callable=AsyncMock),
        ):
            from app.auth.lms_token_exchange import exchange_lms_token
            result = await exchange_lms_token(
                connector_id="maritime-lms",
                lms_user_id="student-42",
            )
            assert result["access_token"] == "at"
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["auth_method"] == "lms"
            assert mock_create.call_args.kwargs["platform_role"] == "user"
            assert mock_create.call_args.kwargs["identity_version"] == "2"

    @pytest.mark.asyncio
    async def test_org_membership_added(self):
        """Token exchange adds org membership when organization_id provided."""
        user = {"id": "u1", "email": None, "name": None, "role": "student"}
        mock_token = MagicMock(
            access_token="at", refresh_token="rt",
            token_type="bearer", expires_in=1800,
        )

        with (
            patch("app.auth.user_service.find_or_create_by_provider", new_callable=AsyncMock, return_value=user),
            patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock, return_value=mock_token),
            patch("app.auth.lms_token_exchange._ensure_org_membership", new_callable=AsyncMock) as mock_org,
        ):
            from app.auth.lms_token_exchange import exchange_lms_token
            result = await exchange_lms_token(
                connector_id="lms-1",
                lms_user_id="s1",
                organization_id="maritime-org",
            )
            mock_org.assert_called_once_with("u1", "maritime-org")
            assert result["user"]["id"] == "u1"

    @pytest.mark.asyncio
    async def test_adminish_lms_role_stays_host_scoped(self):
        """LMS admin/org-admin should not become Wiii platform admin."""
        user = {"id": "u-admin", "email": "a@lms.edu", "name": "Admin", "role": "teacher"}
        mock_token = MagicMock(
            access_token="at", refresh_token="rt",
            token_type="bearer", expires_in=1800,
        )

        with (
            patch("app.auth.user_service.find_or_create_by_provider", new_callable=AsyncMock, return_value=user),
            patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock, return_value=mock_token) as mock_create,
            patch("app.auth.lms_token_exchange._ensure_org_membership", new_callable=AsyncMock),
        ):
            from app.auth.lms_token_exchange import exchange_lms_token
            result = await exchange_lms_token(
                connector_id="maritime-lms",
                lms_user_id="admin-42",
                role="ORG_ADMIN",
            )

            assert result["user"]["role"] == "teacher"
            assert result["user"]["platform_role"] == "user"
            assert result["user"]["host_role"] == "org_admin"
            assert mock_create.call_args.kwargs["role"] == "teacher"
            assert mock_create.call_args.kwargs["platform_role"] == "user"
            assert mock_create.call_args.kwargs["host_role"] == "org_admin"


# ===========================================================================
# TestLMSAuthRouterDiagnostics
# ===========================================================================


class TestLMSAuthRouterDiagnostics:
    """Test LMS auth router diagnostics privacy."""

    @pytest.mark.asyncio
    async def test_token_exchange_failure_redacts_http_log_and_audit_reason(self, caplog):
        """Exchange failures must not expose raw LMS identity or secrets."""
        from fastapi import HTTPException
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_connector = "lms-private-connector"
        raw_lms_user = "lms-private-user"
        raw_email = "student-private@example.edu"
        raw_org = "org-private-lms"
        raw_secret = "lms-secret-private-value"
        request = _mock_lms_request(
            {
                "connector_id": raw_connector,
                "lms_user_id": raw_lms_user,
                "email": raw_email,
                "organization_id": raw_org,
                "timestamp": int(time.time()),
            }
        )
        audit_log = AsyncMock()

        with (
            patch("app.auth.lms_token_exchange.validate_lms_signature", return_value=True),
            patch("app.auth.lms_token_exchange.validate_request_timestamp", return_value=True),
            patch(
                "app.auth.lms_token_exchange.exchange_lms_token",
                new=AsyncMock(
                    side_effect=RuntimeError(
                        f"failed connector={raw_connector} user={raw_lms_user} "
                        f"email={raw_email} org={raw_org} secret={raw_secret}"
                    )
                ),
            ),
            patch("app.auth.auth_audit.log_auth_event", audit_log),
        ):
            from app.auth.lms_auth_router import lms_token_exchange

            with caplog.at_level(logging.ERROR, logger="app.auth.lms_auth_router"):
                with pytest.raises(HTTPException) as exc:
                    await lms_token_exchange(request)

        assert exc.value.status_code == 500
        assert exc.value.detail == "Token exchange failed"
        for raw_value in (raw_connector, raw_lms_user, raw_email, raw_org, raw_secret):
            assert raw_value not in caplog.text
        assert f"connector_ref={hash_runtime_identifier(raw_connector)}" in caplog.text
        assert f"lms_user_ref={hash_runtime_identifier(raw_lms_user)}" in caplog.text
        assert f"org_ref={hash_runtime_identifier(raw_org)}" in caplog.text
        assert "<redacted-secret>" in caplog.text
        audit_log.assert_awaited_once()
        audit_kwargs = audit_log.await_args.kwargs
        assert audit_kwargs["reason"]
        for raw_value in (raw_connector, raw_lms_user, raw_email, raw_org, raw_secret):
            assert raw_value not in audit_kwargs["reason"]
        assert audit_kwargs["metadata"] == {
            "connector_ref": hash_runtime_identifier(raw_connector),
        }

    @pytest.mark.asyncio
    async def test_signature_config_error_uses_generic_http_detail_and_hash_log(self, caplog):
        """Signature setup errors should not expose raw connector ids or signatures."""
        from fastapi import HTTPException
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_connector = "lms-private-connector"
        raw_signature = "sha256=private-signature"
        request = _mock_lms_request(
            {
                "connector_id": raw_connector,
                "lms_user_id": "student-1",
            },
            signature=raw_signature,
        )

        with patch(
            "app.auth.lms_token_exchange.validate_lms_signature",
            side_effect=ValueError(
                f"No HMAC secret configured for connector '{raw_connector}' "
                f"signature={raw_signature}"
            ),
        ):
            from app.auth.lms_auth_router import lms_token_exchange

            with caplog.at_level(logging.WARNING, logger="app.auth.lms_auth_router"):
                with pytest.raises(HTTPException) as exc:
                    await lms_token_exchange(request)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Invalid HMAC signature"
        assert raw_connector not in caplog.text
        assert raw_signature not in caplog.text
        assert f"connector_ref={hash_runtime_identifier(raw_connector)}" in caplog.text
        assert "<redacted-secret>" in caplog.text

    @pytest.mark.asyncio
    async def test_connector_grant_warning_logs_hash_refs(self, caplog):
        """Connector-grant refresh warnings should not expose raw IDs."""
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_user = "wiii-private-user"
        raw_connector = "lms-private-connector"
        raw_org = "org-private-lms"
        user = {"id": raw_user, "email": "student@example.edu", "name": "S", "role": "student"}
        mock_token = MagicMock(
            access_token="at", refresh_token="rt",
            token_type="bearer", expires_in=1800,
        )

        with (
            patch("app.auth.user_service.find_or_create_by_provider", new_callable=AsyncMock, return_value=user),
            patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock, return_value=mock_token),
            patch("app.auth.lms_token_exchange._ensure_org_membership", new_callable=AsyncMock),
            patch(
                "app.repositories.connector_grant_repository.upsert_connector_grant",
                new=AsyncMock(
                    side_effect=RuntimeError(
                        f"grant failed user={raw_user} connector={raw_connector} org={raw_org}"
                    )
                ),
                create=True,
            ),
        ):
            from app.auth.lms_token_exchange import exchange_lms_token

            with caplog.at_level(logging.WARNING, logger="app.auth.lms_token_exchange"):
                await exchange_lms_token(
                    connector_id=raw_connector,
                    lms_user_id="student-1",
                    organization_id=raw_org,
                )

        assert raw_user not in caplog.text
        assert raw_connector not in caplog.text
        assert raw_org not in caplog.text
        assert f"user_ref={hash_runtime_identifier(raw_user)}" in caplog.text
        assert f"connector_ref={hash_runtime_identifier(raw_connector)}" in caplog.text
        assert f"org_ref={hash_runtime_identifier(raw_org)}" in caplog.text
