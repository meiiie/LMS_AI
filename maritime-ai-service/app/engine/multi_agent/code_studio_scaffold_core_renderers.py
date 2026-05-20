"""Core primitive renderers for deterministic Code Studio scaffolds."""

from __future__ import annotations

from collections.abc import Callable
import html
import json
from typing import Any


BuildShell = Callable[..., str]
CommonScriptWrapper = Callable[[str, str, str, str, str, str], str]
ShortTitle = Callable[[Any], str]
PaletteMap = dict[str, dict[str, str]]


def render_particle_field_scaffold(
    spec: dict[str, Any],
    *,
    build_shell: BuildShell,
    common_script_wrapper: CommonScriptWrapper,
    short_title: ShortTitle,
    palettes: PaletteMap,
) -> str:
    prefix = "wiii-pf"
    title = html.escape(short_title(spec.get("title", "")))
    palette = palettes.get(spec.get("palette", "night_sky"))
    count_min = int(spec.get("particle_count_min", 20))
    count_max = int(spec.get("particle_count_max", 400))
    count_default = int(spec.get("particle_count_default", 180))
    label = spec.get("particle_label", "ngôi sao")
    slider_label = html.escape(spec.get("slider_label", "Số ngôi sao"))
    readout_lead = html.escape(spec.get("readout_lead", "Bầu trời"))
    readout_phrase = html.escape(spec.get("readout_phrase", "đang lung linh"))
    particle_color = spec.get("particle_color", palette["accent"])
    drift = spec.get("drift_direction", "twinkle")
    extra_layers = spec.get("extra_layers", [])

    canvas_html = (
        f'<canvas id="{prefix}-canvas" class="{prefix}-canvas" width="640" '
        f'height="360" aria-label="Khung hạt cho {title}"></canvas>'
    )
    controls_html = f"""
    <div class="{prefix}-row">
      <label for="{prefix}-slider">{slider_label}</label>
      <input id="{prefix}-slider" class="{prefix}-slider" type="range"
        min="{count_min}" max="{count_max}" step="1" value="{count_default}"
        aria-label="{slider_label}">
    </div>
    <div class="{prefix}-readout" id="{prefix}-readout" aria-live="polite">
      <strong>{readout_lead}:</strong> {count_default} {html.escape(label)} {readout_phrase}.
    </div>
""".strip()
    setup_body = """
    var particles = [];
    function rebuild(count){
      particles = [];
      for (var i = 0; i < count; i++){
        particles.push({
          x: Math.random(),
          y: Math.random() * 0.85,
          size: 0.4 + Math.random() * 1.6,
          speed: 0.5 + Math.random() * 1.8,
          phase: Math.random() * Math.PI * 2,
          driftY: 0.05 + Math.random() * 0.18
        });
      }
    }
    rebuild(parseInt(slider.value, 10));
""".strip()

    moon_layer = ""
    if "moon" in extra_layers:
        moon_layer = """
    var moonX = w * 0.78;
    var moonY = h * 0.22;
    var moonR = Math.min(w, h) * 0.06;
    var mg = ctx.createRadialGradient(moonX - moonR*0.3, moonY - moonR*0.3, moonR*0.2, moonX, moonY, moonR);
    mg.addColorStop(0, '#fff8d6');
    mg.addColorStop(1, 'rgba(255,248,214,0.05)');
    ctx.fillStyle = mg;
    ctx.beginPath(); ctx.arc(moonX, moonY, moonR, 0, Math.PI * 2); ctx.fill();
""".strip()
    milky_layer = ""
    if "milky_way" in extra_layers:
        milky_layer = """
    var bandY = h * 0.55;
    ctx.fillStyle = 'rgba(120,90,180,0.06)';
    ctx.beginPath();
    for (var bx = 0; bx <= w; bx += 4){
      var by = bandY + Math.sin(bx * 0.012 + elapsed * 0.25) * 24;
      if (bx === 0) ctx.moveTo(bx, by - 30); else ctx.lineTo(bx, by - 30);
    }
    for (var bx2 = w; bx2 >= 0; bx2 -= 4){
      var by2 = bandY + Math.sin(bx2 * 0.012 + elapsed * 0.25) * 24;
      ctx.lineTo(bx2, by2 + 30);
    }
    ctx.closePath(); ctx.fill();
""".strip()

    if drift == "down":
        drift_update = "p.y = (p.y + p.driftY * 0.005) % 0.85;"
    elif drift == "down_fast":
        drift_update = "p.y = (p.y + p.driftY * 0.02) % 0.85;"
    elif drift == "float":
        drift_update = (
            "p.x = (p.x + Math.cos(elapsed * p.speed * 0.4 + p.phase) * 0.0015) % 1;"
            " p.y = (p.y + Math.sin(elapsed * p.speed * 0.4 + p.phase) * 0.0015) % 0.85;"
        )
    else:
        drift_update = ""

    sky_top = palette["sky_top"]
    sky_mid = palette["sky_mid"]
    sky_bottom = palette["sky_bottom"]

    render_body = f"""
    var grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, '{sky_top}');
    grad.addColorStop(0.55, '{sky_mid}');
    grad.addColorStop(1, '{sky_bottom}');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
    {milky_layer}
    {moon_layer}
    for (var i = 0; i < particles.length; i++){{
      var p = particles[i];
      var twinkle = 0.55 + 0.45 * Math.sin(p.phase + elapsed * p.speed);
      ctx.globalAlpha = twinkle;
      ctx.fillStyle = '{particle_color}';
      ctx.beginPath();
      ctx.arc(p.x * w, p.y * h, p.size, 0, Math.PI * 2);
      ctx.fill();
      {drift_update}
    }}
    ctx.globalAlpha = 1;
""".strip()

    slider_handler_body = f"""
    rebuild(parseInt(slider.value, 10));
    readout.innerHTML = '<strong>{readout_lead}:</strong> ' + slider.value + ' {html.escape(label)} {readout_phrase}.';
    reportProgress({{count: parseInt(slider.value, 10)}}, slider.value + ' {html.escape(label)}');
""".strip()

    script_html = common_script_wrapper(
        f"{prefix}-canvas", f"{prefix}-slider", f"{prefix}-readout",
        setup_body, render_body, slider_handler_body,
    )
    return build_shell(prefix=prefix, spec=spec, canvas_html=canvas_html,
                        controls_html=controls_html, script_html=script_html)


