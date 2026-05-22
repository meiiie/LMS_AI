import sys
from types import SimpleNamespace


def test_direct_tool_provider_policy_tracks_failover_and_runtime_target():
    from app.engine.multi_agent.direct_runtime_bindings import (
        build_direct_tool_provider_policy,
    )

    state: dict = {}
    llm_base = SimpleNamespace(
        _wiii_provider_name="QWEN",
        _wiii_model_name="qwen-main",
        _wiii_tier_key="FAST",
    )
    fallback = SimpleNamespace(_wiii_provider_name="zhipu", model_name="glm")

    policy = build_direct_tool_provider_policy(
        state=state,
        provider="qwen",
        llm_base=llm_base,
        llm_auto=object(),
        llm_with_tools=object(),
        failover_mode_auto="auto",
        failover_mode_pinned="pinned",
    )

    assert policy.request_failover_mode == "pinned"
    assert policy.resolved_provider == "qwen"
    assert policy.runtime_tier_for(object()) == "fast"
    assert policy.remember_execution_target(object(), fallback_source=fallback) == (
        "zhipu",
        "glm",
    )
    assert state["_execution_provider"] == "zhipu"
    assert state["_execution_model"] == "glm"
    assert state["model"] == "glm"


def test_direct_tool_provider_policy_uses_auto_failover_for_auto_provider():
    from app.engine.multi_agent.direct_runtime_bindings import (
        build_direct_tool_provider_policy,
    )

    policy = build_direct_tool_provider_policy(
        state={},
        provider="auto",
        llm_base=None,
        llm_auto=SimpleNamespace(_wiii_provider_name="auto"),
        llm_with_tools=object(),
        failover_mode_auto="auto",
        failover_mode_pinned="pinned",
    )

    assert policy.request_failover_mode == "auto"
    assert policy.resolved_provider == "auto"
    assert policy.runtime_tier_for(object()) == "moderate"


def test_resolve_direct_tool_runtime_bindings_uses_graph_overrides():
    from app.engine.multi_agent.direct_runtime_bindings import (
        resolve_direct_tool_runtime_bindings,
    )

    graph_module_name = "app.engine.multi_agent.graph"
    original_graph_module = sys.modules.get(graph_module_name)
    override = object()
    sys.modules[graph_module_name] = SimpleNamespace(
        _ainvoke_with_fallback=override,
        get_tool_by_name=override,
    )
    fallback = object()
    try:
        bindings = resolve_direct_tool_runtime_bindings(
            ainvoke_with_fallback=fallback,
            stream_direct_answer_with_fallback=fallback,
            stream_direct_wait_heartbeats=fallback,
            build_direct_tool_reflection=fallback,
            maybe_emit_host_action_event=fallback,
            maybe_emit_visual_event=fallback,
            emit_visual_commit_events=fallback,
            get_tool_by_name=fallback,
            invoke_tool_with_runtime=fallback,
        )
    finally:
        if original_graph_module is None:
            sys.modules.pop(graph_module_name, None)
        else:
            sys.modules[graph_module_name] = original_graph_module

    assert bindings.ainvoke_with_fallback is override
    assert bindings.get_tool_by_name is override
    assert bindings.stream_direct_answer_with_fallback is fallback
    assert bindings.invoke_tool_with_runtime is fallback
