"""
Tests for Sprint 73: Enhanced Extraction in FactExtractor.

Covers:
- _build_enhanced_prompt (existing facts block, 15 categories, no existing facts)
- _build_legacy_prompt (old 6-type format)
- _build_fact_extraction_prompt dispatching (enhanced vs legacy via settings)
- extract_user_facts / extract_and_store_facts passing existing_facts
- extract_and_store_facts invalidating CoreMemoryBlock cache on success
- _parse_fact_extraction_response handling new fact types (age, location, etc.)
- _validate_fact_type accepting new types + strong_area mapping
- IGNORED_FACT_TYPES empty, ALLOWED_FACT_TYPES has 15 entries
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.semantic_memory import (
    ALLOWED_FACT_TYPES,
    FACT_TYPE_MAPPING,
    IGNORED_FACT_TYPES,
    FactType,
    UserFact,
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
# _build_enhanced_prompt
# ============================================================================


class TestBuildEnhancedPrompt:
    """Test Sprint 73 enhanced Mem0-style prompt."""

    def test_includes_existing_facts_block(self):
        """When existing_facts is provided, prompt includes the known-facts block."""
        fe = _make_extractor()
        existing = {"name": "Minh", "role": "sinh vien", "goal": "hoc COLREGs"}
        prompt = fe._build_enhanced_prompt("Hello", existing_facts=existing)

        assert "KHONG trich xuat lai" in prompt.replace("\u0110\u00c3", "DA").replace(
            "\u00c3", "A"
        ) or "ĐÃ BIẾT" in prompt
        assert "name: Minh" in prompt
        assert "role: sinh vien" in prompt
        assert "goal: hoc COLREGs" in prompt

    def test_no_existing_facts(self):
        """When existing_facts is None, prompt does not include known-facts block."""
        fe = _make_extractor()
        prompt = fe._build_enhanced_prompt("Hello", existing_facts=None)

        # Should NOT contain the existing facts header
        assert "ĐÃ BIẾT" not in prompt
        # But should still contain the message and instructions
        assert "Hello" in prompt
        assert "fact_type" in prompt

    def test_empty_existing_facts(self):
        """When existing_facts is empty dict, no existing facts block."""
        fe = _make_extractor()
        prompt = fe._build_enhanced_prompt("Hello", existing_facts={})

        assert "ĐÃ BIẾT" not in prompt

    def test_mentions_15_fact_types(self):
        """Enhanced prompt lists all 15 fact types."""
        fe = _make_extractor()
        prompt = fe._build_enhanced_prompt("Hello")

        expected_types = [
            "name", "age", "role", "level", "location", "organization",
            "goal", "preference", "weakness", "strength", "learning_style",
            "hobby", "interest", "emotion", "recent_topic",
        ]
        for ft in expected_types:
            assert ft in prompt, f"Expected fact type '{ft}' in enhanced prompt"


# ============================================================================
# _build_legacy_prompt
# ============================================================================


class TestBuildLegacyPrompt:
    """Test pre-Sprint 73 legacy prompt format."""

    def test_legacy_prompt_contains_message(self):
        fe = _make_extractor()
        prompt = fe._build_legacy_prompt("Toi la Minh")
        assert "Toi la Minh" in prompt

    def test_legacy_prompt_mentions_old_types(self):
        """Legacy prompt should mention the old type set (name, preference, goal, etc.)."""
        fe = _make_extractor()
        prompt = fe._build_legacy_prompt("Hello")
        for ft in ["name", "preference", "goal", "background", "weak_area", "strong_area"]:
            assert ft in prompt, f"Expected '{ft}' in legacy prompt"

    def test_legacy_prompt_does_not_mention_new_types(self):
        """Legacy prompt should NOT mention Sprint 73 new types like 'age', 'emotion'."""
        fe = _make_extractor()
        prompt = fe._build_legacy_prompt("Hello")
        # The legacy prompt uses a fixed set; 'emotion' and 'recent_topic' are new
        # Check that the 15-type instruction block is not present
        assert "Personal Information Organizer" not in prompt


# ============================================================================
# _build_fact_extraction_prompt dispatching
# ============================================================================


class TestBuildFactExtractionPromptDispatch:
    """Test that _build_fact_extraction_prompt dispatches based on settings."""

    def test_dispatches_to_enhanced_when_enabled(self):
        """When enable_enhanced_extraction=True, uses enhanced prompt."""
        fe = _make_extractor()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_enhanced_extraction = True
            prompt = fe._build_fact_extraction_prompt("Toi la Minh, 25 tuoi")

        # Enhanced prompt signature
        assert "Personal Information Organizer" in prompt
        assert "Toi la Minh, 25 tuoi" in prompt

    def test_dispatches_to_legacy_when_disabled(self):
        """When enable_enhanced_extraction=False, uses legacy prompt."""
        fe = _make_extractor()

        with patch("app.engine.semantic_memory.extraction.settings") as mock_settings:
            mock_settings.enable_enhanced_extraction = False
            prompt = fe._build_fact_extraction_prompt("Toi la Minh")

        # Legacy prompt signature
        assert "Personal Information Organizer" not in prompt
        assert "Toi la Minh" in prompt
        assert "fact_type" in prompt

    def test_passes_existing_facts_to_enhanced(self):
        """existing_facts argument is forwarded to _build_enhanced_prompt."""
        fe = _make_extractor()
        existing = {"name": "Linh"}

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_enhanced_extraction = True
            prompt = fe._build_fact_extraction_prompt("Hello", existing_facts=existing)

        assert "name: Linh" in prompt


# ============================================================================
# extract_user_facts passes existing_facts
# ============================================================================


class TestExtractUserFactsExistingFacts:
    """Test that extract_user_facts passes existing_facts to prompt builder."""

    @pytest.mark.asyncio
    async def test_passes_existing_facts_to_prompt_builder(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "[]"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        fe = _make_extractor(llm=mock_llm)

        existing = {"name": "Minh", "age": "25"}

        with patch.object(fe, "_build_fact_extraction_prompt", return_value="prompt") as mock_build, \
             patch("app.services.output_processor.extract_thinking_from_response",
                   return_value=("[]", None)):
            await fe.extract_user_facts("u1", "Hello", existing_facts=existing)

        mock_build.assert_called_once_with("Hello", existing)


# ============================================================================
# extract_and_store_facts passes existing_facts
# ============================================================================


class TestExtractAndStoreFactsExistingFacts:
    """Test that extract_and_store_facts passes existing_facts through."""

    @pytest.mark.asyncio
    async def test_passes_existing_facts_through(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "[]"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        fe = _make_extractor(llm=mock_llm)

        existing = {"name": "Minh"}

        with patch.object(fe, "extract_user_facts", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = MagicMock(has_facts=False, facts=[])
            await fe.extract_and_store_facts("u1", "Hello", existing_facts=existing)

        mock_extract.assert_called_once_with("u1", "Hello", existing_facts=existing)


# ============================================================================
# extract_and_store_facts invalidates CoreMemoryBlock cache
# ============================================================================


class TestExtractAndStoreFactsCacheInvalidation:
    """Test that successful fact storage invalidates CoreMemoryBlock cache."""

    @pytest.mark.asyncio
    async def test_invalidates_cache_on_success(self):
        mock_llm = AsyncMock()
        facts_json = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 0.95},
        ])
        mock_response = MagicMock()
        mock_response.content = facts_json
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        fe = _make_extractor(llm=mock_llm)
        fe._repository.find_similar_fact_by_embedding.return_value = None
        fe._repository.find_fact_by_type.return_value = None
        fe._repository.save_memory.return_value = MagicMock(id="memory-1")
        fe._repository.count_user_memories.return_value = 5

        mock_cmb = MagicMock()

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=(facts_json, None)), \
             patch("app.engine.semantic_memory.core_memory_block.get_core_memory_block",
                    return_value=mock_cmb) as mock_get_cmb:
            result = await fe.extract_and_store_facts("u1", "Toi la Minh")

        assert len(result) == 1
        mock_get_cmb.assert_called_once()
        mock_cmb.invalidate.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_no_invalidation_when_no_facts_stored(self):
        """Cache is NOT invalidated when no facts are stored."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "[]"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        fe = _make_extractor(llm=mock_llm)

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("[]", None)), \
             patch("app.engine.semantic_memory.core_memory_block.get_core_memory_block") as mock_get_cmb:
            result = await fe.extract_and_store_facts("u1", "Hello")

        assert result == []
        mock_get_cmb.assert_not_called()


