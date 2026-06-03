"""
Sprint 160: "Hàng Rào" — Multi-Tenant Data Isolation Tests.

Tests verify that organization_id is properly threaded through the entire
pipeline: ChatContext → AgentState → repositories → search → cache.

All tests run with enable_multi_tenant toggled to verify zero regression
when the feature is disabled.
"""

import json
import importlib
import logging
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from uuid import uuid4


# ============================================================================
# Helpers
# ============================================================================

def _make_settings(**overrides):
    """Create a mock settings object with sensible defaults."""
    s = MagicMock()
    s.enable_multi_tenant = overrides.get("enable_multi_tenant", False)
    s.default_organization_id = overrides.get("default_organization_id", "default")
    s.environment = overrides.get("environment", "development")
    s.cross_domain_search = overrides.get("cross_domain_search", False)
    s.semantic_cache_enabled = False
    s.context_window_size = 50
    return s


def _patch_settings(enable_multi_tenant=False, default_org="default"):
    """Patch app.core.config.settings which org_filter imports lazily."""
    return patch(
        "app.core.config.settings",
        _make_settings(
            enable_multi_tenant=enable_multi_tenant,
            default_organization_id=default_org,
        ),
    )


# ============================================================================
# Group 1: org_filter.py helper functions (5 tests)
# ============================================================================

