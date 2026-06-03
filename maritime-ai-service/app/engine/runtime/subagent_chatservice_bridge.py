"""SubagentRunner ↔ ChatService bridge.

Phase 15 of the runtime migration epic (issue #207). Phase 12 shipped
the isolation harness (``SubagentRunner``) but left ``runner_callable``
unbound — production parents that called ``run(task)`` got an
``error / "no runner_callable"`` result. This module fills that gap by
binding the existing battle-tested ``ChatService`` as the default runner.

Wire shape (intentionally minimal):

    SubagentTask(description="...", parent_session_id="p1") →
        chatservice_runner(task, child_session_id) →
            ChatRequest(message=task.description, session_id=child_session_id, ...) →
            ChatService.process_message(...) → InternalChatResponse →
        SubagentResult(status="success", summary=..., sources=..., tool_calls_made=...)

The bridge does NOT replay the parent's history — by design. The whole
point of subagent isolation is a clean child window scoped to the task
description + any explicit ``context_hints``. A parent that wants the
child to know more must encode it in ``description`` or ``context_hints``.

Failure modes:
- ChatService raises → SubagentRunner.run catches it and emits a
  ``subagent_completed`` event with ``status="error"``. We do NOT swallow
  exceptions here — let the runner's own error path own the protocol.
- Returned response is missing fields → fall back to safe defaults (empty
  summary, zero counts) rather than crashing.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.engine.runtime.subagent_runner import (
    SubagentResult,
    SubagentRunner,
    SubagentTask,
    get_subagent_runner,
)

logger = logging.getLogger(__name__)

_MAX_CONTEXT_HINTS = 12
_MAX_CONTEXT_HINT_VALUE_CHARS = 480
_MAX_SOURCES = 16
_MAX_SOURCE_TEXT_CHARS = 240
_SAFE_SOURCE_KEYS = {
    "id",
    "node_id",
    "source_id",
    "title",
    "source",
    "source_type",
    "content_type",
    "page",
    "page_number",
    "document_id",
    "image_url",
    "url",
    "relevance_score",
    "score",
    "bounding_boxes",
}


def _compact_public_value(value: Any, *, max_chars: int) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = redact_runtime_secret_text(" ".join(text.split()))
    if len(text) > max_chars:
        return text[: max_chars - 1] + "..."
    return text


def _safe_context_hints(context_hints: dict) -> dict[str, str]:
    safe_hints = sanitize_runtime_payload(context_hints)
    if not isinstance(safe_hints, dict):
        return {}
    rendered: dict[str, str] = {}
    for raw_key, raw_value in list(safe_hints.items())[:_MAX_CONTEXT_HINTS]:
        key = redact_runtime_secret_text(str(raw_key)).strip()
        if not key:
            continue
        value = _compact_public_value(
            raw_value,
            max_chars=_MAX_CONTEXT_HINT_VALUE_CHARS,
        )
        if value:
            rendered[key] = value
    return rendered


def _format_description(task: SubagentTask) -> str:
    """Materialise the child's user-message body.

    Description is the primary signal. ``context_hints`` ride as a
    structured suffix so the LLM can see them without losing them in
    free-form prose.
    """
    lines = [task.description.strip()]
    context_hints = _safe_context_hints(task.context_hints)
    if context_hints:
        lines.append("")
        lines.append("Context hints (do not echo verbatim):")
        for key, value in context_hints.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _count_tool_calls(internal_response) -> int:
    """Extract the tool-call count from whichever metadata shape is present."""
    metadata = getattr(internal_response, "metadata", None) or {}
    tools_used = metadata.get("tools_used")
    if isinstance(tools_used, list):
        return len(tools_used)
    raw = metadata.get("tool_calls")
    if isinstance(raw, list):
        return len(raw)
    return 0


def _coerce_sources(internal_response) -> list[dict]:
    """Return citation dicts; fall back to ``[]`` on any shape mismatch."""
    raw_sources = getattr(internal_response, "sources", None) or []
    if not isinstance(raw_sources, (list, tuple)):
        return []
    sources: list[dict] = []
    for src in raw_sources[:_MAX_SOURCES]:
        raw: dict | None = None
        if hasattr(src, "model_dump"):
            try:
                raw = src.model_dump()
            except Exception:  # noqa: BLE001
                pass
        elif isinstance(src, dict):
            raw = src
        if not isinstance(raw, dict):
            continue
        safe_source = sanitize_runtime_payload(raw)
        if not isinstance(safe_source, dict):
            continue
        citation = {
            str(key): _sanitize_source_value(value)
            for key, value in safe_source.items()
            if key in _SAFE_SOURCE_KEYS and value not in (None, "", [], {})
        }
        if citation:
            sources.append(citation)
    return sources


def _sanitize_source_value(value: Any) -> Any:
    if isinstance(value, str):
        return _compact_public_value(value, max_chars=_MAX_SOURCE_TEXT_CHARS)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return value[:8]
    if isinstance(value, dict):
        return {
            str(key): item
            for key, item in list(value.items())[:16]
            if isinstance(item, (str, bool, int, float)) or item is None
        }
    return _compact_public_value(value, max_chars=_MAX_SOURCE_TEXT_CHARS)


async def chatservice_subagent_runner(
    task: SubagentTask, child_session_id: str
) -> SubagentResult:
    """Default runner_callable: run a child agent through ChatService.

    Imports happen inside the function so this module's import is free of
    runtime side effects — call sites can register the bridge without
    pulling ChatService into module-load.
    """
    from app.models.schemas import ChatRequest, UserRole
    from app.services.chat_service import get_chat_service

    request = ChatRequest(
        user_id=f"subagent::{task.parent_session_id}",
        message=_format_description(task),
        role=UserRole.STUDENT,
        session_id=child_session_id,
        organization_id=task.parent_org_id,
    )

    response = await get_chat_service().process_message(request)
    summary = getattr(response, "message", "") or ""
    return SubagentResult(
        status="success",
        summary=summary,
        sources=_coerce_sources(response),
        tool_calls_made=_count_tool_calls(response),
        child_session_id=child_session_id,
        raw_output=summary,
    )


def wire_default_subagent_runner(
    runner: Optional[SubagentRunner] = None,
) -> SubagentRunner:
    """Bind ``chatservice_subagent_runner`` as the default callable.

    Idempotent: re-calling overwrites the binding. Tests should NOT call
    this — they construct ``SubagentRunner(runner_callable=fake)``
    directly. Production startup (or the first parent that calls
    ``get_subagent_runner()``) is the right place to wire the default.
    """
    target = runner or get_subagent_runner()
    if target._runner is None:  # noqa: SLF001 — explicit DI seam
        target._runner = chatservice_subagent_runner
    return target


__all__ = [
    "chatservice_subagent_runner",
    "wire_default_subagent_runner",
]