# ============================================================================
# _parse_fact_extraction_response handles new fact types
# ============================================================================


class TestParseNewFactTypes:
    """Test that _parse_fact_extraction_response handles Sprint 73 new types."""

    def test_parse_age_fact(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "age", "value": "25", "confidence": 0.9},
        ])
        facts = fe._parse_fact_extraction_response(response, "Toi 25 tuoi")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.AGE
        assert facts[0].value == "25"

    def test_parse_location_fact(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "location", "value": "TP.HCM", "confidence": 0.85},
        ])
        facts = fe._parse_fact_extraction_response(response, "Toi o TP.HCM")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.LOCATION

    def test_parse_organization_fact(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "organization", "value": "DH Hang Hai", "confidence": 0.9},
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.ORGANIZATION

    def test_parse_emotion_fact(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "emotion", "value": "vui", "confidence": 0.7},
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert len(facts) == 1
        assert facts[0].fact_type == FactType.EMOTION

    def test_parse_multiple_new_types(self):
        fe = _make_extractor()
        response = json.dumps([
            {"fact_type": "name", "value": "Minh", "confidence": 0.95},
            {"fact_type": "age", "value": "25", "confidence": 0.9},
            {"fact_type": "location", "value": "Sai Gon", "confidence": 0.85},
            {"fact_type": "hobby", "value": "doc sach", "confidence": 0.8},
            {"fact_type": "recent_topic", "value": "COLREGs", "confidence": 0.7},
        ])
        facts = fe._parse_fact_extraction_response(response, "msg")
        assert len(facts) == 5
        types = {f.fact_type for f in facts}
        assert types == {
            FactType.NAME, FactType.AGE, FactType.LOCATION,
            FactType.HOBBY, FactType.RECENT_TOPIC,
        }


