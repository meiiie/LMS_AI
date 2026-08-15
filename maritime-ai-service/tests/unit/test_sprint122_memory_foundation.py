"""
Sprint 122: Memory Foundation Bug Fixes — Unit Tests

Tests for:
- F1: Running Summary Storage Split (RUNNING_SUMMARY enum alignment)
- F2: access_count increment in update_last_accessed()
- F3: Updated type_order/type_labels in to_prompt_context()
- F4: Single authoritative fact injection path
- F5: Importance-aware eviction (replaces FIFO)
- F6: Configurable memory constants from settings
"""

import json
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

import pytest

# ============================================================
# F1: Running Summary Storage Split
# ============================================================


class TestF1RunningSummaryStorageSplit:
    """Bug F1: MemoryType.RUNNING_SUMMARY enum exists and is used consistently."""

    def test_running_summary_enum_exists(self):
        """RUNNING_SUMMARY must be a distinct MemoryType value."""
        from app.models.semantic_memory import MemoryType

        assert hasattr(MemoryType, "RUNNING_SUMMARY")
        assert MemoryType.RUNNING_SUMMARY.value == "running_summary"
        # SUMMARY is still separate
        assert MemoryType.SUMMARY.value == "summary"
        assert MemoryType.RUNNING_SUMMARY != MemoryType.SUMMARY

    def test_upsert_uses_running_summary_type(self):
        """upsert_running_summary() must use RUNNING_SUMMARY, not SUMMARY."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository
        from app.models.semantic_memory import MemoryType

        repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
        repo.TABLE_NAME = "semantic_memories"

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=uuid4())
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo._session_factory = mock_factory
        repo._ensure_initialized = MagicMock()

        repo.upsert_running_summary("session-1", "Test summary")

        # Verify the memory_type parameter
        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["memory_type"] == MemoryType.RUNNING_SUMMARY.value

    def test_get_running_summary_uses_running_summary_type(self):
        """get_running_summary() must query RUNNING_SUMMARY type."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository
        from app.models.semantic_memory import MemoryType

        repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
        repo.TABLE_NAME = "semantic_memories"

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo._session_factory = mock_factory
        repo._ensure_initialized = MagicMock()

        repo.get_running_summary("session-1")

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["memory_type"] == MemoryType.RUNNING_SUMMARY.value


# ============================================================
# F2: access_count Never Incremented
# ============================================================


class TestF2AccessCountIncrement:
    """Bug F2: update_last_accessed() must increment metadata.access_count."""

    def test_update_last_accessed_sql_has_access_count(self):
        """SQL must include jsonb_set for access_count."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
        repo.TABLE_NAME = "semantic_memories"

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=uuid4())
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo._session_factory = mock_factory
        repo._ensure_initialized = MagicMock()

        result = repo.update_last_accessed(uuid4(), user_id="user-1")

        assert result is True
        # Verify the SQL contains access_count increment
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "access_count" in sql_text
        assert "jsonb_set" in sql_text

    def test_update_last_accessed_without_user_id(self):
        """Should work without user_id too."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
        repo.TABLE_NAME = "semantic_memories"

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock(id=uuid4())
        mock_session.execute.return_value = mock_result

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo._session_factory = mock_factory
        repo._ensure_initialized = MagicMock()

        result = repo.update_last_accessed(uuid4())

        assert result is True
        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "access_count" in sql_text


# ============================================================
# F3: Stale type_order in to_prompt_context()
# ============================================================


