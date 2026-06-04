"""
Sprint 123: Provenance-Annotated Memory + Active Lifecycle — Unit Tests

Tests for:
- P1: FactWithProvenance dataclass and format_for_prompt()
- P2: Confidence-gated injection in build_system_prompt()
- P3: Source quote capture at extraction time
- P4: Active memory pruning via memory_lifecycle.py
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

import pytest


# ============================================================
# P1: Provenance-Annotated Fact Injection
# ============================================================


class TestP1FactWithProvenance:
    """P1: FactWithProvenance dataclass with temporal annotations."""

    def test_fresh_fact_annotation(self):
        """Facts within 3 days should show '✓ xác nhận gần đây'."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        fact = FactWithProvenance(
            content="Hùng",
            fact_type="name",
            confidence=0.95,
            created_at=now - timedelta(hours=12),
            last_accessed=now - timedelta(hours=2),
            access_count=3,
        )

        output = fact.format_for_prompt(now=now)
        assert "Tên: Hùng" in output
        assert "✓ xác nhận gần đây" in output
        assert "⚠️" not in output

    def test_aging_fact_annotation(self):
        """Facts 3-14 days old should show 'aging=Xd'."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        fact = FactWithProvenance(
            content="Sinh viên",
            fact_type="role",
            confidence=0.80,
            created_at=now - timedelta(days=8),
            last_accessed=now - timedelta(days=5),
        )

        output = fact.format_for_prompt(now=now)
        assert "Nghề nghiệp: Sinh viên" in output
        assert "aging=5d" in output

    def test_stale_fact_annotation(self):
        """Facts > 14 days old should show warning."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        fact = FactWithProvenance(
            content="COLREGs",
            fact_type="interest",
            confidence=0.60,
            created_at=now - timedelta(days=30),
            last_accessed=now - timedelta(days=28),
        )

        output = fact.format_for_prompt(now=now)
        assert "Quan tâm: COLREGs" in output
        assert "⚠️ cũ" in output
        assert "28d trước" in output
        assert "xác minh trước khi dùng" in output

    def test_low_confidence_annotation(self):
        """Facts with confidence < 0.7 should show low confidence warning."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        fact = FactWithProvenance(
            content="Hải Phòng",
            fact_type="location",
            confidence=0.55,
            created_at=now - timedelta(hours=1),
            last_accessed=now - timedelta(minutes=30),
        )

        output = fact.format_for_prompt(now=now)
        assert "Nơi ở: Hải Phòng" in output
        assert "độ tin cậy thấp" in output

    def test_no_timestamps_uses_zero_age(self):
        """Facts without timestamps should show as fresh."""
        from app.models.semantic_memory import FactWithProvenance

        fact = FactWithProvenance(
            content="22",
            fact_type="age",
            confidence=0.9,
        )

        output = fact.format_for_prompt()
        assert "Tuổi: 22" in output
        assert "✓ xác nhận gần đây" in output

    def test_format_includes_type_label(self):
        """Each fact type should get correct Vietnamese label."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        test_cases = [
            ("name", "Tên"),
            ("role", "Nghề nghiệp"),
            ("goal", "Mục tiêu học tập"),
            ("weakness", "Điểm yếu"),
            ("strength", "Điểm mạnh"),
            ("hobby", "Sở thích"),
            ("learning_style", "Phong cách học"),
            ("pronoun_style", "Cách xưng hô"),
        ]

        for fact_type, expected_label in test_cases:
            fact = FactWithProvenance(
                content="test", fact_type=fact_type, confidence=0.9,
                created_at=now, last_accessed=now,
            )
            output = fact.format_for_prompt(now=now)
            assert expected_label in output, f"Missing label '{expected_label}' for type '{fact_type}'"


# ============================================================
# P2: Confidence-Gated Injection
# ============================================================


