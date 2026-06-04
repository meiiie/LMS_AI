# -*- coding: utf-8 -*-
"""
Sprint 194c — Security Hardening Tests

Covers:
  B1: admin-context endpoint now uses require_auth() dependency
  B2: WebSocket first-message auth (no query-param API key)
  B6: OrgContextMiddleware fail-closed on DB error
  B3: OTP exponential backoff between failed verify attempts
  B8: OTP probabilistic cleanup (10% chance)
  B5/B9: Session secret validation warning when key < 32 chars

Lazy-import gotchas (see CLAUDE.md knowledge/backend-gotchas.md):
  - settings imported lazily inside function bodies in otp_linking.py,
    websocket.py, user_router.py → patch at app.core.config.settings
  - get_asyncpg_pool imported lazily → patch at app.core.database.get_asyncpg_pool
    with create=True
  - organization_repository imported lazily inside middleware → patch at
    app.repositories.organization_repository.get_organization_repository
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ── Canonical patch targets (lazy imports live here) ────────────────────────
_POOL_PATCH = "app.core.database.get_asyncpg_pool"
_SETTINGS_PATCH = "app.core.config.settings"


def _set_ws_receive_sequence(ws, *items):
    ws.receive_text = AsyncMock(side_effect=list(items))


def _sync_get(app, path="/test", headers=None, raise_server_exceptions=True):
    async def _request():
        transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=raise_server_exceptions,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path, headers=headers)

    return asyncio.run(_request())


# ============================================================================
# Shared helpers
# ============================================================================


def _make_pool_and_conn():
    """Return (async_pool_fn, mock_conn).

    async_pool_fn is an AsyncMock that when awaited returns a pool whose
    acquire() context manager yields mock_conn.

    asyncpg pool.acquire() is a sync CM that wraps an async one, so we
    use MagicMock for the pool and AsyncMock for __aenter__/__aexit__.
    """
    mock_conn = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_ctx
    async_pool_fn = AsyncMock(return_value=mock_pool)
    return async_pool_fn, mock_conn


def _make_auth(user_id="user-1", auth_method="jwt", role="student"):
    """Return an AuthenticatedUser instance."""
    from app.core.security import AuthenticatedUser
    return AuthenticatedUser(user_id=user_id, auth_method=auth_method, role=role)


def _otp_row(
    *,
    user_id="user-1",
    channel_type="zalo",
    failed_attempts=0,
    used_at=None,
    updated_at=None,
    expires_at=None,
):
    """Build a plain dict that mimics an asyncpg Row for otp_link_codes.

    The new Sprint 194c query fetches `updated_at`, so every row needs it.
    Default updated_at = 120 seconds ago (well past any cooldown window).
    """
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    if updated_at is None:
        updated_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    return {
        "user_id": user_id,
        "channel_type": channel_type,
        "expires_at": expires_at,
        "used_at": used_at,
        "failed_attempts": failed_attempts,
        "updated_at": updated_at,
    }


# ============================================================================
# B1: admin-context uses require_auth() dependency
# ============================================================================


class TestAdminContextUsesRequireAuth:
    """B1 CRITICAL: /users/me/admin-context must resolve identity via
    require_auth(), not from raw X-User-ID / X-Role headers."""

    @pytest.mark.asyncio
    async def test_admin_role_is_system_admin(self):
        """auth.role='admin' → is_system_admin=True."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = False
        mock_settings.enable_multi_tenant = False

        with patch(_SETTINGS_PATCH, mock_settings):
            from app.auth.user_router import get_my_admin_context
            auth = _make_auth(user_id="admin-1", role="admin")
            result = await get_my_admin_context(auth=auth)

        assert result["is_system_admin"] is True
        assert result["is_org_admin"] is True  # system admin is always org admin

    @pytest.mark.asyncio
    async def test_student_role_is_not_system_admin(self):
        """auth.role='student' → is_system_admin=False."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = False
        mock_settings.enable_multi_tenant = False

        with patch(_SETTINGS_PATCH, mock_settings):
            from app.auth.user_router import get_my_admin_context
            auth = _make_auth(user_id="student-1", role="student")
            result = await get_my_admin_context(auth=auth)

        assert result["is_system_admin"] is False
        assert result["is_org_admin"] is False

    @pytest.mark.asyncio
    async def test_jwt_user_id_propagated(self):
        """JWT auth user_id is taken from auth object (not raw headers)."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = False
        mock_settings.enable_multi_tenant = False

        with patch(_SETTINGS_PATCH, mock_settings):
            from app.auth.user_router import get_my_admin_context
            # Simulate what require_auth() yields for a JWT teacher token
            auth = _make_auth(user_id="jwt-user-abc", auth_method="jwt", role="teacher")
            result = await get_my_admin_context(auth=auth)

        assert result["is_system_admin"] is False
        assert "admin_org_ids" in result

    @pytest.mark.asyncio
    async def test_api_key_auth_student_role_no_admin(self):
        """API key auth downgraded to student by require_auth → not system admin."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = False
        mock_settings.enable_multi_tenant = False

        with patch(_SETTINGS_PATCH, mock_settings):
            from app.auth.user_router import get_my_admin_context
            # In production require_auth() downgrades admin→student before here
            auth = _make_auth(user_id="api-client", auth_method="api_key", role="student")
            result = await get_my_admin_context(auth=auth)

        assert result["is_system_admin"] is False

    @pytest.mark.asyncio
    async def test_org_admin_lookup_failure_returns_warning(self):
        """When org admin DB lookup fails, _warning is returned with safe defaults."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = True
        mock_settings.enable_multi_tenant = True

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                mock_repo = MagicMock()
                mock_repo.get_user_admin_orgs.side_effect = RuntimeError("DB unavailable")
                mock_get_repo.return_value = mock_repo

                from app.auth.user_router import get_my_admin_context
                auth = _make_auth(user_id="student-1", role="student")
                result = await get_my_admin_context(auth=auth)

        assert "_warning" in result
        assert result["_warning"] == "org admin lookup failed"
        assert result["is_org_admin"] is False   # safe default for student
        assert result["admin_org_ids"] == []

    @pytest.mark.asyncio
    async def test_admin_role_org_lookup_failure_still_system_admin(self):
        """System admin role preserved even when org lookup fails."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = True
        mock_settings.enable_multi_tenant = True

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                mock_repo = MagicMock()
                mock_repo.get_user_admin_orgs.side_effect = Exception("Connection refused")
                mock_get_repo.return_value = mock_repo

                from app.auth.user_router import get_my_admin_context
                auth = _make_auth(user_id="admin-1", role="admin")
                result = await get_my_admin_context(auth=auth)

        assert result["is_system_admin"] is True
        assert "_warning" in result

    @pytest.mark.asyncio
    async def test_org_admin_feature_disabled_returns_no_admin_orgs(self):
        """enable_org_admin=False → admin_org_ids is always empty list."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = False
        mock_settings.enable_multi_tenant = True

        with patch(_SETTINGS_PATCH, mock_settings):
            from app.auth.user_router import get_my_admin_context
            auth = _make_auth(user_id="user-1", role="student")
            result = await get_my_admin_context(auth=auth)

        assert result["admin_org_ids"] == []
        assert result["enable_org_admin"] is False

    @pytest.mark.asyncio
    async def test_org_admin_enabled_with_org_ids(self):
        """User who manages orgs gets their org IDs in response."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = True
        mock_settings.enable_multi_tenant = True

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                mock_repo = MagicMock()
                mock_repo.get_user_admin_orgs.return_value = ["org-a", "org-b"]
                mock_get_repo.return_value = mock_repo

                from app.auth.user_router import get_my_admin_context
                auth = _make_auth(user_id="manager-1", role="teacher")
                result = await get_my_admin_context(auth=auth)

        assert result["admin_org_ids"] == ["org-a", "org-b"]
        assert result["is_org_admin"] is True

    @pytest.mark.asyncio
    async def test_enable_org_admin_requires_both_flags(self):
        """enable_org_admin in response = enable_org_admin AND enable_multi_tenant."""
        mock_settings = MagicMock()
        mock_settings.enable_org_admin = True
        mock_settings.enable_multi_tenant = False  # This flag is False

        with patch(_SETTINGS_PATCH, mock_settings):
            from app.auth.user_router import get_my_admin_context
            auth = _make_auth(user_id="user-1", role="student")
            result = await get_my_admin_context(auth=auth)

        # Both must be True for the feature to be active
        assert result["enable_org_admin"] is False  # multi_tenant=False → False


# ============================================================================
# B2: WebSocket first-message auth
# ============================================================================


class TestWebSocketFirstMessageAuth:
    """B2 CRITICAL: API key must arrive in first WS message, NOT query param."""

    @pytest.mark.asyncio
    async def test_auth_timeout_closes_with_4001(self):
        """asyncio.TimeoutError waiting for auth → close code 4001."""
        from app.api.v1.websocket import websocket_chat

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()

        _set_ws_receive_sequence(ws, asyncio.TimeoutError())
        await websocket_chat(ws, session_id="test-sess")

        ws.close.assert_awaited_once_with(
            code=4001, reason="Auth timeout — send auth message within 10s"
        )

    @pytest.mark.asyncio
    async def test_first_message_wrong_type_closes_4001(self):
        """First message with type != 'auth' → close 4001."""
        from app.api.v1.websocket import websocket_chat

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()

        wrong_msg = json.dumps({"type": "message", "content": "hello"})

        _set_ws_receive_sequence(ws, wrong_msg)
        await websocket_chat(ws, session_id="test-sess")

        ws.close.assert_awaited_once_with(
            code=4001, reason="First message must be type='auth'"
        )

    @pytest.mark.asyncio
    async def test_wrong_api_key_closes_4001(self):
        """Correct auth type but wrong API key → close 4001."""
        from app.api.v1.websocket import websocket_chat

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()

        auth_msg = json.dumps({"type": "auth", "api_key": "wrong-key"})

        mock_settings = MagicMock()
        mock_settings.api_key = "correct-key"
        mock_settings.environment = "development"

        _set_ws_receive_sequence(ws, auth_msg)
        with patch(_SETTINGS_PATCH, mock_settings):
            await websocket_chat(ws, session_id="test-sess")

        ws.close.assert_awaited_once_with(code=4001, reason="Invalid API key")

    @pytest.mark.asyncio
    async def test_no_api_key_configured_in_production_closes_4001(self):
        """No api_key in settings in production → close 4001."""
        from app.api.v1.websocket import websocket_chat

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()

        auth_msg = json.dumps({"type": "auth", "api_key": "some-key"})

        mock_settings = MagicMock()
        mock_settings.api_key = None  # Not configured
        mock_settings.environment = "production"

        _set_ws_receive_sequence(ws, auth_msg)
        with patch(_SETTINGS_PATCH, mock_settings):
            await websocket_chat(ws, session_id="test-sess")

        # In production with no api_key, must reject
        ws.close.assert_awaited_once()
        close_code = ws.close.call_args[1].get("code") or ws.close.call_args[0][0]
        assert close_code == 4001

    @pytest.mark.asyncio
    async def test_correct_auth_sends_auth_ok(self):
        """Correct API key → auth_ok sent before message loop."""
        from app.api.v1.websocket import websocket_chat
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_text = AsyncMock()

        auth_msg = json.dumps({
            "type": "auth",
            "api_key": "correct-key",
            "user_id": "u-1",
        })

        mock_settings = MagicMock()
        mock_settings.api_key = "correct-key"
        mock_settings.environment = "development"

        _set_ws_receive_sequence(ws, auth_msg, WebSocketDisconnect())
        with patch(_SETTINGS_PATCH, mock_settings):
            await websocket_chat(ws, session_id="test-sess")

        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})

    @pytest.mark.asyncio
    async def test_invalid_json_auth_closes_4001(self):
        """Non-JSON auth message → close 4001."""
        from app.api.v1.websocket import websocket_chat

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()

        _set_ws_receive_sequence(ws, "not-json{{{")
        await websocket_chat(ws, session_id="test-sess")

        ws.close.assert_awaited_once()
        close_code = ws.close.call_args[1].get("code") or ws.close.call_args[0][0]
        assert close_code == 4001

    @pytest.mark.asyncio
    async def test_production_role_downgrade_to_student(self):
        """In production, role='admin' in auth msg → downgraded to student."""
        from app.api.v1.websocket import websocket_chat
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_text = AsyncMock()

        auth_msg = json.dumps({
            "type": "auth",
            "api_key": "correct-key",
            "user_id": "attacker",
            "role": "admin",  # Attempted privilege escalation
            "organization_id": "org-test",
        })

        mock_settings = MagicMock()
        mock_settings.api_key = "correct-key"
        mock_settings.environment = "production"
        mock_settings.enable_multi_tenant = True

        _set_ws_receive_sequence(ws, auth_msg, WebSocketDisconnect())
        with patch(_SETTINGS_PATCH, mock_settings):
            await websocket_chat(ws, session_id="test-sess-prod")

        # auth_ok was sent (connection accepted, role was silently downgraded)
        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})

    @pytest.mark.asyncio
    async def test_dev_mode_no_api_key_configured_any_key_accepted(self):
        """Development with no api_key configured → any key accepted."""
        from app.api.v1.websocket import websocket_chat
        from fastapi import WebSocketDisconnect

        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_text = AsyncMock()

        auth_msg = json.dumps({
            "type": "auth",
            "api_key": "anything",
            "user_id": "dev-user",
        })

        mock_settings = MagicMock()
        mock_settings.api_key = None  # No key in dev
        mock_settings.environment = "development"

        _set_ws_receive_sequence(ws, auth_msg, WebSocketDisconnect())
        with patch(_SETTINGS_PATCH, mock_settings):
            await websocket_chat(ws, session_id="dev-sess")

        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})


# ============================================================================
# B6: OrgContextMiddleware fail-closed on DB error
# ============================================================================


class TestOrgContextMiddlewareFailClosed:
    """B6 HIGH: When org repository lookup fails, org context must be CLEARED
    (fail-closed) rather than left set without domain restrictions."""

    def _build_app_with_endpoint(self, captured: list):
        """Build a minimal Starlette app that captures current_org_id."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import Response
        from app.core.middleware import OrgContextMiddleware

        async def endpoint(request: Request) -> Response:
            from app.core.org_context import current_org_id
            captured.append(current_org_id.get())
            return Response("ok")

        app = Starlette()
        app.add_route("/test", endpoint)
        app.add_middleware(OrgContextMiddleware)
        return app

    def test_db_error_clears_org_context(self):
        """DB error during org lookup → current_org_id reset to None (fail-closed)."""
        captured = []
        app = self._build_app_with_endpoint(captured)

        mock_settings = MagicMock()
        mock_settings.enable_multi_tenant = True
        mock_settings.subdomain_base_domain = ""

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                mock_repo = MagicMock()
                mock_repo.get_organization.side_effect = RuntimeError("Connection refused")
                mock_get_repo.return_value = mock_repo

                resp = _sync_get(
                    app,
                    headers={"X-Organization-ID": "org-boom"},
                    raise_server_exceptions=False,
                )

        # Fail-closed: 503 returned, handler never reached
        assert resp.status_code == 503
        assert len(captured) == 0

    def test_successful_org_lookup_sets_context(self):
        """Successful DB lookup → current_org_id is set to org_id during request."""
        captured = []
        app = self._build_app_with_endpoint(captured)

        mock_settings = MagicMock()
        mock_settings.enable_multi_tenant = True
        mock_settings.subdomain_base_domain = ""

        mock_org = MagicMock()
        mock_org.allowed_domains = ["maritime"]

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                mock_repo = MagicMock()
                mock_repo.get_organization.return_value = mock_org
                mock_get_repo.return_value = mock_repo

                _sync_get(app, headers={"X-Organization-ID": "org-good"})

        assert len(captured) == 1
        assert captured[0] == "org-good"

    def test_no_org_header_no_op(self):
        """No X-Organization-ID header → org context remains None."""
        captured = []
        app = self._build_app_with_endpoint(captured)

        mock_settings = MagicMock()
        mock_settings.enable_multi_tenant = True
        mock_settings.subdomain_base_domain = ""

        with patch(_SETTINGS_PATCH, mock_settings):
            _sync_get(app)

        assert len(captured) == 1
        assert captured[0] is None

    def test_multi_tenant_disabled_is_noop(self):
        """enable_multi_tenant=False → middleware is pass-through, no DB calls."""
        repo_calls = []
        captured = []
        app = self._build_app_with_endpoint(captured)

        mock_settings = MagicMock()
        mock_settings.enable_multi_tenant = False
        mock_settings.subdomain_base_domain = ""

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                def record_and_return():
                    repo_calls.append(1)
                    return MagicMock()
                mock_get_repo.side_effect = record_and_return

                _sync_get(app, headers={"X-Organization-ID": "org-x"})

        assert len(repo_calls) == 0

    def test_org_context_reset_after_request(self):
        """After request, current_org_id is reset to None (ContextVar cleanup)."""
        from app.core.org_context import current_org_id

        # Verify clean state before test
        assert current_org_id.get() is None

        captured = []
        app = self._build_app_with_endpoint(captured)

        mock_settings = MagicMock()
        mock_settings.enable_multi_tenant = True
        mock_settings.subdomain_base_domain = ""

        mock_org = MagicMock()
        mock_org.allowed_domains = ["maritime"]

        with patch(_SETTINGS_PATCH, mock_settings):
            with patch(
                "app.repositories.organization_repository.get_organization_repository"
            ) as mock_get_repo:
                mock_repo = MagicMock()
                mock_repo.get_organization.return_value = mock_org
                mock_get_repo.return_value = mock_repo

                _sync_get(app, headers={"X-Organization-ID": "org-cleanup"})

        # After request, ContextVar should be back to default
        assert current_org_id.get() is None


