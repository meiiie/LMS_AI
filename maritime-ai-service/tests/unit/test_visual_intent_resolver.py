from app.engine.multi_agent.visual_intent_resolver import (
    build_visual_tool_requirement,
    detect_visual_patch_request,
    filter_tools_for_visual_intent,
    merge_quality_profile,
    recommended_visual_thinking_effort,
    preferred_visual_tool_name,
    required_visual_tool_names,
    resolve_visual_intent,
    visual_tool_capability_names,
)
from app.engine.tools.code_studio_app_intent_contract import infer_code_studio_app_category


class _Tool:
    def __init__(self, name: str):
        self.name = name


def _tool_names(tools):
    return [tool.name for tool in tools]


def test_resolves_comparison_visual():
    decision = resolve_visual_intent("So sanh softmax attention voi linear attention")
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.visual_type == "comparison"
    assert decision.presentation_intent == "article_figure"
    assert decision.preferred_tool == "tool_generate_visual"
    assert decision.figure_budget == 2
    assert decision.renderer_contract == "article_figure"
    assert decision.preferred_render_surface == "svg"
    assert decision.planning_profile == "article_svg"
    assert decision.thinking_floor == "high"
    assert decision.critic_policy == "standard"


def test_resolves_explicit_inline_visual_comparison_request():
    decision = resolve_visual_intent(
        "Create a compact inline visual comparing soft attention and linear attention. "
        "Use structured visual lifecycle."
    )
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.visual_type == "comparison"
    assert decision.reason == "explicit-inline-visual"
    assert decision.presentation_intent == "article_figure"
    assert decision.preferred_tool == "tool_generate_visual"


def test_resolves_mojibake_smoke_prompt_from_deploy_script():
    decision = resolve_visual_intent(
        "So sÃ¡nh attention má»m vÃ  linear attention báº±ng visual inline"
    )
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.presentation_intent == "article_figure"
    assert decision.preferred_tool == "tool_generate_visual"


def test_resolves_process_visual():
    decision = resolve_visual_intent("Giai thich quy trinh docking step by step")
    assert decision.mode == "inline_html"
    assert decision.visual_type == "process"
    assert decision.presentation_intent == "article_figure"
    assert decision.preferred_tool == "tool_generate_visual"
    assert decision.figure_budget == 2
    assert decision.preferred_render_surface == "svg"
    assert decision.living_expression_mode == "expressive"


def test_resolves_architecture_visual():
    decision = resolve_visual_intent("Mo ta kien truc he thong RAG nhieu layer")
    assert decision.mode == "inline_html"
    assert decision.visual_type == "architecture"
    assert decision.presentation_intent == "article_figure"
    assert decision.preferred_tool == "tool_generate_visual"
    assert decision.figure_budget >= 2
    assert decision.quality_profile == "premium"
    assert decision.preferred_render_surface == "svg"
    assert decision.critic_policy == "premium"


def test_resolves_chart_request_as_inline_html():
    decision = resolve_visual_intent("Ve bieu do KPI theo thang")
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.visual_type == "chart"
    assert decision.presentation_intent == "chart_runtime"
    assert decision.preferred_tool == "tool_generate_visual"
    assert decision.renderer_contract == "chart_runtime"
    assert decision.preferred_render_surface == "svg"
    assert decision.planning_profile == "chart_svg"
    assert decision.living_expression_mode == "subtle"


def test_resolves_container_speed_chart_as_chart_runtime_not_code_studio():
    decision = resolve_visual_intent("Ve bieu do so sanh toc do cac loai tau container")
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.visual_type == "chart"
    assert decision.presentation_intent == "chart_runtime"
    assert decision.preferred_tool == "tool_generate_visual"
    assert decision.studio_lane is None
    assert decision.renderer_contract == "chart_runtime"


