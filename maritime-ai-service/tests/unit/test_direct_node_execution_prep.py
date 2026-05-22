from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from app.engine.multi_agent.direct_node_execution_prep import (
    prepare_direct_node_tool_execution,
)


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Llm:
    _wiii_provider_name = "qwen"
    _wiii_model_name = "qwen3-next"


def _prepare(
    *,
    monkeypatch,
    state: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
    explicit_user_provider: str | None = None,
    visual_decision: Any | None = None,
    tools: list[Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}

    def resolve_primary_timeout(**kwargs: Any) -> float:
        captured["primary_timeout_kwargs"] = kwargs
        return 12.5

    def resolve_fallback_allowlist(**kwargs: Any) -> list[str]:
        captured["fallback_allowlist_kwargs"] = kwargs
        return ["qwen"]

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_node_execution_prep.resolve_direct_answer_primary_timeout_impl",
        resolve_primary_timeout,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_node_execution_prep.resolve_direct_fallback_provider_allowlist_impl_wrapper",
        resolve_fallback_allowlist,
    )

    def resolve_timeout_profile(**kwargs: Any) -> dict[str, Any]:
        captured["timeout_profile_kwargs"] = kwargs
        return {"profile": "moderate"}

    def bind_direct_tools(
        llm: Any,
        active_tools: list[Any],
        force_tools: bool,
        *,
        provider: str | None,
        include_forced_choice: bool,
    ) -> tuple[str, str, str | None]:
        captured["bind_kwargs"] = {
            "llm": llm,
            "tools": active_tools,
            "force_tools": force_tools,
            "provider": provider,
            "include_forced_choice": include_forced_choice,
        }
        return "llm-with-tools", "llm-auto", "any" if force_tools else None

    def build_messages(
        runtime_state: dict[str, Any],
        query: str,
        domain_name_vi: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        captured["message_kwargs"] = {
            "state": runtime_state,
            "query": query,
            "domain_name_vi": domain_name_vi,
            **kwargs,
        }
        return [{"role": "system", "content": "direct"}]

    def build_runtime_context(**kwargs: Any) -> dict[str, Any]:
        captured["runtime_context_kwargs"] = kwargs
        return kwargs

    result = prepare_direct_node_tool_execution(
        llm=_Llm(),
        tools=tools or [_Tool("tool_generate_visual"), _Tool("tool_web_search")],
        force_tools=False,
        query="tao mo phong canvas",
        state=state or {"session_id": "s1", "organization_id": "org1", "user_id": "u1"},
        ctx=ctx or {"request_id": "r1", "user_role": "teacher"},
        bus_id="bus-1",
        domain_name_vi="Hang hai",
        role_name="direct_agent",
        tools_context_override=None,
        visual_decision=visual_decision
        or SimpleNamespace(force_tool=True, visual_type="simulation"),
        history_limit=10,
        routing_intent="general",
        is_identity_turn=False,
        is_short_house_chatter=False,
        use_house_voice_direct=False,
        direct_provider_override="qwen",
        preferred_provider="qwen",
        explicit_user_provider=explicit_user_provider,
        needs_web_search=lambda _query: False,
        needs_datetime=lambda _query: False,
        resolve_direct_answer_timeout_profile=resolve_timeout_profile,
        bind_direct_tools=bind_direct_tools,
        build_direct_system_messages=build_messages,
        build_visual_tool_runtime_metadata=lambda _state, _query: {"visual": "metadata"},
        logger_obj=logging.getLogger(__name__),
        build_tool_runtime_context_fn=build_runtime_context,
    )
    return result, captured


def test_prepare_direct_node_tool_execution_forces_visual_tool(monkeypatch) -> None:
    state: dict[str, Any] = {"session_id": "s1", "organization_id": "org1", "user_id": "u1"}

    result, captured = _prepare(monkeypatch=monkeypatch, state=state)

    assert result.force_tools is True
    assert result.llm_with_tools == "llm-with-tools"
    assert result.llm_auto == "llm-auto"
    assert result.forced_tool_choice == "any"
    assert state["_execution_provider"] == "qwen"
    assert state["_execution_model"] == "qwen3-next"
    assert state["model"] == "qwen3-next"
    assert captured["bind_kwargs"]["force_tools"] is True
    assert captured["bind_kwargs"]["provider"] == "qwen"
    assert captured["timeout_profile_kwargs"]["provider_name"] == "qwen"
    assert captured["timeout_profile_kwargs"]["tools_bound"] is True
    assert captured["message_kwargs"]["native_messages"] is False
    assert result.messages == [{"role": "system", "content": "direct"}]
    assert result.runtime_context_base["node"] == "direct"
    assert result.runtime_context_base["metadata"] == {"visual": "metadata"}
    assert result.direct_allowed_fallback_providers == ["qwen"]


def test_prepare_direct_node_tool_execution_respects_explicit_provider(monkeypatch) -> None:
    result, captured = _prepare(
        monkeypatch=monkeypatch,
        explicit_user_provider="qwen",
        visual_decision=SimpleNamespace(force_tool=False, visual_type=None),
        tools=[_Tool("tool_web_search")],
    )

    assert result.force_tools is False
    assert result.forced_tool_choice is None
    assert result.direct_allowed_fallback_providers is None
    assert "fallback_allowlist_kwargs" not in captured
    assert captured["bind_kwargs"]["force_tools"] is False
