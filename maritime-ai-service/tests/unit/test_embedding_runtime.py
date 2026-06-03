from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.error import URLError

import pytest


class TestEmbeddingCatalogHelpers:
    def test_infer_embedding_provider_from_known_models(self):
        from app.engine.model_catalog import get_embedding_provider

        assert get_embedding_provider("models/gemini-embedding-001") == "google"
        assert get_embedding_provider("text-embedding-3-small") == "openai"
        assert get_embedding_provider("embeddinggemma") == "ollama"

    def test_zhipu_has_no_default_embedding_model_until_cataloged(self):
        from app.engine.model_catalog import get_default_embedding_model_for_provider

        assert get_default_embedding_model_for_provider("zhipu") is None

    def test_sanitize_error_for_log_redacts_api_key_shapes(self):
        from app.engine.embedding_runtime import _sanitize_error_for_log

        sanitized = _sanitize_error_for_log(
            "Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-proj-abc123XYZ'}}"
        )

        assert "sk-proj-abc123XYZ" not in sanitized
        assert "[REDACTED]" in sanitized or "sk-REDACTED" in sanitized

    def test_provider_can_serve_embedding_model_requires_same_space(self):
        from app.engine.model_catalog import provider_can_serve_embedding_model

        assert provider_can_serve_embedding_model("ollama", "embeddinggemma") is True
        assert provider_can_serve_embedding_model("openrouter", "text-embedding-3-small") is True
        assert provider_can_serve_embedding_model("openai", "embeddinggemma") is False
        assert provider_can_serve_embedding_model("google", "text-embedding-3-small") is False


class TestOpenAICompatibleEmbeddings:
    @patch("openai.OpenAI")
    def test_openai_embeddings_request_dimensions_when_supported(self, mock_openai_cls):
        from app.engine.embedding_runtime import OpenAICompatibleEmbeddings

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[3.0, 4.0, 0.0])]
        )
        mock_openai_cls.return_value = mock_client

        embeddings = OpenAICompatibleEmbeddings(
            provider="openai",
            api_key="test-key",
            model_name="text-embedding-3-small",
            dimensions=3,
        )

        result = embeddings.embed_query("hello")

        assert len(result) == 3
        assert mock_client.embeddings.create.call_args.kwargs["dimensions"] == 3


