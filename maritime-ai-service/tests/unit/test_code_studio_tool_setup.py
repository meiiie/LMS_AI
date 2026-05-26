from types import SimpleNamespace
from unittest.mock import MagicMock

from app.engine.multi_agent.code_studio_tool_setup import (
    CodeStudioToolSetupResult,
    prepare_code_studio_tool_setup,
)


def test_prepare_code_studio_tool_setup_selects_tools_and_builds_runtime_context() -> None:
    original_tools = [
        SimpleNamespace(name="tool_create_visual_code"),
        SimpleNamespace(name="tool_python"),
    ]
    selected_tools = [original_tools[0]]
    runtime_context = SimpleNamespace(runtime="ctx")
    state = {
        "routing_metadata": {"intent": "visual_app"},
        "session_id": "session-1",
        "organization_id": "org-1",
        "user_id": "user-1",
    }

    def select_runtime_tools_fn(tools, **kwargs):
        assert tools == original_tools
        assert kwargs["query"] == "build a simulation"
        assert kwargs["intent"] == "visual_app"
        assert kwargs["user_role"] == "teacher"
        assert kwargs["max_tools"] == 2
        assert kwargs["must_include"] == ["tool_create_visual_code"]
        return selected_tools

    def build_tool_runtime_context_fn(**kwargs):
        assert kwargs["event_bus_id"] == "bus-1"
        assert kwargs["request_id"] == "req-1"
        assert kwargs["session_id"] == "session-1"
        assert kwargs["organization_id"] == "org-1"
        assert kwargs["user_id"] == "user-1"
        assert kwargs["user_role"] == "teacher"
        assert kwargs["node"] == "code_studio_agent"
        assert kwargs["source"] == "agentic_loop"
        assert kwargs["metadata"] == {"visual": True}
        return runtime_context

    result = prepare_code_studio_tool_setup(
        effective_query="build a simulation",
        state=state,
        ctx={"user_role": "teacher", "request_id": "req-1"},
        bus_id="bus-1",
        collect_code_studio_tools=lambda _query, _role: (original_tools, True),
        code_studio_required_tool_names=lambda _query, _role: ["tool_create_visual_code"],
        build_tool_runtime_context_fn=build_tool_runtime_context_fn,
        build_visual_tool_runtime_metadata=lambda _state, _query: {"visual": True},
        logger_obj=MagicMock(),
        select_runtime_tools_fn=select_runtime_tools_fn,
    )

    assert isinstance(result, CodeStudioToolSetupResult)
    assert result.tools == selected_tools
    assert result.force_tools is True
    assert result.runtime_context_base is runtime_context
    policy = state["_tool_policy_session"]
    assert policy["path"] == "code_studio"
    assert policy["candidate_tool_names"] == [
        "tool_create_visual_code",
        "tool_python",
    ]
    assert policy["visible_tool_names"] == ["tool_create_visual_code"]
    assert policy["tool_capabilities"]["tool_create_visual_code"]["group"] == "visual"


def test_prepare_code_studio_tool_setup_keeps_tools_when_selection_fails() -> None:
    tools = [SimpleNamespace(name="tool_create_visual_code")]
    logger = MagicMock()
    state = {}

    def select_runtime_tools_fn(*_args, **_kwargs):
        raise RuntimeError("selector unavailable")

    result = prepare_code_studio_tool_setup(
        effective_query="build a simulation",
        state=state,
        ctx={},
        bus_id=None,
        collect_code_studio_tools=lambda _query, _role: (tools, False),
        code_studio_required_tool_names=lambda _query, _role: [],
        build_tool_runtime_context_fn=lambda **kwargs: kwargs,
        build_visual_tool_runtime_metadata=lambda _state, _query: {},
        logger_obj=logger,
        select_runtime_tools_fn=select_runtime_tools_fn,
    )

    assert result.tools == tools
    assert result.force_tools is False
    assert result.runtime_context_base["user_role"] == "student"
    assert state["_tool_policy_session"]["visible_tool_names"] == ["tool_create_visual_code"]
    logger.debug.assert_called_once()