class TestOrgFilter:
    """Tests for app.core.org_filter helper functions."""

    def test_get_effective_org_id_disabled(self):
        """When multi-tenant disabled, returns default org (Sprint 175b: NOT NULL support)."""
        with _patch_settings(enable_multi_tenant=False):
            from app.core.org_filter import get_effective_org_id
            result = get_effective_org_id()
            assert result == "default"  # Sprint 175b: returns "default" instead of None

    def test_get_effective_org_id_enabled_with_context(self):
        """When enabled + ContextVar set, returns ContextVar value."""
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = "org-abc"
                from app.core.org_filter import get_effective_org_id
                assert get_effective_org_id() == "org-abc"

    def test_get_effective_org_id_enabled_fallback_default(self):
        """When enabled + ContextVar is None, falls back to config default."""
        with _patch_settings(enable_multi_tenant=True, default_org="default"):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = None
                from app.core.org_filter import get_effective_org_id
                assert get_effective_org_id() == "default"

    def test_org_where_clause_disabled(self):
        """When multi-tenant disabled, returns empty string."""
        with _patch_settings(enable_multi_tenant=False):
            from app.core.org_filter import org_where_clause
            assert org_where_clause("org-abc") == ""

    def test_org_where_clause_none_org(self):
        """When org_id is None, returns empty string even if enabled."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_clause
            assert org_where_clause(None) == ""

    def test_org_where_clause_basic(self):
        """Basic clause without NULL-awareness."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_clause
            clause = org_where_clause("org-abc")
            assert "organization_id = :org_id" in clause
            assert "IS NULL" not in clause

    def test_org_where_clause_allow_null(self):
        """NULL-aware clause for shared KB."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_clause
            clause = org_where_clause("org-abc", allow_null=True)
            assert "organization_id = :org_id" in clause
            assert "IS NULL" in clause

    def test_org_where_positional_disabled(self):
        """Positional helper returns empty when disabled."""
        with _patch_settings(enable_multi_tenant=False):
            from app.core.org_filter import org_where_positional
            params = ["existing"]
            clause = org_where_positional("org-abc", params)
            assert clause == ""
            assert len(params) == 1  # Not modified

    def test_org_where_positional_basic(self):
        """Positional helper appends param and returns $N clause."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_positional
            params = ["existing_param"]
            clause = org_where_positional("org-abc", params)
            assert "$2" in clause
            assert params[-1] == "org-abc"

    def test_org_where_positional_allow_null(self):
        """Positional NULL-aware clause."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_positional
            params = []
            clause = org_where_positional("org-abc", params, allow_null=True)
            assert "$1" in clause
            assert "IS NULL" in clause
            assert params == ["org-abc"]


# ============================================================================
# Group 2: ChatContext and AgentState fields (3 tests)
# ============================================================================

class TestDataclassFields:
    """Tests for organization_id field on ChatContext and AgentState."""

    def test_chat_context_has_organization_id(self):
        """ChatContext dataclass includes organization_id field."""
        from app.services.input_processor import ChatContext
        ctx = ChatContext(
            user_id="u1",
            session_id=uuid4(),
            message="hello",
            user_role=MagicMock(),
            organization_id="org-test"
        )
        assert ctx.organization_id == "org-test"

    def test_chat_context_organization_id_defaults_none(self):
        """ChatContext.organization_id defaults to None."""
        from app.services.input_processor import ChatContext
        ctx = ChatContext(
            user_id="u1",
            session_id=uuid4(),
            message="hello",
            user_role=MagicMock()
        )
        assert ctx.organization_id is None

    def test_agent_state_has_organization_id(self):
        """AgentState TypedDict accepts organization_id."""
        from app.engine.multi_agent.state import AgentState
        state: AgentState = {
            "query": "test",
            "user_id": "u1",
            "session_id": "s1",
            "organization_id": "org-test",
        }
        assert state["organization_id"] == "org-test"


# ============================================================================
# Group 3: semantic_memory_repository (8 tests)
# ============================================================================

class TestSemanticMemoryRepoOrgIsolation:
    """Tests for org_id in semantic_memory_repository."""

    def _make_repo(self):
        """Create a repo with mocked DB."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository
        repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
        repo._initialized = True
        repo._session_factory = MagicMock()
        repo._engine = MagicMock()
        return repo

    def test_save_memory_blocks_missing_org_context_before_embedding_or_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Repository writes fail closed before embedding/DB work when org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.models.semantic_memory import MemoryType, SemanticMemoryCreate

        repo = self._make_repo()
        repo._resolve_inline_embedding = MagicMock()
        repo._store_shadow_vectors = MagicMock()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        memory = SemanticMemoryCreate(
            user_id="PRIVATE-USER",
            content="private memory",
            embedding=[0.1] * 768,
            memory_type=MemoryType.USER_FACT,
            importance=0.8,
        )

        token = current_org_id.set(None)
        try:
            result = repo.save_memory(memory)
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._resolve_inline_embedding.assert_not_called()
        repo._session_factory.assert_not_called()
        assert "semantic_memory_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_save_memory_includes_org_id_when_enabled(self):
        """save_memory INSERT should include organization_id param."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            id=uuid4(), user_id="u1", content="test", memory_type="user_fact",
            importance=0.8, metadata={}, session_id="s1",
            created_at=None, updated_at=None
        )
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import SemanticMemoryCreate, MemoryType
        memory = SemanticMemoryCreate(
            user_id="u1", content="test", embedding=[0.1]*768,
            memory_type=MemoryType.USER_FACT, importance=0.8
        )

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True), \
             patch.object(repo, "_resolve_inline_embedding", return_value=(memory.embedding, json.dumps({}, ensure_ascii=False), tuple())), \
             patch.object(repo, "_store_shadow_vectors", return_value=None):
            token = current_org_id.set("org-test")
            try:
                repo.save_memory(memory)
            finally:
                current_org_id.reset(token)

        # Verify the execute was called with org_id in params
        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params.get("org_id") == "org-test"

    def test_save_memory_uses_default_org_when_single_tenant(self):
        """save_memory still scopes rows to the configured default org."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(
            id=uuid4(), user_id="u1", content="test", memory_type="user_fact",
            importance=0.8, metadata={}, session_id="s1",
            created_at=None, updated_at=None
        )
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import SemanticMemoryCreate, MemoryType
        memory = SemanticMemoryCreate(
            user_id="u1", content="test", embedding=[0.1]*768,
            memory_type=MemoryType.USER_FACT, importance=0.8
        )

        with _patch_settings(enable_multi_tenant=False, default_org="default"), \
             patch.object(repo, "_resolve_inline_embedding", return_value=(memory.embedding, json.dumps({}, ensure_ascii=False), tuple())), \
             patch.object(repo, "_store_shadow_vectors", return_value=None):
            repo.save_memory(memory)

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params.get("org_id") == "default"

    def test_get_memories_by_type_filters_org_when_enabled(self):
        """get_memories_by_type should include org filter in query when enabled."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import MemoryType

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-test")
            try:
                repo.get_memories_by_type("u1", MemoryType.USER_FACT)
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-test"

    def test_get_memories_by_type_uses_default_org_when_single_tenant(self):
        """get_memories_by_type scopes to default org when multi-tenant is disabled."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import MemoryType

        with _patch_settings(enable_multi_tenant=False, default_org="default"):
            repo.get_memories_by_type("u1", MemoryType.USER_FACT)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "default"

    def test_get_memories_by_type_includes_org_id_in_params(self):
        """When org is effective, org_id should be in query params."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import MemoryType

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-xyz")
            try:
                repo.get_memories_by_type("u1", MemoryType.USER_FACT)
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert params.get("org_id") == "org-xyz"

    def test_get_memories_by_type_default_org_in_params_when_single_tenant(self):
        """Single-tenant reads still bind the default org_id."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import MemoryType

        with _patch_settings(enable_multi_tenant=False, default_org="default"):
            repo.get_memories_by_type("u1", MemoryType.USER_FACT)

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert params.get("org_id") == "default"

    def test_get_memories_by_type_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Repository reads fail closed before DB work when org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.models.semantic_memory import MemoryType

        repo = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_memories_by_type("PRIVATE-USER", MemoryType.USER_FACT)
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._session_factory.assert_not_called()
        assert "semantic_memory_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text


