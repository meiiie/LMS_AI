import json
from types import SimpleNamespace

import pytest

from app.engine.multi_agent.graph_stream_runtime import (
    build_stream_bootstrap_impl,
    emit_stream_finalization_impl,
)
from app.engine.llm_runtime_metadata import resolve_runtime_llm_metadata
from app.engine.multi_agent.graph_process import _build_process_result_payload
from app.engine.reasoning import capture_thinking_lifecycle_event
from app.engine.multi_agent.stream_utils import (
    create_done_event,
    create_metadata_event,
    create_sources_event,
)


class _RegistryStub:
    def end_request_trace(self, trace_id: str):
        return {"trace_id": trace_id, "span_count": 0}


@pytest.mark.asyncio
async def test_build_stream_bootstrap_matches_sync_context_injection(monkeypatch):
    import app.engine.multi_agent.graph_runtime_bindings as runtime_bindings

    def _inject_host_context(state):
        state["host_capabilities_prompt"] = "HOST CAPS"
        return "HOST PROMPT"

    monkeypatch.setattr(runtime_bindings, "_inject_host_context", _inject_host_context)
    monkeypatch.setattr(runtime_bindings, "_inject_host_session", lambda _state: "HOST SESSION")
    monkeypatch.setattr(runtime_bindings, "_inject_operator_context", lambda _state: "OPERATOR PROMPT")
    monkeypatch.setattr(runtime_bindings, "_inject_living_context", lambda _state: "LIVING PROMPT")
    monkeypatch.setattr(runtime_bindings, "_inject_visual_context", lambda _state: "")
    monkeypatch.setattr(runtime_bindings, "_inject_visual_cognition_context", lambda _state: "")
    monkeypatch.setattr(runtime_bindings, "_inject_widget_feedback_context", lambda _state: "")
    monkeypatch.setattr(runtime_bindings, "_inject_code_studio_context", lambda _state: "")

    bootstrap = await build_stream_bootstrap_impl(
        query="hello",
        user_id="user-1",
        session_id="session-1",
        context={"organization_id": "org-1"},
        domain_id="maritime",
        thinking_effort="medium",
        provider="google",
        settings_obj=SimpleNamespace(enable_preview=False, enable_soul_emotion=False),
        register_event_queue=lambda *_args, **_kwargs: None,
        cleanup_stale_queues=lambda: None,
        build_domain_config=lambda _domain_id: {},
        build_turn_local_state_defaults=lambda _context: {},
    )

    initial_state = bootstrap["initial_state"]
    assert initial_state["host_context_prompt"] == "HOST PROMPT"
    assert initial_state["host_capabilities_prompt"] == "HOST CAPS"
    assert initial_state["host_session_prompt"] == "HOST SESSION"
    assert initial_state["operator_context_prompt"] == "OPERATOR PROMPT"
    assert initial_state["living_context_prompt"] == "LIVING PROMPT"


@pytest.mark.asyncio
async def test_emit_stream_finalization_prefers_public_thinking_fragments():
    final_state = {
        "session_id": "session-1",
        "grader_score": 8.0,
        "thinking": "native private thinking",
        "thinking_content": "Nhịp này không cần kéo dài quá tay.",
        "_public_thinking_fragments": [
            "Mình đang gom các biến số thị trường quan trọng trước.",
            "Sau đó mình đối chiếu cung cầu với yếu tố địa chính trị để tránh nhận định bề mặt.",
        ],
        "routing_metadata": {"final_agent": "direct"},
    }

    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            session_id="session-1",
            context={"user_id": "user-1"},
            start_time=0.0,
            resolve_runtime_llm_metadata=lambda *_args, **_kwargs: {
                "provider": "google",
                "model": "gemini-3.1-flash-lite-preview",
                "runtime_authoritative": True,
            },
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-1",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    expected_thinking = (
        "Mình đang gom các biến số thị trường quan trọng trước.\n\n"
        "Sau đó mình đối chiếu cung cầu với yếu tố địa chính trị để tránh nhận định bề mặt."
    )
    assert metadata_event.content["thinking"] == expected_thinking
    assert metadata_event.content["thinking_content"] == expected_thinking
    assert metadata_event.content["thinking_lifecycle"]["final_text"] == expected_thinking
    assert "native private thinking" not in json.dumps(
        metadata_event.to_dict(),
        ensure_ascii=False,
    )
    assert events[-1].type == "done"


