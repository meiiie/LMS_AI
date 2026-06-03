"""Public thinking ownership helpers for multi-agent streaming.

These helpers define what visible thinking fragments are allowed to survive
into the user-facing gray rail and final thinking_content field.
"""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.state import AgentState
from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.engine.reasoning import (
    capture_thinking_lifecycle_event,
    resolve_visible_thinking_from_lifecycle,
    sanitize_visible_reasoning_text,
)


def _normalize_reasoning_text(value: str) -> str:
    return " ".join((value or "").lower().split())


_PUBLIC_THINKING_INTERNAL_MARKERS: tuple[str, ...] = (
    "pipeline",
    "router",
    "reasoning_trace",
    "tool_call_id",
    "request_id",
    "session_id",
    "organization_id",
    "langgraph",
    "iteration=",
)


def _public_reasoning_delta_chunks(beat: Any) -> list[str]:
    chunks: list[str] = []
    for chunk in getattr(beat, "delta_chunks", []) or []:
        if not chunk:
            continue
        clean_chunk = sanitize_visible_reasoning_text(str(chunk)).strip()
        if not clean_chunk:
            continue
        chunk_norm = _normalize_reasoning_text(clean_chunk)
        if any(marker in chunk_norm for marker in _PUBLIC_THINKING_INTERNAL_MARKERS):
            continue
        if chunks and _normalize_reasoning_text(chunks[-1]) == chunk_norm:
            continue
        chunks.append(clean_chunk)
    return chunks


def _code_studio_delta_chunks(beat: Any) -> list[str]:
    return _public_reasoning_delta_chunks(beat)


def _append_public_thinking_fragment(
    state: AgentState,
    content: str,
    *,
    node: str | None = None,
    capture: bool = True,
) -> None:
    clean = sanitize_visible_reasoning_text(
        redact_runtime_secret_text(str(content or ""))
    ).strip()
    if len(clean) < 12:
        return

    normalized = _normalize_reasoning_text(clean)
    if not normalized:
        return
    if any(marker in normalized for marker in _PUBLIC_THINKING_INTERNAL_MARKERS):
        return

    fragments = list(state.get("_public_thinking_fragments") or [])
    if fragments:
        recent_norm = [_normalize_reasoning_text(item) for item in fragments[-4:]]
        if normalized in recent_norm:
            return
    if capture:
        capture_thinking_lifecycle_event(
            state,
            {
                "type": "thinking_delta",
                "content": clean,
                "node": node or state.get("current_agent") or state.get("next_agent") or "unknown",
            },
        )
    fragments.append(clean)
    state["_public_thinking_fragments"] = fragments[-12:]


def _sanitize_public_thinking_event(event: dict[str, Any]) -> dict[str, Any]:
    safe_event = sanitize_runtime_payload(event)
    return safe_event if isinstance(safe_event, dict) else {}


def _capture_public_thinking_event(state: AgentState, event: dict) -> None:
    if not isinstance(event, dict):
        return
    safe_event = _sanitize_public_thinking_event(event)
    if not safe_event:
        return
    capture_thinking_lifecycle_event(state, safe_event)
    if str(safe_event.get("type") or "").strip().lower() != "thinking_delta":
        return
    _append_public_thinking_fragment(
        state,
        str(safe_event.get("content") or ""),
        node=str(safe_event.get("node") or "").strip() or None,
        capture=False,
    )


def _resolve_public_thinking_content(
    state: AgentState,
    *,
    fallback: str = "",
) -> str:
    fragments = [
        sanitize_visible_reasoning_text(str(fragment)).strip()
        for fragment in (state.get("_public_thinking_fragments") or [])
        if str(fragment or "").strip()
    ]
    fragments = [fragment for fragment in fragments if fragment]
    if fragments:
        return "\n\n".join(fragments)

    lifecycle_text = resolve_visible_thinking_from_lifecycle(
        state,
        fallback=fallback,
    )
    if lifecycle_text:
        return lifecycle_text

    current = sanitize_visible_reasoning_text(str(state.get("thinking_content") or "")).strip()
    if current:
        return current

    public_native = sanitize_visible_reasoning_text(str(state.get("thinking") or "")).strip()
    if public_native:
        return public_native

    return sanitize_visible_reasoning_text(str(fallback or "")).strip()
