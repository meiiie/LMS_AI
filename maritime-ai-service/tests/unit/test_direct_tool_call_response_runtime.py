import logging
from types import SimpleNamespace

from app.engine.multi_agent.direct_tool_call_response_runtime import (
    prepare_direct_tool_call_response,
)


def test_prepare_direct_tool_call_response_converts_raw_text_tool_call() -> None:
    raw_calls = [{"name": "tool_demo", "args": {"query": "x"}, "id": "call-1"}]
    captured: dict = {}

    def extract_raw(content, *, allowed_tool_names):
        captured["content"] = content
        captured["allowed_tool_names"] = allowed_tool_names
        return raw_calls

    def build_message(tool_calls, **kwargs):
        captured["native_tool_messages"] = kwargs["native_tool_messages"]
        return SimpleNamespace(content="", tool_calls=tool_calls)

    response = prepare_direct_tool_call_response(
        llm_response=SimpleNamespace(
            content='{"name":"tool_demo","arguments":{"query":"x"}}',
            tool_calls=[],
        ),
        tools=[object()],
        native_tool_messages=True,
        extract_raw_tool_calls_from_text=extract_raw,
        tool_names_from_tools=lambda tools: ["tool_demo"],
        build_assistant_tool_call_message=build_message,
        logger_obj=logging.getLogger(__name__),
    )

    assert response.llm_response.tool_calls == raw_calls
    assert response.tool_calls == raw_calls
    assert captured == {
        "content": '{"name":"tool_demo","arguments":{"query":"x"}}',
        "allowed_tool_names": ["tool_demo"],
        "native_tool_messages": True,
    }


def test_prepare_direct_tool_call_response_keeps_structured_tool_calls() -> None:
    structured_calls = [{"name": "tool_demo", "args": {}, "id": "call-1"}]

    response = prepare_direct_tool_call_response(
        llm_response=SimpleNamespace(content="", tool_calls=structured_calls),
        tools=[object()],
        native_tool_messages=False,
        extract_raw_tool_calls_from_text=lambda *args, **kwargs: [],
        tool_names_from_tools=lambda tools: ["tool_demo"],
        build_assistant_tool_call_message=lambda *args, **kwargs: None,
        logger_obj=logging.getLogger(__name__),
    )

    assert response.llm_response.tool_calls == structured_calls
    assert response.tool_calls == structured_calls


def test_prepare_direct_tool_call_response_skips_raw_parse_without_tools() -> None:
    parsed = False

    def extract_raw(*args, **kwargs):
        nonlocal parsed
        parsed = True
        return []

    response = prepare_direct_tool_call_response(
        llm_response=SimpleNamespace(content='{"name":"tool_demo"}', tool_calls=[]),
        tools=[],
        native_tool_messages=False,
        extract_raw_tool_calls_from_text=extract_raw,
        tool_names_from_tools=lambda tools: [],
        build_assistant_tool_call_message=lambda *args, **kwargs: None,
        logger_obj=logging.getLogger(__name__),
    )

    assert parsed is False
    assert response.tool_calls == []