def test_resolves_accented_vietnamese_chart_request():
    decision = resolve_visual_intent("Vẽ biểu đồ so sánh tốc độ các loại tàu container")
    assert decision.mode == "inline_html"
    assert decision.presentation_intent == "chart_runtime"
    assert decision.preferred_tool == "tool_generate_visual"


def test_resolves_visual_statistics_request_with_unicode_vietnamese_as_chart_runtime():
    decision = resolve_visual_intent("Visual cho mình xem thống kê dữ liệu hiện tại giá dầu mấy ngày gần đây")
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.visual_type == "chart"
    assert decision.presentation_intent == "chart_runtime"
    assert decision.preferred_tool == "tool_generate_visual"


def test_resolves_mermaid_request():
    decision = resolve_visual_intent("Ve flowchart quy trinh onboarding")
    assert decision.mode == "mermaid"
    assert decision.force_tool is True


def test_resolves_app_request():
    decision = resolve_visual_intent("Tao dashboard app HTML cho chien dich nay")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.studio_lane == "app"
    assert decision.visual_type == "react_app"
    assert decision.app_category == "dashboard"


def test_resolves_vietnamese_simulation_request_as_app():
    decision = resolve_visual_intent("Hay mo phong vat ly con lac co the keo tha")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.visual_type == "simulation"
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.renderer_contract == "host_shell"
    assert decision.preferred_render_surface == "canvas"
    assert decision.planning_profile == "simulation_canvas"
    assert decision.thinking_floor == "max"
    assert decision.critic_policy == "premium"
    assert decision.app_category == "simulation"


def test_resolves_accented_vietnamese_simulation_request_as_app():
    decision = resolve_visual_intent("Hãy mô phỏng vật lý con lắc có kéo thả chuột")
    assert decision.mode == "app"
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.preferred_render_surface == "canvas"


def test_resolves_english_pendulum_simulation_request_as_app():
    decision = resolve_visual_intent(
        "Build a mini pendulum physics app in chat with drag interaction. Use Code Studio and keep it inline with the conversation."
    )
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.visual_type == "simulation"
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.quality_profile == "premium"
    assert decision.app_category == "simulation"


def test_resolves_literary_scene_simulation_request_as_code_studio_app():
    decision = resolve_visual_intent("Mô phỏng cảnh Thúy Kiều ở lầu Ngưng Bích cho mình được chứ ?")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.visual_type == "simulation"
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.preferred_render_surface == "canvas"


def test_resolves_vietnamese_app_followup_patch_as_app():
    decision = resolve_visual_intent("Gi\u1eef app hi\u1ec7n t\u1ea1i, th\u00eam slider \u0111i\u1ec1u ch\u1ec9nh tr\u1ecdng l\u1ef1c v\u00e0 ma s\u00e1t")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.studio_lane == "app"
    assert decision.renderer_contract == "host_shell"
    assert decision.quality_profile == "premium"


def test_resolves_simulation_followup_with_live_readouts_as_premium():
    decision = resolve_visual_intent("Gi\u1eef app hi\u1ec7n t\u1ea1i, th\u00eam hi\u1ec3n th\u1ecb g\u00f3c l\u1ec7ch v\u00e0 v\u1eadn t\u1ed1c theo th\u1eddi gian")
    assert decision.mode == "app"
    assert decision.visual_type == "simulation"
    assert decision.quality_profile == "premium"


def test_resolves_inline_html_request():
    decision = resolve_visual_intent("Hay lam mot editorial visual animated de giai thich Kimi linear attention")
    assert decision.mode == "inline_html"
    assert decision.force_tool is True
    assert decision.presentation_intent == "article_figure"
    assert decision.preferred_tool == "tool_generate_visual"


def test_resolves_embeddable_html_app_as_artifact():
    decision = resolve_visual_intent("Tao mot mini app HTML de nhung vao LMS")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.presentation_intent == "artifact"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.studio_lane == "artifact"
    assert decision.renderer_contract == "host_shell"
    assert decision.preferred_render_surface == "html"
    assert decision.planning_profile == "artifact_html"
    assert decision.thinking_floor == "high"
    assert decision.app_category == "artifact"


