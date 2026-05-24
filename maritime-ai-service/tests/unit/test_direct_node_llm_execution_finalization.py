from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.engine.multi_agent.direct_node_llm_execution_finalization import (
    finalize_direct_node_llm_execution,
)


@pytest.mark.asyncio
async def test_finalize_direct_node_llm_execution_applies_cleanup_fallback_and_state() -> None:
    state: dict[str, Any] = {}
    finalizer_calls: list[dict[str, Any]] = []
    tool_events = [{"type": "result", "name": "tool_web_search", "content": "source"}]

    def extract_direct_response(_llm_response: Any, _messages: list[Any]):
        return "raw answer", "thinking", ["tool_web_search"]

    def clean_response(**kwargs: Any):
        assert kwargs["response"] == "raw answer"
        assert kwargs["tool_call_events"] == tool_events
        return SimpleNamespace(
            response="clean answer",
            thinking_content="clean thinking",
            tools_used=["tool_web_search"],
        )

    def source_fallback(**kwargs: Any):
        assert kwargs["response"] == "clean answer"
        return SimpleNamespace(
            response="source-backed answer",
            tools_used=[*kwargs["tools_used"], {"name": "tool_knowledge_search"}],
        )

    async def finalize_visible_thinking(**kwargs: Any):
        finalizer_calls.append(kwargs)

    result = await finalize_direct_node_llm_execution(
        query="gia dau hom nay",
        state=state,
        llm_response=SimpleNamespace(content="raw"),
        messages=["message"],
        tool_call_events=tool_events,
        llm=SimpleNamespace(name="llm"),
        routing_intent="lookup",
        response_language="vi",
        is_identity_turn=False,
        explicit_web_search_turn=True,
        extract_direct_response=extract_direct_response,
        sanitize_structured_visual_answer_text=lambda text, **_kwargs: text,
        sanitize_wiii_house_text=lambda text, **_kwargs: text,
        build_direct_reasoning_summary=lambda **_kwargs: "summary",
        logger_obj=logging.getLogger(__name__),
        clean_direct_node_llm_response_fn=clean_response,
        apply_source_backed_empty_response_fallback_fn=source_fallback,
        finalize_direct_node_visible_thinking_fn=finalize_visible_thinking,
    )

    assert result.response == "source-backed answer"
    assert result.thinking_content == "clean thinking"
    assert result.tools_used == [
        "tool_web_search",
        {"name": "tool_knowledge_search"},
    ]
    assert state["tool_call_events"] == tool_events
    assert state["tools_used"] == result.tools_used
    assert finalizer_calls[0]["response"] == "source-backed answer"
    assert finalizer_calls[0]["thinking_content"] == "clean thinking"
    assert finalizer_calls[0]["tools_used"] == result.tools_used


@pytest.mark.asyncio
async def test_finalize_direct_node_llm_execution_leaves_empty_tool_state_when_no_tools() -> None:
    state: dict[str, Any] = {}

    def extract_direct_response(_llm_response: Any, _messages: list[Any]):
        return "answer", "", []

    def clean_response(**_kwargs: Any):
        return SimpleNamespace(response="answer", thinking_content="", tools_used=[])

    def source_fallback(**kwargs: Any):
        return SimpleNamespace(response=kwargs["response"], tools_used=kwargs["tools_used"])

    async def finalize_visible_thinking(**_kwargs: Any):
        return None

    result = await finalize_direct_node_llm_execution(
        query="xin chao",
        state=state,
        llm_response=SimpleNamespace(content="answer"),
        messages=[],
        tool_call_events=[],
        llm=None,
        routing_intent="chat",
        response_language="vi",
        is_identity_turn=False,
        explicit_web_search_turn=False,
        extract_direct_response=extract_direct_response,
        sanitize_structured_visual_answer_text=lambda text, **_kwargs: text,
        sanitize_wiii_house_text=lambda text, **_kwargs: text,
        build_direct_reasoning_summary=lambda **_kwargs: "",
        logger_obj=logging.getLogger(__name__),
        clean_direct_node_llm_response_fn=clean_response,
        apply_source_backed_empty_response_fallback_fn=source_fallback,
        finalize_direct_node_visible_thinking_fn=finalize_visible_thinking,
    )

    assert result.response == "answer"
    assert result.tools_used == []
    assert "tool_call_events" not in state
    assert "tools_used" not in state
