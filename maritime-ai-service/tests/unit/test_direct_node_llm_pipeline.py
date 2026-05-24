from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.multi_agent import direct_node_llm_pipeline as module
from app.engine.multi_agent.direct_node_llm_pipeline import (
    DirectNodeLlmPipelineDependencies,
    DirectNodeLlmPipelineRequest,
    execute_direct_node_llm_pipeline,
)


class _Tracer:
    def __init__(self):
        self.end_steps: list[dict[str, object]] = []

    def end_step(self, **kwargs):
        self.end_steps.append(kwargs)


def _turn_policy(**overrides):
    values = {
        "ctx": {"user_role": "student", "response_language": "vi"},
        "response_language": "vi",
        "thinking_effort": None,
        "routing_intent": "general",
        "is_identity_turn": False,
        "is_emotional_support_turn": False,
        "is_short_house_chatter": False,
        "visual_decision": SimpleNamespace(force_tool=False),
        "history_limit": 10,
        "tools_context_override": None,
        "role_name": "direct_agent",
        "preferred_provider": None,
        "explicit_user_provider": None,
        "use_house_voice_direct": False,
        "direct_provider_override": None,
        "is_codebase_source_turn": False,
        "explicit_web_search_turn": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(**overrides):
    values = {
        "query": "Giup minh hoc Hang hai",
        "state": {
            "query": "Giup minh hoc Hang hai",
            "context": {"user_role": "student", "response_language": "vi"},
        },
        "bus_id": "bus-1",
        "push_event": lambda *_args, **_kwargs: None,
        "tracer": _Tracer(),
        "ctx_for_preflight": {"user_role": "student", "response_language": "vi"},
        "has_uploaded_document_context": False,
        "domain_name_vi": "Hang hai",
        "sanitize_document_preview_response": lambda text, *_args, **_kwargs: text,
        "explicit_web_search_turn": False,
        "enable_natural_conversation": True,
        "requested_model": None,
        "llm_presence_penalty": 0.0,
        "llm_frequency_penalty": 0.0,
        "direct_max_rounds": 12,
        "host_ui_total_timeout_seconds": 45.0,
    }
    values.update(overrides)
    return DirectNodeLlmPipelineRequest(**values)


def _dependencies(**overrides):
    values = {
        "normalize_for_intent": lambda text: text.lower(),
        "looks_identity_selfhood_turn": lambda _text: False,
        "needs_web_search": lambda _text: False,
        "needs_datetime": lambda _text: False,
        "resolve_visual_intent": lambda _text: SimpleNamespace(force_tool=False),
        "recommended_visual_thinking_effort": lambda *_args, **_kwargs: None,
        "get_active_code_studio_session": lambda _state: None,
        "merge_thinking_effort": lambda current, other: other or current,
        "get_effective_provider": lambda _state: None,
        "get_explicit_user_provider": lambda _state: None,
        "collect_direct_tools": lambda *_args, **_kwargs: ([], False),
        "direct_required_tool_names": lambda *_args, **_kwargs: [],
        "resolve_direct_answer_timeout_profile": lambda **_kwargs: None,
        "bind_direct_tools": lambda *_args, **_kwargs: (object(), object(), None),
        "build_direct_system_messages": lambda *_args, **_kwargs: [],
        "build_visual_tool_runtime_metadata": lambda *_args, **_kwargs: {},
        "execute_direct_tool_rounds": lambda *_args, **_kwargs: None,
        "extract_direct_response": lambda *_args, **_kwargs: ("", "", []),
        "sanitize_structured_visual_answer_text": lambda text, *_args, **_kwargs: text,
        "sanitize_wiii_house_text": lambda text, *_args, **_kwargs: text,
        "build_direct_reasoning_summary": lambda *_args, **_kwargs: "",
        "get_phase_fallback": lambda _state: "Fallback tu phase.",
        "record_thinking_snapshot_fn": lambda *_args, **_kwargs: None,
        "logger_obj": MagicMock(),
    }
    values.update(overrides)
    return DirectNodeLlmPipelineDependencies(**values)


@pytest.mark.asyncio
async def test_execute_direct_node_llm_pipeline_returns_typed_unavailable_fallback(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "resolve_direct_node_turn_policy",
        lambda **_kwargs: _turn_policy(),
    )
    monkeypatch.setattr(
        module,
        "select_direct_node_tools",
        lambda **_kwargs: SimpleNamespace(tools=[], force_tools=False),
    )
    monkeypatch.setattr(
        module,
        "prepare_direct_node_llm_preflight",
        lambda **_kwargs: SimpleNamespace(llm=None, response=""),
    )
    monkeypatch.setattr(
        module,
        "resolve_direct_node_llm_unavailable_fallback",
        lambda **_kwargs: SimpleNamespace(
            response="Fallback co contract.",
            response_type="fallback",
        ),
    )

    request = _request()
    result = await execute_direct_node_llm_pipeline(
        request=request,
        dependencies=_dependencies(),
    )

    assert result.response == "Fallback co contract."
    assert result.tool_call_events == []
    assert request.tracer.end_steps == [
        {
            "result": "Fallback (LLM unavailable)",
            "confidence": 0.5,
            "details": {"response_type": "fallback"},
        }
    ]


@pytest.mark.asyncio
async def test_execute_direct_node_llm_pipeline_runs_tool_loop_with_typed_inputs(
    monkeypatch,
):
    llm = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        module,
        "resolve_direct_node_turn_policy",
        lambda **_kwargs: _turn_policy(
            preferred_provider="qwen",
            direct_provider_override="qwen",
        ),
    )
    monkeypatch.setattr(
        module,
        "select_direct_node_tools",
        lambda **_kwargs: SimpleNamespace(
            tools=[SimpleNamespace(name="tool_knowledge_search")],
            force_tools=True,
        ),
    )
    monkeypatch.setattr(
        module,
        "prepare_direct_node_llm_preflight",
        lambda **_kwargs: SimpleNamespace(llm=llm, response=""),
    )

    async def _execute_tool_loop(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            response="Da tra loi bang LLM.",
            messages=["system", "assistant"],
            tool_call_events=[{"name": "tool_knowledge_search", "status": "ok"}],
            force_tools=True,
        )

    monkeypatch.setattr(module, "execute_direct_node_llm_tool_loop", _execute_tool_loop)
    monkeypatch.setattr(
        module,
        "resolve_direct_node_llm_unavailable_fallback",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("fallback must not run when LLM exists")
        ),
    )

    request = _request(direct_max_rounds=9, host_ui_total_timeout_seconds=30.0)
    result = await execute_direct_node_llm_pipeline(
        request=request,
        dependencies=_dependencies(),
    )

    assert result.response == "Da tra loi bang LLM."
    assert result.tool_call_events == [
        {"name": "tool_knowledge_search", "status": "ok"}
    ]
    assert captured["llm"] is llm
    assert captured["force_tools"] is True
    assert captured["preferred_provider"] == "qwen"
    assert captured["direct_max_rounds"] == 9
    assert captured["host_ui_total_timeout_seconds"] == 30.0
