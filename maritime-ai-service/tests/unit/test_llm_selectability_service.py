from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.llm_runtime_audit_service import LlmRuntimeAuditRecord


def _provider(*, configured: bool = True, available: bool = True):
    mock = MagicMock()
    mock.is_configured.return_value = configured
    mock.is_available.return_value = available
    return mock


def _audit_record(google_state: dict) -> LlmRuntimeAuditRecord:
    return LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-03-23T10:00:00+00:00",
            "last_live_probe_at": "2026-03-23T10:00:00+00:00",
            "providers": {
                "google": google_state,
                "zhipu": {"provider": "zhipu"},
                "openai": {"provider": "openai"},
                "openrouter": {"provider": "openrouter"},
                "ollama": {"provider": "ollama"},
            },
        },
        updated_at=datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
        persisted=True,
    )


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_configured_healthy_provider_is_selectable(mock_stats, mock_provider_info, mock_settings):
    from app.services.llm_selectability_service import get_llm_selectability_snapshot, invalidate_llm_selectability_cache

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google"],
        "active_provider": "google",
        "fallback_provider": "zhipu",
    }
    mock_provider_info.side_effect = lambda name: _provider(configured=(name == "google"), available=(name == "google"))

    google_state = {
        "provider": "google",
        "selected_model": "gemini-3.1-flash-lite-preview",
        "selected_model_in_catalog": True,
        "model_count": 3,
        "last_discovery_attempt_at": "2026-03-23T09:59:00+00:00",
        "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
        "last_live_probe_success_at": "2026-03-23T10:00:00+00:00",
        "streaming_supported": True,
        "structured_output_supported": True,
        "tool_calling_supported": True,
        "degraded_reasons": [],
    }

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=_audit_record(google_state),
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    assert google.state == "selectable"
    assert google.reason_code is None


