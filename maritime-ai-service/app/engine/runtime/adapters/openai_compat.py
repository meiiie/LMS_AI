"""Adapter: OpenAI Chat Completions request → ``TurnRequest``.

Phase 4 of the runtime migration epic (issue #207). Lets external
clients (or local SDKs) hit Wiii with a vanilla OpenAI-shape body —
``{"model": ..., "messages": [...], "tools": [...], "stream": bool}`` —
without rewriting the internal pipeline.

The adapter is pure: dict in, ``TurnRequest`` out. Identity is supplied
out-of-band (auth header / X-User-ID), not from the request body.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.engine.messages import Message, ToolCall
from app.engine.runtime.adapters.message_summary import summarize_provider_messages
from app.engine.runtime.turn_request import TurnRequest

_VALID_ROLES = {"system", "user", "assistant", "tool"}


def _coerce_content(raw: Any) -> str:
    """Reduce OpenAI's content (str / list of blocks) to a string.

    Multimodal content arrays are flattened to their text portions. A
    compact, privacy-safe structure summary rides in metadata for
    observability; raw provider messages do not.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(raw)


def _parse_tool_calls(raw: Any) -> Optional[list[ToolCall]]:
    if not raw:
        return None
    parsed: list[ToolCall] = []
    for tc in raw:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments")
        try:
            args = json.loads(args_raw) if args_raw else {}
        except (json.JSONDecodeError, TypeError):
            args = {}
        parsed.append(
            ToolCall(
                id=tc.get("id") or "",
                name=fn.get("name") or "",
                arguments=args if isinstance(args, dict) else {},
            )
        )
    return parsed or None


def _normalise_message(raw: dict) -> Message:
    role = raw.get("role")
    if role not in _VALID_ROLES:
        role = "user"
    return Message(
        role=role,
        content=_coerce_content(raw.get("content")),
        name=raw.get("name"),
        tool_call_id=raw.get("tool_call_id"),
        tool_calls=_parse_tool_calls(raw.get("tool_calls")),
    )


def _has_image_content(raw_messages: list[dict]) -> bool:
    for msg in raw_messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in {
                    "image_url",
                    "input_image",
                    "image",
                }:
                    return True
    return False


def openai_chat_completions_to_turn_request(
    body: dict,
    *,
    user_id: str,
    session_id: str,
    org_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    role: str = "student",
) -> TurnRequest:
    """Convert an OpenAI Chat Completions request body into a ``TurnRequest``."""
    raw_messages = body.get("messages") or []
    messages = [_normalise_message(m) for m in raw_messages if isinstance(m, dict)]

    requested_capabilities: list[str] = []
    if body.get("tools"):
        requested_capabilities.append("tools")
    if body.get("response_format", {}).get("type") in {"json_object", "json_schema"}:
        requested_capabilities.append("structured_output")
    if _has_image_content(raw_messages):
        requested_capabilities.append("vision")

    metadata: dict[str, Any] = {
        "openai_model": body.get("model"),
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


__all__ = ["openai_chat_completions_to_turn_request"]
