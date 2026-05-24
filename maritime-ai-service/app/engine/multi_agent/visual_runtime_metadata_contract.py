"""Typed metadata bridge from visual intent decisions into tool runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.tools.code_studio_app_intent_contract import (
    resolve_code_studio_app_intent_contract,
)


VISUAL_RUNTIME_MODES = frozenset({"template", "inline_html", "app", "mermaid"})
PRESENTATION_INTENTS = frozenset(
    {"text", "article_figure", "chart_runtime", "code_studio_app", "artifact"}
)
QUALITY_PROFILES = frozenset({"draft", "standard", "premium"})


def _text(value: Any, default: str = "") -> str:
    cleaned = str(value if value is not None else default).strip()
    return cleaned or default


def _bounded_figure_budget(value: Any) -> int:
    try:
        return max(1, min(3, int(value or 1)))
    except Exception:
        return 1


@dataclass(frozen=True, slots=True)
class VisualToolRuntimeIntent:
    """Tool-runtime view of a resolved visual turn."""

    query: str
    mode: str
    reason: str
    presentation_intent: str
    figure_budget: int
    quality_profile: str
    preferred_render_surface: str
    planning_profile: str
    thinking_floor: str
    critic_policy: str
    living_expression_mode: str
    visual_type: str = ""
    preferred_tool: str = ""
    studio_lane: str = ""
    artifact_kind: str = ""
    renderer_contract: str = ""
    renderer_kind_hint: str = ""
    app_category: str = ""
    app_required_surface: str = ""
    app_required_controls: str = ""
    app_required_state: str = ""
    app_feedback_hooks: str = ""
    app_reject_if_missing: str = ""
    app_critic_focus: str = ""

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "visual_user_query": self.query,
            "visual_intent_mode": self.mode,
            "visual_intent_reason": self.reason,
            "visual_force_tool": True,
            "presentation_intent": self.presentation_intent,
            "figure_budget": self.figure_budget,
            "quality_profile": self.quality_profile,
            "preferred_render_surface": self.preferred_render_surface,
            "planning_profile": self.planning_profile,
            "thinking_floor": self.thinking_floor,
            "critic_policy": self.critic_policy,
            "living_expression_mode": self.living_expression_mode,
        }
        optional_fields = {
            "visual_requested_type": self.visual_type,
            "preferred_visual_tool": self.preferred_tool,
            "studio_lane": self.studio_lane,
            "artifact_kind": self.artifact_kind,
            "renderer_contract": self.renderer_contract,
            "renderer_kind_hint": self.renderer_kind_hint,
            "app_category": self.app_category,
            "app_required_surface": self.app_required_surface,
            "app_required_controls": self.app_required_controls,
            "app_required_state": self.app_required_state,
            "app_feedback_hooks": self.app_feedback_hooks,
            "app_reject_if_missing": self.app_reject_if_missing,
            "app_critic_focus": self.app_critic_focus,
        }
        metadata.update({key: value for key, value in optional_fields.items() if value})
        return metadata


def build_visual_tool_runtime_intent(
    *,
    query: str,
    visual_decision: Any,
) -> VisualToolRuntimeIntent | None:
    """Build auditable tool-runtime metadata from one visual intent decision."""

    if not bool(getattr(visual_decision, "force_tool", False)):
        return None

    mode = _text(getattr(visual_decision, "mode", ""))
    if mode not in VISUAL_RUNTIME_MODES:
        return None

    presentation_intent = _text(getattr(visual_decision, "presentation_intent", ""), "text")
    if presentation_intent not in PRESENTATION_INTENTS:
        presentation_intent = "text"

    quality_profile = _text(getattr(visual_decision, "quality_profile", ""), "standard")
    if quality_profile not in QUALITY_PROFILES:
        quality_profile = "standard"

    preferred_tool = _text(getattr(visual_decision, "preferred_tool", ""))
    app_metadata: dict[str, str] = {}
    if presentation_intent in {"code_studio_app", "artifact"} or preferred_tool == "tool_create_visual_code":
        app_contract = resolve_code_studio_app_intent_contract(
            presentation_intent=presentation_intent,
            studio_lane=_text(getattr(visual_decision, "studio_lane", "")),
            artifact_kind=_text(getattr(visual_decision, "artifact_kind", "")),
            requested_visual_type=_text(getattr(visual_decision, "visual_type", "")),
            app_category=_text(getattr(visual_decision, "app_category", "")),
            user_query=query,
            planning_profile=_text(getattr(visual_decision, "planning_profile", "")),
        )
        app_metadata = app_contract.metadata_text()

    return VisualToolRuntimeIntent(
        query=query,
        mode=mode,
        reason=_text(getattr(visual_decision, "reason", "")),
        presentation_intent=presentation_intent,
        figure_budget=_bounded_figure_budget(getattr(visual_decision, "figure_budget", 1)),
        quality_profile=quality_profile,
        preferred_render_surface=_text(getattr(visual_decision, "preferred_render_surface", "")),
        planning_profile=_text(getattr(visual_decision, "planning_profile", "")),
        thinking_floor=_text(getattr(visual_decision, "thinking_floor", "")),
        critic_policy=_text(getattr(visual_decision, "critic_policy", "")),
        living_expression_mode=_text(getattr(visual_decision, "living_expression_mode", "")),
        visual_type=_text(getattr(visual_decision, "visual_type", "")),
        preferred_tool=preferred_tool,
        studio_lane=_text(getattr(visual_decision, "studio_lane", "")),
        artifact_kind=_text(getattr(visual_decision, "artifact_kind", "")),
        renderer_contract=_text(getattr(visual_decision, "renderer_contract", "")),
        renderer_kind_hint=_text(getattr(visual_decision, "renderer_kind_hint", "")),
        app_category=app_metadata.get("app_category", ""),
        app_required_surface=app_metadata.get("app_required_surface", ""),
        app_required_controls=app_metadata.get("app_required_controls", ""),
        app_required_state=app_metadata.get("app_required_state", ""),
        app_feedback_hooks=app_metadata.get("app_feedback_hooks", ""),
        app_reject_if_missing=app_metadata.get("app_reject_if_missing", ""),
        app_critic_focus=app_metadata.get("app_critic_focus", ""),
    )
