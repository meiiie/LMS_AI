"""
Sprint 178: Admin Compliance Tests — Phase 3

Tests:
  1. Audit Log Viewer  — GET /api/v1/admin/audit-logs
  2. Auth Events Viewer — GET /api/v1/admin/auth-events
  3. GDPR Export        — POST /api/v1/admin/users/{user_id}/export
  4. GDPR Forget        — POST /api/v1/admin/users/{user_id}/forget

Patching strategy:
  - Auth: app.dependency_overrides[require_auth] = lambda: _ADMIN_USER
    FastAPI resolves dependencies at request time, so we override the function
    that is registered as Depends(require_auth) in _require_admin.
  - Admin module gate: patch `app.core.admin_security.check_admin_module` to
              skip the enable_admin_module check + IP allowlist in one shot.
  - DB pool: patch `app.core.database.get_asyncpg_pool` (create=True) because
             it is a lazy import inside function bodies.
  - DB pool: patch `app.core.database.get_asyncpg_pool` (create=True) because
             it is a lazy import inside function bodies.
  - audit service: patch `app.services.admin_audit.log_admin_action` for GDPR
             endpoints that fire-and-forget an audit event.
"""

from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.security import AuthenticatedUser, require_auth

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POOL_PATCH = "app.core.database.get_asyncpg_pool"

_ADMIN_USER = AuthenticatedUser(
    user_id="admin-1",
    auth_method="api_key",
    role="admin",
    organization_id="org-admin",
)

