"""Parallel subagent dispatch helpers extracted from graph orchestration."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.subagents.event_stream import (
    push_subagent_stream_event,
    sanitize_subagent_stream_event,
)
from app.engine.multi_agent.subagents.handoff_context import (
    project_state_for_subagent,
)
from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
)
from app.engine.reasoning import sanitize_visible_reasoning_text

logger = logging.getLogger(__name__)

_DEFAULT_PARALLEL_TARGETS = ("rag", "tutor")


def _project_state_for_subagent(state: dict) -> dict[str, Any]:
    """Compatibility wrapper for older tests/imports."""

    return project_state_for_subagent(state)


def _sanitize_subagent_event(event: dict) -> dict[str, Any]:
    return sanitize_subagent_stream_event(event)


def _push_bus_event(state: dict, event: dict) -> None:
    """Push a raw event to the streaming bus when one is attached."""
    bus_id = state.get("_event_bus_id")
    if not bus_id:
        return
    safe_event = _sanitize_subagent_event(event)
    if not safe_event:
        return
    try:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue

        queue = _get_event_queue(bus_id)
        if queue:
            push_subagent_stream_event(queue, safe_event)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[SUBAGENT_EVENT] Event emit failed: %s", exc)


def _emit_subagent_event_impl(
    state: dict,
    event: dict,
    *,
    capture_public_thinking_event: Callable[[dict, dict], None],
) -> None:
    """Emit an SSE event from a subagent adapter via the event bus."""
    safe_event = _sanitize_subagent_event(event)
    if not safe_event:
        return
    capture_public_thinking_event(state, safe_event)
    _push_bus_event(state, safe_event)


def _normalize_parallel_targets(
    raw_targets: Any,
    *,
    subagent_adapters: dict[str, Callable[..., Any]],
) -> list[str]:
    if raw_targets is None:
        candidates: list[Any] = list(_DEFAULT_PARALLEL_TARGETS)
    elif isinstance(raw_targets, str):
        candidates = [raw_targets]
    elif isinstance(raw_targets, (list, tuple, set)):
        candidates = list(raw_targets)
    else:
        logger.warning(
            "[PARALLEL_DISPATCH] Invalid target plan type: %s",
            type(raw_targets).__name__,
        )
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for raw_name in candidates:
        name = redact_runtime_secret_text(str(raw_name or "")[:128]).strip()
        if not name:
            continue
        if name in seen:
            logger.debug("[PARALLEL_DISPATCH] Duplicate target skipped: %s", name)
            continue
        seen.add(name)
        if name not in subagent_adapters:
            logger.warning("[PARALLEL_DISPATCH] Unknown target: %s, skipping", name)
            continue
        targets.append(name)
    return targets


def build_subagent_registry_impl(
    *,
    render_reasoning_fast,
    capture_public_thinking_event,
    thinking_start_label,
) -> tuple[dict[str, Callable[..., Any]], dict[str, str]]:
    """Build subagent adapter registries for the graph shell."""

    def emit_subagent_event(state: dict, event: dict) -> None:
        _emit_subagent_event_impl(
            state,
            event,
            capture_public_thinking_event=capture_public_thinking_event,
        )

    async def run_rag_subagent(state: dict, **kwargs):
        return await _run_rag_subagent_impl(
            state,
            render_reasoning_fast=render_reasoning_fast,
            emit_subagent_event=emit_subagent_event,
            thinking_start_label=thinking_start_label,
            **kwargs,
        )

    async def run_tutor_subagent(state: dict, **kwargs):
        return await _run_tutor_subagent_impl(
            state,
            render_reasoning_fast=render_reasoning_fast,
            emit_subagent_event=emit_subagent_event,
            thinking_start_label=thinking_start_label,
            **kwargs,
        )

    async def run_search_subagent(state: dict, **kwargs):
        return await _run_search_subagent_impl(
            state,
            render_reasoning_fast=render_reasoning_fast,
            emit_subagent_event=emit_subagent_event,
            thinking_start_label=thinking_start_label,
            **kwargs,
        )

    return (
        {
            "rag": run_rag_subagent,
            "tutor": run_tutor_subagent,
            "search": run_search_subagent,
        },
        {
            "rag": "retrieval",
            "tutor": "teaching",
            "search": "product_search",
        },
    )


async def _run_rag_subagent_impl(
    state: dict,
    *,
    render_reasoning_fast,
    emit_subagent_event,
    thinking_start_label,
    **kwargs,
):
    """Adapter: run existing RAG agent and wrap output as SubagentResult."""
    del kwargs
    from app.engine.multi_agent.agents.rag_node import get_rag_agent_node
    from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus

    rag_opening = await render_reasoning_fast(
        state=state,
        node="rag_agent",
        phase="retrieve",
        cue="parallel_dispatch",
        next_action="Lục lại kho tri thức rồi gạn nguồn đỡ câu hỏi nhất.",
        style_tags=["rag", "parallel_dispatch"],
    )

    emit_subagent_event(
        state,
        {
            "type": "thinking_start",
            "content": thinking_start_label(rag_opening.label),
            "node": "rag",
            "summary": rag_opening.summary,
            "details": {"phase": rag_opening.phase},
        },
    )
    emit_subagent_event(
        state,
        {
            "type": "status",
            "content": "Tìm kiếm trong kho tri thức...",
            "node": "rag",
            "details": {"visibility": "status_only"},
        },
    )

    try:
        rag_agent = get_rag_agent_node()
        result_state = await rag_agent.process(state)

        emit_subagent_event(
            state,
            {
                "type": "status",
                "content": "Đánh giá tài liệu và tạo câu trả lời...",
                "node": "rag",
                "details": {"visibility": "status_only"},
            },
        )

        output = result_state.get("rag_output", "") or result_state.get("final_response", "")
        trace = result_state.get("reasoning_trace")
        if trace and hasattr(trace, "final_confidence"):
            confidence = trace.final_confidence or 0.0
        elif result_state.get("grader_score"):
            confidence = result_state["grader_score"] / 10.0
        else:
            confidence = 0.6 if output else 0.0

        thinking = sanitize_visible_reasoning_text(
            str(result_state.get("thinking") or ""),
            user_goal=str(state.get("query") or ""),
        )
        if thinking:
            emit_subagent_event(
                state,
                {
                    "type": "thinking_delta",
                    "content": thinking[:500],
                    "node": "rag",
                },
            )

        emit_subagent_event(state, {"type": "thinking_end", "node": "rag"})

        return SubagentResult(
            status=SubagentStatus.SUCCESS if output else SubagentStatus.PARTIAL,
            output=output,
            confidence=confidence,
            sources=result_state.get("sources", []),
            evidence_images=result_state.get("evidence_images", []),
            thinking=thinking,
        )
    except Exception as exc:
        logger.warning("[PARALLEL_DISPATCH] RAG subagent error: %s", exc)
        emit_subagent_event(state, {"type": "thinking_end", "node": "rag"})
        return SubagentResult(
            status=SubagentStatus.ERROR,
            error_message="RAG subagent processing error",
        )


async def _run_tutor_subagent_impl(
    state: dict,
    *,
    render_reasoning_fast,
    emit_subagent_event,
    thinking_start_label,
    **kwargs,
):
    """Adapter: run existing Tutor agent and wrap output as SubagentResult."""
    del kwargs
    from app.engine.multi_agent.agents.tutor_node import get_tutor_agent_node
    from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus

    tutor_opening = await render_reasoning_fast(
        state=state,
        node="tutor_agent",
        phase="attune",
        cue="parallel_dispatch",
        next_action="Bắt nhịp điều người dùng đang vướng rồi soạn lại đường giải thích.",
        style_tags=["tutor", "parallel_dispatch"],
    )

    emit_subagent_event(
        state,
        {
            "type": "thinking_start",
            "content": thinking_start_label(tutor_opening.label),
            "node": "tutor",
            "summary": tutor_opening.summary,
            "details": {"phase": tutor_opening.phase},
        },
    )
    emit_subagent_event(
        state,
        {
            "type": "status",
            "content": "Đang chuẩn bị phần giải thích...",
            "node": "tutor",
            "details": {"visibility": "status_only"},
        },
    )

    try:
        tutor_agent = get_tutor_agent_node()
        result_state = await tutor_agent.process(state)

        emit_subagent_event(
            state,
            {
                "type": "status",
                "content": "Đang viết lại lời giải...",
                "node": "tutor",
                "details": {"visibility": "status_only"},
            },
        )

        output = result_state.get("tutor_output", "") or result_state.get("final_response", "")
        confidence = 0.7 if output else 0.0

        thinking = sanitize_visible_reasoning_text(
            str(result_state.get("thinking") or ""),
            user_goal=str(state.get("query") or ""),
        )
        if thinking:
            emit_subagent_event(
                state,
                {
                    "type": "thinking_delta",
                    "content": thinking[:500],
                    "node": "tutor",
                },
            )

        emit_subagent_event(state, {"type": "thinking_end", "node": "tutor"})

        return SubagentResult(
            status=SubagentStatus.SUCCESS if output else SubagentStatus.PARTIAL,
            output=output,
            confidence=confidence,
            sources=result_state.get("sources", []),
            tools_used=result_state.get("tools_used", []),
            thinking=thinking,
        )
    except Exception as exc:
        logger.warning("[PARALLEL_DISPATCH] Tutor subagent error: %s", exc)
        emit_subagent_event(state, {"type": "thinking_end", "node": "tutor"})
        return SubagentResult(
            status=SubagentStatus.ERROR,
            error_message="Tutor subagent processing error",
        )


async def _run_search_subagent_impl(
    state: dict,
    *,
    render_reasoning_fast,
    emit_subagent_event,
    thinking_start_label,
    **kwargs,
):
    """Adapter: run product search and wrap output as SubagentResult."""
    del kwargs
    from app.engine.multi_agent.agents.product_search_node import get_product_search_agent_node
    from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus

    search_opening = await render_reasoning_fast(
        state=state,
        node="product_search_agent",
        phase="retrieve",
        cue="parallel_dispatch",
        next_action="Mở nhiều nguồn giá song song rồi gạn lại mặt bằng đáng tin.",
        style_tags=["product_search", "parallel_dispatch"],
    )

    emit_subagent_event(
        state,
        {
            "type": "thinking_start",
            "content": thinking_start_label(search_opening.label),
            "node": "search",
            "summary": search_opening.summary,
            "details": {"phase": search_opening.phase},
        },
    )

    try:
        agent = get_product_search_agent_node()
        result_state = await agent.process(state)
        output = result_state.get("final_response", "")
        confidence = 0.7 if output else 0.0

        emit_subagent_event(state, {"type": "thinking_end", "node": "search"})

        return SubagentResult(
            status=SubagentStatus.SUCCESS if output else SubagentStatus.PARTIAL,
            output=output,
            confidence=confidence,
            tools_used=result_state.get("tools_used", []),
        )
    except Exception as exc:
        logger.warning("[PARALLEL_DISPATCH] Search subagent error: %s", exc)
        emit_subagent_event(state, {"type": "thinking_end", "node": "search"})
        return SubagentResult(
            status=SubagentStatus.ERROR,
            error_message="Search subagent processing error",
        )


async def parallel_dispatch_node_impl(
    state: AgentState,
    *,
    subagent_adapters: dict[str, Callable[..., Any]],
    subagent_types: dict[str, str],
) -> AgentState:
    """Dispatch query to multiple subagents in parallel and collect reports."""
    from app.engine.multi_agent.subagents.config import SubagentConfig
    from app.engine.multi_agent.subagents.executor import execute_parallel_subagents
    from app.engine.multi_agent.subagents.report import build_report

    targets = _normalize_parallel_targets(
        state.get("_parallel_targets"),
        subagent_adapters=subagent_adapters,
    )

    logger.info("[PARALLEL_DISPATCH] Dispatching to: %s", targets)

    _push_bus_event(
        state,
        {
            "type": "status",
            "content": f"Triển khai song song: {', '.join(targets)}",
            "node": "parallel_dispatch",
        },
    )

    timeout = 60
    try:
        from app.core.config import settings as _settings

        timeout = _settings.subagent_default_timeout
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[PARALLEL_DISPATCH] Could not read subagent_default_timeout: %s", exc)

    tasks = []
    for name in targets:
        adapter = subagent_adapters[name]
        config = SubagentConfig(name=name, timeout_seconds=timeout)
        tasks.append((adapter, config, _project_state_for_subagent(dict(state)), {}))

    if not tasks:
        logger.warning("[PARALLEL_DISPATCH] No valid targets, skipping")
        state["subagent_reports"] = []
        return state

    max_concurrent = 5
    try:
        from app.core.config import settings as _settings

        max_concurrent = _settings.subagent_max_parallel
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[PARALLEL_DISPATCH] Could not read subagent_max_parallel: %s", exc)

    results = await execute_parallel_subagents(tasks, max_concurrent=max_concurrent)

    reports = []
    for name, result in zip(targets, results):
        agent_type = subagent_types.get(name, "general")
        report = build_report(name, agent_type, result)
        reports.append(report.model_dump())

    state["subagent_reports"] = reports
    logger.info(
        "[PARALLEL_DISPATCH] Collected %d reports: %s",
        len(reports),
        [(r.get("agent_name"), r.get("verdict")) for r in reports],
    )

    state["_trace_id"] = state.get("_trace_id")
    return state