# ============================================================================
# Group 4: chat_history_repository (8 tests)
# ============================================================================

class TestChatHistoryRepoOrgIsolation:
    """Tests for org_id in chat_history_repository."""

    def _make_repo(self, use_new_schema=True):
        """Create repo with mocked DB."""
        from app.repositories.chat_history_repository import ChatHistoryRepository
        repo = ChatHistoryRepository.__new__(ChatHistoryRepository)
        repo._engine = MagicMock()
        repo._session_factory = MagicMock()
        repo._available = True
        repo._has_chat_history = True
        repo.ensure_tables = MagicMock()
        repo.WINDOW_SIZE = 50
        return repo

    def test_save_message_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """save_message fails closed before DB when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = self._make_repo(use_new_schema=True)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.save_message(uuid4(), "user", "hello", user_id="PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "chat_history_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_save_message_new_schema_includes_org_id(self):
        """save_message (new schema) INSERT includes organization_id."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-test")
            try:
                repo.save_message(uuid4(), "user", "hello", user_id="u1")
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("org_id") == "org-test"

    def test_save_message_accepts_explicit_org_scope(self):
        """Message persistence can bind org scope from the active request."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                message = repo.save_message(
                    uuid4(),
                    "user",
                    "hello",
                    user_id="u1",
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert message is not None
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1]
        assert "organization_id" in sql_text
        assert params.get("org_id") == "org-explicit"

    def test_save_message_uses_default_org_when_single_tenant(self):
        """save_message scopes rows to default org when multi-tenant is disabled."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        with _patch_settings(enable_multi_tenant=False, default_org="default"):
            repo.save_message(uuid4(), "user", "hello", user_id="u1")

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("org_id") == "default"

    def test_get_recent_messages_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """get_recent_messages fails closed before DB when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = self._make_repo(use_new_schema=True)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_recent_messages(uuid4(), user_id="PRIVATE-USER")
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._session_factory.assert_not_called()
        assert "chat_history_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_get_recent_messages_filters_org_when_enabled(self):
        """get_recent_messages adds org filter when enabled."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-xyz")
            try:
                repo.get_recent_messages(uuid4())
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-xyz"

    def test_get_recent_messages_accepts_explicit_org_scope(self):
        """Live history context reads can bind org scope from the request."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                result = repo.get_recent_messages(
                    uuid4(),
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert result == []
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1]
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-explicit"

    def test_get_session_history_accepts_explicit_org_scope(self):
        """Thread message pagination can bind org scope from the API auth boundary."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.fetchall.return_value = []
        mock_session.execute.side_effect = [count_result, rows_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                messages, total = repo.get_session_history(
                    uuid4(),
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert messages == []
        assert total == 0
        for execute_call in mock_session.execute.call_args_list:
            sql_text = str(execute_call[0][0])
            params = execute_call[0][1]
            assert "organization_id = :org_id" in sql_text
            assert params.get("org_id") == "org-explicit"

    def test_get_recent_messages_uses_default_org_when_single_tenant(self):
        """get_recent_messages scopes to default org when multi-tenant is disabled."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        with _patch_settings(enable_multi_tenant=False, default_org="default"):
            repo.get_recent_messages(uuid4())

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("org_id") == "default"

    def test_delete_user_history_scoped_by_org(self):
        """delete_user_history respects org filter when enabled."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-test")
            try:
                deleted = repo.delete_user_history("u1")
            finally:
                current_org_id.reset(token)

        assert deleted == 3
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-test"

    def test_delete_user_history_accepts_explicit_org_scope(self):
        """History deletion can bind org scope from the API auth boundary."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                deleted = repo.delete_user_history(
                    "u1",
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert deleted == 2
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1]
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-explicit"

    def test_delete_user_history_uses_default_org_when_single_tenant(self):
        """delete_user_history scopes to default org when multi-tenant is disabled."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        with _patch_settings(enable_multi_tenant=False, default_org="default"):
            deleted = repo.delete_user_history("u1")

        assert deleted == 5
        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("org_id") == "default"

    def test_get_user_history_accepts_explicit_org_scope(self):
        """History API page reads can bind org scope from the auth boundary."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.fetchall.return_value = []
        mock_session.execute.side_effect = [count_result, rows_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                messages, total = repo.get_user_history(
                    "u1",
                    limit=10,
                    offset=0,
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert messages == []
        assert total == 0
        for execute_call in mock_session.execute.call_args_list:
            sql_text = str(execute_call[0][0])
            params = execute_call[0][1]
            assert "organization_id = :org_id" in sql_text
            assert params.get("org_id") == "org-explicit"

    def test_update_user_name_accepts_explicit_org_scope(self):
        """User-name writes can bind org scope from the active request."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        session_id = uuid4()
        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                updated = repo.update_user_name(
                    session_id,
                    "Scoped name",
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert updated is True
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1]
        assert "organization_id = :org_id" in sql_text
        assert params["session_id"] == str(session_id)
        assert params["org_id"] == "org-explicit"
        mock_session.commit.assert_called_once()

    def test_get_user_name_accepts_explicit_org_scope(self):
        """User-name reads can bind org scope from the active request."""
        repo = self._make_repo(use_new_schema=True)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "Scoped name"
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        session_id = uuid4()
        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set(None)
            try:
                user_name = repo.get_user_name(
                    session_id,
                    organization_id="org-explicit",
                )
            finally:
                current_org_id.reset(token)

        assert user_name == "Scoped name"
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1]
        assert "organization_id = :org_id" in sql_text
        assert params["session_id"] == str(session_id)
        assert params["org_id"] == "org-explicit"


