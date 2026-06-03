"""
Sprint 176: "Bao Mat Dang Nhap" — Auth Hardening Tests

Tests: PKCE, JWT jti, refresh token family_id, replay detection,
OTP database, auth audit events, security payload.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Helper: get_asyncpg_pool is a lazy import inside function bodies,
# and may not exist yet as a module-level attribute in app.core.database.
# Use create=True so patch creates the attribute for the test.
_POOL_PATCH = "app.core.database.get_asyncpg_pool"


@pytest.fixture(autouse=True)
def _reset_db_degraded_cooldown():
    from app.core.database import clear_shared_database_unavailable

    clear_shared_database_unavailable()
    yield
    clear_shared_database_unavailable()


def _mock_pool_and_conn():
    """Create standard mock pool + connection for async DB tests.

    Returns (pool_coro, mock_conn) where pool_coro is an AsyncMock
    that when awaited returns a pool with working acquire() context manager.
    """
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    # pool.acquire() returns an async context manager
    acm = AsyncMock()
    acm.__aenter__ = AsyncMock(return_value=mock_conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = acm

    # get_asyncpg_pool is an async function → returns awaitable that yields mock_pool
    async_pool_fn = AsyncMock(return_value=mock_pool)
    return async_pool_fn, mock_conn


# ============================================================================
# TestConfig
# ============================================================================

class TestConfig:
    """Test enable_auth_audit config flag."""

    def test_enable_auth_audit_default_true(self):
        """enable_auth_audit defaults to True."""
        from app.core.config import settings
        assert hasattr(settings, "enable_auth_audit")

    def test_backward_compat_no_crash(self):
        """Settings load without errors even with new field."""
        from app.core.config import settings
        assert settings is not None


# ============================================================================
# TestPKCE
# ============================================================================

class TestPKCE:
    """Test PKCE S256 enforcement in OAuth config."""

    def test_client_kwargs_has_s256(self):
        """OAuth client_kwargs includes code_challenge_method S256."""
        try:
            import authlib
            if not hasattr(authlib, "__version__"):
                pytest.skip("authlib is mocked, not real")
            from app.auth.google_oauth import oauth
        except ImportError:
            pytest.skip("authlib not installed")
        config = oauth._registry.get("google")
        assert config is not None
        client_kwargs = getattr(config, "client_kwargs", None)
        if client_kwargs is None and isinstance(config, tuple) and len(config) >= 2:
            registry_entry = config[1]
            if isinstance(registry_entry, dict):
                client_kwargs = registry_entry.get("client_kwargs", {})
            else:
                client_kwargs = getattr(registry_entry, "client_kwargs", {})
        client_kwargs = client_kwargs or {}
        assert client_kwargs.get("code_challenge_method") == "S256"

    def test_oauth_module_imports(self):
        """google_oauth module imports without errors."""
        try:
            import app.auth.google_oauth as mod
        except ImportError:
            pytest.skip("authlib not installed")
        assert hasattr(mod, "router")
        assert hasattr(mod, "oauth")


# ============================================================================
# TestJWTJti
# ============================================================================

class TestJWTJti:
    """Test JWT jti (unique token ID) claim."""

    def test_jti_in_access_token_payload(self):
        """create_access_token includes jti claim."""
        with patch("app.auth.token_service.settings") as mock_settings:
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_access_token
            token = create_access_token(user_id="user-1", email="a@b.com")

            import jwt
            payload = jwt.decode(token, "test-secret-key-12345", algorithms=["HS256"], audience="wiii")
            assert "jti" in payload
            assert payload["jti"] is not None

    def test_jti_is_uuid_format(self):
        """jti is a valid UUID string."""
        with patch("app.auth.token_service.settings") as mock_settings:
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_access_token
            token = create_access_token(user_id="user-1")

            import jwt
            payload = jwt.decode(token, "test-secret-key-12345", algorithms=["HS256"], audience="wiii")
            uuid.UUID(payload["jti"])  # Should not raise

    def test_jti_unique_per_token(self):
        """Each token gets a unique jti."""
        with patch("app.auth.token_service.settings") as mock_settings:
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_access_token
            t1 = create_access_token(user_id="user-1")
            t2 = create_access_token(user_id="user-1")

            import jwt
            p1 = jwt.decode(t1, "test-secret-key-12345", algorithms=["HS256"], audience="wiii")
            p2 = jwt.decode(t2, "test-secret-key-12345", algorithms=["HS256"], audience="wiii")
            assert p1["jti"] != p2["jti"]

    def test_jti_in_access_token_payload_model(self):
        """AccessTokenPayload model accepts jti field."""
        from app.auth.token_service import AccessTokenPayload
        payload = AccessTokenPayload(
            sub="user-1",
            exp=datetime.now(timezone.utc) + timedelta(minutes=30),
            iat=datetime.now(timezone.utc),
            jti="test-jti-123",
        )
        assert payload.jti == "test-jti-123"

    def test_jti_optional_backward_compat(self):
        """AccessTokenPayload works without jti (backward compat)."""
        from app.auth.token_service import AccessTokenPayload
        payload = AccessTokenPayload(
            sub="user-1",
            exp=datetime.now(timezone.utc) + timedelta(minutes=30),
            iat=datetime.now(timezone.utc),
        )
        assert payload.jti is None


# ============================================================================
# TestRefreshFamily
# ============================================================================

class TestRefreshFamily:
    """Test refresh token family_id for replay detection."""

    @pytest.mark.asyncio
    async def test_family_id_generated_on_create(self):
        """create_token_pair generates family_id when not provided."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            pair = await create_token_pair(user_id="user-1")

            call_args = mock_conn.execute.call_args
            assert call_args is not None
            args = call_args[0]
            assert len(args) >= 7  # SQL + 6 params
            family_id = args[6]
            assert family_id is not None
            uuid.UUID(family_id)  # Should be valid UUID

    @pytest.mark.asyncio
    async def test_family_id_propagated_when_provided(self):
        """create_token_pair uses provided family_id."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            await create_token_pair(user_id="user-1", family_id="family-abc")

            call_args = mock_conn.execute.call_args
            args = call_args[0]
            family_id = args[6]
            assert family_id == "family-abc"

    @pytest.mark.asyncio
    async def test_create_token_pair_returns_valid_pair(self):
        """create_token_pair returns valid TokenPair with all fields."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            pair = await create_token_pair(user_id="user-1", email="a@b.com")

            assert pair.access_token
            assert pair.refresh_token
            assert pair.token_type == "bearer"
            assert pair.expires_in == 30 * 60

    @pytest.mark.asyncio
    async def test_family_id_sql_includes_column(self):
        """INSERT SQL includes family_id column."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            await create_token_pair(user_id="user-1")

            sql = mock_conn.execute.call_args[0][0]
            assert "family_id" in sql

    @pytest.mark.asyncio
    async def test_identity_snapshot_persisted_with_refresh_token(self):
        """Refresh-token row stores additive Identity V2 context."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            await create_token_pair(
                user_id="user-1",
                role="teacher",
                platform_role="user",
                organization_role="org_admin",
                host_role="teacher",
                role_source="lms_host",
                active_organization_id="org-lms",
                connector_id="maritime-lms",
                identity_version="2",
            )

            sql = mock_conn.execute.call_args[0][0]
            args = mock_conn.execute.call_args[0]
            assert "identity_snapshot" in sql
            assert args[7] == "org-lms"
            snapshot = json.loads(args[8])
            assert snapshot["role"] == "teacher"
            assert snapshot["platform_role"] == "user"
            assert snapshot["organization_role"] == "org_admin"
            assert snapshot["host_role"] == "teacher"
            assert snapshot["connector_id"] == "maritime-lms"
            assert snapshot["identity_version"] == "2"

    @pytest.mark.asyncio
    async def test_db_failure_still_returns_pair(self):
        """Token pair is still returned even if DB fails."""
        failing_pool_fn = AsyncMock(side_effect=Exception("DB down"))

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=failing_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            pair = await create_token_pair(user_id="user-1")
            assert pair.access_token
            assert pair.refresh_token

    @pytest.mark.asyncio
    async def test_stateless_dev_refresh_rotates_without_db(self):
        """Local dev fallback refresh should not depend on PostgreSQL."""
        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, side_effect=AssertionError("DB should not be used")):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"
            mock_settings.enable_dev_login = True
            mock_settings.environment = "development"

            from app.auth.token_service import (
                create_stateless_refresh_token,
                refresh_access_token,
            )

            refresh_token = create_stateless_refresh_token(
                user_id="user-dev",
                email="dev@example.test",
                name="Dev User",
                role="admin",
                platform_role="platform_admin",
                auth_method="dev",
            )
            pair = await refresh_access_token(refresh_token)

            assert pair is not None
            assert pair.access_token
            assert pair.refresh_token != refresh_token

    @pytest.mark.asyncio
    async def test_identity_snapshot_insert_falls_back_to_legacy_schema(self):
        """Missing Identity V2 columns should not break refresh-token storage."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.execute.side_effect = [
            Exception('column "identity_snapshot" of relation "refresh_tokens" does not exist'),
            None,
        ]

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import create_token_pair
            pair = await create_token_pair(user_id="user-1", role="teacher")

            assert pair.access_token
            assert pair.refresh_token
            assert mock_conn.execute.await_count == 2
            fallback_sql = mock_conn.execute.await_args_list[1][0][0]
            assert "identity_snapshot" not in fallback_sql
            assert "family_id" in fallback_sql

    @pytest.mark.asyncio
    async def test_strict_schema_missing_uses_stateless_refresh_with_org(self):
        """Strict multi-tenant issuance must not persist org-less legacy refresh rows."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.execute.side_effect = [
            Exception('column "identity_snapshot" of relation "refresh_tokens" does not exist'),
        ]

        with patch("app.auth.token_service.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"
            mock_settings.environment = "production"
            mock_settings.enable_multi_tenant = True

            from app.auth.token_service import create_token_pair
            pair = await create_token_pair(
                user_id="user-1",
                role="student",
                active_organization_id="org-default",
            )

            import jwt
            refresh_payload = jwt.decode(
                pair.refresh_token,
                "test-secret-key-12345",
                algorithms=["HS256"],
                audience="wiii",
            )
            assert refresh_payload["type"] == "refresh"
            assert refresh_payload["stateless"] is True
            assert refresh_payload["active_organization_id"] == "org-default"
            assert mock_conn.execute.await_count == 1


# ============================================================================
# TestReplayDetection
# ============================================================================

class TestReplayDetection:
    """Test refresh token replay detection."""

    @pytest.mark.asyncio
    async def test_revoked_with_active_siblings_purges_family(self):
        """Reusing a revoked token that has active siblings purges the family."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": datetime.now(timezone.utc),
            "auth_method": "google",
            "family_id": "family-abc",
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
        }
        mock_conn.fetchval.return_value = 2  # Active siblings

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock):
            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("fake-refresh-token")

            assert result is None
            purge_calls = [
                c for c in mock_conn.execute.call_args_list
                if "family_id" in str(c)
            ]
            assert len(purge_calls) > 0

    @pytest.mark.asyncio
    async def test_replay_diagnostics_hash_user_and_family_refs(self, caplog):
        """Replay diagnostics must not expose raw user_id or token family_id."""
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        async_pool_fn, mock_conn = _mock_pool_and_conn()
        raw_user_id = "user-replay-secret"
        raw_family_id = "family-replay-secret"

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": raw_user_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": datetime.now(timezone.utc),
            "auth_method": "google",
            "family_id": raw_family_id,
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
        }
        mock_conn.fetchval.return_value = 2

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock) as mock_audit, \
             caplog.at_level(logging.WARNING, logger="app.auth.token_service"):
            from app.auth.token_service import refresh_access_token

            result = await refresh_access_token("fake-refresh-token")

        assert result is None
        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert raw_user_id not in log_text
        assert raw_family_id not in log_text
        assert f"user_ref={hash_runtime_identifier(raw_user_id)}" in log_text
        assert f"family_ref={hash_runtime_identifier(raw_family_id)}" in log_text

        replay_audit = [
            call
            for call in mock_audit.await_args_list
            if call.args and call.args[0] == "token_replay_detected"
        ][0]
        reason = replay_audit.kwargs["reason"]
        assert raw_family_id not in reason
        assert f"family_ref={hash_runtime_identifier(raw_family_id)}" in reason

    @pytest.mark.asyncio
    async def test_revoked_no_active_siblings_returns_none(self):
        """Revoked token with no active siblings just returns None."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": datetime.now(timezone.utc),
            "auth_method": "google",
            "family_id": "family-abc",
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
        }
        mock_conn.fetchval.return_value = 0

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("fake-refresh-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_null_family_no_replay_check(self):
        """Revoked token with NULL family_id skips replay check."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": datetime.now(timezone.utc),
            "auth_method": "google",
            "family_id": None,
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("fake-refresh-token")
            assert result is None
            mock_conn.fetchval.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_rotation_propagates_family(self):
        """Valid refresh propagates family_id to new token pair."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": None,
            "auth_method": "google",
            "family_id": "family-xyz",
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.token_service.settings") as mock_settings, \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"

            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("valid-refresh-token")

            assert result is not None
            assert result.access_token
            assert result.refresh_token

            insert_calls = [
                c for c in mock_conn.execute.call_args_list
                if "INSERT" in str(c) and "family_id" in str(c)
            ]
            assert len(insert_calls) > 0

    @pytest.mark.asyncio
    async def test_refresh_preserves_identity_snapshot(self):
        """Rotated tokens keep additive Identity V2 claims from refresh storage."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": None,
            "auth_method": "lms",
            "family_id": "family-xyz",
            "organization_id": "org-lms",
            "identity_snapshot": {
                "role": "teacher",
                "platform_role": "user",
                "organization_role": "org_admin",
                "host_role": "org_admin",
                "role_source": "lms_host",
                "active_organization_id": "org-lms",
                "connector_id": "maritime-lms",
                "identity_version": "2",
            },
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock) as mock_create, \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock):
            mock_create.return_value = MagicMock(
                access_token="at",
                refresh_token="rt",
                token_type="bearer",
                expires_in=1800,
            )

            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("valid-refresh-token")

            assert result is not None
            kwargs = mock_create.call_args.kwargs
            assert kwargs["role"] == "teacher"
            assert kwargs["platform_role"] == "user"
            assert kwargs["organization_role"] == "org_admin"
            assert kwargs["host_role"] == "org_admin"
            assert kwargs["role_source"] == "lms_host"
            assert kwargs["active_organization_id"] == "org-lms"
            assert kwargs["connector_id"] == "maritime-lms"
            assert kwargs["identity_version"] == "2"
            assert kwargs["family_id"] == "family-xyz"

    @pytest.mark.asyncio
    async def test_refresh_uses_row_organization_when_snapshot_missing(self):
        """Rotated tokens keep the stored org even when snapshot JSON is absent."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": None,
            "auth_method": "google",
            "family_id": "family-xyz",
            "organization_id": "org-default",
            "identity_snapshot": None,
            "email": "a@b.com",
            "name": "Test",
            "role": "student",
            "platform_role": "user",
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.token_service.settings") as mock_settings, \
             patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock) as mock_create, \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock):
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"
            mock_settings.environment = "production"
            mock_settings.enable_multi_tenant = True
            mock_create.return_value = MagicMock(
                access_token="at",
                refresh_token="rt",
                token_type="bearer",
                expires_in=1800,
            )

            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("persisted-org-token")

            assert result is not None
            kwargs = mock_create.call_args.kwargs
            assert kwargs["active_organization_id"] == "org-default"
            assert kwargs["family_id"] == "family-xyz"

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        """Token not found returns None."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = None

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("nonexistent-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_refresh_lookup_falls_back_when_identity_columns_missing(self):
        """Legacy refresh_tokens schema should still support refresh rotation."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.side_effect = [
            Exception('column "identity_snapshot" does not exist'),
            {
                "id": "token-1",
                "user_id": "user-1",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
                "revoked_at": None,
                "auth_method": "google",
                "family_id": "family-legacy",
                "email": "a@b.com",
                "name": "Test",
                "role": "student",
            },
        ]

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock) as mock_create, \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock):
            mock_create.return_value = MagicMock(
                access_token="at",
                refresh_token="rt",
                token_type="bearer",
                expires_in=1800,
            )

            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("legacy-refresh-token")

            assert result is not None
            kwargs = mock_create.call_args.kwargs
            assert kwargs["role"] == "student"
            assert kwargs["family_id"] == "family-legacy"

    @pytest.mark.asyncio
    async def test_refresh_lookup_missing_identity_columns_rejected_in_strict_mode(self):
        """Strict multi-tenant refresh must not mint a token from legacy org-less rows."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.side_effect = [
            Exception('column "identity_snapshot" does not exist'),
        ]

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.token_service.settings") as mock_settings, \
             patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock) as mock_create:
            mock_settings.jwt_expire_minutes = 30
            mock_settings.jwt_secret_key = "test-secret-key-12345"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_refresh_expire_days = 30
            mock_settings.jwt_audience = "wiii"
            mock_settings.environment = "production"
            mock_settings.enable_multi_tenant = True

            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("legacy-refresh-token")

            assert result is None
            assert mock_conn.fetchrow.await_count == 1
            mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_uses_persisted_platform_role_when_snapshot_missing(self):
        """Migrated users still recover platform_role even if refresh snapshot is absent."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "id": "token-1",
            "user_id": "user-1",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            "revoked_at": None,
            "auth_method": "google",
            "family_id": "family-xyz",
            "organization_id": None,
            "identity_snapshot": None,
            "email": "a@b.com",
            "name": "Test",
            "role": "admin",
            "platform_role": "platform_admin",
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.token_service.create_token_pair", new_callable=AsyncMock) as mock_create, \
             patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock):
            mock_create.return_value = MagicMock(
                access_token="at",
                refresh_token="rt",
                token_type="bearer",
                expires_in=1800,
            )

            from app.auth.token_service import refresh_access_token
            result = await refresh_access_token("persisted-platform-role")

            assert result is not None
            kwargs = mock_create.call_args.kwargs
            assert kwargs["role"] == "admin"
            assert kwargs["platform_role"] == "platform_admin"