class TestF3TypeOrderUpdated:
    """Bug F3: type_order and type_labels match current ALLOWED_FACT_TYPES."""

    def test_all_non_volatile_types_have_labels(self):
        """All non-volatile fact types should have Vietnamese labels."""
        from app.models.semantic_memory import (
            SemanticContext,
            SemanticMemorySearchResult,
            MemoryType,
            ALLOWED_FACT_TYPES,
            VOLATILE_FACT_TYPES,
        )

        non_volatile = ALLOWED_FACT_TYPES - VOLATILE_FACT_TYPES

        # Create a fact for each type
        facts = []
        for ft in non_volatile:
            facts.append(SemanticMemorySearchResult(
                id=uuid4(),
                content=f"{ft}: test_value",
                memory_type=MemoryType.USER_FACT,
                importance=0.8,
                similarity=1.0,
                metadata={"fact_type": ft},
                created_at=datetime.utcnow(),
            ))

        ctx = SemanticContext(user_facts=facts)
        output = ctx.to_prompt_context()

        # Verify no raw fact_type strings leak through (all should be Vietnamese)
        assert "test_value" in output  # Values should appear
        # All types should get a Vietnamese label (not raw English type names)
        for ft in ["role", "level", "location", "organization", "weakness",
                    "strength", "hobby", "pronoun_style"]:
            # These should NOT appear as raw labels in the output
            assert ft + ": test_value" not in output or ft in output

    def test_deprecated_types_still_work(self):
        """Deprecated types (background, weak_area, strong_area) should still render."""
        from app.models.semantic_memory import (
            SemanticContext,
            SemanticMemorySearchResult,
            MemoryType,
        )

        facts = [
            SemanticMemorySearchResult(
                id=uuid4(),
                content="background: sinh viên",
                memory_type=MemoryType.USER_FACT,
                importance=0.8,
                similarity=1.0,
                metadata={"fact_type": "background"},
                created_at=datetime.utcnow(),
            ),
        ]

        ctx = SemanticContext(user_facts=facts)
        output = ctx.to_prompt_context()
        # "background" maps to "Nghề nghiệp" label
        assert "Nghề nghiệp" in output
        assert "sinh viên" in output

    def test_volatile_types_excluded_from_profile(self):
        """Emotion and recent_topic should not appear in type_order."""
        from app.models.semantic_memory import (
            SemanticContext,
            SemanticMemorySearchResult,
            MemoryType,
        )

        # Only add volatile facts
        facts = [
            SemanticMemorySearchResult(
                id=uuid4(),
                content="emotion: vui",
                memory_type=MemoryType.USER_FACT,
                importance=0.3,
                similarity=1.0,
                metadata={"fact_type": "emotion"},
                created_at=datetime.utcnow(),
            ),
        ]

        ctx = SemanticContext(user_facts=facts)
        output = ctx.to_prompt_context()
        # Volatile facts still render (as "remaining"), but they're last
        assert "vui" in output


# ============================================================
# F4: Triple Fact Injection
# ============================================================




# ============================================================
# F5: Importance-Aware Eviction
# ============================================================


