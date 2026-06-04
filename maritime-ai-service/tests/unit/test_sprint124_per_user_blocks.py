"""
Sprint 124: Per-User Character Blocks — User Isolation Tests

Tests:
1. Repository: user_id filtering in all CRUD operations
2. State Manager: per-user cache isolation
3. Character Tools: ContextVar isolation
4. Prompt Loader: user_id forwarded to compile_living_state
5. Character API: auth user filtering
6. Consolidation: per-user scoping
7. Backward compat: __global__ default works
"""

import sys
import types
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

# Break circular import (standard pattern)
_cs_key = "app.services.chat_service"
if _cs_key not in sys.modules:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs


# =============================================================================
# Phase 1: Repository — user_id in all queries
# =============================================================================

class TestCharacterRepositoryUserIsolation:
    """Verify repository methods accept and use user_id parameter."""

    def _make_repo(self):
        from app.core.database import clear_shared_database_unavailable
        from app.engine.character.character_repository import CharacterRepository

        # These tests provide their own healthy session factory; keep them
        # isolated from earlier outage simulations in the shared DB module.
        clear_shared_database_unavailable()

        repo = CharacterRepository()
        repo._initialized = True
        repo._session_factory = MagicMock()
        return repo

    def test_get_all_blocks_default_user_id(self):
        """get_all_blocks() defaults to '__global__'."""
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        result = repo.get_all_blocks()
        assert result == []
        # Verify user_id was passed in params
        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("parameters", {})
        assert params.get("user_id") == "__global__"

    def test_get_all_blocks_custom_user_id(self):
        """get_all_blocks(user_id='user-A') filters by user-A."""
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo.get_all_blocks(user_id="user-A")
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["user_id"] == "user-A"

    def test_get_block_with_user_id(self):
        """get_block() passes user_id to WHERE clause."""
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo.get_block("self_notes", user_id="user-B")
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["label"] == "self_notes"
        assert params["user_id"] == "user-B"

    def test_create_block_with_user_id(self):
        """create_block() includes user_id in INSERT."""
        from app.engine.character.models import CharacterBlockCreate
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.label = "self_notes"
        mock_row.content = ""
        mock_row.char_limit = 1000
        mock_row.version = 1
        mock_row.metadata = {}
        mock_row.created_at = None
        mock_row.updated_at = None
        mock_session.execute.return_value.fetchone.return_value = mock_row
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo.create_block(
            CharacterBlockCreate(label="self_notes", content="", char_limit=1000),
            user_id="user-C",
        )
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["user_id"] == "user-C"

    def test_update_block_replace_with_user_id(self):
        """update_block() replace mode includes user_id in WHERE."""
        from app.engine.character.models import CharacterBlockUpdate
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.label = "self_notes"
        mock_row.content = "new content"
        mock_row.char_limit = 1000
        mock_row.version = 2
        mock_row.metadata = {}
        mock_row.created_at = None
        mock_row.updated_at = None
        mock_session.execute.return_value.fetchone.return_value = mock_row
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo.update_block(
            "self_notes",
            CharacterBlockUpdate(content="new content"),
            user_id="user-D",
        )
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["user_id"] == "user-D"

    def test_update_block_append_with_user_id(self):
        """update_block() append mode includes user_id in WHERE."""
        from app.engine.character.models import CharacterBlockUpdate
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.label = "learned_lessons"
        mock_row.content = "appended"
        mock_row.char_limit = 1500
        mock_row.version = 3
        mock_row.metadata = {}
        mock_row.created_at = None
        mock_row.updated_at = None
        mock_session.execute.return_value.fetchone.return_value = mock_row
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo.update_block(
            "learned_lessons",
            CharacterBlockUpdate(append="\n- new lesson"),
            user_id="user-E",
        )
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["user_id"] == "user-E"

    def test_update_block_no_content_no_append_delegates_get_block(self):
        """update_block() with neither content nor append calls get_block with user_id."""
        from app.engine.character.models import CharacterBlockUpdate
        repo = self._make_repo()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        result = repo.update_block(
            "self_notes",
            CharacterBlockUpdate(),  # No content, no append
            user_id="user-F",
        )
        # Should call get_block which also uses user_id
        # The get_block call uses user_id in its WHERE clause
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["user_id"] == "user-F"


