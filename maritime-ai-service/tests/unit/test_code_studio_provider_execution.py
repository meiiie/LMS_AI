from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.multi_agent.code_studio_provider_execution import (
    CodeStudioProviderExecutionDependencies,
    CodeStudioProviderExecutionRequest,
    execute_code_studio_provider_execution,
)


class _FakeLlm:
    _wiii_provider_name = "qwen"
    _wiii_model_name = "qwen3-next"

    def bind(self, **kwargs):
        return SimpleNamespace(
            _wiii_provider_name=self._wiii_provider_name,
            _wiii_model_name=self._wiii_model_name,
            bound_penalties=kwargs,
        )


def _request(**overrides):
    values = {
        "effective_query": "Tao mo phong COLREG",
        "state": {
            "query": "Tao mo phong COLREG",
            "provider": "qwen",
            "context": {"user_role": "teacher"},
        },
        "ctx": {"user_role": "teacher"},
        "domain_name_vi": "Hang hai",
        "explicit_provider": "qwen",
        "tools": [SimpleNamespace(name="tool_create_visual_code")],
        "force_tools": True,
        "runtime_context_base": {"request_id": "req-1"},
        "event_queue_present": False,
        "push_event": lambda *_args, **_kwargs: None,
        "settings_obj": SimpleNamespace(
            enable_natural_conversation=True,
            llm_presence_penalty=0.1,
            llm_frequency_penalty=0.2,
        ),
        "requested_model": None,
    }
    values.update(overrides)
    return CodeStudioProviderExecutionRequest(**values)


def _dependencies(**overrides):
    calls: dict[str, object] = {}

    def bind_direct_tools(llm, tools, force_tools, **kwargs):
        calls["bound_llm"] = llm
        calls["bind_kwargs"] = kwargs
        return "llm-with-tools", "llm-auto", "tool_create_visual_code"

    async def execute_code_studio_tool_rounds(*args, **kwargs):
        calls["tool_round_args"] = args
        calls["tool_round_kwargs"] = kwargs
        return (
            SimpleNamespace(content="raw tool response"),
            ["system", "assistant"],
            [{"name": "tool_create_visual_code", "status": "ok"}],
        )

    def extract_direct_response(response, _messages):
        content = getattr(response, "content", "")
        if content == "summary response":
            return "Summary da stream.", "", []
        return "Raw da tao preview.", "", ["tool_create_visual_code"]

    async def build_code_studio_reasoning_summary(*_args, **_kwargs):
        return "Minh dang giu preview that va tranh template chung chung."

    values = {
        "bind_direct_tools": bind_direct_tools,
        "build_direct_system_messages": lambda *_args, **_kwargs: ["system"],
        "build_code_studio_tools_context": lambda *_args, **_kwargs: "tools context",
        "execute_code_studio_tool_rounds": execute_code_studio_tool_rounds,
        "extract_direct_response": extract_direct_response,
        "build_code_studio_stream_summary_messages": (
            lambda *_args, **_kwargs: ["summary system"]
        ),
        "stream_answer_with_fallback": lambda *_args, **_kwargs: None,
        "sanitize_code_studio_response": lambda text, *_args, **_kwargs: text.strip(),
        "build_code_studio_reasoning_summary": build_code_studio_reasoning_summary,
        "direct_tool_names": lambda tools: [str(tool) for tool in tools],
        "logger_obj": MagicMock(),
        "get_agent_llm": lambda *_args, **_kwargs: _FakeLlm(),
        "get_summary_llm_for_provider": lambda *_args, **_kwargs: "summary-llm",
        "record_thinking_snapshot_fn": lambda *_args, **_kwargs: calls.setdefault(
            "snapshot_recorded",
            True,
        ),
        "resolve_visible_thinking_fn": (
            lambda _state, *, fallback, default_node: f"{default_node}: {fallback}"
        ),
    }
    values.update(overrides)
    return CodeStudioProviderExecutionDependencies(**values), calls


@pytest.mark.asyncio
async def test_execute_code_studio_provider_execution_returns_typed_result():
    request = _request()
    dependencies, calls = _dependencies()

    result = await execute_code_studio_provider_execution(
        request=request,
        dependencies=dependencies,
    )

    assert result.response == "Raw da tao preview."
    assert result.tool_call_events == [
        {"name": "tool_create_visual_code", "status": "ok"}
    ]
    assert result.tools_used == ["tool_create_visual_code"]
    assert result.streamed_delivery is False
    assert result.bound_provider == "qwen"
    assert result.bound_model == "qwen3-next"
    assert request.state["_execution_provider"] == "qwen"
    assert request.state["_execution_model"] == "qwen3-next"
    assert request.state["model"] == "qwen3-next"
    assert request.state["tool_call_events"] == result.tool_call_events
    assert request.state["tools_used"] == ["tool_create_visual_code"]
    assert "code_studio_agent:" in request.state["thinking_content"]
    assert calls["snapshot_recorded"] is True
    assert calls["bind_kwargs"]["provider"] == "qwen"
    assert calls["tool_round_kwargs"]["runtime_provider"] == "qwen"
    assert calls["tool_round_kwargs"]["forced_tool_choice"] == "tool_create_visual_code"


@pytest.mark.asyncio
async def test_execute_code_studio_provider_execution_uses_streamed_summary():
    summary_calls: dict[str, object] = {}

    async def stream_answer_with_fallback(llm, messages, push_event, **kwargs):
        summary_calls["llm"] = llm
        summary_calls["messages"] = messages
        summary_calls["kwargs"] = kwargs
        summary_calls["push_event"] = push_event
        return SimpleNamespace(content="summary response"), True

    def get_summary_llm_for_provider(provider, **kwargs):
        summary_calls["provider"] = provider
        summary_calls["summary_kwargs"] = kwargs
        return "summary-llm"

    dependencies, _calls = _dependencies(
        stream_answer_with_fallback=stream_answer_with_fallback,
        get_summary_llm_for_provider=get_summary_llm_for_provider,
    )

    result = await execute_code_studio_provider_execution(
        request=_request(event_queue_present=True),
        dependencies=dependencies,
    )

    assert result.response == "Summary da stream."
    assert result.streamed_delivery is True
    assert summary_calls["provider"] == "qwen"
    assert summary_calls["llm"] == "summary-llm"
    assert summary_calls["messages"] == ["summary system"]
    assert summary_calls["kwargs"]["provider"] == "qwen"
    assert summary_calls["kwargs"]["node"] == "code_studio_agent"
    assert summary_calls["summary_kwargs"]["strict_pin"] is True


@pytest.mark.asyncio
async def test_execute_code_studio_provider_execution_fails_when_llm_missing():
    dependencies, _calls = _dependencies(get_agent_llm=lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="provider returned no LLM"):
        await execute_code_studio_provider_execution(
            request=_request(),
            dependencies=dependencies,
        )
