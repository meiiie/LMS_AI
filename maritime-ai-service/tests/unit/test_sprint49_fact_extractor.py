"""
Tests for Sprint 49: FactExtractor coverage.

Tests fact extraction pipeline including:
- __init__, _ensure_llm (lazy init, failure)
- _validate_fact_type (allowed, ignored, mapped, unknown)
- _build_fact_extraction_prompt (contains message)
- _parse_fact_extraction_response (valid, markdown, invalid JSON, not array, bad types, confidence clamp)
- store_user_fact_upsert (semantic duplicate, type fallback, insert new, cap, validate fail, error)
- _enforce_memory_cap (under, over, error)
- extract_user_facts (no LLM, success, error)
- extract_and_store_facts (no LLM, no facts, success, runtime error, general error)
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.semantic_memory import (
    ALLOWED_FACT_TYPES,
    FACT_TYPE_MAPPING,
    IGNORED_FACT_TYPES,
    FactType,
    MemoryType,
    UserFact,
    UserFactExtraction,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_extractor(llm=None):
    """Create FactExtractor with mocked dependencies."""
    from app.engine.semantic_memory.extraction import FactExtractor

    mock_embeddings = AsyncMock()
    mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
    mock_repo = MagicMock()
    return FactExtractor(
        embeddings=mock_embeddings,
        repository=mock_repo,
        llm=llm,
    )


# ============================================================================
# __init__
# ============================================================================


class TestInit:
    """Test FactExtractor initialization."""

    def test_stores_deps(self):
        from app.engine.semantic_memory.extraction import FactExtractor

        emb = MagicMock()
        repo = MagicMock()
        llm = MagicMock()
        fe = FactExtractor(embeddings=emb, repository=repo, llm=llm)
        assert fe._embeddings is emb
        assert fe._repository is repo
        assert fe._llm is llm

    def test_llm_default_none(self):
        fe = _make_extractor()
        assert fe._llm is None


# ============================================================================
# _ensure_llm
# ============================================================================


class TestEnsureLlm:
    """Test lazy LLM initialization."""

    def test_lazy_init_success(self):
        fe = _make_extractor()
        mock_llm = MagicMock()
        with patch("app.engine.semantic_memory.extraction.get_llm_light", return_value=mock_llm):
            fe._ensure_llm()
        assert fe._llm is mock_llm

    def test_lazy_init_already_set(self):
        existing_llm = MagicMock()
        fe = _make_extractor(llm=existing_llm)
        fe._ensure_llm()
        assert fe._llm is existing_llm

    def test_lazy_init_failure(self):
        fe = _make_extractor()
        with patch("app.engine.semantic_memory.extraction.get_llm_light", side_effect=Exception("No API key")):
            fe._ensure_llm()
        assert fe._llm is None


# ============================================================================
# _validate_fact_type
# ============================================================================


class TestValidateFactType:
    """Test fact type validation and normalization."""

    def test_allowed_types(self):
        fe = _make_extractor()
        for ft in ALLOWED_FACT_TYPES:
            assert fe._validate_fact_type(ft) == ft

    def test_case_insensitive(self):
        fe = _make_extractor()
        assert fe._validate_fact_type("NAME") == "name"
        assert fe._validate_fact_type("  Goal  ") == "goal"

    def test_ignored_types(self):
        fe = _make_extractor()
        for ft in IGNORED_FACT_TYPES:
            assert fe._validate_fact_type(ft) is None

    def test_mapped_types(self):
        fe = _make_extractor()
        for old_type, new_type in FACT_TYPE_MAPPING.items():
            assert fe._validate_fact_type(old_type) == new_type

    def test_unknown_type(self):
        fe = _make_extractor()
        assert fe._validate_fact_type("zodiac_sign") is None
        assert fe._validate_fact_type("") is None


# ============================================================================
# _build_fact_extraction_prompt
# ============================================================================


class TestBuildPrompt:
    """Test prompt building."""

    def test_contains_message(self):
        fe = _make_extractor()
        prompt = fe._build_fact_extraction_prompt("Toi la Minh")
        assert "Toi la Minh" in prompt

    def test_contains_instructions(self):
        fe = _make_extractor()
        prompt = fe._build_fact_extraction_prompt("Hello")
        assert "fact_type" in prompt
        assert "JSON" in prompt

    def test_enhanced_prompt_with_existing_facts(self):
        """Sprint 73: Enhanced prompt includes existing facts block."""
        fe = _make_extractor()
        existing = {"name": "Minh", "role": "sinh viên"}
        prompt = fe._build_enhanced_prompt("Hello", existing)
        assert "Minh" in prompt
        assert "sinh viên" in prompt
        assert "ĐÃ BIẾT" in prompt

    def test_legacy_prompt_format(self):
        """Sprint 73: Legacy prompt still works."""
        fe = _make_extractor()
        prompt = fe._build_legacy_prompt("Hello")
        assert "background" in prompt
        assert "strong_area" in prompt


# ============================================================================
# _parse_fact_extraction_response
# ============================================================================


class TestParseResponse:
    """Test LLM response parsing."""

    def test_valid_json(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 0.95}
        ])
        facts = fe._parse_fact_extraction_response(response, "Toi la Minh")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.NAME
        assert facts[0].value == "Minh"
        assert facts[0].confidence == 0.95

    def test_markdown_code_block(self):
        fe = _make_extractor()
        response = '```json\n[{"fact_type": "goal", "value": "Learn COLREGs", "confidence": 0.8}]\n```'
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.GOAL

    def test_plain_code_block(self):
        fe = _make_extractor()
        response = '```\n[{"fact_type": "role", "value": "Captain", "confidence": 0.9}]\n```'
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.ROLE

    def test_invalid_json(self):
        fe = _make_extractor()
        facts = fe._parse_fact_extraction_response("not json {}", "msg")
        assert facts == []

    def test_not_array(self):
        fe = _make_extractor()
        facts = fe._parse_fact_extraction_response('{"fact": "value"}', "msg")
        assert facts == []

    def test_empty_array(self):
        fe = _make_extractor()
        facts = fe._parse_fact_extraction_response("[]", "msg")
        assert facts == []

    def test_invalid_fact_type_skipped(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "invalid_type", "value": "something", "confidence": 0.8}
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert facts == []

    def test_empty_value_skipped(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "", "confidence": 0.8}
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert facts == []

    def test_confidence_clamped(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 1.5}
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert facts[0].confidence == 1.0

    def test_confidence_clamped_low(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": -0.5}
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert facts[0].confidence == 0.0

    def test_default_confidence(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "Minh"}
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert facts[0].confidence == 0.8

    def test_multiple_facts(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 0.9},
            {"fact_type": "goal", "value": "Learn COLREGs", "confidence": 0.85},
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert len(facts) == 2


# ============================================================================
# store_user_fact_upsert
# ============================================================================


class TestStoreUserFactUpsert:
    """Test upsert logic for user facts."""

    @pytest.mark.asyncio
    async def test_invalid_type_returns_false(self):
        fe = _make_extractor()
        result = await fe.store_user_fact_upsert("u1", "some content", fact_type="zodiac")
        assert result is False

    @pytest.mark.asyncio
    async def test_semantic_duplicate_updates(self):
        fe = _make_extractor()
        mock_existing = MagicMock()
        mock_existing.id = "fact-id-1"
        fe._repository.find_similar_fact_by_embedding.return_value = mock_existing
        fe._repository.update_fact.return_value = True

        result = await fe.store_user_fact_upsert("u1", "name: Minh", fact_type="name")
        assert result is True
        fe._repository.update_fact.assert_called_once()

    @pytest.mark.asyncio
    async def test_type_based_fallback_updates(self):
        fe = _make_extractor()
        fe._repository.find_similar_fact_by_embedding.return_value = None
        mock_existing = MagicMock()
        mock_existing.id = "fact-id-2"
        fe._repository.find_fact_by_type.return_value = mock_existing
        fe._repository.update_fact.return_value = True

        result = await fe.store_user_fact_upsert("u1", "name: Linh", fact_type="name")
        assert result is True
        fe._repository.update_fact.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_new_fact(self):
        fe = _make_extractor()
        fe._repository.find_similar_fact_by_embedding.return_value = None
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = MagicMock()
        fe._repository.count_user_memories.return_value = 5

        result = await fe.store_user_fact_upsert("u1", "goal: Learn COLREGs", fact_type="goal")
        assert result is True
        fe._repository.save_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_triggers_cap_enforcement(self):
        """Sprint 122 F5: importance-aware eviction replaces FIFO delete_oldest_facts."""
        from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult
        from datetime import datetime, timezone, timedelta

        fe = _make_extractor()
        fe._repository.find_similar_fact_by_embedding.return_value = None
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = MagicMock()
        fe._repository.count_user_memories.return_value = 55

        # Mock get_all_user_facts for importance-aware eviction
        now = datetime.now(timezone.utc)
        fe._repository.get_all_user_facts.return_value = [
            SemanticMemorySearchResult(
                id=uuid4(), content=f"emotion: test_{i}",
                memory_type=MemoryType.USER_FACT, importance=0.2, similarity=1.0,
                metadata={"fact_type": "emotion", "access_count": 0},
                created_at=now - timedelta(days=10),
            ) for i in range(55)
        ]
        fe._repository.delete_memory.return_value = True

        result = await fe.store_user_fact_upsert("u1", "goal: Learn SOLAS", fact_type="goal")
        assert result is True
        # Importance-aware eviction calls delete_memory (not delete_oldest_facts)
        assert fe._repository.delete_memory.call_count >= 1

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        fe = _make_extractor()
        fe._embeddings.aembed_documents = AsyncMock(side_effect=Exception("Embedding error"))
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = None

        result = await fe.store_user_fact_upsert("u1", "name: Minh", fact_type="name")
        assert result is False

    @pytest.mark.asyncio
    async def test_embedding_failure_falls_back_to_insert_without_vector(self):
        fe = _make_extractor()
        fe._embeddings.aembed_documents = AsyncMock(side_effect=Exception("Embedding error"))
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = MagicMock()

        result = await fe.store_user_fact_upsert("u1", "name: Minh", fact_type="name")

        assert result is True
        fe._repository.find_similar_fact_by_embedding.assert_not_called()
        saved = fe._repository.save_memory.call_args[0][0]
        assert saved.embedding == []

    @pytest.mark.asyncio
    async def test_embedding_failure_updates_existing_fact_preserving_embedding(self):
        fe = _make_extractor()
        fe._embeddings.aembed_documents = AsyncMock(side_effect=Exception("Embedding error"))
        fe._repository.find_similar_fact_by_embedding.return_value = None
        mock_existing = MagicMock()
        mock_existing.id = "fact-id-3"
        fe._repository.find_fact_by_type.return_value = mock_existing
        fe._repository.update_fact_preserve_embedding.return_value = True

        result = await fe.store_user_fact_upsert("u1", "name: Linh", fact_type="name")

        assert result is True
        fe._repository.update_fact.assert_not_called()
        fe._repository.update_fact_preserve_embedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_mapped_type_used(self):
        fe = _make_extractor()
        fe._repository.find_similar_fact_by_embedding.return_value = None
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = MagicMock()
        fe._repository.count_user_memories.return_value = 1

        # "background" should be mapped to "role"
        result = await fe.store_user_fact_upsert("u1", "role: Captain", fact_type="background")
        assert result is True
        call_args = fe._repository.save_memory.call_args
        saved = call_args[0][0]
        assert saved.metadata["fact_type"] == "role"

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_embedding(
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

        fe = _make_extractor()
        token = current_org_id.set(None)
        try:
            result = await fe.store_user_fact_upsert(
                user_id="user-private-123",
                fact_content="PRIVATE FACT access_token=raw-fact-token-12345",
                fact_type="goal",
                session_id="session-private-123",
                source_message="PRIVATE MESSAGE",
            )
        finally:
            current_org_id.reset(token)

        assert result is False
        fe._embeddings.aembed_documents.assert_not_awaited()
        fe._repository.save_memory.assert_not_called()
        fe._repository.update_fact.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["kind"] == "fact_upsert"
        assert payload["write"]["status"] == "blocked"
        assert payload["scope"]["write_allowed"] is False
        assert (
            payload["scope"]["organization_context"]
            == "blocked_missing_org_context"
        )
        serialized = str(payload)
        assert "PRIVATE FACT" not in serialized
        assert "raw-fact-token" not in serialized
        assert "user-private-123" not in serialized
        assert "session-private-123" not in serialized


# ============================================================================
# _enforce_memory_cap
# ============================================================================


class TestEnforceMemoryCap:
    """Test FIFO memory cap enforcement."""

    @pytest.mark.asyncio
    async def test_under_cap(self):
        fe = _make_extractor()
        fe._repository.count_user_memories.return_value = 30
        deleted = await fe._enforce_memory_cap("u1")
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_at_cap(self):
        fe = _make_extractor()
        fe._repository.count_user_memories.return_value = 50
        deleted = await fe._enforce_memory_cap("u1")
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_over_cap(self):
        """Sprint 122 F5: importance-aware eviction replaces FIFO."""
        from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult
        from datetime import datetime, timezone, timedelta

        fe = _make_extractor()
        now = datetime.now(timezone.utc)
        # 55 volatile facts → need to evict 5 to reach cap (50)
        fe._repository.get_all_user_facts.return_value = [
            SemanticMemorySearchResult(
                id=uuid4(), content=f"emotion: test_{i}",
                memory_type=MemoryType.USER_FACT, importance=0.2, similarity=1.0,
                metadata={"fact_type": "emotion", "access_count": 0},
                created_at=now - timedelta(days=10),
            ) for i in range(55)
        ]
        fe._repository.delete_memory.return_value = True

        deleted = await fe._enforce_memory_cap("u1")
        assert deleted == 5
        assert fe._repository.delete_memory.call_count == 5

    @pytest.mark.asyncio
    async def test_error(self):
        fe = _make_extractor()
        fe._repository.count_user_memories.side_effect = Exception("DB error")
        deleted = await fe._enforce_memory_cap("u1")
        assert deleted == 0


# ============================================================================
# extract_user_facts
# ============================================================================


class TestExtractUserFacts:
    """Test LLM-based fact extraction."""

    @pytest.mark.asyncio
    async def test_no_llm(self):
        fe = _make_extractor()
        # _ensure_llm won't set _llm since get_llm_light is not mocked
        with patch("app.engine.semantic_memory.extraction.get_llm_light", side_effect=Exception("No key")):
            result = await fe.extract_user_facts("u1", "Hello")
        assert result.facts == []
        assert result.raw_message == "Hello"

    @pytest.mark.asyncio
    async def test_success(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 0.95}
        ])
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        fe = _make_extractor(llm=mock_llm)

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=(mock_response.content, None)):
            result = await fe.extract_user_facts("u1", "Toi la Minh")

        assert result.has_facts
        assert result.facts[0].value == "Minh"

    @pytest.mark.asyncio
    async def test_llm_error(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM failed"))
        fe = _make_extractor(llm=mock_llm)

        result = await fe.extract_user_facts("u1", "Hello")
        assert result.facts == []


# ============================================================================
# extract_and_store_facts
# ============================================================================


class TestExtractAndStoreFacts:
    """Test full extract+store pipeline."""

    @pytest.mark.asyncio
    async def test_no_llm(self):
        fe = _make_extractor()
        with patch("app.engine.semantic_memory.extraction.get_llm_light", side_effect=Exception("No key")):
            result = await fe.extract_and_store_facts("u1", "Hello")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_facts_extracted(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "[]"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        fe = _make_extractor(llm=mock_llm)

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("[]", None)):
            result = await fe.extract_and_store_facts("u1", "Hello world")
        assert result == []

    @pytest.mark.asyncio
    async def test_success_stores_facts(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        facts_json = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 0.95}
        ])
        mock_response.content = facts_json
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        fe = _make_extractor(llm=mock_llm)
        fe._repository.find_similar_fact_by_embedding.return_value = None
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = MagicMock()
        fe._repository.count_user_memories.return_value = 5

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=(facts_json, None)):
            result = await fe.extract_and_store_facts("u1", "Toi la Minh")

        assert len(result) == 1
        assert result[0].value == "Minh"

    @pytest.mark.asyncio
    async def test_runtime_error_event_loop(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("Event loop is closed"))
        fe = _make_extractor(llm=mock_llm)

        result = await fe.extract_and_store_facts("u1", "Hello")
        assert result == []

    @pytest.mark.asyncio
    async def test_runtime_error_other(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("Other error"))
        fe = _make_extractor(llm=mock_llm)

        result = await fe.extract_and_store_facts("u1", "Hello")
        assert result == []

    @pytest.mark.asyncio
    async def test_general_error(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("Unexpected"))
        fe = _make_extractor(llm=mock_llm)

        result = await fe.extract_and_store_facts("u1", "Hello")
        assert result == []

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_embedding(
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
        fe = _make_extractor()
        fe.extract_user_facts = AsyncMock(return_value=UserFactExtraction(
            facts=[],
            raw_message="PRIVATE MESSAGE",
        ))
        token = current_org_id.set(None)
        try:
            result = await fe.extract_and_store_facts(
                user_id="user-private-123",
                message="PRIVATE MESSAGE access_token=raw-message-token-12345",
                session_id="session-private-123",
            )
        finally:
            current_org_id.reset(token)

        assert result == []
        fe.extract_user_facts.assert_not_awaited()
        fe._embeddings.aembed_documents.assert_not_awaited()
        fe._repository.save_memory.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["kind"] == "fact_extraction"
        assert payload["write"]["status"] == "blocked"
        assert payload["write"]["stored_fact_count"] == 0
        assert payload["scope"]["write_allowed"] is False
        assert (
            payload["scope"]["organization_context"]
            == "blocked_missing_org_context"
        )
        serialized = str(payload)
        assert "PRIVATE MESSAGE" not in serialized
        assert "raw-message-token" not in serialized
        assert "user-private-123" not in serialized
        assert "session-private-123" not in serialized
