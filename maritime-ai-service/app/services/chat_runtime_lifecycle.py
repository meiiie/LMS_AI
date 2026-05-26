"""Typed lifecycle events for the SSE V3 chat runtime.

These events are additive observability: they let clients and harnesses follow
the turn path without parsing Vietnamese status copy or waiting for terminal
metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.engine.multi_agent.stream_utils import StreamEvent


CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION = "wiii.chat_runtime_lifecycle.v1"
CHAT_RUNTIME_LIFECYCLE_EVENT_TYPE = "chat_lifecycle"


class ChatLifecycleName:
    """Stable lifecycle names emitted on the SSE wire."""

    CHAT_ACCEPTED = "chat.accepted"
    TURN_PREPARED = "turn.prepared"
    PATH_SELECTED = "path.selected"
    CAPABILITY_CHECKED = "capability.checked"
    FINALIZATION_COMPLETED = "finalization.completed"
    FINALIZATION_FAILED = "finalization.failed"
    CHAT_DONE = "chat.done"
    CHAT_ERROR = "chat.error"


_MAX_ITEMS = 24
_MAX_STRING_LENGTH = 128


def _safe_string(value: Any, *, max_length: int = _MAX_STRING_LENGTH) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 1] + "..."
    return text


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    output: list[str] = []
    for item in value:
        text = _safe_string(item)
        if text and text not in output:
            output.append(text)
        if len(output) >= _MAX_ITEMS:
            break
    return output


def _safe_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def capability_snapshot_from_ledger_payload(
    ledger_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the lifecycle-safe capability/tool subset from a flow ledger."""

    request = _safe_mapping(ledger_payload.get("request"))
    tools = _safe_mapping(ledger_payload.get("tools"))
    host_actions = _safe_mapping(ledger_payload.get("host_actions"))
    return {
        "host_surface": _safe_string(request.get("host_surface")) or "unknown",
        "host_capabilities": _safe_string_list(request.get("host_capabilities")),
        "observed_tools": _safe_string_list(tools.get("observed")),
        "suppressed_tools": _safe_string_list(tools.get("suppressed")),
        "preview_required": bool(host_actions.get("preview_required")),
        "preview_emitted": bool(host_actions.get("preview_emitted")),
        "approval_token_present": bool(host_actions.get("approval_token_present")),
        "apply_attempted": bool(host_actions.get("apply_attempted")),
    }


@dataclass(frozen=True)
class ChatRuntimeLifecycleEvent:
    """Privacy-safe lifecycle event for streaming chat clients."""

    name: str
    phase: str
    status: str
    message: str
    request_id: str | None = None
    session_id: str | None = None
    lane: str | None = None
    reason: str | None = None
    node: str | None = None
    capabilities: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION,
            "event_name": self.name,
            "phase": self.phase,
            "status": self.status,
            "message": self.message,
        }
        for key, value in (
            ("request_id", self.request_id),
            ("session_id", self.session_id),
            ("lane", self.lane),
            ("reason", self.reason),
            ("node", self.node),
        ):
            text = _safe_string(value)
            if text:
                payload[key] = text
        if self.capabilities is not None:
            payload["capabilities"] = dict(self.capabilities)
        if self.metadata:
            payload["metadata"] = {
                str(key): value
                for key, value in self.metadata.items()
                if value is not None
            }
        return payload


def create_chat_lifecycle_event(
    lifecycle: ChatRuntimeLifecycleEvent,
) -> StreamEvent:
    """Wrap a typed lifecycle payload in the existing StreamEvent transport."""

    return StreamEvent(
        type=CHAT_RUNTIME_LIFECYCLE_EVENT_TYPE,
        content=lifecycle.to_payload(),
        node=lifecycle.node,
        step=lifecycle.phase,
        details={"event_name": lifecycle.name},
    )


__all__ = [
    "CHAT_RUNTIME_LIFECYCLE_EVENT_TYPE",
    "CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION",
    "ChatLifecycleName",
    "ChatRuntimeLifecycleEvent",
    "capability_snapshot_from_ledger_payload",
    "create_chat_lifecycle_event",
]
