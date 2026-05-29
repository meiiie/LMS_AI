from types import SimpleNamespace

import pytest


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


@pytest.mark.parametrize(
    "query",
    [
        "noi de",
        "sao lai z",
        "sao lo lung ?",
        "the ngu di",
    ],
)
def test_turn_path_governor_marks_short_social_followup_as_no_tool_chat(query):
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(TurnPathSignals(normalized_query=query))

    assert decision.path == "casual_chat"
    assert decision.bind_tools is False
    assert decision.force_tools is False


def test_turn_path_governor_does_not_treat_task_query_as_social_followup():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="sao lai colreg rule 15 ap dung",
            needs_maritime_search=True,
        )
    )

    assert decision.path == "maritime_search"
    assert decision.bind_tools is True
    assert decision.force_tools is True


def test_turn_path_governor_defaults_plain_direct_prose_to_no_tool():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(normalized_query="giai thich ngan ve cach hoc tot hon")
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "default_direct_prose_no_tool"
    assert decision.bind_tools is False
    assert decision.allow_agent_handoff is False


def test_turn_path_governor_keeps_low_signal_noise_off_tool_path():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query=(
                "flow noi chuyen thuong van bi keo sang search tool "
                + ("r" * 128)
            )
        )
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "low_signal_noise_no_tool"
    assert decision.bind_tools is False


def test_turn_path_governor_marks_wiii_pipeline_meta_as_no_tool_direct_prose():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="wiii flow noi chuyen sai route, kiem tra pipeline",
            looks_wiii_pipeline_meta=True,
        )
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "wiii_pipeline_meta_no_tool"
    assert decision.bind_tools is False


def test_turn_path_governor_scopes_character_memory_tools():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="ten toi la an",
            needs_character_memory_tool=True,
        )
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "character_memory_tool_request"
    assert decision.bind_tools is True
    assert decision.force_tools is False
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name("tool_character_note") is True
    assert decision.should_keep_tool_name("tool_web_search") is False


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


def test_turn_path_governor_forces_wiii_connect_facebook_post_tools():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="wiii dang bai len facebook giup minh",
            needs_external_app_action=True,
            pointy_requested=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "external_app_action"
    assert decision.force_tools is True
    assert decision.bind_tools is True
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name(WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL) is True
    assert decision.should_keep_tool_name(WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL) is True
    assert decision.should_keep_tool_name("host_action__ui_click") is False
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


def test_collect_direct_tools_keeps_short_social_followup_off_tool_path():
    from app.engine.multi_agent import tool_collection as module

    state = {
        "context": {},
        "routing_metadata": {
            "intent": "unknown",
        },
    }
    tools, force_tools = module._collect_direct_tools(
        "sao lơ lửng ?",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "casual_chat"


@pytest.mark.parametrize(
    "query",
    [
        "flow noi chuyen thuong van bi keo sang search/tool",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "sao lai z " + ("R" * 256),
    ],
)
def test_collect_direct_tools_keeps_plain_meta_and_noise_off_tool_path(query):
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        query,
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "direct_prose"
    assert state["_turn_path_decision"]["bind_tools"] is False
    assert state["_tool_policy_session"]["visible_tool_names"] == []


def test_collect_direct_tools_marks_wiii_pipeline_meta_as_no_tool():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii flow noi chuyen bi sai route, kiem tra pipeline tool policy.",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "direct_prose"
    assert state["_turn_path_decision"]["reason"] == "wiii_pipeline_meta_no_tool"


def test_collect_direct_tools_keeps_explicit_web_search_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "hom nay co gi hot?",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "web_search"
    assert "tool_web_search" in names
    assert "tool_current_weather" not in names


def test_collect_direct_tools_scopes_personal_fact_to_character_tools():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Ten toi la An",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is False
    assert state["_turn_path_decision"]["reason"] == "character_memory_tool_request"
    assert "tool_character_note" in names
    assert "tool_character_log_experience" in names
    assert "tool_web_search" not in names


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


@pytest.mark.parametrize(
    "query",
    [
        "nay thoi tiet nong nhi",
        "hom nay troi nong nhi",
        "hom nay bao nhieu do",
        "troi co mua khong",
    ],
)
def test_collect_direct_tools_routes_weather_turns_to_weather_tool(query):
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        query,
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "weather_lookup"
    assert names == {"tool_current_weather"}


def test_collect_direct_tools_keeps_maritime_tool_on_maritime_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Tra cứu quy định COLREG mới nhất",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "maritime_search"
    assert "tool_search_maritime" in names
    assert "tool_current_weather" not in names


def test_direct_required_tool_names_weather_prefers_weather_over_web():
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names

    required = _direct_required_tool_names(
        "ý là thời tiết nóng đó. Bạn biết nay bao độ không",
        user_role="student",
    )

    assert "tool_current_weather" in required
    assert "tool_web_search" not in required


def test_direct_required_tool_names_temperature_question_prefers_weather_over_web():
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names

    required = _direct_required_tool_names(
        "hom nay bao nhieu do",
        user_role="student",
    )

    assert required == ["tool_current_weather"]


def test_direct_required_tool_names_includes_wiii_connect_facebook_direct_apply():
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    required = _direct_required_tool_names(
        "Wiii tao bai viet Facebook ve lop hoc hom nay",
        user_role="student",
    )

    assert WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL in required
