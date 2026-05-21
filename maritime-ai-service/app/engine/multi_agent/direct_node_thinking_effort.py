"""Thinking-effort policy for direct-node turns."""

from __future__ import annotations

from app.engine.multi_agent.direct_node_visible_thought import _IDENTITY_ORIGIN_QUERY_MARKERS
from app.engine.multi_agent.direct_reasoning import _infer_direct_thinking_mode
from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.visual_intent_resolver import merge_thinking_effort

_DIRECT_CANONICAL_THINKING_EFFORT_ALIASES = {
    "light": "low",
    "low": "low",
    "moderate": "medium",
    "medium": "medium",
    "deep": "high",
    "high": "high",
    "max": "max",
}
_DIRECT_ANALYTICAL_THINKING_MODES = {
    "analytical_general",
    "analytical_market",
    "analytical_math",
}


def _canonicalize_direct_thinking_effort(value: str | None) -> str | None:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    return _DIRECT_CANONICAL_THINKING_EFFORT_ALIASES.get(candidate)


def _resolve_direct_thinking_effort(
    *,
    query: str,
    state: AgentState,
    current_effort: str | None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
) -> str | None:
    canonical_effort = _canonicalize_direct_thinking_effort(current_effort)
    local_effort: str | None = None

    if is_short_house_chatter:
        local_effort = "low"
    else:
        folded_query = _fold_direct_text(query)
        if is_identity_turn:
            if any(marker in folded_query for marker in _IDENTITY_ORIGIN_QUERY_MARKERS):
                local_effort = "max"
            else:
                local_effort = "high"
        else:
            thinking_mode = _infer_direct_thinking_mode(query, state, [])
            if thinking_mode in _DIRECT_ANALYTICAL_THINKING_MODES:
                local_effort = "high"

    # Direct lane should be allowed to override generic routing defaults such as
    # medium/moderate, while still preserving explicit higher asks like max.
    if canonical_effort in {"high", "max"}:
        return merge_thinking_effort(local_effort, canonical_effort)
    if local_effort:
        return local_effort
    return canonical_effort