@pytest.mark.asyncio
async def test_emit_stream_finalization_sanitizes_public_metadata_payload():
    final_state = {
        "session_id": "session-metadata-safe",
        "grader_score": 8.0,
        "thinking": "Bearer raw-private-thinking-token-12345678",
        "_public_thinking_fragments": ["safe public thinking"],
        "routing_metadata": {
            "final_agent": "direct",
            "access_token": "raw-routing-token-123456",
            "safe": "ok",
        },
        "evidence_images": [
            {
                "label": "screen",
                "image_base64": "raw-image-payload",
            }
        ],
        "_runtime_latency": {
            "elapsed_ms": 10,
            "timeline": [
                {
                    "stage": "runtime_step",
                    "access_token": "raw-latency-token-123456",
                }
            ],
        },
    }

    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            session_id="session-metadata-safe",
            context={"user_id": "user-metadata-safe"},
            start_time=0.0,
            resolve_runtime_llm_metadata=lambda *_args, **_kwargs: {
                "provider": "google",
                "model": "gemini-3.1-flash-lite-preview",
                "runtime_authoritative": True,
            },
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-metadata-safe",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    metadata = metadata_event.content
    serialized = json.dumps(metadata, ensure_ascii=False)

    assert metadata["thinking"] == "safe public thinking"
    assert metadata["routing_metadata"]["safe"] == "ok"
    assert "access_token" not in metadata["routing_metadata"]
    assert "image_base64" not in metadata["evidence_images"][0]
    assert "raw-private-thinking-token" not in serialized
    assert "raw-routing-token" not in serialized
    assert "raw-image-payload" not in serialized
    assert "raw-latency-token" not in serialized


@pytest.mark.asyncio
async def test_emit_stream_finalization_falls_back_to_existing_thinking_content():
    final_state = {
        "session_id": "session-2",
        "grader_score": 7.0,
        "thinking_content": "Đây là thinking content cuối cùng đã có sẵn.",
        "routing_metadata": {"final_agent": "rag_agent"},
    }

    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            session_id="session-2",
            context={"user_id": "user-2"},
            start_time=0.0,
            resolve_runtime_llm_metadata=lambda *_args, **_kwargs: {
                "provider": "google",
                "model": "gemini-3.1-flash-lite-preview",
                "runtime_authoritative": True,
            },
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-2",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    assert metadata_event.content["thinking_content"] == "Đây là thinking content cuối cùng đã có sẵn."


@pytest.mark.asyncio
async def test_emit_stream_finalization_merges_bus_lifecycle_from_initial_state():
    initial_state = {
        "session_id": "session-merge",
        "context": {"user_id": "user-merge"},
        "routing_metadata": {"final_agent": "tutor"},
    }
    capture_thinking_lifecycle_event(
        initial_state,
        {
            "type": "thinking_start",
            "content": "Phan tich quy tac",
            "node": "tutor_agent",
            "summary": "Dang chot diem neo truoc khi giai thich.",
        },
    )
    capture_thinking_lifecycle_event(
        initial_state,
        {
            "type": "thinking_delta",
            "content": "Minh dang chot diem neo ve Rule 15 truoc khi mo loi giai thich.",
            "node": "tutor_agent",
        },
    )
    capture_thinking_lifecycle_event(
        initial_state,
        {
            "type": "thinking_end",
            "content": "",
            "node": "tutor_agent",
        },
    )

    final_state = {
        "session_id": "session-merge",
        "grader_score": 9.0,
        "routing_metadata": {"final_agent": "tutor"},
    }

    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            initial_state=initial_state,
            session_id="session-merge",
            context={"user_id": "user-merge"},
            start_time=0.0,
            resolve_runtime_llm_metadata=lambda *_args, **_kwargs: {
                "provider": "google",
                "model": "gemini-3.1-flash-lite-preview",
                "runtime_authoritative": True,
            },
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-merge",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    lifecycle = metadata_event.content["thinking_lifecycle"]

    assert metadata_event.content["thinking_content"] == (
        "Minh dang chot diem neo ve Rule 15 truoc khi mo loi giai thich."
    )
    assert lifecycle["final_text"] == metadata_event.content["thinking_content"]
    assert lifecycle["live_length"] == len(metadata_event.content["thinking_content"])
    assert "live_native" in lifecycle["provenance_mix"]


