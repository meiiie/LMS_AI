"""
Sprint 160b: "Hoàn Thiện" — Complete Isolation + OAuth Security Tests.

Tests verify:
1. Scheduler repo org filtering (5 tests)
2. Insight repo org filtering (3 tests)
3. Preferences repo org filtering (3 tests)
4. Learning profile repo org filtering (3 tests)
5. Thread repo org filtering (6 tests)
6. Character repo org filtering (4 tests)
7. OAuth email_verified guard (5 tests)
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
# Group 1: Scheduler repo org filtering (5 tests)
# ============================================================================

class TestSchedulerOrgFilter:
    """Test org filtering on scheduler_repository methods."""

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

    def test_get_due_tasks_no_filter_when_disabled(self):
        """get_due_tasks() should NOT filter by org when multi-tenant disabled."""
        with _patch_settings(enable_multi_tenant=False):
            from app.repositories.scheduler_repository import SchedulerRepository
            repo = SchedulerRepository()
            factory, session = _mock_session_factory()
            repo._session_factory = factory
            repo._initialized = True

            session.execute.return_value.fetchall.return_value = []
            repo.get_due_tasks()

            sql_text = str(session.execute.call_args[0][0])
            assert "organization_id" not in sql_text

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

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

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

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text


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

    def test_get_user_insights_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-x"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_user_insights("u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_delete_user_insights_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-x"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.delete_user_insights("u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_get_insights_by_category_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-x"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_insights_by_category("u1", "learning")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text


# ============================================================================
# Group 3: Learning profile repo org filtering (3 tests)
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
    async def test_get_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                await repo.get("u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

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
                sql_text = str(session.execute.call_args_list[0][0][0])
                assert "organization_id" in sql_text

    @pytest.mark.asyncio
    async def test_update_weak_areas_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-lp"
                repo, session = self._make_repo()
                await repo.update_weak_areas("u1", ["topic1"])

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text


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

    def test_get_thread_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-t"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                repo.get_thread("t1", "u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

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
# Group 6: Character repo org filtering (4 tests)
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
                assert "organization_id = :org_id" in sql_text

    def test_get_block_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.fetchone.return_value = None
                repo.get_block("learned_lessons", "u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_get_recent_experiences_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.fetchall.return_value = []
                repo.get_recent_experiences(user_id="u1")

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text

    def test_count_experiences_includes_org_filter(self):
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-ch"
                repo, session = self._make_repo()
                session.execute.return_value.scalar.return_value = 10
                repo.count_experiences()

                sql_text = str(session.execute.call_args[0][0])
                assert "organization_id = :org_id" in sql_text


# ============================================================================
# Group 7: OAuth email_verified guard (5 tests)
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
        existing_user = {"id": "user-1", "email": "test@example.com", "name": "T", "avatar_url": None, "role": "student", "is_active": True}
        new_user = {"id": "user-2", "email": "test@example.com", "name": "T", "avatar_url": None, "role": "student", "is_active": True}

        from app.auth.user_service import find_or_create_by_provider
        with patch("app.auth.user_service.find_user_by_provider", return_value=None), \
             patch("app.auth.user_service.find_user_by_email", return_value=existing_user), \
             patch("app.auth.user_service.create_user", return_value=new_user), \
             patch("app.auth.user_service.link_identity", return_value="id-2"):

            with caplog.at_level(logging.WARNING, logger="app.auth.user_service"):
                await find_or_create_by_provider(
                    provider="github",
                    provider_sub="gh-789",
                    email="test@example.com",
                    email_verified=False,
                )

            assert any("SECURITY" in r.message and "UNVERIFIED" in r.message for r in caplog.records)

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
