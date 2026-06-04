"""Per-turn planning policy for the direct node."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.direct_intent import _looks_emotional_support_turn
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _is_explicit_web_search_turn_for_direct,
)
from app.engine.multi_agent.direct_node_thinking_effort import (
    _resolve_direct_thinking_effort,
)
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.social_followup_policy import (
    looks_short_social_followup_turn,
)
from app.engine.multi_agent.state import AgentState


TextPredicate = Callable[[str], bool]
StateGetter = Callable[[AgentState], Any]
VisualIntentResolver = Callable[[str], Any]
RecommendedVisualEffort = Callable[..., Any]
MergeThinkingEffort = Callable[[Any, Any], Any]


@dataclass(frozen=True)
class DirectNodeTurnPolicy:
    """Resolved direct-node planning state used before tool and LLM execution."""

    ctx: dict[str, Any]
    response_language: str
    thinking_effort: Any
    routing_intent: str
    is_identity_turn: bool
    is_emotional_support_turn: bool
    is_short_house_chatter: bool
    visual_decision: Any
    history_limit: int
    tools_context_override: str | None
    role_name: str
    preferred_provider: Any
    explicit_user_provider: Any
    use_house_voice_direct: bool
    direct_provider_override: Any
    is_codebase_source_turn: bool
    explicit_web_search_turn: bool


def _turn_path_requires_tools(state: AgentState) -> bool:
    if not isinstance(state, dict):
        return False
    decision = state.get("_turn_path_decision")
    if not isinstance(decision, dict):
        return False
    return bool(decision.get("bind_tools", True)) and bool(decision.get("force_tools"))


def resolve_direct_node_turn_policy(
    *,
    query: str,
    state: AgentState,
    has_uploaded_document_context: bool,
    normalize_for_intent: Callable[[str], str],
    looks_identity_selfhood_turn: TextPredicate,
    needs_web_search: TextPredicate,
    needs_datetime: TextPredicate,
    resolve_visual_intent: VisualIntentResolver,
    recommended_visual_thinking_effort: RecommendedVisualEffort,
    get_active_code_studio_session: StateGetter,
    merge_thinking_effort: MergeThinkingEffort,
    get_effective_provider: StateGetter,
    get_explicit_user_provider: StateGetter,
    looks_uploaded_document_preview_request: TextPredicate,
    logger_obj: logging.Logger | None = None,
) -> DirectNodeTurnPolicy:
    """Resolve the per-turn policy that feeds tools, prompts, and provider choice."""

    ctx = state.get("context", {})
    response_language = str(ctx.get("response_language") or "vi").strip() or "vi"
    thinking_effort = state.get("thinking_effort")
    routing_meta = state.get("routing_metadata") or {}
    routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
    routing_method = str(routing_meta.get("method") or "").strip().lower()
    routing_intent = str(routing_meta.get("intent") or "").strip().lower()
    hint_kind = str(routing_hint.get("kind") or "").strip().lower()
    hint_shape = str(routing_hint.get("shape") or "").strip().lower()
    normalized_query = normalize_for_intent(query)
    short_token_count = len([token for token in normalized_query.split() if token])
    is_identity_turn = (
        hint_kind == "identity_probe"
        or hint_kind == "selfhood_followup"
        or routing_intent in {"identity", "selfhood"}
        or looks_identity_selfhood_turn(query)
    )
    is_emotional_support_turn = _looks_emotional_support_turn(query)
    is_chatter_fast_path = (
        routing_method == "always_on_chatter_fast_path"
        or (
            hint_kind == "fast_chatter"
            and hint_shape
            in {"hunger_chatter", "reaction", "social_status", "vague_banter"}
        )
    )
    is_social_followup_chatter = (
        not is_identity_turn
        and (
            (hint_kind == "fast_chatter" and hint_shape == "social_followup")
            or looks_short_social_followup_turn(normalized_query)
        )
    )
    is_social_fast_path = (
        routing_method == "always_on_social_fast_path"
        or (
            hint_kind == "fast_chatter"
            and hint_shape in {"social", "social_followup", "social_status"}
        )
    )
    visual_decision = resolve_visual_intent(query)
    turn_path_requires_tools = _turn_path_requires_tools(state)
    is_short_house_chatter = (
        not is_identity_turn
        and not turn_path_requires_tools
        and (
            is_chatter_fast_path
            or is_social_fast_path
            or is_social_followup_chatter
            or (
                routing_intent == "social"
                and short_token_count <= 6
                and not needs_web_search(query)
                and not needs_datetime(query)
                and not visual_decision.force_tool
            )
        )
    )
    history_limit = 4 if is_social_followup_chatter else (0 if is_short_house_chatter else 10)
    tools_context_override = "" if is_short_house_chatter else None
    role_name = (
        "direct_chatter_agent"
        if (is_short_house_chatter or is_identity_turn)
        else "direct_agent"
    )
    if is_identity_turn:
        history_limit = max(history_limit, 6)
    thinking_effort = _resolve_direct_thinking_effort(
        query=query,
        state=state,
        current_effort=thinking_effort,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
    )

    visual_effort = recommended_visual_thinking_effort(
        query,
        active_code_session=get_active_code_studio_session(state),
    )
    if visual_effort:
        previous_effort = thinking_effort
        thinking_effort = merge_thinking_effort(
            thinking_effort,
            visual_effort,
        )
        if thinking_effort != previous_effort and logger_obj is not None:
            logger_obj.info(
                "[DIRECT] Visual intent detected -> upgrade thinking effort %s -> %s",
                previous_effort or "default",
                thinking_effort,
            )

    preferred_provider = get_effective_provider(state)
    explicit_user_provider = get_explicit_user_provider(state)
    use_house_voice_direct = (
        routing_intent in {"social", "personal", "off_topic"}
        and not turn_path_requires_tools
        and not needs_web_search(query)
        and not needs_datetime(query)
        and not visual_decision.force_tool
    )
    direct_provider_override = explicit_user_provider or preferred_provider
    is_codebase_source_turn = _is_codebase_analysis_query(query) and not (
        has_uploaded_document_context
        and looks_uploaded_document_preview_request(query)
    )
    explicit_web_search_turn = _is_explicit_web_search_turn_for_direct(query, state)

    return DirectNodeTurnPolicy(
        ctx=ctx,
        response_language=response_language,
        thinking_effort=thinking_effort,
        routing_intent=routing_intent,
        is_identity_turn=is_identity_turn,
        is_emotional_support_turn=is_emotional_support_turn,
        is_short_house_chatter=is_short_house_chatter,
        visual_decision=visual_decision,
        history_limit=history_limit,
        tools_context_override=tools_context_override,
        role_name=role_name,
        preferred_provider=preferred_provider,
        explicit_user_provider=explicit_user_provider,
        use_house_voice_direct=use_house_voice_direct,
        direct_provider_override=direct_provider_override,
        is_codebase_source_turn=is_codebase_source_turn,
        explicit_web_search_turn=explicit_web_search_turn,
    )
