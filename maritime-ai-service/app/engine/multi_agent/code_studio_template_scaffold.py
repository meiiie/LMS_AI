"""Spec-driven graceful HTML scaffold for Code Studio (Sprint 35i SOTA refactor).

When the Code Studio tool-planning LLM call times out or fails (NVIDIA NIM
connection errors, DeepSeek streaming stalls), we still owe the user a
visible canvas instead of a canned "Mình gặp trục trặc" message.

## Why this exists (the 10 000-topic problem)

Sprint 35e/35f/35g built one HTML template per topic kind (literary,
physics, math, history, celestial, default). Sprint 35h replaced that
with 16 INTENT_PATTERNS — better, but still topic-bound: adding "lá rụng
mùa thu" needed a dict entry, "mưa rơi" needed another, "đại bàng săn
mồi" needed another. With 10 000 possible Vietnamese queries it didn't
scale.

Sprint 35i fixes the architecture, not the count.

## Architecture — three-tier resolution

### Tier 1: ``TOPIC_LIBRARY`` (rich content overrides, ~5 entries)

Hand-curated event/moment lists for famous, recurring topics: Thế chiến
II, Khởi nghĩa Lam Sơn, Bạch Đằng, Truyện Kiều, văn học Việt Nam. When
matched, scaffold ships concrete years/quotes instead of placeholder
structure. Adding a new famous topic = +1 entry (~10 lines).

### Tier 2: ``PRIMITIVE_CONCEPTS`` (concept-level patterns, 7 entries)

Universal motion/structure/atmosphere signals → primitive type. NOT
topic-bound: "rụng/rơi/lả tả" matches falling autumn leaves, snow, rain,
ash, petals, tears — anything that falls. "lịch sử/triều đại/chiến
tranh" matches WW2, Lê Lợi, Roman empire, Genghis Khan. "hàm/đồ thị/sin"
matches any math curve.

The 7 concepts cover every primitive family the renderers can produce:
``particle_drift_down``, ``particle_float``, ``particle_twinkle``,
``oscillation``, ``function_plot``, ``timeline``, ``scene``.

### Tier 3: smart inference defaults (handles infinite novel topics)

When no concept matches, ``_build_default_spec`` returns a ``DATA_BAND``
canvas with all fields filled by deterministic inference helpers run on
the query alone:

- ``_extract_visual_title`` — strips command words ("mô phỏng", "vẽ",
  "tạo") so the title focuses on the noun phrase.
- ``_infer_palette`` — picks palette from atmospheric/seasonal keywords
  ("đêm" → night_sky, "mùa thu" → autumn, "biển" → ocean, etc.).
- ``_infer_object_name`` — detects object noun ("lá", "tuyết", "giọt",
  "ngôi sao", "đom đóm") for slider labels.
- ``_infer_drift_direction`` — extracts motion verb ("rơi" → down,
  "bay" → float, "lung linh" → twinkle) for particle behaviour.
- ``_infer_count_range`` — quantity hints ("dày đặc" → 250 default,
  "lác đác" → 25 default).

All deterministic, microsecond-fast, no LLM dependency. Adding 10 000
novel topics = 0 lines of code.

## Primitives (6 universal canvas families, unchanged from 35h)

- ``PARTICLE_FIELD`` — stars, dust, leaves, snow, fireflies, plankton…
- ``OSCILLATION`` — pendulum, spring, transverse wave, harmonic motion
- ``TIMELINE`` — historical events, project plan, life cycle, story arc
- ``FUNCTION_PLOT`` — math curves, value-over-x with draggable probe
- ``SCENE`` — atmospheric scene with optional figure(s) + landmark
- ``DATA_BAND`` — abstract sine wave (true topic-agnostic placeholder)

Each primitive accepts the same ``ScaffoldSpec`` shape (now richer
thanks to ``_enrich_spec``) and emits canvas + slider + aria-live
readout + RAF state engine + WiiiVisualBridge feedback hook — passing
every requirement of ``validate_code_studio_output`` for premium
simulations.

## Public API (backward-compatible)

- ``INTENT_PATTERNS`` — alias = TOPIC_LIBRARY + PRIMITIVE_CONCEPTS
  (existing tests still import this).
- ``extract_scaffold_spec(query)`` — runs the 3-tier resolution.
- ``detect_scaffold_kind(query)`` — returns legacy kind name
  (``literary``, ``physics``, ``math``, ``history``, ``celestial``,
  ``default``) for callers/tests that depend on the older surface.
- ``build_code_studio_scaffold(query, kind=None)`` — returns full HTML.
- ``build_scaffold_visible_caption(query, kind=None)`` — short caption.

Pure functions — no LLM, no async, no I/O. Pattern reference:
- Anthropic Claude Artifacts 2026 — spec-driven primitives
- Vercel v0 — parameterized React templates
- Bolt.new — WebContainer scaffolds + theme inheritance
- Cursor Composer 2026 — LLM-as-renderer fallback chain
- W3C CSS Custom Properties Level 3 — variable inheritance

Wiii references:
- ``app/engine/reasoning/skills/subagents/code_studio_agent/VISUAL_CODE_GEN.md``
- ``app/engine/tools/visual_code_quality.py`` (validator the scaffold
  output must satisfy)
"""

from __future__ import annotations

