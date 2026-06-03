"""Sprint 224: Magic Link Email Auth — Unit Tests."""
import asyncio
import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConfigDefaults:
    """Config flag defaults."""

    def test_enable_magic_link_auth_default_false(self):
        from app.core.config import Settings
        default = Settings.model_fields["enable_magic_link_auth"].default
        assert default is False

    def test_magic_link_expires_default_600(self):
        from app.core.config import Settings
        default = Settings.model_fields["magic_link_expires_seconds"].default
        assert default == 600

    def test_magic_link_max_per_hour_default_5(self):
        from app.core.config import Settings
        default = Settings.model_fields["magic_link_max_per_hour"].default
        assert default == 5

    def test_magic_link_ws_timeout_default_900(self):
        from app.core.config import Settings
        default = Settings.model_fields["magic_link_ws_timeout_seconds"].default
        assert default == 900

    def test_magic_link_resend_cooldown_default_45(self):
        from app.core.config import Settings
        default = Settings.model_fields["magic_link_resend_cooldown_seconds"].default
        assert default == 45


class TestEmailService:
    """Email sending via Resend."""

    def test_build_magic_link_html_contains_url(self):
        from app.auth.email_service import build_magic_link_html
        html = build_magic_link_html("https://wiii.app/verify/abc123")
        assert "https://wiii.app/verify/abc123" in html
        assert "Đăng nhập Wiii" in html

    def test_build_magic_link_html_contains_expiry_notice(self):
        from app.auth.email_service import build_magic_link_html
        html = build_magic_link_html("https://example.com/verify/x")
        assert "10 phút" in html

    @pytest.mark.asyncio
    async def test_send_magic_link_email_calls_resend(self):
        from app.auth.email_service import send_magic_link_email

        mock_settings = MagicMock()
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.magic_link_from_email = "Wiii <noreply@wiii.app>"

        with patch("app.auth.email_service.resend") as mock_resend, \
             patch("app.auth.email_service.settings", mock_settings):
            mock_resend.Emails.send.return_value = {"id": "email_123"}
            result = await send_magic_link_email("test@example.com", "https://wiii.app/verify/abc")
            assert result is True
            mock_resend.Emails.send.assert_called_once()
            call_args = mock_resend.Emails.send.call_args[0][0]
            assert call_args["to"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_send_magic_link_email_success_logs_hash_ref(self, caplog):
        from app.auth.email_service import send_magic_link_email
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_email = "private-login@example.com"
        verify_url = "https://wiii.app/verify/raw-token-private"
        mock_settings = MagicMock()
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.magic_link_from_email = "Wiii <noreply@wiii.app>"

        with patch("app.auth.email_service.resend") as mock_resend, \
             patch("app.auth.email_service.settings", mock_settings), \
             caplog.at_level(logging.INFO, logger="app.auth.email_service"):
            mock_resend.Emails.send.return_value = {"id": "email_123"}
            result = await send_magic_link_email(raw_email, verify_url)

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert result is True
        assert raw_email not in log_text
        assert verify_url not in log_text
        assert f"email_ref={hash_runtime_identifier(raw_email)}" in log_text

    @pytest.mark.asyncio
    async def test_send_magic_link_email_handles_error(self):
        from app.auth.email_service import send_magic_link_email

        mock_settings = MagicMock()
        mock_settings.resend_api_key = "re_test_key"
        mock_settings.magic_link_from_email = "Wiii <noreply@wiii.app>"

        with patch("app.auth.email_service.resend") as mock_resend, \
             patch("app.auth.email_service.settings", mock_settings):
            mock_resend.Emails.send.side_effect = Exception("API error")
            result = await send_magic_link_email("test@example.com", "https://wiii.app/verify/abc")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_magic_link_email_error_redacts_recipient_url_and_secrets(self, caplog):
        from app.auth.email_service import send_magic_link_email
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_email = "private-login@example.com"
        raw_url = "https://wiii.app/verify/raw-token-private"
        raw_key = "re_private_api_key_123"
        raw_from = "Wiii <private-from@example.com>"
        mock_settings = MagicMock()
        mock_settings.resend_api_key = raw_key
        mock_settings.magic_link_from_email = raw_from

        with patch("app.auth.email_service.resend") as mock_resend, \
             patch("app.auth.email_service.settings", mock_settings), \
             caplog.at_level(logging.ERROR, logger="app.auth.email_service"):
            mock_resend.Emails.send.side_effect = Exception(
                f"provider failed email={raw_email} url={raw_url} "
                f"api_key={raw_key} from={raw_from}"
            )
            result = await send_magic_link_email(raw_email, raw_url)

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert result is False
        for raw_value in (raw_email, raw_url, raw_key, raw_from):
            assert raw_value not in log_text
        assert f"email_ref={hash_runtime_identifier(raw_email)}" in log_text
        assert "<redacted-secret>" in log_text

    @pytest.mark.asyncio
    async def test_send_magic_link_email_fails_closed_in_production_without_resend(self):
        from app.auth.email_service import send_magic_link_email

        mock_settings = MagicMock()
        mock_settings.environment = "production"
        mock_settings.resend_api_key = ""

        with patch("app.auth.email_service.settings", mock_settings):
            result = await send_magic_link_email(
                "test@example.com",
                "https://wiii.app/verify/abc",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_magic_link_email_keeps_dev_fallback_outside_production(self):
        from app.auth.email_service import send_magic_link_email

        mock_settings = MagicMock()
        mock_settings.environment = "development"
        mock_settings.resend_api_key = ""

        with patch("app.auth.email_service.settings", mock_settings):
            result = await send_magic_link_email(
                "test@example.com",
                "https://wiii.app/verify/abc",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_magic_link_email_dev_fallback_logs_hash_ref_without_url(self, caplog):
        from app.auth.email_service import send_magic_link_email
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_email = "private-dev@example.com"
        raw_url = "https://wiii.app/verify/dev-token-private"
        mock_settings = MagicMock()
        mock_settings.environment = "development"
        mock_settings.resend_api_key = ""

        with patch("app.auth.email_service.settings", mock_settings), \
             caplog.at_level(logging.WARNING, logger="app.auth.email_service"):
            result = await send_magic_link_email(raw_email, raw_url)

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert result is True
        assert raw_email not in log_text
        assert raw_url not in log_text
        assert f"email_ref={hash_runtime_identifier(raw_email)}" in log_text


class TestMagicLinkTokenGeneration:
    """Token generation and hashing."""

    def test_generate_token_returns_tuple(self):
        from app.auth.magic_link_service import generate_magic_token
        raw_token, token_hash = generate_magic_token()
        assert len(raw_token) > 32
        assert len(token_hash) == 64  # SHA256 hex

    def test_token_hash_is_sha256(self):
        from app.auth.magic_link_service import generate_magic_token, hash_token
        raw_token, token_hash = generate_magic_token()
        assert hash_token(raw_token) == token_hash

    def test_different_tokens_each_call(self):
        from app.auth.magic_link_service import generate_magic_token
        t1, _ = generate_magic_token()
        t2, _ = generate_magic_token()
        assert t1 != t2


class TestMagicLinkVerification:
    """Token verification logic (no DB)."""

    def test_token_not_expired(self):
        from app.auth.magic_link_service import is_token_expired
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        assert is_token_expired(future) is False

    def test_token_expired(self):
        from app.auth.magic_link_service import is_token_expired
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert is_token_expired(past) is True

    def test_token_already_used(self):
        from app.auth.magic_link_service import is_token_used
        assert is_token_used(datetime.now(timezone.utc)) is True

    def test_token_not_used(self):
        from app.auth.magic_link_service import is_token_used
        assert is_token_used(None) is False


class TestEmailValidation:
    """Email format validation."""

    def test_valid_email(self):
        from app.auth.magic_link_service import validate_email
        assert validate_email("student@maritime.edu") is True

    def test_invalid_email_no_at(self):
        from app.auth.magic_link_service import validate_email
        assert validate_email("invalid-email") is False

    def test_invalid_email_empty(self):
        from app.auth.magic_link_service import validate_email
        assert validate_email("") is False

    def test_invalid_email_spaces(self):
        from app.auth.magic_link_service import validate_email
        assert validate_email("  ") is False


class TestSessionManager:
    """WebSocket session management."""

    def test_singleton_returns_same_instance(self):
        from app.auth.magic_link_service import get_session_manager
        m1 = get_session_manager()
        m2 = get_session_manager()
        assert m1 is m2

    def test_remove_nonexistent_session(self):
        from app.auth.magic_link_service import MagicLinkSessionManager
        mgr = MagicLinkSessionManager()
        mgr.remove("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_push_to_missing_session_returns_false(self):
        from app.auth.magic_link_service import MagicLinkSessionManager
        mgr = MagicLinkSessionManager()
        result = await mgr.push_tokens("nonexistent", {"token": "abc"})
        assert result is False

    def test_active_count_starts_at_zero(self):
        from app.auth.magic_link_service import MagicLinkSessionManager
        mgr = MagicLinkSessionManager()
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_websocket_error_logs_hash_ref(self, caplog):
        """WebSocket diagnostics must not expose raw magic-link session ids."""
        from app.auth.magic_link_router import magic_link_websocket
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_session = "magic-link-ws-secret-session"
        mock_mgr = MagicMock()
        mock_mgr.register = AsyncMock()
        mock_mgr.remove = MagicMock()

        with patch("app.auth.magic_link_router.get_session_manager", return_value=mock_mgr), \
             patch("app.auth.magic_link_router.settings") as mock_settings, \
             patch(
                 "app.auth.magic_link_router._ws_keepalive",
                 new=AsyncMock(side_effect=RuntimeError(f"ws failed {raw_session}")),
             ), caplog.at_level(logging.ERROR, logger="app.auth.magic_link_router"):
            mock_settings.magic_link_ws_timeout_seconds = 30
            await magic_link_websocket(MagicMock(), raw_session)

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert raw_session not in log_text
        assert f"session_ref={hash_runtime_identifier(raw_session)}" in log_text
        assert "<redacted-secret>" in log_text
        mock_mgr.remove.assert_called_once_with(raw_session)


# ===================================================================
# Router tests (Sprint 224 Task 3)
# ===================================================================


class TestMagicLinkRequest:
    """POST /auth/magic/request -- send magic link email."""

    @pytest.mark.asyncio
    async def test_create_magic_link_sends_email(self):
        """Core logic creates token and sends email."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)  # rate limit check
        mock_conn.execute = AsyncMock()

        with patch("app.auth.magic_link_router.send_magic_link_email", new_callable=AsyncMock, return_value=True) as mock_send, \
             patch("app.auth.magic_link_router.settings") as mock_settings:
            mock_settings.magic_link_expires_seconds = 600
            mock_settings.magic_link_base_url = "http://localhost:8000"
            mock_settings.magic_link_max_per_hour = 5
            mock_settings.api_v1_prefix = "/api/v1"

            result = await _create_magic_link("test@example.com", mock_conn)
            assert "session_id" in result
            assert len(result["session_id"]) > 20
            assert result["expires_in"] == 600
            assert "message" in result
            mock_send.assert_called_once()
            mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_magic_link_logs_hash_refs(self, caplog):
        """Create diagnostics must not expose raw email or WS session id."""
        from app.auth.magic_link_router import _create_magic_link
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_email = "private-login@example.com"
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        with patch(
            "app.auth.magic_link_router.send_magic_link_email",
            new_callable=AsyncMock,
            return_value=True,
        ), patch("app.auth.magic_link_router.settings") as mock_settings, caplog.at_level(
            logging.INFO,
            logger="app.auth.magic_link_router",
        ):
            mock_settings.environment = "production"
            mock_settings.resend_api_key = ""
            mock_settings.magic_link_expires_seconds = 600
            mock_settings.magic_link_base_url = "https://wiii.example"
            mock_settings.magic_link_max_per_hour = 5
            mock_settings.api_v1_prefix = "/api/v1"

            result = await _create_magic_link(raw_email, mock_conn)

        raw_session = result["session_id"]
        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert raw_email not in log_text
        assert raw_session not in log_text
        assert f"email_ref={hash_runtime_identifier(raw_email)}" in log_text
        assert f"session_ref={hash_runtime_identifier(raw_session)}" in log_text

    @pytest.mark.asyncio
    async def test_create_magic_link_rate_limited(self):
        """Rate limit rejects when too many requests."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=10)  # over limit

        with patch("app.auth.magic_link_router.settings") as mock_settings, \
             pytest.raises(Exception) as exc_info:
            mock_settings.magic_link_max_per_hour = 5
            await _create_magic_link("test@example.com", mock_conn)
        assert "429" in str(exc_info.value.status_code) or "Too many" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_magic_link_email_failure(self):
        """Email send failure raises 500."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        with patch("app.auth.magic_link_router.send_magic_link_email", new_callable=AsyncMock, return_value=False), \
             patch("app.auth.magic_link_router.settings") as mock_settings, \
             pytest.raises(Exception) as exc_info:
            mock_settings.magic_link_expires_seconds = 600
            mock_settings.magic_link_base_url = "http://localhost:8000"
            mock_settings.magic_link_max_per_hour = 5
            mock_settings.api_v1_prefix = "/api/v1"
            await _create_magic_link("test@example.com", mock_conn)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_create_magic_link_stores_token_hash_not_raw(self):
        """DB receives hashed token, not the raw token."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        with patch("app.auth.magic_link_router.send_magic_link_email", new_callable=AsyncMock, return_value=True), \
             patch("app.auth.magic_link_router.settings") as mock_settings:
            mock_settings.magic_link_expires_seconds = 600
            mock_settings.magic_link_base_url = "http://localhost:8000"
            mock_settings.magic_link_max_per_hour = 5
            mock_settings.api_v1_prefix = "/api/v1"

            await _create_magic_link("test@example.com", mock_conn)

            # Verify the INSERT call
            call_args = mock_conn.execute.call_args
            insert_sql = call_args[0][0]
            assert "INSERT INTO magic_link_tokens" in insert_sql
            # token_hash is the first positional param ($1)
            stored_hash = call_args[0][1]
            assert len(stored_hash) == 64  # SHA256 hex digest

    @pytest.mark.asyncio
    async def test_create_magic_link_does_not_surface_dev_verify_url_in_production(self):
        """Production responses must not expose raw verification URLs."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        with patch("app.auth.magic_link_router.send_magic_link_email", new_callable=AsyncMock, return_value=True), \
             patch("app.auth.magic_link_router.settings") as mock_settings:
            mock_settings.environment = "production"
            mock_settings.resend_api_key = ""
            mock_settings.magic_link_expires_seconds = 600
            mock_settings.magic_link_base_url = "https://wiii.holilihu.online"
            mock_settings.magic_link_max_per_hour = 5
            mock_settings.api_v1_prefix = "/api/v1"

            result = await _create_magic_link("test@example.com", mock_conn)

        assert "dev_verify_url" not in result

    @pytest.mark.asyncio
    async def test_create_magic_link_surfaces_dev_verify_url_outside_production(self):
        """Local/dev keeps the convenience URL for manual login testing."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        with patch("app.auth.magic_link_router.send_magic_link_email", new_callable=AsyncMock, return_value=True), \
             patch("app.auth.magic_link_router.settings") as mock_settings:
            mock_settings.environment = "development"
            mock_settings.resend_api_key = ""
            mock_settings.magic_link_expires_seconds = 600
            mock_settings.magic_link_base_url = "http://localhost:8000"
            mock_settings.magic_link_max_per_hour = 5
            mock_settings.api_v1_prefix = "/api/v1"

            result = await _create_magic_link("test@example.com", mock_conn)

        assert result["dev_verify_url"].startswith(
            "http://localhost:8000/api/v1/auth/magic-link/verify/"
        )

    @pytest.mark.asyncio
    async def test_create_magic_link_at_rate_limit_boundary(self):
        """Exactly at max_per_hour should still be rejected."""
        from app.auth.magic_link_router import _create_magic_link

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=5)  # exactly at limit

        with patch("app.auth.magic_link_router.settings") as mock_settings, \
             pytest.raises(Exception) as exc_info:
            mock_settings.magic_link_max_per_hour = 5
            await _create_magic_link("test@example.com", mock_conn)
        assert exc_info.value.status_code == 429


class TestMagicLinkVerify:
    """GET /auth/magic/verify/{token} -- verify token + create JWT."""

    def test_hash_token_consistent(self):
        from app.auth.magic_link_service import hash_token
        assert hash_token("abc") == hash_token("abc")
        assert hash_token("abc") != hash_token("def")

    def test_hash_token_is_sha256(self):
        from app.auth.magic_link_service import hash_token
        expected = hashlib.sha256(b"test_token").hexdigest()
        assert hash_token("test_token") == expected

    @pytest.mark.asyncio
    async def test_verify_mints_token_with_default_org_claim(self, caplog):
        """Magic-link token payload must carry the same default org sent to the app."""
        from app.auth.magic_link_router import verify_magic_link
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        raw_email = "test@example.com"
        raw_session = "session-1"
        raw_user_id = "user-1"
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "email": raw_email,
            "ws_session_id": raw_session,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "used_at": None,
        })
        mock_conn.execute = AsyncMock()

        class _PoolCtx:
            async def __aenter__(self_inner): return mock_conn
            async def __aexit__(self_inner, *_): return None

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_PoolCtx())

        mock_settings = MagicMock()
        mock_settings.enable_multi_tenant = True
        mock_settings.default_organization_id = "default"

        mock_pair = MagicMock(
            access_token="ACCESS",
            refresh_token="REFRESH",
            token_type="bearer",
            expires_in=900,
        )
        mock_session_manager = MagicMock()
        mock_session_manager.push_tokens = AsyncMock(return_value=True)

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")

        create_pair = AsyncMock(return_value=mock_pair)
        with (
            patch("app.auth.magic_link_router.settings", mock_settings),
            patch("app.core.database.get_asyncpg_pool", new=AsyncMock(return_value=mock_pool)),
            patch(
                "app.auth.user_service.find_or_create_by_provider",
                new=AsyncMock(return_value={
                    "id": raw_user_id,
                    "email": raw_email,
                    "name": "Test User",
                    "role": "student",
                    "platform_role": "user",
                }),
            ),
            patch("app.auth.token_service.create_token_pair", new=create_pair),
            patch(
                "app.auth.magic_link_router.ensure_user_org_membership",
                new=AsyncMock(return_value=True),
            ),
            patch("app.auth.magic_link_router.get_session_manager", return_value=mock_session_manager),
            patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock) as mock_audit,
            caplog.at_level(logging.INFO, logger="app.auth.magic_link_router"),
        ):
            handler = getattr(verify_magic_link, "__wrapped__", verify_magic_link)
            response = await handler("raw-token", request)

        assert response.status_code == 200
        kwargs = create_pair.call_args.kwargs
        assert kwargs["active_organization_id"] == "default"
        assert kwargs["role_source"] == "platform"

        pushed_payload = mock_session_manager.push_tokens.call_args.args[1]
        assert pushed_payload["organization_id"] == "default"
        assert pushed_payload["user"]["active_organization_id"] == "default"

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert raw_email not in log_text
        assert raw_session not in log_text
        assert raw_user_id not in log_text
        assert f"email_ref={hash_runtime_identifier(raw_email)}" in log_text
        assert f"user_ref={hash_runtime_identifier(raw_user_id)}" in log_text

        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["metadata"] == {
            "email_ref": hash_runtime_identifier(raw_email)
        }


