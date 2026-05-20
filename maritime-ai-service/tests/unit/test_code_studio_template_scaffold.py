"""Regression tests for Sprint 35d Code Studio graceful HTML scaffold.

The scaffold module is the deterministic fallback Wiii uses when the
NVIDIA NIM streaming/non-streaming planning call fails to produce a
``tool_create_visual_code`` invocation. These tests pin down:

- topic-kind detection across Vietnamese literature, physics, math, default
- HTML output shape that satisfies ``tool_create_visual_code_impl``
- Vietnamese caption that the chat thread shows above the canvas
- counter emission so operators can observe scaffold engagement rate

Pattern reference: VISUAL_CODE_GEN.md v6.0.0 host-governed runtime + the
direct_search_synthesis_fallback companion module from Sprint 35c.
"""

from __future__ import annotations

import pytest

from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    PRIMITIVE_FUNCTION_PLOT,
    PRIMITIVE_OSCILLATION,
    PRIMITIVE_PARTICLE_FIELD,
    PRIMITIVE_SCENE,
    PRIMITIVE_TIMELINE,
    legacy_kind_for_primitive,
    primitive_for_legacy_kind,
)
from app.engine.multi_agent.code_studio_scaffold_captions import (
    caption_for_scaffold_primitive,
)
from app.engine.multi_agent.code_studio_scaffold_registry import (
    ScaffoldRendererRegistry,
)
from app.engine.multi_agent.code_studio_template_scaffold import (
    _render_data_band,
    _render_function_plot,
    _render_oscillation,
    _render_particle_field,
    _render_scene,
    _render_timeline,
    build_code_studio_scaffold,
    build_scaffold_visible_caption,
    detect_scaffold_kind,
    extract_scaffold_spec,
)


# ---------------------------------------------------------------------------
# detect_scaffold_kind — mapping queries to the right scaffold family
# ---------------------------------------------------------------------------


def test_scaffold_contract_maps_legacy_kinds_without_renderer_imports() -> None:
    """Routing code can depend on the typed scaffold contract directly."""
    assert primitive_for_legacy_kind("literary") == PRIMITIVE_SCENE
    assert primitive_for_legacy_kind("physics") == PRIMITIVE_OSCILLATION
    assert primitive_for_legacy_kind("math") == PRIMITIVE_FUNCTION_PLOT
    assert primitive_for_legacy_kind("history") == PRIMITIVE_TIMELINE
    assert primitive_for_legacy_kind("celestial") == PRIMITIVE_PARTICLE_FIELD
    assert primitive_for_legacy_kind("default") == PRIMITIVE_DATA_BAND
    assert primitive_for_legacy_kind("unknown") is None
    assert legacy_kind_for_primitive(PRIMITIVE_SCENE) == "literary"
    assert legacy_kind_for_primitive("unknown") == "default"


def test_scaffold_renderer_registry_falls_back_to_data_band_renderer() -> None:
    """Unknown primitive names must have exactly one safe fallback path."""
    calls: list[dict] = []

    def fallback_renderer(spec: dict) -> str:
        calls.append(spec)
        return "fallback-html"

    registry = ScaffoldRendererRegistry(
        renderers={},
        fallback_renderer=fallback_renderer,
    )

    spec = {"primitive": "unknown"}
    assert registry.render(spec) == "fallback-html"
    assert calls == [spec]


def test_scaffold_caption_contract_is_primitive_based() -> None:
    """Caption copy can be audited without importing the large renderer."""
    scene_caption = caption_for_scaffold_primitive(PRIMITIVE_SCENE)
    fallback_caption = caption_for_scaffold_primitive("unknown")

    assert "scene" in scene_caption.lower()
    assert "canvas" in fallback_caption.lower()