class TestSemanticEmbeddingBackend:
    @pytest.fixture(autouse=True)
    def _reset_ollama_probe_cache(self):
        """Clear the module-level probe cache before each test.

        The cache is keyed by ``(base_url, model_name)``. When CI runs other
        tests that exercise ``probe_ollama_embedding_model`` against a real
        unreachable Ollama, the cache stores ``available=False`` for the
        common ``localhost:11434 / embeddinggemma`` key. Subsequent tests in
        this class then short-circuit to the cached miss BEFORE reaching the
        ``urlopen`` mock, producing the long-running flake on CI Unit Tests.
        Resetting the cache per test makes the mock authoritative.
        """
        from app.engine import embedding_runtime as mod

        mod._ollama_embedding_probe_cache.clear()
        yield
        mod._ollama_embedding_probe_cache.clear()

    def test_build_embedding_backend_for_provider_model_refuses_cross_space_pair(self):
        from app.engine import embedding_runtime as mod

        backend = mod.build_embedding_backend_for_provider_model(
            "openai",
            "embeddinggemma",
            dimensions=768,
        )

        assert backend is None

    def test_auto_mode_promotes_first_available_same_space_provider(self):
        from app.engine import embedding_runtime as mod

        backend = MagicMock()
        backend.provider = "openai"
        backend.model_name = "text-embedding-3-small"
        backend.dimensions = 768

        patched_settings = SimpleNamespace(
            embedding_provider="auto",
            embedding_failover_chain=["google", "openai"],
            embedding_model="text-embedding-3-small",
            embedding_dimensions=768,
        )

        with patch.object(mod, "settings", patched_settings), patch.object(
            mod.SemanticEmbeddingBackend,
            "_build_backend",
            side_effect=lambda provider: None if provider == "google" else backend,
        ):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.provider == "openai"
        assert runtime.model_name == "text-embedding-3-small"

    def test_auto_mode_refuses_cross_space_provider_promotion(self):
        from app.engine import embedding_runtime as mod

        patched_settings = SimpleNamespace(
            embedding_provider="auto",
            embedding_failover_chain=["google", "openai"],
            embedding_model="embeddinggemma",
            embedding_dimensions=768,
            google_api_key="google-key",
            openai_api_key="openai-key",
            openai_base_url="https://api.openai.com/v1",
        )

        with patch.object(mod, "settings", patched_settings), patch.object(
            mod,
            "probe_ollama_embedding_model",
            return_value=SimpleNamespace(
                available=False,
                reason_code="host_down",
                reason_label="Ollama down",
                resolved_base_url=None,
            ),
        ):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.is_available() is False
        assert runtime.provider is None

    def test_zhipu_embedding_provider_fails_closed_without_verified_model(self):
        from app.engine import embedding_runtime as mod

        patched_settings = SimpleNamespace(
            embedding_provider="zhipu",
            embedding_failover_chain=["zhipu"],
            embedding_model=None,
            embedding_dimensions=768,
            zhipu_api_key="live-key",
        )

        with patch.object(mod, "settings", patched_settings):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.is_available() is False
        assert runtime.provider is None

    def test_openrouter_embedding_provider_fails_closed_without_openrouter_base_url_signal(self):
        from app.engine import embedding_runtime as mod

        patched_settings = SimpleNamespace(
            embedding_provider="openrouter",
            embedding_failover_chain=["openrouter"],
            embedding_model="text-embedding-3-small",
            embedding_dimensions=768,
            openai_api_key="openai-key",
            openai_base_url="https://api.openai.com/v1",
        )

        with patch.object(mod, "settings", patched_settings):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.is_available() is False
        assert runtime.provider is None

    def test_openrouter_embedding_provider_builds_when_openrouter_base_url_is_explicit(self):
        from app.engine import embedding_runtime as mod

        patched_settings = SimpleNamespace(
            embedding_provider="openrouter",
            embedding_failover_chain=["openrouter"],
            embedding_model="text-embedding-3-small",
            embedding_dimensions=768,
            openai_api_key="openrouter-key",
            openai_base_url="https://openrouter.ai/api/v1",
        )

        with patch.object(mod, "settings", patched_settings):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.is_available() is True
        assert runtime.provider == "openrouter"
        assert runtime.model_name == "text-embedding-3-small"

    def test_ollama_embedding_provider_fails_closed_when_model_not_installed(self):
        from app.engine import embedding_runtime as mod

        patched_settings = SimpleNamespace(
            embedding_provider="ollama",
            embedding_failover_chain=["ollama"],
            embedding_model="embeddinggemma",
            embedding_dimensions=768,
            ollama_base_url="http://localhost:11434",
        )

        with patch.object(mod, "settings", patched_settings), patch.object(
            mod,
            "probe_ollama_embedding_model",
            return_value=SimpleNamespace(
                available=False,
                reason_code="model_missing",
                reason_label="Model embedding local chua duoc cai tren Ollama.",
                resolved_base_url="http://localhost:11434",
            ),
        ):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.is_available() is False
        assert runtime.provider is None

    def test_ollama_embedding_provider_builds_when_model_is_installed(self):
        from app.engine import embedding_runtime as mod

        patched_settings = SimpleNamespace(
            embedding_provider="ollama",
            embedding_failover_chain=["ollama"],
            embedding_model="embeddinggemma",
            embedding_dimensions=768,
            ollama_base_url="http://localhost:11434",
            ollama_api_key=None,
        )

        with patch.object(mod, "settings", patched_settings), patch.object(
            mod,
            "probe_ollama_embedding_model",
            return_value=SimpleNamespace(
                available=True,
                reason_code=None,
                reason_label=None,
                resolved_base_url="http://localhost:11434",
            ),
        ):
            runtime = mod.SemanticEmbeddingBackend()

        assert runtime.is_available() is True
        assert runtime.provider == "ollama"
        assert runtime.model_name == "embeddinggemma"

    def test_probe_ollama_embedding_model_falls_back_to_localhost_candidate(self):
        from app.engine import embedding_runtime as mod

        host_down = URLError("timed out")
        localhost_payload = {
            "models": [
                {"name": "embeddinggemma"},
            ]
        }

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                import json as _json

                return _json.dumps(self._payload).encode("utf-8")

        def _fake_urlopen(request, timeout):
            url = request.full_url
            if "host.docker.internal" in url:
                raise host_down
            return _Response(localhost_payload)

        with patch.object(mod, "urlopen", side_effect=_fake_urlopen):
            result = mod.probe_ollama_embedding_model(
                "http://host.docker.internal:11434",
                "embeddinggemma",
            )

        assert result.available is True
        assert result.resolved_base_url == "http://localhost:11434"

    def test_probe_ollama_embedding_model_accepts_latest_tag_variant(self):
        from app.engine import embedding_runtime as mod

        payload = {
            "models": [
                {"name": "embeddinggemma:latest"},
            ]
        }

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                import json as _json

                return _json.dumps(self._payload).encode("utf-8")

        with patch.object(mod, "urlopen", return_value=_Response(payload)) as mock_urlopen:
            result = mod.probe_ollama_embedding_model(
                "http://localhost:11434",
                "embeddinggemma",
            )

        # If the cache short-circuited the call, urlopen would never run —
        # asserting ``called`` is the canary for cache pollution regressions.
        assert mock_urlopen.called, "urlopen was bypassed by the probe cache — fixture must clear it before each test"
        assert result.available is True

    def test_probe_ollama_embedding_model_uses_short_cache(self):
        from app.engine import embedding_runtime as mod

        payload = {
            "models": [
                {"name": "embeddinggemma"},
            ]
        }

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                import json as _json

                return _json.dumps(self._payload).encode("utf-8")

        mod.reset_ollama_embedding_probe_cache()
        with patch.object(mod, "urlopen", return_value=_Response(payload)) as mock_urlopen:
            first = mod.probe_ollama_embedding_model(
                "http://localhost:11434",
                "embeddinggemma",
            )
            second = mod.probe_ollama_embedding_model(
                "http://localhost:11434",
                "embeddinggemma",
            )

        assert first.available is True
        assert second.available is True
        assert mock_urlopen.call_count == 1


