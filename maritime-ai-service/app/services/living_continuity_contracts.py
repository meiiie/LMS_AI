"""Shared contracts for post-response continuity helpers.

These types are intentionally separated from the orchestration module so
specialized post-response helpers can depend on stable contracts without
importing the higher-level coordinator back.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PostResponseContinuityContext"]


@dataclass(frozen=True)
class PostResponseContinuityContext:
    """Inputs needed after a response has been produced."""

    user_id: str
    user_role: str
    message: str
    response_text: str
    session_id: str | None = None
    request_id: str | None = None
    domain_id: str = ""
    organization_id: str | None = None
    channel: str = "web"
