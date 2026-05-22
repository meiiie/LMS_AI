import logging
import re

from app.engine.tools.visual_html_builders import _wrap_html
from app.engine.tools.visual_ai_slop import check_ai_slop_patterns
from app.engine.tools.visual_scaffolds import (
    build_scaffold,
    detect_scaffold,
)
from app.engine.tools.runtime_context import get_current_tool_runtime_context
from app.engine.tools.visual_runtime_metadata import (
    _runtime_metadata_text_impl,
    _runtime_preferred_render_surface_impl,
    _runtime_visual_user_query_impl,
)

logger = logging.getLogger(__name__)


def _get_runtime_metadata() -> dict:
    runtime = get_current_tool_runtime_context()
    if runtime and isinstance(runtime.metadata, dict):
        return runtime.metadata
    return {}


def _runtime_metadata_text(key: str, default: str = "") -> str:
    return _runtime_metadata_text_impl(key, default, _get_runtime_metadata)


def resolve_code_html_impl(code_html: str, visual_type: str, title: str, spec: dict) -> str | None:
    _ = visual_type, spec
    raw = code_html.strip() if isinstance(code_html, str) else ""
    if not raw:
        return None
    from app.core.config import get_settings

    if not getattr(get_settings(), "enable_llm_code_gen_visuals", False):
        logger.info("code_html provided but enable_llm_code_gen_visuals=False, ignoring")
        return None
    if raw.lstrip().lower().startswith("<!doctype") or raw.lstrip().lower().startswith("<html"):
        return raw
    css_parts = []
    body_content = raw
    style_pattern = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
    for match in style_pattern.finditer(raw):
        css_parts.append(match.group(1))
    body_content = style_pattern.sub("", body_content).strip()
    return _wrap_html("\n".join(css_parts), body_content, title)


def validate_code_studio_output_impl(
    raw_html: str,
    *,
    requested_visual_type: str,
    studio_lane: str,
    artifact_kind: str,
    quality_profile: str,
) -> str | None:
    lowered = raw_html.lower()
    high_severity_slop = [
        violation
        for violation in check_ai_slop_patterns(raw_html)
        if violation.severity == "high"
    ]
    if high_severity_slop:
        details = "\n".join(
            f"- {violation.rule}: {violation.message}"
            for violation in high_severity_slop[:3]
        )
        return (
            "Error: Code Studio output chua dat bar UI/UX truoc preview. "
            "Hay sua cac dau hieu AI slop high-severity sau:\n"
            f"{details}\n\n"
            "Dung icon/SVG thay emoji trong UI chrome, tranh hero gradient tim-xanh, "
            "va giu visual tap trung vao state/controls/readout that."
        )

    chart_like = requested_visual_type == "chart" or artifact_kind == "chart_widget"
    uses_chart_runtime = any(
        token in lowered
        for token in ("<svg", "<canvas", "chart.js", "new chart(", "plotly", "echarts", "apexcharts", "vega", "recharts", "d3.", "viewbox")
    )
    looks_like_handmade_div_chart = "chart-container" in lowered and (
        "bar-group" in lowered or "bar-wrapper" in lowered or 'class="bar"' in lowered or "class='bar'" in lowered
    )
    if chart_like and looks_like_handmade_div_chart and not uses_chart_runtime:
        return (
            "Error: chart/data visual nay dang di vao Code Studio theo kieu demo thu cong "
            "(div bars / CSS-only chart). Hay route qua chart_runtime/tool_generate_visual, "
            "hoac neu that su can code widget thi dung SVG/Canvas/Chart.js voi axis, legend, "
            "units, source, va takeaway ro rang."
        )

    if requested_visual_type == "simulation" and quality_profile == "premium":
        preferred_surface = _runtime_preferred_render_surface_impl(_runtime_metadata_text) or "canvas"
        has_canvas_surface = any(token in lowered for token in ("<canvas", "getcontext("))
        has_render_surface = any(
            token in lowered
            for token in ("<canvas", "<svg", "getcontext(", "viewbox", 'id="sim"', "id='sim'", "simulation-stage", "sim-stage")
        )
        parameter_control_count = sum(lowered.count(token) for token in ('type="range"', "type='range'", 'type="number"', "type='number'", "<select"))
        has_live_readout = any(
            token in lowered
            for token in ("innertext", "textcontent", "aria-live", "readout", "telemetry", "velocity", "angle", "omega", "theta", "acceleration", "gravity", "friction", "thoi gian", "goc lech", "van toc", "trang thai", "status")
        )
        has_state_engine = any(
            token in lowered
            for token in ("requestanimationframe", "setinterval(", "performance.now", "deltatime", "delta_time", "time_step", "timestep", "velocity", "acceleration", "gravity", "friction", "omega", "theta")
        )
        has_feedback_bridge = any(
            token in lowered for token in ("window.wiiivisualbridge.reportresult", "wiiivisualbridge.reportresult", "reportresult(")
        )
        button_count = lowered.count("<button")
        if preferred_surface == "canvas" and not has_canvas_surface:
            return (
                "Error: premium simulation nay dang chua dung Canvas-first runtime. "
                "Hay dung canvas + render loop + state model ro rang, hoac de runtime "
                "nang cap sang scaffold canvas phu hop truoc khi preview."
            )
        if (
            not has_render_surface
            or parameter_control_count < 1
            or not has_live_readout
            or not has_state_engine
            or not has_feedback_bridge
        ):
            if button_count <= 2 and parameter_control_count == 0 and not has_render_surface:
                return (
                    "Error: premium simulation nay van qua giong demo minh hoa (vai div + nut bam) "
                    "va chua dat bar cua Code Studio. Hay nang cap thanh mot mo phong that su: "
                    "co render surface ro rang (canvas/svg), it nhat mot dieu khien tham so "
                    "(slider/number/select), readout song (goc/van toc/trang thai), va state/time "
                    "engine ro rang truoc khi preview."
                )
            if not has_feedback_bridge:
                return (
                    "Error: premium simulation can feedback bridge de Wiii biet nguoi dung "
                    "da tuong tac gi. Hay goi window.WiiiVisualBridge.reportResult(...) "
                    "cho cac hanh dong chinh hoac de runtime nang cap sang scaffold phu hop."
                )
            return (
                "Error: premium simulation can runtime giau hon truoc khi preview. "
                "Hay bo sung render surface ro rang, parameter controls, readout song, "
                "va state/time engine thay vi mot canh minh hoa script qua don gian."
            )

    if studio_lane == "widget":
        has_interaction = any(token in lowered for token in ("<button", "<input", "<select", "onclick=", "addeventlistener", 'type="range"', "type='range'"))
        if has_interaction and "reportresult" not in lowered:
            return (
                "Error: widget lane yeu cau feedback bridge. Hay goi "
                "window.WiiiVisualBridge.reportResult(...) khi user tuong tac xong "
                "de Wiii co the nho va phan hoi o luot sau."
            )
    return None


