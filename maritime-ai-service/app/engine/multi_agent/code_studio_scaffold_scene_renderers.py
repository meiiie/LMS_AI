"""Scene and data-band renderers for deterministic Code Studio scaffolds."""

from __future__ import annotations

from collections.abc import Callable
import html
import json
from typing import Any


BuildShell = Callable[..., str]
CommonScriptWrapper = Callable[[str, str, str, str, str, str], str]
ShortTitle = Callable[[Any], str]


def render_scene_scaffold(
    spec: dict[str, Any],
    *,
    build_shell: BuildShell,
    common_script_wrapper: CommonScriptWrapper,
    short_title: ShortTitle,
) -> str:
    """Render the scene primitive without importing the monolithic scaffold."""
    prefix = "wiii-sc"
    title = html.escape(short_title(spec.get("title", "")))
    slider_label = html.escape(spec.get("slider_label", "Thời gian trôi"))
    moments = spec.get("moments", [])
    if not moments:
        moments = [{"key": "Khởi đầu", "quote": "...", "sky_blend": 0.0}]
    first = moments[0]
    canvas_html = (
        f'<canvas id="{prefix}-canvas" class="{prefix}-canvas" width="640" '
        f'height="360" aria-label="Cảnh {title}"></canvas>'
    )
    controls_html = f"""
    <div class="{prefix}-row">
      <label for="{prefix}-slider">{slider_label}</label>
      <input id="{prefix}-slider" class="{prefix}-slider" type="range"
        min="0" max="100" step="1" value="20" aria-label="{slider_label}">
    </div>
    <div class="{prefix}-readout" id="{prefix}-readout" aria-live="polite">
      <strong>{html.escape(first.get('key', ''))}:</strong>
      <em>{html.escape(first.get('quote', ''))}</em>
    </div>
""".strip()
    palettes = [
        # (top, mid, warm, sand) - 4-stop gradient sweeping dusk to dawn.
        ["#1f1c33", "#3b2c4a", "#76506a", "#d2a673"],
        ["#0e1230", "#1f1c33", "#3b2c4a", "#5a4870"],
        ["#080826", "#0e1230", "#1f1c33", "#2c2548"],
        ["#1f1c33", "#5a4870", "#c08a6e", "#f0d4a3"],
    ]
    moments_json = json.dumps(moments, ensure_ascii=False)
    palettes_json = json.dumps(palettes)
    figure_kind_json = json.dumps(str(spec.get("scene_figure", "character")))
    setup_body = f"""
    var moments = {moments_json};
    var palettes = {palettes_json};
    var figureKind = {figure_kind_json};
    function lerp(a, b, t){{ return a + (b - a) * t; }}
    function hexToRgb(h){{
      var m = h.replace('#','');
      return [parseInt(m.slice(0,2),16), parseInt(m.slice(2,4),16), parseInt(m.slice(4,6),16)];
    }}
    function blend(c1, c2, t){{
      var a = hexToRgb(c1), b = hexToRgb(c2);
      return 'rgb(' + Math.round(lerp(a[0],b[0],t)) + ',' + Math.round(lerp(a[1],b[1],t)) + ',' + Math.round(lerp(a[2],b[2],t)) + ')';
    }}
""".strip()
    render_body = """
    var t = parseFloat(slider.value) / 100;
    var seg = t * (moments.length - 1);
    var i = Math.floor(seg);
    var local = seg - i;
    var pa = palettes[Math.min(i, palettes.length - 1)];
    var pb = palettes[Math.min(i + 1, palettes.length - 1)];
    var grad = ctx.createLinearGradient(0, 0, 0, h);
    [0, 0.35, 0.65, 1].forEach(function(stop, idx){
      grad.addColorStop(stop, blend(pa[idx], pb[idx], local));
    });
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = 'rgba(0,0,0,0.32)';
    ctx.fillRect(0, h * 0.78, w, h * 0.22);

    if (figureKind === 'tower'){
      var towerX = w * 0.78;
      var towerW = Math.max(40, w * 0.08);
      var towerH = h * 0.48;
      ctx.fillStyle = 'rgba(255,255,255,0.12)';
      ctx.fillRect(towerX, h * 0.30, towerW, towerH);
      ctx.strokeStyle = 'rgba(255,255,255,0.28)';
      ctx.lineWidth = 1;
      ctx.strokeRect(towerX, h * 0.30, towerW, towerH);
      ctx.beginPath();
      ctx.moveTo(towerX - 6, h * 0.30);
      ctx.lineTo(towerX + towerW / 2, h * 0.22);
      ctx.lineTo(towerX + towerW + 6, h * 0.30);
      ctx.closePath();
      ctx.fillStyle = 'rgba(255,255,255,0.18)';
      ctx.fill();
    }

    var figX = w * 0.46;
    var figY = h * 0.62;
    var sway = Math.sin(elapsed * 0.5) * 3;
    ctx.fillStyle = '#7a4f3a';
    ctx.beginPath();
    ctx.ellipse(figX + sway, figY + 36, 14, 36, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#d4a373';
    ctx.beginPath();
    ctx.arc(figX + sway, figY, 10, 0, Math.PI * 2);
    ctx.fill();

    var ev = local < 0.5 ? moments[i] : moments[Math.min(i + 1, moments.length - 1)];
    readout.innerHTML = '<strong>' + ev.key + ':</strong> <em>' + ev.quote + '</em>';
""".strip()
    slider_handler_body = """
    var t = parseFloat(slider.value) / 100;
    var idx = Math.round(t * (moments.length - 1));
    reportProgress({moment: moments[idx].key}, moments[idx].key);
""".strip()
    script_html = common_script_wrapper(
        f"{prefix}-canvas",
        f"{prefix}-slider",
        f"{prefix}-readout",
        setup_body,
        render_body,
        slider_handler_body,
    )
    return build_shell(
        prefix=prefix,
        spec=spec,
        canvas_html=canvas_html,
        controls_html=controls_html,
        script_html=script_html,
    )


