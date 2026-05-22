"""
Sprint 229: Rich Visual Widget Generator tests.

Tests visual tools: tool_generate_visual, tool_create_visual_code, and all visual type builders.
"""

import json
import pytest


# =============================================================================
# Builder unit tests
# =============================================================================


class TestComparisonVisual:
    """Test comparison (side-by-side) visual generation."""

    def test_basic_comparison(self):
        from app.engine.tools.visual_tools import _build_comparison_html

        spec = {
            "left": {"title": "Method A", "subtitle": "O(n²)", "items": ["Slow", "Simple"]},
            "right": {"title": "Method B", "subtitle": "O(n)", "items": ["Fast", "Complex"]},
        }
        html = _build_comparison_html(spec, "Comparison Test")
        assert "<!DOCTYPE html>" in html
        assert "Method A" in html
        assert "Method B" in html
        assert "O(n²)" in html
        assert "comparison" in html  # CSS class

    def test_comparison_with_note(self):
        from app.engine.tools.visual_tools import _build_comparison_html

        spec = {
            "left": {"title": "A", "items": []},
            "right": {"title": "B", "items": []},
            "note": "Key takeaway here",
        }
        html = _build_comparison_html(spec, "")
        assert "Key takeaway here" in html

    def test_comparison_escapes_html(self):
        from app.engine.tools.visual_tools import _build_comparison_html

        spec = {
            "left": {"title": "<script>alert(1)</script>", "items": []},
            "right": {"title": "Safe", "items": []},
        }
        html = _build_comparison_html(spec, "")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestProcessVisual:
    """Test process (step flow) visual generation."""

    def test_basic_process(self):
        from app.engine.tools.visual_tools import _build_process_html

        spec = {
            "steps": [
                {"title": "Step 1", "description": "Do this"},
                {"title": "Step 2", "description": "Then that"},
                {"title": "Step 3", "description": "Finally"},
            ],
        }
        html = _build_process_html(spec, "Process Flow")
        assert "Step 1" in html
        assert "Step 2" in html
        assert "Step 3" in html
        assert "process" in html  # CSS class
        assert "step-arrow" in html  # arrows between steps

    def test_vertical_direction(self):
        from app.engine.tools.visual_tools import _build_process_html

        spec = {"steps": [{"title": "A"}, {"title": "B"}], "direction": "vertical"}
        html = _build_process_html(spec, "")
        assert "vertical" in html


class TestMatrixVisual:
    """Test matrix (color grid) visual generation."""

    def test_basic_matrix(self):
        from app.engine.tools.visual_tools import _build_matrix_html

        spec = {
            "rows": ["Q1", "Q2"],
            "cols": ["K1", "K2"],
            "cells": [[0.9, 0.3], [0.1, 0.8]],
            "row_label": "Queries",
            "col_label": "Keys",
        }
        html = _build_matrix_html(spec, "Attention Matrix")
        assert "Q1" in html
        assert "K1" in html
        assert "Queries" in html
        assert "Keys" in html
        assert "matrix-grid" in html

    def test_matrix_with_values(self):
        from app.engine.tools.visual_tools import _build_matrix_html

        spec = {
            "rows": ["A"], "cols": ["B"],
            "cells": [[0.75]],
            "show_values": True,
        }
        html = _build_matrix_html(spec, "")
        assert "0.8" in html  # formatted to 1 decimal


class TestArchitectureVisual:
    """Test architecture (layered diagram) visual generation."""

    def test_basic_architecture(self):
        from app.engine.tools.visual_tools import _build_architecture_html

        spec = {
            "layers": [
                {"name": "Frontend", "components": ["React", "Tailwind"]},
                {"name": "Backend", "components": ["FastAPI", "LangGraph"]},
                {"name": "Database", "components": ["PostgreSQL", "Neo4j"]},
            ]
        }
        html = _build_architecture_html(spec, "System Architecture")
        assert "Frontend" in html
        assert "Backend" in html
        assert "React" in html
        assert "FastAPI" in html
        assert "arch-layer" in html
        assert "arch-arrow" in html  # arrows between layers


class TestConceptVisual:
    """Test concept map visual generation."""

    def test_basic_concept(self):
        from app.engine.tools.visual_tools import _build_concept_html

        spec = {
            "center": {"title": "Machine Learning", "description": "AI subset"},
            "branches": [
                {"title": "Supervised", "items": ["Classification", "Regression"]},
                {"title": "Unsupervised", "items": ["Clustering", "Dimensionality"]},
            ]
        }
        html = _build_concept_html(spec, "ML Overview")
        assert "Machine Learning" in html
        assert "Supervised" in html
        assert "Classification" in html
        assert "concept-center" in html


class TestInfographicVisual:
    """Test infographic visual generation."""

    def test_basic_infographic(self):
        from app.engine.tools.visual_tools import _build_infographic_html

        spec = {
            "stats": [
                {"value": "95%", "label": "Accuracy"},
                {"value": "2.3s", "label": "Latency"},
                {"value": "1M+", "label": "Users"},
            ],
            "sections": [
                {"title": "Highlight", "content": "Significant improvement over baseline."},
            ]
        }
        html = _build_infographic_html(spec, "Results")
        assert "95%" in html
        assert "Accuracy" in html
        assert "Significant improvement" in html
        assert "info-stat" in html


class TestChartVisual:
    """Test chart visual generation."""

    def test_chart_accepts_row_data_shape(self):
        from app.engine.tools.visual_tools import _build_chart_html

        spec = {
            "type": "bar",
            "data": [
                {"label": "Feeder", "value": 15},
                {"label": "Panamax", "value": 20},
                {"label": "ULCV", "value": 18},
            ],
            "caption": "Toc do khai thac trung binh.",
        }
        html = _build_chart_html(spec, "Container speed")
        assert "No chart data provided" not in html
        assert "Feeder" in html
        assert "Panamax" in html
        assert "ULCV" in html
        assert "Toc do khai thac trung binh." in html


# =============================================================================
# Tool integration tests
# =============================================================================