def postprocess_visual_html_impl(raw: str) -> str:
    if "--bg" not in raw and "--accent" not in raw and "<style" in raw.lower():
        css_vars = (
            ":root {\n"
            "  --bg: #0f172a; --fg: #e2e8f0; --accent: #38bdf8;\n"
            "  --surface: #1e293b; --border: #475569; --text-secondary: #94a3b8;\n"
            "}\n"
            "@media (prefers-color-scheme: light) {\n"
            "  :root { --bg: #f8fafc; --fg: #0f172a; --accent: #0284c7; --surface: #fff; --border: #cbd5e1; --text-secondary: #64748b; }\n"
            "}\n"
        )
        raw = re.sub(r"(<style[^>]*>)", r"\1\n" + css_vars, raw, count=1)
        raw = raw.replace("background: #050505", "background: var(--bg)")
        raw = raw.replace("background: #000", "background: var(--bg)")
        raw = raw.replace("background: #1a1a1a", "background: var(--bg)")
        raw = raw.replace("background: black", "background: var(--bg)")
        raw = raw.replace("color: white", "color: var(--fg)")
        raw = raw.replace("color: #fff", "color: var(--fg)")
        raw = raw.replace("color: #ffffff", "color: var(--fg)")
    if "STATE MODEL" not in raw and "RENDER SURFACE" not in raw:
        has_canvas = "<canvas" in raw.lower()
        has_svg = "<svg" in raw.lower()
        surface = "Canvas 2D" if has_canvas else "SVG" if has_svg else "HTML"
        raw = (
            "<!--\n"
            "  STATE MODEL: [auto-detected]\n"
            f"  RENDER SURFACE: {surface}\n"
            "  CONTROLS: [see interactive elements below]\n"
            "  READOUTS: [see output displays below]\n"
            "  FEEDBACK: WiiiVisualBridge.reportResult\n"
            "-->\n"
        ) + raw
    return raw


