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
    CODE_WIDGET_CUES as _CODE_WIDGET_CUES,
    DASHBOARD_APP_CUES as _DASHBOARD_APP_CUES,
    INTERACTIVE_TABLE_CUES as _INTERACTIVE_TABLE_CUES,
    MINI_TOOL_CUES as _MINI_TOOL_CUES,
    QUIZ_WIDGET_CUES as _QUIZ_WIDGET_CUES,
    SEARCH_WIDGET_CUES as _SEARCH_WIDGET_CUES,
    SIMULATION_APP_CUES as _SIMULATION_APP_CUES,
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
from app.engine.tools.code_studio_app_intent_contract import (
    infer_code_studio_app_category as infer_code_studio_app_category_contract,
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
CodeStudioAppCategory = Literal[
    "simulation",
    "quiz",
    "dashboard",
    "mini_tool",
    "interactive_table",
    "search_widget",
    "code_widget",
    "artifact",
]
VisualToolCapabilityLane = Literal["structured_visual", "code_studio", "mermaid", "legacy_chart"]


@dataclass(frozen=True, slots=True)
class VisualToolCapability:
    """Runtime capability advertised by a visual generation tool."""

    name: str
    lane: VisualToolCapabilityLane
    presentation_intents: tuple[PresentationIntent, ...]
    legacy: bool = False


@dataclass(frozen=True, slots=True)
class VisualToolRequirement:
    """Auditable tool-binding requirement derived from one visual intent decision."""

    force_tool: bool
    mode: str
    presentation_intent: str
    required_tool_names: tuple[str, ...]
    required_capabilities: tuple[VisualToolCapability, ...]
    visual_tool_names: frozenset[str]
    strip_unrequired_visual_tools: bool

    def should_keep_tool_name(self, tool_name: str) -> bool:
        """Return whether a bound tool should survive visual-intent narrowing."""

        if not self.strip_unrequired_visual_tools:
            return True
        if tool_name in self.required_tool_names:
            return True
        if tool_name in self.visual_tool_names:
            return False
        return True


VISUAL_TOOL_CAPABILITIES: dict[str, VisualToolCapability] = {
    "tool_generate_visual": VisualToolCapability(
        name="tool_generate_visual",
        lane="structured_visual",
        presentation_intents=("article_figure", "chart_runtime"),
    ),
    "tool_create_visual_code": VisualToolCapability(
        name="tool_create_visual_code",
        lane="code_studio",
        presentation_intents=("code_studio_app", "artifact"),
    ),
    "tool_generate_mermaid": VisualToolCapability(
        name="tool_generate_mermaid",
        lane="mermaid",
        presentation_intents=("article_figure",),
    ),
    "tool_generate_chart": VisualToolCapability(
        name="tool_generate_chart",
        lane="legacy_chart",
        presentation_intents=("chart_runtime",),
        legacy=True,
    ),
    "tool_generate_interactive_chart": VisualToolCapability(
        name="tool_generate_interactive_chart",
        lane="legacy_chart",
        presentation_intents=("chart_runtime",),
        legacy=True,
    ),
}
VISUAL_TOOL_CAPABILITY_NAMES = frozenset(VISUAL_TOOL_CAPABILITIES)


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
    app_category: CodeStudioAppCategory | str = ""


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

def _infer_code_studio_app_category(normalized: str, *, visual_type: str | None = None) -> str:
    return infer_code_studio_app_category_contract(
        presentation_intent="code_studio_app",
        studio_lane="app",
        requested_visual_type=visual_type or "",
        user_query=normalized,
        planning_profile="simulation_canvas" if visual_type == "simulation" else "",
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
    preferred_tool = getattr(visual_decision, "preferred_tool", None)
    if preferred_tool:
        return preferred_tool
    mode = getattr(visual_decision, "mode", "")
    if mode in {"template", "inline_html", "app"}:
        return preferred_visual_tool_name()
    if mode == "mermaid":
        return "tool_generate_mermaid"
    return None


def required_visual_tool_names(
    visual_decision: VisualIntentDecision,
) -> tuple[str, ...]:
    """Return the visual tool names that should remain available for an explicit intent."""
    if not bool(getattr(visual_decision, "force_tool", False)):
        return ()

    tool_name = _resolve_preferred_tool(visual_decision)
    return (tool_name,) if tool_name else ()


def visual_tool_capability_names(*, include_legacy: bool = True) -> frozenset[str]:
    """Return known visual tool names for deterministic pruning."""

    if include_legacy:
        return VISUAL_TOOL_CAPABILITY_NAMES
    return frozenset(
        name for name, capability in VISUAL_TOOL_CAPABILITIES.items()
        if not capability.legacy
    )


def build_visual_tool_requirement(
    visual_decision: VisualIntentDecision,
    *,
    structured_visuals_enabled: bool,
) -> VisualToolRequirement:
    """Build the typed visual tool requirement consumed by tool collection."""

    required_tool_names = required_visual_tool_names(visual_decision)
    required_capabilities = tuple(
        VISUAL_TOOL_CAPABILITIES[tool_name]
        for tool_name in required_tool_names
        if tool_name in VISUAL_TOOL_CAPABILITIES
    )
    return VisualToolRequirement(
        force_tool=bool(getattr(visual_decision, "force_tool", False)),
        mode=str(getattr(visual_decision, "mode", "") or ""),
        presentation_intent=str(getattr(visual_decision, "presentation_intent", "text") or "text"),
        required_tool_names=required_tool_names,
        required_capabilities=required_capabilities,
        visual_tool_names=VISUAL_TOOL_CAPABILITY_NAMES,
        strip_unrequired_visual_tools=structured_visuals_enabled and bool(required_tool_names),
    )


def filter_tools_for_visual_intent(
    tools: list[Any],
    visual_decision: VisualIntentDecision,
    *,
    structured_visuals_enabled: bool,
) -> list[Any]:
    """Reduce drift toward legacy visual tools when structured intent is explicit."""
    requirement = build_visual_tool_requirement(
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )
    if not requirement.strip_unrequired_visual_tools:
        return tools

    filtered: list[Any] = []
    for tool in tools:
        tool_name = str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "")
        if requirement.should_keep_tool_name(tool_name):
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
        artifact_kind = "search_widget" if _contains_any(normalized, _SEARCH_WIDGET_CUES) else "html_app"
        return build_artifact_decision_impl(
            decision_cls=VisualIntentDecision,
            artifact_kind=artifact_kind,
            app_category="artifact" if artifact_kind == "html_app" else "search_widget",
        )

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
    ) or _contains_any(
        normalized,
        _QUIZ_WIDGET_CUES
        + _DASHBOARD_APP_CUES
        + _MINI_TOOL_CUES
        + _INTERACTIVE_TABLE_CUES
        + _SEARCH_WIDGET_CUES
        + _CODE_WIDGET_CUES,
    ) or _looks_like_quiz_app_request(query, normalized) or (
        "app" in normalized
        and _contains_any(normalized, _SIMULATION_APP_CUES)
    ):
        if _contains_any(
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
        ):
            visual_type = "simulation"
        elif _looks_like_quiz_app_request(query, normalized) or _contains_any(normalized, _QUIZ_WIDGET_CUES):
            visual_type = "quiz"
        elif _contains_any(normalized, _INTERACTIVE_TABLE_CUES):
            visual_type = "interactive_table"
        else:
            visual_type = "react_app"
        app_category = _infer_code_studio_app_category(normalized, visual_type=visual_type)
        return build_app_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type=visual_type,
            reason="app-request",
            app_category=app_category,
        )

    if _looks_like_app_followup_patch(normalized):
        visual_type = _infer_followup_simulation_type(normalized)
        return build_app_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type=visual_type,
            reason="app-followup-patch",
            app_category=_infer_code_studio_app_category(normalized, visual_type=visual_type),
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

    explicit_inline_visual = _contains_any(
        normalized,
        (
            "article figure",
            "comparison visual",
            "compare visually",
            "explain visually",
            "inline diagram",
            "inline figure",
            "inline visual",
            "minh hoa",
            "minh hoa truc quan",
            "structured visual",
            "truc quan hoa",
            "visual comparison",
            "visual explanation",
            "visual inline",
            "with an inline visual",
            "with visual",
        ),
    )
    if explicit_inline_visual:
        is_comparison = _contains_any(
            normalized,
            (
                "compare",
                "comparing",
                "comparison",
                "khac nhau",
                "so sanh",
                "trade off",
                "vs ",
            ),
        )
        return build_article_figure_decision_impl(
            decision_cls=VisualIntentDecision,
            visual_type="comparison" if is_comparison else "concept",
            reason="explicit-inline-visual",
            figure_budget=2,
            living_expression_mode="expressive",
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

    if _contains_any(
        normalized,
        (
            "comparison",
            "compare",
            "comparing",
            "so sanh",
            "vs ",
            "khac nhau",
            "uu nhuoc diem",
        ),
    ):
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
