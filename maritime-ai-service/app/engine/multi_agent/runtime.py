"""Canonical WiiiRunner-backed multi-agent runtime surface."""

from __future__ import annotations

import sys
from typing import Any

from app.engine.multi_agent.runtime_contracts import WiiiTurnRequest, WiiiTurnResult
from app.engine.multi_agent.graph_process import process_with_multi_agent_impl
from app.engine.multi_agent.graph_runtime_bindings import (
    _inject_code_studio_context,
    _inject_document_context,
    _inject_host_context,
    _inject_host_session,
    _inject_living_context,
    _inject_operator_context,
    _inject_visual_cognition_context,
    _inject_visual_context,
    _inject_widget_feedback_context,
    _resolve_public_thinking_content,
)
from app.engine.multi_agent.graph_support import (
    _SUMMARY_MILESTONES,
    _build_domain_config,
    _build_turn_local_state_defaults,
    _generate_session_summary_bg,
)
from app.engine.multi_agent.graph_trace_store import _cleanup_tracer


def _get_legacy_graph_patch() -> Any | None:
    """Return a monkeypatched legacy graph entrypoint without importing graph.py."""
    graph_module = sys.modules.get("app.engine.multi_agent.graph")
    if graph_module is None:
        return None

    legacy_process = getattr(graph_module, "process_with_multi_agent", None)
    if legacy_process is None:
        return None
    if legacy_process is process_with_multi_agent:
        return None

    is_graph_wrapper = (
        getattr(legacy_process, "__module__", "") == "app.engine.multi_agent.graph"
        and getattr(legacy_process, "__name__", "") == "process_with_multi_agent"
    )
    if is_graph_wrapper:
        return None

    return legacy_process


async def process_with_multi_agent(
    query: str,
    user_id: str,
    session_id: str = "",
    context: dict | None = None,
    domain_id: str | None = None,
    thinking_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Process a query through the WiiiRunner-native sync runtime."""
    legacy_patch = _get_legacy_graph_patch()
    if legacy_patch is not None:
        return await legacy_patch(
            query=query,
            user_id=user_id,
            session_id=session_id,
            context=context,
            domain_id=domain_id,
            thinking_effort=thinking_effort,
            provider=provider,
            model=model,
        )

    return await process_with_multi_agent_impl(
        query=query,
        user_id=user_id,
        session_id=session_id,
        context=context,
        domain_id=domain_id,
        thinking_effort=thinking_effort,
        provider=provider,
        model=model,
        build_domain_config=_build_domain_config,
        build_turn_local_state_defaults=_build_turn_local_state_defaults,
        cleanup_tracer=_cleanup_tracer,
        resolve_public_thinking_content=_resolve_public_thinking_content,
        generate_session_summary_bg=_generate_session_summary_bg,
        inject_document_context=_inject_document_context,
        inject_host_context=_inject_host_context,
        inject_host_session=_inject_host_session,
        inject_operator_context=_inject_operator_context,
        inject_living_context=_inject_living_context,
        inject_visual_context=_inject_visual_context,
        inject_visual_cognition_context=_inject_visual_cognition_context,
        inject_widget_feedback_context=_inject_widget_feedback_context,
        inject_code_studio_context=_inject_code_studio_context,
        summary_milestones=_SUMMARY_MILESTONES,
    )


async def run_wiii_turn(request: WiiiTurnRequest) -> WiiiTurnResult:
    """Run one native Wiii turn through the existing WiiiRunner adapter."""

    payload = await process_with_multi_agent(**request.to_runtime_kwargs())
    return WiiiTurnResult.from_payload(payload)


__all__ = ["process_with_multi_agent", "run_wiii_turn"]