# ============================================================================
# _validate_fact_type — new types and mappings
# ============================================================================


class TestValidateNewFactTypes:
    """Test _validate_fact_type with Sprint 73 new types and mappings."""

    @pytest.mark.parametrize("new_type", [
        "age", "location", "organization", "strength", "hobby",
        "emotion", "recent_topic", "learning_style", "level",
    ])
    def test_accepts_new_types(self, new_type):
        fe = _make_extractor()
        assert fe._validate_fact_type(new_type) == new_type

    def test_maps_strong_area_to_strength(self):
        """Sprint 73: strong_area is now mapped to strength (not ignored)."""
        fe = _make_extractor()
        result = fe._validate_fact_type("strong_area")
        assert result == "strength"

    def test_maps_weak_area_to_weakness(self):
        fe = _make_extractor()
        assert fe._validate_fact_type("weak_area") == "weakness"

    def test_maps_background_to_role(self):
        fe = _make_extractor()
        assert fe._validate_fact_type("background") == "role"

    def test_truly_unknown_type_returns_none(self):
        fe = _make_extractor()
        assert fe._validate_fact_type("zodiac_sign") is None
        assert fe._validate_fact_type("blood_type") is None
        assert fe._validate_fact_type("favorite_color") is None


# ============================================================================
# Constants validation
# ============================================================================