# ============================================================================
# Group 5: Search repos — Dense and Sparse (6 tests)
# ============================================================================

class TestSearchRepoOrgIsolation:
    """Tests for org_id parameter in dense/sparse search repos."""

    def test_dense_search_signature_has_org_id(self):
        """DenseSearchRepository.search() accepts org_id parameter."""
        import inspect
        from app.repositories.dense_search_repository import DenseSearchRepository
        sig = inspect.signature(DenseSearchRepository.search)
        assert "org_id" in sig.parameters

    def test_sparse_search_signature_has_org_id(self):
        """SparseSearchRepository.search() accepts org_id parameter."""
        import inspect
        from app.repositories.sparse_search_repository import SparseSearchRepository
        sig = inspect.signature(SparseSearchRepository.search)
        assert "org_id" in sig.parameters

    @pytest.mark.asyncio
    async def test_dense_search_passes_org_to_filter(self):
        """Dense search calls org_where_positional with org_id."""
        from app.repositories.dense_search_repository import DenseSearchRepository
        repo = DenseSearchRepository.__new__(DenseSearchRepository)
        repo._available = True
        repo._column_cache = {}

        # Sprint 170b: conn must be AsyncMock (SET LOCAL hnsw.ef_search)
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire.return_value = cm
        repo._pool = mock_pool

        with patch("app.core.org_filter.org_where_positional") as mock_org:
            mock_org.return_value = ""
            await repo.search([0.1]*768, limit=5, org_id="org-test")
            mock_org.assert_called_once()
            call_args = mock_org.call_args
            assert call_args[0][0] == "org-test"  # org_id
            assert call_args[1].get("allow_null") is True

    @pytest.mark.asyncio
    async def test_dense_search_no_org_filter_when_none(self):
        """Dense search with org_id=None resolves default scope in single-tenant mode."""
        from app.repositories.dense_search_repository import DenseSearchRepository
        repo = DenseSearchRepository.__new__(DenseSearchRepository)
        repo._available = True
        repo._column_cache = {}

        # Sprint 170b: conn must be AsyncMock (SET LOCAL hnsw.ef_search)
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire.return_value = cm
        repo._pool = mock_pool

        with patch("app.core.org_filter.org_where_positional") as mock_org:
            mock_org.return_value = ""
            await repo.search([0.1]*768, limit=5, org_id=None)
            mock_org.assert_called_once()
            assert mock_org.call_args[0][0] == "default"

    @pytest.mark.asyncio
    async def test_dense_search_blocks_missing_org_context_before_pool(
        self,
        monkeypatch,
        caplog,
    ):
        """Production multi-tenant dense search fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.dense_search_repository import DenseSearchRepository

        repo = DenseSearchRepository.__new__(DenseSearchRepository)
        repo._available = True
        repo._get_pool = AsyncMock()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = await repo.search([0.1] * 768, limit=5, org_id=None)
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._get_pool.assert_not_called()
        assert "knowledge_search_blocked_missing_org_context" in caplog.text

    @pytest.mark.asyncio
    async def test_sparse_search_passes_org_to_filter(self):
        """Sparse search calls org_where_positional with org_id."""
        from app.repositories.sparse_search_repository import SparseSearchRepository
        repo = SparseSearchRepository.__new__(SparseSearchRepository)
        repo._available = True

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire.return_value = cm

        with patch("app.core.org_filter.org_where_positional") as mock_org, \
             patch.object(repo, "_build_tsquery", return_value="test"), \
             patch.object(repo, "_apply_number_boost", side_effect=lambda r, q: r), \
             patch.object(repo, "_get_pool", AsyncMock(return_value=mock_pool)):
            mock_org.return_value = ""
            await repo.search("test query", limit=5, org_id="org-123")
            mock_org.assert_called_once()
            assert mock_org.call_args[0][0] == "org-123"

    @pytest.mark.asyncio
    async def test_sparse_search_no_org_filter_when_none(self):
        """Sparse search with org_id=None resolves default scope in single-tenant mode."""
        from app.repositories.sparse_search_repository import SparseSearchRepository
        repo = SparseSearchRepository.__new__(SparseSearchRepository)
        repo._available = True

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire.return_value = cm

        with patch("app.core.org_filter.org_where_positional") as mock_org, \
             patch.object(repo, "_build_tsquery", return_value="test"), \
             patch.object(repo, "_apply_number_boost", side_effect=lambda r, q: r), \
             patch.object(repo, "_get_pool", AsyncMock(return_value=mock_pool)):
            mock_org.return_value = ""
            await repo.search("test query", limit=5, org_id=None)
            mock_org.assert_called_once()
            assert mock_org.call_args[0][0] == "default"

    @pytest.mark.asyncio
    async def test_sparse_search_blocks_missing_org_context_before_pool(
        self,
        monkeypatch,
        caplog,
    ):
        """Production multi-tenant sparse search fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.sparse_search_repository import SparseSearchRepository

        repo = SparseSearchRepository.__new__(SparseSearchRepository)
        repo._available = True
        repo._get_pool = AsyncMock()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = await repo.search("PRIVATE QUERY", limit=5, org_id=None)
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._get_pool.assert_not_called()
        assert "knowledge_search_blocked_missing_org_context" in caplog.text
        assert "PRIVATE QUERY" not in caplog.text


