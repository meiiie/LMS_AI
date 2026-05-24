"""Reusable decision presets for visual intent resolution."""

from __future__ import annotations


def build_artifact_decision_impl(
    *,
    decision_cls,
    reason: str = "artifact-request",
    artifact_kind: str = "html_app",
    app_category: str = "artifact",
):
    return decision_cls(
        mode="app",
        force_tool=True,
        reason=reason,
        presentation_intent="artifact",
        preferred_tool="tool_create_visual_code",
        figure_budget=1,
        studio_lane="artifact",
        artifact_kind=artifact_kind,
        quality_profile="premium",
        renderer_contract="host_shell",
        preferred_render_surface="html",
        planning_profile="artifact_html",
        thinking_floor="high",
        critic_policy="standard",
        living_expression_mode="subtle",
        app_category=app_category,
    )


def build_app_decision_impl(
    *,
    decision_cls,
    visual_type: str | None,
    reason: str,
    app_category: str = "",
):
    is_simulation = visual_type == "simulation"
    return decision_cls(
        mode="app",
        force_tool=True,
        visual_type=visual_type,
        reason=reason,
        presentation_intent="code_studio_app",
        preferred_tool="tool_create_visual_code",
        figure_budget=1,
        studio_lane="app",
        artifact_kind="html_app",
        quality_profile="premium" if is_simulation else "standard",
        renderer_contract="host_shell",
        preferred_render_surface="canvas" if is_simulation else "html",
        planning_profile="simulation_canvas" if is_simulation else "artifact_html",
        thinking_floor="max" if is_simulation else "high",
        critic_policy="premium" if is_simulation else "standard",
        living_expression_mode="expressive" if is_simulation else "subtle",
        app_category=app_category or ("simulation" if is_simulation else "mini_tool"),
    )


def build_diagram_decision_impl(*, decision_cls):
    return decision_cls(
        mode="mermaid",
        force_tool=True,
        reason="diagram-request",
        presentation_intent="article_figure",
        preferred_tool="tool_generate_mermaid",
        figure_budget=1,
        renderer_contract="article_figure",
        preferred_render_surface="svg",
        planning_profile="article_svg",
        thinking_floor="high",
        critic_policy="standard",
        living_expression_mode="expressive",
    )


def build_chart_runtime_decision_impl(
    *,
    decision_cls,
    visual_type: str,
    reason: str,
    figure_budget: int,
    quality_profile: str = "standard",
    living_expression_mode: str = "subtle",
):
    return decision_cls(
        mode="inline_html",
        force_tool=True,
        visual_type=visual_type,
        reason=reason,
        presentation_intent="chart_runtime",
        preferred_tool="tool_generate_visual",
        figure_budget=figure_budget,
        quality_profile=quality_profile,
        renderer_contract="chart_runtime",
        preferred_render_surface="svg",
        planning_profile="chart_svg",
        thinking_floor="high",
        critic_policy="standard",
        living_expression_mode=living_expression_mode,
    )


def build_article_figure_decision_impl(
    *,
    decision_cls,
    visual_type: str,
    reason: str,
    figure_budget: int,
    quality_profile: str = "standard",
    preferred_render_surface: str = "svg",
    planning_profile: str = "article_svg",
    critic_policy: str = "standard",
    living_expression_mode: str = "expressive",
):
    return decision_cls(
        mode="inline_html",
        force_tool=True,
        visual_type=visual_type,
        reason=reason,
        presentation_intent="article_figure",
        preferred_tool="tool_generate_visual",
        figure_budget=figure_budget,
        quality_profile=quality_profile,
        renderer_contract="article_figure",
        preferred_render_surface=preferred_render_surface,
        planning_profile=planning_profile,
        thinking_floor="high",
        critic_policy=critic_policy,
        living_expression_mode=living_expression_mode,
    )
