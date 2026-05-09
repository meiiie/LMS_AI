"""Single point of truth for ``Message`` → provider dict conversion.

These adapters are the *only* place Wiii encodes provider-specific message
shape. The OpenAI form is also accepted by Gemini and Zhipu via their
OpenAI-compat endpoints; Anthropic uses its own typed-content layout.

Used at LLM-dispatch boundaries:

    >>> from app.engine.messages import Message
    >>> from app.engine.messages_adapters import to_openai_dict
    >>> msgs = [Message(role="system", content="hi"), Message(role="user", content="x")]
    >>> response = await llm.ainvoke([to_openai_dict(m) for m in msgs])
"""

from __future__ import annotations

import json
from typing import Any

from .messages import Message, ToolCall


def to_openai_dict(m: Message) -> dict[str, Any]:
    """OpenAI Chat Completions message format.

    Also used by Gemini (OpenAI-compat endpoint) and Zhipu (GLM).
    """
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    if m.name:
        out["name"] = m.name
    return out


def to_anthropic_dict(m: Message) -> dict[str, Any]:
    """Anthropic Messages API format.

    Anthropic represents tool results as a ``user`` message with a typed
    ``tool_result`` content block. Tool calls flow back as ``assistant``
    messages with ``tool_use`` blocks.
    """
    if m.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content,
                    "is_error": False,
                }
            ],
        }
    if m.tool_calls:
        blocks: list[dict[str, Any]] = []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        for tc in m.tool_calls:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
            )
        return {"role": "assistant", "content": blocks}
    return {"role": m.role, "content": m.content}


def to_gemini_dict(m: Message) -> dict[str, Any]:
    """Gemini via OpenAI-compat endpoint — same shape as OpenAI."""
    return to_openai_dict(m)


# ── Reverse adapters: provider response → Wiii Message ──


