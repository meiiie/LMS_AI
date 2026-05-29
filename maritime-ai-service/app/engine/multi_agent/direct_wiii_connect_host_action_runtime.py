"""Wiii Connect host-action preflight helpers for direct turns."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.direct_prompt_tool_binding import _tool_name
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.wiii_connect_intent import (
    build_wiii_connect_facebook_post_unavailable_answer,
    looks_wiii_connect_facebook_post_request,
)
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL,
)


def find_wiii_connect_facebook_post_preview_tool(tools: list[Any]) -> Any | None:
    """Find the generated host action tool for Facebook post preview."""

    for tool in tools:
        if _tool_name(tool) == WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL:
            return tool
    return None


def find_wiii_connect_facebook_post_direct_apply_tool(tools: list[Any]) -> Any | None:
    """Find the generated host action tool for direct Facebook publish."""

    for tool in tools:
        if _tool_name(tool) == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL:
            return tool
    return None


async def preflight_requested_wiii_connect_facebook_post(
    *,
    query: str,
    state: AgentState,
    native_tool_messages: bool,
    build_assistant_message,
) -> Any | None:
    """Fail closed for unavailable Facebook publish requests.

    When Facebook is available, return ``None`` so the normal forced tool-call
    path can ask the model to draft the action arguments from the typed
    ``direct_apply`` schema. This mirrors OpenHuman's Composio flow: policy
    selects the action boundary, but the model authors the provider payload.
    """

    if not looks_wiii_connect_facebook_post_request(query):
        return None

    unavailable_answer = build_wiii_connect_facebook_post_unavailable_answer(state)
    if unavailable_answer:
        return build_assistant_message(
            unavailable_answer,
            native_tool_messages=native_tool_messages,
        )

    return None
