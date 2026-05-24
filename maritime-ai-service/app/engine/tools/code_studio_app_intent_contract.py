"""Typed app-intent contract for Code Studio app/widget/artifact lanes."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


CODE_STUDIO_APP_CATEGORIES = frozenset(
    {
        "simulation",
        "quiz",
        "dashboard",
        "mini_tool",
        "interactive_table",
        "search_widget",
        "code_widget",
        "artifact",
    }
)


def _text(value: Any, default: str = "") -> str:
    cleaned = str(value if value is not None else default).strip()
    return cleaned or default


def _typed(value: Any, default: str = "") -> str:
    return _text(value, default).lower()


def _category(value: Any) -> str:
    return _typed(value).replace("-", "_").replace(" ", "_")


def _normalize(value: Any) -> str:
    text = _typed(value)
    if not text:
        return ""
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s/+.-]", " ", text)
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


@dataclass(frozen=True, slots=True)
class CodeStudioAppIntentContract:
    """Host-governed contract for one Code Studio app category."""

    category: str
    required_surface: str
    required_controls: tuple[str, ...]
    required_state: tuple[str, ...]
    required_feedback_hooks: tuple[str, ...]
    reject_if_missing: tuple[str, ...]
    critic_focus: tuple[str, ...]

    def metadata(self) -> dict[str, Any]:
        return {
            "app_category": self.category,
            "app_required_surface": self.required_surface,
            "app_required_controls": list(self.required_controls),
            "app_required_state": list(self.required_state),
            "app_feedback_hooks": list(self.required_feedback_hooks),
            "app_reject_if_missing": list(self.reject_if_missing),
            "app_critic_focus": list(self.critic_focus),
        }

    def metadata_text(self) -> dict[str, str]:
        return {
            "app_category": self.category,
            "app_required_surface": self.required_surface,
            "app_required_controls": ",".join(self.required_controls),
            "app_required_state": ",".join(self.required_state),
            "app_feedback_hooks": ",".join(self.required_feedback_hooks),
            "app_reject_if_missing": ",".join(self.reject_if_missing),
            "app_critic_focus": ",".join(self.critic_focus),
        }

    def prompt_lines(self) -> tuple[str, ...]:
        controls = ", ".join(self.required_controls)
        state = ", ".join(self.required_state)
        feedback = ", ".join(self.required_feedback_hooks)
        reject = ", ".join(self.reject_if_missing)
        return (
            f"- APP CONTRACT: category={self.category}; surface={self.required_surface}.",
            f"- Required controls: {controls}.",
            f"- Required state/readouts: {state}.",
            f"- Feedback hooks: {feedback}.",
            f"- Reject or repair if missing: {reject}.",
        )


_CONTRACTS: dict[str, CodeStudioAppIntentContract] = {
    "simulation": CodeStudioAppIntentContract(
        category="simulation",
        required_surface="canvas_or_svg_scene",
        required_controls=("play_pause", "reset", "parameter_control"),
        required_state=("time_step", "entity_state", "live_readout"),
        required_feedback_hooks=("state_changed", "checkpoint_reached"),
        reject_if_missing=("state_model", "render_loop", "live_readout", "feedback_bridge"),
        critic_focus=("real_causality", "not_css_only_motion", "teachable_controls"),
    ),
    "quiz": CodeStudioAppIntentContract(
        category="quiz",
        required_surface="form_or_cards",
        required_controls=("answer_choice", "submit", "reset"),
        required_state=("questions", "current_question", "score"),
        required_feedback_hooks=("answer_submitted", "quiz_completed"),
        reject_if_missing=("question_bank", "scoring_state", "result_feedback"),
        critic_focus=("clear_question_flow", "accessible_inputs", "score_feedback"),
    ),
    "dashboard": CodeStudioAppIntentContract(
        category="dashboard",
        required_surface="dashboard_grid",
        required_controls=("filter", "view_toggle", "reset"),
        required_state=("dataset", "filters", "selected_view"),
        required_feedback_hooks=("filter_changed", "view_changed"),
        reject_if_missing=("real_data_model", "axis_or_units", "empty_state"),
        critic_focus=("scan_density", "meaningful_metrics", "no_fake_div_bars"),
    ),
    "mini_tool": CodeStudioAppIntentContract(
        category="mini_tool",
        required_surface="tool_panel",
        required_controls=("input", "run_or_update", "reset"),
        required_state=("inputs", "computed_result", "validation_state"),
        required_feedback_hooks=("result_ready", "input_changed"),
        reject_if_missing=("input_model", "computed_output", "validation_feedback"),
        critic_focus=("ergonomic_controls", "clear_output", "repeatable_action"),
    ),
    "interactive_table": CodeStudioAppIntentContract(
        category="interactive_table",
        required_surface="table",
        required_controls=("sort", "filter", "row_select"),
        required_state=("rows", "sort_state", "filter_state"),
        required_feedback_hooks=("row_selected", "filter_changed"),
        reject_if_missing=("table_semantics", "keyboard_navigation", "empty_state"),
        critic_focus=("dense_but_readable", "table_accessibility", "source_or_units"),
    ),
    "search_widget": CodeStudioAppIntentContract(
        category="search_widget",
        required_surface="search_results",
        required_controls=("query_input", "search", "filter"),
        required_state=("query", "results", "selected_result"),
        required_feedback_hooks=("search_submitted", "result_selected"),
        reject_if_missing=("query_state", "results_state", "no_results_state"),
        critic_focus=("result_relevance", "source_visibility", "keyboard_search"),
    ),
    "code_widget": CodeStudioAppIntentContract(
        category="code_widget",
        required_surface="code_workspace",
        required_controls=("edit", "run_or_preview", "reset"),
        required_state=("source", "preview_or_output", "error_state"),
        required_feedback_hooks=("code_updated", "preview_ready"),
        reject_if_missing=("source_state", "preview_state", "error_feedback"),
        critic_focus=("safe_preview", "readable_code", "clear_error_state"),
    ),
    "artifact": CodeStudioAppIntentContract(
        category="artifact",
        required_surface="artifact_preview",
        required_controls=("preview", "apply_or_export", "reset"),
        required_state=("artifact_payload", "embed_state", "version"),
        required_feedback_hooks=("artifact_ready", "artifact_exported"),
        reject_if_missing=("artifact_payload", "preview_state", "handoff_metadata"),
        critic_focus=("portable_output", "embed_ready", "no_session_only_assumptions"),
    ),
}


def infer_code_studio_app_category(
    *,
    presentation_intent: str = "",
    studio_lane: str = "",
    artifact_kind: str = "",
    requested_visual_type: str = "",
    app_category: str = "",
    user_query: str = "",
    planning_profile: str = "",
) -> str:
    """Infer the stable Code Studio app category from typed and lexical cues."""

    explicit = _category(app_category)
    if explicit in CODE_STUDIO_APP_CATEGORIES:
        return explicit

    intent = _typed(presentation_intent)
    lane = _typed(studio_lane)
    kind = _typed(artifact_kind)
    visual_type = _typed(requested_visual_type)
    query = _normalize(user_query)
    planning = _typed(planning_profile)

    if intent == "artifact" or lane == "artifact":
        if kind == "search_widget":
            return "search_widget"
        if kind == "code_widget":
            return "code_widget"
        return "artifact"

    if visual_type == "simulation" or planning == "simulation_canvas":
        return "simulation"
    if visual_type == "quiz" or _contains_any(query, ("quiz", "quizz", "trac nghiem")):
        return "quiz"
    if visual_type == "interactive_table" or _contains_any(query, ("interactive table", "bang tuong tac")):
        return "interactive_table"
    if _contains_any(query, ("dashboard", "kpi", "metric", "analytics", "phan tich")):
        return "dashboard"
    if _contains_any(query, ("search widget", "tim kiem", "search tool")):
        return "search_widget"
    if _contains_any(query, ("code widget", "code editor", "snippet", "playground")):
        return "code_widget"
    return "mini_tool"


def resolve_code_studio_app_intent_contract(
    *,
    presentation_intent: str = "",
    studio_lane: str = "",
    artifact_kind: str = "",
    requested_visual_type: str = "",
    app_category: str = "",
    user_query: str = "",
    planning_profile: str = "",
) -> CodeStudioAppIntentContract:
    """Resolve the Code Studio category contract used by prompts and payloads."""

    category = infer_code_studio_app_category(
        presentation_intent=presentation_intent,
        studio_lane=studio_lane,
        artifact_kind=artifact_kind,
        requested_visual_type=requested_visual_type,
        app_category=app_category,
        user_query=user_query,
        planning_profile=planning_profile,
    )
    return _CONTRACTS.get(category, _CONTRACTS["mini_tool"])