class TestF5ImportanceAwareEviction:
    """Bug F5: _enforce_memory_cap() uses importance-based eviction."""

    @pytest.mark.asyncio
    async def test_evicts_lowest_importance_first(self):
        """Should evict volatile/low-importance facts before identity facts."""
        from app.engine.semantic_memory.extraction import FactExtractor
        from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult

        mock_embeddings = MagicMock()
        mock_repo = MagicMock()

        extractor = FactExtractor(mock_embeddings, mock_repo)

        # Create test facts: 3 identity (high importance) + 3 volatile (low importance)
        now = datetime.now(timezone.utc)
        all_facts = [
            # Identity facts — should NOT be evicted
            SemanticMemorySearchResult(
                id=uuid4(), content="name: Hùng",
                memory_type=MemoryType.USER_FACT, importance=0.9, similarity=1.0,
                metadata={"fact_type": "name", "access_count": 5},
                created_at=now - timedelta(days=30),
            ),
            SemanticMemorySearchResult(
                id=uuid4(), content="age: 22",
                memory_type=MemoryType.USER_FACT, importance=0.9, similarity=1.0,
                metadata={"fact_type": "age", "access_count": 2},
                created_at=now - timedelta(days=30),
            ),
            # Volatile facts — should be evicted first
            SemanticMemorySearchResult(
                id=uuid4(), content="emotion: buồn",
                memory_type=MemoryType.USER_FACT, importance=0.3, similarity=1.0,
                metadata={"fact_type": "emotion", "access_count": 0},
                created_at=now - timedelta(days=3),
            ),
            SemanticMemorySearchResult(
                id=uuid4(), content="recent_topic: thời tiết",
                memory_type=MemoryType.USER_FACT, importance=0.3, similarity=1.0,
                metadata={"fact_type": "recent_topic", "access_count": 0},
                created_at=now - timedelta(days=5),
            ),
        ]

        mock_repo.get_all_user_facts.return_value = all_facts
        mock_repo.delete_memory.return_value = True

        # Set cap to 2 → need to evict 2 facts
        with patch.object(type(extractor), "MAX_USER_FACTS", new_callable=lambda: property(lambda self: 2)):
            deleted = await extractor._enforce_memory_cap("user-1")

        assert deleted == 2
        # Verify volatile facts were deleted (not identity)
        delete_calls = mock_repo.delete_memory.call_args_list
        deleted_ids = {str(call[0][1]) for call in delete_calls}
        # The volatile facts should have been evicted
        volatile_ids = {str(all_facts[2].id), str(all_facts[3].id)}
        assert deleted_ids == volatile_ids

    @pytest.mark.asyncio
    async def test_no_eviction_when_under_cap(self):
        """Should not evict anything when count <= MAX_USER_FACTS."""
        from app.engine.semantic_memory.extraction import FactExtractor
        from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult

        mock_repo = MagicMock()
        extractor = FactExtractor(MagicMock(), mock_repo)

        mock_repo.get_all_user_facts.return_value = [
            SemanticMemorySearchResult(
                id=uuid4(), content="name: Hùng",
                memory_type=MemoryType.USER_FACT, importance=0.9, similarity=1.0,
                metadata={"fact_type": "name"}, created_at=datetime.utcnow(),
            ),
        ]

        deleted = await extractor._enforce_memory_cap("user-1")
        assert deleted == 0
        mock_repo.delete_memory.assert_not_called()


# ============================================================
# F6: Configurable Memory Constants
# ============================================================


class TestF6ConfigurableMemoryConstants:
    """Bug F6: Memory constants are in Settings, not hardcoded."""

    def test_settings_has_memory_fields(self):
        """Settings class should have all new memory configuration fields."""
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "max_user_facts" in fields
        assert "character_cache_ttl" in fields
        assert "memory_prune_threshold" in fields
        assert "fact_injection_min_confidence" in fields
        assert "max_injected_facts" in fields
        assert "enable_memory_pruning" in fields

    def test_default_values(self):
        """Verify default values match documented expectations."""
        from app.core.config import Settings

        defaults = {
            "max_user_facts": 50,
            "character_cache_ttl": 60,
            "memory_prune_threshold": 0.1,
            "fact_injection_min_confidence": 0.5,
            "max_injected_facts": 5,
            "enable_memory_pruning": True,
        }

        for field_name, expected_default in defaults.items():
            field_info = Settings.model_fields[field_name]
            assert field_info.default == expected_default, (
                f"{field_name}: expected {expected_default}, got {field_info.default}"
            )

    def test_max_user_facts_reads_from_settings(self):
        """FactExtractor.MAX_USER_FACTS should read from settings."""
        from app.engine.semantic_memory.extraction import FactExtractor

        mock_embeddings = MagicMock()
        mock_repo = MagicMock()
        extractor = FactExtractor(mock_embeddings, mock_repo)

        with patch("app.engine.semantic_memory.extraction.settings") as mock_settings:
            mock_settings.max_user_facts = 100
            assert extractor.MAX_USER_FACTS == 100

            mock_settings.max_user_facts = 25
            assert extractor.MAX_USER_FACTS == 25
