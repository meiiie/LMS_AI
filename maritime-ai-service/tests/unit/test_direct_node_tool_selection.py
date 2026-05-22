from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.direct_node_tool_selection import select_direct_node_tools


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_select_direct_node_tools_skips_short_house_chatter() -> None:
    def collect_direct_tools(*_args: Any, **_kwargs: Any) -> tuple[list[Any], bool]:
        raise AssertionError("short chatter should not collect tools")

    result = select_direct_node_tools(
        query="ê",
        state={},
        ctx={"user_role": "student"},
        routing_intent="social",
        is_short_house_chatter=True,
        is_identity_turn=False,
        is_emotional_support_turn=False,
        is_codebase_source_turn=False,
        explicit_web_search_turn=False,
        has_uploaded_document_context=False,
        needs_web_search=lambda _query: False,
        collect_direct_tools=collect_direct_tools,
        direct_required_tool_names=lambda _query, _role: [],
        logger_obj=logging.getLogger(__name__),
    )

    assert result.tools == []
    assert result.force_tools is False


def test_select_direct_node_tools_forces_web_search_and_must_include(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_select_runtime_tools(
        tools: list[Any],
        *,
        query: str,
        intent: str | None,
        user_role: str,
        max_tools: int,
        must_include: list[str],
    ) -> list[Any]:
        captured.update(
            {
                "query": query,
                "intent": intent,
                "user_role": user_role,
                "max_tools": max_tools,
                "must_include": must_include,
            }
        )
        return tools

    monkeypatch.setattr(
        "app.engine.skills.skill_recommender.select_runtime_tools",
        fake_select_runtime_tools,
    )

    tools = [_Tool("tool_web_search"), _Tool("tool_knowledge_search")]
    state: dict[str, Any] = {"routing_metadata": {"intent": "web_search"}}
    ctx: dict[str, Any] = {"user_role": "teacher"}

    result = select_direct_node_tools(
        query="giá dầu hôm nay",
        state=state,
        ctx=ctx,
        routing_intent="web_search",
        is_short_house_chatter=False,
        is_identity_turn=False,
        is_emotional_support_turn=False,
        is_codebase_source_turn=False,
        explicit_web_search_turn=True,
        has_uploaded_document_context=False,
        needs_web_search=lambda _query: True,
        collect_direct_tools=lambda *_args, **_kwargs: (tools, False),
        direct_required_tool_names=lambda _query, _role: [],
        logger_obj=logging.getLogger(__name__),
    )

    assert result.tools == tools
    assert result.force_tools is True
    assert state["force_skills"] == ["web-search"]
    assert ctx["force_skills"] == ["web-search"]
    assert "tool_web_search" in captured["must_include"]
    assert captured["user_role"] == "teacher"
