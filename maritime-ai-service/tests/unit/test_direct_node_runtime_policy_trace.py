from types import SimpleNamespace

import pytest


class _FakeTracer:
    def start_step(self, *_args, **_kwargs):
        return None

    def end_step(self, *_args, **_kwargs):
        return None


def _unused_async(*_args, **_kwargs):
    raise AssertionError("LLM/tool path should not run for this fast response")


def _direct_node_kwargs():
    return {
        "direct_response_step_name": "direct",
        "get_or_create_tracer": lambda _state: _FakeTracer(),
        "capture_public_thinking_event": lambda *_args, **_kwargs: None,
        "get_domain_greetings": lambda _domain: {},
        "normalize_for_intent": lambda text: str(text).lower(),
        "looks_identity_selfhood_turn": lambda _query: False,
        "needs_web_search": lambda _query: False,
        "needs_datetime": lambda _query: False,
        "resolve_visual_intent": lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            presentation_intent="text",
        ),
        "recommended_visual_thinking_effort": lambda *_args, **_kwargs: None,
        "get_active_code_studio_session": lambda _state: None,
        "merge_thinking_effort": lambda base, recommended: recommended or base,
        "get_effective_provider": lambda _state: None,
        "get_explicit_user_provider": lambda _state: None,
        "collect_direct_tools": lambda *_args, **_kwargs: ([], False),
        "direct_required_tool_names": lambda _query, _role: [],
        "resolve_direct_answer_timeout_profile": lambda *_args, **_kwargs: None,
        "bind_direct_tools": lambda *_args, **_kwargs: (None, None, None),
        "build_direct_system_messages": lambda *_args, **_kwargs: [],
        "build_visual_tool_runtime_metadata": lambda *_args, **_kwargs: {},
        "execute_direct_tool_rounds": _unused_async,
        "extract_direct_response": lambda *_args, **_kwargs: ("", "", []),
        "sanitize_structured_visual_answer_text": lambda text, **_kwargs: text,
        "sanitize_wiii_house_text": lambda text, **_kwargs: text,
        "build_direct_reasoning_summary": lambda *_args, **_kwargs: "",
        "direct_tool_names": lambda _tools: [],
        "should_surface_direct_thinking": lambda *_args, **_kwargs: False,
        "resolve_public_thinking_content": lambda _state, fallback="": fallback,
        "get_phase_fallback": lambda _state: "",
    }


@pytest.mark.asyncio
async def test_direct_node_fast_response_keeps_connection_status_trace(monkeypatch):
    from app.engine.multi_agent import direct_node_runtime as module
    from app.engine.multi_agent.runtime_flow_ledger import (
        build_runtime_flow_trace_from_state,
    )

    async def fake_pre_llm_pipeline(*_args, **_kwargs):
        return SimpleNamespace(
            response="Facebook chưa agent-ready.",
            response_type="wiii_connect_provider_status",
            explicit_web_search_turn=False,
            ctx_for_preflight={},
            has_uploaded_document_context=False,
            domain_name_vi="Hàng hải",
            sanitize_document_preview_response=lambda text, _events: text,
        )

    monkeypatch.setattr(
        module,
        "execute_direct_node_pre_llm_pipeline",
        fake_pre_llm_pipeline,
    )
    monkeypatch.setattr(
        module,
        "execute_direct_node_llm_pipeline",
        _unused_async,
    )

    state = {
        "query": "Wiii co ket noi duoc facebook khong?",
        "context": {"user_role": "student"},
        "routing_metadata": {"intent": "off_topic"},
    }

    result = await module.direct_response_node_impl(state, **_direct_node_kwargs())

    trace = build_runtime_flow_trace_from_state(result)

    assert result["final_response"] == "Facebook chưa agent-ready."
    assert trace["turn_path_decision"]["path"] == "external_connection_status"
    assert trace["turn_path_decision"]["bind_tools"] is False
    assert trace["tool_policy_session"]["path"] == "external_connection_status"
    assert trace["tool_policy_session"]["visible_tool_names"] == []


@pytest.mark.asyncio
async def test_direct_node_provider_no_tool_turn_keeps_policy_trace(monkeypatch):
    from app.engine.multi_agent import direct_node_runtime as module
    from app.engine.multi_agent.runtime_flow_ledger import (
        build_runtime_flow_trace_from_state,
    )

    async def fake_pre_llm_pipeline(*_args, **_kwargs):
        return SimpleNamespace(
            response=None,
            response_type="",
            explicit_web_search_turn=False,
            ctx_for_preflight={},
            has_uploaded_document_context=False,
            domain_name_vi="Hàng hải",
            sanitize_document_preview_response=lambda text, _events: text,
        )

    async def fake_llm_pipeline(*_args, **_kwargs):
        return SimpleNamespace(response="Chào cậu.", tool_call_events=[])

    monkeypatch.setattr(
        module,
        "execute_direct_node_pre_llm_pipeline",
        fake_pre_llm_pipeline,
    )
    monkeypatch.setattr(
        module,
        "execute_direct_node_llm_pipeline",
        fake_llm_pipeline,
    )

    state = {
        "query": "xin chao Wiii",
        "context": {"user_role": "student"},
        "routing_metadata": {"intent": "social"},
    }

    result = await module.direct_response_node_impl(state, **_direct_node_kwargs())
    trace = build_runtime_flow_trace_from_state(result)

    assert result["final_response"] == "Chào cậu."
    assert trace["turn_path_decision"]["path"] == "casual_chat"
    assert trace["tool_policy_session"]["path"] == "casual_chat"
    assert trace["tool_policy_session"]["visible_tool_names"] == []
