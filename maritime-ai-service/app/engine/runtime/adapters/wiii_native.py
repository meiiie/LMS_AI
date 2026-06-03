"""Adapter: Wiii native ``ChatRequest`` → ``TurnRequest``.

Today the Wiii API accepts a compact ``ChatRequest`` (``message`` string +
identity headers). This adapter wraps that shape into a canonical
``TurnRequest`` so downstream lane-first dispatch can be unified across
all three edge protocols.

Pure conversion function, no I/O. Identity (user/session/org/role/domain)
is read from caller-supplied kwargs because in the live API those values
arrive via headers, not the body.
"""

from __future__ import annotations

from typing import Optional

from app.engine.messages import Message
from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload
from app.engine.runtime.turn_request import TurnRequest


def _safe_metadata(value: Optional[dict]) -> dict:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


def wiii_chat_request_to_turn_request(
    *,
    message: str,
    user_id: str,
    session_id: str,
    org_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    role: str = "student",
    history: Optional[list[Message]] = None,
    requested_streaming: bool = False,
    requested_capabilities: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> TurnRequest:
    """Build a ``TurnRequest`` from a Wiii native chat call.

    ``message`` becomes the final ``user`` turn appended to ``history``;
    everything else is identity / capability metadata.
    """
    msgs: list[Message] = list(history or [])
    msgs.append(Message(role="user", content=message))
    return TurnRequest(
        messages=msgs,
        user_id=user_id,
        session_id=session_id,
        org_id=org_id,
        domain_id=domain_id,
        role=role,
        requested_streaming=requested_streaming,
        requested_capabilities=list(requested_capabilities or []),
        metadata=_safe_metadata(metadata),
    )


__all__ = ["wiii_chat_request_to_turn_request"]