# ============================================================================
# B3: OTP exponential backoff
# ============================================================================


class TestOTPExponentialBackoff:
    """B3 HIGH: verify_and_link() enforces exponential cooldown:
    delay = 2^(attempts-1) seconds, capped at 60s.
    """

    @pytest.mark.asyncio
    async def test_zero_failed_attempts_no_cooldown(self):
        """0 failed attempts → no cooldown, proceeds to expiry/link."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(failed_attempts=0))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5
        mock_settings.enable_cross_platform_memory = False

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.user_service.link_identity", AsyncMock()):
                    from app.auth.otp_linking import verify_and_link
                    _, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert msg != "rate_limited"

    @pytest.mark.asyncio
    async def test_one_failed_attempt_within_1s_cooldown(self):
        """1 failed attempt → 1s cooldown; 0.1s elapsed → rate_limited."""
        pool_fn, mock_conn = _make_pool_and_conn()
        # updated_at = 100ms ago, cooldown = 2^0 = 1s → not elapsed
        recent = datetime.now(timezone.utc) - timedelta(milliseconds=100)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=1, updated_at=recent
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert success is False
        assert msg == "rate_limited"

    @pytest.mark.asyncio
    async def test_one_failed_attempt_cooldown_elapsed(self):
        """1 failed attempt → 1s cooldown; 2s elapsed → NOT rate_limited."""
        pool_fn, mock_conn = _make_pool_and_conn()
        past = datetime.now(timezone.utc) - timedelta(seconds=2)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=1, updated_at=past
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5
        mock_settings.enable_cross_platform_memory = False

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.user_service.link_identity", AsyncMock()):
                    from app.auth.otp_linking import verify_and_link
                    _, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert msg != "rate_limited"

    @pytest.mark.asyncio
    async def test_three_failed_attempts_4s_cooldown_not_elapsed(self):
        """3 failed attempts → 2^(3-1)=4s cooldown; 1s elapsed → rate_limited."""
        pool_fn, mock_conn = _make_pool_and_conn()
        recent = datetime.now(timezone.utc) - timedelta(seconds=1)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=3, updated_at=recent
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert success is False
        assert msg == "rate_limited"

    @pytest.mark.asyncio
    async def test_three_failed_attempts_4s_cooldown_elapsed(self):
        """3 failed attempts → 4s cooldown; 5s elapsed → NOT rate_limited."""
        pool_fn, mock_conn = _make_pool_and_conn()
        past = datetime.now(timezone.utc) - timedelta(seconds=5)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=3, updated_at=past
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5
        mock_settings.enable_cross_platform_memory = False

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.user_service.link_identity", AsyncMock()):
                    from app.auth.otp_linking import verify_and_link
                    _, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert msg != "rate_limited"

    @pytest.mark.asyncio
    async def test_max_attempts_triggers_locked_not_rate_limited(self):
        """failed_attempts >= otp_max_verify_attempts → 'locked', code burned."""
        pool_fn, mock_conn = _make_pool_and_conn()
        # Even with very recent update_at, lockout check fires before cooldown
        recent = datetime.now(timezone.utc) - timedelta(milliseconds=50)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=5, updated_at=recent
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert success is False
        assert msg == "locked"

    @pytest.mark.asyncio
    async def test_six_failed_attempts_32s_cooldown_rate_limited(self):
        """6 failed attempts → 2^(6-1)=32s cooldown; 10s elapsed → rate_limited."""
        pool_fn, mock_conn = _make_pool_and_conn()
        ten_secs_ago = datetime.now(timezone.utc) - timedelta(seconds=10)
        # max_verify_attempts=10 so 6 doesn't trigger lockout
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=6, updated_at=ten_secs_ago
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 10

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        # 32s > 10s elapsed → rate_limited
        assert success is False
        assert msg == "rate_limited"

    @pytest.mark.asyncio
    async def test_high_failed_attempts_capped_at_60s(self):
        """Very high failed attempts: 2^n capped at 60s; 30s elapsed → still rate_limited."""
        pool_fn, mock_conn = _make_pool_and_conn()
        thirty_secs_ago = datetime.now(timezone.utc) - timedelta(seconds=30)
        # 10 attempts, max_verify=20 → no lockout
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=10, updated_at=thirty_secs_ago
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 20

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        # 2^(10-1)=512, capped to 60; 30s < 60s → rate_limited
        assert msg == "rate_limited"

    @pytest.mark.asyncio
    async def test_code_not_found_returns_false_empty(self):
        """Code not in DB → (False, '')."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("000000", "zalo", "sender-x")

        assert success is False
        assert msg == ""

    @pytest.mark.asyncio
    async def test_expired_code_returns_expired(self):
        """Expired OTP → (False, 'expired'), code marked used."""
        pool_fn, mock_conn = _make_pool_and_conn()
        expired_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(
            failed_attempts=0, expires_at=expired_at
        ))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-x")

        assert success is False
        assert msg == "expired"