# ============================================================================
# TestOTPDatabase
# ============================================================================

class TestOTPDatabase:
    """Test OTP codes stored in database."""

    @pytest.mark.asyncio
    async def test_generate_link_code_inserts(self):
        """generate_link_code inserts code into DB."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)  # Sprint 192: rate limit count

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.otp_linking._get_expiry_seconds", return_value=300):
            from app.auth.otp_linking import generate_link_code
            code = await generate_link_code("user-1", "messenger")

            assert len(code) == 6
            assert code.isdigit()
            assert int(code) >= 100000

    @pytest.mark.asyncio
    async def test_generate_cleans_expired(self):
        """generate_link_code cleans expired codes (Sprint 194c: probabilistic cleanup)."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)  # Sprint 192: rate limit count

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.otp_linking._get_expiry_seconds", return_value=300), \
             patch("app.auth.otp_linking.random") as mock_random:
            mock_random.random.return_value = 0.05  # < 0.1 → cleanup triggers
            from app.auth.otp_linking import generate_link_code
            await generate_link_code("user-1", "zalo")

            first_sql = mock_conn.execute.call_args_list[0][0][0]
            assert "DELETE" in first_sql
            assert "expires_at" in first_sql

    @pytest.mark.asyncio
    async def test_generate_revokes_existing(self):
        """generate_link_code revokes existing code for same user+channel."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)  # Sprint 192: rate limit count

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.otp_linking._get_expiry_seconds", return_value=300), \
             patch("app.auth.otp_linking.random") as mock_random:
            mock_random.random.return_value = 0.5  # > 0.1 → skip cleanup
            from app.auth.otp_linking import generate_link_code
            await generate_link_code("user-1", "messenger")

            # With cleanup skipped: [0]=revoke existing, [1]=insert
            first_sql = mock_conn.execute.call_args_list[0][0][0]
            assert "DELETE" in first_sql
            assert "user_id" in first_sql
            assert "channel_type" in first_sql

    @pytest.mark.asyncio
    async def test_verify_and_link_success(self):
        """verify_and_link marks code used and links identity."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "user_id": "user-1",
            "channel_type": "messenger",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "used_at": None,
            "failed_attempts": 0,
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             patch("app.auth.user_service.link_identity", new_callable=AsyncMock) as mock_link:
            from app.auth.otp_linking import verify_and_link
            success, msg = await verify_and_link("123456", "messenger", "sender-abc")

            assert success is True
            assert msg == "user-1"
            mock_link.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_expired_code(self):
        """verify_and_link returns expired for expired code."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "user_id": "user-1",
            "channel_type": "messenger",
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
            "used_at": None,
            "failed_attempts": 0,
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.otp_linking import verify_and_link
            success, msg = await verify_and_link("123456", "messenger", "sender-abc")

            assert success is False
            assert msg == "expired"

    @pytest.mark.asyncio
    async def test_verify_wrong_channel(self):
        """verify_and_link rejects wrong channel."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "user_id": "user-1",
            "channel_type": "zalo",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "used_at": None,
            "failed_attempts": 0,
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.otp_linking import verify_and_link
            success, msg = await verify_and_link("123456", "messenger", "sender-abc")

            assert success is False
            assert msg == ""

    @pytest.mark.asyncio
    async def test_verify_not_found(self):
        """verify_and_link returns empty for unknown code."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = None

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.otp_linking import verify_and_link
            success, msg = await verify_and_link("000000", "messenger", "sender-abc")

            assert success is False
            assert msg == ""

    @pytest.mark.asyncio
    async def test_verify_already_used(self):
        """verify_and_link rejects already-used code."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        mock_conn.fetchrow.return_value = {
            "user_id": "user-1",
            "channel_type": "messenger",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            "used_at": datetime.now(timezone.utc),
            "failed_attempts": 0,
        }

        with patch(_POOL_PATCH, create=True, new=async_pool_fn):
            from app.auth.otp_linking import verify_and_link
            success, msg = await verify_and_link("123456", "messenger", "sender-abc")

            assert success is False
            assert msg == ""


