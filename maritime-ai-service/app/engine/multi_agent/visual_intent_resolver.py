"""Resolve visual delivery lanes for article figures, chart runtime, apps, and artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.engine.multi_agent.visual_intent_presets import (
    build_app_decision_impl,
    build_article_figure_decision_impl,
    build_artifact_decision_impl,
    build_chart_runtime_decision_impl,
    build_diagram_decision_impl,
)
from app.engine.multi_agent.visual_intent_support import (
    LEGACY_VISUAL_TOOL_NAMES as _LEGACY_VISUAL_TOOL_NAMES,
    QUIZ_WIDGET_CUES as _QUIZ_WIDGET_CUES,
    SCENE_SIMULATION_CUES as _SCENE_SIMULATION_CUES,
    SIMULATION_APP_CUES as _SIMULATION_APP_CUES,
    SIMULATION_PATCH_CUES as _SIMULATION_PATCH_CUES,
    contains_any_impl,
    detect_visual_patch_request_impl,
    infer_figure_budget_impl,
    infer_followup_simulation_type_impl,
    looks_like_app_followup_patch_impl,
    looks_like_quiz_app_request_impl,
    looks_like_recipe_backed_simulation_impl,
    merge_quality_profile_impl,
    merge_thinking_effort_impl,
    metadata_value_impl,
    normalize_impl,
)
VisualMode = Literal["text", "mermaid", "template", "inline_html", "app"]
PresentationIntent = Literal["text", "article_figure", "chart_runtime", "code_studio_app", "artifact"]
StudioLane = Literal["app", "artifact", "widget"]
ArtifactKind = Literal["html_app", "code_widget", "search_widget", "document", "chart_widget"]
QualityProfile = Literal["draft", "standard", "premium"]
RendererContract = Literal["host_shell", "chart_runtime", "article_figure"]
ThinkingEffort = Literal["low", "medium", "high", "max"]
PreferredRenderSurface = Literal["svg", "canvas", "html", "video"]
PlanningProfile = Literal["article_svg", "chart_svg", "simulation_canvas", "artifact_html"]
CriticPolicy = Literal["none", "standard", "premium"]
LivingExpressionMode = Literal["subtle", "expressive"]



@dataclass(frozen=True)
class VisualIntentDecision:
    mode: VisualMode
    force_tool: bool = False
    visual_type: str | None = None
    reason: str = ""
    presentation_intent: PresentationIntent = "text"
    preferred_tool: str | None = None
    figure_budget: int = 1
    studio_lane: StudioLane | None = None
    artifact_kind: ArtifactKind | None = None
    quality_profile: QualityProfile = "standard"
    renderer_contract: RendererContract | None = None
    preferred_render_surface: PreferredRenderSurface = "svg"
    planning_profile: PlanningProfile = "article_svg"
    thinking_floor: ThinkingEffort = "medium"
    critic_policy: CriticPolicy = "standard"
    living_expression_mode: LivingExpressionMode = "expressive"
    renderer_kind_hint: str = ""


def _looks_like_quiz_app_request(query: str, normalized: str) -> bool:
    return looks_like_quiz_app_request_impl(
        query,
        normalized,
        contains_any=_contains_any,
    )


def _looks_like_recipe_backed_simulation(normalized: str) -> bool:
    return looks_like_recipe_backed_simulation_impl(
        normalized,
        contains_any=_contains_any,
    )


def _normalize(text: str) -> str:
    return normalize_impl(text)

def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return contains_any_impl(text, needles)

def _metadata_value(source: dict[str, Any] | None, *keys: str) -> str:
    return metadata_value_impl(source, *keys)

def merge_quality_profile(*values: Any) -> QualityProfile:
    return merge_quality_profile_impl(*values)  # type: ignore[return-value]

def merge_thinking_effort(base: str | None, recommended: str | None) -> str | None:
    return merge_thinking_effort_impl(base, recommended)

def _looks_like_app_followup_patch(normalized: str) -> bool:
    return looks_like_app_followup_patch_impl(
        normalized,
        contains_any=_contains_any,
        detect_visual_patch_request=detect_visual_patch_request,
    )

def _infer_followup_simulation_type(normalized: str) -> str | None:
    return infer_followup_simulation_type_impl(
        normalized,
        contains_any=_contains_any,
    )

def detect_visual_patch_request(query: str) -> bool:
    """Return True when the query looks like a follow-up edit to an existing visual."""
    return detect_visual_patch_request_impl(
        query,
        normalize=_normalize,
        contains_any=_contains_any,
    )

def preferred_visual_tool_name() -> str:
    """Return the preferred rich visual tool for the current runtime mode."""
    return "tool_generate_visual"


def recommended_visual_thinking_effort(
    query: str,
    *,
    active_code_session: dict[str, Any] | None = None,
) -> ThinkingEffort | None:
    normalized = _normalize(query)
    if not normalized:
        return None

    visual_decision = resolve_visual_intent(query)
    session_quality = _metadata_value(
        active_code_session,
        "quality_profile",
        "qualityProfile",
    )
    session_lane = _metadata_value(
        active_code_session,
        "studio_lane",
        "studioLane",
    )
    session_artifact_kind = _metadata_value(
        active_code_session,
        "artifact_kind",
        "artifactKind",
    )
    effective_quality = merge_quality_profile(visual_decision.quality_profile, session_quality)
    recommended_floor: ThinkingEffort | None = visual_decision.thinking_floor

    if visual_decision.presentation_intent == "code_studio_app":
        if visual_decision.visual_type == "simulation":
            if _looks_like_recipe_backed_simulation(normalized):
                recommended_floor = merge_thinking_effort(recommended_floor, "high")  # type: ignore[assignment]
            else:
                recommended_floor = merge_thinking_effort(  # type: ignore[assignment]
                    recommended_floor,
                    "max" if effective_quality == "premium" else "high",
                )
            return recommended_floor
        if effective_quality == "premium":
            return merge_thinking_effort(recommended_floor, "max")  # type: ignore[return-value]
        if session_lane in {"app", "widget"} or visual_decision.studio_lane in {"app", "widget"}:
            return merge_thinking_effort(recommended_floor, "high")  # type: ignore[return-value]

    if visual_decision.presentation_intent == "artifact":
        artifact_kind = visual_decision.artifact_kind or session_artifact_kind
        if artifact_kind in {"html_app", "code_widget", "search_widget"}:
            return merge_thinking_effort(recommended_floor, "high")  # type: ignore[return-value]

    if visual_decision.presentation_intent == "chart_runtime":
        if effective_quality == "premium":
            return merge_thinking_effort(recommended_floor, "high")  # type: ignore[return-value]
        return recommended_floor

    if visual_decision.presentation_intent == "article_figure":
        if visual_decision.mode == "inline_html" or effective_quality == "premium":
            return merge_thinking_effort(recommended_floor, "high")  # type: ignore[return-value]
        return recommended_floor

    if visual_decision.presentation_intent == "artifact":
        return recommended_floor

    return recommended_floor if visual_decision.force_tool else None


def _resolve_preferred_tool(
    visual_decision: VisualIntentDecision,
) -> str | None:
    if visual_decision.preferred_tool:
        return visual_decision.preferred_tool
    if visual_decision.mode in {"template", "inline_html", "app"}:
        return preferred_visual_tool_name()
    if visual_decision.mode == "mermaid":
        return "tool_generate_mermaid"
    return None


def required_visual_tool_names(
    visual_decision: VisualIntentDecision,
) -> tuple[str, ...]:
    """Return the visual tool names that should remain available for an explicit intent."""
    if not visual_decision.force_tool:
        return ()

    tool_name = _resolve_preferred_tool(visual_decision)
    return (tool_name,) if tool_name else ()


def filter_tools_for_visual_intent(
    tools: list[Any],
    visual_decision: VisualIntentDecision,
    *,
    structured_visuals_enabled: bool,
) -> list[Any]:
    """Reduce drift toward legacy visual tools when structured intent is explicit."""
    if not structured_visuals_enabled:
        return tools

    allowed_names = set(
        required_visual_tool_names(visual_decision)
    )
    if not allowed_names:
        return tools

    filtered: list[Any] = []
    for tool in tools:
        tool_name = str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "")
        if tool_name in allowed_names:
            filtered.append(tool)
            continue
        if tool_name in _LEGACY_VISUAL_TOOL_NAMES:
            continue
        filtered.append(tool)

    return filtered


def resolve_visual_intent(query: str) -> VisualIntentDecision:
    """Classify a user request into the most suitable visual delivery mode."""
    return _resolve_visual_intent_core(query)


def _infer_figure_budget(
    normalized: str,
    *,
    visual_type: str | None,
    presentation_intent: PresentationIntent,
) -> int:
    return infer_figure_budget_impl(
        normalized,
        visual_type=visual_type,
        presentation_intent=presentation_intent,
        contains_any=_contains_any,
    )

def _resolve_visual_intent_core(query: str) -> VisualIntentDecision:
    """Core classification logic (before code-gen upgrade)."""
    normalized = _normalize(query)
    if not normalized:
        return VisualIntentDecision(mode="text", reason="empty-query")

    if _contains_any(
        normalized,
        (
            "visual studio",
            "visual basic",
            "artifact repository",
        ),
    ):
        return VisualIntentDecision(mode="text", reason="false-positive-visual")

    if _contains_any(
        normalized,
        (
            "chain of thought",
            "chain-of-thought",
            "developer instruction",
            "developer instructions",
            "hidden reasoning",
            "internal reasoning",
            "raw reasoning",
            "reasoning tho",
            "system prompt",
            "visible thinking",
        ),
    ) or ("thinking" in normalized and _contains_any(normalized, ("an toan", "noi bo", "safety"))):
        return VisualIntentDecision(mode="text", reason="reasoning-safety-text")

    if _contains_any(
        normalized,
        (
            "landing page",
            "website",
            "microsite",
            "web app",
            "html app",
            "html file",
            "file html",
            "excel file",
            "spreadsheet",
            "word file",
            "docx",
            "xlsx",
            "download file",
            "de nhung",
            "embed",
            "artifact",
            "react app",
        ),
    ):
        return build_artifact_decision_impl(decision_cls=VisualIntentDecision)

    if _contains_any(
        normalized,
        (
            "mini app",
            "mini tool",
            "interactive tool",
            "dashboard",
            "dashboard app",
            "simulation",
            "simulate",
            "simulator",
            "mo phong",
            "mo phong vat ly",
            "mo phong canh",
            "tai hien canh",
            "dung canh",
            "khung canh",
            "keo tha",
            "drag and drop",
            "interactive table",
        ),
    ) or _contains_any(normalized, _QUIZ_WIDGET_CUES) or _looks_like_quiz_app_request(query, normalized) or (
        "app" in normalized
        and _contains_any(normalized, _SIMULATION_APP_CUES)
    ):
        visual_type = "simulation" if _contains_any(
            normalized,
            (
                "simulation",
                "simulate",
                "simulator",
                "mo phong",
                "mo phong vat ly",
                "mo phong canh",
                "tai hien canh",
                "dung canh",
                "khung canh",
                "keo tha",
                "drag and drop",
                "drag interaction",
                "pendulum",
                "physics",
                "con lac",
                "van hoc",
                "nhan vat",
            ),
        ) else None
        return build_app_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type=visual_type,
            reason="app-request",
        )

    if _looks_like_app_followup_patch(normalized):
        visual_type = _infer_followup_simulation_type(normalized)
        return build_app_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type=visual_type,
            reason="app-followup-patch",
        )

    if _contains_any(
        normalized,
        (
            "flowchart",
            "timeline",
            "sequence diagram",
            "state diagram",
            "er diagram",
            "mindmap",
            "mind map",
            "so do",
        ),
    ):
        return build_diagram_decision_impl(decision_cls=VisualIntentDecision)

    if _contains_any(
        normalized,
        (
            "animated",
            "animation",
            "animate",
            "hero visual",
            "editorial visual",
            "storyboard",
            "bespoke visual",
            "visual walkthrough",
            "trinh bay dep",
            "trinh bay hien dai",
        ),
    ):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="concept",
            reason="bespoke-inline-html",
            figure_budget=2,
            quality_profile="premium",
            preferred_render_surface="html",
            critic_policy="premium",
        )

    if _contains_any(
        normalized,
        (
            "chart",
            "charts",
            "bar chart",
            "line chart",
            "pie chart",
            "doughnut chart",
            "radar chart",
            "trend",
            "xu huong",
            "thong ke",
            "bieu do",
            "phan bo",
            "du lieu so",
            "kpi",
            "explain in charts",
            "explain with charts",
            "nguyen nhan",
            "top ",
            "lon nhat",
            "xep hang",
            "ty le",
            "ranking",
        ),
    ):
        return build_chart_runtime_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="chart",
            reason="chart-runtime",
            figure_budget=_infer_figure_budget(
                normalized,
                visual_type="chart",
                presentation_intent="chart_runtime",
            ),
            quality_profile="premium" if _contains_any(normalized, ("benchmark", "kpi", "perplexity")) else "standard",
            living_expression_mode="subtle",
        )

    if _contains_any(normalized, ("so sanh", "compare", "vs ", "khac nhau", "uu nhuoc diem")):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="comparison",
            reason="comparison_as_inline_chart",
            figure_budget=2,
            living_expression_mode="expressive",
        )

    if _contains_any(normalized, ("quy trinh", "cac buoc", "step by step", "how it works", "process")):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="process",
            reason="process",
            figure_budget=_infer_figure_budget(
                normalized,
                visual_type="process",
                presentation_intent="article_figure",
            ),
        )

    if _contains_any(normalized, ("kien truc", "architecture", "he thong", "layer", "stack")):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="architecture",
            reason="architecture",
            figure_budget=_infer_figure_budget(
                normalized,
                visual_type="architecture",
                presentation_intent="article_figure",
            ),
            quality_profile="premium",
            critic_policy="premium",
        )

    if _contains_any(normalized, ("ma tran", "matrix", "heatmap", "quadrant", "2x2")):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="matrix",
            reason="matrix",
            figure_budget=2,
        )

    if _contains_any(normalized, ("infographic", "tong quan nhanh", "facts at a glance", "highlights")):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="infographic",
            reason="infographic",
            figure_budget=2,
        )

    if _contains_any(
        normalized,
        (
            "concept map",
            "ban do khai niem",
            "khai niem bang so do",
            "explain visually",
            "visualize this concept",
            "truc quan hoa",
        ),
    ):
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="concept",
            reason="concept",
            figure_budget=2,
        )

    return VisualIntentDecision(mode="text", reason="plain-text")