def render_oscillation_scaffold(
    spec: dict[str, Any],
    *,
    build_shell: BuildShell,
    common_script_wrapper: CommonScriptWrapper,
    short_title: ShortTitle,
    palettes: PaletteMap,
) -> str:
    prefix = "wiii-osc"
    title = html.escape(short_title(spec.get("title", "")))
    slider_label = html.escape(spec.get("slider_label", "Góc lệch ban đầu"))
    smin = float(spec.get("slider_min", 5))
    smax = float(spec.get("slider_max", 60))
    sdef = float(spec.get("slider_default", 30))
    sunit = html.escape(spec.get("slider_unit", "°"))

    canvas_html = (
        f'<canvas id="{prefix}-canvas" class="{prefix}-canvas" width="640" '
        f'height="360" aria-label="Khung dao động cho {title}"></canvas>'
    )
    controls_html = f"""
    <div class="{prefix}-row">
      <label for="{prefix}-slider">{slider_label}</label>
      <input id="{prefix}-slider" class="{prefix}-slider" type="range"
        min="{smin}" max="{smax}" step="1" value="{sdef}" aria-label="{slider_label}">
    </div>
    <div class="{prefix}-readout" id="{prefix}-readout" aria-live="polite">
      <strong>Trạng thái:</strong> Góc {sdef}{sunit}, vận tốc đang dao động theo thời gian.
    </div>
""".strip()
    setup_body = """
    var theta0Deg = parseFloat(slider.value);
    var omega = 1.6;
    var t0 = performance.now();
""".strip()
    render_body = """
    ctx.clearRect(0, 0, w, h);
    var t = (performance.now() - t0) / 1000;
    var theta = (theta0Deg * Math.PI / 180) * Math.cos(omega * t);
    var velocity = -(theta0Deg * Math.PI / 180) * omega * Math.sin(omega * t);

    var pivotX = w / 2;
    var pivotY = h * 0.18;
    var rodLen = h * 0.55;
    var bobX = pivotX + rodLen * Math.sin(theta);
    var bobY = pivotY + rodLen * Math.cos(theta);

    ctx.strokeStyle = 'rgba(58,42,31,0.25)';
    ctx.beginPath();
    ctx.moveTo(0, pivotY);
    ctx.lineTo(w, pivotY);
    ctx.stroke();

    ctx.fillStyle = '#3a2a1f';
    ctx.beginPath();
    ctx.arc(pivotX, pivotY, 6, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = '#3a2a1f';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(pivotX, pivotY);
    ctx.lineTo(bobX, bobY);
    ctx.stroke();

    var grad = ctx.createRadialGradient(bobX - 6, bobY - 6, 4, bobX, bobY, 22);
    grad.addColorStop(0, '#ffe2bd');
    grad.addColorStop(1, '#d97757');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(bobX, bobY, 18, 0, Math.PI * 2);
    ctx.fill();

    readout.innerHTML = '<strong>Trạng thái:</strong> Góc ' +
      (theta * 180 / Math.PI).toFixed(1) + '°, vận tốc ' +
      velocity.toFixed(2) + ' rad/s.';
""".strip()
    slider_handler_body = """
    theta0Deg = parseFloat(slider.value);
    t0 = performance.now();
    reportProgress({theta0_deg: theta0Deg}, 'Góc ' + theta0Deg + '°');
""".strip()
    script_html = common_script_wrapper(
        f"{prefix}-canvas", f"{prefix}-slider", f"{prefix}-readout",
        setup_body, render_body, slider_handler_body,
    )
    return build_shell(prefix=prefix, spec=spec, canvas_html=canvas_html,
                        controls_html=controls_html, script_html=script_html)


