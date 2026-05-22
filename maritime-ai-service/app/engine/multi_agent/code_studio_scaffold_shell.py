"""Shared HTML shell helpers for deterministic Code Studio scaffolds."""

from __future__ import annotations

import html

from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    legacy_kind_for_primitive,
)

_PALETTES = {
    "night_sky": {
        "sky_top": "#02030f", "sky_mid": "#08102a", "sky_bottom": "#1a1f2e",
        "accent": "#fef9e7", "fg": "#e8e1d0", "fg_muted": "rgba(232,225,208,.85)",
    },
    "deep_space": {
        "sky_top": "#0e0530", "sky_mid": "#241750", "sky_bottom": "#5a3088",
        "accent": "#ff86d2", "fg": "#e8d5ff", "fg_muted": "rgba(232,213,255,.85)",
    },
    "warm_dusk": {
        "sky_top": "#1f1c33", "sky_mid": "#3b2c4a", "sky_bottom": "#d2a673",
        "accent": "#ffe5c1", "fg": "#fff8ec", "fg_muted": "rgba(255,248,236,.85)",
    },
    "autumn": {
        "sky_top": "#3a1f0a", "sky_mid": "#7a3a14", "sky_bottom": "#d97744",
        "accent": "#ffba6b", "fg": "#fff0d6", "fg_muted": "rgba(255,240,214,.85)",
    },
    "winter": {
        "sky_top": "#1a2a3f", "sky_mid": "#3e5878", "sky_bottom": "#a3c5e0",
        "accent": "#ffffff", "fg": "#e8f0f8", "fg_muted": "rgba(232,240,248,.85)",
    },
    "spring": {
        "sky_top": "#fff5d6", "sky_mid": "#fbe5a6", "sky_bottom": "#a3d495",
        "accent": "#ff8fa3", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.78)",
    },
    "ocean": {
        "sky_top": "#0a3a5c", "sky_mid": "#1a6b8a", "sky_bottom": "#5fb3c9",
        "accent": "#fff6a3", "fg": "#e3f2f9", "fg_muted": "rgba(227,242,249,.85)",
    },
    "forest": {
        "sky_top": "#0e2a14", "sky_mid": "#2a5a30", "sky_bottom": "#7ba85c",
        "accent": "#ffd66b", "fg": "#dff0d2", "fg_muted": "rgba(223,240,210,.85)",
    },
    "physics_warm": {
        "sky_top": "#fff7e8", "sky_mid": "#f4dfae", "sky_bottom": "#dfa667",
        "accent": "#d97757", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.7)",
    },
    "math_cream": {
        "sky_top": "#fff8f1", "sky_mid": "#fce6c7", "sky_bottom": "#fde9d3",
        "accent": "#d97757", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.7)",
    },
    "historical_dark": {
        "sky_top": "#0e1230", "sky_mid": "#1f1c33", "sky_bottom": "#1a1f2e",
        "accent": "#d97757", "fg": "#e8e1d0", "fg_muted": "rgba(232,225,208,.85)",
    },
    "lab_bright": {
        "sky_top": "#fdf6ef", "sky_mid": "#f9e6c5", "sky_bottom": "#f3dcc4",
        "accent": "#d97757", "fg": "#3a2a1f", "fg_muted": "rgba(58,42,31,.78)",
    },
}


def _short_title(query: str, max_len: int = 60) -> str:
    title = (query or "").strip()
    if len(title) > max_len:
        title = title[:max_len].rstrip() + "…"
    return title or "Khung dựng cảnh"


def _legacy_kind_for(spec: dict) -> str:
    primitive = spec.get("primitive", PRIMITIVE_DATA_BAND)
    return legacy_kind_for_primitive(primitive)


def _aria_label(spec: dict, title: str) -> str:
    legacy = _legacy_kind_for(spec)
    descriptor = {
        "literary": "Khung mô phỏng văn học",
        "physics": "Khung mô phỏng vật lý",
        "math": "Khung dựng đồ thị",
        "history": "Khung mô phỏng lịch sử",
        "celestial": "Khung mô phỏng bầu trời",
        "default": "Khung mô phỏng",
    }.get(legacy, "Khung mô phỏng")
    return (
        f"{descriptor} cho {title} — màn hình tạm, "
        "Wiii sẽ mở rộng khi bạn mô tả thêm chi tiết"
    )


# ============================================================================
# Common HTML/JS helpers shared by every primitive renderer
# ============================================================================


