from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.admin_runtime_settings_repository import AdminRuntimeSettingsRecord


def test_record_runtime_discovery_snapshot_persists_model_hints():
    from app.engine.model_catalog import ChatModelMetadata
    from app.services.llm_runtime_audit_service import record_runtime_discovery_snapshot

    persisted_payload = {}

    def _upsert(key, settings_payload, *, description=None):
        persisted_payload.update(settings_payload)
        return AdminRuntimeSettingsRecord(
            key=key,
            settings=settings_payload,
            description=description,
            created_at=datetime(2026, 3, 23, 8, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 23, 8, 0, tzinfo=timezone.utc),
        )

    repo = MagicMock()
    repo.get_settings.return_value = None
    repo.upsert_settings.side_effect = _upsert

    catalog = {
        "providers": {
            "google": {
                "gemini-3.1-flash-lite-preview": ChatModelMetadata(
                    provider="google",
                    model_name="gemini-3.1-flash-lite-preview",
                    display_name="Gemini 3.1 Flash-Lite Preview",
                    status="current",
                    supports_tool_calling=True,
                    supports_structured_output=True,
                    supports_streaming=True,
                    context_window_tokens=1048576,
                    max_output_tokens=65536,
                    capability_source="runtime",
                )
            }
        },
        "provider_metadata": {
            "google": {
                "catalog_source": "mixed",
                "runtime_discovery_enabled": True,
                "runtime_discovery_succeeded": True,
                "model_count": 4,
                "discovered_model_count": 2,
            }
        },
    }

    with patch(
        "app.services.llm_runtime_audit_service.get_admin_runtime_settings_repository",
        return_value=repo,
    ):
        record = record_runtime_discovery_snapshot(catalog)

    assert record is not None
    assert record.persisted is True
    google_state = persisted_payload["providers"]["google"]
    assert google_state["selected_model"] == "gemini-3.1-flash-lite-preview"
    assert google_state["context_window_tokens"] == 1048576
    assert google_state["max_output_tokens"] == 65536
    assert google_state["tool_calling_supported"] is True
    assert google_state["runtime_discovery_succeeded"] is True
    assert google_state["selected_model_in_catalog"] is True
    assert google_state["last_discovery_success_at"] is not None


def test_persist_llm_runtime_audit_snapshot_returns_ephemeral_record_when_db_unavailable():
    from app.services.llm_runtime_audit_service import persist_llm_runtime_audit_snapshot

    repo = MagicMock()
    repo.upsert_settings.return_value = None

    with patch(
        "app.services.llm_runtime_audit_service.get_admin_runtime_settings_repository",
        return_value=repo,
    ):
        record = persist_llm_runtime_audit_snapshot(
            {
                "schema_version": 1,
                "audit_updated_at": "2026-03-23T08:00:00+00:00",
                "last_live_probe_at": None,
                "providers": {},
            }
        )

    assert record is not None
    assert record.persisted is False
    assert record.payload["audit_updated_at"] == "2026-03-23T08:00:00+00:00"
    assert record.warnings


def test_sanitize_llm_runtime_audit_payload_preserves_unknown_catalog_flags():
    from app.services.llm_runtime_audit_service import sanitize_llm_runtime_audit_payload

    payload = sanitize_llm_runtime_audit_payload(
        {
            "schema_version": 1,
            "audit_updated_at": "2026-04-04T08:00:00+00:00",
            "providers": {
                "openrouter": {
                    "provider": "openrouter",
                    "selected_model": "qwen/qwen3.6-plus:free",
                    "selected_model_in_catalog": None,
                    "selected_model_advanced_in_catalog": None,
                }
            },
        }
    )

    openrouter_state = payload["providers"]["openrouter"]
    assert openrouter_state["selected_model"] == "qwen/qwen3.6-plus:free"
    assert openrouter_state["selected_model_in_catalog"] is None
    assert openrouter_state["selected_model_advanced_in_catalog"] is None