def render_function_plot_scaffold(
    spec: dict[str, Any],
    *,
    build_shell: BuildShell,
    common_script_wrapper: CommonScriptWrapper,
    short_title: ShortTitle,
    palettes: PaletteMap,
) -> str:
    prefix = "wiii-fp"
    title = html.escape(short_title(spec.get("title", "")))
    slider_label = html.escape(spec.get("slider_label", "Vị trí điểm x"))
    smin = float(spec.get("slider_min", -50))
    smax = float(spec.get("slider_max", 50))
    sdef = float(spec.get("slider_default", 10))
    expr = spec.get("function_expression", "x*x")
    label_vi = html.escape(spec.get("function_label_vi", "y = x²"))

    canvas_html = (
        f'<canvas id="{prefix}-canvas" class="{prefix}-canvas" width="640" '
        f'height="360" aria-label="Đồ thị {title}"></canvas>'
    )
    controls_html = f"""
    <div class="{prefix}-row">
      <label for="{prefix}-slider">{slider_label}</label>
      <input id="{prefix}-slider" class="{prefix}-slider" type="range"
        min="{smin}" max="{smax}" step="1" value="{sdef}" aria-label="{slider_label}">
    </div>
    <div class="{prefix}-readout" id="{prefix}-readout" aria-live="polite">
      <strong>{label_vi}:</strong> Tại x = {sdef/10:.1f}, giá trị f(x) = {(sdef/10)*(sdef/10):.2f}.
    </div>
""".strip()
    setup_body = f"""
    function f(x){{ return {expr}; }}
""".strip()
    render_body = f"""
    ctx.clearRect(0, 0, w, h);
    var cx = w / 2, cy = h * 0.7;
    var unitX = w / 12, unitY = h / 8;
    var step = 32;
    ctx.strokeStyle = 'rgba(60,40,30,0.07)';
    ctx.lineWidth = 1;
    for (var gx = step; gx < w; gx += step){{
      ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke();
    }}
    for (var gy = step; gy < h; gy += step){{
      ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke();
    }}
    ctx.strokeStyle = '#3a2a1f';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();

    ctx.strokeStyle = '#d97757';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    var first = true;
    for (var px = 0; px <= w; px += 2){{
      var x = (px - cx) / unitX;
      var y = f(x);
      var py = cy - y * unitY;
      if (first){{ ctx.moveTo(px, py); first = false; }} else {{ ctx.lineTo(px, py); }}
    }}
    ctx.stroke();

    var slx = parseFloat(slider.value) / 10;
    var sly = f(slx);
    var sx = cx + slx * unitX;
    var sy = cy - sly * unitY;
    ctx.fillStyle = '#d97757';
    ctx.beginPath(); ctx.arc(sx, sy, 6, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = 'rgba(217,119,87,0.5)';
    ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx, cy); ctx.stroke();
    ctx.setLineDash([]);

    readout.innerHTML = '<strong>{label_vi}:</strong> Tại x = ' + slx.toFixed(1) +
      ', giá trị f(x) = ' + sly.toFixed(2) + '.';
""".strip()
    slider_handler_body = """
    var slx = parseFloat(slider.value) / 10;
    reportProgress({x: slx, fx: f(slx)}, 'x = ' + slx.toFixed(1));
""".strip()
    script_html = common_script_wrapper(
        f"{prefix}-canvas", f"{prefix}-slider", f"{prefix}-readout",
        setup_body, render_body, slider_handler_body,
    )
    return build_shell(prefix=prefix, spec=spec, canvas_html=canvas_html,
                        controls_html=controls_html, script_html=script_html)