@patch("app.services.llm_selectability_service.get_supported_provider_names")
@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_nvidia_provider_requires_streaming_only_for_selectability(
    mock_stats,
    mock_provider_info,
    mock_settings,
    mock_supported_providers,
):
    from app.services.llm_selectability_service import get_llm_selectability_snapshot, invalidate_llm_selectability_cache

    invalidate_llm_selectability_cache()
    mock_supported_providers.return_value = ["nvidia"]
    mock_settings.use_multi_agent = True
    mock_settings.nvidia_model = "deepseek-ai/deepseek-v4-flash"
    mock_stats.return_value = {
        "request_selectable_providers": ["nvidia"],
        "active_provider": "nvidia",
        "fallback_provider": None,
    }
    mock_provider_info.return_value = _provider(configured=True, available=True)

    audit_record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-03-23T10:00:00+00:00",
            "last_live_probe_at": "2026-03-23T10:00:00+00:00",
            "providers": {
                "nvidia": {
                    "provider": "nvidia",
                    "selected_model": "deepseek-ai/deepseek-v4-flash",
                    "selected_model_in_catalog": True,
                    "model_count": 2,
                    "last_discovery_attempt_at": "2026-03-23T09:59:00+00:00",
                    "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
                    "streaming_supported": True,
                    "structured_output_supported": False,
                    "structured_output_source": "static",
                    "tool_calling_supported": False,
                    "tool_calling_source": "static",
                    "degraded_reasons": [],
                }
            },
        },
        updated_at=datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=audit_record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    nvidia = next(item for item in snapshot if item.provider == "nvidia")
    assert nvidia.state == "selectable"
    assert nvidia.reason_code is None


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_rate_limited_provider_is_disabled_busy(mock_stats, mock_provider_info, mock_settings):
    from app.services.llm_selectability_service import get_llm_selectability_snapshot, invalidate_llm_selectability_cache

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google"],
        "active_provider": "google",
        "fallback_provider": None,
    }
    mock_provider_info.side_effect = lambda name: _provider(configured=(name == "google"), available=True)

    google_state = {
        "provider": "google",
        "selected_model": "gemini-3.1-flash-lite-preview",
        "selected_model_in_catalog": True,
        "model_count": 3,
        "last_discovery_attempt_at": "2026-03-23T09:59:00+00:00",
        "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
        "last_live_probe_error": "provider probe: quota_or_rate_limited (429)",
        "streaming_supported": True,
        "structured_output_supported": True,
        "tool_calling_supported": True,
        "degraded_reasons": ["Live capability probe failed."],
    }

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=_audit_record(google_state),
    ), patch(
        "app.services.llm_selectability_service.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 23, 10, 1, tzinfo=timezone.utc)
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    assert google.state == "disabled"
    assert google.reason_code == "busy"


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_stale_busy_provider_recovers_to_selectable_when_runtime_available(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google"],
        "active_provider": "google",
        "fallback_provider": None,
    }
    mock_provider_info.side_effect = lambda name: _provider(configured=(name == "google"), available=True)

    google_state = {
        "provider": "google",
        "selected_model": "gemini-3.1-flash-lite-preview",
        "selected_model_in_catalog": True,
        "model_count": 3,
        "last_discovery_attempt_at": "2026-03-23T09:50:00+00:00",
        "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
        "last_live_probe_error": "provider probe: quota_or_rate_limited (429)",
        "streaming_supported": True,
        "structured_output_supported": True,
        "tool_calling_supported": True,
        "degraded_reasons": ["Live capability probe failed."],
    }

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=_audit_record(google_state),
    ), patch(
        "app.services.llm_selectability_service.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 23, 10, 20, tzinfo=timezone.utc)
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        mock_datetime.timezone = timezone
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    assert google.state == "selectable"
    assert google.reason_code is None


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_probe_failed_capability_does_not_disable_otherwise_healthy_provider(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "zhipu"],
        "active_provider": "google",
        "fallback_provider": "zhipu",
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "zhipu"}),
        available=(name in {"google", "zhipu"}),
    )

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-03-23T10:00:00+00:00",
            "last_live_probe_at": "2026-03-23T10:00:00+00:00",
            "providers": {
                "google": {"provider": "google"},
                "zhipu": {
                    "provider": "zhipu",
                    "selected_model": "glm-4.5-air",
                    "selected_model_in_catalog": True,
                    "model_count": 6,
                    "last_discovery_attempt_at": "2026-03-23T09:59:00+00:00",
                    "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
                    "last_live_probe_success_at": "2026-03-23T10:00:00+00:00",
                    "last_live_probe_error": "tool calling: timeout",
                    "tool_calling_supported": None,
                    "tool_calling_source": "probe_failed",
                    "structured_output_supported": True,
                    "structured_output_source": "live_probe",
                    "streaming_supported": True,
                    "streaming_source": "live_probe",
                    "degraded_reasons": ["Live capability probe failed."],
                },
                "openai": {"provider": "openai"},
                "openrouter": {"provider": "openrouter"},
                "ollama": {"provider": "ollama"},
            },
        },
        updated_at=datetime(2026, 3, 23, 10, 0, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    zhipu = next(item for item in snapshot if item.provider == "zhipu")
    assert zhipu.state == "selectable"
    assert zhipu.reason_code is None


@patch("app.services.llm_selectability_service.get_supported_provider_names")
@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_ollama_partial_probe_timeout_does_not_override_streaming_success(
    mock_stats,
    mock_provider_info,
    mock_settings,
    mock_supported_providers,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_supported_providers.return_value = ("ollama",)
    mock_settings.use_multi_agent = False
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:4b"
    mock_settings.llm_provider = "ollama"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["ollama"],
        "active_provider": "ollama",
        "fallback_provider": None,
    }
    mock_provider_info.return_value = _provider(configured=True, available=False)

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-05-26T04:23:47+00:00",
            "last_live_probe_at": "2026-05-26T04:23:26+00:00",
            "providers": {
                "ollama": {
                    "provider": "ollama",
                    "selected_model": "qwen3:4b",
                    "selected_model_in_catalog": True,
                    "model_count": 2,
                    "last_discovery_attempt_at": "2026-05-26T04:23:26+00:00",
                    "last_live_probe_attempt_at": "2026-05-26T04:23:26+00:00",
                    "last_live_probe_success_at": "2026-05-26T04:23:26+00:00",
                    "last_live_probe_error": "tool calling: timeout; structured output: timeout",
                    "last_runtime_observation_at": "2026-05-26T04:30:12+00:00",
                    "last_runtime_success_at": "2026-05-26T04:29:50+00:00",
                    "last_runtime_error": "May chu local hien chua san sang.",
                    "last_runtime_note": "chat_stream:error: requested provider ollama unavailable (host_down).",
                    "last_runtime_source": "chat_stream:error",
                    "tool_calling_supported": None,
                    "tool_calling_source": "probe_failed",
                    "structured_output_supported": None,
                    "structured_output_source": "probe_failed",
                    "streaming_supported": True,
                    "streaming_source": "live_probe",
                    "degraded_reasons": ["Live capability probe failed."],
                },
            },
        },
        updated_at=datetime(2026, 5, 26, 4, 23, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    ollama = next(item for item in snapshot if item.provider == "ollama")
    assert ollama.state == "selectable"
    assert ollama.reason_code is None


@patch("app.services.llm_selectability_service.get_supported_provider_names")
@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_ollama_runtime_success_overrides_partial_probe_timeout(
    mock_stats,
    mock_provider_info,
    mock_settings,
    mock_supported_providers,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_supported_providers.return_value = ("ollama",)
    mock_settings.use_multi_agent = False
    mock_settings.ollama_model = "qwen3:4b"
    mock_settings.llm_provider = "ollama"
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["ollama"],
        "active_provider": "ollama",
        "fallback_provider": None,
    }
    mock_provider_info.return_value = _provider(configured=True, available=True)

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-05-26T04:49:08+00:00",
            "providers": {
                "ollama": {
                    "provider": "ollama",
                    "selected_model": "qwen3:4b",
                    "selected_model_in_catalog": True,
                    "model_count": 2,
                    "last_live_probe_success_at": "2026-05-26T04:23:26+00:00",
                    "last_live_probe_error": "tool calling: timeout; structured output: timeout",
                    "last_runtime_observation_at": "2026-05-26T04:49:08+00:00",
                    "last_runtime_success_at": "2026-05-26T04:49:08+00:00",
                    "last_runtime_error": None,
                    "last_runtime_note": "chat_sync: completed via ollama/qwen3:4b.",
                    "last_runtime_source": "chat_sync",
                    "tool_calling_supported": None,
                    "tool_calling_source": "probe_failed",
                    "structured_output_supported": None,
                    "structured_output_source": "probe_failed",
                    "streaming_supported": True,
                    "streaming_source": "live_probe",
                    "degraded_reasons": ["Live capability probe failed."],
                },
            },
        },
        updated_at=datetime(2026, 5, 26, 4, 49, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    ollama = next(item for item in snapshot if item.provider == "ollama")
    assert ollama.state == "selectable"
    assert ollama.reason_code is None


@patch("app.services.llm_selectability_service.get_supported_provider_names")
@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_ollama_preflight_unavailable_does_not_override_streaming_success_without_runtime_success(
    mock_stats,
    mock_provider_info,
    mock_settings,
    mock_supported_providers,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_supported_providers.return_value = ("ollama",)
    mock_settings.use_multi_agent = False
    mock_settings.ollama_model = "qwen3:4b"
    mock_settings.llm_provider = "ollama"
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["ollama"],
        "active_provider": "ollama",
        "fallback_provider": None,
    }
    mock_provider_info.return_value = _provider(configured=True, available=False)

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-05-26T04:49:08+00:00",
            "providers": {
                "ollama": {
                    "provider": "ollama",
                    "selected_model": "qwen3:4b",
                    "selected_model_in_catalog": True,
                    "model_count": 2,
                    "last_live_probe_attempt_at": "2026-05-26T04:23:26+00:00",
                    "last_live_probe_success_at": "2026-05-26T04:23:26+00:00",
                    "last_live_probe_error": "tool calling: timeout; structured output: timeout",
                    "last_runtime_observation_at": "2026-05-26T04:49:08+00:00",
                    "last_runtime_error": "May chu local hien chua san sang.",
                    "last_runtime_note": "chat_stream:error: requested provider ollama unavailable (host_down).",
                    "last_runtime_source": "chat_stream:error",
                    "tool_calling_supported": None,
                    "tool_calling_source": "probe_failed",
                    "structured_output_supported": None,
                    "structured_output_source": "probe_failed",
                    "streaming_supported": True,
                    "streaming_source": "live_probe",
                    "degraded_reasons": ["Live capability probe failed."],
                },
            },
        },
        updated_at=datetime(2026, 5, 26, 4, 49, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    ollama = next(item for item in snapshot if item.provider == "ollama")
    assert ollama.state == "selectable"
    assert ollama.reason_code is None


@patch("app.services.llm_selectability_service.get_supported_provider_names")
@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_runtime_success_does_not_bypass_required_capability_gating(
    mock_stats,
    mock_provider_info,
    mock_settings,
    mock_supported_providers,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_supported_providers.return_value = ("google",)
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google"],
        "active_provider": "google",
        "fallback_provider": None,
    }
    mock_provider_info.return_value = _provider(configured=True, available=True)

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-05-26T04:49:08+00:00",
            "providers": {
                "google": {
                    "provider": "google",
                    "selected_model": "gemini-3.1-flash-lite-preview",
                    "selected_model_in_catalog": True,
                    "model_count": 3,
                    "last_runtime_observation_at": "2026-05-26T04:49:08+00:00",
                    "last_runtime_success_at": "2026-05-26T04:49:08+00:00",
                    "last_runtime_error": None,
                    "last_runtime_note": "chat_sync: completed via google/gemini-3.1-flash-lite-preview.",
                    "last_runtime_source": "chat_sync",
                    "streaming_supported": True,
                    "streaming_source": "live_probe",
                    "structured_output_supported": False,
                    "structured_output_source": "live_probe",
                    "tool_calling_supported": True,
                    "tool_calling_source": "live_probe",
                },
            },
        },
        updated_at=datetime(2026, 5, 26, 4, 49, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    assert google.state == "disabled"
    assert google.reason_code == "capability_missing"


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_missing_audit_does_not_hide_runtime_available_provider(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "zhipu"],
        "active_provider": "zhipu",
        "fallback_provider": None,
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "zhipu"}),
        available=(name == "zhipu"),
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=None,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    zhipu = next(item for item in snapshot if item.provider == "zhipu")
    assert zhipu.state == "selectable"
    assert zhipu.reason_code is None


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_empty_provider_audit_state_does_not_block_new_runtime_available_provider(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_settings.openrouter_model = "qwen/qwen3.6-plus:free"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "openrouter"],
        "active_provider": "google",
        "fallback_provider": "openrouter",
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "openrouter"}),
        available=(name == "openrouter"),
    )

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-04-04T07:00:00+00:00",
            "last_live_probe_at": "2026-04-04T07:00:00+00:00",
            "providers": {
                "google": {
                    "provider": "google",
                    "selected_model": "gemini-3.1-flash-lite-preview",
                    "selected_model_in_catalog": True,
                    "model_count": 3,
                    "last_live_probe_attempt_at": "2026-04-04T07:00:00+00:00",
                },
                "zhipu": {"provider": "zhipu"},
                "openai": {"provider": "openai"},
                "openrouter": {"provider": "openrouter"},
                "ollama": {"provider": "ollama"},
            },
        },
        updated_at=datetime(2026, 4, 4, 7, 0, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    openrouter = next(item for item in snapshot if item.provider == "openrouter")
    assert openrouter.state == "selectable"
    assert openrouter.reason_code is None


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_changed_provider_model_ignores_stale_audit_until_new_probe(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_settings.openrouter_model = "qwen/qwen3.6-plus:free"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "openrouter"],
        "active_provider": "google",
        "fallback_provider": "openrouter",
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "openrouter"}),
        available=(name == "openrouter"),
    )

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-04-04T07:48:08.962524+00:00",
            "last_live_probe_at": "2026-04-04T07:48:08.962524+00:00",
            "providers": {
                "google": {
                    "provider": "google",
                    "selected_model": "gemini-3.1-flash-lite-preview",
                    "selected_model_in_catalog": True,
                    "model_count": 3,
                    "last_live_probe_attempt_at": "2026-04-04T07:48:08.962524+00:00",
                },
                "zhipu": {"provider": "zhipu"},
                "openai": {"provider": "openai"},
                "openrouter": {
                    "provider": "openrouter",
                    "selected_model": "openai/gpt-oss-20b:free",
                    "selected_model_in_catalog": True,
                    "model_count": 2,
                    "last_runtime_observation_at": "2026-04-04T07:48:08.962524+00:00",
                    "last_runtime_error": "He thong dang xac minh trang thai runtime.",
                    "last_runtime_note": "chat_stream:error: requested provider openrouter unavailable (verifying).",
                    "streaming_supported": True,
                    "streaming_source": "static",
                },
                "ollama": {"provider": "ollama"},
            },
        },
        updated_at=datetime(2026, 4, 4, 7, 48, 8, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    openrouter = next(item for item in snapshot if item.provider == "openrouter")
    assert openrouter.state == "selectable"
    assert openrouter.reason_code is None
    assert openrouter.selected_model == "qwen/qwen3.6-plus:free"
    assert openrouter.verified_at is None


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_latest_runtime_success_keeps_provider_selectable_without_catalog_confirmation(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_settings.openrouter_model = "qwen/qwen3.6-plus:free"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "openrouter"],
        "active_provider": "google",
        "fallback_provider": "openrouter",
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "openrouter"}),
        available=(name == "openrouter"),
    )

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-04-04T08:00:00+00:00",
            "last_live_probe_at": "2026-04-04T08:00:00+00:00",
            "providers": {
                "google": {
                    "provider": "google",
                    "selected_model": "gemini-3.1-flash-lite-preview",
                    "selected_model_in_catalog": True,
                    "model_count": 3,
                    "last_live_probe_attempt_at": "2026-04-04T08:00:00+00:00",
                },
                "zhipu": {"provider": "zhipu"},
                "openai": {"provider": "openai"},
                "openrouter": {
                    "provider": "openrouter",
                    "selected_model": "qwen/qwen3.6-plus:free",
                    "selected_model_in_catalog": None,
                    "model_count": 2,
                    "last_runtime_observation_at": "2026-04-04T08:05:00+00:00",
                    "last_runtime_success_at": "2026-04-04T08:05:00+00:00",
                    "last_runtime_error": None,
                    "streaming_supported": True,
                    "streaming_source": "static",
                },
                "ollama": {"provider": "ollama"},
            },
        },
        updated_at=datetime(2026, 4, 4, 8, 5, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ):
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    openrouter = next(item for item in snapshot if item.provider == "openrouter")
    assert openrouter.state == "selectable"
    assert openrouter.reason_code is None


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_choose_best_runtime_provider_prefers_degraded_but_routable_provider_over_busy_primary(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        choose_best_runtime_provider,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "zhipu", "ollama"],
        "active_provider": "google",
        "fallback_provider": "zhipu",
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "zhipu", "ollama"}),
        available=(name in {"google", "zhipu"}),
    )

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-03-24T08:00:00+00:00",
            "last_live_probe_at": "2026-03-24T08:00:00+00:00",
            "providers": {
                "google": {
                    "provider": "google",
                    "selected_model": "gemini-3.1-flash-lite-preview",
                    "selected_model_in_catalog": True,
                    "model_count": 3,
                    "last_live_probe_attempt_at": "2026-03-24T08:00:00+00:00",
                    "last_live_probe_error": "provider probe: quota_or_rate_limited (429)",
                    "streaming_supported": True,
                    "structured_output_supported": True,
                    "tool_calling_supported": True,
                    "degraded_reasons": ["Live capability probe failed."],
                },
                "zhipu": {
                    "provider": "zhipu",
                    "selected_model": "glm-4.5-air",
                    "selected_model_in_catalog": True,
                    "model_count": 6,
                    "last_live_probe_attempt_at": "2026-03-24T08:00:00+00:00",
                    "last_live_probe_success_at": "2026-03-24T08:00:00+00:00",
                    "streaming_supported": True,
                    "streaming_source": "live_probe",
                    "structured_output_supported": False,
                    "structured_output_source": "live_probe",
                    "tool_calling_supported": True,
                    "tool_calling_source": "live_probe",
                    "degraded_reasons": ["Structured output probe returned false."],
                },
                "openai": {"provider": "openai"},
                "openrouter": {"provider": "openrouter"},
                "ollama": {
                    "provider": "ollama",
                    "selected_model": "qwen3:8b",
                    "selected_model_in_catalog": False,
                    "last_live_probe_error": "host unreachable",
                },
            },
        },
        updated_at=datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ), patch(
        "app.services.llm_selectability_service.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 24, 8, 1, tzinfo=timezone.utc)
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        chosen = choose_best_runtime_provider(
            preferred_provider="google",
            provider_order=["google", "zhipu", "ollama"],
            allow_degraded_fallback=True,
            force_refresh=True,
        )

    assert chosen is not None
    assert chosen.provider == "zhipu"
    assert chosen.reason_code == "capability_missing"


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_recent_runtime_failure_keeps_provider_disabled_even_when_probe_busy_signal_is_stale(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google", "zhipu"],
        "active_provider": "google",
        "fallback_provider": "zhipu",
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name in {"google", "zhipu"}),
        available=(name in {"google", "zhipu"}),
    )

    google_state = {
        "provider": "google",
        "selected_model": "gemini-3.1-flash-lite-preview",
        "selected_model_in_catalog": True,
        "model_count": 3,
        "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
        "last_live_probe_error": "provider probe: quota_or_rate_limited (429)",
        "last_runtime_observation_at": "2026-03-23T10:19:00+00:00",
        "last_runtime_success_at": "2026-03-23T10:05:00+00:00",
        "last_runtime_error": "Cannot connect to host generativelanguage.googleapis.com",
        "last_runtime_note": "chat_stream:error: requested provider google unavailable (timeout).",
        "streaming_supported": True,
        "structured_output_supported": True,
        "tool_calling_supported": True,
    }

    zhipu_state = {
        "provider": "zhipu",
        "selected_model": "glm-4.5-air",
        "selected_model_in_catalog": True,
        "model_count": 6,
        "last_live_probe_attempt_at": "2026-03-23T10:19:00+00:00",
        "last_live_probe_success_at": "2026-03-23T10:19:00+00:00",
        "streaming_supported": True,
        "structured_output_supported": True,
        "tool_calling_supported": True,
    }

    record = LlmRuntimeAuditRecord(
        payload={
            "schema_version": 1,
            "audit_updated_at": "2026-03-23T10:19:00+00:00",
            "last_live_probe_at": "2026-03-23T10:00:00+00:00",
            "providers": {
                "google": google_state,
                "zhipu": zhipu_state,
                "openai": {"provider": "openai"},
                "openrouter": {"provider": "openrouter"},
                "ollama": {"provider": "ollama"},
            },
        },
        updated_at=datetime(2026, 3, 23, 10, 19, tzinfo=timezone.utc),
        persisted=True,
    )

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=record,
    ), patch(
        "app.services.llm_selectability_service.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 23, 10, 20, tzinfo=timezone.utc)
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        mock_datetime.timezone = timezone
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    zhipu = next(item for item in snapshot if item.provider == "zhipu")
    assert google.state == "disabled"
    assert google.reason_code == "busy"
    assert zhipu.state == "selectable"


@patch("app.services.llm_selectability_service.settings")
@patch("app.services.llm_selectability_service.LLMPool.get_provider_info")
@patch("app.services.llm_selectability_service.LLMPool.get_stats")
def test_runtime_success_newer_than_probe_busy_signal_recovers_provider(
    mock_stats,
    mock_provider_info,
    mock_settings,
):
    from app.services.llm_selectability_service import (
        get_llm_selectability_snapshot,
        invalidate_llm_selectability_cache,
    )

    invalidate_llm_selectability_cache()
    mock_settings.use_multi_agent = True
    mock_settings.google_model = "gemini-3.1-flash-lite-preview"
    mock_settings.zhipu_model = "glm-4.5-air"
    mock_settings.ollama_model = "qwen3:8b"
    mock_settings.llm_provider = "google"
    mock_settings.openai_base_url = None
    mock_settings.openai_model = "gpt-5-mini"
    mock_stats.return_value = {
        "request_selectable_providers": ["google"],
        "active_provider": "google",
        "fallback_provider": None,
    }
    mock_provider_info.side_effect = lambda name: _provider(
        configured=(name == "google"),
        available=(name == "google"),
    )

    google_state = {
        "provider": "google",
        "selected_model": "gemini-3.1-flash-lite-preview",
        "selected_model_in_catalog": True,
        "model_count": 3,
        "last_live_probe_attempt_at": "2026-03-23T10:00:00+00:00",
        "last_live_probe_error": "provider probe: quota_or_rate_limited (429)",
        "last_runtime_observation_at": "2026-03-23T10:19:00+00:00",
        "last_runtime_success_at": "2026-03-23T10:19:00+00:00",
        "last_runtime_error": None,
        "last_runtime_note": "chat_stream: completed via google/gemini-3.1-flash-lite-preview.",
        "streaming_supported": True,
        "structured_output_supported": True,
        "tool_calling_supported": True,
    }

    with patch(
        "app.services.llm_selectability_service.get_persisted_llm_runtime_audit",
        return_value=_audit_record(google_state),
    ), patch(
        "app.services.llm_selectability_service.datetime"
    ) as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 23, 10, 20, tzinfo=timezone.utc)
        mock_datetime.fromisoformat.side_effect = datetime.fromisoformat
        mock_datetime.timezone = timezone
        snapshot = get_llm_selectability_snapshot(force_refresh=True)

    google = next(item for item in snapshot if item.provider == "google")
    assert google.state == "selectable"
    assert google.reason_code is None


