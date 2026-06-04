"""
Tests for Sprint 125: Full Isolation Sweep

Tests cover:
  1. EmotionalStateManager TTL eviction
  2. ConversationCompactor composite cache key
  3. Reflection Engine per-user isolation (cross-ref)
  4. Character blocks per-user (Sprint 124 regression)
  5. SemanticCache user_id parameter
"""

import time
import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# EmotionalStateManager — TTL eviction
# =============================================================================

class TestEmotionalStateTTL:
    """Test EmotionalStateManager TTL eviction for bounded growth."""

    def _get_manager(self):
        from app.engine.emotional_state import EmotionalStateManager
        return EmotionalStateManager()

    def test_eviction_removes_stale_users(self):
        manager = self._get_manager()
        # Add 600 users (over MAX_CACHED_USERS=500)
        for i in range(600):
            manager.get_state(f"user-{i}")

        # Make first 200 users stale
        now = time.time()
        for i in range(200):
            manager._last_access[f"user-{i}"] = now - 8000  # older than TTL

        # Trigger eviction
        manager._evict_stale()

        # Stale users should be removed
        assert len(manager._states) == 400
        assert "user-0" not in manager._states
        assert "user-500" in manager._states

    def test_no_eviction_when_under_limit(self):
        manager = self._get_manager()
        for i in range(10):
            manager.get_state(f"user-{i}")

        # All within limit — no eviction
        manager._evict_stale()
        assert len(manager._states) == 10

    def test_reset_removes_access_timestamp(self):
        manager = self._get_manager()
        manager.get_state("user-1")
        assert "user-1" in manager._last_access

        manager.reset("user-1")
        assert "user-1" not in manager._states
        assert "user-1" not in manager._last_access

    def test_active_users_property(self):
        manager = self._get_manager()
        assert manager.active_users == 0

        manager.get_state("user-1")
        manager.get_state("user-2")
        assert manager.active_users == 2

    def test_detect_and_update_triggers_eviction(self):
        """detect_and_update calls _evict_stale internally."""
        manager = self._get_manager()
        # Fill over MAX
        for i in range(510):
            manager.get_state(f"user-{i}")

        # Make first 100 stale
        now = time.time()
        for i in range(100):
            manager._last_access[f"user-{i}"] = now - 8000

        # This should trigger eviction internally
        with patch.object(manager, "_evict_stale", wraps=manager._evict_stale) as spy:
            manager.detect_and_update("user-new", "hello")
            spy.assert_called_once()

    def test_user_isolation_different_users_different_states(self):
        """Different users should have independent emotional states."""
        manager = self._get_manager()

        # User A: excited
        manager.detect_and_update("user-A", "Tuyệt vời quá!")
        # User B: neutral
        manager.detect_and_update("user-B", "Ok")

        state_a = manager.get_state("user-A")
        state_b = manager.get_state("user-B")

        # User A should have higher positivity than User B
        assert state_a.positivity > state_b.positivity


# =============================================================================
# ConversationCompactor — composite cache key
# =============================================================================

