"""Contract-gated policy for deterministic Code Studio scaffold fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.engine.multi_agent.code_studio_template_scaffold import (
    build_scaffold_visible_caption,
    detect_scaffold_kind,
)
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent
from app.engine.tools.visual_code_runtime_contract import (
    resolve_visual_code_runtime_contract,
)


_SAFE_SCAFFOLD_PRESENTATION_INTENTS = frozenset({"artifact"})


@dataclass(frozen=True, slots=True)
class CodeStudioScaffoldFallbackDecision:
    """Auditable decision for whether Code Studio may use a template fallback."""

    engage_scaffold: bool
    response: str
    metric_kind: str
    callsite_reason: str
    policy_reason: str
    response_type: str
    presentation_intent: str
    preferred_tool: str
    studio_lane: str
    artifact_kind: str
    visual_type: str
    app_category: str
    quality_profile: str

    def metric_labels(self) -> dict[str, str]:
        """Return stable metric labels for engaged and suppressed fallbacks."""
        return {
            "kind": self.metric_kind,
            "reason": self.callsite_reason,
            "policy_reason": self.policy_reason,
            "presentation_intent": self.presentation_intent,
            "visual_type": self.visual_type,
            "app_category": self.app_category,
            "studio_lane": self.studio_lane,
        }


VisualIntentResolver = Callable[[str], Any]
RuntimeContractResolver = Callable[..., Any]
CaptionBuilder = Callable[[str], str]
KindDetector = Callable[[str], str]


def _safe_kind(query: str, detect_kind: KindDetector) -> str:
    try:
        return str(detect_kind(query) or "default")
    except Exception:
        return "default"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class CodeStudioScaffoldFallbackIntent:
    """Normalized visual intent metadata used by scaffold fallback policy."""

    force_tool: bool
    presentation_intent: str
    preferred_tool: str
    studio_lane: str
    artifact_kind: str
    visual_type: str
    app_category: str
    quality_profile: str
    planning_profile: str

    @classmethod
    def from_visual_decision(cls, visual_decision: Any) -> "CodeStudioScaffoldFallbackIntent":
        """Create a safe, non-guessing intent view from the visual resolver output."""

        return cls(
            force_tool=bool(getattr(visual_decision, "force_tool", False)),
            presentation_intent=_safe_text(
                getattr(visual_decision, "presentation_intent", "")
            ),
            preferred_tool=_safe_text(getattr(visual_decision, "preferred_tool", "")),
            studio_lane=_safe_text(getattr(visual_decision, "studio_lane", "")),
            artifact_kind=_safe_text(getattr(visual_decision, "artifact_kind", "")),
            visual_type=_safe_text(getattr(visual_decision, "visual_type", "")),
            app_category=_safe_text(getattr(visual_decision, "app_category", "")),
            quality_profile=_safe_text(getattr(visual_decision, "quality_profile", "")),
            planning_profile=_safe_text(getattr(visual_decision, "planning_profile", "")),
        )

    def with_runtime_contract(self, contract: Any) -> "CodeStudioScaffoldFallbackIntent":
        """Overlay the resolved runtime contract without broadening missing metadata."""

        app_intent_contract = getattr(contract, "app_intent_contract", None)
        return CodeStudioScaffoldFallbackIntent(
            force_tool=self.force_tool,
            presentation_intent=_safe_text(
                getattr(contract, "presentation_intent", self.presentation_intent)
            ),
            preferred_tool=self.preferred_tool,
            studio_lane=_safe_text(getattr(contract, "studio_lane", self.studio_lane)),
            artifact_kind=_safe_text(
                getattr(contract, "artifact_kind", self.artifact_kind)
            ),
            visual_type=_safe_text(
                getattr(contract, "resolved_visual_type", self.visual_type)
            ),
            app_category=_safe_text(
                getattr(app_intent_contract, "category", self.app_category)
            ),
            quality_profile=_safe_text(
                getattr(contract, "quality_profile", self.quality_profile)
            ),
            planning_profile=self.planning_profile,
        )

    @property
    def is_code_studio_tool_contract(self) -> bool:
        return self.force_tool and self.preferred_tool == "tool_create_visual_code"

    def decision_fields(self) -> dict[str, str]:
        """Return stable decision fields without inventing missing intent metadata."""

        return {
            "presentation_intent": self.presentation_intent or "none",
            "preferred_tool": self.preferred_tool or "none",
            "studio_lane": self.studio_lane or "none",
            "artifact_kind": self.artifact_kind or "none",
            "visual_type": self.visual_type or "none",
            "app_category": self.app_category or "none",
            "quality_profile": self.quality_profile or "standard",
        }


def _safe_failure_response(
    *,
    visual_type: str,
    presentation_intent: str,
) -> str:
    if presentation_intent == "code_studio_app" and visual_type == "simulation":
        return (
            "Mình đã mở đúng lane mô phỏng trong Code Studio, nhưng lượt này chưa tạo được "
            "preview thật. Mình dừng ở trạng thái an toàn thay vì mở một template chung chung, "
            "để không đưa ra mô phỏng sai."
        )
    if presentation_intent == "code_studio_app":
        return (
            "Mình đã giữ đúng lane Code Studio, nhưng lượt này chưa tạo được preview app thật. "
            "Mình dừng ở trạng thái an toàn thay vì mở một template chung chung."
        )
    return (
        "Yêu cầu này không thuộc lane Code Studio đáng tin cậy ở lượt hiện tại, nên mình không "
        "mở template HTML dự phòng."
    )


def _scaffold_delivery_unavailable_response() -> str:
    return (
        "Mình đã giữ đúng lane Code Studio, nhưng lỗi xảy ra trước khi runtime "
        "có thể gọi công cụ để mở preview thật. Mình dừng ở trạng thái an toàn "
        "thay vì nói rằng đã tạo artifact."
    )


def _resolution_failure_decision(
    *,
    query: str,
    reason: str,
    detect_kind: KindDetector,
) -> CodeStudioScaffoldFallbackDecision:
    return CodeStudioScaffoldFallbackDecision(
        engage_scaffold=False,
        response=(
            "Mình chưa xác định được contract runtime đủ chắc cho Code Studio ở lượt này, "
            "nên mình không mở template dự phòng."
        ),
        metric_kind=_safe_kind(query, detect_kind),
        callsite_reason=reason,
        policy_reason="visual_contract_resolution_failed",
        response_type="code_studio_scaffold_suppressed",
        presentation_intent="unknown",
        preferred_tool="unknown",
        studio_lane="unknown",
        artifact_kind="unknown",
        visual_type="unknown",
        app_category="unknown",
        quality_profile="unknown",
    )


def resolve_code_studio_scaffold_fallback(
    *,
    query: str,
    state: Any | None = None,
    reason: str = "unknown",
    allow_scaffold_delivery: bool = True,
    resolve_visual_intent_fn: VisualIntentResolver = resolve_visual_intent,
    resolve_contract_fn: RuntimeContractResolver = resolve_visual_code_runtime_contract,
    build_caption_fn: CaptionBuilder = build_scaffold_visible_caption,
    detect_kind_fn: KindDetector = detect_scaffold_kind,
) -> CodeStudioScaffoldFallbackDecision:
    """Resolve whether a deterministic scaffold is allowed for this failure path.

    Generic app/simulation fallbacks are intentionally suppressed: if the
    tool path cannot produce a real app preview, Wiii should fail visibly and
    safely instead of shipping a broad topic template.

    ``allow_scaffold_delivery`` must be false for callsites that can only return
    text and cannot dispatch ``tool_create_visual_code`` to open a real preview.
    """
    del state  # Reserved for future session-aware policy without changing call sites.

    try:
        visual_decision = resolve_visual_intent_fn(query)
    except Exception:
        return _resolution_failure_decision(
            query=query,
            reason=reason,
            detect_kind=detect_kind_fn,
        )

    intent = CodeStudioScaffoldFallbackIntent.from_visual_decision(visual_decision)
    metric_kind = _safe_kind(query, detect_kind_fn)

    if not intent.is_code_studio_tool_contract:
        return CodeStudioScaffoldFallbackDecision(
            engage_scaffold=False,
            response=_safe_failure_response(
                visual_type=intent.visual_type,
                presentation_intent=intent.presentation_intent,
            ),
            metric_kind=metric_kind,
            callsite_reason=reason,
            policy_reason="not_code_studio_tool_contract",
            response_type="code_studio_scaffold_suppressed",
            **intent.decision_fields(),
        )

    try:
        contract = resolve_contract_fn(
            presentation_intent=intent.presentation_intent,
            studio_lane=intent.studio_lane,
            artifact_kind=intent.artifact_kind,
            requested_visual_type=intent.visual_type,
            quality_profile=intent.quality_profile,
            app_category=intent.app_category,
            user_query=query,
            planning_profile=intent.planning_profile,
        )
    except Exception:
        return _resolution_failure_decision(
            query=query,
            reason=reason,
            detect_kind=detect_kind_fn,
        )

    intent = intent.with_runtime_contract(contract)

    if getattr(contract, "is_blocked_for_code_studio", False):
        return CodeStudioScaffoldFallbackDecision(
            engage_scaffold=False,
            response=_safe_failure_response(
                visual_type=intent.visual_type,
                presentation_intent=intent.presentation_intent,
            ),
            metric_kind=metric_kind,
            callsite_reason=reason,
            policy_reason="blocked_code_studio_presentation_intent",
            response_type="code_studio_scaffold_suppressed",
            **intent.decision_fields(),
        )

    if intent.presentation_intent not in _SAFE_SCAFFOLD_PRESENTATION_INTENTS:
        return CodeStudioScaffoldFallbackDecision(
            engage_scaffold=False,
            response=_safe_failure_response(
                visual_type=intent.visual_type,
                presentation_intent=intent.presentation_intent,
            ),
            metric_kind=metric_kind,
            callsite_reason=reason,
            policy_reason="app_requires_tool_generated_preview",
            response_type="code_studio_scaffold_suppressed",
            **intent.decision_fields(),
        )

    if not allow_scaffold_delivery:
        return CodeStudioScaffoldFallbackDecision(
            engage_scaffold=False,
            response=_scaffold_delivery_unavailable_response(),
            metric_kind=metric_kind,
            callsite_reason=reason,
            policy_reason="scaffold_delivery_unavailable",
            response_type="code_studio_scaffold_suppressed",
            **intent.decision_fields(),
        )

    return CodeStudioScaffoldFallbackDecision(
        engage_scaffold=True,
        response=build_caption_fn(query),
        metric_kind=metric_kind,
        callsite_reason=reason,
        policy_reason="artifact_contract_allows_scaffold",
        response_type="code_studio_contract_scaffold_fallback",
        **intent.decision_fields(),
    )
