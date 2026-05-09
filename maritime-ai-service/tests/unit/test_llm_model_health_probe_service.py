"""Tests for model-level LLM health probes."""

import asyncio
from types import SimpleNamespace

import pytest


def _settings(**overrides):
    defaults = {
        "enable_llm_model_health_probes": True,
        "nvidia_api_key": "test-key",
        "nvidia_base_url": "https://integrate.api.nvidia.com/v1",
        "nvidia_model": "deepseek-ai/deepseek-v4-flash",
        "nvidia_model_advanced": "qwen/qwen3-next-80b-a3b-instruct",
        "llm_model_health_probe_timeout_seconds": 1.0,
        "llm_model_health_degraded_ttl_seconds": 300.0,
        "llm_model_health_probe_interval_seconds": 0.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def reset_model_health():
    from app.engine.llm_model_health import reset_model_health_state

    reset_model_health_state()
    yield
    reset_model_health_state()


@pytest.mark.asyncio
async def test_nvidia_probe_marks_timeout_degraded_and_fallback_healthy():
    from app.engine.llm_model_health import get_model_health_snapshot, is_model_degraded
    from app.services.llm_model_health_probe_service import (
        run_nvidia_model_health_probe_once,
    )

    async def fake_post(_base_url, _api_key, model, _timeout_seconds):
        if model == "deepseek-ai/deepseek-v4-flash":
            raise asyncio.TimeoutError()

    results = await run_nvidia_model_health_probe_once(
        settings_obj=_settings(),
        post_chat_completion_fn=fake_post,
    )

    assert [item.state for item in results] == ["degraded", "healthy"]
    assert is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-flash")
    assert not is_model_degraded("nvidia", "qwen/qwen3-next-80b-a3b-instruct")
    snapshot = get_model_health_snapshot()["nvidia"]
    assert snapshot["deepseek-ai/deepseek-v4-flash"]["last_reason_code"] == "timeout"


@pytest.mark.asyncio
async def test_nvidia_probe_dedupes_identical_configured_models():
    from app.services.llm_model_health_probe_service import (
        run_nvidia_model_health_probe_once,
    )

    calls = []

    async def fake_post(_base_url, _api_key, model, _timeout_seconds):
        calls.append(model)

    results = await run_nvidia_model_health_probe_once(
        settings_obj=_settings(
            nvidia_model="qwen/qwen3-next-80b-a3b-instruct",
            nvidia_model_advanced="qwen/qwen3-next-80b-a3b-instruct",
        ),
        post_chat_completion_fn=fake_post,
    )

    assert calls == ["qwen/qwen3-next-80b-a3b-instruct"]
    assert len(results) == 1
    assert results[0].state == "healthy"


@pytest.mark.asyncio
async def test_nvidia_probe_skips_when_disabled_or_missing_credentials():
    from app.services.llm_model_health_probe_service import (
        run_nvidia_model_health_probe_once,
    )

    async def fail_if_called(*_args):
        raise AssertionError("probe should not call network")

    disabled = await run_nvidia_model_health_probe_once(
        settings_obj=_settings(enable_llm_model_health_probes=False),
        post_chat_completion_fn=fail_if_called,
    )
    missing_key = await run_nvidia_model_health_probe_once(
        settings_obj=_settings(nvidia_api_key=None),
        post_chat_completion_fn=fail_if_called,
    )

    assert disabled == []
    assert missing_key == []


def test_probe_failure_classification_is_stable():
    from app.services.llm_model_health_probe_service import classify_model_probe_failure

    assert classify_model_probe_failure(asyncio.TimeoutError()) == "timeout"
    assert classify_model_probe_failure(RuntimeError("HTTP 429")) == "rate_limit"
    assert classify_model_probe_failure(RuntimeError("HTTP 403")) == "auth_error"
    assert classify_model_probe_failure(RuntimeError("HTTP 404")) == "provider_unavailable"
    assert classify_model_probe_failure(RuntimeError("HTTP 503")) == "server_error"