@pytest.mark.asyncio
async def test_emit_stream_finalization_matches_sync_runtime_metadata_contract():
    final_state = {
        "session_id": "session-provider",
        "grader_score": 8.0,
        "final_response": "ok",
        "sources": [],
        "thinking_content": "Runtime metadata parity check.",
        "provider": "google",
        "model": "gemini-3.1-flash-lite-preview",
        "_execution_provider": "zhipu",
        "_execution_model": "glm-5",
        "_llm_failover_events": [
            {
                "from_provider": "google",
                "to_provider": "zhipu",
                "reason_code": "rate_limit",
                "reason_category": "rate_limit",
                "reason_label": "Gemini quota",
            }
        ],
        "routing_metadata": {"final_agent": "direct"},
    }

    sync_payload = _build_process_result_payload(
        result=final_state,
        trace_id="trace-sync",
        trace_summary={"span_count": 0},
        tracker=None,
        resolve_public_thinking_content=lambda state, fallback="": fallback,
    )
    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            session_id="session-provider",
            context={
                "user_id": "user-provider",
                "organization_id": "org-1",
                "request_id": "req-1",
            },
            start_time=0.0,
            resolve_runtime_llm_metadata=resolve_runtime_llm_metadata,
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-stream",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    stream_metadata = metadata_event.content

    assert stream_metadata["provider"] == sync_payload["provider"] == "zhipu"
    assert stream_metadata["model"] == sync_payload["model"] == "glm-5"
    assert stream_metadata["runtime_authoritative"] is True
    assert stream_metadata["failover"] == sync_payload["failover"]
    assert stream_metadata["failover"]["switched"] is True
    assert stream_metadata["failover"]["final_provider"] == "zhipu"
    assert stream_metadata["failover"]["last_reason_code"] == "rate_limit"
    assert stream_metadata["routing_metadata"] == sync_payload["routing_metadata"]
    assert stream_metadata["agent_type"] == "direct"
    assert stream_metadata["request_id"] == "req-1"
    assert "org-1" in stream_metadata["thread_id"]
    assert "user-provider" in stream_metadata["thread_id"]
    assert "session-provider" in stream_metadata["thread_id"]
    assert events[-1].type == "done"