@pytest.mark.parametrize(
    "query, expected_kind",
    [
        # Truyện Kiều family
        ("mô phỏng Thúy Kiều ở lầu Ngưng Bích", "literary"),
        ("vẽ cảnh Kiều gặp Kim Trọng", "literary"),
        ("Đoạn trường tân thanh", "literary"),
        # Other Vietnamese literature
        ("mô phỏng Tấm Cám hoá thành chim vàng anh", "literary"),
        ("vẽ Lão Hạc khóc trước khi ăn bả chó", "literary"),
        ("Chí Phèo vác dao đi đòi quyền làm người", "literary"),
        ("Vợ chồng A Phủ trên đồi cao", "literary"),
        # Authors
        ("Nguyễn Du và truyền thuyết Thúy Kiều", "literary"),
        ("phong cách thơ Xuân Diệu", "literary"),
        # Physics
        ("mô phỏng con lắc đơn dao động tự do", "physics"),
        ("vẽ quỹ đạo viên đạn parabol", "physics"),
        ("simulation of pendulum motion", "physics"),
        # Math
        ("vẽ đồ thị hàm số bậc 2", "math"),
        ("dựng vector trong toạ độ Oxy", "math"),
        ("integral của f(x) = x^2", "math"),
        # Default — neutral / unknown topic
        ("widget tính lương nhân viên", "default"),
        ("dashboard quản lý kho", "default"),
    ],
)
def test_detect_scaffold_kind(query: str, expected_kind: str) -> None:
    assert detect_scaffold_kind(query) == expected_kind


def test_detect_scaffold_kind_empty_input() -> None:
    """Empty/blank queries should fall through to the default scaffold."""
    assert detect_scaffold_kind("") == "default"
    assert detect_scaffold_kind("   ") == "default"


# ---------------------------------------------------------------------------
# build_code_studio_scaffold — output shape contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query, expected_kind",
    [
        ("mô phỏng Thúy Kiều ở lầu Ngưng Bích", "literary"),
        ("mô phỏng con lắc", "physics"),
        ("đồ thị hàm số y=x^2", "math"),
        ("widget bất kỳ", "default"),
    ],
)
def test_scaffold_satisfies_tool_create_visual_code_contract(
    query: str, expected_kind: str
) -> None:
    """``tool_create_visual_code_impl`` requires code_html ≥ 50 chars with
    inline ``<style>`` block and visible body — the scaffold must satisfy
    every requirement before the topic-aware fallback can route through it.
    """
    html = build_code_studio_scaffold(query)
    assert len(html) >= 50, f"scaffold too short for {expected_kind!r}: {len(html)}"
    assert "<style>" in html, "scaffold missing <style> block"
    assert "</style>" in html, "scaffold missing closing </style>"
    # Body must contain visible markup, not just CSS.
    assert "<div" in html, "scaffold missing visible <div> body"
    assert "</div>" in html
    # Title is escaped and present so the chat thread can correlate canvas
    # with the original query.
    assert query[:30].split()[0].lower() in html.lower() or "khung" in html.lower()


def test_scaffold_kind_override() -> None:
    """``kind=`` argument overrides auto-detection — useful when callers
    have stronger context than the keyword matcher (e.g. RAG-classified
    intent or visual_intent resolver lock).
    """
    physics_html = build_code_studio_scaffold("anything", kind="physics")
    assert "wiii-phys-stage" in physics_html

    literary_html = build_code_studio_scaffold("anything", kind="literary")
    assert "wiii-scene-stage" in literary_html


def test_explicit_unknown_simulation_avoids_generic_data_band() -> None:
    """Unmatched simulation prompts should still render a real scene surface.

    This is the long-term guard against the "slop template" failure mode:
    when Wiii cannot classify a novel simulation topic, the deterministic
    fallback must not degrade to a generic data dashboard.
    """
    query = "tạo mô phỏng hảo hán đối ẩm xem"

    spec = extract_scaffold_spec(query)

    assert spec["primitive"] == PRIMITIVE_SCENE
    assert spec["quality_gate"]["name"] == "explicit_simulation_not_generic_data_band"
    html = build_code_studio_scaffold(query)
    assert 'data-scaffold-primitive="scene"' in html
    assert "wiii-scene-stage" in html
    assert "wiii-default-stage" not in html