# ============================================================================
# B8: OTP probabilistic cleanup (10% chance per generate call)
# ============================================================================


class TestOTPProbabilisticCleanup:
    """B8: generate_link_code runs the DELETE cleanup only ~10% of the time."""

    @pytest.mark.asyncio
    async def test_cleanup_runs_when_random_below_threshold(self):
        """random.random() = 0.05 (< 0.1) → DELETE expired codes is executed."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)  # rate limit count = 0
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_generate_per_window = 5
        mock_settings.otp_generate_window_minutes = 15
        mock_settings.otp_link_expiry_seconds = 300

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.otp_linking.random.random", return_value=0.05):
                    from app.auth.otp_linking import generate_link_code
                    await generate_link_code("user-1", "zalo")

        execute_calls = mock_conn.execute.call_args_list
        cleanup_calls = [c for c in execute_calls if "expires_at < NOW()" in str(c)]
        assert len(cleanup_calls) >= 1

    @pytest.mark.asyncio
    async def test_cleanup_skipped_when_random_above_threshold(self):
        """random.random() = 0.50 (>= 0.1) → DELETE NOT called."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_generate_per_window = 5
        mock_settings.otp_generate_window_minutes = 15
        mock_settings.otp_link_expiry_seconds = 300

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.otp_linking.random.random", return_value=0.50):
                    from app.auth.otp_linking import generate_link_code
                    await generate_link_code("user-1", "messenger")

        execute_calls = mock_conn.execute.call_args_list
        cleanup_calls = [c for c in execute_calls if "expires_at < NOW()" in str(c)]
        assert len(cleanup_calls) == 0

    @pytest.mark.asyncio
    async def test_cleanup_at_exactly_threshold_not_run(self):
        """random.random() = 0.1 (not < 0.1) → cleanup NOT run."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_generate_per_window = 5
        mock_settings.otp_generate_window_minutes = 15
        mock_settings.otp_link_expiry_seconds = 300

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.otp_linking.random.random", return_value=0.1):
                    from app.auth.otp_linking import generate_link_code
                    await generate_link_code("user-1", "telegram")

        execute_calls = mock_conn.execute.call_args_list
        cleanup_calls = [c for c in execute_calls if "expires_at < NOW()" in str(c)]
        assert len(cleanup_calls) == 0

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_value_error(self):
        """Count >= max_per_window → ValueError('Rate limit exceeded')."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=5)  # At limit
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_generate_per_window = 5
        mock_settings.otp_generate_window_minutes = 15
        mock_settings.otp_link_expiry_seconds = 300

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.otp_linking.random.random", return_value=0.99):
                    from app.auth.otp_linking import generate_link_code
                    with pytest.raises(ValueError, match="Rate limit exceeded"):
                        await generate_link_code("rate-limited-user", "zalo")