def render_timeline_scaffold(
    spec: dict[str, Any],
    *,
    build_shell: BuildShell,
    common_script_wrapper: CommonScriptWrapper,
    short_title: ShortTitle,
    palettes: PaletteMap,
) -> str:
    prefix = "wiii-tl"
    title = html.escape(short_title(spec.get("title", "")))
    slider_label = html.escape(spec.get("slider_label", "Năm"))
    events = spec.get("events", [])
    if not events:
        events = [{"year": 0, "title": "Khởi đầu", "text": "Bối cảnh."}]

    first = events[0]
    canvas_html = (
        f'<canvas id="{prefix}-canvas" class="{prefix}-canvas" width="640" '
        f'height="360" aria-label="Dòng thời gian {title}"></canvas>'
    )
    controls_html = f"""
    <div class="{prefix}-row">
      <label for="{prefix}-slider">{slider_label}</label>
      <input id="{prefix}-slider" class="{prefix}-slider" type="range"
        min="0" max="100" step="1" value="20" aria-label="{slider_label}">
    </div>
    <div class="{prefix}-readout" id="{prefix}-readout" aria-live="polite">
      <strong>{html.escape(str(first.get('year', '')))} — {html.escape(first.get('title', ''))}:</strong>
      {html.escape(first.get('text', ''))}
    </div>
""".strip()
    events_json = json.dumps(events, ensure_ascii=False)
    setup_body = f"""
    var events = {events_json};
""".strip()
    render_body = """
    var grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, '#0e1230');
    grad.addColorStop(1, '#1a1f2e');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    var t = parseFloat(slider.value) / 100;
    var seg = t * (events.length - 1);
    var i = Math.floor(seg);
    var local = seg - i;
    var current = events[i];
    var next = events[Math.min(i + 1, events.length - 1)];

    ctx.strokeStyle = 'rgba(232,225,208,0.16)';
    ctx.lineWidth = 1;
    var trackY = h * 0.72;
    ctx.beginPath();
    ctx.moveTo(40, trackY); ctx.lineTo(w - 40, trackY);
    ctx.stroke();

    events.forEach(function(ev, idx){
      var x = 40 + (w - 80) * (idx / Math.max(1, events.length - 1));
      ctx.fillStyle = 'rgba(232,225,208,0.4)';
      ctx.beginPath(); ctx.arc(x, trackY, 4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = 'rgba(232,225,208,0.55)';
      ctx.font = '10px ' + (getComputedStyle(canvas).fontFamily || 'Inter, sans-serif');
      ctx.fillText(String(ev.year), x - 14, trackY + 18);
    });

    var px = 40 + (w - 80) * t;
    var pulse = 0.55 + 0.45 * Math.sin(elapsed * 2);
    ctx.fillStyle = '#d97757';
    ctx.globalAlpha = pulse;
    ctx.beginPath(); ctx.arc(px, trackY, 9, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;

    var radius = Math.min(w, h) * 0.18 + Math.sin(elapsed * 0.8) * 4;
    ctx.strokeStyle = 'rgba(217,119,87,0.35)';
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(w * 0.32, h * 0.36, radius, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(w * 0.68, h * 0.42, radius * 0.78, 0, Math.PI * 2); ctx.stroke();

    ctx.fillStyle = 'rgba(232,225,208,0.86)';
    ctx.font = '13px ' + (getComputedStyle(canvas).fontFamily || 'Inter, sans-serif');
    ctx.fillText(current.year + ' — ' + current.title, 40, 38);

    var ev = local < 0.5 ? current : next;
    readout.innerHTML = '<strong>' + ev.year + ' — ' + ev.title + ':</strong> ' + ev.text;
""".strip()
    slider_handler_body = """
    var t = parseFloat(slider.value) / 100;
    var idx = Math.round(t * (events.length - 1));
    var ev = events[idx];
    reportProgress({year: ev.year, title: ev.title}, ev.year + ' — ' + ev.title);
""".strip()
    script_html = common_script_wrapper(
        f"{prefix}-canvas", f"{prefix}-slider", f"{prefix}-readout",
        setup_body, render_body, slider_handler_body,
    )
    return build_shell(prefix=prefix, spec=spec, canvas_html=canvas_html,
                        controls_html=controls_html, script_html=script_html)
