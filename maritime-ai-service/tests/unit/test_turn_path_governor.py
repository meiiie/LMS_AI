from types import SimpleNamespace


def test_turn_path_governor_marks_plain_greeting_as_no_tool_chat():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(normalized_query="xin chao wiii")
    )

    assert decision.path == "casual_chat"
    assert decision.bind_tools is False
    assert decision.force_tools is False


def test_turn_path_governor_narrows_visual_app_to_required_tool():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="mo phong vat ly con lac",
            visual_force_tool=True,
            visual_mode="app",
            visual_presentation_intent="code_studio_app",
            visual_required_tool_names=("tool_create_visual_code",),
            pointy_requested=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "visual_generation"
    assert decision.force_tools is True
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name("tool_create_visual_code") is True
    assert decision.should_keep_tool_name("tool_generate_visual") is False
    assert decision.should_keep_tool_name("tool_pointy_show") is False


def test_turn_path_governor_routes_weather_to_weather_tool_only():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="y la thoi tiet nong do ban biet nay bao do khong",
            needs_weather_lookup=True,
            needs_web_search=True,
            pointy_requested=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "weather_lookup"
    assert decision.force_tools is True
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name("tool_current_weather") is True
    assert decision.should_keep_tool_name("tool_web_search") is False
    assert decision.should_keep_tool_name("tool_pointy_show") is False


def test_turn_path_filter_keeps_only_lms_document_preview_tools():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        filter_tools_for_turn_path,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="tao cho minh bai hoc",
            looks_document_preview=True,
        )
    )
    tools = [
        SimpleNamespace(name="host_action__authoring__preview_lesson_patch"),
        SimpleNamespace(name="host_action__authoring__apply_lesson_patch"),
        SimpleNamespace(name="tool_web_search"),
    ]

    filtered = filter_tools_for_turn_path(
        tools,
        decision,
        tool_name=lambda tool: tool.name,
    )

    assert decision.path == "lms_document_preview"
    assert [tool.name for tool in filtered] == [
        "host_action__authoring__preview_lesson_patch"
    ]


def test_collect_direct_tools_uses_governor_for_plain_greeting():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Xin chào Wiii",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "casual_chat"


def test_collect_direct_tools_keeps_daily_status_off_search_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Hôm nay mình ăn cơm rồi",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "casual_chat"


def test_collect_direct_tools_routes_weather_followup_to_weather_tool():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "ý là thời tiết nóng đó. Bạn biết nay bao độ không",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "weather_lookup"
    assert names == {"tool_current_weather"}


def test_direct_required_tool_names_weather_prefers_weather_over_web():
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names

    required = _direct_required_tool_names(
        "ý là thời tiết nóng đó. Bạn biết nay bao độ không",
        user_role="student",
    )

    assert "tool_current_weather" in required
    assert "tool_web_search" not in required