@pytest.mark.asyncio
async def test_run_live_capability_probes_persists_probe_results():
    from app.services.llm_runtime_audit_service import run_live_capability_probes

    persisted_payload = {}

    def _persist(snapshot):
        persisted_payload.update(snapshot)
        return type(
            "AuditRecord",
            (),
            {
                "payload": snapshot,
                "updated_at": datetime(2026, 3, 23, 8, 5, tzinfo=timezone.utc),
            },
        )()

    with patch(
        "app.services.llm_runtime_audit_service._get_current_audit_payload",
        return_value={
            "schema_version": 1,
            "audit_updated_at": None,
            "last_live_probe_at": None,
            "providers": {
                "google": {
                    "provider": "google",
                    "selected_model": "gemini-3.1-flash-lite-preview",
                    "selected_model_advanced": None,
                    "selected_model_in_catalog": True,
                    "selected_model_advanced_in_catalog": False,
                    "probe_model": None,
                    "catalog_source": "mixed",
                    "runtime_discovery_enabled": True,
                    "runtime_discovery_succeeded": True,
                    "model_count": 4,
                    "discovered_model_count": 2,
                    "last_discovery_attempt_at": None,
                    "last_discovery_success_at": None,
                    "last_discovery_error": None,
                    "last_live_probe_attempt_at": None,
                    "last_live_probe_success_at": None,
                    "last_live_probe_error": None,
                    "live_probe_note": None,
                    "degraded": False,
                    "degraded_reasons": [],
                    "tool_calling_supported": None,
                    "tool_calling_source": None,
                    "structured_output_supported": None,
                    "structured_output_source": None,
                    "streaming_supported": None,
                    "streaming_source": None,
                    "context_window_tokens": None,
                    "context_window_source": None,
                    "max_output_tokens": None,
                    "max_output_source": None,
                },
            },
        },
    ), patch(
        "app.services.llm_runtime_audit_service._can_probe_provider",
        return_value=(True, None),
    ), patch(
        "app.services.llm_runtime_audit_service._probe_provider_capabilities",
        return_value={
            "probe_model": "gemini-3.1-flash-lite-preview",
            "tool_calling_supported": True,
            "tool_calling_source": "live_probe",
            "structured_output_supported": True,
            "structured_output_source": "live_probe",
            "streaming_supported": True,
            "streaming_source": "live_probe",
            "context_window_tokens": 1048576,
            "context_window_source": "runtime",
            "last_live_probe_error": None,
            "live_probe_note": "Live probe passed.",
        },
    ), patch(
        "app.services.llm_runtime_audit_service.persist_llm_runtime_audit_snapshot",
        side_effect=_persist,
    ):
        record = await run_live_capability_probes(
            {"providers": {"google": {}}},
            providers=["google"],
        )

    assert record is not None
    google_state = persisted_payload["providers"]["google"]
    assert google_state["tool_calling_supported"] is True
    assert google_state["structured_output_supported"] is True
    assert google_state["streaming_supported"] is True
    assert google_state["last_live_probe_success_at"] is not None
    assert google_state["degraded"] is False


@pytest.mark.asyncio
async def test_probe_structured_output_uses_openai_compatible_json_mode_for_zhipu():
    from app.services.llm_runtime_audit_service import _probe_structured_output

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"status":"ok","detail":"probe"}'
                }
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.llm_runtime_audit_service.settings") as mock_settings, patch(
        "httpx.AsyncClient",
        return_value=mock_client,
    ):
        mock_settings.zhipu_base_url = "https://open.bigmodel.cn/api/paas/v4"
        mock_settings.zhipu_api_key = "zhipu-key"
        assert await _probe_structured_output("zhipu", MagicMock(), "glm-5") is True

    called_url = mock_client.post.call_args[0][0]
    called_payload = mock_client.post.call_args[1]["json"]
    assert called_url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert called_payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_probe_provider_capabilities_google_uses_direct_health_probe():
    from app.services.llm_runtime_audit_service import _probe_provider_capabilities

    with patch(
        "app.services.llm_runtime_audit_service._get_selected_models",
        return_value={"google": {"model": "gemini-3.1-flash-lite-preview"}},
    ), patch(
        "app.services.llm_runtime_audit_service._probe_google_runtime_health",
        new=AsyncMock(),
    ) as mock_health, patch(
        "app.services.llm_runtime_audit_service.create_provider",
    ) as mock_create_provider:
        result = await _probe_provider_capabilities("google")

    mock_health.assert_awaited_once_with("gemini-3.1-flash-lite-preview")
    mock_create_provider.assert_not_called()
    assert result["probe_model"] == "gemini-3.1-flash-lite-preview"
    assert result["last_live_probe_error"] is None