# Kind-specific CSS variable hooks — host theme overrides land via these.
# Each entry maps legacy_kind → list of var declarations the stage CSS
# emits so the iframe can inherit ``--wiii-{kind}-*`` from the host.
# Variable names match Sprint 35e SKILL VISUAL_CODE_GEN.md v6.2.0 §12.
_KIND_VAR_HOOKS: dict[str, list[tuple[str, str]]] = {
    "literary": [
        ("scene-sky-deep", "sky_top"),
        ("scene-sky-mid", "sky_mid"),
        ("scene-fg", "fg"),
    ],
    "physics": [
        ("phys-bg-light", "sky_top"),
        ("phys-fg", "fg"),
    ],
    "math": [
        ("math-bg-light", "sky_top"),
        ("math-fg", "fg"),
        ("math-grid", "fg_muted"),
    ],
    "history": [
        ("history-bg-deep", "sky_top"),
        ("history-fg", "fg"),
    ],
    "celestial": [
        ("celestial-bg-deep", "sky_top"),
        ("celestial-fg", "fg"),
    ],
    "default": [
        ("default-bg-light", "sky_top"),
        ("default-fg", "fg"),
    ],
}


def _common_styles(prefix: str, palette: dict, kind: str = "default") -> str:
    """Shared stage/controls/slider/readout CSS for any primitive.

    ``prefix`` is the unique CSS class prefix (e.g. ``"wiii-cel"`` for
    celestial) so each primitive has its own scope. Hardcoded fallbacks
    pull from ``palette`` so the iframe renders correctly even without
    host theme overrides.

    ``kind`` is the legacy kind label (literary/physics/math/history/
    celestial/default) — used to emit kind-specific CSS variable hooks
    (``var(--wiii-scene-sky-deep, ...)``) so the host theme can override
    via ``InlineVisualFrame.readHostThemeOverrides``.
    """
    sky_top = palette["sky_top"]
    sky_bottom = palette["sky_bottom"]
    accent = palette["accent"]
    fg = palette["fg"]
    fg_muted = palette["fg_muted"]
    # Build kind-specific var hook declarations as `--_local: var(--wiii-{kind}-{slot}, fallback);`
    hooks = _KIND_VAR_HOOKS.get(kind, _KIND_VAR_HOOKS["default"])
    hook_lines = []
    slot_to_value = {
        "sky_top": sky_top, "sky_mid": palette.get("sky_mid", sky_top),
        "sky_bottom": sky_bottom, "fg": fg, "fg_muted": fg_muted, "accent": accent,
    }
    for var_name, slot in hooks:
        hook_lines.append(
            f"  --wiii-_kind-{var_name}: var(--wiii-{var_name}, {slot_to_value.get(slot, sky_top)});"
        )
    hook_block = "\n".join(hook_lines)
    return f"""
.{prefix}-stage{{
{hook_block}
  position:relative;width:100%;max-width:100%;border-radius:18px;overflow:hidden;
  background:{sky_top};
  box-shadow:0 12px 30px rgba(20,24,38,.25);
  font-family:var(--wiii-font-sans,"Inter",system-ui,sans-serif);
  color:{fg};
}}
.{prefix}-canvas{{display:block;width:100%;aspect-ratio:16/9;min-height:240px;}}
.{prefix}-controls{{
  display:flex;flex-direction:column;gap:10px;padding:14px 18px 16px;
  background:linear-gradient(180deg,
    rgba(0,0,0,0) 0%,
    {sky_bottom} 80%);
}}
.{prefix}-row{{display:flex;align-items:center;gap:12px;font-size:12.5px;color:{fg_muted};}}
.{prefix}-row label{{flex:0 0 auto;letter-spacing:.04em;}}
.{prefix}-slider{{
  flex:1;height:4px;-webkit-appearance:none;appearance:none;
  background:rgba(232,225,208,.18);border-radius:2px;outline:none;
}}
.{prefix}-slider::-webkit-slider-thumb{{
  -webkit-appearance:none;appearance:none;width:14px;height:14px;border-radius:50%;
  background:var(--wiii-accent,{accent});border:1px solid rgba(255,255,255,.85);cursor:pointer;
}}
.{prefix}-slider::-moz-range-thumb{{
  width:14px;height:14px;border-radius:50%;background:var(--wiii-accent,{accent});
  border:1px solid rgba(255,255,255,.85);cursor:pointer;
}}
.{prefix}-readout{{font-size:12px;color:{fg};letter-spacing:.02em;line-height:1.5;}}
.{prefix}-readout strong{{color:var(--wiii-accent,{accent});}}
.{prefix}-hint{{
  margin-top:12px;font-size:13px;line-height:1.55;
  color:var(--wiii-text-secondary,#5b4a4a);
  font-family:var(--wiii-font-sans,"Inter",system-ui,sans-serif);
}}
@media (max-width:480px){{
  .{prefix}-stage{{border-radius:14px;}}
  .{prefix}-canvas{{aspect-ratio:4/3;}}
  .{prefix}-controls{{padding:10px 14px 12px;}}
  .{prefix}-hint{{font-size:12px;line-height:1.45;}}
}}
@media (prefers-reduced-motion:reduce){{
  .{prefix}-canvas{{animation:none !important;}}
}}
""".strip()