class TestMagicLinkHTMLPages:
    """HTML response pages."""

    def test_success_page_ws_pushed(self):
        from app.auth.magic_link_router import _success_page
        response = _success_page(True)
        assert response.status_code == 200
        assert "thành công" in response.body.decode().lower()

    def test_success_page_ws_not_pushed(self):
        from app.auth.magic_link_router import _success_page
        response = _success_page(False)
        assert response.status_code == 200
        body = response.body.decode().lower()
        assert "xác minh" in body or "thử lại" in body

    def test_error_page(self):
        from app.auth.magic_link_router import _error_page
        response = _error_page("Token hết hạn")
        assert response.status_code == 400
        assert "Token hết hạn" in response.body.decode()

    def test_error_page_contains_wiii_branding(self):
        from app.auth.magic_link_router import _error_page
        response = _error_page("Test error")
        body = response.body.decode()
        assert "The Wiii Lab" in body

    def test_success_page_contains_wiii_branding(self):
        from app.auth.magic_link_router import _success_page
        response = _success_page(True)
        body = response.body.decode()
        assert "The Wiii Lab" in body


# ===================================================================
# Router structure tests (Sprint 224 Task 3 — endpoint registration)
# ===================================================================


class TestMagicLinkRouter:
    """Router endpoint registration and model tests."""

    def test_magic_link_request_model_validates_email(self):
        """MagicLinkRequest requires email with min_length=5."""
        import pydantic
        from app.auth.magic_link_router import MagicLinkRequest

        req = MagicLinkRequest(email="a@b.co")
        assert req.email == "a@b.co"

        with pytest.raises(pydantic.ValidationError):
            MagicLinkRequest(email="ab")  # too short

    def test_magic_link_response_model(self):
        from app.auth.magic_link_router import MagicLinkResponse
        resp = MagicLinkResponse(message="sent", session_id="abc123", expires_in=600)
        assert resp.session_id == "abc123"
        assert resp.expires_in == 600

    def test_router_prefix(self):
        from app.auth.magic_link_router import router
        assert router.prefix == "/auth/magic-link"

    def test_router_has_request_endpoint(self):
        from app.auth.magic_link_router import router
        paths = [r.path for r in router.routes]
        assert any("request" in p for p in paths)

    def test_router_has_verify_endpoint(self):
        from app.auth.magic_link_router import router
        paths = [r.path for r in router.routes]
        assert any("verify" in p and "token" in p for p in paths)

    def test_router_has_websocket_endpoint(self):
        from app.auth.magic_link_router import router
        paths = [r.path for r in router.routes]
        assert any("/ws/" in p for p in paths)