# ---------------------------------------------------------------------------
# PR #114: probe success supersedes failed runtime observation
# ---------------------------------------------------------------------------


def test_probe_success_supersedes_observation_helper():
    """Probe success at-or-after observation overrides the failure."""
    from app.services.llm_selectability_service import _probe_success_supersedes_observation

    state_recovered = {
        "last_runtime_observation_at": "2026-04-25T15:21:00+00:00",
        "last_live_probe_success_at": "2026-04-25T15:29:00+00:00",
    }
    assert _probe_success_supersedes_observation(state_recovered) is True

    state_equal = {
        "last_runtime_observation_at": "2026-04-25T15:21:00+00:00",
        "last_live_probe_success_at": "2026-04-25T15:21:00+00:00",
    }
    assert _probe_success_supersedes_observation(state_equal) is True

    state_stale_probe = {
        "last_runtime_observation_at": "2026-04-25T15:29:00+00:00",
        "last_live_probe_success_at": "2026-04-25T15:21:00+00:00",
    }
    assert _probe_success_supersedes_observation(state_stale_probe) is False

    assert _probe_success_supersedes_observation(
        {"last_runtime_observation_at": "2026-04-25T15:21:00+00:00"}
    ) is False
    assert _probe_success_supersedes_observation(
        {"last_live_probe_success_at": "2026-04-25T15:21:00+00:00"}
    ) is False