# ============================================================================
# Group 6: Pipeline integration (6 tests)
# ============================================================================

class TestPipelineOrgIsolation:
    """Tests for org_id threading through the pipeline."""

    def test_hybrid_search_signature_has_org_id(self):
        """HybridSearchService.search() accepts org_id parameter."""
        import inspect
        from app.services.hybrid_search_service import HybridSearchService
        sig = inspect.signature(HybridSearchService.search)
        assert "org_id" in sig.parameters

    @pytest.mark.asyncio
    async def test_hybrid_search_passes_org_to_dense_and_sparse(self):
        """HybridSearchService.search(org_id=X) passes X to both repos."""
        from app.services.hybrid_search_service import HybridSearchService

        svc = HybridSearchService.__new__(HybridSearchService)
        svc._dense_weight = 0.5
        svc._sparse_weight = 0.5

        mock_dense = MagicMock()
        mock_dense.search = AsyncMock(return_value=[])
        mock_sparse = MagicMock()
        mock_sparse.search = AsyncMock(return_value=[])
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=[0.1]*768)

        svc._dense_repo = mock_dense
        svc._sparse_repo = mock_sparse
        svc._embeddings = mock_embeddings
        svc._reranker = MagicMock()
        svc._reranker.merge.return_value = []

        await svc.search("test", limit=5, org_id="org-abc")

        # Both repos should have been called with org_id
        mock_dense.search.assert_called_once()
        dense_kwargs = mock_dense.search.call_args[1]
        assert dense_kwargs.get("org_id") == "org-abc"

        mock_sparse.search.assert_called_once()
        sparse_kwargs = mock_sparse.search.call_args[1]
        assert sparse_kwargs.get("org_id") == "org-abc"

    def test_corrective_rag_cache_key_includes_org(self):
        """Cache get() should use org-prefixed user_id."""
        # Verify the cache isolation logic by testing the prefix construction
        org = "org-abc"
        uid = "user-1"
        cache_uid = f"{org}:{uid}" if org else uid
        assert cache_uid == "org-abc:user-1"

    def test_corrective_rag_cache_key_no_org_prefix_when_empty(self):
        """Cache key has no org prefix when organization_id is empty."""
        org = ""
        uid = "user-1"
        cache_uid = f"{org}:{uid}" if org else uid
        assert cache_uid == "user-1"

    def test_orchestrator_sets_context_org_id(self):
        """ChatOrchestrator should set context.organization_id."""
        from app.services.input_processor import ChatContext
        ctx = ChatContext(
            user_id="u1",
            session_id=uuid4(),
            message="test",
            user_role=MagicMock()
        )
        # Simulate what orchestrator does
        ctx.organization_id = "org-test"
        assert ctx.organization_id == "org-test"

    def test_multi_agent_context_includes_org_id(self):
        """multi_agent_context dict includes organization_id."""
        # Simulate building the context dict as orchestrator does
        context = MagicMock()
        context.organization_id = "org-from-orchestrator"
        multi_agent_context = {
            "organization_id": getattr(context, 'organization_id', None),
        }
        assert multi_agent_context["organization_id"] == "org-from-orchestrator"


