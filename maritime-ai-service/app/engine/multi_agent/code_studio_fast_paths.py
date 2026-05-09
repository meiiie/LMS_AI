"""Recipe-backed Code Studio fast paths extracted from graph.py."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.code_studio_context import (
    _infer_artifact_fast_path_title,
    _infer_colreg_fast_path_title,
    _infer_pendulum_fast_path_title,
    _should_use_artifact_code_studio_fast_path,
    _should_use_colreg_code_studio_fast_path,
    _should_use_pendulum_code_studio_fast_path,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.visual_events import (
    _collect_active_visual_session_ids,
    _emit_visual_commit_events,
    _maybe_emit_visual_event,
    _summarize_tool_result_for_stream,
)
from app.engine.tools.invocation import get_tool_by_name, invoke_tool_with_runtime

logger = logging.getLogger(__name__)

_PENDULUM_FAST_PATH_HTML = """
<div class="pendulum-prototype">
  <style>
    .pendulum-prototype { font-family: system-ui, sans-serif; background: #f8fafc; border: 1px solid #d8e2f0; border-radius: 16px; padding: 16px; color: #0f172a; }
    .pendulum-prototype h3 { margin: 0 0 8px; font-size: 18px; }
    .pendulum-prototype .hint { margin: 0; color: #475569; font-size: 14px; }
    .pendulum-prototype .scene { margin-top: 16px; height: 180px; position: relative; display: flex; align-items: flex-start; justify-content: center; }
    .pendulum-prototype .rod { width: 4px; height: 120px; background: linear-gradient(180deg, #64748b, #0f172a); transform-origin: top center; transform: rotate(18deg); border-radius: 999px; position: relative; }
    .pendulum-prototype .bob { width: 32px; height: 32px; border-radius: 999px; background: radial-gradient(circle at 35% 35%, #fde68a, #f97316); position: absolute; bottom: -16px; left: 50%; transform: translateX(-50%); box-shadow: 0 8px 18px rgba(249, 115, 22, 0.28); }
  </style>
  <h3>Mô phỏng con lắc đơn</h3>
  <p class="hint">Bộ khung preview đã sẵn sàng để patch tiếp ngay trong Code Studio.</p>
  <div class="scene">
    <div class="rod"><div class="bob"></div></div>
  </div>
</div>
""".strip()

_COLREG_RULE15_FAST_PATH_HTML = """
<style>
  :root { --ship-a: var(--red); --ship-b: var(--green); }
  .container { display: flex; flex-direction: column; align-items: center; gap: 16px; font-family: sans-serif; }
  .scene { width: 100%; max-width: 500px; aspect-ratio: 1; background: #f0f5ff; border-radius: 12px; position: relative; overflow: hidden; cursor: crosshair; }
  .ship { position: absolute; width: 40px; height: 60px; transition: transform 0.1s linear; display: flex; align-items: center; justify-content: center; font-size: 24px; }
  .ship-a { color: var(--ship-a); }
  .ship-b { color: var(--ship-b); }
  .label { position: absolute; font-size: 12px; background: rgba(255,255,255,0.9); padding: 2px 6px; border-radius: 999px; }
  .controls { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; }
  .readout { display: grid; gap: 8px; width: 100%; max-width: 500px; }
</style>
<div class="container">
  <div class="scene">
    <div class="ship ship-a" style="left:28%;top:60%;transform:rotate(-22deg)">⛴</div>
    <div class="ship ship-b" style="left:62%;top:28%;transform:rotate(130deg)">🚢</div>
    <div class="label" style="left:18%;top:75%">Give-way</div>
    <div class="label" style="left:64%;top:14%">Stand-on</div>
  </div>
  <div class="controls">
    <button type="button">Chạy mô phỏng</button>
    <button type="button">Đổi mức CPA</button>
  </div>
  <div class="readout">
    <strong>Rule 15 - Crossing Situation</strong>
    <span>Tàu nhìn thấy tàu kia ở mạn phải phải chủ động nhường đường.</span>
  </div>
</div>
""".strip()

_ARTIFACT_FAST_PATH_HTML = """
<section style="font-family:system-ui,sans-serif;padding:24px;border:1px solid #e2e8f0;border-radius:18px;background:#fff8f1;max-width:520px">
  <span style="display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:#ffedd5;color:#9a3412;font-weight:600">Artifact scaffold</span>
  <h2 style="margin:14px 0 10px;font-size:24px;color:#7c2d12">Mini HTML app ready</h2>
  <p style="margin:0;color:#78350f;line-height:1.6">Đây là bộ khung embeddable gọn nhẹ để bạn preview ngay và patch tiếp trong Code Studio hoặc Artifact lane.</p>
  <button id="cta" type="button">Thử tương tác</button>
  <p id="state" aria-live="polite" style="margin:12px 0 0">Ready to embed</p>
</section>
<script>
const state=document.getElementById('state');document.getElementById('cta')?.addEventListener('click',()=>{state.textContent='Clicked once - artifact scaffold is alive';window.WiiiVisualBridge?.reportResult?.('artifact',{clicked:true},'Mini HTML app ready','completed')});
</script>
""".strip()


def _build_recipe(query: str, state: AgentState) -> dict[str, str] | None:
    if _should_use_pendulum_code_studio_fast_path(query, state):
        return {
            "code_html": _PENDULUM_FAST_PATH_HTML,
            "title": _infer_pendulum_fast_path_title(query, state),
            "call_id_prefix": "fast_pendulum",
            "response": (
                "Mình đã dùng Code Studio để tạo mô phỏng con lắc inline. "
                "Bạn có thể kéo quả nặng, xem preview, và patch tiếp trên cùng session này."
            ),
            "thinking_content": (
                "Mình đi theo scaffold con lắc host-owned để ưu tiên preview ổn định, patch được, "
                "và giữ cùng session Code Studio."
            ),
        }
    if _should_use_colreg_code_studio_fast_path(query, state):
        return {
            "code_html": _COLREG_RULE15_FAST_PATH_HTML,
            "title": _infer_colreg_fast_path_title(query, state),
            "call_id_prefix": "fast_colreg15",
            "response": (
                "Mình đã dùng Code Studio để mô phỏng tình huống cắt hướng theo Quy tắc 15 COLREGs. "
                "Bạn có thể xem canvas, điều chỉnh mức tránh va, và tiếp tục patch trên cùng session này."
            ),
            "thinking_content": (
                "Mình chọn scaffold canvas cho COLREG để khởi động nhanh, có telemetry rõ ràng, "
                "và để bạn nhìn thấy ngay give-way / stand-on thay vì chỉ đọc lý thuyết."
            ),
        }
    if _should_use_artifact_code_studio_fast_path(query, state):
        return {
            "code_html": _ARTIFACT_FAST_PATH_HTML,
            "title": _infer_artifact_fast_path_title(query, state),
            "call_id_prefix": "fast_artifact",
            "response": (
                "Mình đã dùng Code Studio để tạo bộ khung mini HTML app embeddable. "
                "Bạn có thể mở preview ngay, rồi mở thành Artifact để chỉnh sửa sau."
            ),
            "thinking_content": (
                "Mình đi bằng scaffold artifact nhẹ để bạn có một bộ khung HTML tự chứa ngay lập tức, "
                "rồi mới patch và mở rộng tiếp theo nhu cầu thật."
            ),
        }
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
) -> dict[str, Any] | None:
    matched = get_tool_by_name(tools, "tool_create_visual_code")
    if not matched:
        return None

    recipe = _build_recipe(query, state)
    if not recipe:
        return None

    tool_name = str(getattr(matched, "name", "") or getattr(matched, "__name__", "") or "tool_create_visual_code")
    tool_args = {"code_html": recipe["code_html"], "title": recipe["title"]}
    tool_call_id = f"{recipe['call_id_prefix']}_{uuid.uuid4().hex[:10]}"

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
        logger.warning("[CODE_STUDIO] Recipe fast path failed (%s): %s", recipe["call_id_prefix"], exc)
        return None

    if isinstance(result, str) and result.strip().lower().startswith("error:"):
        logger.debug(
            "[CODE_STUDIO] Recipe fast path returned tool error (%s): %s",
            recipe["call_id_prefix"],
            result[:180],
        )
        return None

    tool_call_events: list[dict[str, Any]] = [
        {"type": "call", "name": tool_name, "args": tool_args, "id": tool_call_id},
    ]

    await push_event({
        "type": "tool_call",
        "content": {"name": tool_name, "args": tool_args, "id": tool_call_id},
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
        "result": str(result),
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
    return {
        "response": sanitize_code_studio_response(recipe["response"], tool_call_events, state),
        "thinking_content": recipe["thinking_content"],
        "tool_call_events": tool_call_events,
        # Presenter contract: tools_used must be a list of dicts with at
        # least a "name" key (see chat_response_presenter.py). Storing the
        # raw LangChain Tool object here used to crash the pendulum
        # fast-path turn with "'Tool' object has no attribute 'get'".
        "tools_used": [{"name": str(matched_name)}],
        "fast_path": recipe["call_id_prefix"],
    }