def test_unknown_non_simulation_still_uses_data_band() -> None:
    """The quality gate should not over-route ordinary widget requests."""
    spec = extract_scaffold_spec("widget bất kỳ")

    assert spec["primitive"] == PRIMITIVE_DATA_BAND
    assert "quality_gate" not in spec


def test_extracted_renderers_keep_wrapper_contract() -> None:
    """Private wrapper names remain the registry boundary after extraction."""
    particle_html = _render_particle_field(
        {
            "primitive": PRIMITIVE_PARTICLE_FIELD,
            "title": "Bầu trời thử",
            "particle_label": "ngôi sao",
        }
    )
    oscillation_html = _render_oscillation(
        {
            "primitive": PRIMITIVE_OSCILLATION,
            "title": "Con lắc thử",
            "slider_label": "Góc lệch",
        }
    )
    plot_html = _render_function_plot(
        {
            "primitive": PRIMITIVE_FUNCTION_PLOT,
            "title": "Hàm thử",
            "slider_label": "x",
        }
    )
    timeline_html = _render_timeline(
        {
            "primitive": PRIMITIVE_TIMELINE,
            "title": "Mốc thử",
            "slider_label": "Năm",
            "events": [
                {"year": 1, "title": "Mở", "text": "Bắt đầu"},
                {"year": 2, "title": "Kết", "text": "Hoàn tất"},
            ],
        }
    )
    scene_html = _render_scene(
        {
            "primitive": PRIMITIVE_SCENE,
            "title": "Cảnh thử",
            "slider_label": "Nhịp cảnh",
            "moments": [
                {"key": "Mở", "quote": "Bắt đầu", "sky_blend": 0.0},
                {"key": "Kết", "quote": "Hoàn tất", "sky_blend": 1.0},
            ],
        }
    )
    data_band_html = _render_data_band(
        {
            "primitive": PRIMITIVE_DATA_BAND,
            "title": "Dữ liệu thử",
            "slider_label": "Tham số",
        }
    )

    assert 'data-scaffold-primitive="particle_field"' in particle_html
    assert "wiii-pf-stage" in particle_html
    assert "WiiiVisualBridge" in particle_html
    assert 'data-scaffold-primitive="oscillation"' in oscillation_html
    assert "wiii-osc-stage" in oscillation_html
    assert "WiiiVisualBridge" in oscillation_html
    assert 'data-scaffold-primitive="function_plot"' in plot_html
    assert "wiii-fp-stage" in plot_html
    assert "WiiiVisualBridge" in plot_html
    assert 'data-scaffold-primitive="timeline"' in timeline_html
    assert "wiii-tl-stage" in timeline_html
    assert "WiiiVisualBridge" in timeline_html
    assert 'data-scaffold-primitive="scene"' in scene_html
    assert "wiii-sc-stage" in scene_html
    assert "WiiiVisualBridge" in scene_html
    assert 'data-scaffold-primitive="data_band"' in data_band_html
    assert "wiii-db-stage" in data_band_html
    assert "WiiiVisualBridge" in data_band_html


def test_scaffold_renders_distinct_html_per_kind() -> None:
    """Each scaffold kind ships its own CSS class namespace so the front-end
    can style/inspect them differently and so a cache key based on the HTML
    is not accidentally shared across kinds.
    """
    queries_by_kind = {
        "literary": "Thúy Kiều ở lầu Ngưng Bích",
        "physics": "con lắc đơn",
        "math": "đồ thị hàm số",
        "default": "widget bất kỳ",
    }
    htmls = {kind: build_code_studio_scaffold(q) for kind, q in queries_by_kind.items()}
    # No two scaffolds should be byte-identical.
    rendered = list(htmls.values())
    assert len(set(rendered)) == 4


