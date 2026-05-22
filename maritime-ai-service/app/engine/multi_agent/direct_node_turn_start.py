"""Turn-start lifecycle helpers for the direct node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_codebase_analysis_fallback_answer,
    _build_codebase_analysis_fallback_thinking,
    _is_explicit_web_search_turn_for_direct,
    _should_use_codebase_source_note_fast_answer,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.state import AgentState


GetDomainGreetings = Callable[[str], dict[str, str]]
RecordThinkingSnapshot = Callable[..., Any]


@dataclass(frozen=True)
class DirectNodeTurnStart:
    """Resolved deterministic state at the start of a direct-node turn."""

    query_lower: str
    response: str | None
    response_type: str
    explicit_web_search_turn: bool


def start_direct_node_turn(
    *,
    query: str,
    state: AgentState,
    enable_natural_conversation: bool,
    default_domain: str,
    get_domain_greetings: GetDomainGreetings,
    record_thinking_snapshot_fn: RecordThinkingSnapshot,
) -> DirectNodeTurnStart:
    """Resolve greetings and source-backed codebase fast paths before LLM work."""

    query_lower = query.lower().strip()
    response: str | None = None
    if not enable_natural_conversation:
        greetings = get_domain_greetings(str(state.get("domain_id", default_domain)))
        response = greetings.get(query_lower)

    response_type = "greeting" if response else ""
    explicit_web_search_turn = _is_explicit_web_search_turn_for_direct(query, state)
    if not response and _is_codebase_analysis_query(query) and not explicit_web_search_turn:
        codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=codebase_thinking,
            provenance="codebase_source_backed_plan",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
        )
        if _should_use_codebase_source_note_fast_answer(query):
            response = _build_codebase_analysis_fallback_answer(query)
            response_type = "codebase_source_backed_fast"

    return DirectNodeTurnStart(
        query_lower=query_lower,
        response=response,
        response_type=response_type,
        explicit_web_search_turn=explicit_web_search_turn,
    )