@pytest.mark.asyncio
async def test_input_processor_semantic_fact_retrieval_uses_embedding_generator():
    from app.services.input_processor_context_runtime import _populate_semantic_memory_context

    context = SimpleNamespace(user_facts=None, semantic_context="")
    semantic_memory = MagicMock()
    semantic_memory.retrieve_insights_prioritized = AsyncMock(return_value=[])
    semantic_context = MagicMock()
    semantic_context.to_prompt_context.return_value = ""
    semantic_memory.retrieve_context = AsyncMock(return_value=semantic_context)
    semantic_memory.search_relevant_facts.return_value = []

    generator = MagicMock()
    generator.agenerate = AsyncMock(return_value=[0.1, 0.2, 0.3])

    settings_obj = SimpleNamespace(
        enable_semantic_fact_retrieval=True,
        fact_min_similarity=0.3,
        max_injected_facts=5,
    )
    logger_obj = MagicMock()

    with patch(
        "app.engine.semantic_memory.embeddings.get_embedding_generator",
        return_value=generator,
    ):
        await _populate_semantic_memory_context(
            semantic_memory=semantic_memory,
            context=context,
            user_id="user-1",
            message="mình tên Nam",
            settings_obj=settings_obj,
            logger_obj=logger_obj,
        )

    generator.agenerate.assert_awaited_once_with("mình tên Nam")
    semantic_memory.search_relevant_facts.assert_called_once()