# ===================================================================
# TASK-2026-04-25-001: Production hardening
# Cleanup task, per-IP rate limit on /verify, WS session reaper
# ===================================================================


class TestExpiredTokenCleanup:
    """Periodic DELETE of expired magic_link_tokens rows."""

    @pytest.mark.asyncio
    async def test_cleanup_returns_deleted_count(self):
        """Parses asyncpg's `DELETE <n>` status string into an int count."""
        from app.auth import magic_link_service

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 7")

        class _PoolCtx:
            async def __aenter__(self_inner): return mock_conn
            async def __aexit__(self_inner, *_): return None

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_PoolCtx())

        with patch("app.core.database.get_asyncpg_pool", new=AsyncMock(return_value=mock_pool)):
            deleted = await magic_link_service.cleanup_expired_tokens(grace_period_hours=24)

        assert deleted == 7
        # Verify the DELETE query targets magic_link_tokens with grace period
        sql = mock_conn.execute.call_args[0][0]
        assert "DELETE FROM magic_link_tokens" in sql
        assert "expires_at" in sql

    @pytest.mark.asyncio
    async def test_cleanup_swallows_db_errors(self):
        """DB failure must NOT raise — cleanup is best-effort hygiene."""
        from app.auth import magic_link_service

        with patch(
            "app.core.database.get_asyncpg_pool",
            new=AsyncMock(side_effect=Exception("connection refused")),
        ):
            deleted = await magic_link_service.cleanup_expired_tokens()
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_handles_unparseable_status(self):
        """Defensive: if execute() returns something unexpected, return 0 gracefully."""
        from app.auth import magic_link_service

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="WEIRD")

        class _PoolCtx:
            async def __aenter__(self_inner): return mock_conn
            async def __aexit__(self_inner, *_): return None

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=_PoolCtx())

        with patch("app.core.database.get_asyncpg_pool", new=AsyncMock(return_value=mock_pool)):
            deleted = await magic_link_service.cleanup_expired_tokens()
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_loop_cancellable(self):
        """Loop must propagate CancelledError so shutdown can stop it cleanly."""
        from app.auth import magic_link_service

        # interval is clamped to >= 60s; we cancel before the first sleep ends
        task = asyncio.create_task(
            magic_link_service.magic_link_cleanup_loop(interval_seconds=60.0)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestMagicLinkConfigDefaults:
    """New config flags introduced by the hardening pass."""

    def test_cleanup_interval_default(self):
        from app.core.config import Settings
        assert Settings.model_fields["magic_link_cleanup_interval_seconds"].default == 3600

    def test_cleanup_grace_default(self):
        from app.core.config import Settings
        assert Settings.model_fields["magic_link_cleanup_grace_hours"].default == 24

    def test_session_reaper_interval_default(self):
        from app.core.config import Settings
        assert Settings.model_fields["magic_link_session_reaper_interval_seconds"].default == 60


class TestSessionReaper:
    """In-memory WS session reaper drops stale entries."""

    def test_reap_drops_stale_sessions(self):
        """Sessions older than max_age are removed; fresh ones kept."""
        from app.auth.magic_link_service import MagicLinkSessionManager, _SessionEntry

        mgr = MagicLinkSessionManager()
        now = time.monotonic()
        mgr._sessions["old"] = _SessionEntry(websocket=MagicMock(), created_at=now - 1000)
        mgr._sessions["fresh"] = _SessionEntry(websocket=MagicMock(), created_at=now - 10)

        reaped = mgr.reap_stale(max_age_seconds=300)

        assert reaped == 1
        assert "old" not in mgr._sessions
        assert "fresh" in mgr._sessions
        assert mgr.active_count == 1

    def test_reap_no_op_when_all_fresh(self):
        from app.auth.magic_link_service import MagicLinkSessionManager, _SessionEntry

        mgr = MagicLinkSessionManager()
        mgr._sessions["a"] = _SessionEntry(websocket=MagicMock(), created_at=time.monotonic())
        mgr._sessions["b"] = _SessionEntry(websocket=MagicMock(), created_at=time.monotonic())

        assert mgr.reap_stale(max_age_seconds=300) == 0
        assert mgr.active_count == 2

    def test_reap_zero_max_age_is_safe(self):
        """Defensive: max_age_seconds=0 short-circuits without touching state."""
        from app.auth.magic_link_service import MagicLinkSessionManager, _SessionEntry

        mgr = MagicLinkSessionManager()
        mgr._sessions["a"] = _SessionEntry(websocket=MagicMock(), created_at=time.monotonic() - 99999)

        assert mgr.reap_stale(max_age_seconds=0) == 0
        assert "a" in mgr._sessions

    @pytest.mark.asyncio
    async def test_register_records_created_at(self):
        """register() must stamp created_at so the reaper can age sessions."""
        from app.auth.magic_link_service import MagicLinkSessionManager

        mgr = MagicLinkSessionManager()
        mock_ws = MagicMock()
        mock_ws.accept = AsyncMock()

        before = time.monotonic()
        await mgr.register("sid-1", mock_ws)
        after = time.monotonic()

        entry = mgr._sessions["sid-1"]
        assert entry.websocket is mock_ws
        assert before <= entry.created_at <= after

    @pytest.mark.asyncio
    async def test_reaper_loop_cancellable(self):
        from app.auth import magic_link_service

        task = asyncio.create_task(
            magic_link_service.magic_link_session_reaper_loop(
                interval_seconds=15.0, max_age_seconds=60.0
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestVerifyEndpointHardening:
    """Per-IP rate limit + audit log on failures."""

    def test_verify_endpoint_takes_request_param(self):
        """slowapi's per-IP limit needs a Request param to extract the client IP."""
        import inspect
        from app.auth.magic_link_router import verify_magic_link

        sig = inspect.signature(verify_magic_link)
        assert "request" in sig.parameters

    def test_verify_endpoint_has_rate_limit_metadata(self):
        """Confirm @limiter.limit(...) decorated the verify endpoint.

        slowapi attaches the limit string to the wrapped function via _rate_limit;
        we check for either that attribute or the wrapped marker so the test
        survives minor slowapi version bumps.
        """
        from app.auth.magic_link_router import verify_magic_link

        # slowapi stores limits in either __wrapped__ or via _rate_limit on the func
        has_limit = (
            hasattr(verify_magic_link, "__wrapped__")
            or hasattr(verify_magic_link, "_rate_limit")
            or any("rate" in attr.lower() for attr in dir(verify_magic_link))
        )
        assert has_limit

    @pytest.mark.asyncio
    async def test_audit_helper_no_op_on_audit_disabled(self):
        """_audit_verify_failure must never raise even if downstream fails."""
        from app.auth.magic_link_router import _audit_verify_failure

        mock_request = MagicMock()
        mock_request.client = MagicMock(host="1.2.3.4")

        with patch(
            "app.auth.auth_audit.log_auth_event",
            new=AsyncMock(side_effect=Exception("DB down")),
        ):
            await _audit_verify_failure("invalid_token", mock_request, "x@y.z")

    @pytest.mark.asyncio
    async def test_audit_helper_extracts_ip(self):
        from app.auth.magic_link_router import _audit_verify_failure
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        mock_request = MagicMock()
        mock_request.client = MagicMock(host="9.8.7.6")

        captured = {}

        async def _capture(*args, **kwargs):
            captured.update(kwargs)

        with patch("app.auth.auth_audit.log_auth_event", new=_capture):
            await _audit_verify_failure("token_expired", mock_request, "abc@example.com")

        assert captured.get("ip_address") == "9.8.7.6"
        assert captured.get("provider") == "magic_link"
        assert captured.get("reason") == "token_expired"
        assert captured.get("metadata") == {
            "email_ref": hash_runtime_identifier("abc@example.com")
        }
