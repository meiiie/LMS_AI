from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded

from app.api.v1.admin import (
    LlmRuntimeConfigResponse,
    ProviderRuntimeStatus,
    router as admin_router,
)
from app.api.v1.chat import router as chat_router
from app.api.v1.chat_stream import (
    _stream_request_headers_with_request_id,
    router as chat_stream_router,
)
from app.api.v1.llm_status import router as llm_status_router
from app.core.exceptions import ProviderUnavailableError
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.security import AuthenticatedUser, require_auth
from app.engine.runtime.session_event_log import InMemorySessionEventLog
from app.models.schemas import AgentType, InternalChatResponse
from app.services.llm_selectability_service import ProviderSelectability


def _student_auth() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id="student-123",
        auth_method="api_key",
        role="student",
        platform_role="user",
    )


def _admin_auth() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id="admin-123",
        auth_method="jwt",
        role="admin",
        platform_role="platform_admin",
    )


def _build_smoke_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(chat_stream_router, prefix="/api/v1")
    app.include_router(llm_status_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    return app


def _transport(app: FastAPI) -> httpx.ASGITransport:
    return httpx.ASGITransport(app=app)


def _runtime_response() -> LlmRuntimeConfigResponse:
    return LlmRuntimeConfigResponse(
        provider="zhipu",
        use_multi_agent=False,
        google_model="gemini-3.1-flash-lite-preview",
        openai_base_url=None,
        openai_model="gpt-5-mini",
        openai_model_advanced="gpt-5.4",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_model="openai/gpt-oss-20b:free",
        openrouter_model_advanced="openai/gpt-oss-120b:free",
        nvidia_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_model="deepseek-ai/deepseek-v4-flash",
        nvidia_model_advanced="deepseek-ai/deepseek-v4-pro",
        zhipu_base_url="https://open.bigmodel.cn/api/paas/v4",
        zhipu_model="glm-5",
        zhipu_model_advanced="glm-5",
        openrouter_model_fallbacks=[],
        openrouter_provider_order=[],
        openrouter_allowed_providers=[],
        openrouter_ignored_providers=[],
        openrouter_allow_fallbacks=None,
        openrouter_require_parameters=None,
        openrouter_data_collection=None,
        openrouter_zdr=None,
        openrouter_provider_sort=None,
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen3:8b",
        ollama_keep_alive="5m",
        google_api_key_configured=True,
        openai_api_key_configured=False,
        openrouter_api_key_configured=False,
        nvidia_api_key_configured=False,
        zhipu_api_key_configured=True,
        ollama_api_key_configured=False,
        enable_llm_failover=True,
        llm_failover_chain=["google", "zhipu", "ollama", "openrouter"],
        active_provider="zhipu",
        providers_registered=["google", "zhipu", "ollama"],
        request_selectable_providers=["google", "zhipu", "ollama"],
        provider_status=[
            ProviderRuntimeStatus(
                provider="zhipu",
                display_name="GLM-5",
                configured=True,
                available=True,
                registered=True,
                request_selectable=True,
                in_failover_chain=True,
                is_default=True,
                is_active=True,
                configurable_via_admin=True,
            )
        ],
        agent_profiles={},
        timeout_profiles={
            "light_seconds": 14,
            "moderate_seconds": 28,
            "deep_seconds": 50,
            "structured_seconds": 70,
            "background_seconds": 0,
            "stream_keepalive_interval_seconds": 15,
            "stream_idle_timeout_seconds": 0,
        },
        timeout_provider_overrides={},
        vision_provider="auto",
        vision_failover_chain=["google", "openai", "ollama"],
        vision_timeout_seconds=30.0,
        vision_provider_status=[
            {
                "provider": "google",
                "display_name": "Gemini Vision",
                "configured": True,
                "available": True,
                "in_failover_chain": True,
                "is_default": True,
                "is_active": True,
                "selected_model": "gemini-3.1-flash-lite-preview",
                "reason_code": None,
                "reason_label": None,
                "last_probe_attempt_at": "2026-03-23T12:00:00+00:00",
                "last_probe_success_at": "2026-03-23T12:00:00+00:00",
                "last_probe_error": None,
                "degraded": False,
                "degraded_reasons": [],
                "capabilities": [
                    {
                        "capability": "visual_describe",
                        "display_name": "Mo ta anh",
                        "available": True,
                        "selected_model": "gemini-3.1-flash-lite-preview",
                        "reason_code": None,
                        "reason_label": None,
                        "resolved_base_url": None,
                        "last_probe_attempt_at": "2026-03-23T12:00:00+00:00",
                        "last_probe_success_at": "2026-03-23T12:00:00+00:00",
                        "last_probe_error": None,
                        "live_probe_note": "Probe ok.",
                    }
                ],
            }
        ],
        vision_audit_updated_at="2026-03-23T12:00:00+00:00",
        vision_last_live_probe_at="2026-03-23T12:00:00+00:00",
        vision_audit_persisted=True,
        vision_audit_warnings=[],
        embedding_provider="auto",
        embedding_failover_chain=["google", "zhipu", "ollama"],
        embedding_model="models/gemini-embedding-001",
        embedding_dimensions=768,
        embedding_status="current",
        embedding_provider_status=[
            {
                "provider": "google",
                "display_name": "Gemini Embeddings",
                "configured": True,
                "available": True,
                "in_failover_chain": True,
                "is_default": True,
                "is_active": True,
                "selected_model": "models/gemini-embedding-001",
                "selected_dimensions": 768,
                "supports_dimension_override": True,
                "reason_code": None,
                "reason_label": None,
            }
        ],
        runtime_policy_persisted=True,
        runtime_policy_updated_at="2026-03-23T12:00:00+00:00",
        warnings=[],
    )


def test_stream_request_headers_prefer_middleware_request_id():
    request = SimpleNamespace(
        headers={"x-request-id": "caller-header"},
        state=SimpleNamespace(request_id="middleware-trace-id"),
    )

    headers = _stream_request_headers_with_request_id(request)

    assert headers["X-Request-ID"] == "middleware-trace-id"
    assert headers["x-request-id"] == "caller-header"


@pytest.fixture
def smoke_app():
    app = _build_smoke_app()
    yield app
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_llm_status_smoke_returns_selectability_contract(smoke_app):
    snapshot = [
        ProviderSelectability(
            provider="google",
            display_name="Gemini",
            state="disabled",
            reason_code="busy",
            reason_label="Provider tam thoi ban hoac da cham gioi han.",
            selected_model="gemini-3.1-flash-lite-preview",
            strict_pin=True,
            verified_at="2026-03-23T12:00:00+00:00",
            available=False,
            configured=True,
            request_selectable=True,
            is_primary=True,
            is_fallback=False,
        ),
        ProviderSelectability(
            provider="zhipu",
            display_name="GLM-5",
            state="selectable",
            reason_code=None,
            reason_label=None,
            selected_model="glm-5",
            strict_pin=True,
            verified_at="2026-03-23T12:00:00+00:00",
            available=True,
            configured=True,
            request_selectable=True,
            is_primary=False,
            is_fallback=True,
        ),
    ]

    with patch(
        "app.api.v1.llm_status.get_llm_selectability_snapshot",
        return_value=snapshot,
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/v1/llm/status")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["providers"]) == 2
    assert payload["providers"][0]["reason_code"] == "busy"
    assert payload["providers"][1]["state"] == "selectable"
    assert payload["providers"][1]["strict_pin"] is True


@pytest.mark.asyncio
async def test_chat_sync_smoke_success_response(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _student_auth
    internal_response = InternalChatResponse(
        message="Chao ban, minh da xu ly xong.",
        agent_type=AgentType.DIRECT,
        metadata={
            "session_id": "session-1",
            "provider": "google",
            "model": "gemini-3.1-flash-lite-preview",
            "runtime_authoritative": True,
            "failover": {
                "switched": True,
                "switch_count": 1,
                "initial_provider": "google",
                "final_provider": "zhipu",
                "last_reason_code": "auth_error",
                "last_reason_category": "auth_error",
                "last_reason_label": "Xac thuc provider that bai.",
                "route": [
                    {
                        "from_provider": "google",
                        "to_provider": "zhipu",
                        "reason_code": "auth_error",
                        "reason_category": "auth_error",
                        "reason_label": "Xac thuc provider that bai.",
                    }
                ],
            },
        },
    )

    with patch(
        "app.api.v1.chat_completion_endpoint_support.process_chat_completion_request",
        new=AsyncMock(return_value=internal_response),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/chat",
                json={
                    "user_id": "student-123",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "auto",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["answer"] == "Chao ban, minh da xu ly xong."
    assert payload["metadata"]["session_id"] == "session-1"
    assert payload["metadata"]["provider"] == "google"
    assert payload["metadata"]["model"] == "gemini-3.1-flash-lite-preview"
    assert payload["metadata"]["runtime_authoritative"] is True
    assert payload["metadata"]["failover"]["last_reason_code"] == "auth_error"
    assert payload["metadata"]["failover"]["final_provider"] == "zhipu"


@pytest.mark.asyncio
async def test_chat_sync_smoke_preserves_request_model_to_processing_boundary(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _student_auth
    captured: dict[str, object] = {}

    async def _fake_process(*, chat_request, background_save):
        captured["provider"] = chat_request.provider
        captured["model"] = chat_request.model
        return InternalChatResponse(
            message="Da nhan model pin.",
            agent_type=AgentType.DIRECT,
            metadata={
                "session_id": "session-model-sync",
                "provider": "openrouter",
                "model": "qwen/qwen3.6-plus:free",
                "runtime_authoritative": True,
            },
        )

    with patch(
        "app.api.v1.chat_completion_endpoint_support.process_chat_completion_request",
        new=AsyncMock(side_effect=_fake_process),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/chat",
                json={
                    "user_id": "student-123",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "openrouter",
                    "model": "qwen/qwen3.6-plus:free",
                },
            )

    assert response.status_code == 200
    assert captured == {
        "provider": "openrouter",
        "model": "qwen/qwen3.6-plus:free",
    }
    payload = response.json()
    assert payload["metadata"]["provider"] == "openrouter"
    assert payload["metadata"]["model"] == "qwen/qwen3.6-plus:free"


@pytest.mark.asyncio
async def test_admin_embedding_space_promote_smoke(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _admin_auth

    with patch(
        "app.api.v1.admin.promote_embedding_space_shadow",
        return_value=SimpleNamespace(
            to_dict=lambda: {
                "dry_run": False,
                "maintenance_acknowledged": True,
                "current_contract_fingerprint": "ollama:embeddinggemma:768",
                "target_contract_fingerprint": "openai:text-embedding-3-small:1536",
                "target_backend_constructible": True,
                "tables": [],
                "warnings": ["promoted"],
                "detail": "done",
                "recommended_next_steps": ["smoke test"],
            }
        ),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/admin/llm-runtime/embedding-space/promote",
                json={
                    "target_model": "text-embedding-3-small",
                    "target_dimensions": 1536,
                    "acknowledge_maintenance_window": True,
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_contract_fingerprint"] == "openai:text-embedding-3-small:1536"


@pytest.mark.asyncio
async def test_chat_sync_smoke_returns_provider_unavailable_503(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _student_auth

    with patch(
        "app.api.v1.chat_completion_endpoint_support.process_chat_completion_request",
        new=AsyncMock(
            side_effect=ProviderUnavailableError(
                provider="google",
                reason_code="busy",
                message="Provider tam thoi ban hoac da cham gioi han.",
            )
        ),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/chat",
                json={
                    "user_id": "student-123",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "google",
                },
            )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "PROVIDER_UNAVAILABLE"
    assert payload["provider"] == "google"
    assert payload["reason_code"] == "busy"


@pytest.mark.asyncio
async def test_chat_stream_v3_smoke_success_transport(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _student_auth

    async def _fake_stream(*args, **kwargs):
        yield 'event: status\ndata: {"content":"Dang xu ly"}\n\n'
        yield 'event: answer\ndata: {"content":"Chao ban qua SSE"}\n\n'
        yield (
            'event: metadata\n'
            'data: {"session_id":"session-stream","provider":"nvidia",'
            '"model":"deepseek-ai/deepseek-v4-flash",'
            '"runtime_authoritative":true,'
            '"failover":{"switched":false,"initial_provider":"nvidia",'
            '"final_provider":"nvidia"}}\n\n'
        )
        yield 'event: done\ndata: {"processing_time":0.1}\n\n'

    with patch(
        "app.api.v1.chat_stream.generate_stream_v3_events",
        side_effect=_fake_stream,
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/chat/stream/v3",
                json={
                    "user_id": "student-123",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "auto",
                },
            ) as response:
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

    assert response.status_code == 200
    assert "event: status" in body
    assert "event: answer" in body
    assert "Chao ban qua SSE" in body
    assert "event: metadata" in body
    assert '"session_id":"session-stream"' in body
    assert '"provider":"nvidia"' in body
    assert '"model":"deepseek-ai/deepseek-v4-flash"' in body
    assert '"runtime_authoritative":true' in body
    assert '"failover":{"switched":false' in body
    assert '"final_provider":"nvidia"' in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_chat_stream_v3_native_dispatch_persists_runtime_flow_ledger(
    smoke_app,
    monkeypatch,
):
    smoke_app.dependency_overrides[require_auth] = _student_auth
    log = InMemorySessionEventLog()
    ledger = {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "route": {"lane": "casual_chat"},
        "stream": {"done_seen": True, "event_counts": {"done": 1}},
    }

    monkeypatch.setattr(
        "app.core.config.settings.enable_native_stream_dispatch",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.engine.runtime.native_stream_dispatch.get_session_event_log",
        lambda: log,
    )

    async def _fake_stream(*args, **kwargs):
        yield 'event: answer\ndata: {"content":"Chao ban"}\n\n'
        yield (
            "event: done\n"
            f"data: {json.dumps({'runtime_flow_ledger': ledger})}\n\n"
        )

    with patch(
        "app.api.v1.chat_stream.generate_stream_v3_events",
        side_effect=_fake_stream,
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/chat/stream/v3",
                json={
                    "user_id": "student-123",
                    "session_id": "session-native-ledger",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "auto",
                },
            ) as response:
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

    assert response.status_code == 200
    assert "event: done" in body
    events = await log.get_events(session_id="session-native-ledger")
    assert [event.event_type for event in events] == [
        "user_message",
        "assistant_message",
        "runtime_flow_ledger",
    ]
    assert (
        events[2].payload["runtime_flow_ledger"]["route"]["lane"]
        == "casual_chat"
    )


@pytest.mark.asyncio
async def test_chat_stream_v3_smoke_preserves_request_model_to_stream_boundary(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _student_auth
    captured: dict[str, object] = {}

    async def _fake_stream(*, chat_request, request_headers, background_save, start_time, **_kwargs):
        captured["provider"] = chat_request.provider
        captured["model"] = chat_request.model
        yield (
            'event: metadata\n'
            'data: {"provider":"openrouter","model":"qwen/qwen3.6-plus:free"}\n\n'
        )
        yield 'event: done\ndata: {"processing_time":0.1}\n\n'

    with patch(
        "app.api.v1.chat_stream.generate_stream_v3_events",
        side_effect=_fake_stream,
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/chat/stream/v3",
                json={
                    "user_id": "student-123",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "openrouter",
                    "model": "qwen/qwen3.6-plus:free",
                },
            ) as response:
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

    assert response.status_code == 200
    assert captured == {
        "provider": "openrouter",
        "model": "qwen/qwen3.6-plus:free",
    }
    assert '"provider":"openrouter"' in body or '"provider": "openrouter"' in body
    assert '"model":"qwen/qwen3.6-plus:free"' in body or '"model": "qwen/qwen3.6-plus:free"' in body


@pytest.mark.asyncio
async def test_chat_stream_v3_smoke_returns_error_then_done_for_unavailable_provider(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _student_auth

    with patch(
        "app.services.chat_service.get_chat_service",
    ) as mock_get_chat_service, patch(
        "app.services.llm_selectability_service.ensure_provider_is_selectable",
        side_effect=ProviderUnavailableError(
            provider="google",
            reason_code="busy",
            message="Provider tam thoi ban hoac da cham gioi han.",
        ),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            async with client.stream(
                "POST",
                "/api/v1/chat/stream/v3",
                json={
                    "user_id": "student-123",
                    "message": "Xin chao",
                    "role": "student",
                    "provider": "google",
                },
            ) as response:
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk

    assert response.status_code == 200
    assert "event: error" in body
    assert '"provider":"google"' in body or '"provider": "google"' in body
    assert '"reason_code":"busy"' in body or '"reason_code": "busy"' in body
    assert "event: done" in body
    mock_get_chat_service.assert_not_called()


@pytest.mark.asyncio
async def test_admin_llm_runtime_smoke_get(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _admin_auth

    with patch(
        "app.services.llm_runtime_policy_service.get_persisted_llm_runtime_policy",
        return_value=SimpleNamespace(
            payload={"provider": "zhipu"},
            updated_at=SimpleNamespace(isoformat=lambda: "2026-03-23T12:00:00+00:00"),
        ),
    ), patch(
        "app.api.v1.admin._serialize_llm_runtime",
        return_value=_runtime_response(),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/v1/admin/llm-runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "zhipu"
    assert payload["runtime_policy_persisted"] is True


@pytest.mark.asyncio
async def test_admin_vision_runtime_audit_smoke(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _admin_auth

    with patch(
        "app.api.v1.admin.run_live_vision_capability_probes",
        new=AsyncMock(return_value=SimpleNamespace()),
    ) as mock_probe, patch(
        "app.services.llm_runtime_policy_service.get_persisted_llm_runtime_policy",
        return_value=SimpleNamespace(
            payload={"provider": "zhipu"},
            updated_at=SimpleNamespace(isoformat=lambda: "2026-03-23T12:00:00+00:00"),
        ),
    ), patch(
        "app.api.v1.admin._serialize_llm_runtime",
        return_value=_runtime_response(),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/admin/llm-runtime/vision-audit",
                json={"providers": ["google"]},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["vision_audit_persisted"] is True
    mock_probe.assert_awaited_once_with(providers=["google"])


@pytest.mark.asyncio
async def test_admin_llm_runtime_smoke_patch(smoke_app, monkeypatch):
    smoke_app.dependency_overrides[require_auth] = _admin_auth
    monkeypatch.setattr("app.core.config.settings.llm_provider", "google", raising=False)
    monkeypatch.setattr("app.core.config.settings.use_multi_agent", True, raising=False)

    with patch(
        "app.services.llm_runtime_policy_service.snapshot_current_llm_runtime_policy",
        return_value={"provider": "google"},
    ), patch(
        "app.services.llm_runtime_policy_service.persist_current_llm_runtime_policy",
        return_value=SimpleNamespace(
            payload={"provider": "zhipu"},
            updated_at=SimpleNamespace(isoformat=lambda: "2026-03-23T12:00:00+00:00"),
        ),
    ), patch(
        "app.services.llm_runtime_policy_service.redact_llm_runtime_policy_snapshot",
        side_effect=lambda payload: payload,
    ), patch(
        "app.engine.llm_pool.LLMPool.reset",
    ) as mock_pool_reset, patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.initialize",
    ) as mock_agent_init, patch(
        "app.services.chat_service.reset_chat_service",
    ) as mock_reset_chat, patch(
        "app.api.v1.admin._build_model_catalog_response",
        new=AsyncMock(return_value=SimpleNamespace()),
    ), patch(
        "app.api.v1.admin._serialize_llm_runtime",
        return_value=_runtime_response(),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.patch(
                "/api/v1/admin/llm-runtime",
                json={
                    "provider": "zhipu",
                    "use_multi_agent": False,
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "zhipu"
    mock_pool_reset.assert_called_once()
    mock_agent_init.assert_called_once()
    mock_reset_chat.assert_called_once()


@pytest.mark.asyncio
async def test_admin_embedding_space_plan_smoke(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _admin_auth

    with patch(
        "app.api.v1.admin.plan_embedding_space_migration",
        return_value=SimpleNamespace(
            to_dict=lambda: {
                "current_contract_fingerprint": "ollama:embeddinggemma:768",
                "target_contract_fingerprint": "openai:text-embedding-3-small:1536",
                "current_contract_label": "embeddinggemma [ollama, 768d]",
                "target_contract_label": "text-embedding-3-small [openai, 1536d]",
                "same_space": False,
                "transition_allowed": False,
                "target_backend_constructible": True,
                "maintenance_required": True,
                "total_candidate_rows": 64,
                "total_embedded_rows": 64,
                "tables": [
                    {
                        "table_name": "semantic_memories",
                        "candidate_rows": 62,
                        "embedded_rows": 62,
                        "tracked_rows": 62,
                        "untracked_rows": 0,
                    }
                ],
                "warnings": ["Khong the xac nhan shadow index."],
                "recommended_steps": ["Len maintenance window."],
                "detail": "Migration maintenance-only.",
            }
        ),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/admin/llm-runtime/embedding-space/plan",
                json={"target_model": "text-embedding-3-small"},
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_contract_fingerprint"] == "openai:text-embedding-3-small:1536"
    assert payload["maintenance_required"] is True
    assert payload["tables"][0]["candidate_rows"] == 62


@pytest.mark.asyncio
async def test_admin_embedding_space_migrate_smoke(smoke_app):
    smoke_app.dependency_overrides[require_auth] = _admin_auth

    with patch(
        "app.api.v1.admin.migrate_embedding_space_rows",
        return_value=SimpleNamespace(
            to_dict=lambda: {
                "dry_run": True,
                "maintenance_acknowledged": True,
                "current_contract_fingerprint": "ollama:embeddinggemma:768",
                "target_contract_fingerprint": "openai:text-embedding-3-small:1536",
                "target_backend_constructible": True,
                "tables": [
                    {
                        "table_name": "semantic_memories",
                        "candidate_rows": 62,
                        "updated_rows": 0,
                        "skipped_rows": 62,
                        "failed_rows": 0,
                    }
                ],
                "warnings": [],
                "detail": "Dry-run only.",
                "recommended_next_steps": ["Run with maintenance window acknowledged."],
            }
        ),
    ):
        async with httpx.AsyncClient(
            transport=_transport(smoke_app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/admin/llm-runtime/embedding-space/migrate",
                json={
                    "target_model": "text-embedding-3-small",
                    "dry_run": True,
                    "acknowledge_maintenance_window": True,
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["tables"][0]["skipped_rows"] == 62
