"""Session reconstruction — replay a SessionEventLog into chat state.

Phase 11a of the runtime migration epic (issue #207). The Anthropic
Managed Agents pattern leans on durable session state living *outside* the
context window so a process restart, host failover, or a follow-up turn
hours later can resume cleanly. Phases 5/10c shipped the durable log;
this module is the readback half — given a ``session_id`` it returns a
``WakeState`` ready to feed into the next turn.

Design points:
- **Event-type tolerant.** The log purposefully keeps types as opaque
  strings; ``wake`` recognises the four shapes that carry conversation
  semantics (``user_message``, ``assistant_message``, ``tool_result``,
  ``system_message``) and skips everything else without raising.
- **Pending tool calls surfaced separately.** If an assistant turn ends
  with one or more ``tool_calls`` and the matching ``tool_result`` events
  never arrive, the resumer can decide whether to re-dispatch the call,
  retry the whole turn, or surface a user-facing error.
- **Pure projection.** No side effects. ``wake`` reads, builds, returns —
  callers own decisions about what to do with the state.
- **Org-scoped.** Pass ``org_id`` to filter; the underlying log already
  enforces the boundary so this is a defence-in-depth mirror.

Payload contract (loose, validated defensively):
- ``user_message`` ─ ``{"text": str}`` (legacy ``content`` accepted)
- ``assistant_message`` ─ ``{"text": str, "tool_calls": [ToolCall.dict, ...]}``
- ``tool_result`` ─ ``{"tool_call_id": str, "content": str, "is_error": bool}``
- ``system_message`` ─ ``{"text": str}``

Anything else falls through with a debug log.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.engine.messages import Message, ToolCall
from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload
from app.engine.runtime.session_event_log import (
    SessionEventLog,
    get_session_event_log,
)

logger = logging.getLogger(__name__)

_TEXT_PROVENANCE_KEYS = {"present", "char_count", "hash"}
_TASK_PROVENANCE_KEYS = {
    "version",
    "description",
    "context_hint_count",
    "metadata_keys",
    "max_steps",
}
_RESULT_PROVENANCE_KEYS = {
    "version",
    "status",
    "summary",
    "source_count",
    "tool_calls_made",
    "duration_ms",
    "error",
    "error_type",
}


class WakeState(BaseModel):
    """Conversation state rebuilt from a session's event log."""

    session_id: str
    org_id: Optional[str] = None
    messages: list[Message] = Field(default_factory=list)
    """Reconstructed conversation in append order."""

    pending_tool_calls: list[ToolCall] = Field(default_factory=list)
    """Tool calls from the most recent assistant turn that never received
    a matching ``tool_result`` event. Empty when the session is in a
    clean state ready for the next user turn."""

    latest_seq: int = 0
    """Highest ``seq`` observed during replay. Useful as a ``since_seq``
    cursor for incremental wake calls."""

    event_count: int = 0
    """Number of events visited, including unknown ones."""

    subagent_runs: list[dict] = Field(default_factory=list)
    """Completed child-agent runs reconstructed as compact provenance."""

    pending_subagents: list[dict] = Field(default_factory=list)
    """Started child-agent runs without a matching completion event."""