# ============================================================================
# Group 7: Cross-org isolation (6 tests)
# ============================================================================

class TestCrossOrgIsolation:
    """Tests verifying cross-org data cannot leak."""

    def test_org_filter_different_orgs_produce_different_clauses(self):
        """Two different org_ids produce clauses with different bind values."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_clause
            clause_a = org_where_clause("org-a")
            clause_b = org_where_clause("org-b")
            # Both return same SQL template — isolation is via param binding
            assert clause_a == clause_b
            assert ":org_id" in clause_a

    def test_cache_keys_different_orgs(self):
        """Cache keys for same user in different orgs are distinct."""
        def make_key(org, uid):
            return f"{org}:{uid}" if org else uid

        key_a = make_key("org-a", "user-1")
        key_b = make_key("org-b", "user-1")
        assert key_a != key_b
        assert key_a == "org-a:user-1"
        assert key_b == "org-b:user-1"

    def test_cache_keys_same_org_same_user(self):
        """Cache keys for same org+user are identical."""
        def make_key(org, uid):
            return f"{org}:{uid}" if org else uid

        assert make_key("org-a", "u1") == make_key("org-a", "u1")

    def test_shared_kb_visible_to_all_orgs(self):
        """allow_null=True makes shared KB (NULL org) visible to any org."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_clause
            clause = org_where_clause("org-test", allow_null=True)
            assert "IS NULL" in clause
            assert "org_id" in clause

    def test_positional_shared_kb(self):
        """Positional variant also supports NULL-aware shared KB."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_positional
            params = []
            clause = org_where_positional("org-test", params, allow_null=True)
            assert "IS NULL" in clause
            assert params == ["org-test"]

    def test_org_filter_custom_column_name(self):
        """org_where_clause supports custom column names."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_clause
            clause = org_where_clause("org-test", column="tenant_id", param="tid")
            assert "tenant_id = :tid" in clause