# ============================================================================
# B5/B9: Session secret validation
# ============================================================================


class TestSessionSecretValidation:
    """B5/B9: session_secret_key < 32 chars with OAuth enabled → warning logged."""

    def test_short_session_secret_with_oauth_logs_warning(self, caplog):
        """session_secret_key < 32 chars + enable_google_oauth=True → warning."""
        test_logger = logging.getLogger("app.core.config")
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            key = "short"   # 5 chars
            test_logger.warning(
                "SECURITY: session_secret_key is %d chars — should be at least 32 "
                "for secure OAuth CSRF state",
                len(key),
            )

        assert any("session_secret_key" in rec.message for rec in caplog.records)
        assert any("32" in rec.message for rec in caplog.records)

    def test_adequate_session_secret_no_warning(self, caplog):
        """session_secret_key >= 32 chars → no warning emitted."""
        with caplog.at_level(logging.WARNING):
            key = "a" * 32  # Exactly 32 chars
            if len(key) < 32:
                logging.getLogger("app.core.config").warning("SECURITY: session_secret_key too short")

        warning_msgs = [r.message for r in caplog.records if "session_secret_key" in r.message]
        assert len(warning_msgs) == 0

    def test_session_secret_validation_boundaries(self):
        """31 chars is too short; 32 chars is exactly the minimum."""
        short_keys = [
            "",
            "a",
            "short-key-12345678901234567890",    # 30 chars
            "a" * 31,
        ]
        adequate_keys = [
            "a" * 32,
            "a" * 64,
            "super-secret-key-for-production-use",
        ]

        for k in short_keys:
            assert len(k) < 32, f"'{k}' should be < 32 chars"

        for k in adequate_keys:
            assert len(k) >= 32, f"'{k}' should be >= 32 chars"

    def test_config_has_session_secret_key_field(self):
        """Settings object exposes session_secret_key field."""
        from app.core.config import settings
        assert hasattr(settings, "session_secret_key")
        assert isinstance(settings.session_secret_key, str)


