from app.engine.tools.visual_code_runtime_contract import (
    resolve_visual_code_runtime_contract,
)


def test_visual_code_contract_resolves_simulation_app_lane() -> None:
    contract = resolve_visual_code_runtime_contract(
        presentation_intent="code_studio_app",
        studio_lane="app",
        artifact_kind="html_app",
        requested_visual_type="simulation",
        quality_profile="premium",
        code_studio_version="3",
    )

    assert contract.presentation_intent == "code_studio_app"
    assert contract.studio_lane == "app"
    assert contract.artifact_kind == "html_app"
    assert contract.requested_visual_type == "simulation"
    assert contract.resolved_visual_type == "simulation"
    assert contract.renderer_kind == "app"
    assert contract.shell_variant == "immersive"
    assert contract.patch_strategy == "app_state"
    assert contract.quality_profile == "premium"
    assert contract.code_studio_version == 3
    assert contract.runtime_manifest is not None
    assert contract.runtime_manifest["ui_runtime"] == "html"
    assert contract.runtime_manifest["file_export"] is False
    assert contract.runtime_manifest["shareability"] == "session"
    assert contract.runtime_manifest["app_category"] == "simulation"
    assert "state_model" in contract.runtime_manifest["app_reject_if_missing"]
    assert contract.payload_metadata()["code_studio_version"] == 3
    assert contract.payload_metadata()["app_category"] == "simulation"


def test_visual_code_contract_resolves_artifact_lane_as_inline_html() -> None:
    contract = resolve_visual_code_runtime_contract(
        presentation_intent="artifact",
        studio_lane="artifact",
        artifact_kind="document",
        requested_visual_type="interactive_table",
        quality_profile="standard",
    )

    assert contract.presentation_intent == "artifact"
    assert contract.studio_lane == "artifact"
    assert contract.artifact_kind == "document"
    assert contract.resolved_visual_type == "interactive_table"
    assert contract.renderer_kind == "inline_html"
    assert contract.shell_variant == "editorial"
    assert contract.patch_strategy == "replace_html"
    assert contract.runtime_manifest is None
    assert contract.payload_metadata()["presentation_intent"] == "artifact"
    assert contract.payload_metadata()["app_category"] == "artifact"


def test_visual_code_contract_marks_article_and_chart_lanes_blocked() -> None:
    article = resolve_visual_code_runtime_contract(
        presentation_intent="article_figure",
        requested_visual_type="comparison",
    )
    chart = resolve_visual_code_runtime_contract(
        presentation_intent="chart_runtime",
        requested_visual_type="chart",
    )

    assert article.is_blocked_for_code_studio is True
    assert chart.is_blocked_for_code_studio is True
    assert article.app_intent_contract is None
    assert chart.app_intent_contract is None
    assert "app_category" not in article.payload_metadata()
    assert "app_category" not in chart.payload_metadata()


def test_visual_code_contract_sanitizes_unknown_runtime_values() -> None:
    contract = resolve_visual_code_runtime_contract(
        presentation_intent="text",
        studio_lane="detached",
        artifact_kind="unknown",
        requested_visual_type="freeform_untyped",
        quality_profile="heroic",
        code_studio_version="bad",
    )

    assert contract.presentation_intent == "code_studio_app"
    assert contract.studio_lane == "app"
    assert contract.artifact_kind == "html_app"
    assert contract.requested_visual_type == "freeform_untyped"
    assert contract.resolved_visual_type == "concept"
    assert contract.renderer_kind == "app"
    assert contract.quality_profile == "standard"
    assert contract.code_studio_version == 0
    assert contract.payload_metadata()["presentation_intent"] == "code_studio_app"
    assert contract.payload_metadata()["app_category"] == "mini_tool"
    assert "code_studio_version" not in contract.payload_metadata()


def test_visual_code_contract_resolves_quiz_app_category() -> None:
    contract = resolve_visual_code_runtime_contract(
        presentation_intent="code_studio_app",
        studio_lane="app",
        artifact_kind="html_app",
        requested_visual_type="quiz",
        user_query="Tao mot interactive quiz widget trong chat",
    )

    assert contract.app_intent_contract is not None
    assert contract.app_intent_contract.category == "quiz"
    assert contract.payload_metadata()["app_category"] == "quiz"
    assert "question_bank" in contract.payload_metadata()["app_reject_if_missing"]


def test_visual_code_contract_resolves_dashboard_from_query() -> None:
    contract = resolve_visual_code_runtime_contract(
        presentation_intent="code_studio_app",
        studio_lane="app",
        artifact_kind="html_app",
        requested_visual_type="react_app",
        user_query="Tao dashboard app HTML cho chien dich nay",
    )

    assert contract.app_intent_contract is not None
    assert contract.app_intent_contract.category == "dashboard"
    assert contract.runtime_manifest is not None
    assert "filter" in contract.runtime_manifest["app_required_controls"]