def test_quiz_creation_request_routes_to_code_studio():
    decision = resolve_visual_intent("Tao cho minh quizz gom 30 cau hoi ve tieng Trung de luyen tap")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.studio_lane == "app"
    assert decision.visual_type == "quiz"
    assert decision.app_category == "quiz"


def test_plain_quiz_request_without_creation_verbs_stays_text():
    decision = resolve_visual_intent("Cho minh bo quiz tieng Trung de on tap")
    assert decision.mode == "text"
    assert decision.force_tool is False
    assert decision.presentation_intent == "text"


def test_interactive_quiz_widget_request_routes_to_code_studio():
    decision = resolve_visual_intent("Tao mot interactive quiz widget HTML tuong tac trong chat")
    assert decision.mode == "app"
    assert decision.force_tool is True
    assert decision.presentation_intent == "code_studio_app"
    assert decision.preferred_tool == "tool_create_visual_code"
    assert decision.studio_lane == "app"
    assert decision.visual_type == "quiz"
    assert decision.app_category == "quiz"


def test_interactive_table_request_routes_to_typed_app_category():
    decision = resolve_visual_intent("Tao interactive table co filter va sort cho danh sach hoc vien")
    assert decision.mode == "app"
    assert decision.visual_type == "interactive_table"
    assert decision.app_category == "interactive_table"
    assert decision.preferred_tool == "tool_create_visual_code"


def test_search_widget_request_routes_to_typed_app_category():
    decision = resolve_visual_intent("Tao search widget tim kiem tai lieu trong chat")
    assert decision.mode == "app"
    assert decision.visual_type == "react_app"
    assert decision.app_category == "search_widget"
    assert decision.preferred_tool == "tool_create_visual_code"


def test_code_studio_app_categories_match_typed_contract():
    cases = (
        ("Hay mo phong vat ly con lac co the keo tha", "simulation"),
        ("Tao cho minh quizz gom 30 cau hoi ve tieng Trung de luyen tap", "quiz"),
        ("Tao dashboard app HTML cho chien dich nay", "dashboard"),
        ("Tao interactive table co filter va sort cho danh sach hoc vien", "interactive_table"),
        ("Tao search widget tim kiem tai lieu trong chat", "search_widget"),
        ("Tao code widget HTML co editor va preview trong chat", "code_widget"),
        ("Tao mini tool tinh toan do lech hang hai", "mini_tool"),
    )

    for prompt, expected_category in cases:
        decision = resolve_visual_intent(prompt)
        contract_category = infer_code_studio_app_category(
            presentation_intent=decision.presentation_intent,
            studio_lane=decision.studio_lane or "",
            requested_visual_type=decision.visual_type or "",
            user_query=prompt,
            planning_profile=decision.planning_profile,
        )

        assert decision.presentation_intent == "code_studio_app"
        assert decision.app_category == expected_category
        assert contract_category == expected_category


def test_ignores_false_positive_visual_terms():
    decision = resolve_visual_intent("Visual Studio Code khac Visual Basic the nao?")
    assert decision.mode == "text"
    assert decision.force_tool is False


def test_ignores_reasoning_safety_meta_as_visual_comparison():
    decision = resolve_visual_intent(
        "Giải thích sự khác nhau giữa visible thinking an toàn và chain-of-thought nội bộ"
    )
    assert decision.mode == "text"
    assert decision.force_tool is False
    assert decision.reason == "reasoning-safety-text"


def test_detects_visual_patch_followup():
    assert detect_visual_patch_request("Highlight only the bottleneck and keep the same visual session.")
    assert detect_visual_patch_request("Biến sơ đồ này thành 3 bước")
    assert detect_visual_patch_request("Giữ app hiện tại, thêm slider điều chỉnh trọng lực và ma sát")
    assert detect_visual_patch_request("Đổi màu nền thành xanh nhạt")


