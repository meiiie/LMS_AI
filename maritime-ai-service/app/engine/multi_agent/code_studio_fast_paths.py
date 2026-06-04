"""Recipe-backed Code Studio fast paths extracted from graph.py."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.code_studio_context import (
    _infer_artifact_fast_path_title,
    _infer_colreg_fast_path_title,
    _infer_pendulum_fast_path_title,
    _should_use_artifact_code_studio_fast_path,
    _should_use_colreg_code_studio_fast_path,
    _should_use_pendulum_code_studio_fast_path,
)
from app.engine.multi_agent.code_studio_event_payloads import (
    sanitize_code_studio_tool_call_args_for_stream,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_event_sanitizer import sanitize_tool_result_for_event
from app.engine.multi_agent.visual_events import (
    _collect_active_visual_session_ids,
    _emit_visual_commit_events,
    _maybe_emit_visual_event,
    _summarize_tool_result_for_stream,
)
from app.engine.tools.invocation import get_tool_by_name, invoke_tool_with_runtime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CodeStudioFastPathRecipe:
    """Typed recipe contract for one audited Code Studio fast path."""

    code_html: str
    title: str
    call_id_prefix: str
    response: str
    thinking_content: str

    def tool_args(self) -> dict[str, str]:
        return {"code_html": self.code_html, "title": self.title}


@dataclass(frozen=True, slots=True)
class CodeStudioFastPathResult:
    """Typed result emitted by an audited Code Studio fast path."""

    response: str
    thinking_content: str
    tool_call_events: list[dict[str, Any]]
    tools_used: list[dict[str, Any]]
    fast_path: str


_PENDULUM_FAST_PATH_HTML = """
<div class="pendulum-prototype">
  <style>
    :root { --bg: #0f172a; --fg: #e2e8f0; --accent: #38bdf8; --surface: #1e293b; --border: #475569; --muted: #94a3b8; }
    @media (prefers-color-scheme: light) {
      :root { --bg: #f8fafc; --fg: #0f172a; --accent: #0284c7; --surface: #ffffff; --border: #cbd5e1; --muted: #64748b; }
    }
    .pendulum-prototype { box-sizing: border-box; display: grid; gap: 14px; width: min(100%, 760px); margin: 0 auto; padding: 16px; border: 1px solid var(--border); border-radius: 14px; background: var(--bg); color: var(--fg); font-family: system-ui, sans-serif; }
    .pendulum-prototype *, .pendulum-prototype *::before, .pendulum-prototype *::after { box-sizing: inherit; }
    .pendulum-prototype h3 { margin: 0; font-size: 18px; line-height: 1.25; }
    .pendulum-prototype .hint { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.5; }
    .pendulum-prototype canvas { display: block; width: 100%; height: min(48vw, 320px); min-height: 220px; border: 1px solid var(--border); border-radius: 12px; background: color-mix(in srgb, var(--surface) 78%, var(--bg)); }
    .pendulum-prototype .controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .pendulum-prototype label { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }
    .pendulum-prototype input[type="range"] { width: 100%; accent-color: var(--accent); }
    .pendulum-prototype .readout { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .pendulum-prototype .readout span { min-height: 40px; padding: 9px 10px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--fg); font-variant-numeric: tabular-nums; }
    .pendulum-prototype button { min-height: 38px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--fg); font-weight: 650; cursor: pointer; }
    @media (max-width: 640px) {
      .pendulum-prototype .controls, .pendulum-prototype .readout { grid-template-columns: 1fr; }
    }
  </style>
  <h3>Mô phỏng con lắc đơn</h3>
  <p class="hint">Kéo trực tiếp trên canvas hoặc chỉnh trọng lực và ma sát để thấy chu kỳ thay đổi theo thời gian.</p>
  <canvas id="pendulumCanvas" width="760" height="320" aria-label="Mô phỏng con lắc đơn có kéo thả"></canvas>
  <div class="controls">
    <label>Trọng lực
      <input id="gravity" type="range" min="4" max="16" step="0.1" value="9.8">
    </label>
    <label>Ma sát
      <input id="damping" type="range" min="0" max="0.12" step="0.005" value="0.035">
    </label>
  </div>
  <div class="readout" id="readout" aria-live="polite">
    <span>Góc: <strong id="angleValue">0°</strong></span>
    <span>Vận tốc: <strong id="omegaValue">0.00 rad/s</strong></span>
    <span>Trạng thái: <strong id="stateValue">đang chạy</strong></span>
  </div>
  <button id="resetPendulum" type="button">Reset</button>
  <script>
    (() => {
      const canvas = document.getElementById('pendulumCanvas');
      const ctx = canvas.getContext('2d');
      const gravityInput = document.getElementById('gravity');
      const dampingInput = document.getElementById('damping');
      const angleValue = document.getElementById('angleValue');
      const omegaValue = document.getElementById('omegaValue');
      const stateValue = document.getElementById('stateValue');
      const resetButton = document.getElementById('resetPendulum');
      const state = { theta: 0.55, omega: 0, length: 130, dragging: false, lastTime: performance.now() };
      function report(kind, payload, summary, status) {
        if (window.WiiiVisualBridge && typeof window.WiiiVisualBridge.reportResult === 'function') {
          window.WiiiVisualBridge.reportResult(kind, payload, summary, status);
        }
      }
      function resize() {
        const rect = canvas.getBoundingClientRect();
        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.max(320, Math.round(rect.width * ratio));
        canvas.height = Math.max(220, Math.round(rect.height * ratio));
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      }
      function bobPosition() {
        const w = canvas.clientWidth;
        const anchor = { x: w / 2, y: 42 };
        return {
          anchor,
          x: anchor.x + Math.sin(state.theta) * state.length,
          y: anchor.y + Math.cos(state.theta) * state.length,
        };
      }
      function draw() {
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        const { anchor, x, y } = bobPosition();
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = getComputedStyle(canvas).color || '#e2e8f0';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(anchor.x, anchor.y);
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.fillStyle = '#f59e0b';
        ctx.beginPath();
        ctx.arc(x, y, 18, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#38bdf8';
        ctx.beginPath();
        ctx.arc(anchor.x, anchor.y, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = 'rgba(56, 189, 248, 0.22)';
        ctx.fillRect(0, h - 34, w, 2);
      }
      function updateReadout() {
        angleValue.textContent = `${Math.round(state.theta * 180 / Math.PI)}°`;
        omegaValue.textContent = `${state.omega.toFixed(2)} rad/s`;
        stateValue.textContent = state.dragging ? 'đang kéo' : 'đang chạy';
      }
      function tick(now) {
        const deltaTime = Math.min((now - state.lastTime) / 1000, 0.05);
        state.lastTime = now;
        if (!state.dragging) {
          const gravity = Number(gravityInput.value);
          const damping = Number(dampingInput.value);
          const acceleration = -(gravity / state.length) * 92 * Math.sin(state.theta) - damping * state.omega;
          state.omega += acceleration * deltaTime;
          state.theta += state.omega * deltaTime;
        }
        draw();
        updateReadout();
        requestAnimationFrame(tick);
      }
      function setFromPointer(event) {
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        const anchor = bobPosition().anchor;
        state.theta = Math.atan2(x - anchor.x, y - anchor.y);
        state.omega = 0;
        report('pendulum_drag', { theta: state.theta }, 'Người dùng kéo con lắc', 'running');
      }
      canvas.addEventListener('pointerdown', (event) => { state.dragging = true; canvas.setPointerCapture(event.pointerId); setFromPointer(event); });
      canvas.addEventListener('pointermove', (event) => { if (state.dragging) setFromPointer(event); });
      canvas.addEventListener('pointerup', (event) => { state.dragging = false; canvas.releasePointerCapture(event.pointerId); report('pendulum_release', { theta: state.theta }, 'Con lắc tiếp tục dao động', 'completed'); });
      resetButton.addEventListener('click', () => { state.theta = 0.55; state.omega = 0; report('pendulum_reset', { theta: state.theta }, 'Reset mô phỏng con lắc', 'completed'); });
      gravityInput.addEventListener('input', () => report('pendulum_gravity', { gravity: Number(gravityInput.value) }, 'Đổi trọng lực', 'running'));
      dampingInput.addEventListener('input', () => report('pendulum_damping', { damping: Number(dampingInput.value) }, 'Đổi ma sát', 'running'));
      new ResizeObserver(resize).observe(canvas);
      resize();
      requestAnimationFrame(tick);
    })();
  </script>
</div>
""".strip()

_COLREG_RULE15_FAST_PATH_HTML = """
<div class="colreg-rule15-sim">
  <style>
    :root { --bg: #07111f; --fg: #e2e8f0; --accent: #38bdf8; --surface: #122033; --border: #38516f; --give: #f97316; --stand: #22c55e; --muted: #9fb3c8; }
    @media (prefers-color-scheme: light) {
      :root { --bg: #f8fafc; --fg: #0f172a; --accent: #0369a1; --surface: #ffffff; --border: #cbd5e1; --give: #c2410c; --stand: #15803d; --muted: #475569; }
    }
    .colreg-rule15-sim { box-sizing: border-box; width: min(100%, 820px); margin: 0 auto; padding: 16px; border: 1px solid var(--border); border-radius: 14px; background: var(--bg); color: var(--fg); font-family: system-ui, sans-serif; }
    .colreg-rule15-sim *, .colreg-rule15-sim *::before, .colreg-rule15-sim *::after { box-sizing: inherit; }
    .colreg-rule15-sim h3 { margin: 0 0 6px; font-size: 18px; line-height: 1.25; }
    .colreg-rule15-sim p { margin: 0; color: var(--muted); line-height: 1.5; }
    .colreg-rule15-sim canvas { display: block; width: 100%; height: min(54vw, 380px); min-height: 260px; margin-top: 14px; border: 1px solid var(--border); border-radius: 12px; background: radial-gradient(circle at 50% 45%, rgba(56,189,248,.16), transparent 36%), color-mix(in srgb, var(--surface) 74%, var(--bg)); }
    .colreg-rule15-sim .controls { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
    .colreg-rule15-sim label { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }
    .colreg-rule15-sim input[type="range"] { width: 100%; accent-color: var(--accent); }
    .colreg-rule15-sim .readout { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
    .colreg-rule15-sim .readout span { min-height: 48px; padding: 9px 10px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--fg); font-variant-numeric: tabular-nums; }
    .colreg-rule15-sim button { min-height: 38px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--fg); font-weight: 650; cursor: pointer; }
    @media (max-width: 720px) {
      .colreg-rule15-sim .controls, .colreg-rule15-sim .readout { grid-template-columns: 1fr; }
    }
  </style>
  <h3>COLREG Rule 15: tình huống cắt hướng</h3>
  <p>Tàu màu cam thấy tàu xanh ở mạn phải nên là give-way vessel; kéo tốc độ hoặc mức tránh va để xem CPA đổi ra sao.</p>
  <canvas id="colregCanvas" width="820" height="380" aria-label="Mô phỏng COLREG Rule 15 bằng canvas"></canvas>
  <div class="controls">
    <label>Tốc độ tàu give-way
      <input id="giveSpeed" type="range" min="0.45" max="1.45" step="0.05" value="0.9">
    </label>
    <label>Tốc độ tàu stand-on
      <input id="standSpeed" type="range" min="0.45" max="1.45" step="0.05" value="0.85">
    </label>
    <label>Mức đổi hướng tránh va
      <input id="avoidLevel" type="range" min="0" max="34" step="1" value="18">
    </label>
  </div>
  <div class="readout" id="readout" aria-live="polite">
    <span>CPA: <strong id="cpaValue">0.00 NM</strong></span>
    <span>TCPA: <strong id="tcpaValue">0.0 phút</strong></span>
    <span>Hành động: <strong id="actionValue">nhường đường</strong></span>
  </div>
  <button id="resetColreg" type="button">Reset tình huống</button>
  <script>
    (() => {
      const canvas = document.getElementById('colregCanvas');
      const ctx = canvas.getContext('2d');
      const giveSpeed = document.getElementById('giveSpeed');
      const standSpeed = document.getElementById('standSpeed');
      const avoidLevel = document.getElementById('avoidLevel');
      const cpaValue = document.getElementById('cpaValue');
      const tcpaValue = document.getElementById('tcpaValue');
      const actionValue = document.getElementById('actionValue');
      const resetButton = document.getElementById('resetColreg');
      const state = { t: 0, lastTime: performance.now(), scale: 1 };
      function report(kind, payload, summary, status) {
        if (window.WiiiVisualBridge && typeof window.WiiiVisualBridge.reportResult === 'function') {
          window.WiiiVisualBridge.reportResult(kind, payload, summary, status);
        }
      }
      function resize() {
        const rect = canvas.getBoundingClientRect();
        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.max(360, Math.round(rect.width * ratio));
        canvas.height = Math.max(260, Math.round(rect.height * ratio));
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      }
      function vectorFrom(angleDeg, speed) {
        const angle = angleDeg * Math.PI / 180;
        return { x: Math.cos(angle) * speed, y: Math.sin(angle) * speed };
      }
      function scenario() {
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        const give = { x: w * 0.25, y: h * 0.78 };
        const stand = { x: w * 0.74, y: h * 0.27 };
        const turn = Number(avoidLevel.value);
        const vg = vectorFrom(-34 - turn, Number(giveSpeed.value) * 72);
        const vs = vectorFrom(132, Number(standSpeed.value) * 72);
        return { w, h, give, stand, vg, vs };
      }
      function closestPoint() {
        const { give, stand, vg, vs } = scenario();
        const rx = stand.x - give.x;
        const ry = stand.y - give.y;
        const vx = vs.x - vg.x;
        const vy = vs.y - vg.y;
        const vv = Math.max(1, vx * vx + vy * vy);
        const tcpa = Math.max(0, -((rx * vx + ry * vy) / vv));
        const dx = rx + vx * tcpa;
        const dy = ry + vy * tcpa;
        const cpaPx = Math.sqrt(dx * dx + dy * dy);
        return { tcpa, cpaNm: cpaPx / 95 };
      }
      function drawShip(x, y, heading, color, label) {
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(heading);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(20, 0);
        ctx.lineTo(-16, -11);
        ctx.lineTo(-10, 0);
        ctx.lineTo(-16, 11);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = 'rgba(255,255,255,.92)';
        ctx.font = '12px system-ui';
        ctx.fillText(label, -30, -18);
        ctx.restore();
      }
      function drawTrack(start, velocity, color) {
        ctx.strokeStyle = color;
        ctx.setLineDash([8, 7]);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(start.x + velocity.x * 2.8, start.y + velocity.y * 2.8);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      function render() {
        const { w, h, give, stand, vg, vs } = scenario();
        const motion = (Math.sin(state.t * 0.7) + 1) * 0.5;
        const gx = give.x + vg.x * motion;
        const gy = give.y + vg.y * motion;
        const sx = stand.x + vs.x * motion;
        const sy = stand.y + vs.y * motion;
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = 'rgba(56,189,248,.22)';
        ctx.lineWidth = 1;
        for (let x = 40; x < w; x += 40) {
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, h);
          ctx.stroke();
        }
        for (let y = 40; y < h; y += 40) {
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(w, y);
          ctx.stroke();
        }
        drawTrack(give, vg, 'rgba(249,115,22,.55)');
        drawTrack(stand, vs, 'rgba(34,197,94,.55)');
        drawShip(gx, gy, Math.atan2(vg.y, vg.x), '#f97316', 'Give-way');
        drawShip(sx, sy, Math.atan2(vs.y, vs.x), '#22c55e', 'Stand-on');
        ctx.strokeStyle = 'rgba(226,232,240,.55)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(gx, gy);
        ctx.lineTo(sx, sy);
        ctx.stroke();
      }
      function updateReadout() {
        const closest = closestPoint();
        cpaValue.textContent = `${closest.cpaNm.toFixed(2)} NM`;
        tcpaValue.textContent = `${(closest.tcpa * 2.4).toFixed(1)} phút`;
        actionValue.textContent = closest.cpaNm < 1 ? 'đổi hướng sớm hơn' : 'nhường đường rõ';
      }
      function tick(now) {
        const deltaTime = Math.min((now - state.lastTime) / 1000, 0.05);
        state.lastTime = now;
        state.t += deltaTime;
        render();
        updateReadout();
        requestAnimationFrame(tick);
      }
      function onControlChange() {
        const closest = closestPoint();
        report('colreg_rule15_adjust', {
          giveSpeed: Number(giveSpeed.value),
          standSpeed: Number(standSpeed.value),
          avoidLevel: Number(avoidLevel.value),
          cpaNm: Number(closest.cpaNm.toFixed(2)),
        }, 'Điều chỉnh tình huống Rule 15', 'running');
      }
      giveSpeed.addEventListener('input', onControlChange);
      standSpeed.addEventListener('input', onControlChange);
      avoidLevel.addEventListener('input', onControlChange);
      resetButton.addEventListener('click', () => {
        state.t = 0;
        giveSpeed.value = '0.9';
        standSpeed.value = '0.85';
        avoidLevel.value = '18';
        report('colreg_rule15_reset', { reset: true }, 'Reset mô phỏng Rule 15', 'completed');
      });
      new ResizeObserver(resize).observe(canvas);
      resize();
      requestAnimationFrame(tick);
      report('colreg_rule15_ready', { rule: 15 }, 'Mô phỏng Rule 15 đã sẵn sàng', 'ready');
    })();
  </script>
</div>
""".strip()

_ARTIFACT_FAST_PATH_HTML = """
<section style="font-family:system-ui,sans-serif;padding:24px;border:1px solid #e2e8f0;border-radius:18px;background:#fff8f1;max-width:520px">
  <span style="display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:#ffedd5;color:#9a3412;font-weight:600">Khung Artifact</span>
  <h2 style="margin:14px 0 10px;font-size:24px;color:#7c2d12">Mini HTML app đã sẵn sàng</h2>
  <p style="margin:0;color:#78350f;line-height:1.6">Đây là bộ khung embeddable gọn nhẹ để bạn preview ngay và patch tiếp trong Code Studio hoặc Artifact lane.</p>
  <button id="cta" type="button">Thử tương tác</button>
  <p id="state" aria-live="polite" style="margin:12px 0 0">Sẵn sàng nhúng</p>
</section>
<script>
const state=document.getElementById('state');document.getElementById('cta')?.addEventListener('click',()=>{state.textContent='Đã nhấn một lần - khung artifact đang hoạt động';window.WiiiVisualBridge?.reportResult?.('artifact',{clicked:true},'Mini HTML app đã sẵn sàng','completed')});
</script>
""".strip()


def _contains_visual_payload_result(result: Any) -> bool:
    if not isinstance(result, str):
        return False
    stripped = result.strip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except Exception:
        return False
    return isinstance(payload, dict) and bool(payload.get("visual_session_id")) and "fallback_html" in payload


def _build_recipe(query: str, state: AgentState) -> CodeStudioFastPathRecipe | None:
    if _should_use_pendulum_code_studio_fast_path(query, state):
        return CodeStudioFastPathRecipe(
            code_html=_PENDULUM_FAST_PATH_HTML,
            title=_infer_pendulum_fast_path_title(query, state),
            call_id_prefix="fast_pendulum",
            response=(
                "Mình đã dùng Code Studio để tạo mô phỏng con lắc inline. "
                "Bạn có thể kéo quả nặng, xem preview, và patch tiếp trên cùng session này."
            ),
            thinking_content=(
                "Mình đi theo scaffold con lắc host-owned để ưu tiên preview ổn định, patch được, "
                "và giữ cùng session Code Studio."
            ),
        )
    if _should_use_colreg_code_studio_fast_path(query, state):
        return CodeStudioFastPathRecipe(
            code_html=_COLREG_RULE15_FAST_PATH_HTML,
            title=_infer_colreg_fast_path_title(query, state),
            call_id_prefix="fast_colreg15",
            response=(
                "Mình đã dùng Code Studio để mô phỏng tình huống cắt hướng theo Quy tắc 15 COLREGs. "
                "Bạn có thể xem canvas, điều chỉnh mức tránh va, và tiếp tục patch trên cùng session này."
            ),
            thinking_content=(
                "Mình chọn scaffold canvas cho COLREG để khởi động nhanh, có telemetry rõ ràng, "
                "và để bạn nhìn thấy ngay give-way / stand-on thay vì chỉ đọc lý thuyết."
            ),
        )
    if _should_use_artifact_code_studio_fast_path(query, state):
        return CodeStudioFastPathRecipe(
            code_html=_ARTIFACT_FAST_PATH_HTML,
            title=_infer_artifact_fast_path_title(query, state),
            call_id_prefix="fast_artifact",
            response=(
                "Mình đã dùng Code Studio để tạo bộ khung mini HTML app embeddable. "
                "Bạn có thể mở preview ngay, rồi mở thành Artifact để chỉnh sửa sau."
            ),
            thinking_content=(
                "Mình đi bằng scaffold artifact nhẹ để bạn có một bộ khung HTML tự chứa ngay lập tức, "
                "rồi mới patch và mở rộng tiếp theo nhu cầu thật."
            ),
        )
    return None


async def execute_code_studio_fast_path(
    *,
    state: AgentState,
    query: str,
    tools: list,
    push_event: Callable[[dict[str, Any]], Awaitable[None]],
    runtime_context_base: Any,
    derive_code_stream_session_id: Callable[..., str],
    sanitize_code_studio_response: Callable[[str, list[dict[str, Any]] | None, AgentState | None], str],
) -> CodeStudioFastPathResult | None:
    matched = get_tool_by_name(tools, "tool_create_visual_code")
    if not matched:
        return None

    recipe = _build_recipe(query, state)
    if not recipe:
        return None

    tool_name = str(getattr(matched, "name", "") or getattr(matched, "__name__", "") or "tool_create_visual_code")
    tool_args = recipe.tool_args()
    tool_call_id = f"{recipe.call_id_prefix}_{uuid.uuid4().hex[:10]}"

    try:
        result = await invoke_tool_with_runtime(
            matched,
            tool_args,
            tool_name=tool_name,
            runtime_context_base=runtime_context_base,
            tool_call_id=tool_call_id,
            query_snippet=query[:100],
            prefer_async=False,
            run_sync_in_thread=True,
        )
    except Exception as exc:
        logger.warning("[CODE_STUDIO] Recipe fast path failed (%s): %s", recipe.call_id_prefix, exc)
        return None

    if isinstance(result, str) and result.strip().lower().startswith("error:"):
        logger.debug(
            "[CODE_STUDIO] Recipe fast path returned tool error (%s): %s",
            recipe.call_id_prefix,
            result[:180],
        )
        return None
    if not _contains_visual_payload_result(result):
        logger.debug(
            "[CODE_STUDIO] Recipe fast path did not return a visual payload (%s): %s",
            recipe.call_id_prefix,
            str(result)[:180],
        )
        return None

    public_tool_args = sanitize_code_studio_tool_call_args_for_stream(
        tool_name,
        tool_args,
    )
    tool_call_events: list[dict[str, Any]] = [
        {"type": "call", "name": tool_name, "args": public_tool_args, "id": tool_call_id},
    ]

    await push_event({
        "type": "tool_call",
        "content": {
            "name": tool_name,
            "args": public_tool_args,
            "id": tool_call_id,
        },
        "node": "code_studio_agent",
    })
    await push_event({
        "type": "tool_result",
        "content": {
            "name": tool_name,
            "result": _summarize_tool_result_for_stream(tool_name, result),
            "id": tool_call_id,
        },
        "node": "code_studio_agent",
    })

    emitted_visual_session_ids, _disposed_visual_session_ids = await _maybe_emit_visual_event(
        push_event=push_event,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        result=result,
        node="code_studio_agent",
        tool_call_events=tool_call_events,
        previous_visual_session_ids=_collect_active_visual_session_ids(state),
        code_session_id_override=derive_code_stream_session_id(
            runtime_context_base=runtime_context_base,
            state=state,
        ),
    )

    tool_call_events.append({
        "type": "result",
        "name": tool_name,
        "result": sanitize_tool_result_for_event(result),
        "id": tool_call_id,
    })

    await _emit_visual_commit_events(
        push_event=push_event,
        node="code_studio_agent",
        visual_session_ids=emitted_visual_session_ids,
        tool_call_events=tool_call_events,
    )

    matched_name = (
        getattr(matched, "name", None)
        or getattr(matched, "__name__", None)
        or "tool_create_visual_code"
    )
    return CodeStudioFastPathResult(
        response=sanitize_code_studio_response(recipe.response, tool_call_events, state),
        thinking_content=recipe.thinking_content,
        tool_call_events=tool_call_events,
        # Presenter contract: tools_used must be a list of dicts with at
        # least a "name" key (see chat_response_presenter.py). Storing the
        # raw LangChain Tool object here used to crash the pendulum
        # fast-path turn with "'Tool' object has no attribute 'get'".
        tools_used=[{"name": str(matched_name)}],
        fast_path=recipe.call_id_prefix,
    )