_STUDENT_USER = AuthenticatedUser(
    user_id="student-1",
    auth_method="api_key",
    role="student",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool_and_conn():
    """Create standard mock pool + connection for async DB tests.

    Returns (async_pool_fn, mock_conn) where async_pool_fn is an AsyncMock
    that, when awaited, returns a pool with a working acquire() context manager.
    Includes transaction() mock for endpoints using conn.transaction().
    """
    mock_conn = AsyncMock()
    # transaction() is a sync call returning an async context manager
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=tx_cm)

    mock_pool = MagicMock()
    acm = AsyncMock()
    acm.__aenter__ = AsyncMock(return_value=mock_conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = acm
    async_pool_fn = AsyncMock(return_value=mock_pool)
    return async_pool_fn, mock_conn


def _make_record(**kwargs):
    """Create a dict-like mock that simulates an asyncpg Record."""
    m = MagicMock()
    m.__getitem__ = lambda self, key: kwargs[key]
    m.get = lambda key, default=None: kwargs.get(key, default)
    return m


def _make_settings_mock(enable_admin=True, ip_allowlist=""):
    """Return a MagicMock configured as settings with admin module enabled."""
    m = MagicMock()
    m.enable_admin_module = enable_admin
    m.admin_ip_allowlist = ip_allowlist
    return m


def _make_client(app) -> httpx.AsyncClient:
    """Return an AsyncClient wired to the given ASGI app."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


def _keep_root_mount_last(app) -> None:
    """Keep SPA catch-all mounts after dynamically attached API routes."""
    root_mount_ids = {
        id(route)
        for route in app.router.routes
        if (
            route.__class__.__name__ == "Mount"
            and getattr(route, "path", None) in {"", "/"}
        )
    }
    if not root_mount_ids:
        return

    app.router.routes[:] = [
        route for route in app.router.routes if id(route) not in root_mount_ids
    ] + [
        route for route in app.router.routes if id(route) in root_mount_ids
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_app():
    """Import the main app and attach the admin routers once."""
    from app.main import app as _app

    from app.api.v1.admin_audit import router as audit_router
    from app.api.v1.admin_gdpr import router as gdpr_router

    existing_paths = {r.path for r in _app.routes}
    if "/api/v1/admin/audit-logs" not in existing_paths:
        _app.include_router(audit_router, prefix="/api/v1")
    if "/api/v1/admin/users/{user_id}/export" not in existing_paths:
        _app.include_router(gdpr_router, prefix="/api/v1")
    _keep_root_mount_last(_app)

    return _app


@pytest.fixture()
def admin_app(base_app):
    """App with require_auth overridden to return admin user.

    Cleans up the override after each test.
    """
    from app.api.v1.admin_audit import _check_admin_module as audit_admin_gate
    from app.api.v1.admin_gdpr import _check_admin_module as gdpr_admin_gate

    base_app.dependency_overrides[require_auth] = lambda: _ADMIN_USER
    base_app.dependency_overrides[audit_admin_gate] = lambda: None
    base_app.dependency_overrides[gdpr_admin_gate] = lambda: None
    yield base_app
    base_app.dependency_overrides.clear()


@pytest.fixture()
def student_app(base_app):
    """App with require_auth overridden to return a student (non-admin) user."""
    from app.api.v1.admin_audit import _check_admin_module as audit_admin_gate
    from app.api.v1.admin_gdpr import _check_admin_module as gdpr_admin_gate

    base_app.dependency_overrides[require_auth] = lambda: _STUDENT_USER
    base_app.dependency_overrides[audit_admin_gate] = lambda: None
    base_app.dependency_overrides[gdpr_admin_gate] = lambda: None
    yield base_app
    base_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Context manager helper: common module-level patches for admin settings
# ---------------------------------------------------------------------------

def _settings_patches():
    """Return a tuple of patch context managers for admin module gate.

    Captured FastAPI dependencies are overridden in the app fixtures above.
    These patches are retained for direct helper imports and to keep the
    existing test context structure stable.
    Tuple size stays at 3 so all ``p1, p2, p3 = _settings_patches()`` unpack.
    """
    return (
        patch("app.core.admin_security.check_admin_module", return_value=None),
        nullcontext(),
        nullcontext(),
    )


# =============================================================================
# TestAuditLogViewer — GET /api/v1/admin/audit-logs
# =============================================================================


class TestAuditLogViewer:
    """GET /api/v1/admin/audit-logs — query the admin_audit_log table."""

    def _audit_row(self, **overrides):
        """Build a minimal audit log record mock."""
        defaults = dict(
            id="row-1",
            actor_id="admin-1",
            actor_role="admin",
            actor_name="Admin User",
            action="user.deactivate",
            http_method="POST",
            http_path="/api/v1/users/u1/deactivate",
            http_status=200,
            target_type="user",
            target_id="u1",
            target_name="Student One",
            old_value=None,
            new_value=None,
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id="req-abc",
            organization_id=None,
            occurred_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return _make_record(**defaults)

    @pytest.mark.asyncio
    async def test_no_filters_returns_entries(self, admin_app):
        """No query params: returns entries list with total=3, limit=50, offset=0."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=3)
        mock_conn.fetch = AsyncMock(return_value=[self._audit_row()])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get("/api/v1/admin/audit-logs")

        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert data["total"] == 3
        assert data["limit"] == 50
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_filter_actor_passes_to_where_clause(self, admin_app):
        """actor_id query param is forwarded to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.fetch = AsyncMock(return_value=[self._audit_row(actor_id="admin-1")])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/audit-logs",
                    params={"actor_id": "admin-1"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "admin-1" in call_args.args

    @pytest.mark.asyncio
    async def test_filter_action_passes_to_where_clause(self, admin_app):
        """action query param is forwarded to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.fetch = AsyncMock(return_value=[])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/audit-logs",
                    params={"action": "gdpr.forget"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "gdpr.forget" in call_args.args

    @pytest.mark.asyncio
    async def test_filter_target_passes_target_type_and_id(self, admin_app):
        """target_type + target_id params are both forwarded to queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=2)
        mock_conn.fetch = AsyncMock(return_value=[self._audit_row()])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/audit-logs",
                    params={"target_type": "user", "target_id": "u1"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "user" in call_args.args
        assert "u1" in call_args.args

    @pytest.mark.asyncio
    async def test_filter_date_range_passes_from_to(self, admin_app):
        """from/to params are forwarded to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=5)
        mock_conn.fetch = AsyncMock(return_value=[self._audit_row()])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/audit-logs",
                    params={
                        "from": "2026-02-01T00:00:00Z",
                        "to": "2026-02-28T23:59:59Z",
                    },
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "2026-02-01T00:00:00Z" in call_args.args
        assert "2026-02-28T23:59:59Z" in call_args.args

    @pytest.mark.asyncio
    async def test_pagination_respects_limit_and_offset(self, admin_app):
        """Custom limit + offset are reflected in response and passed to the DB."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=100)
        mock_conn.fetch = AsyncMock(return_value=[self._audit_row()])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/audit-logs",
                    params={"limit": 10, "offset": 20},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 20
        # Verify that 10 and 20 were actually passed to the DB fetch call
        fetch_args = mock_conn.fetch.call_args.args
        assert 10 in fetch_args
        assert 20 in fetch_args

    @pytest.mark.asyncio
    async def test_requires_admin_role_returns_403(self, student_app):
        """Non-admin user (student) receives 403 Forbidden."""
        p1, p2, p3 = _settings_patches()
        with p1, p2, p3:
            async with _make_client(student_app) as client:
                resp = await client.get("/api/v1/admin/audit-logs")

        assert resp.status_code == 403


# =============================================================================
# TestAuthEventsViewer — GET /api/v1/admin/auth-events
# =============================================================================


class TestAuthEventsViewer:
    """GET /api/v1/admin/auth-events — query the Sprint 176 auth_events table."""

    def _auth_event_row(self, **overrides):
        """Build a minimal auth_events record mock."""
        defaults = dict(
            id="ev-1",
            event_type="login",
            user_id="user-1",
            provider="google",
            result="success",
            reason=None,
            ip_address="10.0.0.1",
            user_agent="Mozilla",
            organization_id=None,
            metadata=None,
            created_at=datetime(2026, 2, 21, 8, 0, 0, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return _make_record(**defaults)

    @pytest.mark.asyncio
    async def test_no_filters_returns_entries(self, admin_app):
        """No filters: response has entries with total=7 and default pagination."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=7)
        mock_conn.fetch = AsyncMock(return_value=[self._auth_event_row()])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get("/api/v1/admin/auth-events")

        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert data["total"] == 7
        assert len(data["entries"]) >= 1

    @pytest.mark.asyncio
    async def test_filter_user_id_forwarded_to_query(self, admin_app):
        """user_id filter is passed through to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=2)
        mock_conn.fetch = AsyncMock(return_value=[self._auth_event_row(user_id="u-42")])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/auth-events",
                    params={"user_id": "u-42"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "u-42" in call_args.args

    @pytest.mark.asyncio
    async def test_filter_event_type_forwarded_to_query(self, admin_app):
        """event_type filter is passed through to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.fetch = AsyncMock(
            return_value=[self._auth_event_row(event_type="replay")]
        )

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/auth-events",
                    params={"event_type": "replay"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "replay" in call_args.args

    @pytest.mark.asyncio
    async def test_date_range_forwarded_to_query(self, admin_app):
        """from/to date filters are passed to both COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.fetch = AsyncMock(return_value=[])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/auth-events",
                    params={
                        "from": "2026-01-01T00:00:00Z",
                        "to": "2026-01-31T23:59:59Z",
                    },
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "2026-01-01T00:00:00Z" in call_args.args
        assert "2026-01-31T23:59:59Z" in call_args.args

    @pytest.mark.asyncio
    async def test_filter_provider_forwarded_to_query(self, admin_app):
        """provider filter is passed through to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=3)
        mock_conn.fetch = AsyncMock(
            return_value=[self._auth_event_row(provider="host_action")]
        )

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/auth-events",
                    params={"provider": "host_action"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "host_action" in call_args.args

    @pytest.mark.asyncio
    async def test_filter_org_id_forwarded_to_query(self, admin_app):
        """org_id filter is passed through to the COUNT and SELECT queries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.fetch = AsyncMock(
            return_value=[self._auth_event_row(organization_id="org-1")]
        )

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/auth-events",
                    params={"org_id": "org-1"},
                )

        assert resp.status_code == 200
        call_args = mock_conn.fetchval.call_args
        assert "org-1" in call_args.args

    @pytest.mark.asyncio
    async def test_pagination_respects_limit_and_offset(self, admin_app):
        """limit + offset appear correctly in the response body."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchval = AsyncMock(return_value=50)
        mock_conn.fetch = AsyncMock(return_value=[])

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.get(
                    "/api/v1/admin/auth-events",
                    params={"limit": 5, "offset": 15},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 5
        assert data["offset"] == 15

    @pytest.mark.asyncio
    async def test_requires_admin_role_returns_403(self, student_app):
        """Non-admin user (student) receives 403 Forbidden."""
        p1, p2, p3 = _settings_patches()
        with p1, p2, p3:
            async with _make_client(student_app) as client:
                resp = await client.get("/api/v1/admin/auth-events")

        assert resp.status_code == 403


# =============================================================================
# TestGDPRExport — POST /api/v1/admin/users/{user_id}/export
# =============================================================================


class TestGDPRExport:
    """POST /api/v1/admin/users/{user_id}/export — GDPR Article 15 data export."""

    def _profile_row(self, user_id="user-123"):
        return _make_record(
            id=user_id,
            email="test@example.com",
            name="Nguyen Van A",
            role="student",
            platform_role="user",
            is_active=True,
            created_at=datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        )

    def _memory_row(self):
        return _make_record(
            memory_type="fact",
            content="User studies maritime law",
            importance=0.8,
            created_at=datetime(2025, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_returns_all_data_sections(self, admin_app):
        """Response includes profile, identities, memories, auth_events, audit_entries."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=self._profile_row())
        mock_conn.fetch = AsyncMock(return_value=[])

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post("/api/v1/admin/users/user-123/export")

        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "profile" in data["data"]
        assert "identities" in data["data"]
        assert "memories" in data["data"]
        assert "auth_events" in data["data"]
        assert "audit_entries" in data["data"]

    @pytest.mark.asyncio
    async def test_includes_profile_fields(self, admin_app):
        """Profile section contains id, email, name, role, platform_role, is_active, created_at."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=self._profile_row("uid-99"))
        mock_conn.fetch = AsyncMock(return_value=[])

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post("/api/v1/admin/users/uid-99/export")

        assert resp.status_code == 200
        profile = resp.json()["data"]["profile"]
        assert profile["id"] == "uid-99"
        assert profile["email"] == "test@example.com"
        assert profile["name"] == "Nguyen Van A"
        assert profile["role"] == "student"
        assert profile["platform_role"] == "user"
        assert profile["is_active"] is True
        assert "created_at" in profile

    @pytest.mark.asyncio
    async def test_includes_memories_when_present(self, admin_app):
        """Memories array is populated from the semantic_memories table query."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=self._profile_row())
        # fetch is called sequentially: identities → memories → auth_events → audit
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [],                       # identities
                [self._memory_row()],     # memories
                [],                       # auth_events
                [],                       # audit_entries
            ]
        )

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post("/api/v1/admin/users/user-123/export")

        assert resp.status_code == 200
        memories = resp.json()["data"]["memories"]
        assert len(memories) == 1
        assert memories[0]["content"] == "User studies maritime law"
        assert memories[0]["memory_type"] == "fact"

    @pytest.mark.asyncio
    async def test_memory_export_filters_by_active_org(self, admin_app, monkeypatch):
        """semantic_memories export is scoped to the active organization."""
        from app.api.v1 import admin_gdpr

        monkeypatch.setattr(admin_gdpr.settings, "enable_multi_tenant", True)
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=self._profile_row())
        mock_conn.fetch = AsyncMock(
            side_effect=[
                [],
                [self._memory_row()],
                [],
                [],
            ]
        )

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post("/api/v1/admin/users/user-123/export")

        assert resp.status_code == 200
        memory_call = mock_conn.fetch.await_args_list[1]
        assert "FROM semantic_memories WHERE user_id = $1 AND organization_id = $2" in memory_call.args[0]
        assert memory_call.args[1:] == ("user-123", "org-admin")

    @pytest.mark.asyncio
    async def test_memory_export_requires_active_org_before_pool(self, admin_app, monkeypatch):
        """Multi-tenant export must not open DB without active organization."""
        from app.api.v1 import admin_gdpr

        monkeypatch.setattr(admin_gdpr.settings, "enable_multi_tenant", True)
        no_org_admin = AuthenticatedUser(
            user_id="admin-1",
            auth_method="api_key",
            role="admin",
            organization_id=None,
        )
        admin_app.dependency_overrides[require_auth] = lambda: no_org_admin
        get_pool = AsyncMock()

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch("app.api.v1.admin_gdpr._get_pool", get_pool):
            async with _make_client(admin_app) as client:
                resp = await client.post("/api/v1/admin/users/user-123/export")

        assert resp.status_code == 403
        assert "Active organization" in resp.json()["detail"]
        get_pool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_user_returns_404(self, admin_app):
        """Returns 404 when the user row is not found (fetchrow returns None)."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/nonexistent-user/export"
                )

        assert resp.status_code == 404
        assert "nonexistent-user" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_requires_admin_role_returns_403(self, student_app):
        """Non-admin user (student) receives 403 Forbidden."""
        p1, p2, p3 = _settings_patches()
        with p1, p2, p3:
            async with _make_client(student_app) as client:
                resp = await client.post("/api/v1/admin/users/user-123/export")

        assert resp.status_code == 403


# =============================================================================
# TestGDPRForget — POST /api/v1/admin/users/{user_id}/forget
# =============================================================================


class TestGDPRForget:
    """POST /api/v1/admin/users/{user_id}/forget — GDPR Article 17 right to erasure."""

    def _user_row(self, user_id="user-del-1"):
        return _make_record(
            id=user_id,
            name="Tran Thi B",
            email="b@example.com",
        )

    def _setup_conn_for_forget(self, mock_conn, user_row=None):
        """Configure mock_conn with the expected call sequence for a successful forget."""
        mock_conn.fetchrow = AsyncMock(return_value=user_row or self._user_row())
        mock_conn.execute = AsyncMock(
            side_effect=[
                "UPDATE 1",   # anonymize profile
                "DELETE 3",   # delete user_identities
                "DELETE 1",   # revoke refresh_tokens
                "DELETE 5",   # delete semantic_memories
            ]
        )

    @pytest.mark.asyncio
    async def test_anonymizes_profile(self, admin_app):
        """Profile UPDATE is called with [Deleted User] and is_active=false."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        assert resp.json()["profile_anonymized"] is True
        update_sql = mock_conn.execute.call_args_list[0].args[0]
        assert "[Deleted User]" in update_sql
        assert "is_active" in update_sql

    @pytest.mark.asyncio
    async def test_deletes_user_identities(self, admin_app):
        """DELETE FROM user_identities is called; count matches execute return."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        assert resp.json()["identities_deleted"] == 3
        delete_id_sql = mock_conn.execute.call_args_list[1].args[0]
        assert "user_identities" in delete_id_sql

    @pytest.mark.asyncio
    async def test_revokes_refresh_tokens(self, admin_app):
        """DELETE FROM refresh_tokens is called; count matches execute return."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        assert resp.json()["tokens_revoked"] == 1
        delete_tok_sql = mock_conn.execute.call_args_list[2].args[0]
        assert "refresh_tokens" in delete_tok_sql

    @pytest.mark.asyncio
    async def test_deletes_semantic_memories(self, admin_app):
        """DELETE FROM semantic_memories is called; count matches execute return."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        assert resp.json()["memories_deleted"] == 5
        delete_mem_sql = mock_conn.execute.call_args_list[3].args[0]
        assert "semantic_memories" in delete_mem_sql

    @pytest.mark.asyncio
    async def test_forget_semantic_memory_delete_filters_by_active_org(self, admin_app, monkeypatch):
        """semantic_memories deletion is scoped to the active organization."""
        from app.api.v1 import admin_gdpr

        monkeypatch.setattr(admin_gdpr.settings, "enable_multi_tenant", True)
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        delete_mem_call = mock_conn.execute.await_args_list[3]
        assert delete_mem_call.args[0] == (
            "DELETE FROM semantic_memories WHERE user_id = $1 AND organization_id = $2"
        )
        assert delete_mem_call.args[1:] == ("user-del-1", "org-admin")

    @pytest.mark.asyncio
    async def test_forget_requires_active_org_before_pool(self, admin_app, monkeypatch):
        """Multi-tenant forget must not open DB without active organization."""
        from app.api.v1 import admin_gdpr

        monkeypatch.setattr(admin_gdpr.settings, "enable_multi_tenant", True)
        no_org_admin = AuthenticatedUser(
            user_id="admin-1",
            auth_method="api_key",
            role="admin",
            organization_id=None,
        )
        admin_app.dependency_overrides[require_auth] = lambda: no_org_admin
        get_pool = AsyncMock()

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch("app.api.v1.admin_gdpr._get_pool", get_pool):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 403
        assert "Active organization" in resp.json()["detail"]
        get_pool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_requires_confirm_true_succeeds(self, admin_app):
        """Sending confirm=true causes the endpoint to proceed and return 200."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "forgotten"

    @pytest.mark.asyncio
    async def test_without_confirm_returns_400(self, admin_app):
        """confirm=false causes 400 Bad Request before any DB calls are made."""
        p1, p2, p3 = _settings_patches()
        with p1, p2, p3:
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": False},
                )

        assert resp.status_code == 400
        assert "confirm" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_unknown_user_returns_404(self, admin_app):
        """Returns 404 when the user is not found (fetchrow returns None)."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        p1, p2, p3 = _settings_patches()
        with p1, p2, p3, patch(_POOL_PATCH, async_pool_fn, create=True):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/ghost-user/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 404
        assert "ghost-user" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_requires_admin_role_returns_403(self, student_app):
        """Non-admin user (student) receives 403 Forbidden."""
        p1, p2, p3 = _settings_patches()
        with p1, p2, p3:
            async with _make_client(student_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_logs_audit_with_gdpr_forget_action(self, admin_app):
        """log_admin_action is called exactly once with action='gdpr.forget'."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ) as mock_log,
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        mock_log.assert_called_once()
        call = mock_log.call_args
        # action is the second positional argument or a keyword argument
        action_value = call.kwargs.get("action") or (
            call.args[1] if len(call.args) > 1 else None
        )
        assert action_value == "gdpr.forget"

    @pytest.mark.asyncio
    async def test_preserves_audit_logs_in_response(self, admin_app):
        """Response contains audit_logs_preserved=True — the audit log is NOT erased."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        assert resp.json()["audit_logs_preserved"] is True

    @pytest.mark.asyncio
    async def test_response_contains_status_forgotten(self, admin_app):
        """Response status='forgotten' and user_id echoes the path parameter."""
        async_pool_fn, mock_conn = _mock_pool_and_conn()
        self._setup_conn_for_forget(mock_conn)

        p1, p2, p3 = _settings_patches()
        with (
            p1, p2, p3,
            patch(_POOL_PATCH, async_pool_fn, create=True),
            patch(
                "app.services.admin_audit.log_admin_action",
                new_callable=AsyncMock,
            ),
        ):
            async with _make_client(admin_app) as client:
                resp = await client.post(
                    "/api/v1/admin/users/user-del-1/forget",
                    json={"confirm": True},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "forgotten"
        assert data["user_id"] == "user-del-1"