class TestToolGenerateVisual:
    """Test the structured visual payload tool."""

    def test_returns_visual_payload_json(self):
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "comparison",
            "spec_json": json.dumps({
                "left": {"title": "Softmax"},
                "right": {"title": "Linear"},
            }),
            "title": "Softmax vs Linear",
            "summary": "Quick comparison",
        })
        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.type == "comparison"
        assert payload.renderer_kind == "inline_html"
        assert payload.shell_variant == "editorial"
        assert payload.patch_strategy == "replace_html"
        assert payload.runtime == "sandbox_html"
        assert payload.title == "Softmax vs Linear"
        assert payload.summary == "Quick comparison"
        assert payload.visual_session_id.startswith("vs-comparison-")
        assert payload.figure_group_id.startswith("fg-comparison-")
        assert payload.figure_index == 1
        assert payload.figure_total == 1
        assert payload.pedagogical_role == "comparison"
        assert payload.chrome_mode == "editorial"
        assert payload.claim == "Quick comparison"
        assert payload.scene["kind"] == "comparison"
        assert payload.scene["render_surface"] == "html"
        assert payload.scene["state_model"]["kind"] == "semantic_svg_scene"
        assert payload.controls[0]["id"] == "focus_side"
        assert payload.annotations
        assert payload.lifecycle_event == "visual_open"
        assert payload.fallback_html is not None
        assert payload.metadata["source_tool"] == "tool_generate_visual"

    def test_returns_grouped_figure_payloads_for_article_flow(self):
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "comparison",
            "spec_json": json.dumps({
                "figures": [
                    {
                        "type": "comparison",
                        "title": "Chi phi tinh toan",
                        "summary": "Softmax tang nhanh hon khi context dai ra.",
                        "claim": "Figure 1 chot van de chi phi tinh toan.",
                        "pedagogical_role": "problem",
                        "spec": {
                            "left": {"title": "Softmax attention"},
                            "right": {"title": "Linear attention"},
                        },
                    },
                    {
                        "type": "process",
                        "title": "Co che cap nhat bo nho",
                        "pedagogical_role": "mechanism",
                        "spec": {
                            "steps": [
                                {"title": "Doc token moi"},
                                {"title": "Cap nhat state S"},
                                {"title": "Sinh dau ra"},
                            ],
                        },
                    },
                ],
            }),
            "title": "Giai thich Kimi Linear",
        })
        payloads = parse_visual_payloads(result)

        assert len(payloads) == 2
        assert {payload.figure_index for payload in payloads} == {1, 2}
        assert {payload.figure_total for payload in payloads} == {2}
        assert len({payload.figure_group_id for payload in payloads}) == 1
        assert payloads[0].pedagogical_role == "problem"
        assert payloads[1].pedagogical_role == "mechanism"
        assert payloads[0].claim == "Figure 1 chot van de chi phi tinh toan."
        assert payloads[1].claim
        assert payloads[0].renderer_kind == "template"
        assert payloads[1].renderer_kind == "template"
        assert payloads[0].metadata["source_tool"] == "tool_generate_visual"
        assert payloads[1].metadata["source_tool"] == "tool_generate_visual"

    def test_supports_patch_operation_with_existing_session(self):
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "process",
            "spec_json": json.dumps({
                "steps": [{"title": "Step 1"}, {"title": "Step 2"}],
            }),
            "visual_session_id": "vs-process-123",
            "operation": "patch",
        })
        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.visual_session_id == "vs-process-123"
        assert payload.lifecycle_event == "visual_patch"
        assert payload.patch_strategy == "replace_html"
        assert payload.scene["kind"] == "process"

    def test_runtime_context_can_promote_followup_to_patch(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "preferred_visual_operation": "patch",
                "preferred_visual_session_id": "vs-comparison-keep",
            },
        )
        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "comparison",
                "spec_json": json.dumps({
                    "left": {"title": "Before"},
                    "right": {"title": "After"},
                }),
                "operation": "open",
            })

        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.visual_session_id == "vs-comparison-keep"
        assert payload.lifecycle_event == "visual_patch"

    def test_runtime_context_overrides_hallucinated_patch_session_id(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "preferred_visual_operation": "patch",
                "preferred_visual_session_id": "vs-comparison-keep",
            },
        )
        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "process",
                "spec_json": json.dumps({
                    "steps": [{"title": "One"}, {"title": "Two"}, {"title": "Three"}],
                }),
                "operation": "patch",
                "visual_session_id": "hallucinated-new-session",
            })

        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.visual_session_id == "vs-comparison-keep"
        assert payload.lifecycle_event == "visual_patch"

    def test_rejects_removed_legacy_sandbox_types(self):
        from app.engine.tools.visual_tools import tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "simulation",
            "spec_json": json.dumps({
                "html": "<div>Sim</div>",
                "ui_runtime": "html",
            }),
        })
        assert "Error" in result
        assert "simulation" in result

    def test_supports_inline_html_renderer(self):
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "concept",
            "spec_json": json.dumps({
                "html": "<section><h1>Custom inline visual</h1></section>",
            }),
            "renderer_kind": "inline_html",
        })
        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.renderer_kind == "inline_html"
        assert payload.patch_strategy == "replace_html"
        assert payload.fallback_html is not None

    def test_runtime_context_prefers_inline_html_for_chart_runtime_when_llm_codegen_enabled(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-chart-inline-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "inline_html",
                "visual_intent_reason": "chart-runtime",
                "presentation_intent": "chart_runtime",
                "visual_user_query": "Ve bieu do so sanh toc do cac loai tau container",
                "visual_requested_type": "chart",
                "preferred_render_surface": "svg",
                "planning_profile": "chart_svg",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "chart",
                "spec_json": json.dumps({
                    "chart_type": "bar",
                    "labels": ["Feeder", "Panamax", "Neo-Panamax"],
                    "datasets": [
                        {"label": "Speed", "data": [18, 22, 24]},
                    ],
                }),
                "title": "Toc do tau container",
                "summary": "So sanh toc do danh nghia giua cac nhom tau container.",
            })

        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.renderer_kind == "inline_html"
        assert payload.patch_strategy == "replace_html"
        assert payload.runtime == "sandbox_html"
        assert payload.scene["render_surface"] == "svg"
        assert payload.fallback_html is not None
        assert payload.artifact_handoff_available is True
        assert payload.artifact_handoff_mode == "followup_prompt"
        assert payload.artifact_handoff_label == "Mo thanh Artifact"
        assert payload.artifact_handoff_prompt is not None
        assert "artifact" in payload.artifact_handoff_prompt.lower()

    def test_runtime_context_auto_groups_explanatory_template_visuals(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-article-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "template",
                "visual_intent_reason": "chart-template",
                "visual_user_query": "Explain Kimi linear attention in charts",
                "visual_requested_type": "chart",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "chart",
                "spec_json": json.dumps({
                    "chart_type": "line",
                    "labels": ["1k", "4k", "16k", "64k"],
                    "datasets": [
                        {"label": "Softmax", "data": [1, 16, 256, 4096]},
                        {"label": "Linear", "data": [1, 4, 16, 64]},
                    ],
                }),
                "title": "Compute cost vs context length",
                "summary": "Softmax tang nhanh hon Linear khi context dai len.",
            })

        payloads = parse_visual_payloads(result)

        assert len(payloads) == 2
        assert payloads[0].figure_total == 2
        assert payloads[1].figure_total == 2
        assert payloads[0].type == "chart"
        assert payloads[1].type == "infographic"
        assert payloads[0].renderer_kind == "template"
        assert payloads[1].renderer_kind == "template"
        assert payloads[0].pedagogical_role == "benchmark"
        assert payloads[1].pedagogical_role == "conclusion"

    def test_runtime_context_can_plan_three_figures_for_dense_stepwise_explanation(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-article-3",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "template",
                "visual_intent_reason": "chart-template",
                "visual_user_query": "Explain Kimi linear attention in charts step by step with mechanism and benchmark",
                "visual_requested_type": "chart",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "chart",
                "spec_json": json.dumps({
                    "chart_type": "line",
                    "labels": ["1k", "4k", "16k", "64k", "256k", "1M"],
                    "datasets": [
                        {"label": "Softmax", "data": [1, 16, 256, 4096, 65536, 1048576]},
                        {"label": "Linear", "data": [1, 4, 16, 64, 256, 1024]},
                    ],
                }),
                "title": "Compute cost vs context length",
                "summary": "Softmax tang nhanh hon Linear khi context dai len.",
            })

        payloads = parse_visual_payloads(result)

        assert len(payloads) == 3
        assert [payload.figure_total for payload in payloads] == [3, 3, 3]
        assert [payload.type for payload in payloads] == ["chart", "infographic", "infographic"]
        assert all(payload.renderer_kind == "template" for payload in payloads)
        assert [payload.pedagogical_role for payload in payloads] == ["benchmark", "mechanism", "conclusion"]

    def test_runtime_context_keeps_simple_template_visual_single_when_scope_is_narrow(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-article-simple-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "template",
                "visual_intent_reason": "comparison",
                "visual_user_query": "So sanh nhanh TCP va UDP",
                "visual_requested_type": "comparison",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "comparison",
                "spec_json": json.dumps({
                    "left": {"title": "TCP"},
                    "right": {"title": "UDP"},
                }),
                "title": "TCP vs UDP",
                "summary": "Dat TCP canh UDP de thay su khac nhau co ban.",
            })

        payloads = parse_visual_payloads(result)

        assert len(payloads) == 1
        assert payloads[0].figure_total == 1
        assert payloads[0].type == "comparison"

    def test_runtime_context_rejects_removed_legacy_type_in_app_mode(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-app-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "app",
                "visual_intent_reason": "app-request",
                "visual_user_query": "Hay mo phong vat ly con lac",
                "visual_requested_type": "simulation",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "simulation",
                "spec_json": json.dumps({
                    "html": "<div>Sim</div>",
                    "ui_runtime": "html",
                }),
            })

        assert "Error" in result
        assert "simulation" in result

    def test_runtime_context_auto_groups_infographic_explanations(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-article-infographic-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "template",
                "visual_intent_reason": "article-figure",
                "visual_user_query": "Explain Kimi linear attention in charts",
                "visual_requested_type": "infographic",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "infographic",
                "spec_json": json.dumps({
                    "sections": [
                        {"title": "Van de", "content": "Softmax can ma tran day du O(n^2)."},
                        {"title": "Co che", "content": "Linear attention chuyen sang running state."},
                        {"title": "Ket qua", "content": "Context dai hon voi chi phi gon hon."},
                    ],
                }),
                "title": "Co che Linear Attention cua Kimi",
                "summary": "Ba diem nhan: van de, co che, va ket qua.",
            })

        payloads = parse_visual_payloads(result)

        assert len(payloads) == 2
        assert payloads[0].figure_total == 2
        assert payloads[1].figure_total == 2
        assert payloads[0].type == "infographic"
        assert payloads[1].type == "infographic"
        assert payloads[0].renderer_kind == "template"
        assert payloads[1].renderer_kind == "template"

    def test_runtime_context_does_not_auto_group_patch_turn(self):
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual

        runtime = build_tool_runtime_context(
            session_id="session-patch-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "template",
                "visual_intent_reason": "comparison",
                "visual_user_query": "Giu visual hien tai va highlight bottleneck",
                "preferred_visual_operation": "patch",
                "preferred_visual_session_id": "vs-comparison-keep",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "comparison",
                "spec_json": json.dumps({
                    "left": {"title": "Before"},
                    "right": {"title": "After"},
                }),
                "operation": "open",
            })

        payloads = parse_visual_payloads(result)

        assert len(payloads) == 1
        assert payloads[0].lifecycle_event == "visual_patch"
        assert payloads[0].visual_session_id == "vs-comparison-keep"

    def test_generates_natural_default_summary_and_takeaway_annotation(self):
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "comparison",
            "spec_json": json.dumps({
                "left": {"title": "Softmax attention"},
                "right": {"title": "Linear attention"},
            }),
            "title": "Softmax vs Linear",
        })
        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.summary == "Đặt Softmax attention cạnh Linear attention để thấy điểm khác biệt chính."
        assert payload.annotations[0]["title"] == "Điểm chốt"


