from app.engine.tools.code_studio_app_intent_contract import (
    infer_code_studio_app_category,
    resolve_code_studio_app_intent_contract,
)


def test_resolves_simulation_contract_from_visual_type() -> None:
    contract = resolve_code_studio_app_intent_contract(
        presentation_intent="code_studio_app",
        studio_lane="app",
        requested_visual_type="simulation",
    )

    assert contract.category == "simulation"
    assert contract.required_surface == "canvas_or_svg_scene"
    assert "state_model" in contract.reject_if_missing
    assert "teachable_controls" in contract.critic_focus


def test_resolves_quiz_contract_from_query() -> None:
    contract = resolve_code_studio_app_intent_contract(
        presentation_intent="code_studio_app",
        studio_lane="app",
        user_query="Tao mot interactive quiz widget HTML",
    )

    assert contract.category == "quiz"
    assert "question_bank" in contract.reject_if_missing
    assert "quiz_completed" in contract.required_feedback_hooks


def test_resolves_dashboard_contract_from_query() -> None:
    category = infer_code_studio_app_category(
        presentation_intent="code_studio_app",
        user_query="Tạo dashboard app HTML cho chiến dịch này",
    )

    assert category == "dashboard"


def test_normalizes_explicit_category_case_and_separator() -> None:
    category = infer_code_studio_app_category(
        presentation_intent="code_studio_app",
        app_category="Interactive-Table",
    )

    assert category == "interactive_table"


def test_artifact_contract_overrides_generic_html_app() -> None:
    contract = resolve_code_studio_app_intent_contract(
        presentation_intent="artifact",
        studio_lane="artifact",
        artifact_kind="html_app",
        requested_visual_type="react_app",
        user_query="Tao mot mini app HTML de nhung vao LMS",
    )

    assert contract.category == "artifact"
    assert "handoff_metadata" in contract.reject_if_missing