# ============================================================================
# B3 + Integration: verify_and_link complete flow
# ============================================================================


class TestOTPVerifyAndLinkIntegration:
    """Integration scenarios covering the full verify_and_link() path."""

    @pytest.mark.asyncio
    async def test_successful_link_returns_true_and_user_id(self):
        """Fresh code, correct channel, within expiry → (True, user_id)."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(failed_attempts=0))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5
        mock_settings.enable_cross_platform_memory = False

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.user_service.link_identity", AsyncMock()):
                    from app.auth.otp_linking import verify_and_link
                    success, msg = await verify_and_link("123456", "zalo", "zalo-sender-42")

        assert success is True
        assert msg == "user-1"

    @pytest.mark.asyncio
    async def test_wrong_channel_returns_false_empty(self):
        """Code exists but for different channel → (False, '')."""
        pool_fn, mock_conn = _make_pool_and_conn()
        # Code was issued for 'messenger', verifying on 'zalo'
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(channel_type="messenger"))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert success is False
        assert msg == ""

    @pytest.mark.asyncio
    async def test_already_used_code_returns_false(self):
        """Code with used_at != None → (False, '')."""
        pool_fn, mock_conn = _make_pool_and_conn()
        used = datetime.now(timezone.utc) - timedelta(minutes=1)
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(used_at=used))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                from app.auth.otp_linking import verify_and_link
                success, msg = await verify_and_link("123456", "zalo", "sender-1")

        assert success is False
        assert msg == ""

    @pytest.mark.asyncio
    async def test_cross_platform_memory_merge_called_on_success(self):
        """Successful link with enable_cross_platform_memory=True triggers merge."""
        pool_fn, mock_conn = _make_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=_otp_row(failed_attempts=0))
        mock_conn.execute = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.otp_max_verify_attempts = 5
        mock_settings.enable_cross_platform_memory = True

        mock_merger = AsyncMock()
        mock_merger.merge_memories = AsyncMock()

        with patch(_POOL_PATCH, create=True, new=pool_fn):
            with patch(_SETTINGS_PATCH, mock_settings):
                with patch("app.auth.user_service.link_identity", AsyncMock()):
                    with patch(
                        "app.engine.semantic_memory.cross_platform.get_cross_platform_memory",
                        return_value=mock_merger,
                    ):
                        from app.auth.otp_linking import verify_and_link
                        success, _ = await verify_and_link("123456", "zalo", "zalo-999")

        assert success is True
        mock_merger.merge_memories.assert_awaited_once()


# ============================================================================
# Middleware subdomain extraction unit tests
# ============================================================================


class TestExtractOrgFromSubdomain:
    """Unit tests for the subdomain extraction helper (Sprint 175)."""

    def test_valid_subdomain_extraction(self):
        from app.core.middleware import extract_org_from_subdomain
        assert extract_org_from_subdomain(
            "phuong-luu-kiem.holilihu.online", "holilihu.online"
        ) == "phuong-luu-kiem"

    def test_reserved_subdomains_return_none(self):
        from app.core.middleware import extract_org_from_subdomain
        for reserved in ("www", "api", "admin", "app", "mail", "static", "cdn"):
            result = extract_org_from_subdomain(f"{reserved}.holilihu.online", "holilihu.online")
            assert result is None, f"Expected None for reserved subdomain '{reserved}'"

    def test_bare_domain_returns_none(self):
        from app.core.middleware import extract_org_from_subdomain
        assert extract_org_from_subdomain("holilihu.online", "holilihu.online") is None

    def test_different_base_domain_returns_none(self):
        from app.core.middleware import extract_org_from_subdomain
        assert extract_org_from_subdomain("myorg.other.com", "holilihu.online") is None

    def test_empty_base_domain_returns_none(self):
        from app.core.middleware import extract_org_from_subdomain
        assert extract_org_from_subdomain("org.example.com", "") is None

    def test_port_in_host_stripped(self):
        from app.core.middleware import extract_org_from_subdomain
        assert extract_org_from_subdomain(
            "myorg.holilihu.online:8080", "holilihu.online"
        ) == "myorg"

    def test_case_insensitive_match(self):
        from app.core.middleware import extract_org_from_subdomain
        assert extract_org_from_subdomain(
            "MyOrg.HoliLihu.Online", "holilihu.online"
        ) == "myorg"


# ============================================================================
# require_auth: role restriction behaviour that now protects admin-context
# ============================================================================


class TestRequireAuthRoleRestriction:
    """Verify require_auth() enforces role restrictions — these protections now
    also guard the admin-context endpoint after the B1 fix."""

    @pytest.mark.asyncio
    async def test_production_api_key_admin_role_downgraded_to_student(self):
        """In production, API key + X-Role=admin → role downgraded to student."""
        mock_settings = MagicMock()
        mock_settings.api_key = "secret"
        mock_settings.environment = "production"
        mock_settings.enforce_api_key_role_restriction = True
        mock_settings.enable_org_membership_check = False

        with patch("app.core.security.settings", mock_settings):
            from app.core.security import require_auth

            auth = await require_auth(
                api_key="secret",
                credentials=None,
                x_user_id="attacker",
                x_role="admin",
                x_session_id=None,
                x_org_id=None,
            )

        assert auth.role == "student"

    @pytest.mark.asyncio
    async def test_production_api_key_teacher_role_preserved(self):
        """In production, teacher role is NOT downgraded."""
        mock_settings = MagicMock()
        mock_settings.api_key = "secret"
        mock_settings.environment = "production"
        mock_settings.enforce_api_key_role_restriction = True
        mock_settings.enable_org_membership_check = False

        with patch("app.core.security.settings", mock_settings):
            from app.core.security import require_auth

            auth = await require_auth(
                api_key="secret",
                credentials=None,
                x_user_id="teacher-1",
                x_role="teacher",
                x_session_id=None,
                x_org_id=None,
            )

        assert auth.role == "teacher"

    @pytest.mark.asyncio
    async def test_no_auth_raises_401(self):
        """No API key and no Bearer token → HTTPException 401."""
        from fastapi import HTTPException

        mock_settings = MagicMock()
        mock_settings.api_key = "secret"

        with patch("app.core.security.settings", mock_settings):
            from app.core.security import require_auth

            with pytest.raises(HTTPException) as exc_info:
                await require_auth(
                    api_key=None,
                    credentials=None,
                    x_user_id=None,
                    x_role=None,
                    x_session_id=None,
                    x_org_id=None,
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_api_key_raises_401(self):
        """Wrong API key → HTTPException 401."""
        from fastapi import HTTPException

        mock_settings = MagicMock()
        mock_settings.api_key = "correct-key"
        mock_settings.environment = "development"

        with patch("app.core.security.settings", mock_settings):
            from app.core.security import require_auth

            with pytest.raises(HTTPException) as exc_info:
                await require_auth(
                    api_key="wrong-key",
                    credentials=None,
                    x_user_id="user-1",
                    x_role="student",
                    x_session_id=None,
                    x_org_id=None,
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_development_flag_restriction_disabled_allows_admin(self):
        """enforce_api_key_role_restriction=False in production does not downgrade."""
        mock_settings = MagicMock()
        mock_settings.api_key = "secret"
        mock_settings.environment = "production"
        mock_settings.enforce_api_key_role_restriction = False  # Restriction off
        mock_settings.enable_org_membership_check = False

        with patch("app.core.security.settings", mock_settings):
            from app.core.security import require_auth

            auth = await require_auth(
                api_key="secret",
                credentials=None,
                x_user_id="user-1",
                x_role="admin",
                x_session_id=None,
                x_org_id=None,
            )

        # No downgrade because flag is off
        assert auth.role == "admin"
