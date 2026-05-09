"""Code Studio skill/example asset loading helpers.

Follows the Anthropic skill-creator progressive-disclosure pattern
(https://github.com/anthropics/skills):

- The Code Studio SKILL lives at
  ``app/engine/skills/library/visual-code-gen/SKILL.md`` (canonical
  ``<skill-name>/SKILL.md`` folder layout). Its frontmatter-stripped
  body is always injected as the core skill — lean ~9 KB lane policy
  + quality rubric.
- Reference docs in ``library/visual-code-gen/references/`` are loaded
  ON-DEMAND via ``load_code_studio_reference(name)`` — the model asks
  for them when it needs deep context (scaffold internals, theme
  variables, AI-slop detection patterns, etc.).
- Reference examples in
  ``app/engine/reasoning/skills/subagents/code_studio_agent/examples/``
  are loaded ON-DEMAND keyed by ``visual_type`` via
  ``_load_code_studio_example``.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CODE_STUDIO_SKILLS_CACHE: list[str] | None = None
_CODE_STUDIO_EXAMPLES_CACHE: dict[str, str] = {}
_CODE_STUDIO_REFERENCES_CACHE: dict[str, str] = {}

# Canonical SKILL location (Anthropic skill-creator layout).
_CODE_STUDIO_SKILL_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "library" / "visual-code-gen"
)

# Map of reference name → filename in references/ folder. Names are
# stable handles the model can request (and we can log/meter).
_CODE_STUDIO_REFERENCE_MAP: dict[str, str] = {
    "scaffold": "scaffold_3tier_resolution.md",
    "scaffold_3tier": "scaffold_3tier_resolution.md",
    "theme": "theme_inheritance.md",
    "theme_inheritance": "theme_inheritance.md",
    "ai_slop": "ai_slop_anti_patterns.md",
    "anti_patterns": "ai_slop_anti_patterns.md",
    "react": "react_widget_guidelines.md",
    "react_widget": "react_widget_guidelines.md",
    "examples_inventory": "reference_examples_inventory.md",
}

# Legacy filename (kept for the assertion in _load_code_studio_visual_skills
# — historic builds shipped this single file at the subagent path).
_CODE_STUDIO_SKILL_FILES = [
    "SKILL.md",
]

_CODE_STUDIO_EXAMPLE_MAP: dict[str, str] = {
    "simulation": "canvas_wave_interference.html",
    "physics": "canvas_wave_interference.html",
    "animation": "canvas_wave_interference.html",
    "diagram": "svg_ship_encounter.html",
    "architecture": "svg_ship_encounter.html",
    "comparison": "html_comparison_clean.html",
    "chart": "svg_horizontal_bar_clean.html",
    "benchmark": "svg_horizontal_bar_clean.html",
    "statistics": "svg_horizontal_bar_clean.html",
    "horizontal_bar": "svg_horizontal_bar_clean.html",
    "process": "html_process_flow_clean.html",
    "workflow": "html_process_flow_clean.html",
    "timeline": "html_process_flow_clean.html",
    "dashboard": "dashboard_metrics.html",
    "metrics": "dashboard_metrics.html",
    "overview": "dashboard_metrics.html",
    "tool": "widget_maritime_calculator.html",
    "quiz": "widget_maritime_calculator.html",
    "calculator": "widget_maritime_calculator.html",
    "radar": "svg_radar_clean.html",
    "spider": "svg_radar_clean.html",
    "bar_chart": "svg_vertical_bar_clean.html",
    "column": "svg_vertical_bar_clean.html",
    "vertical_bar": "svg_vertical_bar_clean.html",
    "pie": "svg_donut_clean.html",
    "donut": "svg_donut_clean.html",
    "doughnut": "svg_donut_clean.html",
    "line_chart": "svg_line_clean.html",
    "line": "svg_line_clean.html",
    "svg_motion": "svg_motion_animation.html",
    "motion": "svg_motion_animation.html",
    "morph": "svg_motion_animation.html",
    "particle": "canvas_particle_system.html",
    "particles": "canvas_particle_system.html",
    "effect": "canvas_particle_system.html",
}


def _load_code_studio_visual_skills() -> list[str]:
    """Load and cache the Code Studio SKILL body (frontmatter stripped).

    Reads from the canonical Anthropic skill-creator location
    (``library/visual-code-gen/SKILL.md``).
    """
    global _CODE_STUDIO_SKILLS_CACHE
    if _CODE_STUDIO_SKILLS_CACHE is not None:
        return _CODE_STUDIO_SKILLS_CACHE

    results: list[str] = []
    skill_path = _CODE_STUDIO_SKILL_DIR / "SKILL.md"
    try:
        raw = skill_path.read_text(encoding="utf-8")
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                results.append(parts[2].strip())
            else:
                results.append(raw.strip())
        else:
            results.append(raw.strip())
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[CODE_STUDIO] Skill unavailable at %s: %s", skill_path, exc)

    _CODE_STUDIO_SKILLS_CACHE = results
    return _CODE_STUDIO_SKILLS_CACHE


def _load_code_studio_example(visual_type: str) -> str | None:
    """Load a reference example on-demand based on visual_type."""
    filename = _CODE_STUDIO_EXAMPLE_MAP.get(visual_type)
    if not filename:
        return None

    if filename in _CODE_STUDIO_EXAMPLES_CACHE:
        return _CODE_STUDIO_EXAMPLES_CACHE[filename]

    examples_dir = (
        Path(__file__).resolve().parent.parent
        / "reasoning" / "skills" / "subagents" / "code_studio_agent" / "examples"
    )
    example_path = examples_dir / filename
    try:
        raw = example_path.read_text(encoding="utf-8")
        lines = raw.split("\n")
        if len(lines) > 250:
            truncated = (
                "\n".join(lines[:250])
                + "\n<!-- ... truncated — see full example in examples/ folder -->"
            )
        else:
            truncated = raw
        _CODE_STUDIO_EXAMPLES_CACHE[filename] = truncated
        return truncated
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[CODE_STUDIO] Example %s unavailable: %s", filename, exc)
        return None


def load_code_studio_reference(name: str) -> str | None:
    """Load a reference doc on-demand from ``references/``.

    Implements the Anthropic skill-creator progressive-disclosure
    pattern: the core SKILL stays lean, deep context is loaded only
    when the agent explicitly asks for it.

    Args:
        name: One of the keys in ``_CODE_STUDIO_REFERENCE_MAP``
            (``scaffold``, ``theme``, ``ai_slop``, ``react``,
            ``examples_inventory``). Aliases are accepted.

    Returns:
        The reference body as a string, or ``None`` if the name is
        unknown or the file cannot be read.
    """
    filename = _CODE_STUDIO_REFERENCE_MAP.get(name)
    if not filename:
        logger.debug("[CODE_STUDIO] Unknown reference name: %s", name)
        return None
    if filename in _CODE_STUDIO_REFERENCES_CACHE:
        return _CODE_STUDIO_REFERENCES_CACHE[filename]
    references_dir = _CODE_STUDIO_SKILL_DIR / "references"
    ref_path = references_dir / filename
    try:
        body = ref_path.read_text(encoding="utf-8")
        _CODE_STUDIO_REFERENCES_CACHE[filename] = body
        return body
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("[CODE_STUDIO] Reference %s unavailable: %s", filename, exc)
        return None


def list_code_studio_references() -> list[str]:
    """Return the stable handle names callers can request."""
    return sorted(set(_CODE_STUDIO_REFERENCE_MAP.keys()))
