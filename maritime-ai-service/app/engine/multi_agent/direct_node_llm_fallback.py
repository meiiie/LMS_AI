"""Fallback lifecycle for direct-node turns when no LLM is available."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.state import AgentState


RecordDirectThinkingSnapshot = Callable[..., Any]
RecordThinkingSnapshot = Callable[..., Any]


@dataclass(frozen=True)
class DirectNodeLlmUnavailableFallback:
    """Resolved response for the no-LLM direct-node branch."""

    response: str
    response_type: str


def resolve_direct_node_llm_unavailable_fallback(
    *,
    query: str,
    state: AgentState,
    explicit_user_provider: str | None,
    explicit_web_search_turn: bool,
    enable_natural_conversation: bool,
    get_phase_fallback: Callable[[AgentState], str],
    build_codebase_analysis_fallback_answer: Callable[[str], str],
    build_codebase_analysis_fallback_thinking: Callable[[str], str],
    record_direct_node_thinking_snapshot: RecordDirectThinkingSnapshot,
    record_thinking_snapshot_fn: RecordThinkingSnapshot,
) -> DirectNodeLlmUnavailableFallback:
    """Fail closed or build a deterministic fallback when LLM resolution is empty."""

    if explicit_user_provider:
        raise ProviderUnavailableError(
            provider=str(explicit_user_provider).strip().lower(),
            reason_code="busy",
            message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
        )

    if _is_codebase_analysis_query(query) and not explicit_web_search_turn:
        response = build_codebase_analysis_fallback_answer(query)
        codebase_thinking = build_codebase_analysis_fallback_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=codebase_thinking,
            provenance="deterministic_codebase_fallback",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
        )
        return DirectNodeLlmUnavailableFallback(
            response=response,
            response_type="codebase_source_backed_fallback",
        )

    response = (
        get_phase_fallback(state)
        if enable_natural_conversation
        else "Xin chao! Toi co the giup gi cho ban?"
    )
    return DirectNodeLlmUnavailableFallback(
        response=response,
        response_type="fallback",
    )
