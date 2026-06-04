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


def test_select_direct_node_tools_forced_path_overrides_short_chatter(monkeypatch) -> None:
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

    weather_tool = _Tool("tool_current_weather")
    state: dict[str, Any] = {
        "_turn_path_decision": {
            "path": "weather_lookup",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "allowed_tool_names": ["tool_current_weather"],
        },
        "routing_metadata": {"intent": "social"},
    }

    result = select_direct_node_tools(
        query="nay thoi tiet nong nhi",
        state=state,
        ctx={"user_role": "student"},
        routing_intent="social",
        is_short_house_chatter=True,
        is_identity_turn=False,
        is_emotional_support_turn=False,
        is_codebase_source_turn=False,
        explicit_web_search_turn=False,
        has_uploaded_document_context=False,
        needs_web_search=lambda _query: False,
        collect_direct_tools=lambda *_args, **_kwargs: ([weather_tool], True),
        direct_required_tool_names=lambda _query, _role: ["tool_current_weather"],
        logger_obj=logging.getLogger(__name__),
    )

    assert result.tools == [weather_tool]
    assert result.force_tools is True
    assert captured["must_include"] == ["tool_current_weather"]


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
    assert "force_skills" not in state
    assert "force_skills" not in ctx
    assert "tool_web_search" in captured["must_include"]
    assert captured["user_role"] == "teacher"


def test_select_direct_node_tools_respects_governor_when_pointy_is_suppressed(monkeypatch) -> None:
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
        captured["must_include"] = must_include
        return tools

    monkeypatch.setattr(
        "app.engine.skills.skill_recommender.select_runtime_tools",
        fake_select_runtime_tools,
    )

    state: dict[str, Any] = {
        "_turn_path_decision": {
            "path": "direct_prose",
            "bind_tools": False,
            "allow_all_tools": False,
            "forbidden_tool_prefixes": ["tool_pointy_"],
        },
        "context": {"force_skills": ["wiii-pointy"]},
        "routing_metadata": {"intent": "general"},
    }

    result = select_direct_node_tools(
        query="@wiii-pointy tao bai hoc ngan ve ky nang hoc tap",
        state=state,
        ctx={"user_role": "teacher"},
        routing_intent="general",
        is_short_house_chatter=False,
        is_identity_turn=False,
        is_emotional_support_turn=False,
        is_codebase_source_turn=False,
        explicit_web_search_turn=False,
        has_uploaded_document_context=False,
        needs_web_search=lambda _query: False,
        collect_direct_tools=lambda *_args, **_kwargs: ([], False),
        direct_required_tool_names=lambda _query, _role: [],
        logger_obj=logging.getLogger(__name__),
    )

    assert result.tools == []
    assert result.force_tools is False
    assert captured["must_include"] == []


def test_select_direct_node_tools_force_binds_pointy_when_governor_allows_it(monkeypatch) -> None:
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
        captured["must_include"] = must_include
        return tools

    monkeypatch.setattr(
        "app.engine.skills.skill_recommender.select_runtime_tools",
        fake_select_runtime_tools,
    )

    tools = [_Tool("tool_pointy_show"), _Tool("tool_pointy_inventory")]
    state: dict[str, Any] = {
        "_turn_path_decision": {
            "path": "pointy_guidance",
            "bind_tools": True,
            "allow_all_tools": False,
            "allowed_tool_prefixes": ["tool_pointy_"],
        },
        "context": {"force_skills": ["wiii-pointy"]},
        "routing_metadata": {"intent": "host_ui_navigation"},
    }

    result = select_direct_node_tools(
        query="@wiii-pointy chi vao nut gui",
        state=state,
        ctx={"user_role": "student"},
        routing_intent="host_ui_navigation",
        is_short_house_chatter=False,
        is_identity_turn=False,
        is_emotional_support_turn=False,
        is_codebase_source_turn=False,
        explicit_web_search_turn=False,
        has_uploaded_document_context=False,
        needs_web_search=lambda _query: False,
        collect_direct_tools=lambda *_args, **_kwargs: (tools, False),
        direct_required_tool_names=lambda _query, _role: [],
        logger_obj=logging.getLogger(__name__),
    )

    assert result.tools == tools
    assert result.force_tools is True
    assert "tool_pointy_show" in captured["must_include"]
    assert "tool_pointy_inventory" in captured["must_include"]