# =============================================================================
# Phase 2: State Manager — per-user cache isolation
# =============================================================================

class TestCharacterStateManagerPerUser:
    """Verify per-user cache and method isolation."""

    def _make_manager(self):
        from app.engine.character.character_state import CharacterStateManager
        return CharacterStateManager()

    def test_cache_is_per_user(self):
        """Different users have separate cache entries."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock

        # Manually populate caches for two users
        block_a = CharacterBlock(label="self_notes", content="User A note", char_limit=1000, version=1)
        block_b = CharacterBlock(label="self_notes", content="User B note", char_limit=1000, version=1)
        import time
        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._cache[key_a] = {"self_notes": block_a}
        mgr._cache_timestamp[key_a] = time.time()
        mgr._cache[key_b] = {"self_notes": block_b}
        mgr._cache_timestamp[key_b] = time.time()

        blocks_a = mgr.get_blocks(user_id="user-A")
        blocks_b = mgr.get_blocks(user_id="user-B")
        assert blocks_a["self_notes"].content == "User A note"
        assert blocks_b["self_notes"].content == "User B note"

    def test_cache_is_per_org_for_same_user(self, monkeypatch):
        """The same user gets separate cache entries per organization."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.character.models import CharacterBlock
        import time

        mgr = self._make_manager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            key_a = mgr._cache_key(user_id="same-user")
        finally:
            current_org_id.reset(token)

        token = current_org_id.set("org-B")
        try:
            key_b = mgr._cache_key(user_id="same-user")
        finally:
            current_org_id.reset(token)

        assert key_a != key_b
        mgr._cache[key_a] = {
            "self_notes": CharacterBlock(
                label="self_notes",
                content="Org A note",
                char_limit=1000,
                version=1,
            )
        }
        mgr._cache_timestamp[key_a] = time.time()
        mgr._cache[key_b] = {
            "self_notes": CharacterBlock(
                label="self_notes",
                content="Org B note",
                char_limit=1000,
                version=1,
            )
        }
        mgr._cache_timestamp[key_b] = time.time()

        token = current_org_id.set("org-A")
        try:
            blocks_a = mgr.get_blocks(user_id="same-user")
        finally:
            current_org_id.reset(token)

        token = current_org_id.set("org-B")
        try:
            blocks_b = mgr.get_blocks(user_id="same-user")
        finally:
            current_org_id.reset(token)

        assert blocks_a["self_notes"].content == "Org A note"
        assert blocks_b["self_notes"].content == "Org B note"

    def test_get_block_returns_user_specific(self):
        """get_block returns block for the specified user only."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock
        import time

        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._cache[key_a] = {
            "learned_lessons": CharacterBlock(label="learned_lessons", content="A's lessons", char_limit=1500, version=1)
        }
        mgr._cache_timestamp[key_a] = time.time()
        mgr._cache[key_b] = {
            "learned_lessons": CharacterBlock(label="learned_lessons", content="B's lessons", char_limit=1500, version=1)
        }
        mgr._cache_timestamp[key_b] = time.time()

        block_a = mgr.get_block("learned_lessons", user_id="user-A")
        block_b = mgr.get_block("learned_lessons", user_id="user-B")
        assert block_a.content == "A's lessons"
        assert block_b.content == "B's lessons"

    def test_get_block_returns_none_for_unknown_user(self):
        """get_block returns None for user with no cached blocks."""
        mgr = self._make_manager()
        import time
        key_a = mgr._cache_key(user_id="user-A")
        mgr._cache[key_a] = {}
        mgr._cache_timestamp[key_a] = time.time()

        result = mgr.get_block("self_notes", user_id="user-A")
        assert result is None

    def test_invalidate_cache_specific_user(self):
        """invalidate_cache(user_id) only clears that user's cache."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock
        import time

        block = CharacterBlock(label="self_notes", content="test", char_limit=1000, version=1)
        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._cache[key_a] = {"self_notes": block}
        mgr._cache_timestamp[key_a] = time.time()
        mgr._cache[key_b] = {"self_notes": block}
        mgr._cache_timestamp[key_b] = time.time()

        mgr.invalidate_cache(user_id="user-A")

        assert key_a not in mgr._cache
        assert key_b in mgr._cache

    def test_invalidate_cache_all_users(self):
        """invalidate_cache() with no args clears ALL user caches."""
        mgr = self._make_manager()
        import time
        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._cache[key_a] = {}
        mgr._cache_timestamp[key_a] = time.time()
        mgr._cache[key_b] = {}
        mgr._cache_timestamp[key_b] = time.time()

        mgr.invalidate_cache()

        assert len(mgr._cache) == 0
        assert len(mgr._cache_timestamp) == 0

    def test_update_block_updates_per_user_cache(self):
        """update_block() updates the correct user's cache entry."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock

        mock_repo = MagicMock()
        updated = CharacterBlock(label="self_notes", content="updated", char_limit=1000, version=2)
        mock_repo.update_block.return_value = updated

        with patch.object(mgr, '_get_repo', return_value=mock_repo):
            result = mgr.update_block("self_notes", content="updated", user_id="user-A")

        assert result == updated
        key_a = mgr._cache_key(user_id="user-A")
        assert mgr._cache[key_a]["self_notes"].content == "updated"

    def test_ensure_defaults_per_user(self):
        """_ensure_defaults seeds blocks for each user independently."""
        mgr = self._make_manager()
        mock_repo = MagicMock()
        mock_repo.get_all_blocks.return_value = []  # No existing blocks
        mock_repo.create_block.return_value = None

        with patch.object(mgr, '_get_repo', return_value=mock_repo):
            mgr._ensure_defaults(user_id="user-A")
            first_call_count = mock_repo.create_block.call_count

            mgr._ensure_defaults(user_id="user-B")
            second_call_count = mock_repo.create_block.call_count - first_call_count

        # Both users should get defaults created
        assert first_call_count > 0
        assert second_call_count > 0
        assert mgr._cache_key(user_id="user-A") in mgr._initialized_defaults
        assert mgr._cache_key(user_id="user-B") in mgr._initialized_defaults

    def test_ensure_defaults_idempotent_per_user(self):
        """_ensure_defaults doesn't re-seed for the same user."""
        mgr = self._make_manager()
        mock_repo = MagicMock()
        mock_repo.get_all_blocks.return_value = []
        mock_repo.create_block.return_value = None

        with patch.object(mgr, '_get_repo', return_value=mock_repo):
            mgr._ensure_defaults(user_id="user-A")
            count1 = mock_repo.create_block.call_count
            mgr._ensure_defaults(user_id="user-A")  # Should be no-op
            count2 = mock_repo.create_block.call_count

        assert count1 == count2, "Second call should not create more blocks"

    def test_compile_living_state_per_user(self):
        """compile_living_state returns user-specific block content."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock
        import time

        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._initialized_defaults.add(key_a)
        mgr._initialized_defaults.add(key_b)

        mgr._cache[key_a] = {
            "learned_lessons": CharacterBlock(label="learned_lessons", content="Rule 15 important", char_limit=1500, version=1),
            "self_notes": CharacterBlock(label="self_notes", content="", char_limit=1000, version=1),
        }
        mgr._cache_timestamp[key_a] = time.time()

        mgr._cache[key_b] = {
            "learned_lessons": CharacterBlock(label="learned_lessons", content="MARPOL Annex I", char_limit=1500, version=1),
            "self_notes": CharacterBlock(label="self_notes", content="", char_limit=1000, version=1),
        }
        mgr._cache_timestamp[key_b] = time.time()

        state_a = mgr.compile_living_state(user_id="user-A")
        state_b = mgr.compile_living_state(user_id="user-B")

        assert "Rule 15" in state_a
        assert "MARPOL" not in state_a
        assert "MARPOL" in state_b
        assert "Rule 15" not in state_b

    def test_compile_living_state_empty_user_returns_empty(self):
        """compile_living_state returns '' for user with no content."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock
        import time

        key_c = mgr._cache_key(user_id="user-C")
        mgr._initialized_defaults.add(key_c)
        mgr._cache[key_c] = {
            "self_notes": CharacterBlock(label="self_notes", content="", char_limit=1000, version=1),
        }
        mgr._cache_timestamp[key_c] = time.time()

        state = mgr.compile_living_state(user_id="user-C")
        assert state == ""

    def test_needs_consolidation_per_user(self):
        """needs_consolidation checks blocks for specific user."""
        mgr = self._make_manager()
        from app.engine.character.models import CharacterBlock
        import time

        # User A: block at 90% full
        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._cache[key_a] = {
            "self_notes": CharacterBlock(label="self_notes", content="x" * 900, char_limit=1000, version=1),
        }
        mgr._cache_timestamp[key_a] = time.time()

        # User B: block at 10% full
        mgr._cache[key_b] = {
            "self_notes": CharacterBlock(label="self_notes", content="x" * 100, char_limit=1000, version=1),
        }
        mgr._cache_timestamp[key_b] = time.time()

        assert mgr.needs_consolidation("self_notes", user_id="user-A") is True
        assert mgr.needs_consolidation("self_notes", user_id="user-B") is False


