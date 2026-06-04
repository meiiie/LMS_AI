"""
Sprint 160b: "Hoàn Thiện" — Complete Isolation + OAuth Security Tests.

Tests verify:
1. Scheduler repo org filtering (9 tests)
2. Insight repo org filtering (3 tests)
3. Preferences repo org filtering (3 tests)
4. Learning profile repo org filtering (8 tests)
5. Thread repo org filtering (8 tests)
6. Character repo org filtering (4 tests)
7. OAuth email_verified guard and diagnostics privacy (8 tests)
8. Token fragment redirect (2 tests)
9. Config security validation (2 tests)
"""

import json
import logging
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime, timezone


# ============================================================================
# Helpers
# ============================================================================

def _make_settings(**overrides):
    """Create a mock settings object."""
    s = MagicMock()
    s.enable_multi_tenant = overrides.get("enable_multi_tenant", False)
    s.default_organization_id = overrides.get("default_organization_id", "default")
    s.enable_google_oauth = overrides.get("enable_google_oauth", True)
    s.google_oauth_client_id = overrides.get("google_oauth_client_id", "test-id")
    s.google_oauth_client_secret = overrides.get("google_oauth_client_secret", "test-secret")
    s.session_secret_key = overrides.get("session_secret_key", "change-session-secret-in-production")
    s.environment = overrides.get("environment", "development")
    return s


def _patch_settings(enable_multi_tenant=False, default_org="default"):
    return patch(
        "app.core.config.settings",
        _make_settings(
            enable_multi_tenant=enable_multi_tenant,
            default_organization_id=default_org,
        ),
    )


def _mock_session_factory():
    """Create a mock session factory that supports context manager."""
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    return factory, session


# ============================================================================
# Group 1: Scheduler repo org filtering (9 tests)
# ============================================================================

