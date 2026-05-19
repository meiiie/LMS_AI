"""Singleton registry for subagent definitions."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from app.engine.multi_agent.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


class SubagentRegistry:
    """Central registry for all available subagents.

    Usage::

        registry = SubagentRegistry.get_instance()
        registry.register(
            "deep_search",
            builder=run_product_search,
            config=SubagentConfig(name="deep_search", timeout_seconds=90),
            description="Parallel product search across platforms",
        )
        entry = registry.get("deep_search")
    """

    _instance: Optional[SubagentRegistry] = None

    def __init__(self) -> None:
        self._subagents: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> SubagentRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — intended for tests only."""
        cls._instance = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        *,
        builder: Callable,
        config: SubagentConfig,
        description: str = "",
    ) -> None:
        """Register a subagent by name."""
        self._subagents[name] = {
            "builder": builder,
            "config": config,
            "description": description,
        }
        logger.info("Registered subagent: %s", name)

    def unregister(self, name: str) -> bool:
        """Remove a subagent.  Returns ``True`` if it existed."""
        return self._subagents.pop(name, None) is not None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._subagents.get(name)

    def get_builder(self, name: str) -> Optional[Callable]:
        entry = self._subagents.get(name)
        return entry["builder"] if entry else None

    def get_config(self, name: str) -> Optional[SubagentConfig]:
        entry = self._subagents.get(name)
        return entry["config"] if entry else None

    def has(self, name: str) -> bool:
        return name in self._subagents

    def list_subagents(self) -> List[Dict[str, str]]:
        return [
            {"name": name, "description": info["description"]}
            for name, info in self._subagents.items()
        ]

    @property
    def count(self) -> int:
        return len(self._subagents)