# =============================================================================
# Phase 3: Character Tools — ContextVar isolation
# =============================================================================

class TestCharacterToolsContextVar:
    """Verify ContextVar-based user isolation in character tools."""

    def test_set_character_user(self):
        """set_character_user sets the ContextVar."""
        from app.engine.character.character_tools import set_character_user, _character_user_id
        set_character_user("user-123")
        assert _character_user_id.get() == "user-123"

    def test_get_user_id_returns_contextvar_value(self):
        """_get_user_id returns value from ContextVar."""
        from app.engine.character.character_tools import set_character_user, _get_user_id
        set_character_user("user-xyz")
        assert _get_user_id() == "user-xyz"

    def test_set_character_user_replaces_previous_identity(self):
        """Changing user context should replace living-character tool state."""
        from app.engine.character.character_tools import (
            _get_state,
            set_character_user,
        )

        set_character_user("user-a")
        first_state = _get_state()

        set_character_user("user-b")
        second_state = _get_state()

        assert second_state is not first_state
        assert second_state.user_id == "user-b"
        assert "user=user-b" in (second_state.identity_key or "")

    def test_runtime_context_identity_isolates_character_state(self):
        """Runtime org/session identity should prevent character state reuse."""
        from app.engine.character.character_tools import _get_state, set_character_user
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        ctx_a = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-a",
            session_id="session-a",
        )
        ctx_b = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-b",
            session_id="session-a",
        )

        with tool_runtime_scope(ctx_a):
            set_character_user("user-a")
            state_a = _get_state()
            assert state_a.user_id == "user-a"
            assert state_a.organization_id == "org-a"
            assert "org=org-a" in (state_a.identity_key or "")

        with tool_runtime_scope(ctx_b):
            state_b = _get_state()
            assert state_b is not state_a
            assert state_b.user_id == "user-a"
            assert state_b.organization_id == "org-b"
            assert "org=org-b" in (state_b.identity_key or "")

    def test_get_user_id_defaults_to_global(self):
        """_get_user_id returns '__global__' when ContextVar not set."""
        from app.engine.character.character_tools import _character_user_id, _get_user_id
        _character_user_id.set(None)
        assert _get_user_id() == "__global__"

    def test_tool_character_note_uses_contextvar_user(self):
        """tool_character_note passes ContextVar user_id to manager."""
        from app.engine.character.character_tools import (
            tool_character_note, set_character_user
        )
        set_character_user("user-note-test")

        mock_manager = MagicMock()
        mock_block = MagicMock()
        mock_block.remaining_chars.return_value = 500
        mock_manager.update_block.return_value = mock_block

        # Lazy import — patch at source module
        with patch(
            "app.engine.character.character_state.get_character_state_manager",
            return_value=mock_manager,
        ):
            result = tool_character_note.invoke({"note": "test note", "block": "self_notes"})

        mock_manager.update_block.assert_called_once()
        call_kwargs = mock_manager.update_block.call_args
        assert call_kwargs[1]["user_id"] == "user-note-test"

    def test_tool_character_note_passes_runtime_org(self):
        """tool_character_note should pass runtime org scope to manager."""
        from app.engine.character.character_tools import (
            set_character_user,
            tool_character_note,
        )
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        mock_manager = MagicMock()
        mock_block = MagicMock()
        mock_block.remaining_chars.return_value = 500
        mock_manager.update_block.return_value = mock_block

        runtime = build_tool_runtime_context(
            user_id="user-note-org",
            organization_id="org-note",
            session_id="session-note",
        )
        with tool_runtime_scope(runtime):
            set_character_user("user-note-org")
            with patch(
                "app.engine.character.character_state.get_character_state_manager",
                return_value=mock_manager,
            ):
                tool_character_note.invoke({"note": "test note", "block": "self_notes"})

        call_kwargs = mock_manager.update_block.call_args.kwargs
        assert call_kwargs["user_id"] == "user-note-org"
        assert call_kwargs["organization_id"] == "org-note"

    def test_tool_character_read_uses_contextvar_user(self):
        """tool_character_read reads blocks for ContextVar user."""
        from app.engine.character.character_tools import (
            tool_character_read, set_character_user
        )
        set_character_user("user-read-test")

        mock_manager = MagicMock()
        # Use a proper MagicMock for the block, with content as a real string
        mock_block = MagicMock()
        mock_block.content = "my notes"
        mock_manager.get_block.return_value = mock_block

        # Lazy import — patch at source module
        with patch(
            "app.engine.character.character_state.get_character_state_manager",
            return_value=mock_manager,
        ):
            result = tool_character_read.invoke({"block": "self_notes"})

        mock_manager.get_block.assert_called_once_with("self_notes", user_id="user-read-test")

    def test_tool_character_log_experience_passes_runtime_org(self):
        """tool_character_log_experience should pass runtime org scope to repo."""
        from app.engine.character.character_tools import (
            set_character_user,
            tool_character_log_experience,
        )
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        mock_repo = MagicMock()
        mock_repo.log_experience.return_value = MagicMock()

        runtime = build_tool_runtime_context(
            user_id="user-exp-org",
            organization_id="org-exp",
            session_id="session-exp",
        )
        with tool_runtime_scope(runtime):
            set_character_user("user-exp-org")
            with patch(
                "app.engine.character.character_repository.get_character_repository",
                return_value=mock_repo,
            ):
                tool_character_log_experience.invoke({
                    "content": "learned one thing",
                    "experience_type": "learning",
                })

        call_kwargs = mock_repo.log_experience.call_args.kwargs
        assert call_kwargs["organization_id"] == "org-exp"
        assert mock_repo.log_experience.call_args.args[0].user_id == "user-exp-org"

    def test_tool_character_note_invalid_block(self):
        """tool_character_note rejects invalid block labels."""
        from app.engine.character.character_tools import tool_character_note
        result = tool_character_note.invoke({"note": "test", "block": "invalid_block"})
        assert "không hợp lệ" in result