def _common_script_wrapper(
    canvas_id: str,
    slider_id: str,
    readout_id: str,
    setup_body: str,
    render_body: str,
    slider_handler_body: str,
) -> str:
    """Shared RAF/slider/reduced-motion JS wrapper for every primitive.

    ``setup_body`` runs once before the loop; ``render_body`` runs every
    frame; ``slider_handler_body`` runs on slider input. All run inside
    an IIFE so iframe globals stay clean.
    """
    return f"""
<script>
(function(){{
  var canvas = document.getElementById('{canvas_id}');
  var slider = document.getElementById('{slider_id}');
  var readout = document.getElementById('{readout_id}');
  if (!canvas || !slider || !readout) return;
  var ctx = canvas.getContext('2d');
  var dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  var raf = 0;
  var startedAt = performance.now();

  function ensureCanvasSize(){{
    var w = canvas.clientWidth || 640;
    var h = canvas.clientHeight || 360;
    if (canvas.width !== w * dpr) canvas.width = w * dpr;
    if (canvas.height !== h * dpr) canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {{w: w, h: h}};
  }}

  {setup_body}

  function frame(){{
    var sz = ensureCanvasSize();
    var w = sz.w, h = sz.h;
    var elapsed = (performance.now() - startedAt) / 1000;
    {render_body}
    raf = requestAnimationFrame(frame);
  }}

  function reportProgress(payload, summary){{
    if (window.WiiiVisualBridge && typeof window.WiiiVisualBridge.reportResult === 'function'){{
      try {{
        window.WiiiVisualBridge.reportResult('scaffold_progress', payload || {{}}, summary || '', 'in_progress');
      }} catch (err) {{}}
    }}
  }}

  slider.addEventListener('input', function(){{
    {slider_handler_body}
  }});
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion:reduce)').matches){{
    frame(); cancelAnimationFrame(raf);
  }} else {{
    raf = requestAnimationFrame(frame);
  }}
}})();
</script>
""".strip()


# Legacy kind → second class prefix (Sprint 35e tests expect these stable
# names for tooling/CSS hooks).
_LEGACY_KIND_TO_CLASS_PREFIX: dict[str, str] = {
    "literary": "scene",
    "physics": "phys",
    "math": "math",
    "history": "hist",
    "celestial": "cel",
    "default": "default",
}


_FALLBACK_HINT = (
    "Đây là khung canvas khởi đầu — kéo thanh trượt để thấy hệ thống "
    "phản hồi theo tham số. Cho Wiii biết hiện tượng/dữ liệu/tương tác "
    "cụ thể bạn muốn dựng và mình sẽ thay phần lõi bằng nội dung "
    "đúng chủ đề."
)


def _build_shell(
    *,
    prefix: str,
    spec: dict,
    canvas_html: str,
    controls_html: str,
    script_html: str,
) -> str:
    """Compose stage + canvas + controls + hint + script into final HTML.

    Emits two stage classes: ``wiii-{primitive}-stage`` (for primitive-
    specific styling) AND ``wiii-{kind}-stage`` (for legacy kind-keyed
    tooling/tests). Both reference the same shared CSS rules.
    """
    palette = _PALETTES.get(spec.get("palette", "lab_bright"), _PALETTES["lab_bright"])
    aria = html.escape(_aria_label(spec, _short_title(spec.get("title", ""))))
    legacy_kind = _legacy_kind_for(spec)
    kind_class_prefix = _LEGACY_KIND_TO_CLASS_PREFIX.get(legacy_kind, "default")
    hint_text = spec.get("hint") or _FALLBACK_HINT
    hint_html_escaped = html.escape(hint_text)
    common_css = _common_styles(prefix, palette, kind=legacy_kind)
    # Append a kind-aliased CSS rule so `.wiii-{kind}-stage` selector
    # resolves to the same shared styles. Tests look for the substring
    # `wiii-{kind}-stage` and tooling can hook on either class.
    kind_alias_css = (
        f".wiii-{kind_class_prefix}-stage{{display:contents;}}"
    )
    return f"""
<style>
{common_css}
{kind_alias_css}
</style>
<div class="{prefix}-stage wiii-{kind_class_prefix}-stage" data-scaffold-kind="{legacy_kind}" data-scaffold-primitive="{spec.get('primitive')}" role="region" aria-label="{aria}">
  {canvas_html}
  <div class="{prefix}-controls">
    {controls_html}
  </div>
</div>
<div class="{prefix}-hint">{hint_html_escaped}</div>
{script_html}
""".strip()
