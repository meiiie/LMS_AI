"""
Sprint 193: "Cổng Chính" — Web OAuth + Logout UX

Tests for:
1. redirect_uri whitelist validation
2. google_login with redirect_uri param
3. google_callback with web_redirect_uri → hash redirect
4. config flag: oauth_allowed_redirect_origins
"""
import json
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock authlib (may not be installed in test env)
# ---------------------------------------------------------------------------
_authlib_mock = MagicMock()
sys.modules.setdefault("authlib", _authlib_mock)
sys.modules.setdefault("authlib.integrations", _authlib_mock)
sys.modules.setdefault("authlib.integrations.starlette_client", _authlib_mock)

# Now safe to import
import app.auth.google_oauth as _oauth_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Unit tests for _validate_redirect_origin
# ---------------------------------------------------------------------------


class TestValidateRedirectOrigin:
    """Test redirect_uri whitelist validation."""

    def test_valid_origin_in_whitelist(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = "http://localhost:1420,http://localhost:1421"
            assert _oauth_mod._validate_redirect_origin("http://localhost:1420") is True
            assert _oauth_mod._validate_redirect_origin("http://localhost:1420/") is True

    def test_valid_origin_with_path(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = "http://localhost:1420"
            assert _oauth_mod._validate_redirect_origin("http://localhost:1420/some/path") is True

    def test_invalid_origin_not_in_whitelist(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = "http://localhost:1420"
            assert _oauth_mod._validate_redirect_origin("http://evil.com") is False
            assert _oauth_mod._validate_redirect_origin("http://localhost:9999") is False

    def test_empty_whitelist_rejects_all(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = ""
            assert _oauth_mod._validate_redirect_origin("http://localhost:1420") is False

    def test_https_origin(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = "https://app.wiii.vn,http://localhost:1420"
            assert _oauth_mod._validate_redirect_origin("https://app.wiii.vn") is True
            assert _oauth_mod._validate_redirect_origin("https://app.wiii.vn/callback") is True
            assert _oauth_mod._validate_redirect_origin("http://app.wiii.vn") is False

    def test_whitelist_with_spaces(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = " http://localhost:1420 , http://localhost:1421 "
            assert _oauth_mod._validate_redirect_origin("http://localhost:1420") is True
            assert _oauth_mod._validate_redirect_origin("http://localhost:1421") is True

    def test_trailing_slash_normalization(self):
        with patch.object(_oauth_mod, "settings") as ms:
            ms.oauth_allowed_redirect_origins = "http://localhost:1420/"
            assert _oauth_mod._validate_redirect_origin("http://localhost:1420") is True


# ---------------------------------------------------------------------------
# google_login endpoint tests
# ---------------------------------------------------------------------------


class TestGoogleLoginRedirectUri:
    """Test /auth/google/login with redirect_uri param."""

    @pytest.mark.asyncio
    async def test_login_with_valid_redirect_uri(self):
        req = MagicMock()
        req.session = {}
        req.base_url = "http://localhost:8000/"

        with patch.object(_oauth_mod, "settings") as ms, \
             patch.object(_oauth_mod, "oauth") as mo:
            ms.enable_google_oauth = True
            ms.oauth_allowed_redirect_origins = "http://localhost:1420"
            ms.oauth_redirect_base_url = None
            mo.google.authorize_redirect = AsyncMock(return_value="redirect")

            await _oauth_mod.google_login(request=req, port=None, redirect_uri="http://localhost:1420")

            assert req.session.get("web_redirect_uri") == "http://localhost:1420"

    @pytest.mark.asyncio
    async def test_login_with_invalid_redirect_uri_rejected(self):
        from fastapi import HTTPException
        req = MagicMock()
        req.session = {}

        with patch.object(_oauth_mod, "settings") as ms:
            ms.enable_google_oauth = True
            ms.oauth_allowed_redirect_origins = "http://localhost:1420"

            with pytest.raises(HTTPException) as exc_info:
                await _oauth_mod.google_login(request=req, port=None, redirect_uri="http://evil.com")
            assert exc_info.value.status_code == 400
            assert "not in allowed list" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_without_redirect_uri(self):
        req = MagicMock()
        req.session = {}
        req.base_url = "http://localhost:8000/"

        with patch.object(_oauth_mod, "settings") as ms, \
             patch.object(_oauth_mod, "oauth") as mo:
            ms.enable_google_oauth = True
            ms.oauth_redirect_base_url = None
            mo.google.authorize_redirect = AsyncMock(return_value="redirect")

            await _oauth_mod.google_login(request=req, port=None, redirect_uri=None)
            assert "web_redirect_uri" not in req.session

    @pytest.mark.asyncio
    async def test_login_oauth_disabled_404(self):
        from fastapi import HTTPException
        req = MagicMock()

        with patch.object(_oauth_mod, "settings") as ms:
            ms.enable_google_oauth = False

            with pytest.raises(HTTPException) as exc_info:
                await _oauth_mod.google_login(request=req, port=None, redirect_uri="http://localhost:1420")
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_login_stores_both_port_and_redirect_uri(self):
        req = MagicMock()
        req.session = {}
        req.base_url = "http://localhost:8000/"

        with patch.object(_oauth_mod, "settings") as ms, \
             patch.object(_oauth_mod, "oauth") as mo:
            ms.enable_google_oauth = True
            ms.oauth_allowed_redirect_origins = "http://localhost:1420"
            ms.oauth_redirect_base_url = None
            mo.google.authorize_redirect = AsyncMock(return_value="redirect")

            await _oauth_mod.google_login(request=req, port=8765, redirect_uri="http://localhost:1420")

            assert req.session["web_redirect_uri"] == "http://localhost:1420"
            assert req.session["desktop_port"] == 8765


# ---------------------------------------------------------------------------
# google_callback endpoint tests
# ---------------------------------------------------------------------------


def _make_callback_mocks(session_data: dict):
    """Helper to create mock request and auth deps for callback tests."""
    req = MagicMock()
    req.session = dict(session_data)  # real dict for pop()
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = MagicMock()
    req.headers.get = MagicMock(return_value="test-agent")

    tp = MagicMock()
    tp.access_token = "test-access-token"
    tp.refresh_token = "test-refresh-token"
    tp.expires_in = 900

    user = {
        "id": "user-123",
        "email": "test@example.com",
        "name": "Test User",
        "avatar_url": "https://example.com/avatar.jpg",
        "role": "student",
    }

    return req, tp, user


def _patch_callback(mock_user, mock_token_pair):
    """Context manager that patches settings, oauth, find_or_create, create_token_pair."""
    settings_patch = patch.object(_oauth_mod, "settings")
    oauth_patch = patch.object(_oauth_mod, "oauth")
    find_patch = patch.object(_oauth_mod, "find_or_create_by_google", new_callable=AsyncMock)
    create_patch = patch.object(_oauth_mod, "create_token_pair", new_callable=AsyncMock)

    class _Ctx:
        def __enter__(self_ctx):
            self_ctx.ms = settings_patch.__enter__()
            self_ctx.mo = oauth_patch.__enter__()
            self_ctx.mf = find_patch.__enter__()
            self_ctx.mc = create_patch.__enter__()
            self_ctx.ms.enable_google_oauth = True
            self_ctx.ms.enable_jti_denylist = False
            self_ctx.ms.enable_auth_audit = False
            self_ctx.ms.enable_multi_tenant = False
            self_ctx.mo.google.authorize_access_token = AsyncMock(return_value={
                "userinfo": {
                    "sub": "google-sub",
                    "email": mock_user.get("email", ""),
                    "name": mock_user.get("name", ""),
                    "picture": mock_user.get("avatar_url", ""),
                    "email_verified": True,
                },
            })
            self_ctx.mf.return_value = mock_user
            self_ctx.mc.return_value = mock_token_pair
            return self_ctx

        def __exit__(self_ctx, *args):
            create_patch.__exit__(*args)
            find_patch.__exit__(*args)
            oauth_patch.__exit__(*args)
            settings_patch.__exit__(*args)

    return _Ctx()


class TestGoogleCallbackWebRedirect:
    """Test /auth/google/callback with web_redirect_uri."""

    @pytest.mark.asyncio
    async def test_callback_token_exchange_failure_redacts_log_and_audit_reason(self, caplog):
        """OAuth failure diagnostics should not expose raw auth code or client secret."""
        from fastapi import HTTPException

        raw_code = "oauth-code-private-123"
        raw_secret = "google-client-secret-private-456"
        req = MagicMock()
        req.session = {}
        req.client = MagicMock(host="127.0.0.1")
        req.headers = MagicMock()
        req.headers.get = MagicMock(return_value="test-agent")
        req.query_params = {"code": raw_code}
        audit_log = AsyncMock()

        with patch.object(_oauth_mod, "settings") as ms, \
             patch.object(_oauth_mod, "oauth") as mo, \
             patch("app.auth.auth_audit.log_auth_event", audit_log):
            ms.enable_google_oauth = True
            ms.google_oauth_client_secret = raw_secret
            mo.google.authorize_access_token = AsyncMock(
                side_effect=RuntimeError(
                    f"provider rejected code={raw_code} client_secret={raw_secret}"
                )
            )

            with caplog.at_level(logging.ERROR, logger="app.auth.google_oauth"):
                with pytest.raises(HTTPException) as exc_info:
                    await _oauth_mod.google_callback(req)

        assert exc_info.value.status_code == 400
        assert raw_code not in caplog.text
        assert raw_secret not in caplog.text
        assert "OAuth token exchange failed" in caplog.text
        audit_log.assert_awaited_once()
        reason = audit_log.await_args.kwargs["reason"]
        assert raw_code not in reason
        assert raw_secret not in reason
        assert reason == "google_oauth_exchange_failed"

    @pytest.mark.asyncio
    async def test_callback_web_redirect_returns_html_with_hash(self):
        req, tp, user = _make_callback_mocks({"web_redirect_uri": "http://localhost:1420"})

        with _patch_callback(user, tp):
            response = await _oauth_mod.google_callback(req)

        assert response.status_code == 200
        body = response.body.decode("utf-8")
        assert "Đăng nhập thành công" in body
        assert "http://localhost:1420#" in body
        assert "access_token=test-access-token" in body
        assert "refresh_token=test-refresh-token" in body
        assert "user_id=user-123" in body

    @pytest.mark.asyncio
    async def test_callback_desktop_port_takes_priority(self):
        req, tp, user = _make_callback_mocks(
            {"desktop_port": 8765, "web_redirect_uri": "http://localhost:1420"}
        )

        with _patch_callback(user, tp):
            response = await _oauth_mod.google_callback(req)

        body = response.body.decode("utf-8")
        assert "http://127.0.0.1:8765#" in body
        # web_redirect_uri should NOT appear in redirect target
        assert "localhost:1420" not in body

    @pytest.mark.asyncio
    async def test_callback_without_redirect_returns_json(self):
        req, tp, user = _make_callback_mocks({})

        with _patch_callback(user, tp):
            response = await _oauth_mod.google_callback(req)

        body = json.loads(response.body.decode("utf-8"))
        assert body["access_token"] == "test-access-token"
        assert body["user"]["id"] == "user-123"

    @pytest.mark.asyncio
    async def test_callback_web_redirect_pops_session(self):
        session = {"web_redirect_uri": "http://localhost:1420"}
        req, tp, user = _make_callback_mocks(session)
        req.session = session  # share same dict

        with _patch_callback(user, tp):
            await _oauth_mod.google_callback(req)

        assert "web_redirect_uri" not in session

    @pytest.mark.asyncio
    async def test_callback_web_redirect_includes_role(self):
        teacher = {
            "id": "teacher-1",
            "email": "teacher@school.com",
            "name": "Teacher",
            "avatar_url": "",
            "role": "teacher",
        }
        req, tp, _ = _make_callback_mocks({"web_redirect_uri": "http://localhost:1420"})

        with _patch_callback(teacher, tp):
            response = await _oauth_mod.google_callback(req)

        body = response.body.decode("utf-8")
        assert "role=teacher" in body

    @pytest.mark.asyncio
    async def test_callback_web_redirect_includes_expires_in(self):
        req, tp, user = _make_callback_mocks({"web_redirect_uri": "http://localhost:1420"})

        with _patch_callback(user, tp):
            response = await _oauth_mod.google_callback(req)

        body = response.body.decode("utf-8")
        assert "expires_in=900" in body


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfigOAuthAllowedRedirectOrigins:
    """Test oauth_allowed_redirect_origins config field."""

    def test_default_value(self):
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test")
        assert "localhost:1420" in s.oauth_allowed_redirect_origins
        assert "localhost:1421" in s.oauth_allowed_redirect_origins

    def test_custom_value(self):
        from app.core.config import Settings
        s = Settings(
            google_api_key="test",
            api_key="test",
            oauth_allowed_redirect_origins="https://app.wiii.vn",
        )
        assert s.oauth_allowed_redirect_origins == "https://app.wiii.vn"


# ---------------------------------------------------------------------------
# Sprint 193b: Auto-assign org + organization_id in response
# ---------------------------------------------------------------------------


class TestGoogleCallbackAutoAssignOrg:
    """Test auto-assign user to default org on OAuth callback."""

    @pytest.mark.asyncio
    async def test_callback_auto_assigns_user_to_default_org(self):
        """When multi_tenant=True and default_organization_id set, user is assigned."""
        req, tp, user = _make_callback_mocks({})
        mock_conn = AsyncMock()

        with _patch_callback(user, tp) as ctx:
            ctx.ms.enable_multi_tenant = True
            ctx.ms.default_organization_id = "default"

            mock_pool = MagicMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_pool_fn = AsyncMock(return_value=mock_pool)

            with patch("app.core.database.get_asyncpg_pool", mock_pool_fn):
                await _oauth_mod.google_callback(req)

            # First execute call should be the org assignment (auth audit may also call execute)
            assert mock_conn.execute.call_count >= 1
            first_call = mock_conn.execute.call_args_list[0]
            assert "INSERT INTO user_organizations" in first_call[0][0]
            assert first_call[0][1] == "user-123"
            assert first_call[0][2] == "default"

    @pytest.mark.asyncio
    async def test_callback_mints_token_with_default_org_claim(self):
        """Frontend org context must match the org embedded in minted tokens."""
        req, tp, user = _make_callback_mocks({})

        with _patch_callback(user, tp) as ctx:
            ctx.ms.enable_multi_tenant = True
            ctx.ms.default_organization_id = "default"

            with patch(
                "app.auth.google_oauth.ensure_user_org_membership",
                new=AsyncMock(return_value=True),
            ):
                await _oauth_mod.google_callback(req)

            kwargs = ctx.mc.call_args.kwargs
            assert kwargs["active_organization_id"] == "default"
            assert kwargs["role_source"] == "platform"

    @pytest.mark.asyncio
    async def test_callback_skips_auto_assign_when_multi_tenant_disabled(self):
        """When multi_tenant=False, no org assignment happens."""
        req, tp, user = _make_callback_mocks({})

        with _patch_callback(user, tp) as ctx:
            ctx.ms.enable_multi_tenant = False
            ctx.ms.default_organization_id = "default"

            response = await _oauth_mod.google_callback(req)

        # Should still succeed — just no org assignment
        body = json.loads(response.body.decode("utf-8"))
        assert body["access_token"] == "test-access-token"
        # organization_id should be empty when multi_tenant=False
        assert body.get("organization_id", "") == ""

    @pytest.mark.asyncio
    async def test_callback_includes_organization_id_in_hash_params(self):
        """Web redirect includes organization_id in hash fragment."""
        req, tp, user = _make_callback_mocks({"web_redirect_uri": "http://localhost:1420"})

        with _patch_callback(user, tp) as ctx:
            ctx.ms.enable_multi_tenant = True
            ctx.ms.default_organization_id = "default"

            mock_pool = MagicMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("app.core.database.get_asyncpg_pool", AsyncMock(return_value=mock_pool)):
                response = await _oauth_mod.google_callback(req)

        body = response.body.decode("utf-8")
        assert "organization_id=default" in body

    @pytest.mark.asyncio
    async def test_callback_includes_organization_id_in_json_fallback(self):
        """JSON fallback includes organization_id field."""
        req, tp, user = _make_callback_mocks({})

        with _patch_callback(user, tp) as ctx:
            ctx.ms.enable_multi_tenant = True
            ctx.ms.default_organization_id = "default"

            mock_pool = MagicMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("app.core.database.get_asyncpg_pool", AsyncMock(return_value=mock_pool)):
                response = await _oauth_mod.google_callback(req)

        body = json.loads(response.body.decode("utf-8"))
        assert body["organization_id"] == "default"