class TestParseVisualPayload:
    """Test structured payload parsing helpers."""

    def test_parses_dict(self):
        from app.engine.tools.visual_tools import parse_visual_payload

        payload = parse_visual_payload({
            "id": "visual-123",
            "type": "process",
            "runtime": "svg",
            "title": "Pipeline",
            "summary": "Step flow",
            "spec": {"steps": [{"title": "Start"}]},
        })

        assert payload is not None
        assert payload.id == "visual-123"
        assert payload.type == "process"
        assert payload.renderer_kind == "template"
        assert payload.visual_session_id.startswith("vs-process-")
        assert payload.scene["kind"] == "process"

    def test_returns_none_for_legacy_widget_string(self):
        from app.engine.tools.visual_tools import parse_visual_payload

        assert parse_visual_payload("```widget\n<div>legacy</div>\n```") is None


class TestGetVisualTools:
    """Test feature gating."""

    def test_returns_empty_when_structured_disabled(self, monkeypatch):
        class FakeSettings:
            enable_chart_tools = True
            enable_structured_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import get_visual_tools
        tools = get_visual_tools()
        assert tools == []

    def test_returns_structured_tool_when_enabled(self, monkeypatch):
        class FakeSettings:
            enable_chart_tools = True
            enable_structured_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import get_visual_tools
        tools = get_visual_tools()
        assert [tool.name for tool in tools] == [
            "tool_generate_visual",
        ]

    def test_returns_empty_when_disabled(self, monkeypatch):
        class FakeSettings:
            enable_chart_tools = False
            enable_structured_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import get_visual_tools
        tools = get_visual_tools()
        assert tools == []


# =============================================================================
# Design system tests
# =============================================================================


class TestDesignSystem:
    """Test shared CSS and HTML structure."""

    def test_all_visuals_have_doctype(self):
        """Every visual should be a complete HTML document."""
        from app.engine.tools.visual_tools import _BUILDERS

        for visual_type, builder in _BUILDERS.items():
            # Minimal spec for each type
            specs = {
                "comparison": {"left": {"title": "A"}, "right": {"title": "B"}},
                "process": {"steps": [{"title": "S1"}]},
                "matrix": {"rows": ["R"], "cols": ["C"], "cells": [[0.5]]},
                "architecture": {"layers": [{"name": "L", "components": ["C"]}]},
                "concept": {"center": {"title": "X"}, "branches": []},
                "infographic": {"stats": [{"value": "1", "label": "L"}]},
                "chart": {"labels": ["A", "B"], "datasets": [{"label": "S", "data": [1, 2]}]},
                "timeline": {"events": [{"title": "E1", "date": "2026"}]},
                "map_lite": {"regions": [{"name": "R1", "value": "100"}]},
            }
            html = builder(specs[visual_type], "Test")
            assert "<!DOCTYPE html>" in html, f"{visual_type} missing DOCTYPE"
            assert "lang=\"vi\"" in html, f"{visual_type} missing lang=vi"

    def test_all_visuals_have_dark_mode(self):
        """Every visual should include dark mode CSS."""
        from app.engine.tools.visual_tools import _DESIGN_CSS

        assert "prefers-color-scheme: dark" in _DESIGN_CSS

    def test_html_escaping_in_text_types(self):
        """XSS protection: user content in text-based types must be escaped."""
        from app.engine.tools.visual_tools import _BUILDERS

        xss = "<img src=x onerror=alert(1)>"
        # Only test types that render user text (not simulation which takes JS code)
        specs = {
            "comparison": {"left": {"title": xss}, "right": {"title": "safe"}},
            "process": {"steps": [{"title": xss}]},
            "matrix": {"rows": [xss], "cols": ["C"], "cells": [["v"]]},
            "architecture": {"layers": [{"name": xss, "components": [xss]}]},
            "concept": {"center": {"title": xss}, "branches": [{"title": xss, "items": [xss]}]},
            "infographic": {"stats": [{"value": xss, "label": xss}]},
            "chart": {"labels": [xss], "datasets": [{"label": xss, "data": [1]}]},
            "timeline": {"events": [{"title": xss, "date": xss}]},
            "map_lite": {"regions": [{"name": xss, "value": xss}]},
        }
        for visual_type in specs:
            builder = _BUILDERS[visual_type]
            html = builder(specs[visual_type], "Test")
            assert "<img src=x" not in html, f"{visual_type} has XSS vulnerability"
            assert "&lt;img" in html, f"{visual_type} did not escape HTML"