def _coerce_text(payload: dict) -> str:
    """Extract a text body, accepting legacy aliases."""
    for key in ("text", "content", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _coerce_tool_calls(raw: object) -> list[ToolCall]:
    """Pull a list of ToolCall from a payload field, defensively."""
    if not isinstance(raw, list):
        return []
    parsed: list[ToolCall] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            parsed.append(ToolCall.model_validate(entry))
        except Exception as exc:  # noqa: BLE001 — diagnostic only
            logger.debug("[wake] dropped malformed tool_call: %s", exc)
    return parsed


def _coerce_tool_result_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return ""


def _text_provenance(value: object) -> dict:
    text = str(value or "").strip()
    metadata: dict = {"present": bool(text), "char_count": len(text)}
    if text:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        metadata["hash"] = f"sha256:{digest}"
    return metadata


def _safe_dict(value: object) -> dict:
    safe_value = sanitize_runtime_payload(value)
    return safe_value if isinstance(safe_value, dict) else {}


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_metadata_keys(value: object) -> list[str]:
    return sorted(
        str(key)
        for key in _safe_dict(value).keys()
        if str(key) != "redacted_secret_count"
    )


def _safe_public_mapping(value: object, allowed_keys: set[str]) -> dict:
    return {
        str(key): item
        for key, item in _safe_dict(value).items()
        if str(key) in allowed_keys
    }


def _coerce_text_provenance(value: object) -> dict:
    if isinstance(value, dict):
        safe_value = _safe_public_mapping(value, _TEXT_PROVENANCE_KEYS)
        if safe_value:
            safe_value["present"] = bool(safe_value.get("present"))
            safe_value["char_count"] = _safe_int(safe_value.get("char_count"))
            hash_value = safe_value.get("hash")
            if hash_value is not None:
                safe_value["hash"] = str(hash_value)
            return safe_value
    return _text_provenance(value)


def _coerce_task_provenance(payload: dict) -> dict:
    task = _safe_public_mapping(payload.get("task"), _TASK_PROVENANCE_KEYS)
    if task:
        task["description"] = _coerce_text_provenance(task.get("description"))
        task["context_hint_count"] = _safe_int(task.get("context_hint_count"))
        if "max_steps" in task:
            task["max_steps"] = _safe_int(task.get("max_steps"))
        metadata_keys = task.get("metadata_keys")
        task["metadata_keys"] = (
            [str(key) for key in metadata_keys[:24]]
            if isinstance(metadata_keys, list)
            else []
        )
        return task
    return {
        "version": "wiii.subagent_task_provenance.v1",
        "description": _text_provenance(payload.get("description")),
        "context_hint_count": 0,
        "metadata_keys": _safe_metadata_keys(payload.get("metadata")),
    }


def _coerce_result_provenance(payload: dict) -> dict:
    result = _safe_public_mapping(payload.get("result"), _RESULT_PROVENANCE_KEYS)
    if result:
        result["summary"] = _coerce_text_provenance(result.get("summary"))
        result["error"] = _coerce_text_provenance(result.get("error"))
        result["source_count"] = _safe_int(result.get("source_count"))
        result["tool_calls_made"] = _safe_int(result.get("tool_calls_made"))
        result["duration_ms"] = _safe_int(result.get("duration_ms"))
        if "status" in result:
            result["status"] = str(result.get("status") or "unknown")
        if "error_type" in result:
            result["error_type"] = str(result.get("error_type") or "")
        return result
    return {
        "version": "wiii.subagent_result_provenance.v1",
        "status": str(payload.get("status") or "unknown"),
        "summary": _text_provenance(payload.get("summary")),
        "source_count": 0,
        "tool_calls_made": _safe_int(payload.get("tool_calls_made")),
        "duration_ms": _safe_int(payload.get("duration_ms")),
        "error": _text_provenance(payload.get("error")),
    }


def _apply_subagent_started(
    state: WakeState,
    payload: dict,
    pending_subagents: dict[str, dict],
) -> None:
    child_session_id = payload.get("child_session_id")
    if not isinstance(child_session_id, str) or not child_session_id:
        return
    pending_subagents[child_session_id] = {
        "child_session_id": child_session_id,
        "task": _coerce_task_provenance(payload),
    }


def _apply_subagent_completed(
    state: WakeState,
    payload: dict,
    pending_subagents: dict[str, dict],
) -> None:
    child_session_id = payload.get("child_session_id")
    if not isinstance(child_session_id, str) or not child_session_id:
        return
    started = pending_subagents.pop(child_session_id, {})
    run: dict = {
        "child_session_id": child_session_id,
        "result": _coerce_result_provenance(payload),
    }
    if isinstance(started.get("task"), dict):
        run["task"] = started["task"]
    state.subagent_runs.append(run)


def _apply_user_message(state: WakeState, payload: dict) -> None:
    text = _coerce_text(payload)
    if not text:
        return
    state.messages.append(Message(role="user", content=text))


def _apply_system_message(state: WakeState, payload: dict) -> None:
    text = _coerce_text(payload)
    if not text:
        return
    state.messages.append(Message(role="system", content=text))


def _apply_assistant_message(
    state: WakeState, payload: dict, pending: dict[str, ToolCall]
) -> None:
    text = _coerce_text(payload)
    tool_calls = _coerce_tool_calls(payload.get("tool_calls"))
    if not text and not tool_calls:
        return
    state.messages.append(
        Message(
            role="assistant",
            content=text,
            tool_calls=tool_calls or None,
        )
    )
    # Each tool_call this assistant turn requested is "pending" until a
    # matching tool_result arrives. Replace any earlier pending set —
    # only the most recent assistant turn's calls matter for resumption.
    pending.clear()
    for call in tool_calls:
        if call.id:
            pending[call.id] = call


def _apply_tool_result(
    state: WakeState, payload: dict, pending: dict[str, ToolCall]
) -> None:
    tool_call_id = payload.get("tool_call_id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        return
    text = _coerce_tool_result_text(payload.get("content"))
    state.messages.append(
        Message(
            role="tool",
            content=text,
            tool_call_id=tool_call_id,
        )
    )
    pending.pop(tool_call_id, None)


_HANDLERS = {
    "user_message": _apply_user_message,
    "system_message": _apply_system_message,
}


async def wake(
    *,
    session_id: str,
    org_id: Optional[str] = None,
    since_seq: Optional[int] = None,
    log: Optional[SessionEventLog] = None,
) -> WakeState:
    """Replay events for ``session_id`` into a ``WakeState``.

    ``since_seq`` lets a caller resume from a known cursor (e.g. a worker
    that has already replayed up to seq 42 and only wants newer events).
    ``log`` is injectable for tests; defaults to the configured singleton.
    """
    backend = log or get_session_event_log()
    events = await backend.get_events(
        session_id=session_id, org_id=org_id, since_seq=since_seq
    )

    state = WakeState(session_id=session_id, org_id=org_id)
    pending: dict[str, ToolCall] = {}
    pending_subagents: dict[str, dict] = {}

    for event in events:
        state.event_count += 1
        if event.seq > state.latest_seq:
            state.latest_seq = event.seq

        payload = _safe_dict(event.payload)
        handler = _HANDLERS.get(event.event_type)
        if handler is not None:
            handler(state, payload)
            continue
        if event.event_type == "assistant_message":
            _apply_assistant_message(state, payload, pending)
            continue
        if event.event_type == "tool_result":
            _apply_tool_result(state, payload, pending)
            continue
        if event.event_type == "subagent_started":
            _apply_subagent_started(state, payload, pending_subagents)
            continue
        if event.event_type == "subagent_completed":
            _apply_subagent_completed(state, payload, pending_subagents)
            continue
        # Unknown event type: telemetry, status pings, etc. Ignored on
        # purpose so new event categories don't break wake().
        logger.debug(
            "[wake] skipped event_type=%r seq=%d", event.event_type, event.seq
        )

    state.pending_tool_calls = list(pending.values())
    state.pending_subagents = list(pending_subagents.values())
    return state


__all__ = ["WakeState", "wake"]