def test_does_not_detect_patch_for_fresh_visual_request():
    assert not detect_visual_patch_request("Explain Kimi linear attention in charts")


def test_preferred_visual_tool_name_always_returns_structured():
    assert preferred_visual_tool_name() == "tool_generate_visual"


def test_visual_tool_requirement_chart_uses_structured_visual_tool():
    decision = resolve_visual_intent("Vẽ biểu đồ KPI theo tháng")
    requirement = build_visual_tool_requirement(
        decision,
        structured_visuals_enabled=True,
    )

    assert required_visual_tool_names(decision) == ("tool_generate_visual",)
    assert requirement.required_tool_names == ("tool_generate_visual",)
    assert [capability.lane for capability in requirement.required_capabilities] == [
        "structured_visual",
    ]


def test_visual_tool_requirement_simulation_requires_code_studio_tool():
    decision = resolve_visual_intent("Hãy mô phỏng vật lý con lắc có kéo thả chuột")
    requirement = build_visual_tool_requirement(
        decision,
        structured_visuals_enabled=True,
    )

    assert required_visual_tool_names(decision) == ("tool_create_visual_code",)
    assert requirement.required_tool_names == ("tool_create_visual_code",)
    assert [capability.lane for capability in requirement.required_capabilities] == [
        "code_studio",
    ]


def test_visual_tool_requirement_artifact_requires_code_studio_tool():
    decision = resolve_visual_intent("Tạo một mini app HTML để nhúng vào LMS")
    requirement = build_visual_tool_requirement(
        decision,
        structured_visuals_enabled=True,
    )

    assert decision.presentation_intent == "artifact"
    assert required_visual_tool_names(decision) == ("tool_create_visual_code",)
    assert requirement.required_tool_names == ("tool_create_visual_code",)


def test_visual_tool_capability_inventory_includes_modern_and_legacy_tools():
    assert visual_tool_capability_names() == frozenset({
        "tool_generate_visual",
        "tool_create_visual_code",
        "tool_generate_mermaid",
        "tool_generate_chart",
        "tool_generate_interactive_chart",
    })
    assert visual_tool_capability_names(include_legacy=False) == frozenset({
        "tool_generate_visual",
        "tool_create_visual_code",
        "tool_generate_mermaid",
    })


def test_merge_quality_profile_prefers_higher_bar():
    assert merge_quality_profile("standard", "premium") == "premium"
    assert merge_quality_profile("draft", None) == "draft"


def test_recommended_visual_thinking_effort_escalates_premium_simulation():
    effort = recommended_visual_thinking_effort(
        "H\u00e3y m\u00f4 ph\u1ecfng v\u1eadt l\u00fd con l\u1eafc c\u00f3 th\u1ec3 k\u00e9o th\u1ea3",
    )
    assert effort == "max"


def test_recommended_visual_thinking_effort_uses_active_session_quality_for_patch():
    effort = recommended_visual_thinking_effort(
        "Gi\u1eef app hi\u1ec7n t\u1ea1i, \u0111\u1ed5i m\u00e0u n\u1ec1n th\u00e0nh xanh nh\u1ea1t",
        active_code_session={
            "session_id": "vs-sim-1",
            "studio_lane": "app",
            "quality_profile": "premium",
        },
    )
    assert effort == "max"


def test_detects_visual_patch_followup_with_unicode_vietnamese():
    assert detect_visual_patch_request("Bi\u1ebfn s\u01a1 \u0111\u1ed3 n\u00e0y th\u00e0nh 3 b\u01b0\u1edbc")
    assert detect_visual_patch_request("Gi\u1eef app hi\u1ec7n t\u1ea1i, th\u00eam slider \u0111i\u1ec1u ch\u1ec9nh tr\u1ecdng l\u1ef1c v\u00e0 ma s\u00e1t")
    assert detect_visual_patch_request("\u0110\u1ed5i m\u00e0u n\u1ec1n th\u00e0nh xanh nh\u1ea1t")


