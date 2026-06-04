"""Document preview host-action rebinding helpers for direct turns."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.document_preview_contract import (
    as_plain_mapping as _as_plain_direct_mapping,
    document_preview_forced_tool_choice as _document_preview_forced_tool_choice,
    extract_document_preview_capabilities as _extract_document_preview_capabilities,
    filter_lms_authoring_capability_tools as _filter_lms_authoring_capability_tools,
    has_document_preview_host_action_tool as _has_document_preview_host_action_tool,
)

logger = logging.getLogger(__name__)


def _direct_role_candidates(state: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    state_context = state.get("context") if isinstance(state.get("context"), dict) else {}
    host_context = _as_plain_direct_mapping(
        ctx.get("host_context")
        or (state_context.get("host_context") if isinstance(state_context, dict) else None)
        or state.get("host_context")
    )
    candidates = [
        ctx.get("user_role"),
        state_context.get("user_role") if isinstance(state_context, dict) else None,
        state.get("user_role"),
        state.get("role"),
        host_context.get("user_role"),
        host_context.get("host_role"),
    ]
    roles: list[str] = []
    for candidate in candidates:
        value = getattr(candidate, "value", candidate)
        role = str(value or "").strip().lower()
        if role and role not in roles:
            roles.append(role)
    return roles


def _rebind_document_preview_host_action_tool(
    *,
    tools: list[Any],
    force_tools: bool,
    query: str,
    state: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[list[Any], bool, dict[str, Any]]:
    """Bind only the declared, non-mutating LMS preview action if collection lost it."""

    if _has_document_preview_host_action_tool(tools):
        return tools, True, {
            "status": "already_bound",
            "tool_count": len(tools),
        }

    preview_capabilities = _filter_lms_authoring_capability_tools(
        _extract_document_preview_capabilities(state, ctx),
        state=state,
        ctx=ctx,
    )
    debug: dict[str, Any] = {
        "status": "missing_capability",
        "tool_count": len(tools),
        "preview_capability_count": len(preview_capabilities),
    }
    if not preview_capabilities:
        return tools, force_tools, debug

    roles = _direct_role_candidates(state, ctx)
    debug["role_candidates"] = roles[:4]
    for role in roles or ["student"]:
        try:
            from app.engine.context.action_tools import generate_host_action_tools

            generated = generate_host_action_tools(
                preview_capabilities,
                role,
                event_bus_id=state.get("_event_bus_id") or state.get("session_id") or "",
                approval_context={
                    "query": query,
                    "host_action_feedback": (
                        state.get("_host_action_control_feedback")
                        or ctx.get("host_action_feedback")
                        or {}
                    ),
                },
            )
        except Exception as exc:
            debug.update({"status": "generation_failed", "error": type(exc).__name__})
            logger.debug("[DIRECT] Document preview host action rebind failed: %s", exc)
            return tools, force_tools, debug

        wanted_tool = _document_preview_forced_tool_choice(query, generated)
        preview_tools = [
            tool
            for tool in generated
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "")).strip().lower()
            == wanted_tool
        ]
        if preview_tools:
            debug.update(
                {
                    "status": "rebound",
                    "role": role,
                    "tool_count": len(preview_tools),
                }
            )
            logger.info(
                "[DIRECT] Rebound LMS document preview host action from runtime capabilities"
            )
            return preview_tools[:1], True, debug

    debug["status"] = "role_filtered"
    return tools, force_tools, debug