# =============================================================================
# Phase 4: Prompt Loader — user_id forwarded
# =============================================================================

class TestPromptLoaderUserIdForwarding:
    """Verify build_system_prompt forwards user_id to compile_living_state."""

    def test_build_system_prompt_passes_user_id_via_kwargs(self):
        """build_system_prompt(**kwargs) forwards user_id to compile_living_state."""
        # Lazy import inside build_system_prompt — patch at source module
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_get_mgr.return_value = mock_mgr

            from app.prompts.prompt_loader import PromptLoader
            loader = PromptLoader()
            loader.build_system_prompt(
                role="student",
                user_id="user-prompt-test",
            )

            mock_mgr.compile_living_state.assert_called_once_with(
                user_id="user-prompt-test",
                organization_id=None,
            )

    def test_build_system_prompt_defaults_to_global(self):
        """build_system_prompt without user_id defaults to '__global__'."""
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_get_mgr.return_value = mock_mgr

            from app.prompts.prompt_loader import PromptLoader
            loader = PromptLoader()
            loader.build_system_prompt(role="student")

            mock_mgr.compile_living_state.assert_called_once_with(
                user_id="__global__",
                organization_id=None,
            )

    def test_build_system_prompt_accepts_kwargs(self):
        """build_system_prompt accepts **kwargs without error."""
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_get_mgr.return_value = mock_mgr

            from app.prompts.prompt_loader import PromptLoader
            loader = PromptLoader()
            # Should not raise
            result = loader.build_system_prompt(
                role="student",
                user_id="test",
                extra_kwarg="should-be-ignored",
            )
            assert isinstance(result, str)


