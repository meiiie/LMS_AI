"""
Tests for Sprint 30: SemanticMemoryEngine (core.py) coverage.

Covers:
- __init__: component initialization
- is_available: availability checks
- _ensure_llm: lazy LLM init
- get_user_facts: dict conversion
- store_interaction: message + response storage
- count_tokens: tiktoken/fallback
- count_session_tokens: session token sum
- delete_memory_by_keyword: keyword-based deletion
- delete_all_user_memories: factory reset
- store_explicit_insight: user-requested memory
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone


# =============================================================================
# Helpers
# =============================================================================


def _make_engine(repo=None, embeddings=None, llm=None):
    """Create SemanticMemoryEngine with mocked dependencies."""
    from app.engine.semantic_memory.core import SemanticMemoryEngine

    mock_embeddings = embeddings or MagicMock()
    mock_repo = repo or MagicMock()

    with patch("app.engine.semantic_memory.core.get_semantic_embedding_backend", return_value=mock_embeddings), \
         patch("app.engine.semantic_memory.core.SemanticMemoryRepository", return_value=mock_repo):
        engine = SemanticMemoryEngine(
            embeddings=mock_embeddings,
            repository=mock_repo,
            llm=llm,
        )

    return engine


# =============================================================================
# __init__
# =============================================================================


class TestInit:
    """Test SemanticMemoryEngine initialization."""

    def test_creates_sub_modules(self):
        engine = _make_engine()
        assert engine._context_retriever is not None
        assert engine._fact_extractor is not None
        assert engine._insight_provider is not None

    def test_accepts_custom_llm(self):
        mock_llm = MagicMock()
        engine = _make_engine(llm=mock_llm)
        assert engine._llm is mock_llm


# =============================================================================
# is_available
# =============================================================================


class TestIsAvailable:
    """Test availability checks."""

    def test_available_when_repo_and_embeddings_ok(self):
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        engine = _make_engine(repo=mock_repo)
        assert engine.is_available() is True

    def test_available_when_repo_ok_but_embeddings_unavailable(self):
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        mock_embeddings = MagicMock()
        mock_embeddings.is_available.return_value = False
        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        assert engine.is_available() is True

    def test_not_available_when_repo_unavailable(self):
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = False
        engine = _make_engine(repo=mock_repo)
        assert engine.is_available() is False

    def test_not_available_on_exception(self):
        mock_repo = MagicMock()
        mock_repo.is_available.side_effect = RuntimeError("DB down")
        engine = _make_engine(repo=mock_repo)
        assert engine.is_available() is False


# =============================================================================
# _ensure_llm
# =============================================================================


class TestEnsureLlm:
    """Test lazy LLM initialization."""

    def test_does_nothing_if_llm_exists(self):
        mock_llm = MagicMock()
        engine = _make_engine(llm=mock_llm)
        engine._ensure_llm()
        assert engine._llm is mock_llm

    def test_creates_llm_on_first_call(self):
        engine = _make_engine(llm=None)
        mock_llm = MagicMock()

        with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
            engine._ensure_llm()

        assert engine._llm is mock_llm

    def test_handles_import_error(self):
        engine = _make_engine(llm=None)

        with patch("app.engine.llm_pool.get_llm_light", side_effect=Exception("pool unavailable")):
            engine._ensure_llm()

        assert engine._llm is None


class TestFactExtractionFallback:
    """Deterministic extraction path for explicit memory writes."""

    @pytest.mark.asyncio
    async def test_explicit_long_term_memory_uses_deterministic_path_before_llm(self):
        from app.engine.semantic_memory.extraction import FactExtractor
        from app.models.semantic_memory import FactType

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("explicit memory should not call LLM"))
        extractor = FactExtractor(MagicMock(), MagicMock(), llm=mock_llm)

        result = await extractor.extract_user_facts(
            "user-1",
            (
                "Hãy ghi nhớ lâu dài rằng mã semantic test của mình là "
                "hải đăng bạc 884. Trả lời ngắn gọn rằng đã lưu."
            ),
        )

        assert result.has_facts
        assert result.facts[0].fact_type == FactType.PREFERENCE
        assert "hải đăng bạc 884" in result.facts[0].value
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_scoped_memory_is_not_persisted_or_sent_to_llm(self):
        from app.engine.semantic_memory.extraction import FactExtractor

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("session memory should not call LLM"))
        extractor = FactExtractor(MagicMock(), MagicMock(), llm=mock_llm)

        result = await extractor.extract_user_facts(
            "user-1",
            (
                "Trong phiên này, hãy nhớ mã kiểm thử UX hôm nay là "
                "sao biển cam 731. Trả lời chỉ: Đã ghi nhận."
            ),
        )

        assert result.facts == []
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_memory_recall_question_is_not_treated_as_write(self):
        from app.engine.semantic_memory.extraction import FactExtractor

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("recall question should not call extractor LLM"))
        extractor = FactExtractor(MagicMock(), MagicMock(), llm=mock_llm)

        result = await extractor.extract_user_facts(
            "user-1",
            "Mã semantic test cuối mình vừa nhờ bạn ghi nhớ là gì? Trả lời đúng 1 câu.",
        )

        assert result.facts == []
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_store_pipeline_does_not_require_llm(self):
        from app.engine.semantic_memory.extraction import FactExtractor

        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo = MagicMock()
        mock_repo.find_similar_fact_by_embedding.return_value = None
        mock_repo.find_fact_by_type.return_value = None
        mock_repo.save_memory.return_value = MagicMock()
        mock_repo.get_all_user_facts.return_value = []
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("explicit memory store should not call LLM"))
        extractor = FactExtractor(mock_embeddings, mock_repo, llm=mock_llm)

        result = await extractor.extract_and_store_facts(
            "user-1",
            (
                "Hãy ghi nhớ lâu dài rằng mã semantic test mới của mình là "
                "đèn biển xanh 942. Trả lời ngắn gọn rằng đã lưu."
            ),
        )

        assert len(result) == 1
        assert "đèn biển xanh 942" in result[0].value
        mock_llm.ainvoke.assert_not_awaited()


# =============================================================================
# get_user_facts
# =============================================================================


class TestGetUserFacts:
    """Test user facts retrieval as dict."""

    @pytest.mark.asyncio
    async def test_empty_facts(self):
        mock_repo = MagicMock()
        mock_repo.get_user_facts.return_value = []
        engine = _make_engine(repo=mock_repo)
        result = await engine.get_user_facts("user-1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_converts_to_dict(self):
        from datetime import datetime, timezone
        _ts = datetime(2026, 2, 17, tzinfo=timezone.utc)
        fact1 = MagicMock()
        fact1.content = "name: Minh"
        fact1.metadata = {"fact_type": "name"}
        fact1.updated_at = _ts
        fact1.created_at = _ts
        fact2 = MagicMock()
        fact2.content = "role: student"
        fact2.metadata = {"fact_type": "role"}
        fact2.updated_at = _ts
        fact2.created_at = _ts

        mock_repo = MagicMock()
        mock_repo.get_user_facts.return_value = [fact1, fact2]
        engine = _make_engine(repo=mock_repo)

        result = await engine.get_user_facts("user-1")
        assert result["name"] == "Minh"
        assert result["role"] == "student"
        # Sprint 121: also includes __updated_at keys
        assert "name__updated_at" in result
        assert "role__updated_at" in result

    @pytest.mark.asyncio
    async def test_content_without_separator(self):
        from datetime import datetime, timezone
        _ts = datetime(2026, 2, 17, tzinfo=timezone.utc)
        fact = MagicMock()
        fact.content = "plain text"
        fact.metadata = {"fact_type": "note"}
        fact.updated_at = _ts
        fact.created_at = _ts

        mock_repo = MagicMock()
        mock_repo.get_user_facts.return_value = [fact]
        engine = _make_engine(repo=mock_repo)

        result = await engine.get_user_facts("user-1")
        assert result["note"] == "plain text"
        assert "note__updated_at" in result

    @pytest.mark.asyncio
    async def test_deduplicates_by_type(self):
        """First occurrence wins (keep latest/first)."""
        fact1 = MagicMock()
        fact1.content = "name: Minh"
        fact1.metadata = {"fact_type": "name"}
        fact2 = MagicMock()
        fact2.content = "name: Nam"
        fact2.metadata = {"fact_type": "name"}

        mock_repo = MagicMock()
        mock_repo.get_user_facts.return_value = [fact1, fact2]
        engine = _make_engine(repo=mock_repo)

        result = await engine.get_user_facts("user-1")
        assert result["name"] == "Minh"

    @pytest.mark.asyncio
    async def test_handles_repo_error(self):
        mock_repo = MagicMock()
        mock_repo.get_user_facts.side_effect = RuntimeError("DB error")
        engine = _make_engine(repo=mock_repo)
        result = await engine.get_user_facts("user-1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        mock_repo = MagicMock()
        engine = _make_engine(repo=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            result = await engine.get_user_facts("user-private-123")
        finally:
            current_org_id.reset(token)

        assert result == {}
        mock_repo.get_user_facts.assert_not_called()

    def test_search_relevant_facts_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        mock_repo = MagicMock()
        engine = _make_engine(repo=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            result = engine.search_relevant_facts(
                "user-private-123",
                [0.1] * 768,
            )
        finally:
            current_org_id.reset(token)

        assert result == []
        mock_repo.search_relevant_facts.assert_not_called()


# =============================================================================
# store_interaction
# =============================================================================


class TestStoreInteraction:
    """Test interaction storage."""

    @pytest.mark.asyncio
    async def test_stores_message_and_response(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        # Mock fact extractor to avoid LLM calls
        engine._fact_extractor.extract_and_store_facts = AsyncMock(return_value=[])

        result = await engine.store_interaction(
            user_id="user-1",
            message="Hello",
            response="Hi there",
            session_id="sess-1",
        )

        assert result is True
        assert mock_repo.save_memory.call_count == 2  # message + response

    @pytest.mark.asyncio
    async def test_extracts_facts_when_enabled(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        engine._fact_extractor.extract_and_store_facts = AsyncMock(return_value=[])

        await engine.store_interaction("user-1", "Hello", "Hi", extract_facts=True)
        engine._fact_extractor.extract_and_store_facts.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_facts_when_disabled(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        engine._fact_extractor.extract_and_store_facts = AsyncMock()

        await engine.store_interaction("user-1", "Hello", "Hi", extract_facts=False)
        engine._fact_extractor.extract_and_store_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.side_effect = RuntimeError("DB fail")
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        result = await engine.store_interaction("user-1", "Hello", "Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_embedding_failure_still_saves_null_vector_records(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(side_effect=Exception("embedding down"))

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        engine._fact_extractor.extract_and_store_facts = AsyncMock(return_value=[])

        result = await engine.store_interaction("user-1", "Hello", "Hi")

        assert result is True
        assert mock_repo.save_memory.call_count == 2
        first_memory = mock_repo.save_memory.call_args_list[0][0][0]
        second_memory = mock_repo.save_memory.call_args_list[1][0][0]
        assert first_memory.embedding == []
        assert second_memory.embedding == []

    @pytest.mark.asyncio
    async def test_store_interaction_appends_privacy_safe_write_audit(
        self,
        monkeypatch,
    ):
        from app.engine.runtime.session_event_log import InMemorySessionEventLog

        log = InMemorySessionEventLog()
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )
        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        engine._fact_extractor.extract_and_store_facts = AsyncMock(
            return_value=[object(), object()]
        )

        result = await engine.store_interaction(
            user_id="user-private-123",
            message="PRIVATE USER MESSAGE access_token=raw-user-token-12345",
            response="PRIVATE ASSISTANT RESPONSE",
            session_id="session-private-123",
            extract_facts=True,
        )

        assert result is True
        events = await log.get_events(session_id="session-private-123")
        assert [event.event_type for event in events] == [
            "semantic_memory_write"
        ]
        payload = events[0].payload
        assert payload["schema_version"] == "wiii.semantic_memory_write.v1"
        assert payload["write"]["stored_fact_count"] == 2
        assert payload["write"]["status"] == "saved"
        serialized = str(payload)
        assert "user-private-123" not in serialized
        assert "session-private-123" not in serialized
        assert "PRIVATE USER MESSAGE" not in serialized
        assert "PRIVATE ASSISTANT RESPONSE" not in serialized
        assert "raw-user-token" not in serialized

    @pytest.mark.asyncio
    async def test_store_interaction_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.runtime.session_event_log import InMemorySessionEventLog

        log = InMemorySessionEventLog()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )
        token = current_org_id.set(None)
        try:
            mock_repo = MagicMock()
            mock_embeddings = MagicMock()
            mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
            engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)

            result = await engine.store_interaction(
                user_id="user-private-123",
                message="PRIVATE USER MESSAGE",
                response="PRIVATE ASSISTANT RESPONSE",
                session_id="session-private-123",
            )
        finally:
            current_org_id.reset(token)

        assert result is False
        mock_repo.save_memory.assert_not_called()
        mock_embeddings.aembed_documents.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["status"] == "blocked"
        assert payload["scope"]["write_allowed"] is False
        assert (
            payload["scope"]["organization_context"]
            == "blocked_missing_org_context"
        )
        serialized = str(payload)
        assert "PRIVATE USER MESSAGE" not in serialized
        assert "PRIVATE ASSISTANT RESPONSE" not in serialized


# =============================================================================
# count_tokens
# =============================================================================


class TestCountTokens:
    """Test token counting."""

    def test_fallback_without_tiktoken(self):
        engine = _make_engine()
        with patch.dict("sys.modules", {"tiktoken": None}):
            result = engine.count_tokens("Hello world test")
            # Fallback: len // 4
            assert result == len("Hello world test") // 4

    def test_empty_string(self):
        engine = _make_engine()
        result = engine.count_tokens("")
        assert result == 0


# =============================================================================
# count_session_tokens
# =============================================================================


class TestCountSessionTokens:
    """Test session token counting."""

    def test_counts_tokens_from_messages(self):
        mock_repo = MagicMock()
        msg1 = MagicMock()
        msg1.content = "Hello world"
        msg2 = MagicMock()
        msg2.content = "How are you"
        mock_repo.get_memories_by_type.return_value = [msg1, msg2]

        engine = _make_engine(repo=mock_repo)
        result = engine.count_session_tokens("user-1", "session-1")
        assert result > 0

    def test_returns_zero_for_empty_session(self):
        mock_repo = MagicMock()
        mock_repo.get_memories_by_type.return_value = []
        engine = _make_engine(repo=mock_repo)
        result = engine.count_session_tokens("user-1", "session-1")
        assert result == 0

    def test_returns_zero_on_error(self):
        mock_repo = MagicMock()
        mock_repo.get_memories_by_type.side_effect = RuntimeError("DB error")
        engine = _make_engine(repo=mock_repo)
        result = engine.count_session_tokens("user-1", "session-1")
        assert result == 0


# =============================================================================
# delete_memory_by_keyword
# =============================================================================


class TestDeleteMemoryByKeyword:
    """Test keyword-based memory deletion."""

    @pytest.mark.asyncio
    async def test_deletes_matching(self):
        mock_repo = MagicMock()
        mock_repo.delete_memories_by_keyword.return_value = 3
        engine = _make_engine(repo=mock_repo)

        result = await engine.delete_memory_by_keyword("user-1", "COLREGs")
        assert result == 3
        mock_repo.delete_memories_by_keyword.assert_called_once_with(
            user_id="user-1", keyword="COLREGs"
        )

    @pytest.mark.asyncio
    async def test_returns_zero_on_no_match(self):
        mock_repo = MagicMock()
        mock_repo.delete_memories_by_keyword.return_value = 0
        engine = _make_engine(repo=mock_repo)
        result = await engine.delete_memory_by_keyword("user-1", "nonexistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_error(self):
        mock_repo = MagicMock()
        mock_repo.delete_memories_by_keyword.side_effect = RuntimeError("DB fail")
        engine = _make_engine(repo=mock_repo)
        result = await engine.delete_memory_by_keyword("user-1", "test")
        assert result == 0

    @pytest.mark.asyncio
    async def test_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        mock_repo = MagicMock()
        engine = _make_engine(repo=mock_repo)

        token = current_org_id.set(None)
        try:
            result = await engine.delete_memory_by_keyword(
                "user-private-123",
                "PRIVATE KEYWORD",
            )
        finally:
            current_org_id.reset(token)

        assert result == 0
        mock_repo.delete_memories_by_keyword.assert_not_called()


# =============================================================================
# delete_all_user_memories
# =============================================================================


class TestDeleteAllUserMemories:
    """Test factory reset."""

    @pytest.mark.asyncio
    async def test_deletes_all(self):
        mock_repo = MagicMock()
        mock_repo.delete_all_user_memories.return_value = 10
        engine = _make_engine(repo=mock_repo)

        result = await engine.delete_all_user_memories("user-1")
        assert result == 10
        mock_repo.delete_all_user_memories.assert_called_once_with(user_id="user-1")

    @pytest.mark.asyncio
    async def test_returns_zero_on_error(self):
        mock_repo = MagicMock()
        mock_repo.delete_all_user_memories.side_effect = RuntimeError("DB error")
        engine = _make_engine(repo=mock_repo)
        result = await engine.delete_all_user_memories("user-1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        mock_repo = MagicMock()
        engine = _make_engine(repo=mock_repo)

        token = current_org_id.set(None)
        try:
            result = await engine.delete_all_user_memories("user-private-123")
        finally:
            current_org_id.reset(token)

        assert result == 0
        mock_repo.delete_all_user_memories.assert_not_called()


# =============================================================================
# store_explicit_insight
# =============================================================================


class TestStoreExplicitInsight:
    """Test explicit insight storage (tool_remember)."""

    @pytest.mark.asyncio
    async def test_stores_with_max_confidence(self):
        mock_repo = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo.save_memory.return_value = MagicMock()

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        result = await engine.store_explicit_insight(
            user_id="user-1",
            insight_text="I prefer visual learning",
            category="preference",
            session_id="sess-1",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_category_defaults_to_preference(self):
        mock_repo = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo.save_memory.return_value = MagicMock()

        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)
        result = await engine.store_explicit_insight(
            user_id="user-1",
            insight_text="Test",
            category="invalid_category_here",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        engine = _make_engine()
        engine._insight_provider._store_insight = AsyncMock(side_effect=RuntimeError("fail"))
        result = await engine.store_explicit_insight("user-1", "Test")
        assert result is False

    @pytest.mark.asyncio
    async def test_store_explicit_insight_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.runtime.session_event_log import InMemorySessionEventLog

        log = InMemorySessionEventLog()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )

        mock_repo = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        engine = _make_engine(repo=mock_repo, embeddings=mock_embeddings)

        token = current_org_id.set(None)
        try:
            result = await engine.store_explicit_insight(
                user_id="user-private-123",
                insight_text="PRIVATE INSIGHT access_token=raw-insight-token-12345",
                category="preference",
                session_id="session-private-123",
            )
        finally:
            current_org_id.reset(token)

        assert result is False
        mock_embeddings.aembed_documents.assert_not_awaited()
        mock_repo.save_memory.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["kind"] == "insight_store"
        assert payload["write"]["status"] == "blocked"
        assert payload["scope"]["write_allowed"] is False
        serialized = str(payload)
        assert "PRIVATE INSIGHT" not in serialized
        assert "raw-insight-token" not in serialized
        assert "user-private-123" not in serialized
