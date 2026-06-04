"""Tests for ModelCatalogService — multi-provider catalog with Ollama discovery."""
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.engine.model_catalog import (
    ChatModelMetadata,
    GOOGLE_DEFAULT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    get_all_static_chat_models,
    is_known_model,
    ModelCatalogService,
    resolve_openai_catalog_provider,
)


class TestStaticCatalogs:
    def test_google_models_present(self):
        cats = get_all_static_chat_models()
        assert "google" in cats
        assert GOOGLE_DEFAULT_MODEL in cats["google"]

    def test_openrouter_models_present(self):
        cats = get_all_static_chat_models()
        assert "openrouter" in cats
        assert "openai/gpt-oss-20b:free" in cats["openrouter"]

    def test_openai_models_present(self):
        cats = get_all_static_chat_models()
        assert "openai" in cats
        assert "gpt-5.4" in cats["openai"]

    def test_ollama_models_present(self):
        cats = get_all_static_chat_models()
        assert "ollama" in cats
        assert len(cats["ollama"]) >= 1

    def test_all_entries_are_chat_model_metadata(self):
        for provider, models in get_all_static_chat_models().items():
            for name, meta in models.items():
                assert isinstance(meta, ChatModelMetadata)
                assert meta.provider == provider or provider in ("openrouter",)


class TestIsKnownModel:
    def test_known_google_current(self):
        assert is_known_model("google", GOOGLE_DEFAULT_MODEL) is True

    def test_known_google_legacy(self):
        assert is_known_model("google", "gemini-2.5-flash") is True

    def test_unknown_google(self):
        assert is_known_model("google", "gemini-99-turbo") is False

    def test_known_openrouter(self):
        assert is_known_model("openrouter", "openai/gpt-oss-20b:free") is True

    def test_known_openai(self):
        assert is_known_model("openai", "gpt-5.4-mini") is True

    def test_unknown_provider(self):
        assert is_known_model("azure", "gpt-4") is False

    def test_empty_model_name(self):
        assert is_known_model("google", "") is False