class TestConversationCompactorCacheKey:
    """Test composite cache key prevents cross-user collision."""

    def _get_compactor(self):
        from app.engine.context_manager import ConversationCompactor
        return ConversationCompactor()

    def test_cache_key_with_user_id(self):
        from app.engine.context_manager import ConversationCompactor
        key = ConversationCompactor._cache_key("session-1", "user-A")
        assert key == "user-A::session-1"

    def test_cache_key_without_user_id(self):
        from app.engine.context_manager import ConversationCompactor
        key = ConversationCompactor._cache_key("session-1", "")
        assert key == "session-1"

    def test_different_users_same_session_different_keys(self):
        from app.engine.context_manager import ConversationCompactor
        key_a = ConversationCompactor._cache_key("session-1", "user-A")
        key_b = ConversationCompactor._cache_key("session-1", "user-B")
        assert key_a != key_b

    def test_set_get_running_summary_user_isolation(self):
        compactor = self._get_compactor()

        # User A sets summary
        compactor.set_running_summary("session-1", "User A summary", user_id="user-A")
        # User B sets different summary for same session name
        compactor.set_running_summary("session-1", "User B summary", user_id="user-B")

        # Each gets their own
        assert compactor.get_running_summary("session-1", user_id="user-A") == "User A summary"
        assert compactor.get_running_summary("session-1", user_id="user-B") == "User B summary"

    def test_backward_compat_no_user_id(self):
        compactor = self._get_compactor()
        compactor.set_running_summary("session-1", "Global summary")
        assert compactor.get_running_summary("session-1") == "Global summary"

    def test_delete_summary_only_affects_target_user(self):
        compactor = self._get_compactor()
        compactor.set_running_summary("session-1", "A summary", user_id="user-A")
        compactor.set_running_summary("session-1", "B summary", user_id="user-B")

        # Delete User A's summary
        compactor.set_running_summary("session-1", "", user_id="user-A")

        assert compactor.get_running_summary("session-1", user_id="user-A") == ""
        assert compactor.get_running_summary("session-1", user_id="user-B") == "B summary"


# =============================================================================
# Character State Manager — per-user cache (Sprint 124 regression)
# =============================================================================

class TestCharacterStatePerUser:
    """Verify Sprint 124 per-user character blocks still work."""

    def _get_manager(self):
        from app.engine.character.character_state import CharacterStateManager
        return CharacterStateManager()

    def test_cache_is_per_user_dict(self):
        manager = self._get_manager()
        assert isinstance(manager._cache, dict)
        # Cache keys should be user_ids
        assert "__global__" not in manager._cache or isinstance(
            manager._cache.get("__global__"), dict
        )

    def test_needs_consolidation_per_user(self):
        from app.engine.character.models import CharacterBlock
        from uuid import uuid4

        manager = self._get_manager()
        block = CharacterBlock(
            id=uuid4(), label="self_notes",
            content="x" * 800, char_limit=1000,
        )
        org_id = "org-test"
        user_a_key = manager._cache_key(user_id="user-A", organization_id=org_id)
        user_b_key = manager._cache_key(user_id="user-B", organization_id=org_id)
        manager._cache = {
            user_a_key: {"self_notes": block},
            user_b_key: {},
        }
        manager._cache_timestamp = {
            user_a_key: 1e18,
            user_b_key: 1e18,
        }

        assert manager.needs_consolidation(
            "self_notes",
            user_id="user-A",
            organization_id=org_id,
        )
        assert not manager.needs_consolidation(
            "self_notes",
            user_id="user-B",
            organization_id=org_id,
        )


# =============================================================================
# SemanticCache — user_id parameter verification
# =============================================================================

class TestSemanticCacheUserParam:
    """Verify SemanticCache get/set accept user_id."""

    def test_get_has_user_id_param(self):
        """Verify the get method signature includes user_id."""
        import inspect
        from app.cache.semantic_cache import SemanticResponseCache
        sig = inspect.signature(SemanticResponseCache.get)
        assert "user_id" in sig.parameters

    def test_set_has_user_id_param(self):
        """Verify the set method signature includes user_id."""
        import inspect
        from app.cache.semantic_cache import SemanticResponseCache
        sig = inspect.signature(SemanticResponseCache.set)
        assert "user_id" in sig.parameters


# =============================================================================
# MemorySummarizer — cache key verification
# =============================================================================

class TestMemorySummarizerCache:
    """Verify MemorySummarizer uses session-based keys."""

    def test_states_is_dict(self):
        from app.engine.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()
        assert isinstance(summarizer._states, dict)

    def test_get_state_creates_new(self):
        from app.engine.memory_summarizer import MemorySummarizer
        summarizer = MemorySummarizer()
        state = summarizer.get_state("session-unique-123")
        assert state is not None
        # Same session returns same state
        assert summarizer.get_state("session-unique-123") is state
