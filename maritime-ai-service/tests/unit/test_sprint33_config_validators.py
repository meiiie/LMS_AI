"""
Tests for Sprint 33: Enum and numeric config validators.

Covers:
- llm_provider: google|vertex|openai|openrouter|nvidia|ollama|zhipu
- rag_quality_mode: speed|balanced|quality
- gemini_thinking_level: minimal|low|medium|high
- log_format: json|text
- embedding_dimensions: 128-4096
- cache_max_response_entries: 100-1,000,000
- contextual_rag_batch_size: 1-50
- entity_extraction_batch_size: 1-50
- rag_max_iterations: 1-10
- rag_confidence_high/medium: 0.0-1.0 (via similarity validator)
- multi_agent_grading_threshold: 0.0-10.0
- retrieval_grade_threshold: 0.0-10.0
"""

import pytest
from pydantic import ValidationError


def _make_settings(**overrides):
    """Create Settings with overrides, bypassing .env."""
    from app.core.config import Settings
    defaults = {
        "environment": "development",
        "api_key": "test-key",
        "google_api_key": "test-google-key",
        "llm_provider": "zhipu",
        "rag_quality_mode": "balanced",
        "gemini_thinking_level": "medium",
        "embedding_dimensions": 768,
        "cache_max_response_entries": 10000,
        "rag_max_iterations": 2,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# =============================================================================
# llm_provider
# =============================================================================


class TestLLMProvider:
    def test_default_valid(self):
        s = _make_settings()
        assert s.llm_provider == "zhipu"

    @pytest.mark.parametrize(
        "val",
        ["google", "vertex", "openai", "openrouter", "nvidia", "ollama", "zhipu"],
    )
    def test_valid_providers(self, val):
        s = _make_settings(llm_provider=val)
        assert s.llm_provider == val

    def test_invalid_rejected(self):
        with pytest.raises(ValidationError, match="llm_provider"):
            _make_settings(llm_provider="azure")

    def test_empty_rejected(self):
        with pytest.raises(ValidationError, match="llm_provider"):
            _make_settings(llm_provider="")


class TestVisionProvider:
    @pytest.mark.parametrize(
        "val",
        ["google", "openai", "openrouter", "nvidia", "ollama", "zhipu", "auto"],
    )
    def test_valid_vision_providers(self, val):
        s = _make_settings(vision_provider=val)
        assert s.vision_provider == val

    @pytest.mark.parametrize(
        "field",
        ["vision_describe_provider", "vision_ocr_provider", "vision_grounded_provider"],
    )
    def test_nvidia_valid_for_capability_provider(self, field):
        s = _make_settings(**{field: "nvidia"})
        assert getattr(s, field) == "nvidia"


# =============================================================================
# rag_quality_mode
# =============================================================================


class TestRagQualityMode:
    def test_default_valid(self):
        s = _make_settings()
        assert s.rag_quality_mode == "balanced"

    @pytest.mark.parametrize("val", ["speed", "balanced", "quality"])
    def test_valid_modes(self, val):
        s = _make_settings(rag_quality_mode=val)
        assert s.rag_quality_mode == val

    def test_invalid_rejected(self):
        with pytest.raises(ValidationError, match="rag_quality_mode"):
            _make_settings(rag_quality_mode="turbo")


# =============================================================================
# gemini_thinking_level
# =============================================================================


class TestGeminiThinkingLevel:
    def test_default_valid(self):
        s = _make_settings()
        assert s.gemini_thinking_level == "medium"

    @pytest.mark.parametrize("val", ["minimal", "low", "medium", "high"])
    def test_valid_levels(self, val):
        s = _make_settings(gemini_thinking_level=val)
        assert s.gemini_thinking_level == val

    def test_invalid_rejected(self):
        with pytest.raises(ValidationError, match="gemini_thinking_level"):
            _make_settings(gemini_thinking_level="ultra")


# =============================================================================
# OpenRouter routing validators
# =============================================================================


class TestOpenRouterRoutingValidators:
    def test_data_collection_accepts_allow(self):
        s = _make_settings(openrouter_data_collection="allow")
        assert s.openrouter_data_collection == "allow"

    def test_data_collection_accepts_deny(self):
        s = _make_settings(openrouter_data_collection="deny")
        assert s.openrouter_data_collection == "deny"

    def test_data_collection_rejects_invalid_value(self):
        with pytest.raises(ValidationError, match="openrouter_data_collection"):
            _make_settings(openrouter_data_collection="archive")

    @pytest.mark.parametrize("val", ["price", "latency", "throughput"])
    def test_provider_sort_accepts_known_values(self, val):
        s = _make_settings(openrouter_provider_sort=val)
        assert s.openrouter_provider_sort == val

    def test_provider_sort_rejects_invalid_value(self):
        with pytest.raises(ValidationError, match="openrouter_provider_sort"):
            _make_settings(openrouter_provider_sort="balanced")

    def test_string_lists_are_trimmed_and_deduped(self):
        s = _make_settings(
            openrouter_provider_order=[" openai ", "anthropic", "openai", ""],
            openrouter_model_fallbacks=[" model-a ", "model-b", "model-a"],
        )
        assert s.openrouter_provider_order == ["openai", "anthropic"]
        assert s.openrouter_model_fallbacks == ["model-a", "model-b"]


# =============================================================================
# log_format
# =============================================================================


class TestLogFormat:
    def test_default_valid(self):
        s = _make_settings()
        assert s.log_format in ("json", "text")

    def test_json_accepted(self):
        s = _make_settings(log_format="json")
        assert s.log_format == "json"

    def test_text_accepted(self):
        s = _make_settings(log_format="text")
        assert s.log_format == "text"

    def test_case_insensitive(self):
        s = _make_settings(log_format="JSON")
        assert s.log_format == "json"

    def test_invalid_rejected(self):
        with pytest.raises(ValidationError, match="log_format"):
            _make_settings(log_format="xml")


# =============================================================================
# embedding_dimensions
# =============================================================================


class TestEmbeddingDimensions:
    def test_default_valid(self):
        s = _make_settings()
        assert s.embedding_dimensions == 768

    def test_boundary_128_accepted(self):
        s = _make_settings(embedding_dimensions=128)
        assert s.embedding_dimensions == 128

    def test_boundary_4096_accepted(self):
        s = _make_settings(embedding_dimensions=4096)
        assert s.embedding_dimensions == 4096

    def test_too_small_rejected(self):
        with pytest.raises(ValidationError, match="embedding_dimensions"):
            _make_settings(embedding_dimensions=64)

    def test_too_large_rejected(self):
        with pytest.raises(ValidationError, match="embedding_dimensions"):
            _make_settings(embedding_dimensions=8192)


# =============================================================================
# cache_max_response_entries
# =============================================================================


class TestCacheMaxResponseEntries:
    def test_default_valid(self):
        s = _make_settings()
        assert s.cache_max_response_entries == 10000

    def test_boundary_100_accepted(self):
        s = _make_settings(cache_max_response_entries=100)
        assert s.cache_max_response_entries == 100

    def test_too_small_rejected(self):
        with pytest.raises(ValidationError, match="cache_max_response_entries"):
            _make_settings(cache_max_response_entries=50)

    def test_too_large_rejected(self):
        with pytest.raises(ValidationError, match="cache_max_response_entries"):
            _make_settings(cache_max_response_entries=2_000_000)


# =============================================================================
# batch sizes
# =============================================================================


class TestBatchSizes:
    @pytest.mark.parametrize("field", [
        "contextual_rag_batch_size",
        "entity_extraction_batch_size",
    ])
    def test_default_valid(self, field):
        s = _make_settings()
        val = getattr(s, field)
        assert 1 <= val <= 50

    @pytest.mark.parametrize("field", [
        "contextual_rag_batch_size",
        "entity_extraction_batch_size",
    ])
    def test_zero_rejected(self, field):
        with pytest.raises(ValidationError, match="batch_size"):
            _make_settings(**{field: 0})

    @pytest.mark.parametrize("field", [
        "contextual_rag_batch_size",
        "entity_extraction_batch_size",
    ])
    def test_over_50_rejected(self, field):
        with pytest.raises(ValidationError, match="batch_size"):
            _make_settings(**{field: 51})


# =============================================================================
# rag_max_iterations
# =============================================================================


class TestRagMaxIterations:
    def test_default_valid(self):
        s = _make_settings()
        assert s.rag_max_iterations == 2

    def test_boundary_1_accepted(self):
        s = _make_settings(rag_max_iterations=1)
        assert s.rag_max_iterations == 1

    def test_boundary_10_accepted(self):
        s = _make_settings(rag_max_iterations=10)
        assert s.rag_max_iterations == 10

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="rag_max_iterations"):
            _make_settings(rag_max_iterations=0)

    def test_over_10_rejected(self):
        with pytest.raises(ValidationError, match="rag_max_iterations"):
            _make_settings(rag_max_iterations=11)