# =============================================================================
# Phase 5: Character API — auth user filtering
# =============================================================================

class TestCharacterAPIUserFiltering:
    """Verify API endpoint uses auth.user_id for filtering."""

    @pytest.mark.asyncio
    async def test_get_character_state_uses_auth_user_id(self):
        """API should call get_blocks(user_id=auth.user_id)."""
        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}

        mock_auth = MagicMock()
        mock_auth.user_id = "api-user-123"
        mock_auth.organization_id = "org-api"

        mock_settings = MagicMock()
        mock_settings.enable_character_tools = True

        # Lazy imports inside endpoint — patch at source modules
        with patch(
            "app.engine.character.character_state.get_character_state_manager",
            return_value=mock_manager,
        ), patch(
            "app.core.config.settings", mock_settings,
        ):
            from app.api.v1.character import get_character_state
            mock_request = MagicMock()
            result = await get_character_state(request=mock_request, auth=mock_auth)

        mock_manager.get_blocks.assert_called_once_with(
            user_id="api-user-123",
            organization_id="org-api",
        )


# =============================================================================
# Phase 6: Consolidation — per-user scoping
# =============================================================================

class TestConsolidationPerUser:
    """Verify consolidation only affects target user's blocks."""

    @pytest.mark.asyncio
    async def test_consolidate_full_blocks_per_user(self):
        """consolidate_full_blocks(user_id) only processes that user's blocks."""
        from app.engine.character.character_state import CharacterStateManager
        from app.engine.character.models import CharacterBlock
        import time

        mgr = CharacterStateManager()

        # User A: block at 90% full
        key_a = mgr._cache_key(user_id="user-A")
        key_b = mgr._cache_key(user_id="user-B")
        mgr._cache[key_a] = {
            "self_notes": CharacterBlock(
                label="self_notes", content="x" * 900, char_limit=1000, version=1
            ),
        }
        mgr._cache_timestamp[key_a] = time.time()

        # User B: block at 90% full too
        mgr._cache[key_b] = {
            "self_notes": CharacterBlock(
                label="self_notes", content="y" * 900, char_limit=1000, version=1
            ),
        }
        mgr._cache_timestamp[key_b] = time.time()

        mock_repo = MagicMock()
        mock_repo.update_block.return_value = CharacterBlock(
            label="self_notes", content="consolidated", char_limit=1000, version=2
        )

        with patch.object(mgr, '_get_repo', return_value=mock_repo), \
             patch.object(mgr, '_consolidate_block_content', new_callable=AsyncMock) as mock_consolidate:
            mock_consolidate.return_value = "shorter"

            count = await mgr.consolidate_full_blocks(user_id="user-A")

        # Should only consolidate user-A's block
        assert count == 1
        mock_consolidate.assert_called_once()
        # User B's cache should be untouched
        assert mgr._cache[key_b]["self_notes"].content == "y" * 900


