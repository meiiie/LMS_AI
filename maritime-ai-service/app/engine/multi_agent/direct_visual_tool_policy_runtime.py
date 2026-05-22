"""Visual-turn policy helpers for the direct tool loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent


@dataclass(frozen=True)
class DirectVisualToolPolicy:
    """Resolved visual policy for one direct turn."""

    visual_decision: Any
    requires_visual_commit: bool
    initial_timeout_profile: str | None
    followup_timeout_profile: str
    structured_visuals_enabled: bool


def build_direct_visual_tool_policy(
    *,
    query: str,
    settings_obj: Any,
    timeout_profile_structured: str,
    timeout_profile_background: str,
    resolve_visual_intent_fn: Callable[[str], Any] = resolve_visual_intent,
) -> DirectVisualToolPolicy:
    """Resolve visual intent and timeout policy for a direct turn."""

    visual_decision = resolve_visual_intent_fn(query)
    requires_visual_commit = bool(
        getattr(visual_decision, "force_tool", False)
        and getattr(visual_decision, "presentation_intent", None)
        in {"article_figure", "chart_runtime"}
    )
    return DirectVisualToolPolicy(
        visual_decision=visual_decision,
        requires_visual_commit=requires_visual_commit,
        initial_timeout_profile=(
            timeout_profile_structured
            if getattr(visual_decision, "force_tool", False)
            else None
        ),
        followup_timeout_profile=(
            timeout_profile_background
            if requires_visual_commit
            else timeout_profile_structured
        ),
        structured_visuals_enabled=bool(
            getattr(settings_obj, "enable_structured_visuals", False)
        ),
    )