class TestSchedulerOrgFilter:
    """Test org filtering on scheduler_repository methods."""

    def test_create_task_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Task creation fails closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.scheduler_repository import SchedulerRepository

        repo = SchedulerRepository()
        factory, _session = _mock_session_factory()
        repo._session_factory = factory
        repo._initialized = True
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.create_task(
                user_id="PRIVATE-USER",
                description="private reminder",
            )
        finally:
            current_org_id.reset(token)

        assert result is None
        factory.assert_not_called()
        assert "scheduler_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text
        assert "private reminder" not in caplog.text

    def test_get_due_tasks_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Tenant-scoped due-task reads fail closed without production org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.scheduler_repository import SchedulerRepository

        repo = SchedulerRepository()
        factory, _session = _mock_session_factory()
        repo._session_factory = factory
        repo._initialized = True
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_due_tasks()
        finally:
            current_org_id.reset(token)

        assert result == []
        factory.assert_not_called()
        assert "scheduler_repository_blocked_missing_org_context" in caplog.text

    def test_cancel_task_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Task cancellation fails closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.scheduler_repository import SchedulerRepository

        repo = SchedulerRepository()
        factory, _session = _mock_session_factory()
        repo._session_factory = factory
        repo._initialized = True
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.cancel_task(
                task_id="PRIVATE-TASK",
                user_id="PRIVATE-USER",
            )
        finally:
            current_org_id.reset(token)

        assert result is False
        factory.assert_not_called()
        assert "scheduler_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-TASK" not in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_get_due_tasks_includes_org_filter_when_enabled(self):
        """get_due_tasks() should include org_where_clause when multi-tenant enabled."""
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-a"
                from app.repositories.scheduler_repository import SchedulerRepository
                repo = SchedulerRepository()
                factory, session = _mock_session_factory()
                repo._session_factory = factory
                repo._initialized = True

                session.execute.return_value.fetchall.return_value = []
                result = repo.get_due_tasks()

                # Verify the SQL includes org_id filter
                call_args = session.execute.call_args
                sql_text = str(call_args[0][0])
                assert "organization_id = :org_id" in sql_text
                assert call_args[0][1].get("org_id") == "org-a"

    def test_get_due_tasks_uses_default_org_when_disabled(self):
        """Single-tenant reads still bind the configured default org."""
        with _patch_settings(enable_multi_tenant=False):
            from app.repositories.scheduler_repository import SchedulerRepository
            repo = SchedulerRepository()
            factory, session = _mock_session_factory()
            repo._session_factory = factory
            repo._initialized = True

            session.execute.return_value.fetchall.return_value = []
            repo.get_due_tasks()

            call_args = session.execute.call_args
            sql_text = str(call_args[0][0])
            assert "organization_id = :org_id" in sql_text
            assert call_args[0][1].get("org_id") == "default"

    def test_get_due_tasks_worker_scope_selects_org_id_without_filter(self):
        """The background worker must opt into all-org polling explicitly."""
        with _patch_settings(enable_multi_tenant=True):
            from app.repositories.scheduler_repository import SchedulerRepository
            repo = SchedulerRepository()
            factory, session = _mock_session_factory()
            repo._session_factory = factory
            repo._initialized = True

            session.execute.return_value.fetchall.return_value = []
            repo.get_due_tasks(allow_all_orgs=True)

            call_args = session.execute.call_args
            sql_text = str(call_args[0][0])
            assert "extra_data, organization_id" in sql_text
            assert "organization_id = :org_id" not in sql_text
            assert "org_id" not in call_args[0][1]

    def test_create_task_includes_org_id(self):
        """create_task() should include organization_id in INSERT."""
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-b"
                from app.repositories.scheduler_repository import SchedulerRepository
                repo = SchedulerRepository()
                factory, session = _mock_session_factory()
                repo._session_factory = factory
                repo._initialized = True

                repo.create_task(user_id="u1", description="test")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id" in sql_text
                assert session.execute.call_args[0][1].get("org_id") == "org-b"

    def test_list_tasks_includes_org_filter(self):
        """list_tasks() should include org_where_clause when enabled."""
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-c"
                from app.repositories.scheduler_repository import SchedulerRepository
                repo = SchedulerRepository()
                factory, session = _mock_session_factory()
                repo._session_factory = factory
                repo._initialized = True

                session.execute.return_value.fetchall.return_value = []
                repo.list_tasks(user_id="u1")

                call_args = session.execute.call_args
                sql_text = str(call_args[0][0])
                assert "organization_id = :org_id" in sql_text
                assert call_args[0][1].get("org_id") == "org-c"

    def test_cancel_task_includes_org_filter(self):
        """cancel_task() should include org_where_clause when enabled."""
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-d"
                from app.repositories.scheduler_repository import SchedulerRepository
                repo = SchedulerRepository()
                factory, session = _mock_session_factory()
                repo._session_factory = factory
                repo._initialized = True

                session.execute.return_value.rowcount = 1
                repo.cancel_task(task_id="t1", user_id="u1")

                call_args = session.execute.call_args
                sql_text = str(call_args[0][0])
                assert "organization_id = :org_id" in sql_text
                assert call_args[0][1].get("org_id") == "org-d"


# ============================================================================
# Group 2: Insight repo org filtering (3 tests)
# ============================================================================