from app.engine.multi_agent.code_studio_scaffold_core_renderers import (
    render_function_plot_scaffold,
    render_oscillation_scaffold,
    render_particle_field_scaffold,
    render_timeline_scaffold,
)
from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    PRIMITIVE_FUNCTION_PLOT,
    PRIMITIVE_OSCILLATION,
    PRIMITIVE_PARTICLE_FIELD,
    PRIMITIVE_SCENE,
    PRIMITIVE_TIMELINE,
    primitive_for_legacy_kind,
)
from app.engine.multi_agent.code_studio_scaffold_captions import (
    caption_for_scaffold_primitive,
)
from app.engine.multi_agent.code_studio_scaffold_registry import (
    ScaffoldRendererRegistry,
)
from app.engine.multi_agent.code_studio_scaffold_scene_renderers import (
    render_data_band_scaffold,
    render_scene_scaffold,
)
from app.engine.multi_agent.code_studio_scaffold_shell import (
    _PALETTES,
    _build_shell,
    _common_script_wrapper,
    _short_title,
)

# ============================================================================
# Primitive identifiers + legacy kind mapping contract
# ============================================================================

# Primitive and legacy-kind names live in ``code_studio_scaffold_contract``.
# This renderer imports them so public routing/metrics code can depend on the
# contract without importing the full HTML scaffold module.

# ============================================================================
# Intent/spec extraction
# ============================================================================

# Compatibility re-exports keep existing imports stable while the deterministic
# topic library and inference helpers live in a focused, I/O-free spec module.
from app.engine.multi_agent.code_studio_scaffold_spec import (
    INTENT_PATTERNS as INTENT_PATTERNS,
    PRIMITIVE_CONCEPTS as PRIMITIVE_CONCEPTS,
    TOPIC_LIBRARY as TOPIC_LIBRARY,
    _DEFAULT_PALETTE_BY_PRIMITIVE as _DEFAULT_PALETTE_BY_PRIMITIVE,
    _OBJECT_HINTS as _OBJECT_HINTS,
    _PALETTE_HINTS as _PALETTE_HINTS,
    _TITLE_PREFIXES as _TITLE_PREFIXES,
    _build_default_spec as _build_default_spec,
    _enrich_spec as _enrich_spec,
    _extract_visual_title as _extract_visual_title,
    _infer_count_range as _infer_count_range,
    _infer_drift_direction as _infer_drift_direction,
    _infer_object_name as _infer_object_name,
    _infer_palette as _infer_palette,
    _normalize as _normalize,
    detect_scaffold_kind as detect_scaffold_kind,
    extract_scaffold_spec as extract_scaffold_spec,
)

# ============================================================================
# Primitive renderers (parameterized by spec)
# ============================================================================


# Extraction boundary: user-visible fallback HTML parity is the risk; rollback
# is a straight revert of the renderer-split commit if core primitives drift.
def _render_particle_field(spec: dict) -> str:
    return render_particle_field_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


def _render_oscillation(spec: dict) -> str:
    return render_oscillation_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


def _render_function_plot(spec: dict) -> str:
    return render_function_plot_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


def _render_timeline(spec: dict) -> str:
    return render_timeline_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
        palettes=_PALETTES,
    )


# Extraction boundary: user-visible fallback HTML parity is the risk; rollback
# is a straight revert of the renderer-split commit if scene/data-band drifts.
def _render_scene(spec: dict) -> str:
    return render_scene_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
    )


def _render_data_band(spec: dict) -> str:
    return render_data_band_scaffold(
        spec,
        build_shell=_build_shell,
        common_script_wrapper=_common_script_wrapper,
        short_title=_short_title,
    )

# ============================================================================
# Public API
# ============================================================================


_PRIMITIVE_RENDERERS = {
    PRIMITIVE_PARTICLE_FIELD: _render_particle_field,
    PRIMITIVE_OSCILLATION: _render_oscillation,
    PRIMITIVE_TIMELINE: _render_timeline,
    PRIMITIVE_FUNCTION_PLOT: _render_function_plot,
    PRIMITIVE_SCENE: _render_scene,
    PRIMITIVE_DATA_BAND: _render_data_band,
}

_RENDERER_REGISTRY = ScaffoldRendererRegistry(
    renderers=_PRIMITIVE_RENDERERS,
    fallback_renderer=_render_data_band,
)


def build_code_studio_scaffold(query: str, *, kind: str | None = None) -> str:
    """Return Canvas-first HTML scaffold satisfying tool_create_visual_code.

    The output is generated by selecting one of six universal canvas
    primitives (``particle_field``, ``oscillation``, ``timeline``,
    ``function_plot``, ``scene``, ``data_band``) and parameterising it
    with a spec extracted from the query via ``INTENT_PATTERNS``. Every
    primitive ships ``<canvas>``, ``<input type="range">``, ``aria-live``,
    ``requestAnimationFrame``, and ``WiiiVisualBridge.reportResult`` so it
    passes ``validate_code_studio_output`` for premium simulations.

    Args:
        query: User's original simulation/visualisation request.
        kind: Optional legacy kind override (``literary``, ``physics``,
            ``math``, ``history``, ``celestial``, ``default``). When set,
            forces the matching primitive even if intent extraction picks
            something else.
    """
    spec = extract_scaffold_spec(query)
    if kind:
        forced_primitive = primitive_for_legacy_kind(kind)
        if forced_primitive:
            spec = {**spec, "primitive": forced_primitive}
    return _RENDERER_REGISTRY.render(spec)


def build_scaffold_visible_caption(query: str, *, kind: str | None = None) -> str:
    """Short Vietnamese caption shown above the canvas in the chat thread."""
    spec = extract_scaffold_spec(query)
    if kind:
        forced_primitive = primitive_for_legacy_kind(kind)
        if forced_primitive:
            spec["primitive"] = forced_primitive
    primitive = spec.get("primitive", PRIMITIVE_DATA_BAND)
    return caption_for_scaffold_primitive(primitive)
