"""Adapter: Anthropic Messages API request → ``TurnRequest``.

Phase 4 of the runtime migration epic (issue #207), shipped after the
OpenAI compat adapter to keep the lane-first surface consistent across
all three edge protocols.

Anthropic's wire shape is content-block-typed (``text`` blocks +
``tool_use`` blocks + ``tool_result`` blocks) rather than the OpenAI flat
``role`` + ``content`` + ``tool_calls`` shape. This adapter normalises
those typed blocks into a single ``Message`` per turn, with tool calls
flattened back into the canonical ``ToolCall`` list.

Pure conversion function — dict in, ``TurnRequest`` out. Identity is
supplied out-of-band (auth header / X-User-ID), not from the request.
"""

from __future__ import annotations

from typing import Any, Optional

from app.engine.messages import Message, ToolCall
from app.engine.runtime.adapters.message_summary import summarize_provider_messages
from app.engine.runtime.turn_request import TurnRequest

_VALID_ROLES = {"user", "assistant"}


def _join_text(blocks: list[Any]) -> str:
    """Concatenate text content from a list of typed Anthropic content blocks."""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _collect_tool_uses(blocks: list[Any]) -> Optional[list[ToolCall]]:
    """Pull ``tool_use`` blocks from an assistant message's content list."""
    calls: list[ToolCall] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        calls.append(
            ToolCall(
                id=block.get("id") or "",
                name=block.get("name") or "",
                arguments=block.get("input") or {},
            )
        )
    return calls or None


def _split_tool_results(blocks: list[Any]) -> list[Message]:
    """Anthropic encodes tool results as a ``user`` message with one or more
    ``tool_result`` content blocks. Wiii's canonical ``Message`` puts each
    tool result on its own row with role ``tool`` so downstream code does
    not need to deconstruct typed blocks again.
    """
    out: list[Message] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        # Anthropic tool_result content can be a string or another typed
        # block list — flatten to text.
        result_content = block.get("content")
        if isinstance(result_content, list):
            text = _join_text(result_content)
        elif isinstance(result_content, str):
            text = result_content
        else:
            text = "" if result_content is None else str(result_content)
        out.append(
            Message(
                role="tool",
                content=text,
                tool_call_id=block.get("tool_use_id") or "",
            )
        )
    return out


def _normalise_message(raw: dict) -> list[Message]:
    """One Anthropic message → one or more native Messages.

    Most messages map 1:1, but a ``user`` message that carries
    ``tool_result`` blocks expands into one ``tool`` Message per result.
    """
    role = raw.get("role")
    if role not in _VALID_ROLES:
        role = "user"

    content = raw.get("content")
    # Plain-string body is allowed.
    if isinstance(content, str):
        return [Message(role=role, content=content)]
    if not isinstance(content, list):
        return [Message(role=role, content="")]

    if role == "assistant":
        return [
            Message(
                role="assistant",
                content=_join_text(content),
                tool_calls=_collect_tool_uses(content),
            )
        ]

    # role == "user"
    tool_messages = _split_tool_results(content)
    text = _join_text(content)
    msgs: list[Message] = []
    if text:
        msgs.append(Message(role="user", content=text))
    msgs.extend(tool_messages)
    if not msgs:
        msgs.append(Message(role="user", content=""))
    return msgs


def _has_image_block(raw_messages: list[dict]) -> bool:
    for raw in raw_messages:
        content = raw.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image":
                return True
    return False


def anthropic_messages_to_turn_request(
    body: dict,
    *,
    user_id: str,
    session_id: str,
    org_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    role: str = "student",
) -> TurnRequest:
    """Convert an Anthropic ``POST /v1/messages`` body into a ``TurnRequest``.

    Recognised body fields: ``model``, ``messages``, ``system``,
    ``tools``, ``stream``, ``temperature``, ``top_p``, ``max_tokens``,
    ``tool_choice``. Unknown fields ride in ``metadata`` for observability.
    """
    raw_messages = body.get("messages") or []

    messages: list[Message] = []
    system_prompt = body.get("system")
    if isinstance(system_prompt, str) and system_prompt:
        messages.append(Message(role="system", content=system_prompt))
    elif isinstance(system_prompt, list):
        joined = _join_text(system_prompt)
        if joined:
            messages.append(Message(role="system", content=joined))

    for raw in raw_messages:
        if isinstance(raw, dict):
            messages.extend(_normalise_message(raw))

    requested_capabilities: list[str] = []
    if body.get("tools"):
        requested_capabilities.append("tools")
    if _has_image_block(raw_messages):
        requested_capabilities.append("vision")

    metadata: dict[str, Any] = {
        "anthropic_model": body.get("model"),
        "original_messages_summary": summarize_provider_messages(raw_messages),
    }
    for opt_key in ("temperature", "top_p", "max_tokens", "tool_choice"):
        if opt_key in body:
            metadata[opt_key] = body[opt_key]

    return TurnRequest(
        messages=messages,
        user_id=user_id,
        session_id=session_id,
        org_id=org_id,
        domain_id=domain_id,
        role=role,
        requested_streaming=bool(body.get("stream", False)),
        requested_capabilities=requested_capabilities,
        metadata=metadata,
    )


__all__ = ["anthropic_messages_to_turn_request"]