# =============================================================================
# Phase 7: Backward compatibility
# =============================================================================

class TestBackwardCompatibility:
    """Verify __global__ default preserves existing behavior."""

    def test_repository_default_user_id(self):
        """All repo methods default to '__global__'."""
        from app.engine.character.character_repository import CharacterRepository
        import inspect

        repo = CharacterRepository()
        for method_name in ['get_all_blocks', 'get_block', 'create_block', 'update_block']:
            method = getattr(repo, method_name)
            sig = inspect.signature(method)
            if 'user_id' in sig.parameters:
                default = sig.parameters['user_id'].default
                assert default == "__global__", f"{method_name}.user_id should default to '__global__', got {default}"

    def test_state_manager_default_user_id(self):
        """All state manager methods default to '__global__'."""
        from app.engine.character.character_state import CharacterStateManager
        import inspect

        mgr = CharacterStateManager()
        for method_name in ['get_blocks', 'get_block', 'update_block', 'compile_living_state',
                           'needs_consolidation', 'consolidate_full_blocks', '_ensure_defaults']:
            method = getattr(mgr, method_name)
            sig = inspect.signature(method)
            if 'user_id' in sig.parameters:
                default = sig.parameters['user_id'].default
                assert default == "__global__", f"{method_name}.user_id should default to '__global__', got {default}"

    def test_singleton_pattern_preserved(self):
        """get_character_state_manager() still returns singleton."""
        from app.engine.character import character_state as mod
        old = mod._state_manager
        try:
            mod._state_manager = None
            mgr1 = mod.get_character_state_manager()
            mgr2 = mod.get_character_state_manager()
            assert mgr1 is mgr2
        finally:
            mod._state_manager = old