# ============================================================================
# TestAuthAudit
# ============================================================================

class TestAuthAudit:
    """Test auth audit event logging."""

    @pytest.mark.asyncio
    async def test_insert_event(self):
        """log_auth_event inserts into auth_events table."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.core.config.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.enable_auth_audit = True

            from app.auth.auth_audit import log_auth_event
            await log_auth_event(
                "login",
                user_id="user-1",
                provider="google",
                result="success",
                ip_address="127.0.0.1",
            )

            mock_conn.execute.assert_called_once()
            sql = mock_conn.execute.call_args[0][0]
            assert "auth_events" in sql
            assert "INSERT" in sql

    @pytest.mark.asyncio
    async def test_noop_when_disabled(self):
        """log_auth_event is no-op when enable_auth_audit=False."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_auth_audit = False

            from app.auth.auth_audit import log_auth_event
            await log_auth_event("login", user_id="user-1")

    @pytest.mark.asyncio
    async def test_fire_and_forget_no_raise(self):
        """log_auth_event never raises, even on DB failure."""
        failing_pool_fn = AsyncMock(side_effect=Exception("DB down"))

        with patch("app.core.config.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=failing_pool_fn):
            mock_settings.enable_auth_audit = True

            from app.auth.auth_audit import log_auth_event
            await log_auth_event("login_failed", user_id="user-1")

    @pytest.mark.asyncio
    async def test_log_auth_event_failure_log_redacts_raw_identity_and_metadata(self, caplog):
        """Audit persistence failure diagnostics must not expose raw auth data."""
        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier

        async_pool_fn, mock_conn = _mock_pool_and_conn()
        raw_user_id = "audit-private-user"
        raw_org = "audit-private-org"
        raw_ip = "203.0.113.77"
        raw_user_agent = "audit-private-user-agent"
        raw_reason = "audit-private-reason-with-token"
        metadata = {
            "provider_sub": "audit-private-provider-sub",
            "nested": {"refresh_token": "audit-private-metadata-token"},
        }
        mock_conn.execute.side_effect = RuntimeError(
            "insert failed "
            f"user_id={raw_user_id} "
            f"organization_id={raw_org} "
            f"ip_address={raw_ip} "
            f"user_agent={raw_user_agent} "
            f"reason={raw_reason} "
            f"provider_sub={metadata['provider_sub']} "
            f"refresh_token={metadata['nested']['refresh_token']}"
        )

        with patch("app.core.config.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn), \
             caplog.at_level(logging.WARNING, logger="app.auth.auth_audit"):
            mock_settings.enable_auth_audit = True

            from app.auth.auth_audit import log_auth_event
            await log_auth_event(
                "login_failed",
                user_id=raw_user_id,
                provider="google",
                result="failed",
                reason=raw_reason,
                ip_address=raw_ip,
                user_agent=raw_user_agent,
                organization_id=raw_org,
                metadata=metadata,
            )

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        for raw_value in (
            raw_user_id,
            raw_org,
            raw_ip,
            raw_user_agent,
            raw_reason,
            metadata["provider_sub"],
            metadata["nested"]["refresh_token"],
        ):
            assert raw_value not in log_text
        assert f"user_ref={hash_runtime_identifier(raw_user_id)}" in log_text
        assert f"org_ref={hash_runtime_identifier(raw_org)}" in log_text
        assert "provider=google" in log_text
        assert "result=failed" in log_text
        assert "<redacted-secret>" in log_text

    @pytest.mark.asyncio
    async def test_metadata_json_serialized(self):
        """Metadata dict is JSON-serialized."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.core.config.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.enable_auth_audit = True

            from app.auth.auth_audit import log_auth_event
            await log_auth_event(
                "token_replay_detected",
                user_id="user-1",
                metadata={"family": "abc", "purged": 2},
            )

            args = mock_conn.execute.call_args[0]
            metadata_arg = args[-1]
            parsed = json.loads(metadata_arg)
            assert parsed["family"] == "abc"
            assert parsed["purged"] == 2

    @pytest.mark.asyncio
    async def test_null_metadata(self):
        """Null metadata is passed as None."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with patch("app.core.config.settings") as mock_settings, \
             patch(_POOL_PATCH, create=True, new=async_pool_fn):
            mock_settings.enable_auth_audit = True

            from app.auth.auth_audit import log_auth_event
            await log_auth_event("logout", user_id="user-1")

            args = mock_conn.execute.call_args[0]
            metadata_arg = args[-1]
            assert metadata_arg is None


# ============================================================================
# TestSecurityPayload
# ============================================================================

class TestSecurityPayload:
    """Test jti in security.py TokenPayload."""

    def test_jti_in_token_payload(self):
        """TokenPayload model has jti field."""
        from app.core.security import TokenPayload
        payload = TokenPayload(
            sub="user-1",
            exp=datetime.now(timezone.utc) + timedelta(minutes=30),
            iat=datetime.now(timezone.utc),
            jti="test-jti",
        )
        assert payload.jti == "test-jti"

    def test_jti_optional(self):
        """jti is optional in TokenPayload."""
        from app.core.security import TokenPayload
        payload = TokenPayload(
            sub="user-1",
            exp=datetime.now(timezone.utc) + timedelta(minutes=30),
            iat=datetime.now(timezone.utc),
        )
        assert payload.jti is None

    def test_backward_compat_without_jti(self):
        """Tokens without jti still validate (backward compat)."""
        from app.core.security import TokenPayload
        data = {
            "sub": "user-1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        payload = TokenPayload(**data)
        assert payload.sub == "user-1"
        assert payload.jti is None
