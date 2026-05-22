"""Final state contract for the direct response node."""

from __future__ import annotations

from typing import Any, Callable

from app.engine.multi_agent.state import AgentState


def finalize_direct_node_state(
    *,
    state: AgentState,
    response: str,
    domain_name_vi: str,
    resolve_public_thinking_content: Callable[..., str],
    record_thinking_snapshot_fn: Callable[..., Any],
    enable_org_knowledge: bool,
    get_current_org_id_fn: Callable[[], str | None],
) -> AgentState:
    """Apply final response, thinking snapshot, and domain notice state."""

    resolved_direct_thinking = resolve_public_thinking_content(
        state,
        fallback="",
    )
    if resolved_direct_thinking:
        state["thinking_content"] = resolved_direct_thinking
        record_thinking_snapshot_fn(
            state,
            resolved_direct_thinking,
            node="direct",
            provenance=(
                "final_snapshot"
                if resolved_direct_thinking == str(state.get("thinking") or "").strip()
                else "aligned_cleanup"
            ),
        )

    state["final_response"] = response
    state["agent_outputs"] = {"direct": response}
    state["current_agent"] = "direct"

    routing_meta = state.get("routing_metadata", {})
    intent = routing_meta.get("intent", "") if routing_meta else ""
    if intent == "general":
        suppress = enable_org_knowledge and bool(get_current_org_id_fn())
        if not suppress:
            state["domain_notice"] = (
                f"Noi dung nay nam ngoai chuyen mon {domain_name_vi}. "
                f"De duoc ho tro chinh xac hon, hay hoi ve {domain_name_vi} nhe!"
            )

    return state
