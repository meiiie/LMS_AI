"""Typed contract for deterministic Code Studio scaffold fallbacks.

The scaffold renderer may stay large while Wiii evolves, but primitive names
and legacy kind mapping are public compatibility surface. Keeping them here
prevents renderer internals from becoming the source of truth for routing,
metrics, and tests.
"""

from __future__ import annotations

from typing import Literal

ScaffoldPrimitive = Literal[
    "particle_field",
    "oscillation",
    "timeline",
    "function_plot",
    "scene",
    "data_band",
]

LegacyScaffoldKind = Literal[
    "literary",
    "physics",
    "math",
    "history",
    "celestial",
    "default",
]

PRIMITIVE_PARTICLE_FIELD: ScaffoldPrimitive = "particle_field"
PRIMITIVE_OSCILLATION: ScaffoldPrimitive = "oscillation"
PRIMITIVE_TIMELINE: ScaffoldPrimitive = "timeline"
PRIMITIVE_FUNCTION_PLOT: ScaffoldPrimitive = "function_plot"
PRIMITIVE_SCENE: ScaffoldPrimitive = "scene"
PRIMITIVE_DATA_BAND: ScaffoldPrimitive = "data_band"

LEGACY_KIND_TO_PRIMITIVE: dict[LegacyScaffoldKind, ScaffoldPrimitive] = {
    "literary": PRIMITIVE_SCENE,
    "physics": PRIMITIVE_OSCILLATION,
    "math": PRIMITIVE_FUNCTION_PLOT,
    "history": PRIMITIVE_TIMELINE,
    "celestial": PRIMITIVE_PARTICLE_FIELD,
    "default": PRIMITIVE_DATA_BAND,
}

PRIMITIVE_TO_LEGACY_KIND: dict[ScaffoldPrimitive, LegacyScaffoldKind] = {
    PRIMITIVE_SCENE: "literary",
    PRIMITIVE_OSCILLATION: "physics",
    PRIMITIVE_FUNCTION_PLOT: "math",
    PRIMITIVE_TIMELINE: "history",
    PRIMITIVE_PARTICLE_FIELD: "celestial",
    PRIMITIVE_DATA_BAND: "default",
}


def primitive_for_legacy_kind(kind: str | None) -> ScaffoldPrimitive | None:
    """Return the primitive forced by a legacy kind override, if valid."""
    if not kind:
        return None
    return LEGACY_KIND_TO_PRIMITIVE.get(kind)  # type: ignore[arg-type]


def legacy_kind_for_primitive(primitive: str | None) -> LegacyScaffoldKind:
    """Return the compatibility kind for a primitive name."""
    return PRIMITIVE_TO_LEGACY_KIND.get(primitive, "default")  # type: ignore[arg-type]