def test_runtime_observation_failure_overridden_by_fresh_probe():
    """Stale chat_stream:error observation is masked by a newer probe success.

    Loop-break behavior introduced in PR #114: NVIDIA was getting rejected by
    ensure_provider_is_selectable, the rejection was recorded as a runtime
    observation failure, and the next request saw the same audit state and
    rejected again — forever. A successful live probe between rejections
    must clear the failure.
    """
    from app.services.llm_selectability_service import _latest_runtime_observation_failed

    state_loop = {
        "last_runtime_observation_at": "2026-04-25T15:21:00+00:00",
        "last_runtime_error": "Provider tam thoi ban hoac da cham gioi han.",
        "last_runtime_success_at": None,
        "last_live_probe_success_at": "2026-04-25T15:29:00+00:00",
    }
    assert _latest_runtime_observation_failed(state_loop) is False

    state_no_probe = {
        "last_runtime_observation_at": "2026-04-25T15:21:00+00:00",
        "last_runtime_error": "Provider tam thoi ban hoac da cham gioi han.",
        "last_runtime_success_at": None,
    }
    assert _latest_runtime_observation_failed(state_no_probe) is True


def test_busy_signal_overridden_by_fresh_probe_success():
    """A 429 marker in last_runtime_note is masked by a newer probe success."""
    from app.services.llm_selectability_service import _is_stale_busy_signal

    state_busy_marker_with_fresh_probe = {
        "last_runtime_observation_at": "2026-04-25T15:21:00+00:00",
        "last_runtime_success_at": "2026-04-25T15:21:00+00:00",
        "last_runtime_note": "chat_stream: completed after 429 quota recovery.",
        "last_live_probe_success_at": "2026-04-25T15:29:00+00:00",
    }
    assert _is_stale_busy_signal(state_busy_marker_with_fresh_probe) is True