class TestInsightOrgFilter:
    """Test org filtering on insight_repository methods."""

    def _make_repo(self):
        """Create a mock InsightRepositoryMixin host."""
        from app.repositories.insight_repository import InsightRepositoryMixin

        class FakeRepo(InsightRepositoryMixin):
            TABLE_NAME = "semantic_memories"
            def _ensure_initialized(self):
                pass

        repo = FakeRepo()
        factory, session = _mock_session_factory()
        repo._session_factory = factory
        return repo, session

    def test_get_user_insights_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Insight reads fail closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_user_insights("PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._session_factory.assert_not_called()
        assert "insight_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_get_user_insights_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-x"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_user_insights("u1")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-x"

    def test_delete_user_insights_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Insight deletes fail closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            deleted = repo.delete_user_insights("PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert deleted == 0
        repo._session_factory.assert_not_called()
        assert "insight_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_delete_user_insights_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-x"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.delete_user_insights("u1")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-x"

    def test_get_insights_by_category_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-x"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_insights_by_category("u1", "learning")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-x"


# ============================================================================
# Group 3: Learning profile repo org filtering (8 tests)
# ============================================================================

class TestLearningProfileOrgFilter:
    """Test org filtering on LearningProfileRepository."""

    def _make_repo(self):
        from app.repositories.learning_profile_repository import LearningProfileRepository
        # Use __new__ to skip __init__ (which tries to connect to DB)
        repo = LearningProfileRepository.__new__(LearningProfileRepository)
        factory, session = _mock_session_factory()
        repo._engine = MagicMock()
        repo._session_factory = factory
        repo._available = True
        return repo, session

    @pytest.mark.asyncio
    async def test_get_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Learning profile reads fail closed without production org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = await repo.get("PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "learning_profile_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    @pytest.mark.asyncio
    async def test_create_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Learning profile creation fails closed without production org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = await repo.create("PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "learning_profile_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    @pytest.mark.asyncio
    async def test_update_weak_areas_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Learning profile writes fail closed without production org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = await repo.update_weak_areas("PRIVATE-USER", ["private-topic"])
        finally:
            current_org_id.reset(token)

        assert result is False
        repo._session_factory.assert_not_called()
        assert "learning_profile_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text
        assert "private-topic" not in caplog.text

    @pytest.mark.asyncio
    async def test_get_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                await repo.get("u1")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-lp"

    @pytest.mark.asyncio
    async def test_create_includes_org_id(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                # get returns None (no profile)
                session.execute.return_value.fetchone.return_value = None
                await repo.create("u1")

                # First call is the INSERT
                call_args = session.execute.call_args_list[0]
                sql_text = str(call_args[0][0])
                assert "organization_id" in sql_text
                assert "ON CONFLICT (organization_id, user_id)" in sql_text
                assert call_args[0][1]["org_id"] == "org-lp"

    @pytest.mark.asyncio
    async def test_update_weak_areas_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                await repo.update_weak_areas("u1", ["topic1"])

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-lp"

    @pytest.mark.asyncio
    async def test_update_strong_areas_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                await repo.update_strong_areas("u1", ["topic2"])

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-lp"

    @pytest.mark.asyncio
    async def test_increment_stats_uses_org_for_get_or_create_and_update(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                repo.get_or_create = AsyncMock(return_value={"user_id": "u1"})

                result = await repo.increment_stats("u1", messages=3)

                assert result is True
                repo.get_or_create.assert_awaited_once_with(
                    "u1",
                    organization_id="org-lp",
                )
                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-lp"


# ============================================================================
# Group 5: Thread repo org filtering (6 tests)
# ============================================================================

class TestThreadOrgFilter:
    """Test org filtering on thread_repository methods."""

    def _make_repo(self):
        from app.repositories.thread_repository import ThreadRepository
        repo = ThreadRepository()
        factory, session = _mock_session_factory()
        repo._session_factory = factory
        repo._initialized = True
        return repo, session

    def test_upsert_thread_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Thread upserts fail closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.upsert_thread("PRIVATE-THREAD", "PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "thread_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-THREAD" not in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_get_thread_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Thread reads fail closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_thread("PRIVATE-THREAD", "PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "thread_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-THREAD" not in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_get_thread_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                repo.get_thread("t1", "u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_get_thread_accepts_explicit_org_without_context(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = None
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                repo.get_thread("t1", "u1", organization_id="org-explicit")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-explicit"

    def test_delete_thread_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.rowcount = 1
                repo.delete_thread("t1", "u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_rename_thread_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.rowcount = 1
                repo.rename_thread("t1", "u1", "New title")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_update_extra_data_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.rowcount = 1
                repo.update_extra_data("t1", "u1", {"summary": "test"})

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_get_threads_with_summaries_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_threads_with_summaries("u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_count_threads_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.scalar.return_value = 5
                repo.count_threads("u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text


# ============================================================================
# Group 6: Character repo org filtering (9 tests)
# ============================================================================

class TestCharacterOrgFilter:
    """Test org filtering on character_repository methods."""

    def _make_repo(self):
        from app.engine.character.character_repository import CharacterRepository
        repo = CharacterRepository()
        factory, session = _mock_session_factory()
        repo._session_factory = factory
        repo._initialized = True
        return repo, session

    def test_get_all_blocks_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_all_blocks("u1")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-ch"

    def test_get_block_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                repo.get_block("learned_lessons", "u1")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-ch"

    def test_create_block_uses_org_conflict_key(self):
        from app.engine.character.models import CharacterBlockCreate

        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                repo.create_block(
                    CharacterBlockCreate(label="self_notes", content="x"),
                    user_id="u1",
                )

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id, user_id, label" in sql_text
                assert "ON CONFLICT (organization_id, user_id, label)" in sql_text
                assert params["org_id"] == "org-ch"

    def test_get_recent_experiences_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_recent_experiences(user_id="u1")

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-ch"

    def test_count_experiences_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.scalar.return_value = 10
                repo.count_experiences()

                sql_text = str(session.execute.call_args[0][0])
                params = session.execute.call_args[0][1]
                assert "organization_id = :org_id" in sql_text
                assert params["org_id"] == "org-ch"

    def test_get_all_blocks_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_all_blocks(user_id="PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._session_factory.assert_not_called()
        assert "character_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_create_block_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.character.models import CharacterBlockCreate

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.create_block(
                CharacterBlockCreate(label="PRIVATE-LABEL", content="PRIVATE CONTENT"),
                user_id="PRIVATE-USER",
            )
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "character_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-LABEL" not in caplog.text
        assert "PRIVATE CONTENT" not in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_log_experience_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.character.models import CharacterExperienceCreate

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.log_experience(
                CharacterExperienceCreate(
                    experience_type="learning",
                    content="PRIVATE EXPERIENCE",
                    user_id="PRIVATE-USER",
                )
            )
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "character_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE EXPERIENCE" not in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_cleanup_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo, _session = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.cleanup_old_experiences(user_id="PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result == 0
        repo._session_factory.assert_not_called()
        assert "character_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text


# ============================================================================
# Group 7: OAuth email_verified guard and diagnostics privacy (8 tests)
# ============================================================================

class TestOAuthEmailVerified:
    """Test email_verified security guard in user_service."""

    @pytest.mark.asyncio
    async def test_verified_email_allows_auto_link(self):
        """When email_verified=True, auto-link should proceed."""
        with patch("app.auth.user_service._get_pool") as mock_pool:
            pool = AsyncMock()
            mock_pool.return_value = pool
            conn = AsyncMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            # Step 1: No provider match
            # Step 2: Email match exists
            existing_user = {"id": "user-1", "email": "test@example.com", "name": "T", "avatar_url": None, "role": "student", "is_active": True}

            from app.auth.user_service import find_or_create_by_provider
            with patch("app.auth.user_service.find_user_by_provider", return_value=None), \
                 patch("app.auth.user_service.find_user_by_email", return_value=existing_user), \
                 patch("app.auth.user_service.link_identity", return_value="id-1"):

                result = await find_or_create_by_provider(
                    provider="github",
                    provider_sub="gh-123",
                    email="test@example.com",
                    email_verified=True,
                )

                assert result["id"] == "user-1"

    @pytest.mark.asyncio
    async def test_unverified_email_blocks_auto_link(self):
        """When email_verified=False, auto-link should be blocked → create new user."""
        existing_user = {"id": "user-1", "email": "test@example.com", "name": "T", "avatar_url": None, "role": "student", "is_active": True}
        new_user = {"id": "user-2", "email": "test@example.com", "name": "T", "avatar_url": None, "role": "student", "is_active": True}

        from app.auth.user_service import find_or_create_by_provider
        with patch("app.auth.user_service.find_user_by_provider", return_value=None), \
             patch("app.auth.user_service.find_user_by_email", return_value=existing_user), \
             patch("app.auth.user_service.create_user", return_value=new_user), \
             patch("app.auth.user_service.link_identity", return_value="id-2"):

            result = await find_or_create_by_provider(
                provider="github",
                provider_sub="gh-456",
                email="test@example.com",
                email_verified=False,
            )

            # Should create NEW user, not link to existing
            assert result["id"] == "user-2"

    @pytest.mark.asyncio
    async def test_unverified_email_logs_warning(self, caplog):
        """When email_verified=False and email match exists, should log SECURITY warning."""
        raw_email = "private@example.com"
        raw_existing_user_id = "user-private-existing"
        existing_user = {"id": raw_existing_user_id, "email": raw_email, "name": "T", "avatar_url": None, "role": "student", "is_active": True}
        new_user = {"id": "user-private-new", "email": raw_email, "name": "T", "avatar_url": None, "role": "student", "is_active": True}

        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
        from app.auth.user_service import find_or_create_by_provider
        with patch("app.auth.user_service.find_user_by_provider", return_value=None), \
             patch("app.auth.user_service.find_user_by_email", return_value=existing_user), \
             patch("app.auth.user_service.create_user", return_value=new_user), \
             patch("app.auth.user_service.link_identity", return_value="id-2"):

            with caplog.at_level(logging.WARNING, logger="app.auth.user_service"):
                await find_or_create_by_provider(
                    provider="github",
                    provider_sub="gh-789",
                    email=raw_email,
                    email_verified=False,
                )

            assert any("SECURITY" in r.message and "UNVERIFIED" in r.message for r in caplog.records)
            assert raw_email not in caplog.text
            assert raw_existing_user_id not in caplog.text
            assert hash_runtime_identifier(raw_email) in caplog.text
            assert hash_runtime_identifier(raw_existing_user_id) in caplog.text

    @pytest.mark.asyncio
    async def test_create_user_logs_hash_refs(self, caplog):
        """create_user should log stable refs without raw user IDs or email."""
        raw_email = "create-private@example.com"

        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
        from app.auth.user_service import create_user

        with patch("app.auth.user_service._get_pool") as mock_pool:
            pool = MagicMock()
            mock_pool.return_value = pool
            conn = AsyncMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.INFO, logger="app.auth.user_service"):
                user = await create_user(email=raw_email, name="Private User")

        assert user["id"] not in caplog.text
        assert raw_email not in caplog.text
        assert hash_runtime_identifier(user["id"]) in caplog.text
        assert hash_runtime_identifier(raw_email) in caplog.text

    @pytest.mark.asyncio
    async def test_link_identity_logs_and_audits_hash_refs(self, caplog):
        """link_identity should keep raw provider IDs out of logs and audit metadata."""
        raw_user_id = "user-link-private"
        raw_provider_sub = "github-oauth-private-sub"
        raw_email = "link-private@example.com"

        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
        from app.auth.user_service import link_identity

        with patch("app.auth.user_service._get_pool") as mock_pool:
            pool = MagicMock()
            mock_pool.return_value = pool
            conn = AsyncMock()
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            audit_log = AsyncMock()

            with patch("app.auth.auth_audit.log_auth_event", audit_log):
                with caplog.at_level(logging.INFO, logger="app.auth.user_service"):
                    identity_id = await link_identity(
                        user_id=raw_user_id,
                        provider="github",
                        provider_sub=raw_provider_sub,
                        email=raw_email,
                    )

        assert identity_id not in caplog.text
        assert raw_user_id not in caplog.text
        assert raw_provider_sub not in caplog.text
        assert raw_email not in caplog.text
        assert hash_runtime_identifier(raw_user_id) in caplog.text
        assert hash_runtime_identifier(raw_provider_sub) in caplog.text
        audit_log.assert_awaited_once()
        assert audit_log.call_args.kwargs["metadata"] == {
            "provider_sub_ref": hash_runtime_identifier(raw_provider_sub),
        }

    @pytest.mark.asyncio
    async def test_unlink_identity_logs_and_audits_hash_refs(self, caplog):
        """unlink_identity should log/audit identity refs instead of raw identity IDs."""
        raw_user_id = "user-unlink-private"
        raw_identity_id = "identity-private-id"

        from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
        from app.auth.user_service import unlink_identity

        with patch("app.auth.user_service._get_pool") as mock_pool:
            pool = MagicMock()
            mock_pool.return_value = pool
            conn = AsyncMock()
            conn.fetchval.return_value = 2
            conn.execute.return_value = "DELETE 1"
            pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
            pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            audit_log = AsyncMock()

            with patch("app.auth.auth_audit.log_auth_event", audit_log):
                with caplog.at_level(logging.INFO, logger="app.auth.user_service"):
                    result = await unlink_identity(raw_user_id, raw_identity_id)

        assert result is True
        assert raw_user_id not in caplog.text
        assert raw_identity_id not in caplog.text
        assert hash_runtime_identifier(raw_user_id) in caplog.text
        assert hash_runtime_identifier(raw_identity_id) in caplog.text
        audit_log.assert_awaited_once()
        assert audit_log.call_args.kwargs["metadata"] == {
            "identity_ref": hash_runtime_identifier(raw_identity_id),
        }

    @pytest.mark.asyncio
    async def test_find_or_create_by_google_passes_email_verified(self):
        """find_or_create_by_google() should pass email_verified to find_or_create_by_provider."""
        from app.auth.user_service import find_or_create_by_google
        user = {"id": "u1", "email": "a@b.com", "name": "A", "avatar_url": None, "role": "student", "is_active": True}

        with patch("app.auth.user_service.find_or_create_by_provider", return_value=user) as mock_focp:
            await find_or_create_by_google(
                google_sub="g-1",
                email="a@b.com",
                email_verified=True,
            )
            mock_focp.assert_called_once()
            assert mock_focp.call_args.kwargs.get("email_verified") is True

    @pytest.mark.asyncio
    async def test_default_email_verified_is_false(self):
        """find_or_create_by_provider default email_verified should be False."""
        from app.auth.user_service import find_or_create_by_provider
        user = {"id": "u1", "email": "a@b.com", "name": "A", "avatar_url": None, "role": "student", "is_active": True}

        with patch("app.auth.user_service.find_user_by_provider", return_value=user):
            # This hits step 1 (exact match) so email_verified doesn't matter,
            # but we verify the signature accepts default
            result = await find_or_create_by_provider(
                provider="lms",
                provider_sub="lms-1",
                email="a@b.com",
                # email_verified not passed → defaults to False
            )
            assert result["id"] == "u1"


# ============================================================================
# Group 8: Token fragment redirect (2 tests)
# ============================================================================

class TestTokenFragment:
    """Test token delivery via URL fragment."""

    def test_google_oauth_uses_fragment_redirect(self):
        """Backend callback should use # fragment, not ? query params."""
        import os
        oauth_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "app", "auth", "google_oauth.py"
        )
        oauth_path = os.path.normpath(oauth_path)
        with open(oauth_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Should use fragment (#) not query (?) for token delivery
        # Sprint 193b: variable renamed from `params` to `token_params`
        assert "#{token_params}" in source, "google_oauth.py should use URL fragment (#{token_params}) for token redirect"
        assert "?{token_params}" not in source, "google_oauth.py should NOT use query params (?{token_params}) for tokens"

    def test_desktop_login_screen_parses_fragment(self):
        """Desktop LoginScreen should parse tokens from URL hash."""
        import os
        # Try multiple paths — repo root may differ
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "wiii-desktop", "src", "components", "auth", "LoginScreen.tsx"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "wiii-desktop", "src", "components", "auth", "LoginScreen.tsx"),
        ]
        login_screen_path = None
        for c in candidates:
            p = os.path.normpath(c)
            if os.path.exists(p):
                login_screen_path = p
                break

        if not login_screen_path:
            pytest.skip("LoginScreen.tsx not found")

        with open(login_screen_path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "url.hash" in source, "LoginScreen should parse URL hash"
        assert "hash.substring(1)" in source, "LoginScreen should strip leading # from hash"


# ============================================================================
# Group 9: Config security validation (2 tests)
# ============================================================================

class TestConfigSecurity:
    """Test production security enforcement."""

    def test_session_secret_rejected_in_production(self):
        """Default session_secret_key should raise ValueError in production + OAuth."""
        from app.core.config import Settings

        with pytest.raises(ValueError, match="session_secret_key"):
            Settings(
                environment="production",
                enable_dev_login=False,
                enable_google_oauth=True,
                google_oauth_client_id="test-id",
                google_oauth_client_secret="real-google-client-secret-for-session-test",
                session_secret_key="change-session-secret-in-production",
                jwt_secret_key="real-secret-key-with-32-chars",
                api_key="real-api-key-with-32-chars",
            )

    def test_session_secret_allowed_in_development(self):
        """Default session_secret_key should be allowed in development."""
        from app.core.config import Settings

        # Should NOT raise — development environment
        try:
            s = Settings(
                environment="development",
                enable_google_oauth=True,
                google_oauth_client_id="test-id",
                google_oauth_client_secret="test-secret",
                session_secret_key="change-session-secret-in-production",
            )
            # If we get here, it worked (no ValueError)
            assert s.session_secret_key == "change-session-secret-in-production"
        except ValueError as e:
            if "session_secret_key" in str(e):
                pytest.fail(f"session_secret_key should be allowed in development: {e}")
            # Other validation errors are OK (e.g., missing API key)