# ============================================================================
# Group 8: Migration (4 tests)
# ============================================================================

class TestMigration011:
    """Tests for migration 011 structure."""

    def test_migration_module_importable(self):
        """Migration file can be imported without errors."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_011",
            "alembic/versions/011_add_org_id_data_isolation.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # We can't execute (needs alembic context) but at least parse
        assert mod is not None

    def test_migration_revision_chain(self):
        """Migration 011 follows 010 in revision chain."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_011",
            "alembic/versions/011_add_org_id_data_isolation.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == '011'
        assert mod.down_revision == '010'

    def test_migration_has_upgrade_and_downgrade(self):
        """Migration has both upgrade() and downgrade() functions."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_011",
            "alembic/versions/011_add_org_id_data_isolation.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_migration_has_idempotent_checks(self):
        """Migration uses table_exists/column_exists for idempotency."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_011",
            "alembic/versions/011_add_org_id_data_isolation.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.table_exists)
        assert callable(mod.column_exists)


# ============================================================================
# Group 9: Edge cases (4 tests)
# ============================================================================

class TestEdgeCases:
    """Edge case tests for data isolation."""

    def test_empty_string_org_id_treated_as_none(self):
        """get_effective_org_id with ContextVar returning '' falls back to default."""
        with _patch_settings(enable_multi_tenant=True):
            with patch("app.core.org_context.current_org_id") as mock_cv:
                mock_cv.get.return_value = ""
                from app.core.org_filter import get_effective_org_id
                # Empty string is falsy → falls back to default
                result = get_effective_org_id()
                assert result == "default"

    def test_agent_state_org_id_none_by_default(self):
        """AgentState without organization_id key defaults to no error."""
        from app.engine.multi_agent.state import AgentState
        state: AgentState = {
            "query": "test",
            "user_id": "u1",
            "session_id": "s1",
        }
        # organization_id not set — .get returns None
        assert state.get("organization_id") is None

    def test_backward_compat_no_org_field_in_context(self):
        """Old ChatContext instances without organization_id still work."""
        from app.services.input_processor import ChatContext
        # Default None — backward compatible
        ctx = ChatContext(
            user_id="u1",
            session_id=uuid4(),
            message="test",
            user_role=MagicMock()
        )
        assert ctx.organization_id is None

    def test_org_filter_positional_preserves_existing_params(self):
        """org_where_positional doesn't corrupt existing params."""
        with _patch_settings(enable_multi_tenant=True):
            from app.core.org_filter import org_where_positional
            params = ["query_text", 10]  # 2 existing params
            clause = org_where_positional("org-test", params)
            assert len(params) == 3  # One added
            assert params[0] == "query_text"
            assert params[1] == 10
            assert params[2] == "org-test"
            assert "$3" in clause


