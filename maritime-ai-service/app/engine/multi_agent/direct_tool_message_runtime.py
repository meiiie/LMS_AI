"""Message builders for direct tool-round execution."""

from __future__ import annotations

from typing import Any


def build_tool_result_message(
    content: str,
    *,
    tool_call_id: str,
    native_tool_messages: bool,
) -> Any:
    """Create the post-tool message without depending on LangChain."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_tool_message

        return make_tool_message(content, tool_call_id=tool_call_id)

    from app.engine.messages import Message

    return Message(role="tool", content=content, tool_call_id=tool_call_id)


def build_user_instruction_message(
    content: str,
    *,
    native_tool_messages: bool,
) -> Any:
    """Create a user instruction message for final synthesis."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_user_message

        return make_user_message(content)

    from app.engine.messages import Message

    return Message(role="user", content=content)


def build_system_instruction_message(
    content: str,
    *,
    native_tool_messages: bool,
) -> Any:
    """Create a system instruction message for runtime-only guardrails."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_system_message

        return make_system_message(content)

    from app.engine.messages import Message

    return Message(role="system", content=content)


def build_assistant_message(
    content: str,
    *,
    native_tool_messages: bool,
) -> Any:
    """Create an assistant message for direct tool-round control flow."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_assistant_message

        return make_assistant_message(content)

    from app.engine.messages import Message

    return Message(role="assistant", content=content)


def build_assistant_tool_call_message(
    tool_calls: list[dict[str, Any]],
    *,
    native_tool_messages: bool,
) -> Any:
    """Create an assistant message containing normalized tool calls."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_assistant_message

        return make_assistant_message("", tool_calls=tool_calls)

    from app.engine.messages import Message, ToolCall

    return Message(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(
                id=str(call.get("id") or f"raw_tool_call_{index}"),
                name=str(call.get("name") or ""),
                arguments=dict(call.get("args") or call.get("arguments") or {}),
            )
            for index, call in enumerate(tool_calls)
            if str(call.get("name") or "").strip()
        ],
    )
