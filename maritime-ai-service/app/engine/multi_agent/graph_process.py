"""Process entrypoint helpers extracted from the multi-agent runtime shell."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.config import settings
from app.engine.llm_runtime_metadata import resolve_runtime_failover_metadata
from app.engine.multi_agent.runtime_flow_ledger import build_runtime_flow_trace_from_state
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import build_thinking_lifecycle_snapshot
from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload

logger = logging.getLogger(__name__)


_TOKEN_USAGE_NUMERIC_KEYS = {
    "total_calls",
    "total_input_tokens",
    "total_output_tokens",
    "total_tokens",
    "estimated_cost_usd",
    "duration_ms",
}


def _sanitize_token_usage(value: Any) -> dict[str, Any] | None:
    """Preserve usage counters while applying an allowlist boundary."""

    if not isinstance(value, dict):
        return None
    safe: dict[str, Any] = {}
    for key in _TOKEN_USAGE_NUMERIC_KEYS:
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            safe[key] = item
    return safe or None


def _serialize_langchain_messages(context: dict | None) -> list[dict]:
    """Convert LangChain messages to serializable dict payloads."""
    langchain_messages = (context or {}).get("langchain_messages", [])
    serialized_messages = []
    for message in langchain_messages:
        if isinstance(message, dict):
            serialized_messages.append(message)
        else:
            serialized_messages.append(
                {
                    "role": getattr(message, "type", "human"),
                    "content": message.content,
                }
            )
    return serialized_messages


def _split_model_context(context: dict | None) -> tuple[dict, dict | None]:
    """Remove backend-only continuation data from model-facing context."""

    model_context = dict(context or {})
    host_action_control_feedback = model_context.pop(
        "_host_action_control_feedback",
        None,
    )
    return model_context, host_action_control_feedback


def _apply_graph_context_prompts(
    initial_state: AgentState,
    *,
    inject_document_context,
    inject_host_context,
    inject_host_session,
    inject_operator_context,
    inject_living_context,
    inject_visual_context,
    inject_visual_cognition_context,
    inject_widget_feedback_context,
    inject_code_studio_context,
) -> None:
    """Populate graph-level prompt surfaces shared by all downstream nodes."""
    host_prompt = inject_host_context(initial_state)
    if host_prompt:
        initial_state["host_context_prompt"] = host_prompt
    document_prompt = inject_document_context(initial_state)
    if document_prompt:
        existing_host_prompt = initial_state.get("host_context_prompt", "")
        initial_state["document_context_prompt"] = document_prompt
        initial_state["host_context_prompt"] = (
            f"{existing_host_prompt}\n\n{document_prompt}"
            if existing_host_prompt
            else document_prompt
        )
    host_capabilities_prompt = initial_state.get("host_capabilities_prompt", "")
    if host_capabilities_prompt:
        initial_state["host_capabilities_prompt"] = host_capabilities_prompt
    host_session_prompt = inject_host_session(initial_state)
    if host_session_prompt:
        initial_state["host_session_prompt"] = host_session_prompt
    operator_prompt = inject_operator_context(initial_state)
    if operator_prompt:
        initial_state["operator_context_prompt"] = operator_prompt
    living_prompt = inject_living_context(initial_state)
    if living_prompt:
        initial_state["living_context_prompt"] = living_prompt
    visual_prompt = inject_visual_context(initial_state)
    if visual_prompt:
        initial_state["visual_context_prompt"] = visual_prompt
    visual_cognition_prompt = inject_visual_cognition_context(initial_state)
    if visual_cognition_prompt:
        initial_state["visual_cognition_prompt"] = visual_cognition_prompt
    widget_feedback_prompt = inject_widget_feedback_context(initial_state)
    if widget_feedback_prompt:
        initial_state["widget_feedback_prompt"] = widget_feedback_prompt
    code_studio_prompt = inject_code_studio_context(initial_state)
    if code_studio_prompt:
        initial_state["code_studio_context_prompt"] = code_studio_prompt


async def _upsert_thread_view(
    *,
    query: str,
    user_id: str,
    session_id: str,
    domain_id: str,
    context: dict | None,
    summary_milestones: set[int],
    generate_session_summary_bg,
) -> None:
    """Update the thread index and trigger background summarization when needed."""
    if not (session_id and user_id):
        return
    try:
        from app.repositories.thread_repository import get_thread_repository
        from app.core.thread_utils import build_thread_id as _build_tid

        organization_id = (context or {}).get("organization_id")
        thread_id = _build_tid(user_id, session_id, org_id=organization_id)
        title = query[:60] + ("..." if len(query) > 60 else "")
        thread_data = get_thread_repository().upsert_thread(
            thread_id=thread_id,
            user_id=user_id,
            domain_id=domain_id,
            title=title,
            organization_id=organization_id,
        )
        if thread_data:
            count = thread_data.get("message_count", 0)
            if count in summary_milestones:
                asyncio.create_task(
                    generate_session_summary_bg(
                        thread_id,
                        user_id,
                        organization_id,
                    )
                )
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning("Thread upsert failed: %s", exc)


def _build_process_result_payload(
    *,
    result: dict,
    trace_id: str,
    trace_summary: dict,
    tracker,
    resolve_public_thinking_content,
) -> dict:
    """Shape the final sync API payload from graph state."""
    public_source_state = dict(result)
    public_source_state["thinking"] = ""
    thinking_content = resolve_public_thinking_content(
        public_source_state,
        fallback=result.get("thinking_content") or "",
    )

    lifecycle_state = {
        "current_agent": result.get("current_agent"),
        "next_agent": result.get("next_agent"),
        "routing_metadata": result.get("routing_metadata"),
        "thinking_content": thinking_content,
    }
    thinking_lifecycle = build_thinking_lifecycle_snapshot(
        lifecycle_state,
        fallback=thinking_content,
    )
    token_usage = _sanitize_token_usage(tracker.summary() if tracker else None)
    return {
        "response": sanitize_runtime_payload(result.get("final_response", "")),
        "sources": sanitize_runtime_payload(result.get("sources", [])),
        "tools_used": sanitize_runtime_payload(result.get("tools_used", [])),
        "grader_score": result.get("grader_score", 0),
        "agent_outputs": sanitize_runtime_payload(result.get("agent_outputs", {})),
        "current_agent": result.get("current_agent", ""),
        "next_agent": result.get("next_agent", ""),
        "error": sanitize_runtime_payload(result.get("error")),
        "reasoning_trace": sanitize_runtime_payload(result.get("reasoning_trace")),
        "thinking": thinking_content or None,
        "thinking_content": sanitize_runtime_payload(thinking_content),
        "thinking_lifecycle": sanitize_runtime_payload(thinking_lifecycle),
        "domain_notice": sanitize_runtime_payload(result.get("domain_notice")),
        "routing_metadata": sanitize_runtime_payload(result.get("routing_metadata")),
        "evidence_images": sanitize_runtime_payload(result.get("evidence_images", [])),
        "provider": result.get("_execution_provider") or result.get("provider"),
        "model": result.get("_execution_model") or result.get("model"),
        "_execution_provider": result.get("_execution_provider"),
        "_execution_model": result.get("_execution_model"),
        "_llm_failover_events": sanitize_runtime_payload(
            result.get("_llm_failover_events", []),
        ),
        "failover": sanitize_runtime_payload(
            result.get("failover") or resolve_runtime_failover_metadata(result),
        ),
        "trace_id": trace_id,
        "trace_summary": sanitize_runtime_payload(trace_summary),
        "runtime_flow_trace": sanitize_runtime_payload(
            build_runtime_flow_trace_from_state(result),
        ),
        "token_usage": token_usage,
    }


async def process_with_multi_agent_impl(
    *,
    query: str,
    user_id: str,
    session_id: str = "",
    context: dict | None = None,
    domain_id: Optional[str] = None,
    thinking_effort: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    build_domain_config,
    build_turn_local_state_defaults,
    cleanup_tracer,
    resolve_public_thinking_content,
    generate_session_summary_bg,
    inject_document_context,
    inject_host_context,
    inject_host_session,
    inject_operator_context,
    inject_living_context,
    inject_visual_context,
    inject_visual_cognition_context,
    inject_widget_feedback_context,
    inject_code_studio_context,
    summary_milestones: set[int],
):
    """High-level sync processing entrypoint for the multi-agent system."""
    from app.core.token_tracker import start_tracking, get_tracker
    from app.engine.agents import get_agent_registry
    from app.engine.multi_agent.graph_event_bus import _cleanup_stale_queues

    domain_id = domain_id or settings.default_domain
    registry = get_agent_registry()
    model_context, host_action_control_feedback = _split_model_context(context)

    start_tracking(request_id=session_id or "")
    trace_id = registry.start_request_trace()
    logger.info("[MULTI_AGENT] Started trace: %s, domain=%s", trace_id, domain_id)

    initial_state: AgentState = {
        "query": query,
        "user_id": user_id,
        "session_id": session_id,
        "context": model_context,
        "messages": _serialize_langchain_messages(model_context),
        "current_agent": "",
        "next_agent": "",
        "agent_outputs": {},
        "grader_score": 0.0,
        "grader_feedback": "",
        "final_response": "",
        "sources": [],
        "iteration": 0,
        "max_iterations": 3,
        "error": None,
        "domain_id": domain_id,
        "domain_config": build_domain_config(domain_id),
        "thinking_effort": thinking_effort,
        "provider": provider,
        "model": model,
        "routing_metadata": None,
        "organization_id": model_context.get("organization_id"),
        "_host_action_control_feedback": host_action_control_feedback,
        **build_turn_local_state_defaults(model_context),
    }

    _apply_graph_context_prompts(
        initial_state,
        inject_document_context=inject_document_context,
        inject_host_context=inject_host_context,
        inject_host_session=inject_host_session,
        inject_operator_context=inject_operator_context,
        inject_living_context=inject_living_context,
        inject_visual_context=inject_visual_context,
        inject_visual_cognition_context=inject_visual_cognition_context,
        inject_widget_feedback_context=inject_widget_feedback_context,
        inject_code_studio_context=inject_code_studio_context,
    )

    _cleanup_stale_queues()

    trace_id_for_cleanup = initial_state.get("_trace_id")
    try:
        from app.engine.multi_agent.runner import get_wiii_runner

        runner = get_wiii_runner()
        result = await runner.run(initial_state)
        logger.info("[MULTI_AGENT] Executed via WiiiRunner")
        trace_id_for_cleanup = result.get("_trace_id", trace_id_for_cleanup)
    finally:
        cleanup_tracer(trace_id_for_cleanup)

    await _upsert_thread_view(
        query=query,
        user_id=user_id,
        session_id=session_id,
        domain_id=domain_id,
        context=context,
        summary_milestones=summary_milestones,
        generate_session_summary_bg=generate_session_summary_bg,
    )

    trace_summary = registry.end_request_trace(trace_id)
    logger.info(
        "[MULTI_AGENT] Trace completed: %d spans, %.1fms",
        trace_summary.get("span_count", 0),
        trace_summary.get("total_duration_ms", 0),
    )

    tracker = get_tracker()
    if tracker:
        try:
            calls = getattr(tracker, "calls", None)
            if calls:
                from app.services.llm_usage_logger import log_llm_usage_batch

                asyncio.ensure_future(
                    log_llm_usage_batch(
                        request_id=session_id or "",
                        user_id=user_id or "",
                        session_id=session_id or "",
                        calls=calls,
                        organization_id=(context or {}).get("organization_id"),
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive logging only
            logger.debug("[MULTI_AGENT] LLM usage batch log failed: %s", exc)

    return _build_process_result_payload(
        result=result,
        trace_id=trace_id,
        trace_summary=trace_summary,
        tracker=tracker,
        resolve_public_thinking_content=resolve_public_thinking_content,
    )
