"""Uploaded-document preflight helpers for the direct node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.engine.multi_agent.direct_node_document_preview_rebind import (
    _rebind_document_preview_host_action_tool,
)
from app.engine.multi_agent.direct_node_document_preview_runtime import (
    execute_direct_node_document_preview_round,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.state import AgentState


@dataclass(frozen=True)
class DirectDocumentPreviewPreflightResult:
    response: str
    response_type: str = "document_preview_host_action"


def build_document_preview_response_sanitizer(
    *,
    query: str,
    sanitize_structured_visual_answer_text: Callable[..., str],
    sanitize_wiii_house_text: Callable[..., str],
    strip_direct_inline_private_asides: Callable[[str], str],
    strip_dsml_residue: Callable[[str], str],
) -> Callable[[str, list[dict[str, Any]]], str]:
    def sanitize_document_preview_response(
        preview_response: str,
        preview_tool_call_events: list[dict[str, Any]],
    ) -> str:
        preview_response = sanitize_structured_visual_answer_text(
            preview_response,
            tool_call_events=preview_tool_call_events,
        )
        preview_response = sanitize_wiii_house_text(preview_response, query=query)
        preview_response = strip_direct_inline_private_asides(preview_response)
        return strip_dsml_residue(preview_response).strip()

    return sanitize_document_preview_response


def record_uploaded_document_context_plan(
    *,
    state: AgentState,
    response_present: bool,
    has_uploaded_document_context: bool,
    document_thinking: str,
    record_thinking_snapshot_fn,
) -> None:
    if (
        response_present
        or not has_uploaded_document_context
        or str(state.get("thinking_content") or "").strip()
    ):
        return
    record_direct_node_thinking_snapshot(
        state=state,
        thinking=document_thinking,
        provenance="document_context_plan",
        record_thinking_snapshot_fn=record_thinking_snapshot_fn,
    )


async def execute_direct_node_document_preview_preflight(
    *,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    bus_id: str | None,
    response_present: bool,
    has_uploaded_document_context: bool,
    looks_uploaded_document_preview_request: Callable[[str], bool],
    push_event,
    build_visual_tool_runtime_metadata,
    execute_direct_tool_rounds,
    extract_direct_response,
    sanitize_preview_response,
    fallback_response: str,
    logger_obj,
) -> DirectDocumentPreviewPreflightResult | None:
    if (
        response_present
        or not has_uploaded_document_context
        or not looks_uploaded_document_preview_request(query)
    ):
        return None

    routing_meta = state.get("routing_metadata")
    if not isinstance(routing_meta, dict):
        routing_meta = {}
        state["routing_metadata"] = routing_meta
    preview_tools, preview_force_tools, doc_preview_debug = (
        _rebind_document_preview_host_action_tool(
            tools=[],
            force_tools=False,
            query=query,
            state=state,
            ctx=ctx,
        )
    )
    routing_meta["doc_preview_preflight"] = doc_preview_debug
    preview_result = await execute_direct_node_document_preview_round(
        query=query,
        state=state,
        ctx=ctx,
        bus_id=bus_id,
        tools=preview_tools,
        force_tools=preview_force_tools,
        messages=[],
        push_event=push_event,
        build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
        execute_direct_tool_rounds=execute_direct_tool_rounds,
        extract_direct_response=extract_direct_response,
        sanitize_preview_response=sanitize_preview_response,
        fallback_response=fallback_response,
        debug=doc_preview_debug,
        routing_metadata_key="doc_preview_preflight",
        success_status="executed",
        failure_status="execution_failed",
        failure_log_message="[DIRECT] Early document preview host action failed: %s",
        logger_obj=logger_obj,
    )
    if preview_result is None:
        return None

    logger_obj.info("[DIRECT] Executed LMS document preview host action before planner LLM")
    return DirectDocumentPreviewPreflightResult(response=preview_result.response)