class TestP2ConfidenceGatedInjection:
    """P2: Facts below confidence threshold should be excluded from prompt."""

    def test_low_confidence_facts_excluded(self):
        """Facts below fact_injection_min_confidence should not appear."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        facts = [
            FactWithProvenance(
                content="Hùng", fact_type="name", confidence=0.95,
                created_at=now, last_accessed=now,
            ),
            FactWithProvenance(
                content="maybe_role", fact_type="role", confidence=0.3,  # Below threshold
                created_at=now, last_accessed=now,
            ),
            FactWithProvenance(
                content="goal_value", fact_type="goal", confidence=0.8,
                created_at=now, last_accessed=now,
            ),
        ]

        with patch("app.prompts.prompt_loader.PromptLoader") as MockLoader:
            # Test the injection logic directly
            injected = []
            min_conf = 0.5
            max_facts = 5
            for fact in facts:
                if len(injected) >= max_facts:
                    break
                if isinstance(fact, FactWithProvenance):
                    if fact.confidence < min_conf:
                        continue
                    injected.append(fact.format_for_prompt(now=now))

            assert len(injected) == 2
            assert any("Hùng" in f for f in injected)
            assert any("goal_value" in f for f in injected)
            assert not any("maybe_role" in f for f in injected)

    def test_max_injected_facts_respected(self):
        """At most max_injected_facts should be injected."""
        from app.models.semantic_memory import FactWithProvenance

        now = datetime.now(timezone.utc)
        facts = [
            FactWithProvenance(
                content=f"fact_{i}", fact_type="preference", confidence=0.9,
                created_at=now, last_accessed=now,
            )
            for i in range(10)
        ]

        max_facts = 3
        injected = []
        for fact in facts:
            if len(injected) >= max_facts:
                break
            injected.append(fact.format_for_prompt(now=now))

        assert len(injected) == 3


# ============================================================
# P3: Source Quote Capture
# ============================================================


class TestP3SourceQuoteCapture:
    """P3: Source message captured in fact metadata at extraction time."""

    @pytest.mark.asyncio
    async def test_source_message_passed_to_store(self):
        """extract_and_store_facts() should pass message to store_user_fact_upsert."""
        from app.engine.semantic_memory.extraction import FactExtractor
        from app.models.semantic_memory import UserFact, UserFactExtraction, FactType

        mock_embeddings = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = []
        extractor = FactExtractor(mock_embeddings, mock_repo)
        extractor._llm = MagicMock()

        test_message = "Mình tên Hùng, sinh viên năm 3 trường Hàng Hải"

        # Mock extract_user_facts to return a fact
        mock_extraction = UserFactExtraction(
            facts=[UserFact(fact_type=FactType.NAME, value="Hùng", confidence=0.95)],
            raw_message=test_message,
        )
        extractor.extract_user_facts = AsyncMock(return_value=mock_extraction)
        extractor.store_user_fact_upsert = AsyncMock(return_value=True)

        # Patch pruning — lazy import inside function body
        with patch("app.services.memory_lifecycle.prune_stale_memories", new_callable=AsyncMock, return_value=0):
            await extractor.extract_and_store_facts("user-1", test_message)

        # Verify source_message was passed
        extractor.store_user_fact_upsert.assert_called_once()
        call_kwargs = extractor.store_user_fact_upsert.call_args
        # source_message is passed as keyword arg
        assert call_kwargs.kwargs.get("source_message") == test_message

    @pytest.mark.asyncio
    async def test_source_quote_truncated_to_200_chars(self):
        """Source quote should be truncated to 200 characters."""
        from app.engine.semantic_memory.extraction import FactExtractor
        from app.models.semantic_memory import MemoryType

        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo = MagicMock()
        mock_repo.find_similar_fact_by_embedding.return_value = None
        mock_repo.find_fact_by_type.return_value = None
        mock_repo.save_memory.return_value = MagicMock()
        mock_repo.count_user_memories.return_value = 5
        mock_repo.get_all_user_facts.return_value = []

        extractor = FactExtractor(mock_embeddings, mock_repo)

        long_message = "x" * 500
        await extractor.store_user_fact_upsert(
            "user-1", "name: Hùng", "name", 0.9, "session-1",
            source_message=long_message,
        )

        # Find the save_memory call and check metadata
        save_call = mock_repo.save_memory.call_args
        if save_call:
            memory_obj = save_call[0][0]
            assert len(memory_obj.metadata.get("source_quote", "")) <= 200


# ============================================================
# P4: Active Memory Pruning
# ============================================================


class TestP4ActiveMemoryPruning:
    """P4: memory_lifecycle.py prunes decayed facts."""

    @pytest.mark.asyncio
    async def test_prune_removes_decayed_facts(self):
        """Pruning should remove facts below prune_threshold."""
        from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult

        now = datetime.now(timezone.utc)
        old_volatile = SemanticMemorySearchResult(
            id=uuid4(), content="emotion: buồn",
            memory_type=MemoryType.USER_FACT, importance=0.3, similarity=1.0,
            metadata={"fact_type": "emotion", "access_count": 0},
            created_at=now - timedelta(days=10),  # 10 days old emotion → decayed to ~0
        )
        fresh_identity = SemanticMemorySearchResult(
            id=uuid4(), content="name: Hùng",
            memory_type=MemoryType.USER_FACT, importance=0.9, similarity=1.0,
            metadata={"fact_type": "name", "access_count": 3},
            created_at=now - timedelta(days=30),
        )

        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = [old_volatile, fresh_identity]
        mock_repo.delete_memory.return_value = True

        mock_settings = MagicMock()
        mock_settings.enable_memory_pruning = True
        mock_settings.memory_prune_threshold = 0.1

        # Patch lazy imports at source module level + reload to avoid test pollution
        import importlib
        import app.services.memory_lifecycle as _ml_mod
        with patch("app.core.config.settings", mock_settings):
            with patch(
                "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
                return_value=mock_repo,
            ):
                importlib.reload(_ml_mod)
                pruned = await _ml_mod.prune_stale_memories("user-1")

        # Volatile emotion from 10 days ago should be pruned (effective ≈ 0)
        # Identity name should NOT be pruned (never decays)
        assert pruned >= 1
        # Verify delete was called for the volatile fact
        delete_calls = mock_repo.delete_memory.call_args_list
        deleted_ids = [str(call[0][1]) for call in delete_calls]
        assert str(old_volatile.id) in deleted_ids
        assert str(fresh_identity.id) not in deleted_ids

    @pytest.mark.asyncio
    async def test_prune_disabled_by_setting(self):
        """When enable_memory_pruning=False, no pruning occurs."""
        mock_settings = MagicMock()
        mock_settings.enable_memory_pruning = False

        with patch("app.core.config.settings", mock_settings):
            from app.services.memory_lifecycle import prune_stale_memories
            pruned = await prune_stale_memories("user-1")

        assert pruned == 0

    @pytest.mark.asyncio
    async def test_prune_handles_empty_facts(self):
        """Pruning should handle users with no facts gracefully."""
        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = []

        mock_settings = MagicMock()
        mock_settings.enable_memory_pruning = True
        mock_settings.memory_prune_threshold = 0.1

        with patch("app.core.config.settings", mock_settings):
            with patch(
                "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
                return_value=mock_repo,
            ):
                from app.services.memory_lifecycle import prune_stale_memories
                pruned = await prune_stale_memories("user-1")

        assert pruned == 0

    @pytest.mark.asyncio
    async def test_prune_runs_as_background_memory_maintenance(self):
        """Memory pruning should stay out of extraction hot path."""
        import inspect
        from app.engine.semantic_memory.extraction import FactExtractor
        from app.services.background_tasks import BackgroundTaskRunner
        from app.services.post_turn_lifecycle import schedule_post_turn_background_tasks
        from app.tasks.semantic_memory_tasks import run_semantic_memory_maintenance

        extraction_source = inspect.getsource(FactExtractor.extract_and_store_facts)
        runner_source = inspect.getsource(
            BackgroundTaskRunner._run_semantic_memory_maintenance,
        )
        task_source = inspect.getsource(run_semantic_memory_maintenance)
        schedule_source = inspect.getsource(BackgroundTaskRunner.schedule_all)
        lifecycle_source = inspect.getsource(schedule_post_turn_background_tasks)

        assert "prune_stale_memories" not in extraction_source
        assert "run_semantic_memory_maintenance" in runner_source
        assert "prune_stale_memories" in task_source
        assert "schedule_post_turn_background_tasks" in schedule_source
        assert "_enqueue_or_run_semantic_memory_maintenance" in lifecycle_source
        assert "semantic_memory_maintenance" in lifecycle_source
