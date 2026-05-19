"""Renderer registry for deterministic Code Studio scaffold fallbacks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.code_studio_scaffold_contract import PRIMITIVE_DATA_BAND


ScaffoldRenderer = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ScaffoldRendererRegistry:
    """Map scaffold primitives to renderer functions with one audited fallback."""

    renderers: Mapping[str, ScaffoldRenderer]
    fallback_renderer: ScaffoldRenderer
    fallback_primitive: str = PRIMITIVE_DATA_BAND

    def renderer_for(self, primitive: str | None) -> ScaffoldRenderer:
        if primitive and primitive in self.renderers:
            return self.renderers[primitive]
        return self.fallback_renderer

    def render(self, spec: dict[str, Any]) -> str:
        primitive = str(spec.get("primitive") or self.fallback_primitive)
        return self.renderer_for(primitive)(spec)