class TestConstants:
    """Test Sprint 73 constant definitions."""

    def test_ignored_fact_types_is_empty(self):
        """Sprint 73: IGNORED_FACT_TYPES is empty (strong_area moved to FACT_TYPE_MAPPING)."""
        assert IGNORED_FACT_TYPES == set()

    def test_allowed_fact_types_has_17_entries(self):
        """Sprint 73: 15; Sprint 79: +pronoun_style → 16; Sprint 89: +hometown → 17."""
        assert len(ALLOWED_FACT_TYPES) == 17
        expected = {
            "name", "age", "hometown", "role", "level", "location", "organization",
            "goal", "preference", "weakness", "strength", "learning_style",
            "hobby", "interest", "emotion", "recent_topic", "pronoun_style",
        }
        assert ALLOWED_FACT_TYPES == expected

    def test_fact_type_mapping_includes_strong_area(self):
        """strong_area is mapped to strength in FACT_TYPE_MAPPING."""
        assert "strong_area" in FACT_TYPE_MAPPING
        assert FACT_TYPE_MAPPING["strong_area"] == "strength"


# ============================================================================
# core.py _extract_and_store_facts passes existing_facts (Sprint 73 fix)
# ============================================================================


class TestCoreExtractAndStoreFactsPassesExistingFacts:
    """
    Sprint 73 fix: core.py:_extract_and_store_facts() must fetch existing
    facts and pass them to FactExtractor so ALL messages (including tutor/RAG
    routed) get context-aware extraction.
    """

    @pytest.mark.asyncio
    async def test_fetches_and_passes_existing_facts(self):
        """_extract_and_store_facts calls get_user_facts and passes result."""
        from app.engine.semantic_memory.core import SemanticMemoryEngine

        mock_repo = MagicMock()
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        engine = SemanticMemoryEngine.__new__(SemanticMemoryEngine)
        engine._repository = mock_repo
        engine._embeddings = mock_embeddings
        engine._fact_extractor = MagicMock()
        engine._fact_extractor.extract_and_store_facts = AsyncMock(return_value=[])

        # Mock get_user_facts to return existing facts
        from datetime import datetime, timezone
        _ts = datetime(2026, 2, 17, tzinfo=timezone.utc)
        mock_fact1 = MagicMock(content="name: Minh", metadata={"fact_type": "name"})
        mock_fact1.updated_at = _ts
        mock_fact1.created_at = _ts
        mock_fact2 = MagicMock(content="role: student", metadata={"fact_type": "role"})
        mock_fact2.updated_at = _ts
        mock_fact2.created_at = _ts
        mock_repo.get_user_facts = MagicMock(return_value=[mock_fact1, mock_fact2])

        await engine._extract_and_store_facts("user-1", "I am in SG", "sess-1")

        # Verify existing_facts was passed (contains fact values + __updated_at keys)
        call_kwargs = engine._fact_extractor.extract_and_store_facts.call_args
        passed_facts = call_kwargs.kwargs.get("existing_facts")
        assert passed_facts["name"] == "Minh"
        assert passed_facts["role"] == "student"

    @pytest.mark.asyncio
    async def test_graceful_on_get_user_facts_error(self):
        """If get_user_facts raises, extraction still runs (with empty dict)."""
        from app.engine.semantic_memory.core import SemanticMemoryEngine

        mock_repo = MagicMock()
        mock_embeddings = AsyncMock()

        engine = SemanticMemoryEngine.__new__(SemanticMemoryEngine)
        engine._repository = mock_repo
        engine._embeddings = mock_embeddings
        engine._fact_extractor = MagicMock()
        engine._fact_extractor.extract_and_store_facts = AsyncMock(return_value=[])

        # get_user_facts raises internally → returns {} (graceful)
        mock_repo.get_user_facts = MagicMock(side_effect=Exception("DB error"))

        await engine._extract_and_store_facts("user-1", "test", "sess-1")

        # Should still call extract — with {} since get_user_facts returns {} on error
        engine._fact_extractor.extract_and_store_facts.assert_called_once()
        call_kwargs = engine._fact_extractor.extract_and_store_facts.call_args
        assert call_kwargs.kwargs.get("existing_facts") == {}
