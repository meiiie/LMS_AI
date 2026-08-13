from app.engine.llm_runtime_profiles import (
    get_runtime_provider_preset,
    is_known_default_provider_chain,
    should_apply_openrouter_defaults,
)


def test_known_default_provider_chains_include_current_presets():
    assert is_known_default_provider_chain(["ollama", "google", "openrouter"])
    assert is_known_default_provider_chain(["openrouter", "ollama", "google"])
    assert is_known_default_provider_chain(["google", "openai", "ollama"])


def test_unknown_provider_chain_is_not_treated_as_default():
    assert not is_known_default_provider_chain(["openrouter", "google"])


def test_openrouter_defaults_apply_to_legacy_paid_models():
    assert should_apply_openrouter_defaults("gpt-4o-mini")
    assert should_apply_openrouter_defaults("openai/gpt-4o")


def test_openrouter_defaults_do_not_override_new_models():
    assert not should_apply_openrouter_defaults("openrouter/auto")


def test_get_runtime_provider_preset_for_openrouter():
    preset = get_runtime_provider_preset("openrouter")
    assert preset.provider == "openrouter"
    assert preset.failover_chain == ("openrouter", "google", "zhipu", "ollama")


def test_get_runtime_provider_preset_for_google_exposes_advanced_model():
    preset = get_runtime_provider_preset("google")
    assert preset.provider == "google"
    assert preset.google_model == "gemini-3.1-flash-lite-preview"
    assert preset.google_model_advanced == "gemini-3.1-pro-preview"


def test_get_runtime_provider_preset_for_nvidia_uses_nemotron_design_default():
    preset = get_runtime_provider_preset("nvidia")
    assert preset.provider == "nvidia"
    assert preset.failover_chain == ("nvidia",)
    assert preset.nvidia_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert preset.nvidia_model_advanced == "nvidia/nemotron-3-ultra-550b-a55b"


def test_get_runtime_provider_preset_for_ollama_matches_verified_local_default():
    preset = get_runtime_provider_preset("ollama")
    assert preset.provider == "ollama"
    assert preset.ollama_base_url == "http://host.docker.internal:11434"
    assert preset.ollama_model == "qwen3:4b-instruct-2507-q4_K_M"
    assert preset.ollama_keep_alive == "30m"