def test_ensure_provider_is_selectable_allows_capability_missing_for_explicit_pin():
    """Explicit user pin bypasses capability_missing.

    DeepSeek V4 on NVIDIA NIM lacks structured_output but is otherwise usable;
    user explicitly chose this provider so the strict gate would prevent
    legitimate use.
    """
    from app.services.llm_selectability_service import (
        ensure_provider_is_selectable,
        ProviderSelectability,
    )

    pinned_capable = ProviderSelectability(
        provider="nvidia",
        display_name="Nvidia",
        state="disabled",
        reason_code="capability_missing",
        reason_label="Provider thieu mot so kha nang.",
        selected_model="deepseek-ai/deepseek-v4-flash",
        strict_pin=True,
        verified_at="2026-04-25T15:29:41+00:00",
        available=False,
        configured=True,
        request_selectable=True,
        is_primary=False,
        is_fallback=False,
    )

    with patch(
        "app.services.llm_selectability_service.get_provider_selectability",
        return_value=pinned_capable,
    ):
        result = ensure_provider_is_selectable("nvidia")
    assert result is pinned_capable


def test_ensure_provider_is_selectable_refreshes_stale_ollama_host_down():
    from app.services.llm_selectability_service import (
        ensure_provider_is_selectable,
        ProviderSelectability,
    )

    stale_host_down = ProviderSelectability(
        provider="ollama",
        display_name="Ollama",
        state="disabled",
        reason_code="host_down",
        reason_label="May chu local hien chua san sang.",
        selected_model="qwen3:4b",
        strict_pin=True,
        verified_at="2026-05-26T04:23:26+00:00",
        available=False,
        configured=True,
        request_selectable=True,
        is_primary=True,
        is_fallback=False,
    )
    refreshed = ProviderSelectability(
        provider="ollama",
        display_name="Ollama",
        state="selectable",
        reason_code=None,
        reason_label=None,
        selected_model="qwen3:4b",
        strict_pin=True,
        verified_at="2026-05-26T04:41:20+00:00",
        available=True,
        configured=True,
        request_selectable=True,
        is_primary=True,
        is_fallback=False,
    )

    with patch(
        "app.services.llm_selectability_service.get_provider_selectability",
        return_value=stale_host_down,
    ), patch(
        "app.services.llm_selectability_service._refresh_provider_selectability",
        return_value=refreshed,
    ):
        result = ensure_provider_is_selectable("ollama")

    assert result is refreshed


