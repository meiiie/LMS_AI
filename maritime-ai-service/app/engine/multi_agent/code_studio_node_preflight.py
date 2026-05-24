"""Typed preflight lifecycle for the Code Studio node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.state import AgentState


@dataclass(frozen=True, slots=True)
class CodeStudioNodePreflightRequest:
    """Per-turn state available before Code Studio binds tools or calls a provider."""

    query: str
    state: AgentState
    default_domain: str
    push_event: Callable[[dict[str, Any]], Awaitable[None]]
    tracer: Any


@dataclass(frozen=True, slots=True)
class CodeStudioNodePreflightDependencies:
    """Injected contracts used to resolve Code Studio preflight behavior."""

    looks_like_ambiguous_simulation_request: Callable[[str, AgentState], bool]
    ground_simulation_query_from_visual_context: Callable[[str, AgentState], str]
    last_inline_visual_title: Callable[[AgentState], str]
    build_ambiguous_simulation_clarifier: Callable[[AgentState], str]


@dataclass(frozen=True, slots=True)
class CodeStudioNodePreflightResult:
    """Resolved pre-provider state for a Code Studio turn."""

    effective_query: str
    response: str
    domain_name_vi: str

    @property
    def has_response(self) -> bool:
        return bool(self.response)


def resolve_code_studio_domain_name_vi(
    *,
    state: AgentState,
    default_domain: str,
) -> str:
    """Resolve the Vietnamese domain label without leaking graph details."""

    domain_config = state.get("domain_config", {})
    domain_name_vi = (
        domain_config.get("name_vi", "") if isinstance(domain_config, dict) else ""
    )
    if domain_name_vi:
        return str(domain_name_vi)

    domain_id = state.get("domain_id", default_domain)
    return {
        "maritime": "Hang hai",
        "traffic_law": "Luat Giao thong",
    }.get(domain_id, str(domain_id))


async def execute_code_studio_node_preflight(
    *,
    request: CodeStudioNodePreflightRequest,
    dependencies: CodeStudioNodePreflightDependencies,
) -> CodeStudioNodePreflightResult:
    """Resolve deterministic Code Studio preflight before tool/provider execution."""

    query = request.query
    state = request.state
    effective_query = query
    response = ""
    domain_name_vi = resolve_code_studio_domain_name_vi(
        state=state,
        default_domain=request.default_domain,
    )

    if dependencies.looks_like_ambiguous_simulation_request(query, state):
        grounded_query = dependencies.ground_simulation_query_from_visual_context(
            query,
            state,
        )
        if grounded_query:
            effective_query = grounded_query
            state["thinking_content"] = (
                "Mình đang bám theo visual hiện tại để tiếp tục mô phỏng, "
                "vì turn này tuy ngắn nhưng đã có đủ ngữ cảnh để không cần hỏi lại."
            )
            await request.push_event({
                "type": "status",
                "content": (
                    "Mình đang nối mô phỏng vào chủ đề hiện tại: "
                    f"`{dependencies.last_inline_visual_title(state)}`..."
                ),
                "step": "code_generation",
                "node": "code_studio_agent",
                "details": {"visibility": "status_only"},
            })
        else:
            response = dependencies.build_ambiguous_simulation_clarifier(state)
            state["thinking_content"] = (
                "Mình cần chốt rõ chủ đề mô phỏng trước khi mở canvas, "
                "để khỏi dựng sai hiện tượng hoặc tạo một app lệch mục tiêu."
            )
            request.tracer.end_step(
                result="Code studio clarification before build",
                confidence=0.9,
                details={
                    "response_type": "clarify",
                    "reason": "ambiguous_simulation_request",
                },
            )

    return CodeStudioNodePreflightResult(
        effective_query=effective_query,
        response=response,
        domain_name_vi=domain_name_vi,
    )