def test_filter_tools_for_visual_intent_drops_legacy_visual_tools():
    decision = resolve_visual_intent("Explain Kimi linear attention in charts")
    tools = [
        _Tool("tool_generate_interactive_chart"),
        _Tool("tool_generate_chart"),
        _Tool("tool_generate_visual"),
        _Tool("tool_web_search"),
    ]

    filtered = filter_tools_for_visual_intent(
        tools,
        decision,
        structured_visuals_enabled=True,
    )

    assert [tool.name for tool in filtered] == ["tool_generate_visual", "tool_web_search"]


def test_filter_tools_for_visual_intent_keeps_chart_lane_only():
    decision = resolve_visual_intent("Vẽ biểu đồ so sánh tốc độ các loại tàu container")
    tools = [
        _Tool("tool_create_visual_code"),
        _Tool("tool_generate_visual"),
        _Tool("tool_generate_mermaid"),
        _Tool("tool_generate_interactive_chart"),
        _Tool("tool_generate_chart"),
        _Tool("tool_web_search"),
    ]

    filtered = filter_tools_for_visual_intent(
        tools,
        decision,
        structured_visuals_enabled=True,
    )

    assert _tool_names(filtered) == ["tool_generate_visual", "tool_web_search"]


def test_filter_tools_for_visual_intent_keeps_app_lane_only():
    decision = resolve_visual_intent("Hãy mô phỏng vật lý con lắc có kéo thả chuột")
    tools = [
        _Tool("tool_generate_visual"),
        _Tool("tool_create_visual_code"),
        _Tool("tool_generate_mermaid"),
        _Tool("tool_web_search"),
    ]

    filtered = filter_tools_for_visual_intent(
        tools,
        decision,
        structured_visuals_enabled=True,
    )

    assert _tool_names(filtered) == ["tool_create_visual_code", "tool_web_search"]


def test_filter_tools_for_visual_intent_keeps_artifact_lane_only():
    decision = resolve_visual_intent("Tạo một mini app HTML để nhúng vào LMS")
    tools = [
        _Tool("tool_generate_visual"),
        _Tool("tool_create_visual_code"),
        _Tool("tool_generate_mermaid"),
        _Tool("tool_generate_interactive_chart"),
        _Tool("tool_web_search"),
    ]

    filtered = filter_tools_for_visual_intent(
        tools,
        decision,
        structured_visuals_enabled=True,
    )

    assert _tool_names(filtered) == ["tool_create_visual_code", "tool_web_search"]


def test_filter_tools_for_visual_intent_keeps_mermaid_lane_only():
    decision = resolve_visual_intent("Vẽ flowchart quy trình onboarding")
    tools = [
        _Tool("tool_generate_visual"),
        _Tool("tool_create_visual_code"),
        _Tool("tool_generate_interactive_chart"),
        _Tool("tool_generate_chart"),
        _Tool("tool_generate_mermaid"),
        _Tool("tool_web_search"),
    ]

    filtered = filter_tools_for_visual_intent(
        tools,
        decision,
        structured_visuals_enabled=True,
    )

    assert _tool_names(filtered) == ["tool_generate_mermaid", "tool_web_search"]


def test_filter_tools_for_visual_intent_leaves_text_turn_tools_alone():
    decision = resolve_visual_intent("Visual Studio Code khác Visual Basic thế nào?")
    tools = [
        _Tool("tool_generate_visual"),
        _Tool("tool_create_visual_code"),
        _Tool("tool_web_search"),
        _Tool("tool_knowledge_search"),
    ]

    filtered = filter_tools_for_visual_intent(
        tools,
        decision,
        structured_visuals_enabled=True,
    )

    assert _tool_names(filtered) == _tool_names(tools)
