"""Typed tool setup contract for the Code Studio node."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_policy_session import (
    build_visible_tool_policy_session,
    record_tool_policy_session,
)
from app.engine.skills.skill_recommender import select_runtime_tools


@dataclass(frozen=True, slots=True)
class CodeStudioToolSetupResult:
    """Resolved Code Studio tools and runtime context for one turn."""

    tools: list[Any]
    force_tools: bool
    runtime_context_base: Any


CollectCodeStudioTools = Callable[[str, str], tuple[list[Any], bool]]
RequiredToolNames = Callable[[str, str], list[str]]
BuildToolRuntimeContext = Callable[..., Any]
BuildVisualToolRuntimeMetadata = Callable[[AgentState, str], dict[str, Any]]
RuntimeToolSelector = Callable[..., list[Any] | None]


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def prepare_code_studio_tool_setup(
    *,
    effective_query: str,
    state: AgentState,
    ctx: dict[str, Any],
    bus_id: str | None,
    collect_code_studio_tools: CollectCodeStudioTools,
    code_studio_required_tool_names: RequiredToolNames,
    build_tool_runtime_context_fn: BuildToolRuntimeContext,
    build_visual_tool_runtime_metadata: BuildVisualToolRuntimeMetadata,
    logger_obj: logging.Logger,
    select_runtime_tools_fn: RuntimeToolSelector = select_runtime_tools,
) -> CodeStudioToolSetupResult:
    """Collect, optionally narrow, and bind Code Studio tools for this turn."""

    user_role = str(ctx.get("user_role", "student") or "student")
    tools, force_tools = collect_code_studio_tools(effective_query, user_role)
    candidate_tool_names = [_tool_name(tool) for tool in tools if _tool_name(tool)]

    try:
        selected_tools = select_runtime_tools_fn(
            tools,
            query=effective_query,
            intent=(state.get("routing_metadata") or {}).get("intent"),
            user_role=user_role,
            max_tools=min(len(tools), 8),
            must_include=code_studio_required_tool_names(
                effective_query,
                user_role,
            ),
        )
        if selected_tools:
            tools = selected_tools
            logger_obj.info(
                "[CODE_STUDIO] Runtime-selected tools: %s",
                [
                    getattr(tool, "name", getattr(tool, "__name__", "unknown"))
                    for tool in tools
                ],
            )
    except Exception as selection_error:  # noqa: BLE001
        logger_obj.debug(
            "[CODE_STUDIO] Runtime tool selection skipped: %s",
            selection_error,
        )

    record_tool_policy_session(
        state,
        build_visible_tool_policy_session(
            path="code_studio",
            reason="code_studio_tool_setup",
            state=state,
            query=effective_query,
            candidate_tool_names=candidate_tool_names,
            visible_tool_names=[_tool_name(tool) for tool in tools if _tool_name(tool)],
            force_tools=force_tools,
        ),
    )

    runtime_context_base = build_tool_runtime_context_fn(
        event_bus_id=bus_id,
        request_id=ctx.get("request_id"),
        session_id=state.get("session_id"),
        organization_id=state.get("organization_id"),
        user_id=state.get("user_id"),
        user_role=user_role,
        node="code_studio_agent",
        source="agentic_loop",
        metadata=build_visual_tool_runtime_metadata(state, effective_query),
    )

    return CodeStudioToolSetupResult(
        tools=tools,
        force_tools=force_tools,
        runtime_context_base=runtime_context_base,
    )