class TestOllamaDiscovery:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        ModelCatalogService.reset_cache()
        yield
        ModelCatalogService.reset_cache()

    @pytest.mark.asyncio
    async def test_discover_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:latest", "size": 4000000000},
                {"name": "mistral:7b", "size": 7000000000},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            models = await ModelCatalogService.discover_ollama_models("http://localhost:11434")

        assert len(models) == 2
        assert models[0].model_name == "llama3:latest"
        assert models[0].provider == "ollama"
        assert models[0].status == "available"
        assert models[1].model_name == "mistral:7b"

    @pytest.mark.asyncio
    async def test_discover_timeout(self):
        import httpx
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            models = await ModelCatalogService.discover_ollama_models("http://localhost:11434")

        assert models == []  # graceful degradation

    @pytest.mark.asyncio
    async def test_discover_cached(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "test:latest"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            models1 = await ModelCatalogService.discover_ollama_models("http://localhost:11434")
            models2 = await ModelCatalogService.discover_ollama_models("http://localhost:11434")

        assert len(models1) == 1
        assert len(models2) == 1
        # Only 1 HTTP call (cached)
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_discover_cache_expired(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "test:latest"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await ModelCatalogService.discover_ollama_models("http://localhost:11434")
            # Expire cache
            ModelCatalogService._ollama_cache_ts = time.time() - 120
            await ModelCatalogService.discover_ollama_models("http://localhost:11434")

        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_discover_strips_trailing_api(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await ModelCatalogService.discover_ollama_models("http://localhost:11434/api")

        called_url = mock_client.get.call_args[0][0]
        assert called_url == "http://localhost:11434/api/tags"


class TestProviderCatalogResolution:
    def test_resolve_openai_catalog_provider_to_openrouter_from_base_url(self):
        assert resolve_openai_catalog_provider(
            active_provider="google",
            openai_base_url="https://openrouter.ai/api/v1",
        ) == "openrouter"

    def test_resolve_openai_catalog_provider_to_openrouter_from_active_provider(self):
        assert resolve_openai_catalog_provider(
            active_provider="openrouter",
            openai_base_url="",
        ) == "openrouter"

    def test_resolve_openai_catalog_provider_to_openai(self):
        assert resolve_openai_catalog_provider(
            active_provider="openai",
            openai_base_url=None,
        ) == "openai"


class TestRuntimeDiscovery:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        ModelCatalogService.reset_cache()
        yield
        ModelCatalogService.reset_cache()

    @pytest.mark.asyncio
    async def test_discover_google_models_filters_to_gemini_generation_models(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "models/gemini-3.1-flash-lite-preview",
                    "displayName": "Gemini 3.1 Flash-Lite Preview",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/text-embedding-004",
                    "displayName": "Text Embedding 004",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            models = await ModelCatalogService.discover_google_models("google-key")

        assert [model.model_name for model in models] == [GOOGLE_DEFAULT_MODEL]

    @pytest.mark.asyncio
    async def test_discover_openai_compatible_models_filters_non_chat_models(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-5.4-mini"},
                {"id": "text-embedding-3-large"},
                {"id": "gpt-5.4"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            models = await ModelCatalogService.discover_openai_compatible_models(
                provider="openai",
                base_url="https://api.openai.com/v1",
                api_key="openai-key",
            )

        assert [model.model_name for model in models] == ["gpt-5.4-mini", "gpt-5.4"]


class TestGetFullCatalog:
    @pytest.fixture(autouse=True)
    def reset_cache(self):
        ModelCatalogService.reset_cache()
        yield
        ModelCatalogService.reset_cache()

    @pytest.mark.asyncio
    async def test_without_ollama(self):
        catalog = await ModelCatalogService.get_full_catalog(ollama_base_url=None)
        assert "providers" in catalog
        assert "google" in catalog["providers"]
        assert "openai" in catalog["providers"]
        assert "openrouter" in catalog["providers"]
        assert catalog["ollama_discovered"] is False
        assert "provider_metadata" in catalog
        assert "timestamp" in catalog

    @pytest.mark.asyncio
    async def test_with_ollama(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "phi3:latest"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            catalog = await ModelCatalogService.get_full_catalog(
                ollama_base_url="http://localhost:11434"
            )

        assert catalog["ollama_discovered"] is True
        assert "phi3:latest" in catalog["providers"]["ollama"]

    @pytest.mark.asyncio
    async def test_openrouter_runtime_discovery_metadata_is_exposed(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "openai/gpt-oss-20b:free"},
                {"id": "anthropic/claude-sonnet-4"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            catalog = await ModelCatalogService.get_full_catalog(
                openai_api_key="openrouter-key",
                openai_base_url="https://openrouter.ai/api/v1",
                active_provider="openrouter",
            )

        assert "anthropic/claude-sonnet-4" in catalog["providers"]["openrouter"]
        assert catalog["provider_metadata"]["openrouter"]["runtime_discovery_enabled"] is True
        assert catalog["provider_metadata"]["openrouter"]["runtime_discovery_succeeded"] is True
        assert catalog["provider_metadata"]["openrouter"]["catalog_source"] == "mixed"

    @pytest.mark.asyncio
    async def test_nvidia_runtime_discovery_metadata_is_exposed(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "qwen/qwen3-next-80b-a3b-instruct"},
                {"id": "nvidia/nemotron-3-ultra"},
                {"id": "nvidia/embedding-model"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            catalog = await ModelCatalogService.get_full_catalog(
                nvidia_api_key="nvapi-test-key",
                nvidia_base_url="https://integrate.api.nvidia.com/v1",
            )

        assert "nvidia/nemotron-3-ultra" in catalog["providers"]["nvidia"]
        assert "nvidia/embedding-model" not in catalog["providers"]["nvidia"]
        assert catalog["provider_metadata"]["nvidia"]["runtime_discovery_enabled"] is True
        assert catalog["provider_metadata"]["nvidia"]["runtime_discovery_succeeded"] is True
        assert catalog["provider_metadata"]["nvidia"]["catalog_source"] == "mixed"

    @pytest.mark.asyncio
    async def test_embedding_models_included(self):
        catalog = await ModelCatalogService.get_full_catalog()
        assert "embedding_models" in catalog
        assert DEFAULT_EMBEDDING_MODEL in catalog["embedding_models"]
