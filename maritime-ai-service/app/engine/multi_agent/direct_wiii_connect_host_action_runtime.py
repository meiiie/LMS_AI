"""Deterministic Wiii Connect host-action shortcuts for direct turns."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.direct_document_host_action_runtime import (
    DocumentHostActionShortcut,
    execute_document_host_action_shortcut,
)
from app.engine.multi_agent.direct_prompt_tool_binding import _tool_name
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.wiii_connect_intent import (
    build_wiii_connect_facebook_post_unavailable_answer,
    facebook_post_message_from_query,
    facebook_post_uses_latest_user_image,
    looks_wiii_connect_facebook_post_request,
)
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL,
)


FACEBOOK_POST_PREVIEW_SHORTCUT = DocumentHostActionShortcut(
    tool_name=WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL,
    tool_call_id="wiii-connect-facebook-post-preview",
    thinking=(
        "Mình nhận đây là yêu cầu ghi ra Facebook qua Wiii Connect. "
        "Vì đây là external app action, mình không để LLM trả lời suông; "
        "mình phát host_action preview trước để frontend lấy đúng connection/page và giữ bước xác nhận trước khi publish."
    ),
    thinking_summary="Chuẩn bị preview Facebook qua Wiii Connect.",
    thinking_provenance="deterministic_wiii_connect_facebook_post_preview",
    response=(
        "Mình đã chuẩn bị bản xem trước bài đăng Facebook. "
        "Kiểm tra nội dung trong khung preview rồi bấm Đăng lên Facebook để xác nhận publish."
    ),
    failure_log_message="[DIRECT] Deterministic Wiii Connect Facebook preview failed: %s",
)


def find_wiii_connect_facebook_post_preview_tool(tools: list[Any]) -> Any | None:
    """Find the generated host action tool for Facebook post preview."""

    for tool in tools:
        if _tool_name(tool) == WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL:
            return tool
    return None


def build_wiii_connect_facebook_post_preview_params(
    query: str,
    state: AgentState | None,
) -> dict[str, Any]:
    """Build host-action params for a Facebook post preview."""

    params: dict[str, Any] = {
        "provider_slug": "facebook",
        "message": facebook_post_message_from_query(query),
    }
    if facebook_post_uses_latest_user_image(state):
        params["image_policy"] = "use_latest_user_image"
    return params


async def execute_requested_wiii_connect_facebook_post_shortcut(
    *,
    query: str,
    state: AgentState,
    tools: list[Any],
    tool_call_events: list[dict[str, Any]],
    push_event,
    native_tool_messages: bool,
    runtime_context_base: Any,
    invoke_tool_with_runtime,
    maybe_emit_host_action_event,
    summarize_tool_result_for_stream,
    build_assistant_message,
    logger_obj: logging.Logger,
) -> Any | None:
    """Execute the deterministic Facebook preview shortcut, if requested."""

    if not looks_wiii_connect_facebook_post_request(query):
        return None

    unavailable_answer = build_wiii_connect_facebook_post_unavailable_answer(state)
    if unavailable_answer:
        return build_assistant_message(
            unavailable_answer,
            native_tool_messages=native_tool_messages,
        )

    tool = find_wiii_connect_facebook_post_preview_tool(tools)
    if tool is None:
        return None

    args = build_wiii_connect_facebook_post_preview_params(query, state)
    response = await execute_document_host_action_shortcut(
        shortcut=FACEBOOK_POST_PREVIEW_SHORTCUT,
        tool=tool,
        args=args,
        state=state,
        tool_call_events=tool_call_events,
        push_event=push_event,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        maybe_emit_host_action_event=maybe_emit_host_action_event,
        summarize_tool_result_for_stream=summarize_tool_result_for_stream,
        runtime_context_base=runtime_context_base,
        query_snippet=str(args.get("message") or "")[:100],
        logger_obj=logger_obj,
    )
    logger_obj.info(
        "[DIRECT] Deterministic Wiii Connect Facebook preview host action requested"
    )
    return build_assistant_message(
        response,
        native_tool_messages=native_tool_messages,
    )
