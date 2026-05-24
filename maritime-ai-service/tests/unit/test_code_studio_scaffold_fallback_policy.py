from types import SimpleNamespace

from app.engine.multi_agent.code_studio_scaffold_fallback_policy import (
    resolve_code_studio_scaffold_fallback,
)
from app.engine.multi_agent import code_studio_tool_rounds


def _visual_decision(**overrides):
    data = {
        "mode": "app",
        "force_tool": True,
        "presentation_intent": "code_studio_app",
        "preferred_tool": "tool_create_visual_code",
        "studio_lane": "app",
        "artifact_kind": "html_app",
        "visual_type": "simulation",
        "quality_profile": "premium",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_suppresses_generic_simulation_scaffold_fallback() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo mô phỏng hảo hán đối ẩm",
        reason="llm_prose_no_tool_call",
        resolve_visual_intent_fn=lambda _query: _visual_decision(),
        build_caption_fn=lambda _query: "caption should not be used",
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "app_requires_tool_generated_preview"
    assert decision.response_type == "code_studio_scaffold_suppressed"
    assert "template chung chung" in decision.response
    assert decision.metric_labels()["reason"] == "llm_prose_no_tool_call"


def test_suppresses_non_code_studio_visual_lane() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Vẽ biểu đồ giá dầu hôm nay",
        reason="stream_empty",
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            mode="inline_html",
            force_tool=True,
            presentation_intent="chart_runtime",
            preferred_tool="tool_generate_visual",
            studio_lane=None,
            visual_type="chart",
        ),
        build_caption_fn=lambda _query: "caption should not be used",
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "not_code_studio_tool_contract"
    assert decision.presentation_intent == "chart_runtime"
    assert decision.preferred_tool == "tool_generate_visual"


def test_suppresses_plain_text_misroute_without_sanitizing_to_app() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Chào Wiii",
        reason="node_outer_RuntimeError",
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            mode="text",
            force_tool=False,
            presentation_intent="text",
            preferred_tool=None,
            studio_lane=None,
            visual_type=None,
        ),
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "not_code_studio_tool_contract"
    assert decision.presentation_intent == "text"
    assert decision.preferred_tool == "none"


def test_allows_artifact_scaffold_fallback_with_contract_metadata() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo một mini app HTML để nhúng LMS",
        reason="ainvoke_exception",
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            presentation_intent="artifact",
            studio_lane="artifact",
            visual_type=None,
            quality_profile="premium",
        ),
        build_caption_fn=lambda _query: "artifact caption",
        detect_kind_fn=lambda _query: "default",
    )

    assert decision.engage_scaffold is True
    assert decision.response == "artifact caption"
    assert decision.policy_reason == "artifact_contract_allows_scaffold"
    assert decision.response_type == "code_studio_contract_scaffold_fallback"
    assert decision.presentation_intent == "artifact"
    assert decision.studio_lane == "artifact"
    assert decision.metric_labels()["kind"] == "default"


def test_resolution_failure_suppresses_scaffold() -> None:
    def broken_resolver(_query: str):
        raise RuntimeError("resolver unavailable")

    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo mô phỏng bất kỳ",
        reason="node_outer_RuntimeError",
        resolve_visual_intent_fn=broken_resolver,
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "visual_contract_resolution_failed"
    assert decision.presentation_intent == "unknown"


def test_manual_scaffold_helper_does_not_inject_tool_call_for_simulation() -> None:
    manual_tc, visible_caption, decision = code_studio_tool_rounds._build_scaffold_manual_tool_call(
        "Hay mo phong vat ly con lac co the keo tha",
        reason="stream_empty",
        state={},
    )

    assert manual_tc is None
    assert decision.engage_scaffold is False
    assert decision.policy_reason == "app_requires_tool_generated_preview"
    assert "template chung chung" in visible_caption


def test_manual_scaffold_helper_keeps_artifact_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        code_studio_tool_rounds,
        "build_code_studio_scaffold",
        lambda _query: "<html><body>artifact scaffold</body></html>",
    )

    manual_tc, visible_caption, decision = code_studio_tool_rounds._build_scaffold_manual_tool_call(
        "Tao mot mini app HTML de nhung vao LMS",
        reason="ainvoke_exception",
        state={},
    )

    assert decision.engage_scaffold is True
    assert manual_tc is not None
    assert manual_tc["name"] == "tool_create_visual_code"
    assert manual_tc["args"]["code_html"] == "<html><body>artifact scaffold</body></html>"
    assert visible_caption