def test_record_llm_runtime_observation_tracks_failover_route_and_success():
    from app.services.llm_runtime_audit_service import record_llm_runtime_observation

    persisted_payload = {}

    def _upsert(key, settings_payload, *, description=None):
        persisted_payload.update(settings_payload)
        return AdminRuntimeSettingsRecord(
            key=key,
            settings=settings_payload,
            description=description,
            created_at=datetime(2026, 4, 4, 4, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 4, 4, 0, tzinfo=timezone.utc),
        )

    repo = MagicMock()
    repo.get_settings.return_value = None
    repo.upsert_settings.side_effect = _upsert

    with patch(
        "app.services.llm_runtime_audit_service.get_admin_runtime_settings_repository",
        return_value=repo,
    ), patch(
        "app.services.llm_runtime_audit_service.bump_llm_selectability_cache_generation",
    ) as bump_cache:
        record = record_llm_runtime_observation(
            provider="openrouter",
            success=True,
            model_name="qwen/qwen3-36b:free",
            source="chat_stream",
            failover={
                "route": [
                    {
                        "from_provider": "google",
                        "to_provider": "openrouter",
                        "reason_code": "rate_limit",
                        "reason_label": "Provider vuot gioi han hoac dang bi quota/rate limit.",
                    }
                ]
            },
        )

    assert record is not None
    bump_cache.assert_called_once_with()
    google_state = persisted_payload["providers"]["google"]
    openrouter_state = persisted_payload["providers"]["openrouter"]
    assert google_state["last_runtime_error"] == "Provider vuot gioi han hoac dang bi quota/rate limit."
    assert "failover google -> openrouter" in (google_state["last_runtime_note"] or "")
    assert openrouter_state["last_runtime_success_at"] is not None
    assert openrouter_state["selected_model"] == "qwen/qwen3-36b:free"
    assert "completed via openrouter/qwen/qwen3-36b:free" in (
        openrouter_state["last_runtime_note"] or ""
    )


def test_infer_runtime_completion_degraded_reason_detects_fallback_trace():
    from app.services.llm_runtime_audit_service import (
        infer_runtime_completion_degraded_reason,
    )

    degraded_reason = infer_runtime_completion_degraded_reason(
        {
            "reasoning_trace": {
                "steps": [
                    {
                        "step_name": "direct_response",
                        "result": "Fallback (LLM generation error)",
                        "details": {"response_type": "fallback"},
                    }
                ]
            }
        }
    )

    assert degraded_reason == "fallback response (LLM generation error)"


def test_record_llm_runtime_observation_appends_degraded_reason_to_success_note():
    from app.services.llm_runtime_audit_service import record_llm_runtime_observation

    persisted_payload = {}

    def _upsert(key, settings_payload, *, description=None):
        persisted_payload.update(settings_payload)
        return AdminRuntimeSettingsRecord(
            key=key,
            settings=settings_payload,
            description=description,
            created_at=datetime(2026, 4, 4, 4, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 4, 4, 0, tzinfo=timezone.utc),
        )

    repo = MagicMock()
    repo.get_settings.return_value = None
    repo.upsert_settings.side_effect = _upsert

    with patch(
        "app.services.llm_runtime_audit_service.get_admin_runtime_settings_repository",
        return_value=repo,
    ):
        record_llm_runtime_observation(
            provider="zhipu",
            success=True,
            model_name="glm-4.5-air",
            source="chat_stream",
            degraded_reason="fallback response (LLM generation error)",
        )

    zhipu_state = persisted_payload["providers"]["zhipu"]
    assert "completed via zhipu/glm-4.5-air" in (zhipu_state["last_runtime_note"] or "")
    assert "Completion degraded: fallback response (LLM generation error)." in (
        zhipu_state["last_runtime_note"] or ""
    )
