from types import SimpleNamespace
from unittest.mock import patch


def test_embedding_selectability_snapshot_reports_ollama_model_missing():
    from app.services import embedding_selectability_service as mod

    patched_settings = SimpleNamespace(
        embedding_provider="auto",
        embedding_failover_chain=["ollama", "google"],
        embedding_model="embeddinggemma",
        embedding_dimensions=768,
        google_api_key="google-key",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        ollama_base_url="http://localhost:11434",
        zhipu_api_key="zhipu-key",
    )

    with patch.object(mod, "settings", patched_settings), patch(
        "app.engine.embedding_runtime.settings",
        patched_settings,
    ), patch(
        "app.services.embedding_selectability_service.peek_semantic_embedding_backend",
        return_value=None,
    ), patch(
        "app.services.embedding_selectability_service.probe_ollama_embedding_model",
        return_value=SimpleNamespace(
            available=False,
            reason_code="model_missing",
            reason_label="Model embedding local chua duoc cai tren Ollama.",
        ),
    ):
        mod.invalidate_embedding_selectability_cache()
        snapshot = mod.get_embedding_selectability_snapshot(force_refresh=True)

    ollama = next(item for item in snapshot if item.provider == "ollama")
    google = next(item for item in snapshot if item.provider == "google")
    zhipu = next(item for item in snapshot if item.provider == "zhipu")

    assert ollama.available is False
    assert ollama.reason_code == "model_missing"
    assert google.reason_code == "space_mismatch"
    assert zhipu.reason_code == "space_mismatch"


def test_embedding_selectability_snapshot_blocks_openrouter_without_explicit_openrouter_base_url():
    from app.services import embedding_selectability_service as mod

    patched_settings = SimpleNamespace(
        embedding_provider="auto",
        embedding_failover_chain=["google", "openrouter"],
        embedding_model="models/gemini-embedding-001",
        embedding_dimensions=768,
        google_api_key="google-key",
        openai_api_key="openai-key",
        openai_base_url="https://api.openai.com/v1",
        ollama_base_url="http://localhost:11434",
        zhipu_api_key=None,
    )

    active_backend = SimpleNamespace(provider="google")

    with patch.object(mod, "settings", patched_settings), patch(
        "app.engine.embedding_runtime.settings",
        patched_settings,
    ), patch(
        "app.services.embedding_selectability_service.peek_semantic_embedding_backend",
        return_value=active_backend,
    ), patch(
        "app.services.embedding_selectability_service.probe_ollama_embedding_model",
        return_value=SimpleNamespace(
            available=False,
            reason_code="model_missing",
            reason_label="Model embedding local chua duoc cai tren Ollama.",
        ),
    ):
        mod.invalidate_embedding_selectability_cache()
        snapshot = mod.get_embedding_selectability_snapshot(force_refresh=True)

    openrouter = next(item for item in snapshot if item.provider == "openrouter")
    assert openrouter.available is False
    assert openrouter.reason_code == "missing_api_key"


def test_embedding_selectability_snapshot_reports_dimension_mismatch():
    from app.services import embedding_selectability_service as mod

    patched_settings = SimpleNamespace(
        embedding_provider="ollama",
        embedding_failover_chain=["ollama"],
        embedding_model="embeddinggemma",
        embedding_dimensions=1536,
        google_api_key=None,
        openai_api_key=None,
        ollama_base_url="http://localhost:11434",
        zhipu_api_key=None,
    )

    with patch.object(mod, "settings", patched_settings), patch(
        "app.engine.embedding_runtime.settings",
        patched_settings,
    ), patch(
        "app.services.embedding_selectability_service.peek_semantic_embedding_backend",
        return_value=None,
    ):
        mod.invalidate_embedding_selectability_cache()
        snapshot = mod.get_embedding_selectability_snapshot(force_refresh=True)

    ollama = next(item for item in snapshot if item.provider == "ollama")
    assert ollama.available is False
    assert ollama.reason_code == "dimension_mismatch"


def test_embedding_selectability_snapshot_reports_space_mismatch_for_cross_family_provider():
    from app.services import embedding_selectability_service as mod

    patched_settings = SimpleNamespace(
        embedding_provider="auto",
        embedding_failover_chain=["ollama", "google"],
        embedding_model="embeddinggemma",
        embedding_dimensions=768,
        google_api_key="google-key",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        ollama_base_url="http://localhost:11434",
        zhipu_api_key=None,
    )

    active_backend = SimpleNamespace(provider="ollama")

    with patch.object(mod, "settings", patched_settings), patch(
        "app.engine.embedding_runtime.settings",
        patched_settings,
    ), patch(
        "app.services.embedding_selectability_service.peek_semantic_embedding_backend",
        return_value=active_backend,
    ), patch(
        "app.services.embedding_selectability_service.probe_ollama_embedding_model",
        return_value=SimpleNamespace(
            available=True,
            reason_code=None,
            reason_label=None,
            resolved_base_url="http://localhost:11434",
        ),
    ):
        mod.invalidate_embedding_selectability_cache()
        snapshot = mod.get_embedding_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    ollama = next(item for item in snapshot if item.provider == "ollama")

    assert ollama.available is True
    assert google.available is False
    assert google.reason_code == "space_mismatch"
