from app.engine.model_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_BENCHMARK_CANDIDATE,
    GOOGLE_DEFAULT_MODEL,
    NVIDIA_DEFAULT_MODEL,
    NVIDIA_DEFAULT_MODEL_ADVANCED,
    get_chat_model_metadata,
    get_current_google_chat_models,
    get_embedding_dimensions,
    get_embedding_model_metadata,
    get_provider_chat_model_metadata,
    is_legacy_google_model,
)
from app.engine.model_catalog_runtime_support import hash_secret, sanitize_exception_for_log


def test_google_default_model_is_current():
    metadata = get_chat_model_metadata(GOOGLE_DEFAULT_MODEL)

    assert metadata is not None
    assert metadata.model_name == GOOGLE_DEFAULT_MODEL
    assert metadata.status == "current"


def test_nvidia_defaults_are_qwen_models():
    default_metadata = get_provider_chat_model_metadata("nvidia", NVIDIA_DEFAULT_MODEL)
    advanced_metadata = get_provider_chat_model_metadata(
        "nvidia",
        NVIDIA_DEFAULT_MODEL_ADVANCED,
    )

    assert NVIDIA_DEFAULT_MODEL == "qwen/qwen3-next-80b-a3b-instruct"
    assert NVIDIA_DEFAULT_MODEL_ADVANCED == "qwen/qwen3-next-80b-a3b-thinking"
    assert default_metadata is not None
    assert default_metadata.status == "current"
    assert "Qwen" in default_metadata.display_name
    assert advanced_metadata is not None
    assert advanced_metadata.status == "current"
    assert "Qwen" in advanced_metadata.display_name


def test_legacy_google_model_is_marked_legacy():
    assert is_legacy_google_model("gemini-2.5-flash") is True


def test_current_google_chat_models_only_return_current_entries():
    current_models = get_current_google_chat_models()

    assert GOOGLE_DEFAULT_MODEL in current_models
    assert "gemini-2.5-flash" not in current_models


def test_embedding_models_expose_dimensions():
    default_metadata = get_embedding_model_metadata(DEFAULT_EMBEDDING_MODEL)
    candidate_metadata = get_embedding_model_metadata(EMBEDDING_BENCHMARK_CANDIDATE)

    assert default_metadata is not None
    assert default_metadata.dimensions == get_embedding_dimensions(DEFAULT_EMBEDDING_MODEL)
    assert candidate_metadata is not None
    assert candidate_metadata.dimensions == get_embedding_dimensions(
        EMBEDDING_BENCHMARK_CANDIDATE
    )


def test_runtime_secret_fingerprint_is_stable_and_redacted():
    first = hash_secret("provider-api-key-1")
    second = hash_secret("provider-api-key-1")
    other = hash_secret("provider-api-key-2")

    assert first == second
    assert first != other
    assert first != "provider-api-key-1"
    assert len(first) == 12
    assert hash_secret(None) == "no-secret"


def test_runtime_discovery_exception_log_sanitizes_provider_secrets():
    message = (
        "Client error for url "
        "'https://generativelanguage.googleapis.com/v1beta/models?key=AIza-secret-value' "
        "with Bearer eyJ.secret and nvapi-private-key"
    )

    sanitized = sanitize_exception_for_log(RuntimeError(message))

    assert "AIza-secret-value" not in sanitized
    assert "eyJ.secret" not in sanitized
    assert "nvapi-private-key" not in sanitized
    assert "key=REDACTED" in sanitized
    assert "Bearer REDACTED" in sanitized
    assert "SECRET-REDACTED" in sanitized
