"""
Living context compiler for Wiii.

This module turns Wiii's stable character card, evolving narrative, and
turn-level context into a compact prompt block that can be injected across
agents without rewriting the graph architecture.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.engine.character.character_card import build_character_card_payload
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

logger = logging.getLogger(__name__)

_SOCIAL_KEYWORDS = (
    "xin chao",
    "chao",
    "hello",
    "hi",
    "cam on",
    "thanks",
    "tam biet",
    "bye",
)

_PERSONAL_KEYWORDS = (
    "ten toi",
    "ten minh",
    "my name",
    "ban co nho",
    "nho giup",
    "lan truoc",
    "last time",
    "hom truoc",
)

_PEDAGOGICAL_KEYWORDS = (
    "giai thich",
    "explain",
    "tai sao",
    "how it works",
    "huong dan",
    "quiz",
    "on bai",
    "day toi",
    "tung buoc",
    "step by step",
)

_EMOTIONAL_KEYWORDS = (
    "buon",
    "met",
    "lo",
    "stress",
    "that vong",
    "chia tay",
    "co don",
    "so hai",
    "ap luc",
)

_WEB_KEYWORDS = (
    "tim tren web",
    "tim tren mang",
    "tim tren internet",
    "search",
    "tin tuc",
    "moi nhat",
    "hom nay",
    "nghi dinh",
    "thong tu",
    "van ban phap luat",
    "maritime news",
    "shipping news",
)


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _clip(text: str, limit: int = 220) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = _clip(str(value or "").strip())
        if text:
            return text
    return ""


class MemoryBlockV1(BaseModel):
    namespace: Literal["persona", "human", "relationship", "goals", "craft", "world"]
    summary: str
    items: List[str] = Field(default_factory=list)


class ReasoningPolicyV1(BaseModel):
    task_class: str
    deliberation_level: Literal["low", "medium", "high", "max"] = "medium"
    pace_mode: Literal["quick", "steady", "deliberate", "deep"] = "steady"
    thinking_visibility: Literal["minimal", "brief", "warm"] = "brief"
    handoff_policy: Literal[
        "inline",
        "artifact_followup",
        "memory_specialist",
        "specialist_if_ambiguous",
    ] = "inline"


class LivingExpressionPolicyV1(BaseModel):
    mode: Literal["subtle", "expressive"] = "subtle"
    avoid_mascotization: bool = True
    avoid_over_roleplay: bool = True
    prefer_companionship_over_performance: bool = True


class LivingContextBlockV1(BaseModel):
    contract_version: Literal["living_context.v1"] = "living_context.v1"
    core_card: Dict[str, str]
    current_state: List[str] = Field(default_factory=list)
    narrative_state: List[str] = Field(default_factory=list)
    relationship_memory: List[str] = Field(default_factory=list)
    task_mode: Dict[str, str] = Field(default_factory=dict)
    reasoning_policy: ReasoningPolicyV1
    visual_cognition: Dict[str, str] = Field(default_factory=dict)
    expression_policy: LivingExpressionPolicyV1 = Field(default_factory=LivingExpressionPolicyV1)
    memory_blocks: List[MemoryBlockV1] = Field(default_factory=list)


def infer_reasoning_policy(
    query: str,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> ReasoningPolicyV1:
    normalized = _normalize(query)
    visual_decision = resolve_visual_intent(query)

    if visual_decision.presentation_intent == "code_studio_app":
        return ReasoningPolicyV1(
            task_class="simulation_runtime",
            deliberation_level="max",
            pace_mode="deep",
            thinking_visibility="brief",
            handoff_policy="artifact_followup",
        )

    if visual_decision.presentation_intent in {"article_figure", "chart_runtime"}:
        return ReasoningPolicyV1(
            task_class="visual_pedagogy",
            deliberation_level="high",
            pace_mode="deliberate",
            thinking_visibility="brief",
            handoff_policy="inline",
        )

    if visual_decision.presentation_intent == "artifact":
        return ReasoningPolicyV1(
            task_class="artifact_builder",
            deliberation_level="high",
            pace_mode="deliberate",
            thinking_visibility="brief",
            handoff_policy="artifact_followup",
        )

    if any(keyword in normalized for keyword in _EMOTIONAL_KEYWORDS):
        return ReasoningPolicyV1(
            task_class="emotional_support",
            deliberation_level="high",
            pace_mode="deliberate",
            thinking_visibility="warm",
            handoff_policy="specialist_if_ambiguous",
        )

    if any(keyword in normalized for keyword in _PERSONAL_KEYWORDS):
        return ReasoningPolicyV1(
            task_class="memory_sensitive",
            deliberation_level="medium",
            pace_mode="steady",
            thinking_visibility="warm",
            handoff_policy="memory_specialist",
        )

    if any(keyword in normalized for keyword in _PEDAGOGICAL_KEYWORDS):
        return ReasoningPolicyV1(
            task_class="pedagogical_explanation",
            deliberation_level="high",
            pace_mode="deliberate",
            thinking_visibility="brief",
            handoff_policy="specialist_if_ambiguous",
        )

    if any(keyword in normalized for keyword in _WEB_KEYWORDS):
        return ReasoningPolicyV1(
            task_class="web_lookup",
            deliberation_level="medium",
            pace_mode="steady",
            thinking_visibility="brief",
            handoff_policy="inline",
        )

    if any(keyword in normalized for keyword in _SOCIAL_KEYWORDS):
        return ReasoningPolicyV1(
            task_class="social_simple",
            deliberation_level="low",
            pace_mode="quick",
            thinking_visibility="minimal",
            handoff_policy="inline",
        )

    return ReasoningPolicyV1(
        task_class="general_reasoning",
        deliberation_level="medium",
        pace_mode="steady",
        thinking_visibility="brief",
        handoff_policy="specialist_if_ambiguous",
    )


def _safe_narrative_context(organization_id: Optional[str]) -> str:
    try:
        from app.engine.living_agent.narrative_synthesizer import get_brief_context

        return _clip(get_brief_context(organization_id=organization_id) or "", 240)
    except Exception:
        return ""


def _safe_identity_context() -> str:
    try:
        from app.engine.living_agent.identity_core import get_identity_core

        return _clip(get_identity_core().get_identity_context() or "", 240)
    except Exception:
        return ""


def _safe_character_state(user_id: str, organization_id: Optional[str]) -> str:
    try:
        from app.engine.character.character_state import get_character_state_manager

        manager = get_character_state_manager()
        return _clip(
            manager.compile_living_state(
                user_id=user_id,
                organization_id=organization_id,
            )
            or "",
            240,
        )
    except Exception:
        return ""


def _compile_memory_blocks(
    *,
    query: str,
    context: Dict[str, Any],
    user_id: str,
    organization_id: Optional[str],
) -> List[MemoryBlockV1]:
    card = build_character_card_payload(
        user_id=user_id,
        organization_id=organization_id,
        mood_hint=context.get("mood_hint"),
        personality_mode=context.get("personality_mode"),
    )
    user_facts = [str(item).strip() for item in (context.get("user_facts") or []) if str(item).strip()]
    conversation_summary = _clip(str(context.get("conversation_summary") or "").strip(), 220)
    host_context = context.get("host_context") or {}
    page_context = context.get("page_context") or {}

    persona_items = [item for item in card.get("core_truths", [])[:3] if item]
    identity_context = _safe_identity_context()
    if identity_context:
        persona_items.append(identity_context)

    relationship_items: List[str] = []
    user_name = str(context.get("user_name") or "").strip()
    if user_name:
        relationship_items.append(f"Wiii dang dong hanh cung {user_name}.")
    if conversation_summary:
        relationship_items.append(conversation_summary)
    if context.get("total_responses", 0):
        relationship_items.append(
            f"Cuoc tro chuyen da co {int(context.get('total_responses', 0))} luot hoi dap gan day."
        )

    goals_items: List[str] = []
    query_goal = _clip(query, 140)
    if query_goal:
        goals_items.append(f"Turn goal hien tai: {query_goal}")
    if context.get("page_context"):
        page_title = _first_non_empty(
            page_context.get("title") if isinstance(page_context, dict) else "",
            host_context.get("page", {}).get("title") if isinstance(host_context, dict) else "",
        )
        if page_title:
            goals_items.append(f"Host/page focus: {page_title}")

    craft_items = [
        "Wiii uu tien day bang cach giup nguoi hoc nhin ra ban chat.",
        "Article figure va chart nen la SVG-first, mot claim moi scene.",
        "Simulation chat luong cao nen la Canvas-first voi state model, controls, va readouts.",
    ]

    world_items: List[str] = []
    if organization_id:
        world_items.append(f"Organization context: {organization_id}")
    page_type = ""
    if isinstance(host_context, dict):
        page = host_context.get("page") or {}
        if isinstance(page, dict):
            page_type = str(page.get("type") or "").strip()
    if not page_type and isinstance(page_context, dict):
        page_type = str(page_context.get("page_type") or "").strip()
    if page_type:
        world_items.append(f"Host/page type: {page_type}")

    return [
        MemoryBlockV1(namespace="persona", summary="Dieu Wiii giu ve chinh minh.", items=persona_items[:4]),
        MemoryBlockV1(namespace="human", summary="Su kien va so thich cua nguoi dung.", items=user_facts[:4]),
        MemoryBlockV1(namespace="relationship", summary="Nhip dong hanh giua Wiii va user.", items=relationship_items[:4]),
        MemoryBlockV1(namespace="goals", summary="Muc tieu dang song cua turn nay.", items=goals_items[:4]),
        MemoryBlockV1(namespace="craft", summary="Gu nghe va cach day cua Wiii.", items=craft_items[:4]),
        MemoryBlockV1(namespace="world", summary="Boi canh host va the gioi quanh turn nay.", items=world_items[:4]),
    ]


def compile_living_context_block(
    query: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    user_id: str = "__global__",
    organization_id: Optional[str] = None,
    domain_id: Optional[str] = None,
) -> LivingContextBlockV1:
    ctx = context or {}
    visual_decision = resolve_visual_intent(query)
    reasoning_policy = infer_reasoning_policy(query, context=ctx)
    card = build_character_card_payload(
        user_id=user_id,
        organization_id=organization_id,
        mood_hint=ctx.get("mood_hint"),
        personality_mode=ctx.get("personality_mode"),
    )

    current_state: List[str] = []
    for note in card.get("runtime_notes", [])[:4]:
        cleaned_note = _clip(str(note).strip(), 220)
        if cleaned_note and cleaned_note not in current_state:
            current_state.append(cleaned_note)
    mood_hint = _clip(str(ctx.get("mood_hint") or "").strip(), 220)
    if mood_hint and mood_hint not in current_state:
        current_state.append(mood_hint)

    narrative_state: List[str] = []
    living_state = _safe_character_state(user_id, organization_id)
    if living_state:
        narrative_state.append(living_state)
    narrative_context = _safe_narrative_context(organization_id)
    if narrative_context:
        narrative_state.append(narrative_context)
    if not narrative_state and card.get("runtime_notes"):
        narrative_state.extend(str(item) for item in card["runtime_notes"][:3] if item)

    relationship_memory: List[str] = []
    user_name = str(ctx.get("user_name") or "").strip()
    if user_name:
        relationship_memory.append(f"User hien tai: {user_name}")
    if ctx.get("is_follow_up"):
        relationship_memory.append("Day la mot turn noi tiep, uu tien giu nhip va nho dung ngu canh truoc do.")
    conversation_summary = _clip(str(ctx.get("conversation_summary") or "").strip(), 220)
    if conversation_summary:
        relationship_memory.append(conversation_summary)
    if not relationship_memory:
        relationship_memory.append("Neu khong can ke chuyen ve ban than, Wiii van nen hien dien nhu mot nguoi dong hanh on dinh va tiet che.")

    task_mode = {
        "task_class": reasoning_policy.task_class,
        "deliberation_floor": reasoning_policy.deliberation_level,
        "primary_lane": visual_decision.presentation_intent,
        "artifact_handoff": "follow-up prompt" if visual_decision.presentation_intent != "artifact" else "artifact lane",
    }
    if domain_id:
        task_mode["domain_id"] = domain_id

    visual_cognition = {
        "preferred_lane": visual_decision.presentation_intent,
        "preferred_render_surface": visual_decision.preferred_render_surface,
        "pedagogy_arc": "claim -> scene -> annotation -> takeaway",
        "narrative_voice": "subtle, companion-like, and clarity-first",
    }

    expression_policy = LivingExpressionPolicyV1(
        mode="subtle",
        avoid_mascotization=True,
        avoid_over_roleplay=True,
        prefer_companionship_over_performance=True,
    )

    return LivingContextBlockV1(
        core_card={
            "name": str(card.get("name") or "Wiii"),
            "summary": _clip(str(card.get("summary") or "").strip(), 180),
            "origin": _clip(str(card.get("origin") or "").strip(), 180),
            "identity_anchor": _clip(str(card.get("identity_anchor") or "").strip(), 180),
        },
        current_state=current_state[:4],
        narrative_state=narrative_state[:4],
        relationship_memory=relationship_memory[:4],
        task_mode=task_mode,
        reasoning_policy=reasoning_policy,
        visual_cognition=visual_cognition,
        expression_policy=expression_policy,
        memory_blocks=_compile_memory_blocks(
            query=query,
            context=ctx,
            user_id=user_id,
            organization_id=organization_id,
        ),
    )


def format_living_context_prompt(
    block: LivingContextBlockV1,
    *,
    include_memory_blocks: bool = True,
    include_visual_cognition: bool = True,
) -> str:
    lines = [
        "## Wiii Living Core Bridge",
        "- Đây vẫn là Wiii, không có nhân cách riêng theo agent hay lane.",
        "- Tên agent/lane chỉ là tên công việc hệ thống trong turn này.",
        "- Soul của Wiii nên lộ ra qua nhịp hiện diện, continuity, và cách gỡ rối; không phải roleplay hay mascot show.",
        "",
        "## Living Context Block V1",
        "",
        "### core_card",
        f"- name: {block.core_card.get('name', 'Wiii')}",
    ]

    summary = block.core_card.get("summary")
    if summary:
        lines.append(f"- summary: {summary}")
    origin = block.core_card.get("origin")
    if origin:
        lines.append(f"- origin: {origin}")
    identity_anchor = block.core_card.get("identity_anchor")
    if identity_anchor:
        lines.append(f"- identity_anchor: {identity_anchor}")

    lines.extend(["", "### current_state"])
    for item in block.current_state[:4]:
        lines.append(f"- {item}")

    lines.extend(["", "### narrative_state"])
    for item in block.narrative_state[:4]:
        lines.append(f"- {item}")

    lines.extend(["", "### relationship_memory"])
    for item in block.relationship_memory[:4]:
        lines.append(f"- {item}")

    lines.extend(["", "### task_mode"])
    for key, value in block.task_mode.items():
        if value:
            lines.append(f"- {key}: {value}")

    lines.extend(["", "### reasoning_policy"])
    lines.append(f"- task_class: {block.reasoning_policy.task_class}")
    lines.append(f"- deliberation_level: {block.reasoning_policy.deliberation_level}")
    lines.append(f"- pace_mode: {block.reasoning_policy.pace_mode}")
    lines.append(f"- thinking_visibility: {block.reasoning_policy.thinking_visibility}")
    lines.append(f"- handoff_policy: {block.reasoning_policy.handoff_policy}")

    if include_visual_cognition:
        lines.extend(["", "### visual_cognition"])
        for key, value in block.visual_cognition.items():
            if value:
                lines.append(f"- {key}: {value}")

    lines.extend(["", "### living_expression_policy"])
    lines.append(f"- mode: {block.expression_policy.mode}")
    lines.append("- do not mascotize Wiii or add decorative lore in task output")
    lines.append("- keep story subtle unless it helps trust, memory, or understanding")

    if include_memory_blocks:
        lines.extend(["", "## Memory Blocks V1"])
        for block_item in block.memory_blocks:
            lines.append(f"### {block_item.namespace}")
            lines.append(f"- summary: {block_item.summary}")
            for item in block_item.items[:4]:
                lines.append(f"- {item}")

    return "\n".join(lines)