def quality_score_visual_output_impl(raw_html: str, visual_type: str = "") -> tuple[int, list[str]]:
    score = 0
    deficiencies: list[str] = []
    html_lower = raw_html.lower()
    is_simulation = visual_type in ("simulation", "physics", "animation")
    has_canvas = "<canvas" in html_lower
    has_svg = "<svg" in html_lower
    if "--bg" in raw_html and "--accent" in raw_html:
        score += 1
    else:
        deficiencies.append("Thieu CSS variables. Them :root { --bg: #0f172a; --fg: #e2e8f0; --accent: #38bdf8; --surface: #1e293b; --border: #475569; }")
    if "prefers-color-scheme" in raw_html:
        score += 1
    else:
        deficiencies.append("Thieu dark/light mode. Them @media (prefers-color-scheme: light) { :root { --bg: #f8fafc; --fg: #0f172a; } }")
    if is_simulation and has_canvas:
        score += 1
    elif not is_simulation and (has_canvas or has_svg or "<div" in html_lower):
        score += 1
    else:
        surface = "Canvas voi getContext('2d')" if is_simulation else "SVG hoac HTML"
        deficiencies.append(f"Thieu render surface phu hop. Simulation can {surface}.")
    range_count = html_lower.count('type="range"') + html_lower.count("type='range'")
    button_count = html_lower.count("<button")
    input_count = html_lower.count("<input")
    if range_count >= 2 or (range_count >= 1 and button_count >= 1) or input_count >= 2:
        score += 1
    else:
        deficiencies.append("Thieu controls tuong tac. Them it nhat 2 slider (type='range') hoac buttons de user dieu chinh tham so.")
    has_readout = "readout" in html_lower or "aria-live" in raw_html or html_lower.count("<span id=") >= 2
    if has_readout:
        score += 1
    else:
        deficiencies.append("Thieu readouts song. Them cac phan tu hien thi gia tri tinh toan real-time (dung <span> voi aria-live='polite').")
    has_raf = "requestanimationframe" in html_lower
    has_delta = "deltatime" in html_lower or "dt " in raw_html or "delta" in html_lower
    if is_simulation:
        if has_raf and has_delta:
            score += 1
        elif has_raf:
            score += 1
            if not has_delta:
                deficiencies.append("Them deltaTime cho physics frame-rate-independent: const dt = Math.min((now - lastTime) / 1000, 0.1);")
        else:
            deficiencies.append("Thieu animation loop. Dung requestAnimationFrame voi deltaTime cho simulation muot 60fps.")
    else:
        score += 1
    if "wiiivisualbridge" in html_lower:
        score += 1
    else:
        deficiencies.append("Thieu WiiiVisualBridge. Them: function report(k,p,s,st){window.WiiiVisualBridge?.reportResult?.(k,p,s,st);}")
    line_count = raw_html.count("\n") + 1
    min_lines = 150 if is_simulation else 80
    if line_count >= min_lines:
        score += 1
    else:
        deficiencies.append(f"Code qua ngan ({line_count} dong). Simulation chat luong thuong co {min_lines}+ dong voi physics engine, controls, readouts day du.")
    has_placeholder = any(marker in html_lower for marker in ["todo", "lorem ipsum", "placeholder", "// ...", "/* ... */"])
    if not has_placeholder:
        score += 1
    else:
        deficiencies.append("Code chua hoan chinh — con chua TODO/placeholder. Viet day du, khong de trong.")
    has_responsive = "grid" in html_lower or ("flex" in html_lower and ("@media" in raw_html or "max-width" in html_lower))
    if has_responsive:
        score += 1
    else:
        deficiencies.append("Thieu responsive layout. Dung CSS Grid hoac Flexbox voi @media (max-width: 768px) de ho tro man hinh nho.")
    return score, deficiencies


def maybe_upgrade_code_studio_output_impl(
    raw_html: str,
    *,
    title: str,
    subtitle: str,
    requested_visual_type: str,
    studio_lane: str,
    artifact_kind: str,
    quality_profile: str,
) -> str:
    quality_error = validate_code_studio_output_impl(
        raw_html,
        requested_visual_type=requested_visual_type,
        studio_lane=studio_lane,
        artifact_kind=artifact_kind,
        quality_profile=quality_profile,
    )
    if not quality_error:
        return raw_html
    runtime_visual_user_query = _runtime_visual_user_query_impl(_runtime_metadata_text)

    # Try scaffold detection — supports pendulum, simulation, quiz, dashboard
    scaffold_kind = detect_scaffold(
        query=runtime_visual_user_query,
        visual_type=requested_visual_type,
        raw_html=raw_html,
    )
    if scaffold_kind:
        try:
            upgraded = build_scaffold(scaffold_kind, title, subtitle, runtime_visual_user_query)
            if not validate_code_studio_output_impl(
                upgraded,
                requested_visual_type=requested_visual_type,
                studio_lane=studio_lane,
                artifact_kind=artifact_kind,
                quality_profile=quality_profile,
            ):
                return upgraded
        except Exception as exc:
            logger.debug("[SCAFFOLD] Failed to build %s scaffold: %s", scaffold_kind, exc)

    return raw_html


def resolve_fallback_html_impl(
    visual_type: str,
    spec: dict,
    title: str,
    builder_output: str | None,
) -> str | None:
    _ = visual_type, title
    html = builder_output
    if not html:
        for key in ("html", "markup", "custom_html", "template_html", "app_html"):
            value = spec.get(key)
            if isinstance(value, str) and value.strip():
                html = value
                break
    if html:
        html = postprocess_visual_html_impl(html)
    return html