def test_ensure_provider_is_selectable_still_rejects_hidden_provider():
    """Regression guard: capability_missing bypass must NOT extend to hidden state."""
    from app.services.llm_selectability_service import (
        ensure_provider_is_selectable,
        ProviderSelectability,
    )
    from app.core.exceptions import ProviderUnavailableError

    hidden_item = ProviderSelectability(
        provider="ollama",
        display_name="Ollama",
        state="hidden",
        reason_code=None,
        reason_label=None,
        selected_model=None,
        strict_pin=True,
        verified_at=None,
        available=False,
        configured=False,
        request_selectable=False,
        is_primary=False,
        is_fallback=False,
    )

    with patch(
        "app.services.llm_selectability_service.get_provider_selectability",
        return_value=hidden_item,
    ):
        try:
            ensure_provider_is_selectable("ollama")
            assert False, "Expected ProviderUnavailableError"
        except ProviderUnavailableError as exc:
            assert exc.provider == "ollama"


def test_ensure_provider_is_selectable_still_rejects_busy_provider():
    """Regression guard: capability_missing bypass must NOT extend to busy state.

    A busy provider hasn't passed a recent probe; we still want to reject it
    even on explicit pin so the user gets a clear error rather than a real
    failure mid-stream.
    """
    from app.services.llm_selectability_service import (
        ensure_provider_is_selectable,
        ProviderSelectability,
    )
    from app.core.exceptions import ProviderUnavailableError

    busy_item = ProviderSelectability(
        provider="nvidia",
        display_name="Nvidia",
        state="disabled",
        reason_code="busy",
        reason_label="Provider tam thoi ban.",
        selected_model="deepseek-ai/deepseek-v4-flash",
        strict_pin=True,
        verified_at="2026-04-25T15:29:41+00:00",
        available=False,
        configured=True,
        request_selectable=True,
        is_primary=False,
        is_fallback=False,
    )

    with patch(
        "app.services.llm_selectability_service.get_provider_selectability",
        return_value=busy_item,
    ):
        try:
            ensure_provider_is_selectable("nvidia")
            assert False, "Expected ProviderUnavailableError"
        except ProviderUnavailableError as exc:
            assert exc.provider == "nvidia"
            assert exc.reason_code == "busy"