@pytest.mark.asyncio
async def test_input_processor_blocks_semantic_memory_without_org_context(
    monkeypatch,
):
    from app.core.config import settings
    from app.core.org_context import current_org_id
    from app.services.input_processor_context_runtime import (
        _populate_semantic_memory_context,
    )

    context = SimpleNamespace(
        user_facts=["PRIVATE FACT"],
        semantic_context="",
        memory_warnings=[],
    )
    semantic_memory = MagicMock()
    semantic_memory.retrieve_insights_prioritized = AsyncMock(return_value=[])
    semantic_memory.retrieve_context = AsyncMock()
    semantic_memory.search_relevant_facts = MagicMock()
    settings_obj = SimpleNamespace(
        enable_semantic_fact_retrieval=True,
        fact_min_similarity=0.3,
        max_injected_facts=5,
    )

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    token = current_org_id.set(None)
    try:
        await _populate_semantic_memory_context(
            semantic_memory=semantic_memory,
            context=context,
            user_id="user-private-123",
            message="PRIVATE MESSAGE",
            settings_obj=settings_obj,
            logger_obj=MagicMock(),
        )
    finally:
        current_org_id.reset(token)

    assert context.user_facts == []
    assert context.semantic_context == ""
    assert context.memory_warnings == [
        "semantic_memory_read_blocked_missing_org_context"
    ]
    semantic_memory.retrieve_insights_prioritized.assert_not_called()
    semantic_memory.retrieve_context.assert_not_called()
    semantic_memory.search_relevant_facts.assert_not_called()


