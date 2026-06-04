"""Direct-node tool selection policy."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from app.engine.multi_agent.document_preview_contract import (
    DOC_PREVIEW_HOST_ACTION_TOOL as _DOC_PREVIEW_HOST_ACTION_TOOL,
)
from app.engine.multi_agent.direct_node_document_preview_rebind import (
    _rebind_document_preview_host_action_tool,
)
from app.engine.multi_agent.direct_node_uploaded_context import (
    _looks_uploaded_document_preview_request,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_policy_session import (
    finalize_tool_policy_visible_tools,
    tool_policy_session_from_state,
)
from app.engine.multi_agent.tool_collection import _force_skills_from_state
from app.engine.multi_agent.wiii_connect_intent import (
    looks_wiii_connect_external_app_action_request_for_state,
    looks_wiii_connect_facebook_post_request_for_state,
)


@dataclass(slots=True)
class DirectNodeToolSelection:
    tools: list[Any]
    force_tools: bool


def _turn_path_decision_metadata(state: AgentState) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    metadata = state.get("_turn_path_decision")
    return metadata if isinstance(metadata, dict) else {}


def _turn_path_allows_tool_name(state: AgentState, tool_name: str) -> bool:
    policy_session = tool_policy_session_from_state(state)
    if policy_session is not None:
        return policy_session.should_expose_tool(tool_name)

    decision = _turn_path_decision_metadata(state)
    if not decision:
        return True
    if not bool(decision.get("bind_tools", True)):
        return False

    name = str(tool_name or "").strip()
    if not name:
        return False

    forbidden_names = {
        str(item or "").strip()
        for item in decision.get("forbidden_tool_names", []) or []
        if str(item or "").strip()
    }
    if name in forbidden_names:
        return False

    forbidden_prefixes = tuple(
        str(item or "").strip()
        for item in decision.get("forbidden_tool_prefixes", []) or []
        if str(item or "").strip()
    )
    if any(name.startswith(prefix) for prefix in forbidden_prefixes):
        return False

    if bool(decision.get("allow_all_tools", True)):
        return True

    allowed_names = {
        str(item or "").strip()
        for item in decision.get("allowed_tool_names", []) or []
        if str(item or "").strip()
    }
    if name in allowed_names:
        return True

    allowed_prefixes = tuple(
        str(item or "").strip()
        for item in decision.get("allowed_tool_prefixes", []) or []
        if str(item or "").strip()
    )
    return any(name.startswith(prefix) for prefix in allowed_prefixes)


def select_direct_node_tools(
    *,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    routing_intent: str,
    is_short_house_chatter: bool,
    is_identity_turn: bool,
    is_emotional_support_turn: bool,
    is_codebase_source_turn: bool,
    explicit_web_search_turn: bool,
    has_uploaded_document_context: bool,
    needs_web_search: Callable[[str], bool],
    collect_direct_tools: Callable[..., tuple[list[Any], bool]],
    direct_required_tool_names: Callable[[str, str], list[str]],
    logger_obj: logging.Logger,
) -> DirectNodeToolSelection:
    is_external_app_action = (
        looks_wiii_connect_facebook_post_request_for_state(query, state)
        or looks_wiii_connect_external_app_action_request_for_state(query, state)
    )
    turn_path_decision = _turn_path_decision_metadata(state)
    turn_path_requires_tools = bool(turn_path_decision.get("bind_tools", True)) and bool(
        turn_path_decision.get("force_tools")
    )
    if (
        (is_short_house_chatter or is_identity_turn or is_emotional_support_turn)
        and not is_external_app_action
        and not turn_path_requires_tools
    ):
        return DirectNodeToolSelection(tools=[], force_tools=False)
    if is_codebase_source_turn and not explicit_web_search_turn and not needs_web_search(query):
        return DirectNodeToolSelection(tools=[], force_tools=False)

    user_role = ctx.get("user_role", "student")
    tools, force_tools = collect_direct_tools(query, user_role, state=state)

    # Phase F5 (2026-05-06): explicit @-mention tool binding is a user choice,
    # so required tools must survive recommender pruning and force tool choice.
    force_skills = _force_skills_from_state(state)
    force_required_tools: list[str] = []
    if "wiii-pointy" in force_skills:
        pointy_required = ["tool_pointy_show", "tool_pointy_inventory"]
        force_required_tools.extend(
            tool_name
            for tool_name in pointy_required
            if _turn_path_allows_tool_name(state, tool_name)
        )
    if "web-search" in force_skills:
        if _turn_path_allows_tool_name(state, "tool_web_search"):
            force_required_tools.append("tool_web_search")
    if force_required_tools:
        force_tools = True
        logger_obj.info("[DIRECT] Force-bound via @-mention: required=%s", force_required_tools)

    routing_required_tools: list[str] = []
    if (
        routing_intent == "web_search"
        and "web-search" not in force_skills
        and _turn_path_allows_tool_name(state, "tool_web_search")
    ):
        routing_required_tools.append("tool_web_search")
        force_tools = True
        logger_obj.info(
            "[DIRECT] Required via routing intent: required=%s",
            routing_required_tools,
        )

    try:
        from app.engine.skills.skill_recommender import select_runtime_tools

        must_include_names = direct_required_tool_names(query, user_role)
        if (
            has_uploaded_document_context
            and _looks_uploaded_document_preview_request(query)
            and _DOC_PREVIEW_HOST_ACTION_TOOL not in must_include_names
        ):
            must_include_names.append(_DOC_PREVIEW_HOST_ACTION_TOOL)
        for tool_name in force_required_tools:
            if tool_name not in must_include_names:
                must_include_names.append(tool_name)
        for tool_name in routing_required_tools:
            if tool_name not in must_include_names:
                must_include_names.append(tool_name)

        selected_tools = select_runtime_tools(
            tools,
            query=query,
            intent=(state.get("routing_metadata") or {}).get("intent"),
            user_role=user_role,
            max_tools=min(len(tools), 7),
            must_include=must_include_names,
        )
        if selected_tools:
            tools = selected_tools
            logger_obj.info(
                "[DIRECT] Runtime-selected tools: %s",
                [getattr(tool, "name", getattr(tool, "__name__", "unknown")) for tool in tools],
            )
    except Exception as selection_error:
        logger_obj.debug("[DIRECT] Runtime tool selection skipped: %s", selection_error)

    if has_uploaded_document_context and _looks_uploaded_document_preview_request(query):
        tools, force_tools, doc_preview_debug = _rebind_document_preview_host_action_tool(
            tools=tools,
            force_tools=force_tools,
            query=query,
            state=state,
            ctx=ctx,
        )
        if isinstance(state.get("routing_metadata"), dict):
            state["routing_metadata"]["doc_preview_runtime"] = doc_preview_debug

    if not tools:
        force_tools = False

    finalize_tool_policy_visible_tools(
        state,
        tools,
        tool_name=lambda tool: str(getattr(tool, "name", getattr(tool, "__name__", "")) or ""),
    )

    return DirectNodeToolSelection(tools=tools, force_tools=force_tools)
