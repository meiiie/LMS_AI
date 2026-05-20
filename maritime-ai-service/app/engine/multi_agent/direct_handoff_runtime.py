"""Direct runtime handoff state recording."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.state import AgentState


def record_direct_handoff_request(
    *,
    state: AgentState | dict[str, Any] | None,
    tool_name: str,
    tool_args: dict[str, Any],
    enabled: bool,
    logger_obj: logging.Logger,
) -> str | None:
    """Record a valid direct agent handoff target in state."""

    if state is None or not enabled or tool_name != "handoff_to_agent":
        return None

    try:
        from app.engine.multi_agent.handoff_tools import extract_handoff_target

        target = extract_handoff_target(tool_args or {})
        if not target:
            return None
        state["_handoff_target"] = target
        logger_obj.info("[DIRECT] Agent handoff requested -> %s", target)
        return target
    except Exception:  # noqa: BLE001
        return None
