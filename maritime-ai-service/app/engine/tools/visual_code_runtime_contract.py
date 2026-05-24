"""Typed runtime contract for Code Studio visual-code payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.tools.code_studio_app_intent_contract import (
    CodeStudioAppIntentContract,
    resolve_code_studio_app_intent_contract,
)


BLOCKED_CODE_STUDIO_PRESENTATION_INTENTS = frozenset({"article_figure", "chart_runtime"})
CODE_STUDIO_PRESENTATION_INTENTS = frozenset({"code_studio_app", "artifact"})
CODE_STUDIO_VISUAL_TYPES = frozenset(
    {
        "comparison",
        "process",
        "matrix",
        "architecture",
        "concept",
        "infographic",
        "chart",
        "timeline",
        "map_lite",
        "simulation",
        "quiz",
        "interactive_table",
        "react_app",
    }
)
CODE_STUDIO_LANES = frozenset({"app", "artifact", "widget"})
CODE_STUDIO_ARTIFACT_KINDS = frozenset(
    {"html_app", "code_widget", "search_widget", "document", "chart_widget"}
)
CODE_STUDIO_QUALITY_PROFILES = frozenset({"draft", "standard", "premium"})


def _text(value: Any, default: str = "") -> str:
    cleaned = str(value if value is not None else default).strip()
    return cleaned or default


def _choice(value: Any, allowed: frozenset[str], default: str) -> str:
    candidate = _text(value, default)
    return candidate if candidate in allowed else default


def _code_studio_version(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


@dataclass(frozen=True, slots=True)
class VisualCodeRuntimeContract:
    """Host-shell contract resolved before a Code Studio visual payload is built."""

    presentation_intent: str
    studio_lane: str
    artifact_kind: str
    requested_visual_type: str
    resolved_visual_type: str
    renderer_kind: str
    shell_variant: str
    patch_strategy: str
    quality_profile: str
    code_studio_version: int = 0
    renderer_contract: str = "host_shell"
    app_intent_contract: CodeStudioAppIntentContract | None = None

    @property
    def is_blocked_for_code_studio(self) -> bool:
        return self.presentation_intent in BLOCKED_CODE_STUDIO_PRESENTATION_INTENTS

    @property
    def runtime_manifest(self) -> dict[str, Any] | None:
        if self.renderer_kind != "app":
            return None
        manifest = {
            "ui_runtime": "html",
            "storage": False,
            "mcp_access": False,
            "file_export": self.studio_lane == "artifact",
            "shareability": "session" if self.studio_lane == "app" else "artifact",
        }
        if self.app_intent_contract is not None:
            manifest.update(self.app_intent_contract.metadata())
        return manifest

    def payload_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source_tool": "tool_create_visual_code",
            "presentation_intent": (
                self.presentation_intent
                if self.presentation_intent in CODE_STUDIO_PRESENTATION_INTENTS
                else "code_studio_app"
            ),
            "studio_lane": self.studio_lane,
            "artifact_kind": self.artifact_kind,
            "quality_profile": self.quality_profile,
            "renderer_contract": self.renderer_contract,
        }
        if self.app_intent_contract is not None:
            metadata.update(self.app_intent_contract.metadata())
        if self.code_studio_version > 0:
            metadata["code_studio_version"] = self.code_studio_version
        return metadata


def resolve_visual_code_runtime_contract(
    *,
    presentation_intent: str = "",
    studio_lane: str = "",
    artifact_kind: str = "",
    requested_visual_type: str = "",
    quality_profile: str = "",
    code_studio_version: Any = 0,
    app_category: str = "",
    user_query: str = "",
    planning_profile: str = "",
) -> VisualCodeRuntimeContract:
    """Resolve Code Studio lane metadata once, before validation and payload build."""

    raw_intent = _text(presentation_intent, "code_studio_app")
    if raw_intent in BLOCKED_CODE_STUDIO_PRESENTATION_INTENTS:
        resolved_intent = raw_intent
    else:
        resolved_intent = raw_intent if raw_intent in CODE_STUDIO_PRESENTATION_INTENTS else "code_studio_app"

    resolved_lane = _choice(studio_lane, CODE_STUDIO_LANES, "app")
    resolved_artifact_kind = _choice(artifact_kind, CODE_STUDIO_ARTIFACT_KINDS, "html_app")
    requested_type = _text(requested_visual_type, "concept")
    resolved_visual_type = requested_type if requested_type in CODE_STUDIO_VISUAL_TYPES else "concept"
    renderer_kind = "app" if resolved_lane in {"app", "widget"} else "inline_html"
    app_contract = None
    if resolved_intent in CODE_STUDIO_PRESENTATION_INTENTS:
        app_contract = resolve_code_studio_app_intent_contract(
            presentation_intent=resolved_intent,
            studio_lane=resolved_lane,
            artifact_kind=resolved_artifact_kind,
            requested_visual_type=resolved_visual_type,
            app_category=app_category,
            user_query=user_query,
            planning_profile=planning_profile,
        )

    return VisualCodeRuntimeContract(
        presentation_intent=resolved_intent,
        studio_lane=resolved_lane,
        artifact_kind=resolved_artifact_kind,
        requested_visual_type=requested_type,
        resolved_visual_type=resolved_visual_type,
        renderer_kind=renderer_kind,
        shell_variant="immersive" if renderer_kind == "app" else "editorial",
        patch_strategy="app_state" if renderer_kind == "app" else "replace_html",
        quality_profile=_choice(quality_profile, CODE_STUDIO_QUALITY_PROFILES, "standard"),
        code_studio_version=_code_studio_version(code_studio_version),
        app_intent_contract=app_contract,
    )