def test_sync_process_payload_includes_sanitized_runtime_flow_trace() -> None:
    final_state = {
        "session_id": "session-sync-trace",
        "grader_score": 8.0,
        "final_response": "Posted.",
        "_turn_path_decision": {
            "version": "turn_path_decision.v1",
            "path": "external_app_action",
            "reason": "facebook_post_request",
        },
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "external_app_action",
            "reason": "facebook_post_request",
            "visible_tool_names": [
                "host_action__wiii_connect__facebook_post__direct_apply"
            ],
        },
        "_final_answer_trace": {
            "version": "final_answer_trace.v1",
            "source": "wiii_connect_action_result",
            "reason": "external_app_action_payload",
            "status": "resolved",
            "answer_present": True,
        },
        "tool_call_events": [
            {
                "type": "result",
                "name": "host_action__wiii_connect__facebook_post__direct_apply",
                "result": json.dumps(
                    {
                        "version": "wiii_connect_facebook_direct_tool.v1",
                        "status": "action_completed",
                        "success": True,
                        "provider_slug": "facebook",
                        "action": "wiii_connect.facebook_post.direct_apply",
                        "summary": "Posted.",
                        "data": {
                            "access_token": "raw-provider-token",
                            "provider_payload": {"id": "raw"},
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    }

    payload = _build_process_result_payload(
        result=final_state,
        trace_id="trace-sync-runtime-flow",
        trace_summary={"span_count": 0},
        tracker=None,
        resolve_public_thinking_content=lambda state, fallback="": fallback,
    )

    trace = payload["runtime_flow_trace"]
    assert trace["turn_path_decision"]["path"] == "external_app_action"
    assert trace["external_action_trace"]["last_status"] == "action_completed"
    assert trace["final_answer"]["source"] == "wiii_connect_action_result"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "raw-provider-token" not in serialized
    assert "provider_payload" not in serialized


@pytest.mark.asyncio
async def test_emit_stream_finalization_includes_runtime_latency_timeline():
    runtime_latency = {
        "elapsed_ms": 42,
        "timeline": [
            {
                "stage": "runtime_step",
                "node": "supervisor",
                "status": "ok",
                "started_ms": 3,
                "duration_ms": 17,
            },
            {
                "stage": "runtime_route",
                "from": "supervisor",
                "to": "direct",
                "status": "ok",
                "elapsed_ms": 21,
            },
        ],
    }
    final_state = {
        "session_id": "session-latency",
        "grader_score": 8.0,
        "final_response": "ok",
        "routing_metadata": {"final_agent": "direct"},
        "_runtime_latency": runtime_latency,
    }

    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            session_id="session-latency",
            context={"user_id": "user-latency"},
            start_time=0.0,
            resolve_runtime_llm_metadata=lambda *_args, **_kwargs: {
                "provider": "nvidia",
                "model": "deepseek-ai/deepseek-v4-flash",
                "runtime_authoritative": True,
            },
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-latency",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    assert metadata_event.content["runtime_latency"] == runtime_latency


@pytest.mark.asyncio
async def test_emit_stream_finalization_includes_runtime_flow_trace() -> None:
    final_state = {
        "session_id": "session-trace",
        "grader_score": 8.0,
        "final_response": "Posted.",
        "routing_metadata": {"final_agent": "direct"},
        "_turn_path_decision": {
            "version": "turn_path_decision.v1",
            "path": "external_app_action",
            "reason": "facebook_post_request",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
        },
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "external_app_action",
            "reason": "facebook_post_request",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "visible_tool_names": [
                "host_action__wiii_connect__facebook_post__direct_apply"
            ],
        },
        "_external_app_action_plan": {
            "version": "external_app_action_plan.v1",
            "status": "ready",
            "kind": "facebook_post_direct_apply",
            "provider_slug": "facebook",
            "action_slug": "wiii_connect.facebook_post.direct_apply",
        },
        "_external_app_integration_lane": {
            "version": "external_app_integration_lane.v1",
            "status": "ready",
            "executor": "specialized_direct_tool",
            "provider_slug": "facebook",
            "visible_tool_names": [
                "host_action__wiii_connect__facebook_post__direct_apply"
            ],
        },
        "_final_answer_trace": {
            "version": "final_answer_trace.v1",
            "source": "wiii_connect_action_result",
            "reason": "external_app_action_payload",
            "status": "resolved",
            "answer_present": True,
        },
        "tool_call_events": [
            {
                "type": "result",
                "name": "host_action__wiii_connect__facebook_post__direct_apply",
                "result": (
                    '{"version":"wiii_connect_facebook_direct_tool.v1",'
                    '"status":"action_completed","success":true,'
                    '"provider_slug":"facebook",'
                    '"action":"wiii_connect.facebook_post.direct_apply",'
                    '"summary":"Posted.","access_token":"raw-token"}'
                ),
            }
        ],
    }

    events = [
        event
        async for event in emit_stream_finalization_impl(
            final_state=final_state,
            session_id="session-trace",
            context={"user_id": "user-trace"},
            start_time=0.0,
            resolve_runtime_llm_metadata=lambda *_args, **_kwargs: {
                "provider": "nvidia",
                "model": "qwen/qwen3-next-80b-a3b-instruct",
                "runtime_authoritative": True,
            },
            create_sources_event=create_sources_event,
            create_metadata_event=create_metadata_event,
            create_done_event=create_done_event,
            registry=_RegistryStub(),
            trace_id="trace-runtime-flow",
        )
    ]

    metadata_event = next(event for event in events if event.type == "metadata")
    trace = metadata_event.content["runtime_flow_trace"]

    assert trace["turn_path_decision"]["path"] == "external_app_action"
    assert trace["tool_policy_session"]["visible_tool_names"] == [
        "host_action__wiii_connect__facebook_post__direct_apply"
    ]
    assert trace["external_app_action_plan"]["provider_slug"] == "facebook"
    assert trace["external_app_integration_lane"]["executor"] == (
        "specialized_direct_tool"
    )
    assert trace["external_action_trace"]["last_status"] == "action_completed"
    assert trace["final_answer"]["source"] == "wiii_connect_action_result"
    assert "raw-token" not in str(trace)