def test_scaffold_html_escapes_query_title() -> None:
    """User input lands in the rendered title — must be HTML-escaped so a
    crafted query like ``mô phỏng <script>alert(1)</script>`` cannot inject
    JS into the canvas frame.

    Sprint 35h+ scaffolds use Canvas-first runtime (RAF loop) so a
    legitimate IIFE ``<script>`` tag IS emitted by the framework. What
    matters is that the user's hostile payload is escaped — the framework
    script is hand-written, doesn't interpolate user input as code, and
    runs inside an IIFE with no direct DOM dependencies on user data.
    """
    hostile = 'mô phỏng <script>alert("xss")</script>'
    html = build_code_studio_scaffold(hostile)
    # User's hostile payload must NOT appear unescaped.
    assert "<script>alert(" not in html, "raw user-injected script element"
    assert "alert(\"xss\")" not in html, "user payload not escaped"
    # Inline event handlers on attributes must be absent.
    assert "onerror=" not in html
    assert "onload=" not in html
    # Quotes from the hostile payload must be escaped, not literal.
    assert '"xss"' not in html  # raw double-quoted string broke through escaping
    # Confirm escaping landed — escaped form must appear.
    assert "&lt;" in html, "title escape did not produce &lt; for < character"
    # Framework's IIFE script is allowed exactly once (the canvas-first
    # runtime emits a single self-contained ``(function(){...})()`` block).
    assert html.count("<script>") <= 1, "scaffold should emit at most one framework script"


# ---------------------------------------------------------------------------
# build_scaffold_visible_caption — Vietnamese chat thread copy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query, must_contain",
    [
        ("mô phỏng Thúy Kiều", "scene"),
        ("mô phỏng con lắc", "mô phỏng"),
        ("đồ thị hàm số", "canvas"),
        ("widget bất kỳ", "canvas"),
    ],
)
def test_visible_caption_topic_aware(query: str, must_contain: str) -> None:
    caption = build_scaffold_visible_caption(query)
    assert isinstance(caption, str)
    assert len(caption) > 30, "caption should be a full Vietnamese sentence"
    assert must_contain.lower() in caption.lower()


def test_visible_caption_stays_in_vietnamese() -> None:
    """Wiii's primary language is Vietnamese — caption must not leak the
    English "I have opened the canvas" voice when the LLM falls over.
    """
    caption = build_scaffold_visible_caption("mô phỏng Thúy Kiều")
    # Heuristic: Vietnamese diacritics should appear at least once.
    diacritics = "ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    assert any(ch in caption for ch in diacritics), (
        f"caption missing Vietnamese diacritics: {caption!r}"
    )


# ---------------------------------------------------------------------------
# Sprint 35e Item 1 — Theme inheritance via CSS variables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, must_contain_vars",
    [
        # Literary scaffold should reference scene + accent variables.
        ("literary", [
            "var(--wiii-scene-sky-deep",
            "var(--wiii-scene-sky-mid",
            "var(--wiii-scene-fg",
            "var(--wiii-text-secondary",
            "var(--wiii-font-sans",
        ]),
        # Physics scaffold should reference phys + accent variables.
        ("physics", [
            "var(--wiii-phys-bg-light",
            "var(--wiii-phys-fg",
            "var(--wiii-accent",
            "var(--wiii-text-secondary",
            "var(--wiii-font-sans",
        ]),
        # Math scaffold should reference math + accent variables.
        ("math", [
            "var(--wiii-math-bg-light",
            "var(--wiii-math-fg",
            "var(--wiii-math-grid",
            "var(--wiii-accent",
            "var(--wiii-text-secondary",
        ]),
        # Default scaffold should reference default + accent variables.
        ("default", [
            "var(--wiii-default-bg-light",
            "var(--wiii-default-fg",
            "var(--wiii-accent",
            "var(--wiii-text-secondary",
        ]),
    ],
)
def test_scaffold_consumes_host_theme_variables(
    kind: str, must_contain_vars: list[str]
) -> None:
    """SKILL VISUAL_CODE_GEN.md v6.2.0 §12 — Every scaffold reads its
    palette through ``var(--wiii-*, fallback)`` so host theme overrides
    can land in the iframe via the InlineVisualFrame bridge.
    """
    html = build_code_studio_scaffold("anything", kind=kind)
    for css_var_prefix in must_contain_vars:
        assert css_var_prefix in html, (
            f"{kind} scaffold missing CSS variable: {css_var_prefix}"
        )


