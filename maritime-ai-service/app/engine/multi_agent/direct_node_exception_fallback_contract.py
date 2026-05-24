"""Typed contracts for Direct Node exception fallback handling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.state import AgentState


@dataclass(frozen=True, slots=True)
class DirectNodeExceptionFallbackRequest:
    """Per-turn state captured when Direct Node generation fails."""

    exc: Exception
    query: str
    state: AgentState
    ctx_for_preflight: dict[str, Any]
    tools: list[Any]
    tool_call_events: list[dict[str, Any]]
    llm_response: Any
    messages: list[Any]
    llm: Any
    routing_intent: str
    response_language: str
    is_identity_turn: bool
    explicit_user_provider: str | None
    explicit_web_search_turn: bool
    tracer: Any
    push_event: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class DirectNodeExceptionFallbackDependencies:
    """Injected app contracts used by Direct Node exception fallback recovery."""

    needs_web_search: Callable[[str], bool]
    extract_direct_response: Callable[..., Any]
    sanitize_structured_visual_answer_text: Callable[..., str]
    sanitize_wiii_house_text: Callable[..., str]
    build_search_template_fallback: Callable[..., str]
    build_uploaded_document_context_fallback_answer: Callable[..., str]
    build_codebase_analysis_fallback_answer: Callable[[str], str]
    build_codebase_analysis_fallback_thinking: Callable[[str], str]
    get_phase_fallback: Callable[[AgentState], str]
    record_direct_node_thinking_snapshot: Callable[..., str]
    record_thinking_snapshot_fn: Callable[..., Any]
    inc_counter: Callable[..., Any]
    logger_obj: logging.Logger
    salvage_direct_turn_from_final_result_fn: Callable[..., Any] | None = None
    emergency_search_fallback_fn: Callable[..., Any] | None = None
    emit_synthetic_tool_events_fn: Callable[..., Any] | None = None
    classify_failover_reason_fn: Callable[..., dict[str, Any]] | None = None


@dataclass(frozen=True)
class DirectNodeExceptionFallbackResult:
    """Recovered direct-node response after an exception path."""

    response: str
    tool_call_events: list[dict[str, Any]]