class TestPromptLoaderVisualTiers:
    """Test that prompt_loader renders the new 3-tier visual structure."""

    def test_prompt_includes_visual_section(self):
        from app.prompts.prompt_loader import PromptLoader

        loader = PromptLoader()
        prompt = loader.build_system_prompt("tutor", "Test User")
        assert (
            "INLINE VISUAL" in prompt
            or "RICH VISUAL" in prompt
            or "VISUAL" in prompt
            or "tool_generate_visual" in prompt
        )

    def test_prompt_includes_chart_section(self):
        from app.prompts.prompt_loader import PromptLoader

        loader = PromptLoader()
        prompt = loader.build_system_prompt("tutor", "Test User")
        assert "BIỂU ĐỒ TƯƠNG TÁC" in prompt or "tool_generate_interactive_chart" in prompt


# =============================================================================
# New builder tests (chart, timeline, map_lite)
# =============================================================================


class TestChartVisual:
    """Test chart (SVG bar/line) visual generation."""

    def test_basic_bar_chart(self):
        from app.engine.tools.visual_tools import _build_chart_html

        spec = {
            "labels": ["Q1", "Q2", "Q3"],
            "datasets": [{"label": "Revenue", "data": [100, 200, 150]}],
        }
        html = _build_chart_html(spec, "Revenue Chart")
        assert "<!DOCTYPE html>" in html
        assert "Revenue" in html
        assert "Q1" in html
        assert "<svg" in html
        assert "chart-legend" in html

    def test_line_chart(self):
        from app.engine.tools.visual_tools import _build_chart_html

        spec = {
            "chart_type": "line",
            "labels": ["Jan", "Feb"],
            "datasets": [{"label": "Growth", "data": [10, 20]}],
        }
        html = _build_chart_html(spec, "Growth")
        assert "<path" in html  # line path
        assert "<circle" in html  # data points

    def test_multi_dataset_chart(self):
        from app.engine.tools.visual_tools import _build_chart_html

        spec = {
            "labels": ["A", "B"],
            "datasets": [
                {"label": "Series 1", "data": [10, 20]},
                {"label": "Series 2", "data": [15, 25]},
            ],
        }
        html = _build_chart_html(spec, "Multi")
        assert "Series 1" in html
        assert "Series 2" in html

    def test_empty_chart(self):
        from app.engine.tools.visual_tools import _build_chart_html

        html = _build_chart_html({}, "Empty")
        assert "No chart data" in html


class TestTimelineVisual:
    """Test timeline visual generation."""

    def test_basic_timeline(self):
        from app.engine.tools.visual_tools import _build_timeline_html

        spec = {
            "events": [
                {"title": "Founded", "date": "2020", "description": "Company started"},
                {"title": "Series A", "date": "2022", "description": "Raised funding"},
            ],
        }
        html = _build_timeline_html(spec, "Company History")
        assert "<!DOCTYPE html>" in html
        assert "Founded" in html
        assert "2020" in html
        assert "Company started" in html
        assert "timeline" in html
        assert "tl-event" in html

    def test_timeline_uses_steps_fallback(self):
        from app.engine.tools.visual_tools import _build_timeline_html

        spec = {"steps": [{"title": "Step 1"}, {"title": "Step 2"}]}
        html = _build_timeline_html(spec, "")
        assert "Step 1" in html
        assert "Step 2" in html


class TestMapLiteVisual:
    """Test map_lite (region cards) visual generation."""

    def test_basic_map_lite(self):
        from app.engine.tools.visual_tools import _build_map_lite_html

        spec = {
            "regions": [
                {"name": "North", "value": "1.2M", "description": "Northern region"},
                {"name": "South", "value": "800K", "description": "Southern region"},
            ],
        }
        html = _build_map_lite_html(spec, "Population")
        assert "<!DOCTYPE html>" in html
        assert "North" in html
        assert "1.2M" in html
        assert "Northern region" in html
        assert "map-grid" in html

    def test_map_lite_with_tags(self):
        from app.engine.tools.visual_tools import _build_map_lite_html

        spec = {
            "regions": [
                {"name": "Zone A", "value": "High", "tags": ["priority", "active"]},
            ],
        }
        html = _build_map_lite_html(spec, "Zones")
        assert "priority" in html
        assert "active" in html
        assert "map-card-tag" in html


# =============================================================================
# Code-gen routing tests
# =============================================================================


