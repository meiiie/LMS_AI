from types import SimpleNamespace

from app.engine.multi_agent.visual_runtime_metadata_contract import (
    build_visual_tool_runtime_intent,
)


def test_build_visual_tool_runtime_intent_preserves_typed_lane_metadata() -> None:
    decision = SimpleNamespace(
        force_tool=True,
        mode="app",
        reason="simulation cue",
        presentation_intent="code_studio_app",
        figure_budget=5,
        quality_profile="premium",
        preferred_render_surface="canvas",
        planning_profile="simulation_canvas",
        thinking_floor="max",
        critic_policy="premium",
        living_expression_mode="expressive",
        visual_type="simulation",
        preferred_tool="tool_create_visual_code",
        studio_lane="app",
        artifact_kind="html_app",
        renderer_contract="host_shell",
        renderer_kind_hint="app",
    )

    runtime_intent = build_visual_tool_runtime_intent(
        query="tao mo phong con lac",
        visual_decision=decision,
    )

    assert runtime_intent is not None
    metadata = runtime_intent.to_metadata()
    assert metadata["visual_user_query"] == "tao mo phong con lac"
    assert metadata["visual_intent_mode"] == "app"
    assert metadata["presentation_intent"] == "code_studio_app"
    assert metadata["figure_budget"] == 3
    assert metadata["quality_profile"] == "premium"
    assert metadata["preferred_render_surface"] == "canvas"
    assert metadata["visual_requested_type"] == "simulation"
    assert metadata["preferred_visual_tool"] == "tool_create_visual_code"
    assert metadata["studio_lane"] == "app"
    assert metadata["artifact_kind"] == "html_app"
    assert metadata["renderer_contract"] == "host_shell"
    assert metadata["renderer_kind_hint"] == "app"
    assert metadata["app_category"] == "simulation"
    assert "state_model" in metadata["app_reject_if_missing"]


def test_build_visual_tool_runtime_intent_skips_non_visual_turns() -> None:
    decision = SimpleNamespace(force_tool=False, mode="app")

    runtime_intent = build_visual_tool_runtime_intent(
        query="xin chao",
        visual_decision=decision,
    )

    assert runtime_intent is None


def test_build_visual_tool_runtime_intent_normalizes_unknown_quality() -> None:
    decision = SimpleNamespace(
        force_tool=True,
        mode="inline_html",
        reason="chart cue",
        presentation_intent="chart_runtime",
        figure_budget="bad",
        quality_profile="heroic",
        preferred_render_surface="svg",
        planning_profile="chart_svg",
        thinking_floor="medium",
        critic_policy="standard",
        living_expression_mode="subtle",
    )

    runtime_intent = build_visual_tool_runtime_intent(
        query="ve bieu do",
        visual_decision=decision,
    )

    assert runtime_intent is not None
    metadata = runtime_intent.to_metadata()
    assert metadata["figure_budget"] == 1
    assert metadata["quality_profile"] == "standard"
    assert "visual_requested_type" not in metadata


def test_build_visual_tool_runtime_intent_rejects_unknown_runtime_mode() -> None:
    decision = SimpleNamespace(force_tool=True, mode="raw_html")

    runtime_intent = build_visual_tool_runtime_intent(
        query="tao visual",
        visual_decision=decision,
    )

    assert runtime_intent is None