@pytest.mark.asyncio
async def test_input_processor_records_typed_memory_retrieval_summary():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.models.semantic_memory import MemoryType
    from app.services.input_processor_context_runtime import (
        _populate_semantic_memory_context,
    )

    context = SimpleNamespace(
        user_facts=[],
        semantic_context="",
        memory_warnings=[],
        memory_retrieval_summary={},
    )
    insight = SimpleNamespace(
        category=SimpleNamespace(value="learning_style"),
        content="PRIVATE INSIGHT CONTENT",
    )
    memory = SimpleNamespace(
        memory_type=MemoryType.MESSAGE,
        content="PRIVATE MEMORY CONTENT",
    )
    semantic_context = SimpleNamespace(
        relevant_memories=[memory],
        to_prompt_context=MagicMock(return_value="PRIVATE PROMPT CONTEXT"),
    )
    fact = SimpleNamespace(
        id="fact-1",
        metadata={"fact_type": "goal", "confidence": 0.9, "access_count": 2},
        content="goal: PRIVATE FACT CONTENT",
        importance=0.8,
        created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    semantic_memory = MagicMock()
    semantic_memory.retrieve_insights_prioritized = AsyncMock(return_value=[insight])
    semantic_memory.retrieve_context = AsyncMock(return_value=semantic_context)
    semantic_memory.search_relevant_facts.return_value = [fact]

    generator = MagicMock()
    generator.agenerate = AsyncMock(return_value=[0.1, 0.2, 0.3])
    settings_obj = SimpleNamespace(
        enable_semantic_fact_retrieval=True,
        fact_min_similarity=0.3,
        max_injected_facts=5,
        similarity_threshold=0.7,
    )

    with patch(
        "app.engine.semantic_memory.embeddings.get_embedding_generator",
        return_value=generator,
    ):
        await _populate_semantic_memory_context(
            semantic_memory=semantic_memory,
            context=context,
            user_id="user-1",
            message="mÃ¬nh muá»‘n há»c SOLAS",
            settings_obj=settings_obj,
            logger_obj=MagicMock(),
        )

    summary = context.memory_retrieval_summary
    assert summary["status"] == "ready"
    assert summary["relevant_memory_count"] == 1
    assert summary["insight_count"] == 1
    assert summary["user_fact_count"] == 1
    assert summary["semantic_memory_count"] == 3
    assert summary["memory_type_names"] == ["message"]
    assert summary["fact_type_names"] == ["goal"]
    assert summary["insight_category_names"] == ["learning_style"]
    assert summary["warning_codes"] == []
    assert "PRIVATE" not in str(summary)


@pytest.mark.asyncio
async def test_input_processor_records_typed_episodic_retrieval_summary():
    from app.engine.runtime.episodic_retrieval import EpisodicMatch
    from app.services.input_processor import ChatContext
    from app.services.input_processor_context_runtime import build_context_impl

    request = SimpleNamespace(
        user_id="user-episode",
        message="SOLAS",
        role="student",
        user_context=None,
        organization_id="org-A",
    )
    settings_obj = SimpleNamespace(
        enable_cross_platform_memory=False,
        enable_visual_memory=False,
        enable_episodic_retrieval=True,
        enable_vision=False,
        enable_emotional_state=False,
    )
    core_block = SimpleNamespace(
        get_block=AsyncMock(return_value="CORE PROFILE"),
    )
    matches = [
        EpisodicMatch(
            session_id="prior-session",
            seq=7,
            event_type="user_message",
            text="PRIVATE PRIOR TURN ABOUT SOLAS",
            created_at="2026-05-31T00:00:00Z",
            score=0.6,
        )
    ]

    with patch(
        "app.engine.semantic_memory.core_memory_block.get_core_memory_block",
        return_value=core_block,
    ), patch(
        "app.engine.runtime.episodic_retrieval.search_prior_user_turns",
        new=AsyncMock(return_value=matches),
    ) as search_mock, patch(
        "app.services.input_processor_context_runtime._apply_budgeted_history",
        new=AsyncMock(return_value=None),
    ):
        context = await build_context_impl(
            request=request,
            session_id="current-session",
            user_name=None,
            recent_history_fallback=None,
            chat_context_cls=ChatContext,
            semantic_memory=None,
            chat_history=None,
            learning_graph=None,
            memory_summarizer=None,
            conversation_analyzer=None,
            settings_obj=settings_obj,
            logger_obj=MagicMock(),
        )

    summary = context.episodic_retrieval_summary
    assert summary["schema_version"] == "wiii.episodic_retrieval.v1"
    assert summary["status"] == "ready"
    assert summary["match_count"] == 1
    assert summary["event_types"] == ["user_message"]
    assert summary["max_score"] == 0.6
    assert summary["min_score"] == 0.6
    assert summary["current_session_excluded"] is True
    assert summary["org_scoped"] is True
    assert summary["raw_content_included"] is False
    assert summary["warning_codes"] == []
    assert "PRIVATE" not in str(summary)
    assert "PRIVATE PRIOR TURN ABOUT SOLAS" in context.core_memory_block
    search_mock.assert_awaited_once()
    assert search_mock.call_args.kwargs["org_id"] == "org-A"


def test_semantic_memory_engine_search_relevant_facts_facade_delegates_to_repository():
    from app.engine.semantic_memory.core import SemanticMemoryEngine

    engine = SemanticMemoryEngine.__new__(SemanticMemoryEngine)
    engine._repository = MagicMock()
    engine._repository.search_relevant_facts.return_value = ["fact"]

    assert engine.search_relevant_facts(
        user_id="user-1",
        query_embedding=[0.1, 0.2],
        limit=3,
        min_similarity=0.4,
    ) == ["fact"]
    engine._repository.search_relevant_facts.assert_called_once_with(
        user_id="user-1",
        query_embedding=[0.1, 0.2],
        limit=3,
        min_similarity=0.4,
    )