def render_data_band_scaffold(
    spec: dict[str, Any],
    *,
    build_shell: BuildShell,
    common_script_wrapper: CommonScriptWrapper,
    short_title: ShortTitle,
) -> str:
    """Render the generic data-band primitive behind the registry."""
    prefix = "wiii-db"
    title = html.escape(short_title(spec.get("title", "")))
    slider_label = html.escape(spec.get("slider_label", "Tham số chính"))
    smin = float(spec.get("slider_min", 10))
    smax = float(spec.get("slider_max", 100))
    sdef = float(spec.get("slider_default", 50))

    canvas_html = (
        f'<canvas id="{prefix}-canvas" class="{prefix}-canvas" width="640" '
        f'height="360" aria-label="Khung tổng quát cho {title}"></canvas>'
    )
    controls_html = f"""
    <div class="{prefix}-row">
      <label for="{prefix}-slider">{slider_label}</label>
      <input id="{prefix}-slider" class="{prefix}-slider" type="range"
        min="{smin}" max="{smax}" step="1" value="{sdef}" aria-label="{slider_label}">
    </div>
    <div class="{prefix}-readout" id="{prefix}-readout" aria-live="polite">
      <strong>Trạng thái:</strong> Tham số = {int(sdef)}, hệ thống đang ở mức cân bằng.
    </div>
""".strip()
    setup_body = ""
    render_body = """
    ctx.clearRect(0, 0, w, h);
    var param = parseFloat(slider.value);
    var amp = (param / 100) * h * 0.32;
    var freq = 0.012 + (param / 100) * 0.018;

    ctx.strokeStyle = 'rgba(60,40,30,0.08)';
    ctx.lineWidth = 1;
    var step = 32;
    for (var gy = step; gy < h; gy += step){
      ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke();
    }
    ctx.strokeStyle = '#d97757';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    var first = true;
    for (var px = 0; px <= w; px += 2){
      var y = h / 2 + Math.sin(px * freq + elapsed * 1.2) * amp;
      if (first){ ctx.moveTo(px, y); first = false; } else { ctx.lineTo(px, y); }
    }
    ctx.stroke();
    ctx.strokeStyle = 'rgba(60,40,30,0.4)';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();

    readout.innerHTML = '<strong>Trạng thái:</strong> Tham số = ' + param.toFixed(0) +
      ', biên độ ' + amp.toFixed(0) + ' px, tần số ' + (freq * 1000).toFixed(1) + ' mHz.';
""".strip()
    slider_handler_body = """
    reportProgress({param: parseFloat(slider.value)}, 'Tham số = ' + slider.value);
""".strip()
    script_html = common_script_wrapper(
        f"{prefix}-canvas",
        f"{prefix}-slider",
        f"{prefix}-readout",
        setup_body,
        render_body,
        slider_handler_body,
    )
    return build_shell(
        prefix=prefix,
        spec=spec,
        canvas_html=canvas_html,
        controls_html=controls_html,
        script_html=script_html,
    )