def _safe_json_loads(value: Any) -> Any:
    """Permissive JSON parse — returns ``{}`` on empty / invalid input."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_dsml_tool_calls(content: str) -> tuple[str, list[ToolCall]]:
    """Parse DeepSeek-native ``<｜DSML｜tool_calls>...</｜DSML｜tool_calls>`` markup.

    Some NVIDIA NIM models (DeepSeek V4) return tool calls inside ``content``
    as DSML XML instead of populating the structured ``tool_calls`` field.
    OpenAI parser misses these → pipeline sees prose, user gets raw XML.

    Returns ``(content_without_dsml, parsed_tool_calls)``. When no DSML is
    present, returns ``(content, [])`` — caller falls through to standard
    structured-tool_calls path.

    DSML grammar (informal):
        <｜DSML｜tool_calls>
          <｜DSML｜invoke name="<TOOL_NAME>">
            <｜DSML｜parameter name="<KEY>" string="true">VALUE</｜DSML｜parameter>
            ...
          </｜DSML｜invoke>
          ...
        </｜DSML｜tool_calls>

    Note: ``｜`` is U+FF5C (FULLWIDTH VERTICAL LINE), not ASCII ``|``.
    Some models emit the ASCII variant; we accept both.
    """
    if not content or "DSML" not in content:
        return content, []

    import re as _re

    # Block detector — match outer <｜DSML｜tool_calls>...</｜DSML｜tool_calls>
    bar = r"[｜|]"  # accept both fullwidth and ASCII variants
    block_re = _re.compile(
        rf"<{bar}DSML{bar}tool_calls>(.*?)</{bar}DSML{bar}tool_calls>",
        flags=_re.DOTALL,
    )
    invoke_re = _re.compile(
        rf"<{bar}DSML{bar}invoke\s+name=\"([^\"]+)\"\s*>(.*?)</{bar}DSML{bar}invoke>",
        flags=_re.DOTALL,
    )
    param_re = _re.compile(
        rf"<{bar}DSML{bar}parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</{bar}DSML{bar}parameter>",
        flags=_re.DOTALL,
    )

    parsed: list[ToolCall] = []
    cleaned_chunks: list[str] = []
    cursor = 0
    for block_match in block_re.finditer(content):
        cleaned_chunks.append(content[cursor:block_match.start()])
        cursor = block_match.end()

        block_body = block_match.group(1)
        for idx, invoke_match in enumerate(invoke_re.finditer(block_body)):
            tool_name = invoke_match.group(1).strip()
            invoke_body = invoke_match.group(2)
            args: dict[str, Any] = {}
            for param_match in param_re.finditer(invoke_body):
                key = param_match.group(1).strip()
                value = param_match.group(2).strip()
                args[key] = value
            parsed.append(
                ToolCall(
                    id=f"dsml_{idx}_{abs(hash(tool_name)) % 10_000}",
                    name=tool_name,
                    arguments=args,
                )
            )

    cleaned_chunks.append(content[cursor:])
    cleaned = "".join(cleaned_chunks).strip()
    return cleaned, parsed


def from_openai_response(resp_msg: Any) -> Message:
    """Parse an OpenAI ``ChatCompletionMessage`` (or compatible dict) into a Wiii Message.

    Accepts both the SDK object form (``response.choices[0].message``) and a
    raw dict — Gemini/Zhipu OpenAI-compat endpoints return the same shape.

    Phase 35: Also detects DeepSeek-native DSML tool-call markup inside
    ``content`` and converts it to structured ``tool_calls``.
    """
    if isinstance(resp_msg, dict):
        content = resp_msg.get("content") or ""
        raw_tool_calls = resp_msg.get("tool_calls")
    else:
        content = getattr(resp_msg, "content", None) or ""
        raw_tool_calls = getattr(resp_msg, "tool_calls", None)

    # Phase 35 — DSML root cause fix. When NVIDIA NIM (DeepSeek V4) emits
    # tool calls in `content` instead of `tool_calls`, parse them out so the
    # downstream loop dispatches them properly.
    if not raw_tool_calls and content and "DSML" in content:
        cleaned, dsml_calls = _parse_dsml_tool_calls(content)
        if dsml_calls:
            content = cleaned
            return Message(role="assistant", content=content, tool_calls=dsml_calls)

    tool_calls: list[ToolCall] | None = None
    if raw_tool_calls:
        parsed: list[ToolCall] = []
        for tc in raw_tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id", "")
                fn = tc.get("function") or {}
                fn_name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", "")
                fn_args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "")
            else:
                tc_id = getattr(tc, "id", "")
                fn = getattr(tc, "function", None)
                fn_name = getattr(fn, "name", "") if fn is not None else ""
                fn_args = getattr(fn, "arguments", "") if fn is not None else ""
            parsed.append(
                ToolCall(
                    id=tc_id or "",
                    name=fn_name or "",
                    arguments=_safe_json_loads(fn_args),
                )
            )
        tool_calls = parsed or None

    return Message(role="assistant", content=content, tool_calls=tool_calls)


def from_anthropic_response(resp: Any) -> Message:
    """Parse an Anthropic ``Message`` response into a Wiii Message.

    Anthropic returns ``content`` as a list of typed blocks
    (``TextBlock`` / ``ToolUseBlock``); accepts both SDK object form and dict.
    """
    blocks = resp.get("content") if isinstance(resp, dict) else getattr(resp, "content", [])
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in blocks or []:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "text":
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", "")
            if text:
                text_parts.append(text)
        elif block_type == "tool_use":
            tc_id = block.get("id") if isinstance(block, dict) else getattr(block, "id", "")
            name = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
            tc_input = (
                block.get("input")
                if isinstance(block, dict)
                else getattr(block, "input", {})
            )
            tool_calls.append(
                ToolCall(
                    id=tc_id or "",
                    name=name or "",
                    arguments=tc_input if isinstance(tc_input, dict) else {},
                )
            )

    return Message(
        role="assistant",
        content="\n".join(text_parts),
        tool_calls=tool_calls or None,
    )


__all__ = [
    "to_openai_dict",
    "to_anthropic_dict",
    "to_gemini_dict",
    "from_openai_response",
    "from_anthropic_response",
]
