"""Shared runtime contracts for application startup and shutdown."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class AppRuntimeResources:
    """Shared startup resources that must be cleaned up on shutdown."""

    neo4j_repo: Any = None
    runtime_audit_task: asyncio.Task | None = None
    runtime_audit_loop_task: asyncio.Task | None = None
    model_health_probe_task: asyncio.Task | None = None
    model_health_probe_loop_task: asyncio.Task | None = None
    scheduled_executor: Any = None
    heartbeat: Any = None
    soul_bridge: Any = None
    magic_link_cleanup_task: asyncio.Task | None = None
    magic_link_reaper_task: asyncio.Task | None = None