class TestCodeGenRouting:
    """Test enable_code_gen_visuals feature flag routing."""

    def test_flag_off_keeps_template_default(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _infer_renderer_kind

        assert _infer_renderer_kind("comparison", {}) == "template"
        assert _infer_renderer_kind("architecture", {}) == "template"

    def test_flag_on_keeps_explanatory_types_on_template(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _infer_renderer_kind

        assert _infer_renderer_kind("comparison", {}) == "template"
        assert _infer_renderer_kind("process", {}) == "template"
        assert _infer_renderer_kind("architecture", {}) == "template"
        assert _infer_renderer_kind("concept", {}) == "template"
        assert _infer_renderer_kind("infographic", {}) == "template"
        assert _infer_renderer_kind("matrix", {}) == "template"
        assert _infer_renderer_kind("chart", {}) == "template"
        assert _infer_renderer_kind("timeline", {}) == "template"
        assert _infer_renderer_kind("map_lite", {}) == "template"

    def test_flag_on_unknown_types_fall_through_to_template(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _infer_renderer_kind

        # Types not in _BUILDERS fall through to template
        assert _infer_renderer_kind("simulation", {}) == "template"
        assert _infer_renderer_kind("quiz", {}) == "template"
        assert _infer_renderer_kind("react_app", {}) == "template"

    def test_explicit_renderer_kind_overrides_flag(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _infer_renderer_kind

        assert _infer_renderer_kind("comparison", {}, "template") == "template"

    def test_intent_resolver_prefers_inline_html_for_article_figures(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

        decision = resolve_visual_intent("so sanh TCP va UDP")
        assert decision.mode == "inline_html"
        assert decision.presentation_intent == "article_figure"
        assert decision.preferred_tool == "tool_generate_visual"
        assert decision.renderer_contract == "article_figure"

    def test_intent_resolver_keeps_inline_html_even_when_codegen_flag_off(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

        decision = resolve_visual_intent("so sanh TCP va UDP")
        assert decision.mode == "inline_html"

    def test_intent_resolver_does_not_upgrade_app_mode(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

        decision = resolve_visual_intent("mo phong vat ly con lac")
        assert decision.mode == "app"

    def test_intent_resolver_does_not_upgrade_text_mode(self, monkeypatch):
        class FakeSettings:
            enable_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

        decision = resolve_visual_intent("hello world")
        assert decision.mode == "text"


# =============================================================================
# Enhanced builder field tests
# =============================================================================


class TestEnhancedBuilderFields:
    """Test that upgraded builders render new spec fields."""

    def test_architecture_renders_description(self):
        from app.engine.tools.visual_tools import _build_architecture_html

        spec = {
            "layers": [
                {"name": "API", "description": "REST endpoints and routing", "components": ["FastAPI"]},
            ],
        }
        html = _build_architecture_html(spec, "")
        assert "REST endpoints and routing" in html
        assert "arch-layer-desc" in html

    def test_comparison_renders_highlight(self):
        from app.engine.tools.visual_tools import _build_comparison_html

        spec = {
            "left": {"title": "A", "items": []},
            "right": {"title": "B", "items": []},
            "highlight": "A is clearly better for performance",
        }
        html = _build_comparison_html(spec, "")
        assert "A is clearly better for performance" in html
        assert "comp-highlight" in html

    def test_concept_renders_branch_description(self):
        from app.engine.tools.visual_tools import _build_concept_html

        spec = {
            "center": {"title": "ML"},
            "branches": [
                {"title": "Supervised", "description": "Learns from labeled data", "items": ["SVM"]},
            ],
        }
        html = _build_concept_html(spec, "")
        assert "Learns from labeled data" in html
        assert "concept-branch-desc" in html

    def test_infographic_renders_highlights_and_takeaway(self):
        from app.engine.tools.visual_tools import _build_infographic_html

        spec = {
            "stats": [{"value": "99%", "label": "Accuracy"}],
            "highlights": ["Best in class", "Production ready"],
            "takeaway": "This model outperforms all baselines.",
        }
        html = _build_infographic_html(spec, "")
        assert "Best in class" in html
        assert "Production ready" in html
        assert "info-highlights" in html
        assert "This model outperforms all baselines" in html
        assert "info-takeaway" in html

    def test_process_renders_content_and_signals(self):
        from app.engine.tools.visual_tools import _build_process_html

        spec = {
            "steps": [
                {
                    "title": "Parse",
                    "description": "Parse input",
                    "content": "Uses recursive descent parser",
                    "signals": ["AST", "tokens"],
                },
            ],
        }
        html = _build_process_html(spec, "")
        assert "Uses recursive descent parser" in html
        assert "step-content" in html
        assert "AST" in html
        assert "step-signal" in html


# =============================================================================
# Phase 4: LLM code_html tests
# =============================================================================


class TestCodeHtmlResolve:
    """Test _resolve_code_html helper."""

    def test_empty_code_html_returns_none(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _resolve_code_html

        assert _resolve_code_html("", "comparison", "T", {}) is None
        assert _resolve_code_html("   ", "comparison", "T", {}) is None

    def test_flag_off_ignores_code_html(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _resolve_code_html

        result = _resolve_code_html("<div>Custom</div>", "comparison", "T", {})
        assert result is None

    def test_wraps_body_in_design_system(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _resolve_code_html

        result = _resolve_code_html(
            '<div class="custom">Hello World</div>',
            "concept",
            "Test Title",
            {},
        )
        assert result is not None
        assert "<!DOCTYPE html>" in result
        assert "Hello World" in result
        assert "Test Title" in result  # title rendered
        assert "--accent" in result  # design system CSS vars

    def test_extracts_style_blocks(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _resolve_code_html

        code = '<style>.box{color:red}</style><div class="box">Hi</div>'
        result = _resolve_code_html(code, "concept", "", {})
        assert result is not None
        assert ".box{color:red}" in result
        assert '<div class="box">Hi</div>' in result

    def test_full_html_document_passthrough(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import _resolve_code_html

        full_doc = "<!DOCTYPE html><html><body><p>Full doc</p></body></html>"
        result = _resolve_code_html(full_doc, "concept", "T", {})
        assert result == full_doc  # returned as-is


class TestCodeHtmlToolIntegration:
    """Test code_html param in tool_generate_visual."""

    def test_code_html_produces_inline_html_payload(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
            enable_code_gen_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "architecture",
            "spec_json": json.dumps({"layers": [{"name": "L1", "components": ["C1"]}]}),
            "title": "Custom Arch",
            "summary": "LLM-generated HTML",
            "code_html": '<style>.custom{color:var(--accent)}</style><div class="custom">Custom SVG diagram here</div>',
        })
        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.renderer_kind == "inline_html"
        assert payload.fallback_html is not None
        assert "Custom SVG diagram here" in payload.fallback_html
        assert ".custom{color:var(--accent)}" in payload.fallback_html
        assert "<!DOCTYPE html>" in payload.fallback_html

    def test_code_html_ignored_when_flag_off(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = False
            enable_code_gen_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payload, tool_generate_visual

        result = tool_generate_visual.invoke({
            "visual_type": "comparison",
            "spec_json": json.dumps({
                "left": {"title": "A"},
                "right": {"title": "B"},
            }),
            "title": "Test",
            "code_html": "<div>Should be ignored</div>",
        })
        payload = parse_visual_payload(result)

        assert payload is not None
        assert payload.renderer_kind == "inline_html"
        # fallback_html should be builder output, not code_html
        if payload.fallback_html:
            assert "Should be ignored" not in payload.fallback_html

    def test_code_html_skips_auto_grouping(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
            enable_code_gen_visuals = False

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope

        runtime = build_tool_runtime_context(
            session_id="session-codegen-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "visual_force_tool": True,
                "visual_intent_mode": "template",
                "visual_intent_reason": "chart-template",
                "presentation_intent": "chart_runtime",
                "renderer_contract": "chart_runtime",
                "visual_user_query": "Explain with charts",
                "visual_requested_type": "chart",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_generate_visual.invoke({
                "visual_type": "chart",
                "spec_json": json.dumps({"labels": ["A"], "datasets": [{"label": "S", "data": [1]}]}),
                "title": "Custom Chart",
                "code_html": '<svg><rect width="100" height="50" fill="var(--accent)"/></svg>',
            })

        payloads = parse_visual_payloads(result)
        assert len(payloads) == 1
        assert payloads[0].renderer_kind == "inline_html"
        assert payloads[0].patch_strategy == "replace_html"
        assert payloads[0].fallback_html is not None
        assert "<rect" in payloads[0].fallback_html


# =============================================================================
# tool_create_visual_code tests
# =============================================================================


class TestCreateVisualCodeTool:
    """Test tool_create_visual_code — dedicated code-gen visual tool."""

    def test_requires_code_html(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": "",
            "title": "Empty",
        })
        assert "Error" in result
        assert "BẮT BUỘC" in result

    def test_rejects_too_short_code_html(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": "<div>Hi</div>",  # Too short (< 50 chars)
            "title": "Short",
        })
        assert "Error" in result
        assert "quá ngắn" in result

    def test_rejects_when_flag_off(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = False
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": "<div>Hello</div>",
            "title": "Test",
        })
        assert "Error" in result

    def test_produces_code_studio_app_payload(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": '<style>.box{color:var(--accent);padding:20px;border:1.5px solid var(--border);border-radius:var(--radius);background:var(--bg2)}</style><div class="box">Hello World — visual content with real styling</div>',
            "title": "Test Visual",
        })
        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.renderer_kind == "app"
        assert payload.shell_variant == "immersive"
        assert payload.patch_strategy == "app_state"
        assert payload.title == "Test Visual"
        assert payload.presentation_intent == "code_studio_app"
        assert payload.renderer_contract == "host_shell"
        assert payload.studio_lane == "app"
        assert payload.fallback_html is not None
        assert "<!DOCTYPE html>" in payload.fallback_html
        assert "Hello World" in payload.fallback_html
        assert ".box" in payload.fallback_html

    def test_app_lane_never_returns_template_renderer_even_for_comparison_visual_type(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-comparison-app",
            user_id="user-1",
            user_role="admin",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "comparison",
            },
        )

        # Quality-gate-compliant HTML (score >= 6/10): CSS vars, dark/light,
        # controls, readouts, bridge, grid layout, sufficient depth
        _rich_html = "\n".join([
            "<style>",
            ":root { --bg: #0f172a; --fg: #e2e8f0; --accent: #38bdf8; --surface: #1e293b; --border: #475569; }",
            "@media (prefers-color-scheme: light) { :root { --bg: #f8fafc; --fg: #0f172a; } }",
            ".layout { display: grid; grid-template-columns: 1fr 300px; gap: 16px; padding: 16px; }",
            "@media (max-width: 768px) { .layout { grid-template-columns: 1fr; } }",
            ".box { padding: 20px; background: var(--surface); border-radius: 8px; }",
            ".readout { color: var(--accent); font-variant-numeric: tabular-nums; }",
            "</style>",
            '<div class="layout">',
            '  <div class="box">',
            "    <h2>Container Speed Explorer</h2>",
            "    <p>Comparison app with custom interaction surface and enough detail for validation.</p>",
            '    <div class="readout"><span id="val-a">0</span> vs <span id="val-b">0</span></div>',
            "  </div>",
            '  <div class="box">',
            '    <label>Speed A <input type="range" min="0" max="100" value="50" id="speed-a"></label>',
            '    <label>Speed B <input type="range" min="0" max="100" value="50" id="speed-b"></label>',
            "    <button id=\"reset\">Reset</button>",
            "  </div>",
            "</div>",
            "<script>",
            "(function() {",
            "  const a = document.getElementById('speed-a');",
            "  const b = document.getElementById('speed-b');",
            "  const va = document.getElementById('val-a');",
            "  const vb = document.getElementById('val-b');",
            "  function update() { va.textContent = a.value; vb.textContent = b.value; }",
            "  a.addEventListener('input', update);",
            "  b.addEventListener('input', update);",
            "  document.getElementById('reset').addEventListener('click', function() {",
            "    a.value = 50; b.value = 50; update();",
            "    window.WiiiVisualBridge?.reportResult?.('reset', {a:50,b:50}, 'Reset done', 'ok');",
            "  });",
            "  update();",
        ] + [f"  // line {i}" for i in range(80)] + [
            "})();",
            "</script>",
        ])

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": _rich_html,
                "title": "Container Speed Explorer",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.renderer_kind == "app"
        assert payload.shell_variant == "immersive"
        assert payload.patch_strategy == "app_state"
        assert payload.fallback_html is not None
        assert "Container Speed Explorer" in payload.fallback_html

    def test_artifact_lane_returns_inline_html_with_fallback(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-artifact",
            user_id="user-1",
            user_role="admin",
            metadata={
                "presentation_intent": "artifact",
                "studio_lane": "artifact",
                "artifact_kind": "html_app",
                "visual_requested_type": "comparison",
            },
        )

        # Quality-gate-compliant HTML (score >= 6/10)
        _rich_html = "\n".join([
            "<style>",
            ":root { --bg: #0f172a; --fg: #e2e8f0; --accent: #38bdf8; --surface: #1e293b; --border: #475569; }",
            "@media (prefers-color-scheme: light) { :root { --bg: #f8fafc; --fg: #0f172a; } }",
            ".layout { display: grid; grid-template-columns: 1fr 300px; gap: 16px; padding: 16px; }",
            "@media (max-width: 768px) { .layout { grid-template-columns: 1fr; } }",
            ".box { padding: 20px; background: var(--surface); border-radius: 8px; }",
            ".readout { color: var(--accent); }",
            "</style>",
            '<div class="layout">',
            '  <div class="box">',
            "    <h2>Embeddable HTML App</h2>",
            "    <p>Artifact shell with embeddable inline HTML output and complete fallback payload.</p>",
            '    <div class="readout" aria-live="polite"><span id="out">Ready</span></div>',
            "  </div>",
            '  <div class="box">',
            '    <label>Param A <input type="range" min="0" max="100" value="50" id="pa"></label>',
            '    <label>Param B <input type="range" min="0" max="100" value="50" id="pb"></label>',
            "    <button id=\"go\">Apply</button>",
            "  </div>",
            "</div>",
            "<script>",
            "(function() {",
            "  const pa = document.getElementById('pa');",
            "  const pb = document.getElementById('pb');",
            "  const out = document.getElementById('out');",
            "  function update() { out.textContent = 'A=' + pa.value + ' B=' + pb.value; }",
            "  pa.addEventListener('input', update);",
            "  pb.addEventListener('input', update);",
            "  document.getElementById('go').addEventListener('click', function() {",
            "    window.WiiiVisualBridge?.reportResult?.('apply', {a: pa.value, b: pb.value}, 'Applied', 'ok');",
            "  });",
            "  update();",
        ] + [f"  // padding line {i}" for i in range(80)] + [
            "})();",
            "</script>",
        ])

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": _rich_html,
                "title": "Embeddable HTML App",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.renderer_kind == "inline_html"
        assert payload.shell_variant == "editorial"
        assert payload.patch_strategy == "replace_html"
        assert payload.fallback_html is not None
        assert "<!DOCTYPE html>" in payload.fallback_html
        assert payload.artifact_handoff_available is False
        assert payload.artifact_handoff_mode == "none"
        assert payload.artifact_handoff_prompt is None

    def test_rejects_chart_runtime_lane_for_code_studio(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="chart-runtime-1",
            user_id="user-1",
            user_role="admin",
            metadata={
                "presentation_intent": "chart_runtime",
                "visual_requested_type": "chart",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": '<style>.box{height:100px;background:var(--bg2)}</style><div class="box">Chart-like content with enough length for validation and lane rejection.</div>',
                "title": "Wrong Lane",
            })

        assert "tool_generate_visual" in result

    def test_rejects_high_severity_ai_slop_before_preview(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": (
                "<style>"
                ".hero{padding:24px;background:#0f172a;color:white}"
                ".action{border:1px solid #475569;padding:12px}"
                "</style>"
                "<div class='hero'>"
                "<h2>" + "\U0001F680" + " Launch Panel</h2>"
                "<button class='action'>" + "\U0001F680" + " Start</button>"
                "<p>Interactive shell with enough visible content for validation.</p>"
                "</div>"
            ),
            "title": "Slop Gate",
        })

        assert "AI slop" in result
        assert "emoji_in_code_elements" in result

    def test_full_html_passthrough(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        full_html = '<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8"><style>body{font-family:system-ui;color:#1e293b}</style></head><body><h1>Full document with styling</h1><p>Content here</p></body></html>'
        result = tool_create_visual_code.invoke({
            "code_html": full_html,
            "title": "Full Doc",
        })
        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.fallback_html is not None
        assert "Full document with styling" in payload.fallback_html

    def test_code_studio_payload_metadata_canonicalizes_presentation_intent(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-ctx",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "text",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "renderer_contract": "host_shell",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": '<style>.box{padding:20px;background:var(--bg2);border-radius:var(--radius)}</style><div class="box">Pendulum app with enough detail for code studio output validation.</div>',
                "title": "Pendulum App",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.presentation_intent == "code_studio_app"
        assert payload.metadata is not None
        assert payload.metadata["presentation_intent"] == "code_studio_app"
        assert payload.metadata["studio_lane"] == "app"
        assert payload.metadata["artifact_kind"] == "html_app"
        assert payload.artifact_handoff_available is True
        assert payload.artifact_handoff_mode == "followup_prompt"
        assert payload.artifact_handoff_prompt is not None

    def test_code_studio_runtime_context_promotes_followup_to_patch(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-patch",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "renderer_contract": "host_shell",
                "preferred_visual_operation": "patch",
                "preferred_visual_session_id": "vs-pendulum-keep",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": '<style>.app{padding:20px;background:var(--bg2);border-radius:var(--radius)}</style><div class="app">Pendulum app upgraded with sliders, preserved as the same interactive session for patch testing.</div>',
                "title": "Pendulum App V2",
                "visual_session_id": "hallucinated-new-session",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.visual_session_id == "vs-pendulum-keep"
        assert payload.lifecycle_event == "visual_patch"
        assert payload.metadata is not None
        assert payload.metadata["presentation_intent"] == "code_studio_app"
        assert payload.metadata["studio_lane"] == "app"

    def test_code_studio_runtime_context_accepts_preferred_code_session_id(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-patch",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "renderer_contract": "host_shell",
                "preferred_visual_operation": "patch",
                "preferred_code_studio_session_id": "vs-pendulum-keep",
            },
        )

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": '<style>.app{padding:20px;background:var(--bg2);border-radius:var(--radius)}</style><div class="app">Pendulum app patched from active Code Studio context without opening a new session.</div>',
                "title": "Pendulum App V2",
                "visual_session_id": "hallucinated-new-session",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.visual_session_id == "vs-pendulum-keep"
        assert payload.lifecycle_event == "visual_patch"

    def test_rejects_premium_simulation_that_is_too_shallow(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-sim-shallow",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "simulation",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
            },
        )

        shallow_html = """
<style>
#canvas-container { position: relative; width: 600px; height: 400px; }
.ship { position: absolute; width: 40px; height: 20px; }
</style>
<div id="canvas-container"><div id="ship-a" class="ship"></div><div id="ship-b" class="ship"></div></div>
<div class="controls"><button onclick="runSimulation()">Chạy mô phỏng</button><button onclick="reset()">Đặt lại</button></div>
<script>
function reset(){ document.getElementById('msg').innerText = 'reset'; }
function runSimulation(){ document.getElementById('msg').innerText = 'run'; }
</script>
<div id="msg">Quy tắc 15</div>
"""

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": shallow_html,
                "title": "Mô phỏng Quy tắc 15",
            })

        assert "Error" in result
        assert "premium simulation" in result

    def test_rejects_premium_simulation_without_canvas_first_surface(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-sim-svg-only",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "simulation",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
                "preferred_render_surface": "canvas",
            },
        )

        svg_only_html = """
<style>
.sim-shell { display:grid; gap:16px; }
svg { width:100%; height:auto; background:var(--bg2); border-radius:var(--radius); }
</style>
<div class="sim-shell">
  <svg viewBox="0 0 640 320" role="img" aria-label="Rule 15 scene"><rect x="120" y="220" width="120" height="18" fill="var(--accent)" /><rect x="360" y="80" width="120" height="18" fill="var(--green)" /></svg>
  <label>CPA target <input id="cpa" type="range" min="0.1" max="2.0" value="0.8" step="0.1" /></label>
  <div class="readout" aria-live="polite">CPA: <span id="cpa-readout">0.8</span> nm</div>
</div>
<script>
let cpa = 0.8;
function step(){ cpa = Math.max(0.1, cpa - 0.01); requestAnimationFrame(step); }
requestAnimationFrame(step);
window.WiiiVisualBridge?.reportResult?.('simulation', { cpa }, 'tick', 'running');
</script>
"""

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": svg_only_html,
                "title": "Rule 15 SVG Only Simulation",
            })

        assert "Error" in result
        assert "Canvas-first runtime" in result

    def test_upgrades_shallow_pendulum_simulation_to_approved_scaffold(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-pendulum-upgrade",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "simulation",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
                "visual_user_query": "Build a mini pendulum physics app in chat with drag interaction.",
            },
        )

        shallow_html = """
<div class="pendulum-demo">
  <div id="ball"></div>
  <button onclick="run()">Run</button>
  <script>
    function run() { document.getElementById('ball').style.left = '120px'; }
  </script>
</div>
"""
        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": shallow_html,
                "title": "Mini Pendulum Physics App",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.renderer_kind == "app"
        assert payload.fallback_html is not None
        assert "pendulum-sim" in payload.fallback_html
        assert "length-slider" in payload.fallback_html
        assert 'input id="gravity-slider"' not in payload.fallback_html
        assert 'input id="damping-slider"' not in payload.fallback_html
        assert "requestAnimationFrame" in payload.fallback_html
        assert "reportResult" in payload.fallback_html

    def test_upgrades_pendulum_simulation_without_feedback_bridge(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-pendulum-feedback-upgrade",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "simulation",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
                "visual_user_query": "Build a premium pendulum simulation with drag interaction.",
            },
        )

        rich_but_silent_html = """
<style>
.sim-shell { display:grid; gap:16px; }
canvas { width:100%; height:260px; background:var(--bg2); border-radius:var(--radius); }
.controls { display:grid; gap:10px; }
.readout { font-size:13px; color:var(--text2); }
</style>
<div class="sim-shell">
  <canvas id="sim" width="640" height="320"></canvas>
  <div class="controls">
    <label>Gravity <input id="gravity" type="range" min="1" max="20" value="9.8" step="0.1" /></label>
    <label>Damping <input id="damping" type="range" min="0" max="0.2" value="0.03" step="0.01" /></label>
  </div>
  <div class="readout" aria-live="polite">Angle: <span id="theta">0.52</span> rad · Velocity: <span id="omega">0.00</span> rad/s</div>
</div>
<script>
const canvas = document.getElementById('sim');
const ctx = canvas.getContext('2d');
const gravityInput = document.getElementById('gravity');
const dampingInput = document.getElementById('damping');
let theta = 0.52;
let omega = 0;
let last = performance.now();
function frame(now){
  const deltaTime = Math.min((now - last) / 1000, 0.05);
  last = now;
  const gravity = Number(gravityInput.value);
  const damping = Number(dampingInput.value);
  const acceleration = -(gravity / 2) * Math.sin(theta) - damping * omega;
  omega += acceleration * deltaTime;
  theta += omega * deltaTime;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
</script>
"""

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": rich_but_silent_html,
                "title": "Pendulum Lab",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.fallback_html is not None
        assert "pendulum-sim" in payload.fallback_html
        assert "length-slider" in payload.fallback_html
        assert 'input id="gravity-slider"' not in payload.fallback_html
        assert "reportResult" in payload.fallback_html

    def test_upgraded_pendulum_scaffold_adds_requested_gravity_and_damping_controls(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-pendulum-parameter-patch",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "simulation",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
                "visual_user_query": "Keep the pendulum app and add gravity and damping sliders.",
            },
        )

        shallow_html = """
<div class="pendulum-demo">
  <div id="ball"></div>
</div>
"""
        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": shallow_html,
                "title": "Pendulum Lab",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.fallback_html is not None
        assert 'input id="gravity-slider"' in payload.fallback_html
        assert 'input id="damping-slider"' in payload.fallback_html
        assert 'input id="length-slider"' in payload.fallback_html

    def test_accepts_premium_simulation_with_surface_controls_and_live_readout(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True

        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        runtime = build_tool_runtime_context(
            session_id="code-studio-sim-rich",
            user_id="user-1",
            user_role="student",
            metadata={
                "presentation_intent": "code_studio_app",
                "studio_lane": "app",
                "artifact_kind": "html_app",
                "visual_requested_type": "simulation",
                "quality_profile": "premium",
                "renderer_contract": "host_shell",
            },
        )

        rich_html = """
<style>
.sim-shell { display:grid; gap:16px; }
canvas { width:100%; height:260px; background:var(--bg2); border-radius:var(--radius); }
.controls { display:grid; gap:10px; }
.readout { font-size:13px; color:var(--text2); }
</style>
<div class="sim-shell">
  <canvas id="sim" width="640" height="320"></canvas>
  <div class="controls">
    <label>Gravity <input id="gravity" type="range" min="1" max="20" value="9.8" step="0.1" /></label>
    <label>Friction <input id="friction" type="range" min="0" max="1" value="0.05" step="0.01" /></label>
    <button id="reset">Đặt lại</button>
  </div>
  <div class="readout" aria-live="polite">Góc lệch: <span id="theta">0.52</span> rad · Vận tốc: <span id="omega">0.00</span> rad/s</div>
</div>
<script>
const canvas = document.getElementById('sim');
const ctx = canvas.getContext('2d');
const gravityInput = document.getElementById('gravity');
const frictionInput = document.getElementById('friction');
const resetButton = document.getElementById('reset');
const thetaNode = document.getElementById('theta');
const omegaNode = document.getElementById('omega');
let theta = 0.52;
let omega = 0;
let last = performance.now();
function frame(now){
  const deltaTime = Math.min((now - last) / 1000, 0.05);
  last = now;
  const gravity = Number(gravityInput.value);
  const friction = Number(frictionInput.value);
  const acceleration = -(gravity / 2) * Math.sin(theta) - friction * omega;
  omega += acceleration * deltaTime;
  theta += omega * deltaTime;
  thetaNode.textContent = theta.toFixed(2);
  omegaNode.textContent = omega.toFixed(2);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  requestAnimationFrame(frame);
}
function report(reason){
  if (window.WiiiVisualBridge && typeof window.WiiiVisualBridge.reportResult === 'function') {
    window.WiiiVisualBridge.reportResult('simulation', {
      gravity: Number(gravityInput.value),
      friction: Number(frictionInput.value),
      theta,
      omega,
      reason,
    }, 'Simulation updated', 'success');
  }
}
gravityInput.addEventListener('input', () => report('gravity-change'));
frictionInput.addEventListener('input', () => report('friction-change'));
resetButton.addEventListener('click', () => report('reset'));
requestAnimationFrame(frame);
</script>
"""

        with tool_runtime_scope(runtime):
            result = tool_create_visual_code.invoke({
                "code_html": rich_html,
                "title": "Mô phỏng Con lắc",
            })

        payload = parse_visual_payload(result)
        assert payload is not None
        assert payload.renderer_kind == "app"
        assert payload.metadata is not None
        assert payload.metadata["quality_profile"] == "premium"
        assert payload.fallback_html is not None
        assert "reportResult" in payload.fallback_html

    def test_svg_content(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": '<svg viewBox="0 0 400 200" style="width:100%;height:auto"><rect x="10" y="10" width="380" height="180" rx="12" fill="var(--bg2)" stroke="var(--border)"/><circle cx="200" cy="100" r="40" fill="var(--accent)" opacity="0.8"/><text x="200" y="105" text-anchor="middle" fill="white" font-size="14">Visual</text></svg>',
            "title": "SVG Visual",
        })
        payload = parse_visual_payload(result)
        assert payload is not None
        assert "svg" in payload.fallback_html.lower()
        assert "circle" in payload.fallback_html

    def test_with_javascript(self, monkeypatch):
        class FakeSettings:
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import parse_visual_payload, tool_create_visual_code

        result = tool_create_visual_code.invoke({
            "code_html": '<style>#app{padding:20px;background:var(--bg2);border-radius:var(--radius);min-height:100px}</style><div id="app">Loading...</div><script>document.getElementById("app").textContent="Dynamic content loaded successfully";</script>',
            "title": "JS Visual",
        })
        payload = parse_visual_payload(result)
        assert payload is not None
        assert "<script>" in payload.fallback_html

    def test_included_in_get_visual_tools_when_flag_on(self, monkeypatch):
        class FakeSettings:
            enable_chart_tools = True
            enable_structured_visuals = True
            enable_llm_code_gen_visuals = True
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import get_visual_tools

        tools = get_visual_tools()
        tool_names = [t.name for t in tools]
        assert "tool_create_visual_code" in tool_names

    def test_not_included_when_flag_off(self, monkeypatch):
        class FakeSettings:
            enable_chart_tools = True
            enable_structured_visuals = True
            enable_llm_code_gen_visuals = False
        monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())
        from app.engine.tools.visual_tools import get_visual_tools

        tools = get_visual_tools()
        tool_names = [t.name for t in tools]
        assert "tool_create_visual_code" not in tool_names