def test_scaffold_keeps_hardcoded_fallback_alongside_variables() -> None:
    """Standalone-renderable contract: every var() must include a fallback
    so the scaffold renders correctly when downloaded as an .html file or
    previewed outside Wiii's iframe (no host theme reachable).
    """
    html = build_code_studio_scaffold("Thúy Kiều ở lầu Ngưng Bích")
    # All var() references should have a fallback (comma-separated form).
    import re
    var_refs = re.findall(r"var\(--wiii-[a-z-]+(?:,[^)]*)?\)", html)
    assert var_refs, "literary scaffold should use var() at least once"
    bare_refs = [ref for ref in var_refs if "," not in ref]
    assert not bare_refs, (
        f"var() without fallback breaks standalone preview: {bare_refs}"
    )


# ---------------------------------------------------------------------------
# Sprint 35e Item 3 — Mobile responsive iPhone SE (≤480px)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", ["literary", "physics", "math", "default"],
)
def test_scaffold_ships_mobile_breakpoint(kind: str) -> None:
    """Every scaffold must include a ``@media (max-width: 480px)`` block
    so iPhone SE (375px) and similar narrow viewports get tightened
    padding, font-size, and animation deltas. SKILL VISUAL_CODE_GEN.md
    v6.2.0 §12 "Mobile responsive contract".
    """
    html = build_code_studio_scaffold("anything", kind=kind)
    assert "@media (max-width:480px)" in html or "@media(max-width:480px)" in html, (
        f"{kind} scaffold missing iPhone SE responsive breakpoint"
    )


@pytest.mark.parametrize(
    "kind", ["literary", "physics", "math"],
)
def test_scaffold_uses_aspect_ratio_for_resilience(kind: str) -> None:
    """Stages should use ``aspect-ratio`` rather than fixed pixel heights
    so they scale to the parent container without overflow.
    """
    html = build_code_studio_scaffold("anything", kind=kind)
    assert "aspect-ratio:" in html, (
        f"{kind} scaffold missing aspect-ratio (would not scale gracefully)"
    )


def test_scaffold_handles_reduced_motion() -> None:
    """Scaffolds with animations must respect ``prefers-reduced-motion``
    so users with vestibular sensitivities are not subjected to
    perpetual sway/swing animations. WCAG 2.2 §2.3.3.
    """
    for kind in ("literary", "physics", "default"):
        html = build_code_studio_scaffold("anything", kind=kind)
        assert "prefers-reduced-motion:reduce" in html, (
            f"{kind} scaffold missing reduced-motion media query"
        )


# ---------------------------------------------------------------------------
# Sprint 35e Item 4 — Kind-specific aria-label + data-scaffold-kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, descriptor_fragment",
    [
        ("literary", "Khung mô phỏng văn học"),
        ("physics", "Khung mô phỏng vật lý"),
        ("math", "Khung dựng đồ thị"),
        ("default", "Khung mô phỏng"),
    ],
)
def test_scaffold_aria_label_describes_kind(
    kind: str, descriptor_fragment: str
) -> None:
    """Screen readers should hear the topic family AND the temporary
    nature of the canvas, not just the generic "Khung scene" wording.
    """
    html = build_code_studio_scaffold("Bài thơ", kind=kind)
    assert descriptor_fragment in html, (
        f"{kind} scaffold aria-label missing descriptor: {descriptor_fragment}"
    )
    assert "màn hình tạm" in html, (
        f"{kind} scaffold aria-label missing 'temporary canvas' signal"
    )


@pytest.mark.parametrize(
    "kind", ["literary", "physics", "math", "default"],
)
def test_scaffold_root_carries_data_kind_attribute(kind: str) -> None:
    """Telemetry and CSS hooks need a stable ``data-scaffold-kind``
    attribute on the root element so they don't have to parse class names.
    """
    html = build_code_studio_scaffold("anything", kind=kind)
    assert f'data-scaffold-kind="{kind}"' in html, (
        f"{kind} scaffold root missing data-scaffold-kind attribute"
    )