# =============================================================================
# Phase 8: Tools __init__ wiring
# =============================================================================

class TestToolsInitWiring:
    """Verify init_all_tools wires set_character_user."""

    def test_init_all_tools_sets_character_user(self):
        """init_all_tools(user_id='X') should call set_character_user('X')."""
        with patch("app.engine.character.character_tools.set_character_user") as mock_set:
            from app.engine.tools import init_all_tools
            # Minimal init — just to trigger the character user wiring
            with patch("app.engine.tools.init_rag_tools"), \
                 patch("app.engine.tools.init_memory_tools"), \
                 patch("app.engine.tools.init_tutor_tools"), \
                 patch("app.engine.tools.init_utility_tools"), \
                 patch("app.engine.tools.init_web_search_tools"), \
                 patch("app.engine.tools._init_extended_tools"), \
                 patch("app.engine.tools.get_tool_registry") as mock_reg:
                mock_reg.return_value.summary.return_value = "test"
                init_all_tools(user_id="tool-user-456")

            mock_set.assert_called_once_with("tool-user-456")


# =============================================================================
# Phase 9: Integration-like — compile_living_state excludes user_patterns
# =============================================================================

class TestLivingStateExclusions:
    """Verify USER_PATTERNS excluded from compiled state (Sprint 121 RC-5)."""

    def test_user_patterns_excluded_from_living_state(self):
        """USER_PATTERNS block should not appear in compile_living_state output."""
        from app.engine.character.character_state import CharacterStateManager
        from app.engine.character.models import CharacterBlock
        import time

        mgr = CharacterStateManager()
        key_x = mgr._cache_key(user_id="user-X")
        mgr._initialized_defaults.add(key_x)
        mgr._cache[key_x] = {
            "learned_lessons": CharacterBlock(
                label="learned_lessons", content="Rule 15", char_limit=1500, version=1
            ),
            "user_patterns": CharacterBlock(
                label="user_patterns", content="SHOULD NOT APPEAR", char_limit=800, version=1
            ),
        }
        mgr._cache_timestamp[key_x] = time.time()

        state = mgr.compile_living_state(user_id="user-X")
        assert "Rule 15" in state
        assert "SHOULD NOT APPEAR" not in state


# =============================================================================
# Phase 10: Refresh cache calls repo with user_id
# =============================================================================

class TestCacheRefreshPerUser:
    """Verify _refresh_cache passes user_id to repo."""

    def test_refresh_cache_passes_user_id(self):
        """_refresh_cache(user_id) calls repo.get_all_blocks(user_id=...)."""
        from app.engine.character.character_state import CharacterStateManager

        mgr = CharacterStateManager()
        mock_repo = MagicMock()
        mock_repo.get_all_blocks.return_value = []

        with patch.object(mgr, '_get_repo', return_value=mock_repo):
            mgr._refresh_cache(user_id="user-refresh")

        mock_repo.get_all_blocks.assert_called_once_with(
            user_id="user-refresh",
            organization_id=None,
        )
