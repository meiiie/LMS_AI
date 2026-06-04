"""
Sprint 178 Phase 2: Feature Flag Service + Analytics API Tests

Covers:
1. Feature flag service (app/services/feature_flag_service.py)
2. Feature flag API handlers (admin_flag_toggle, admin_flag_delete)
3. LLM usage logger (app/services/llm_usage_logger.py)
4. Analytics overview handler (analytics_overview)
5. LLM usage analytics handler (analytics_llm_usage)
6. User analytics handler (analytics_users)

Note: Admin routes (/admin/feature-flags/*, /admin/analytics/*) are only
registered when enable_admin_module=True at app startup. Since tests run
with enable_admin_module=False (default), API tests call handler functions
directly — the same pattern used in test_sprint178_admin_foundation.py.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# get_asyncpg_pool is a lazy import inside function bodies;
# use create=True so patch can create the attribute for the test.
_POOL_PATCH = "app.core.database.get_asyncpg_pool"


def _mock_pool_and_conn():
    """Create standard mock pool + connection for async DB tests.

    Returns (async_pool_fn, mock_conn) where async_pool_fn is an AsyncMock
    that when awaited returns a pool with a working acquire() context manager.
    """
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    acm = AsyncMock()
    acm.__aenter__ = AsyncMock(return_value=mock_conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = acm
    async_pool_fn = AsyncMock(return_value=mock_pool)
    return async_pool_fn, mock_conn


def _reset_ffs_cache():
    """Reset the module-level cache in feature_flag_service."""
    import app.services.feature_flag_service as ffs
    ffs._cache.clear()
    ffs._cache_ts = 0.0


# ---------------------------------------------------------------------------
# Shared auth user fixtures
# ---------------------------------------------------------------------------

from app.core.security import AuthenticatedUser

_ADMIN_USER = AuthenticatedUser(
    user_id="admin-1",
    auth_method="api_key",
    role="admin",
    organization_id="org-active",
)
_ADMIN_NO_ORG_USER = AuthenticatedUser(
    user_id="admin-1",
    auth_method="api_key",
    role="admin",
)
_ADMIN_ORG_USER = AuthenticatedUser(
    user_id="admin-1",
    auth_method="api_key",
    role="admin",
    organization_id="org-active",
)
_STUDENT_USER = AuthenticatedUser(user_id="student-1", auth_method="api_key", role="student")


# =============================================================================
# TestFeatureFlagService (12 tests)
# =============================================================================


class TestFeatureFlagService:
    """Tests for app/services/feature_flag_service.py."""

    @pytest.mark.asyncio
    async def test_get_config_default(self):
        """Returns config.py value when no DB override exists."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # DB returns no rows → empty cache → falls back to config.py
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import get_flag
            from app.core.config import settings

            result = await get_flag("enable_neo4j")

        assert result == getattr(settings, "enable_neo4j", False)

    @pytest.mark.asyncio
    async def test_get_db_override(self):
        """Returns DB value when a global override exists."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetch.return_value = [
            {
                "key": "enable_neo4j",
                "value": True,
                "flag_type": "release",
                "description": None,
                "owner": None,
                "organization_id": None,
                "expires_at": None,
            }
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import get_flag
            result = await get_flag("enable_neo4j")

        assert result is True

    @pytest.mark.asyncio
    async def test_org_override_precedence(self):
        """Org-specific override beats global override."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # Two rows: global (False) and org-specific (True)
        mock_conn.fetch.return_value = [
            {
                "key": "enable_neo4j",
                "value": False,
                "flag_type": "release",
                "description": None,
                "owner": None,
                "organization_id": None,
                "expires_at": None,
            },
            {
                "key": "enable_neo4j",
                "value": True,
                "flag_type": "release",
                "description": None,
                "owner": None,
                "organization_id": "org-special",
                "expires_at": None,
            },
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import get_flag
            result = await get_flag("enable_neo4j", org_id="org-special")

        # org-specific override (True) wins over global (False)
        assert result is True

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Second call uses cache — no additional DB query.

        Note: _is_cache_valid() checks bool(_cache) AND time, so the cache
        must be non-empty after the first load for the second call to be a
        genuine cache hit. We return a real DB row to populate the cache.
        """
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # Return a real row so _cache is non-empty after the first fetch
        mock_conn.fetch.return_value = [
            {
                "key": "enable_neo4j",
                "value": False,
                "flag_type": "release",
                "description": None,
                "owner": None,
                "organization_id": None,
                "expires_at": None,
            }
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import get_flag
            await get_flag("enable_neo4j")
            await get_flag("enable_neo4j")

        # fetch called once (cache hit on second call)
        assert mock_conn.fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expired(self):
        """Re-fetches from DB after TTL expires."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # Return a real row so cache is non-empty
        mock_conn.fetch.return_value = [
            {
                "key": "enable_neo4j",
                "value": False,
                "flag_type": "release",
                "description": None,
                "owner": None,
                "organization_id": None,
                "expires_at": None,
            }
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            import app.services.feature_flag_service as ffs
            from app.services.feature_flag_service import get_flag

            await get_flag("enable_neo4j")
            # Simulate cache expiry by setting timestamp far in the past
            ffs._cache_ts = time.monotonic() - 999.0
            await get_flag("enable_neo4j")

        # fetch called twice — expired cache triggers re-fetch
        assert mock_conn.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_set_creates_record(self):
        """set_flag UPSERT inserts a new record and returns dict."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "key": "enable_neo4j",
            "value": True,
            "flag_type": "release",
            "description": "test desc",
            "owner": "admin-1",
            "organization_id": None,
            "expires_at": None,
            "created_at": None,
            "updated_at": None,
        }

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import set_flag
            result = await set_flag("enable_neo4j", True, owner="admin-1", description="test desc")

        assert result["key"] == "enable_neo4j"
        assert result["value"] is True
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_updates(self):
        """set_flag UPSERT updates existing record via ON CONFLICT clause."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "key": "enable_neo4j",
            "value": False,
            "flag_type": "release",
            "description": None,
            "owner": None,
            "organization_id": None,
            "expires_at": None,
            "created_at": None,
            "updated_at": None,
        }

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import set_flag
            result = await set_flag("enable_neo4j", False)

        assert result["value"] is False
        # Verify ON CONFLICT path — fetchrow uses UPSERT SQL
        query_str = mock_conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in query_str

    @pytest.mark.asyncio
    async def test_delete_removes(self):
        """delete_flag returns True when a row was deleted."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.execute.return_value = "DELETE 1"

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import delete_flag
            result = await delete_flag("enable_neo4j")

        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """delete_flag returns False when no row was deleted."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.execute.return_value = "DELETE 0"

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import delete_flag
            result = await delete_flag("enable_neo4j")

        assert result is False

    def test_invalidate_cache(self):
        """invalidate_cache clears the module-level cache."""
        import app.services.feature_flag_service as ffs
        ffs._cache = {"enable_neo4j:": {"value": True}}
        ffs._cache_ts = time.monotonic()

        from app.services.feature_flag_service import invalidate_cache
        invalidate_cache()

        assert ffs._cache == {}
        assert ffs._cache_ts == 0.0

    @pytest.mark.asyncio
    async def test_list_merges(self):
        """list_all_flags merges config.py defaults with DB overrides."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # DB returns one override for enable_neo4j
        mock_conn.fetch.return_value = [
            {
                "key": "enable_neo4j",
                "value": True,
                "flag_type": "release",
                "description": "db override",
                "owner": "admin",
                "organization_id": None,
                "expires_at": None,
            }
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import list_all_flags
            flags = await list_all_flags()

        # Result should be a list of dicts
        assert isinstance(flags, list)
        # neo4j flag should exist with db_override source
        neo4j_flag = next((f for f in flags if f["key"] == "enable_neo4j"), None)
        assert neo4j_flag is not None
        assert neo4j_flag["value"] is True
        assert neo4j_flag["source"] == "db_override"

    @pytest.mark.asyncio
    async def test_expired_fallback(self):
        """Expired DB flags (expires_at in past) are skipped."""
        _reset_ffs_cache()
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # Row with expires_at in the past — should be ignored by _load_db_flags
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_conn.fetch.return_value = [
            {
                "key": "enable_neo4j",
                "value": True,
                "flag_type": "release",
                "description": None,
                "owner": None,
                "organization_id": None,
                "expires_at": past,
            }
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.services.feature_flag_service import get_flag
            from app.core.config import settings
            result = await get_flag("enable_neo4j")

        # Expired flag is skipped → falls back to config.py default
        assert result == getattr(settings, "enable_neo4j", False)


# =============================================================================
# TestFeatureFlagAPI (7 tests)
#
# Routes /admin/feature-flags/* are only registered when enable_admin_module=True
# at startup. Tests call handler functions directly (same pattern as foundation).
# =============================================================================


class TestFeatureFlagAPI:
    """Tests for admin_flag_toggle / admin_flag_delete handlers."""

    def _make_fake_request(self, method="PATCH", path="/admin/feature-flags/enable_neo4j"):
        """Build a minimal fake Request for audit context extraction."""
        req = MagicMock()
        req.method = method
        req.url.path = path
        req.client.host = "127.0.0.1"
        req.headers.get = MagicMock(return_value=None)
        return req

    @pytest.mark.asyncio
    async def test_patch_creates(self):
        """admin_flag_toggle calls set_flag and returns the saved record."""
        _reset_ffs_cache()
        saved_record = {
            "key": "enable_neo4j",
            "value": True,
            "flag_type": "release",
            "description": None,
            "owner": None,
            "organization_id": None,
            "expires_at": None,
        }

        with (
            patch("app.api.v1.admin_feature_flags.settings") as mock_settings,
            patch("app.services.feature_flag_service.set_flag", new=AsyncMock(return_value=saved_record)),
            patch("app.services.admin_audit.log_admin_action", new=AsyncMock()),
        ):
            mock_settings.enable_admin_module = True
            mock_settings.enable_neo4j = False  # exists on settings

            from app.api.v1.admin_feature_flags import admin_flag_toggle, FlagUpdateBody

            body = FlagUpdateBody(value=True)
            result = await admin_flag_toggle(
                key="enable_neo4j",
                body=body,
                request=self._make_fake_request(),
                auth=_ADMIN_USER,
            )

        assert result["key"] == "enable_neo4j"
        assert result["value"] is True

    @pytest.mark.asyncio
    async def test_patch_audits(self):
        """admin_flag_toggle calls log_admin_action with action=flag.toggle."""
        _reset_ffs_cache()
        audit_mock = AsyncMock()
        saved_record = {
            "key": "enable_neo4j",
            "value": False,
            "flag_type": "release",
            "description": None,
            "owner": None,
            "organization_id": None,
            "expires_at": None,
        }

        with (
            patch("app.api.v1.admin_feature_flags.settings") as mock_settings,
            patch("app.services.feature_flag_service.set_flag", new=AsyncMock(return_value=saved_record)),
            patch("app.services.admin_audit.log_admin_action", new=audit_mock),
        ):
            mock_settings.enable_admin_module = True
            mock_settings.enable_neo4j = False

            from app.api.v1.admin_feature_flags import admin_flag_toggle, FlagUpdateBody

            body = FlagUpdateBody(value=False)
            await admin_flag_toggle(
                key="enable_neo4j",
                body=body,
                request=self._make_fake_request(),
                auth=_ADMIN_USER,
            )

        audit_mock.assert_called_once()
        call_kwargs = audit_mock.call_args.kwargs
        assert call_kwargs.get("action") == "flag.toggle"

    @pytest.mark.asyncio
    async def test_patch_validates_key(self):
        """admin_flag_toggle raises HTTPException 400 for unknown flag key."""
        from fastapi import HTTPException

        with patch("app.api.v1.admin_feature_flags.settings") as mock_settings:
            mock_settings.enable_admin_module = True
            # Flag does NOT exist on mock settings
            del mock_settings.totally_nonexistent_flag_xyz_123

            from app.api.v1.admin_feature_flags import admin_flag_toggle, FlagUpdateBody

            body = FlagUpdateBody(value=True)
            with pytest.raises(HTTPException) as exc_info:
                await admin_flag_toggle(
                    key="totally_nonexistent_flag_xyz_123",
                    body=body,
                    request=self._make_fake_request(),
                    auth=_ADMIN_USER,
                )

        assert exc_info.value.status_code == 400
        assert "Unknown flag key" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_patch_requires_admin(self):
        """admin_flag_delete raises HTTPException 403 for non-admin users.

        The RequireAdmin dependency enforces this; we simulate the 403 by
        invoking the underlying _require_admin dependency directly.
        """
        from fastapi import HTTPException
        from app.api.deps import _require_admin

        with pytest.raises(HTTPException) as exc_info:
            await _require_admin(auth=_STUDENT_USER)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_removes(self):
        """admin_flag_delete returns {'deleted': True, 'key': ...} on success."""
        _reset_ffs_cache()

        with (
            patch("app.services.feature_flag_service.delete_flag", new=AsyncMock(return_value=True)),
            patch("app.services.admin_audit.log_admin_action", new=AsyncMock()),
        ):
            from app.api.v1.admin_feature_flags import admin_flag_delete

            result = await admin_flag_delete(
                key="enable_neo4j",
                request=self._make_fake_request(method="DELETE"),
                auth=_ADMIN_USER,
                organization_id=None,
            )

        assert result["deleted"] is True
        assert result["key"] == "enable_neo4j"

    @pytest.mark.asyncio
    async def test_delete_audits(self):
        """admin_flag_delete calls log_admin_action with action=flag.delete."""
        _reset_ffs_cache()
        audit_mock = AsyncMock()

        with (
            patch("app.services.feature_flag_service.delete_flag", new=AsyncMock(return_value=True)),
            patch("app.services.admin_audit.log_admin_action", new=audit_mock),
        ):
            from app.api.v1.admin_feature_flags import admin_flag_delete

            await admin_flag_delete(
                key="enable_neo4j",
                request=self._make_fake_request(method="DELETE"),
                auth=_ADMIN_USER,
                organization_id=None,
            )

        audit_mock.assert_called_once()
        call_kwargs = audit_mock.call_args.kwargs
        assert call_kwargs.get("action") == "flag.delete"

    @pytest.mark.asyncio
    async def test_delete_404(self):
        """admin_flag_delete raises HTTPException 404 when no override exists."""
        from fastapi import HTTPException

        with patch("app.services.feature_flag_service.delete_flag", new=AsyncMock(return_value=False)):
            from app.api.v1.admin_feature_flags import admin_flag_delete

            with pytest.raises(HTTPException) as exc_info:
                await admin_flag_delete(
                    key="enable_neo4j",
                    request=self._make_fake_request(method="DELETE"),
                    auth=_ADMIN_USER,
                    organization_id=None,
                )

        assert exc_info.value.status_code == 404


# =============================================================================
# TestLLMUsageLogger (4 tests)
# =============================================================================


class TestLLMUsageLogger:
    """Tests for app/services/llm_usage_logger.py."""

    @pytest.mark.asyncio
    async def test_log_single(self):
        """log_llm_usage inserts a single row when feature is enabled."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.execute.return_value = None

        with (
            patch("app.core.config.settings.enable_admin_module", True),
            patch(_POOL_PATCH, async_pool_fn, create=True),
        ):
            from app.services.llm_usage_logger import log_llm_usage
            await log_llm_usage(
                request_id="req-1",
                user_id="user-1",
                session_id="sess-1",
                model="gemini-3.1-flash-lite-preview",
                provider="google",
                tier="moderate",
                input_tokens=100,
                output_tokens=200,
                duration_ms=350.0,
                estimated_cost_usd=0.0001,
                component="tutor_node",
            )

        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "llm_usage_log" in sql

    @pytest.mark.asyncio
    async def test_log_batch(self):
        """log_llm_usage_batch inserts multiple rows via executemany."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.executemany.return_value = None

        calls = [
            {
                "model": "gemini-3.1-flash-lite-preview", "provider": "google", "tier": "moderate",
                "component": "rag", "input_tokens": 100, "output_tokens": 200,
                "duration_ms": 300.0, "estimated_cost_usd": 0.0001,
            },
            {
                "model": "gemini-3.1-flash-lite-preview", "provider": "google", "tier": "deep",
                "component": "tutor", "input_tokens": 300, "output_tokens": 400,
                "duration_ms": 600.0, "estimated_cost_usd": 0.0003,
            },
        ]

        with (
            patch("app.core.config.settings.enable_admin_module", True),
            patch(_POOL_PATCH, async_pool_fn, create=True),
        ):
            from app.services.llm_usage_logger import log_llm_usage_batch
            await log_llm_usage_batch(
                request_id="req-batch",
                user_id="user-1",
                session_id="sess-1",
                calls=calls,
            )

        mock_conn.executemany.assert_called_once()
        _, records = mock_conn.executemany.call_args[0]
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_log_batch_accepts_dataclass_calls(self):
        """log_llm_usage_batch accepts TokenTracker LLMCall dataclasses too."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.executemany.return_value = None

        from app.core.token_tracker import LLMCall

        calls = [
            LLMCall(
                model="qwen/qwen3.6-plus:free",
                tier="openrouter_light",
                input_tokens=80,
                output_tokens=24,
                duration_ms=123.0,
                component="supervisor",
            )
        ]

        with (
            patch("app.core.config.settings.enable_admin_module", True),
            patch(_POOL_PATCH, async_pool_fn, create=True),
        ):
            from app.services.llm_usage_logger import log_llm_usage_batch
            await log_llm_usage_batch(
                request_id="req-dataclass",
                user_id="user-1",
                session_id="sess-1",
                calls=calls,
            )

        mock_conn.executemany.assert_called_once()
        _, records = mock_conn.executemany.call_args[0]
        assert records[0][4] == "qwen/qwen3.6-plus:free"
        assert records[0][5] == "openrouter"
        assert records[0][6] == "light"

    @pytest.mark.asyncio
    async def test_never_raises(self):
        """Exception in DB does not propagate — function swallows errors."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.execute.side_effect = RuntimeError("DB exploded")

        with (
            patch("app.core.config.settings.enable_admin_module", True),
            patch(_POOL_PATCH, async_pool_fn, create=True),
        ):
            from app.services.llm_usage_logger import log_llm_usage
            # Must not raise even when DB errors out
            await log_llm_usage(
                request_id="req-err",
                user_id="u",
                session_id="s",
                model="m",
                provider="google",
                tier="light",
                input_tokens=10,
                output_tokens=20,
            )

    @pytest.mark.asyncio
    async def test_noop_disabled(self):
        """No DB call when enable_admin_module=False."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()

        with (
            patch("app.core.config.settings.enable_admin_module", False),
            patch(_POOL_PATCH, async_pool_fn, create=True),
        ):
            from app.services.llm_usage_logger import log_llm_usage
            await log_llm_usage(
                request_id="req-noop",
                user_id="u",
                session_id="s",
                model="m",
                provider="google",
                tier="light",
                input_tokens=10,
                output_tokens=20,
            )

        # Pool should never have been acquired
        mock_conn.execute.assert_not_called()


# =============================================================================
# TestAnalyticsOverview (5 tests)
#
# Calls analytics_overview() handler directly (routes not registered at test time).
# =============================================================================


class TestAnalyticsOverview:
    """Tests for analytics_overview handler."""

    @pytest.mark.asyncio
    async def test_returns_daily(self):
        """Returns daily_active_users, chat_volume, error_rate arrays."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            result = await analytics_overview(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        assert "daily_active_users" in result
        assert "chat_volume" in result
        assert "error_rate" in result
        assert isinstance(result["daily_active_users"], list)

    @pytest.mark.asyncio
    async def test_date_range(self):
        """Respects from_date/to_date params in response metadata."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            result = await analytics_overview(
                auth=_ADMIN_USER,
                from_date="2026-01-01",
                to_date="2026-01-31",
                org_id=None,
            )

        assert result["period_start"] == "2026-01-01"
        assert result["period_end"] == "2026-01-31"

    @pytest.mark.asyncio
    async def test_org_filter(self):
        """org_id is passed as a SQL parameter to the DB queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            await analytics_overview(
                auth=AuthenticatedUser(
                    user_id="admin-1",
                    auth_method="api_key",
                    role="admin",
                    organization_id="lms-hang-hai",
                ),
                from_date=None,
                to_date=None,
                org_id="lms-hang-hai",
            )

        # org_id should appear in at least one fetch call's arguments
        all_call_str = str(mock_conn.fetch.call_args_list)
        assert "lms-hang-hai" in all_call_str

    @pytest.mark.asyncio
    async def test_multi_tenant_defaults_to_active_org_scope(self, monkeypatch):
        """Multi-tenant overview analytics use active org before querying."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            result = await analytics_overview(
                auth=_ADMIN_ORG_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        all_call_str = str(mock_conn.fetch.call_args_list)
        assert "org-active" in all_call_str
        assert result["scope"] == {
            "org_scoped": True,
            "org_filter_applied": True,
            "identifier_strategy": "active_org_id_not_echoed",
        }
        assert "org-active" not in str(result)

    @pytest.mark.asyncio
    async def test_multi_tenant_requires_active_org_before_db(self, monkeypatch):
        """Missing active org fails closed before opening the pool."""
        from fastapi import HTTPException
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        async_pool_fn = AsyncMock()

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            with pytest.raises(HTTPException) as exc_info:
                await analytics_overview(
                    auth=_ADMIN_NO_ORG_USER,
                    from_date=None,
                    to_date=None,
                    org_id=None,
                )

        assert exc_info.value.status_code == 403
        async_pool_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_tenant_rejects_mismatched_org_before_db(self, monkeypatch):
        """Requested org_id cannot override the authenticated active org."""
        from fastapi import HTTPException
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        async_pool_fn = AsyncMock()

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            with pytest.raises(HTTPException) as exc_info:
                await analytics_overview(
                    auth=_ADMIN_ORG_USER,
                    from_date=None,
                    to_date=None,
                    org_id="org-other",
                )

        assert exc_info.value.status_code == 403
        async_pool_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_admin(self):
        """_require_admin dep raises 403 for non-admin, guarding the endpoint."""
        from fastapi import HTTPException
        from app.api.deps import _require_admin

        with pytest.raises(HTTPException) as exc_info:
            await _require_admin(auth=_STUDENT_USER)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_empty(self):
        """Returns empty arrays when no data in DB."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_overview
            result = await analytics_overview(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        assert result["daily_active_users"] == []
        assert result["chat_volume"] == []
        assert result["error_rate"] == []


# =============================================================================
# TestLLMUsageAnalytics (5 tests)
# =============================================================================


class TestLLMUsageAnalytics:
    """Tests for analytics_llm_usage handler."""

    @pytest.mark.asyncio
    async def test_total_tokens(self):
        """Returns total_tokens, total_cost_usd, total_requests."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "total_tokens": 500000,
            "total_cost": 2.50,
            "total_requests": 1200,
        }
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_llm_usage
            result = await analytics_llm_usage(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
                model=None,
                group_by="day",
            )

        assert result["total_tokens"] == 500000
        assert result["total_cost_usd"] == 2.50
        assert result["total_requests"] == 1200

    @pytest.mark.asyncio
    async def test_multi_tenant_llm_usage_uses_active_org_scope(self, monkeypatch):
        """LLM usage analytics bind active org and do not echo it in response."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "total_tokens": 10,
            "total_cost": 0.01,
            "total_requests": 1,
        }
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_llm_usage
            result = await analytics_llm_usage(
                auth=_ADMIN_ORG_USER,
                from_date=None,
                to_date=None,
                org_id=None,
                model=None,
                group_by="day",
            )

        assert "org-active" in str(mock_conn.fetchrow.call_args_list)
        assert result["scope"]["org_scoped"] is True
        assert "org-active" not in str(result)

    @pytest.mark.asyncio
    async def test_group_by_model(self):
        """group_by='model' returns breakdown entries keyed by model name."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "total_tokens": 100,
            "total_cost": 0.01,
            "total_requests": 2,
        }
        mock_conn.fetch.return_value = [
            {"group_key": "gemini-3.1-flash-lite-preview", "tokens": 80, "cost": 0.008, "requests": 1},
            {"group_key": "gpt-4o", "tokens": 20, "cost": 0.002, "requests": 1},
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_llm_usage
            result = await analytics_llm_usage(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
                model=None,
                group_by="model",
            )

        assert "breakdown" in result
        assert isinstance(result["breakdown"], list)

    @pytest.mark.asyncio
    async def test_group_by_org(self):
        """group_by='org' groups breakdown by organization_id."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "total_tokens": 200,
            "total_cost": 0.02,
            "total_requests": 3,
        }
        mock_conn.fetch.return_value = [
            {"group_key": "lms-hang-hai", "tokens": 150, "cost": 0.015, "requests": 2},
            {"group_key": None, "tokens": 50, "cost": 0.005, "requests": 1},
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_llm_usage
            result = await analytics_llm_usage(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
                model=None,
                group_by="org",
            )

        assert "breakdown" in result

    @pytest.mark.asyncio
    async def test_top_users(self):
        """Returns top_users list populated from DB."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "total_tokens": 0,
            "total_cost": 0,
            "total_requests": 0,
        }
        # fetch called three times: breakdown, top_models, top_users
        mock_conn.fetch.side_effect = [
            [],  # breakdown
            [{"model": "gemini-3.1-flash-lite-preview", "tokens": 100, "requests": 5}],  # top_models
            [{"user_id": "u1", "tokens": 80, "requests": 3}],  # top_users
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_llm_usage
            result = await analytics_llm_usage(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
                model=None,
                group_by="day",
            )

        assert "top_users" in result
        assert isinstance(result["top_users"], list)
        assert result["top_users"][0]["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_date_range(self):
        """from_date/to_date are passed as positional params to fetchrow."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow.return_value = {
            "total_tokens": 0,
            "total_cost": 0,
            "total_requests": 0,
        }
        mock_conn.fetch.return_value = []

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_llm_usage
            await analytics_llm_usage(
                auth=_ADMIN_USER,
                from_date="2026-02-01",
                to_date="2026-02-28",
                org_id=None,
                model=None,
                group_by="day",
            )

        fetchrow_call = mock_conn.fetchrow.call_args
        # Date params are positional args after the SQL string
        call_params = fetchrow_call[0][1:]
        assert datetime(2026, 2, 1, tzinfo=timezone.utc) in call_params
        assert datetime(2026, 2, 28, 23, 59, 59, 999999, tzinfo=timezone.utc) in call_params


# =============================================================================
# TestUserAnalytics (4 tests)
# =============================================================================


class TestUserAnalytics:
    """Tests for analytics_users handler."""

    @pytest.mark.asyncio
    async def test_growth_curve(self):
        """Returns user_growth array with date/new_users entries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        # fetchval calls: total_users, new_users, active_users
        mock_conn.fetchval.side_effect = [50, 10, 8]
        mock_conn.fetch.side_effect = [
            [{"date": "2026-02-20", "new_users": 3}, {"date": "2026-02-21", "new_users": 7}],
            [{"role": "student", "count": 40}, {"role": "teacher", "count": 10}],
            [{"platform_role": "user", "count": 50}],
            [],  # top_active
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_users
            result = await analytics_users(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        assert "user_growth" in result
        assert len(result["user_growth"]) == 2
        assert result["user_growth"][0]["date"] == "2026-02-20"
        assert result["user_growth"][0]["new_users"] == 3

    @pytest.mark.asyncio
    async def test_multi_tenant_user_analytics_uses_active_org_scope(self, monkeypatch):
        """User analytics use active org when no org_id query is supplied."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval.side_effect = [24, 6, 5]
        mock_conn.fetch.side_effect = [
            [],
            [],
            [],
            [],
            [],
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_users
            result = await analytics_users(
                auth=_ADMIN_ORG_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        assert "org-active" in str(mock_conn.fetchval.call_args_list)
        assert "org-active" in str(mock_conn.fetch.call_args_list)
        assert result["scope"] == {
            "org_scoped": True,
            "org_filter_applied": True,
            "identifier_strategy": "active_org_id_not_echoed",
        }
        assert "org-active" not in str(result)

    @pytest.mark.asyncio
    async def test_role_distribution(self):
        """Returns both canonical and compatibility role distributions."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval.side_effect = [100, 20, 15]
        mock_conn.fetch.side_effect = [
            [],  # user_growth (empty)
            [
                {"role": "student", "count": 85},
                {"role": "teacher", "count": 12},
                {"role": "admin", "count": 3},
            ],
            [
                {"platform_role": "user", "count": 97},
                {"platform_role": "platform_admin", "count": 3},
            ],
            [],  # top_active
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_users
            result = await analytics_users(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        assert "role_distribution" in result
        assert "legacy_role_distribution" in result
        assert "platform_role_distribution" in result
        assert isinstance(result["role_distribution"], dict)
        assert result["role_distribution"].get("student") == 85
        assert result["role_distribution"].get("teacher") == 12
        assert result["legacy_role_distribution"].get("admin") == 3
        assert result["platform_role_distribution"].get("user") == 97
        assert result["platform_role_distribution"].get("platform_admin") == 3

    @pytest.mark.asyncio
    async def test_top_active(self):
        """Returns top_active_users list sorted by sessions descending."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval.side_effect = [50, 5, 4]
        mock_conn.fetch.side_effect = [
            [],  # user_growth
            [],  # role_distribution
            [],  # platform_role_distribution
            [],  # organization_role_distribution
            [
                {"user_id": "power-user", "sessions": 42},
                {"user_id": "regular-user", "sessions": 7},
            ],  # top_active
        ]

        with (
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch("app.api.v1.admin_analytics.settings.enable_multi_tenant", True),
        ):
            from app.api.v1.admin_analytics import analytics_users
            result = await analytics_users(
                auth=_ADMIN_USER,
                from_date=None,
                to_date=None,
                org_id=None,
            )

        assert "top_active_users" in result
        assert len(result["top_active_users"]) == 2
        assert result["top_active_users"][0]["user_id"] == "power-user"
        assert result["top_active_users"][0]["sessions"] == 42

    @pytest.mark.asyncio
    async def test_new_users(self):
        """Returns new_users_period count and total_users for the period."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval.side_effect = [200, 15, 10]  # total, new, active
        mock_conn.fetch.side_effect = [[], [], [], []]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_users
            result = await analytics_users(
                auth=_ADMIN_USER,
                from_date="2026-02-01",
                to_date="2026-02-23",
                org_id=None,
            )

        assert result["new_users_period"] == 15
        assert result["total_users"] == 200

    @pytest.mark.asyncio
    async def test_org_filtered_user_analytics_include_org_role_distribution(self):
        """Org-scoped analytics return organization role distribution separately."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval.side_effect = [24, 6, 5]  # total, new, active
        mock_conn.fetch.side_effect = [
            [],  # user_growth
            [{"role": "teacher", "count": 10}, {"role": "student", "count": 14}],
            [{"platform_role": "user", "count": 24}],
            [{"role": "org_admin", "count": 2}, {"role": "member", "count": 22}],
            [],  # top_active
        ]

        with patch(_POOL_PATCH, async_pool_fn, create=True):
            from app.api.v1.admin_analytics import analytics_users
            result = await analytics_users(
                auth=AuthenticatedUser(
                    user_id="admin-1",
                    auth_method="api_key",
                    role="admin",
                    organization_id="org-lms",
                ),
                from_date=None,
                to_date=None,
                org_id="org-lms",
            )

        assert result["total_users"] == 24
        assert result["legacy_role_distribution"]["teacher"] == 10
        assert result["platform_role_distribution"]["user"] == 24
        assert result["organization_role_distribution"]["org_admin"] == 2
        assert result["organization_role_distribution"]["member"] == 22