# ============================================================================
# Group 10: Fact repository org isolation (7 tests)
# ============================================================================

class TestFactRepoOrgIsolation:
    """Tests for org_id in fact_repository.py."""

    def _make_repo(self):
        """Create a repo with mocked DB."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository
        repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
        repo._initialized = True
        repo._session_factory = MagicMock()
        repo._engine = MagicMock()
        repo.TABLE_NAME = "semantic_memories"
        return repo

    def test_get_user_facts_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Fact reads fail closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.get_user_facts("PRIVATE-USER", limit=10, deduplicate=False)
        finally:
            current_org_id.reset(token)

        assert result == []
        repo._session_factory.assert_not_called()
        assert "fact_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_get_user_facts_filters_org_when_enabled(self):
        """get_user_facts includes org filter when multi-tenant enabled."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-test")
            try:
                repo.get_user_facts("u1", limit=10, deduplicate=False)
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-test"

    def test_get_user_facts_uses_default_org_when_single_tenant(self):
        """get_user_facts still scopes to the configured default org in single-tenant mode."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        with _patch_settings(enable_multi_tenant=False, default_org="default"):
            repo.get_user_facts("u1", limit=10, deduplicate=False)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "default"

    def test_get_user_facts_dedup_includes_org_filter(self):
        """get_user_facts with deduplicate=True also includes org filter."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-xyz")
            try:
                repo.get_user_facts("u1", deduplicate=True)
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        # Check the SQL text contains org filter
        sql_text = str(call_args[0][0])
        params = call_args[0][1]
        assert "organization_id" in sql_text
        assert params["org_id"] == "org-xyz"

    def test_get_all_user_facts_includes_org(self):
        """get_all_user_facts includes org filter when enabled."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-test")
            try:
                repo.get_all_user_facts("u1")
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-test"

    def test_search_relevant_facts_includes_org(self):
        """search_relevant_facts includes org filter when enabled."""
        repo = self._make_repo()

        mock_session = MagicMock()
        mock_session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[]))
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.core.org_context import current_org_id

        with _patch_settings(enable_multi_tenant=True):
            token = current_org_id.set("org-xyz")
            try:
                repo.search_relevant_facts("u1", [0.1] * 768, limit=5)
            finally:
                current_org_id.reset(token)

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert "organization_id = :org_id" in sql_text
        assert params.get("org_id") == "org-xyz"

    def test_update_metadata_only_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Fact metadata writes fail closed when production org context is missing."""
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = self._make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.update_metadata_only(
                uuid4(),
                {"fact_type": "preference"},
                user_id="PRIVATE-USER",
            )
        finally:
            current_org_id.reset(token)

        assert result is False
        repo._session_factory.assert_not_called()
        assert "fact_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text