# =============================================================================
# rag_confidence thresholds (0-1 via similarity validator)
# =============================================================================


class TestRagConfidenceThresholds:
    @pytest.mark.parametrize("field", ["rag_confidence_high", "rag_confidence_medium"])
    def test_default_valid(self, field):
        s = _make_settings()
        val = getattr(s, field)
        assert 0.0 <= val <= 1.0

    @pytest.mark.parametrize("field", ["rag_confidence_high", "rag_confidence_medium"])
    def test_over_1_rejected(self, field):
        with pytest.raises(ValidationError, match="Similarity threshold"):
            _make_settings(**{field: 1.5})

    @pytest.mark.parametrize("field", ["rag_confidence_high", "rag_confidence_medium"])
    def test_negative_rejected(self, field):
        with pytest.raises(ValidationError, match="Similarity threshold"):
            _make_settings(**{field: -0.1})


# =============================================================================
# grading thresholds (0-10 scale)
# =============================================================================


class TestGradingThresholds:
    @pytest.mark.parametrize("field", [
        "multi_agent_grading_threshold",
        "retrieval_grade_threshold",
    ])
    def test_default_valid(self, field):
        s = _make_settings()
        val = getattr(s, field)
        assert 0.0 <= val <= 10.0

    @pytest.mark.parametrize("field", [
        "multi_agent_grading_threshold",
        "retrieval_grade_threshold",
    ])
    def test_boundary_0_accepted(self, field):
        s = _make_settings(**{field: 0.0})
        assert getattr(s, field) == 0.0

    @pytest.mark.parametrize("field", [
        "multi_agent_grading_threshold",
        "retrieval_grade_threshold",
    ])
    def test_boundary_10_accepted(self, field):
        s = _make_settings(**{field: 10.0})
        assert getattr(s, field) == 10.0

    @pytest.mark.parametrize("field", [
        "multi_agent_grading_threshold",
        "retrieval_grade_threshold",
    ])
    def test_over_10_rejected(self, field):
        with pytest.raises(ValidationError, match="Grading threshold"):
            _make_settings(**{field: 10.1})

    @pytest.mark.parametrize("field", [
        "multi_agent_grading_threshold",
        "retrieval_grade_threshold",
    ])
    def test_negative_rejected(self, field):
        with pytest.raises(ValidationError, match="Grading threshold"):
            _make_settings(**{field: -0.1})
