"""Visual event emission helpers for multi-agent graph.

Extracted from graph.py — handles telemetry, visual/host-action events,
code studio event emission, and visual commit lifecycle.
"""

from __future__ import annotations

from app.core.config import settings
from app.engine.context.host_action_result_bridge import (
    parse_host_action_request_result,
)
from app.engine.multi_agent.direct_reasoning import _DIRECT_HOST_ACTION_PREFIX
from app.engine.multi_agent.direct_tool_sources import (
    extract_source_infos_from_tool_result,
)
from app.engine.multi_agent.state import AgentState
from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload
from typing import Any, Optional
import asyncio
import json
import logging
import unicodedata
import uuid

logger = logging.getLogger(__name__)


def _log_visual_telemetry(event_name: str, **fields: object) -> None:
    if fields:
        logger.info("[VISUAL_TELEMETRY] %s %s", event_name, json.dumps(fields, ensure_ascii=False, sort_keys=True))
    else:
        logger.info("[VISUAL_TELEMETRY] %s", event_name)


def _fold_for_stream_compare(value: str) -> str:
    normalized = value.replace("đ", "d").replace("Đ", "D")
    return (
        unicodedata.normalize("NFD", normalized)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _is_weather_tool_for_stream(tool_name: str) -> bool:
    normalized = str(tool_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return (
        normalized in {"tool_current_weather", "current_weather"}
        or "current_weather" in normalized
        or normalized.endswith("_weather")
    )


def _truncate_stream_summary(value: str, limit: int = 180) -> str:
    if len(value) <= limit:
        return value
    sliced = value[:limit]
    last_space = sliced.rfind(" ")
    if last_space > 80:
        sliced = sliced[:last_space]
    return f"{sliced.strip()}..."


def _summarize_weather_result_for_stream(result: object) -> str:
    compact = " ".join(str(result or "").split())
    if not compact:
        return "Chưa có dữ liệu thời tiết từ tool."

    folded = _fold_for_stream_compare(compact)
    if "chua co ket noi thoi tiet truc tiep" in folded:
        return "Chưa có kết nối thời tiết trực tiếp."
    if (
        "ban muon xem nhiet do" in folded
        or "thanh pho nao" in folded
        or "can them dia diem" in folded
    ):
        return "Cần thêm địa điểm để tra thời tiết."
    if (
        "chua lay duoc thoi tiet" in folded
        or "khong co du lieu thoi tiet" in folded
    ):
        return "Chưa lấy được thời tiết hiện tại."

    return _truncate_stream_summary(compact)


def _summarize_tool_result_for_stream(tool_name: str, result: object) -> str:
    """Keep SSE tool_result concise for structured payload tools."""
    try:
        from app.engine.tools.visual_tools import parse_visual_payloads

        payloads = parse_visual_payloads(result)
        if payloads:
            if len(payloads) == 1:
                return f"Minh họa đã sẵn sàng: {payloads[0].title}"
            group_title = payloads[0].title
            return f"Nhóm minh họa đã sẵn sàng: {group_title} và {len(payloads) - 1} figure liên kết"
    except Exception:
        pass
    try:
        if str(tool_name).startswith(_DIRECT_HOST_ACTION_PREFIX):
            parsed = json.loads(str(result or "{}"))
            if parsed.get("status") == "action_requested":
                action_name = str(parsed.get("action") or "").strip()
                request_id = str(parsed.get("request_id") or "").strip()
                if action_name and request_id:
                    return f"Đã gửi host action `{action_name}` ({request_id})"
    except Exception:
        pass
    lowered_tool = str(tool_name or "").strip().lower()
    if _is_weather_tool_for_stream(lowered_tool):
        return _summarize_weather_result_for_stream(result)
    if any(token in lowered_tool for token in ("web_search", "search_news", "search_legal", "search_maritime")):
        result_str = str(result or "")
        sources = extract_source_infos_from_tool_result(lowered_tool, result)
        domains: list[str] = []
        for source in sources:
            url = str(source.get("url") or "")
            if not url:
                continue
            try:
                from urllib.parse import urlparse

                domain = urlparse(url).netloc.replace("www.", "")
            except Exception:  # noqa: BLE001
                continue
            if domain and domain not in domains:
                domains.append(domain)
        if sources:
            top = ", ".join(domains[:3])
            extra = f" +{len(domains) - 3}" if len(domains) > 3 else ""
            return f"Tìm được {len(sources)} nguồn: {top}{extra}"
        # No URLs detected → check for "Không tìm thấy" or empty
        if "không tìm thấy" in result_str.lower():
            return "Chưa tìm được kết quả phù hợp — sẽ thử cách khác."
        return "Đã kéo thêm vài nguồn để kiểm chéo."
    if "knowledge_search" in lowered_tool:
        return "Đã rà lại phần tri thức liên quan."
    if "fetch_url" in lowered_tool:
        # Show source domain when fetching deep content
        import re as _re
        result_str = str(result or "")
        url_match = _re.search(r"#\s+(https?://[^\s\n]+)", result_str)
        if url_match:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url_match.group(1)).netloc.replace("www.", "")
                # Estimate length of extracted markdown
                content_len = len(result_str)
                kb = content_len / 1024
                return f"Đã đọc chi tiết từ {domain} (~{kb:.1f}KB)"
            except Exception:  # noqa: BLE001
                pass
        return "Đã đọc chi tiết URL."
    if any(token in lowered_tool for token in ("chart", "visual")):
        return "Phần nhìn đang sẵn sàng."
    compact = " ".join(str(result or "").split())
    lowered_result = compact.lower()
    if (
        not compact
        or "tim thay 0 tai lieu lien quan" in lowered_result
        or len(compact) > 180
        or "http" in lowered_result
    ):
        return "Đã có thêm kết quả để chắt lọc."
    return compact


def _parse_host_action_result(tool_name: str, result: object) -> dict[str, Any] | None:
    """Parse a generated host action tool result."""
    parsed = parse_host_action_request_result(tool_name, result)
    if parsed is None:
        return None
    return {
        "request_id": parsed.request_id,
        "action": parsed.action,
        "params": parsed.params,
    }


async def _maybe_emit_host_action_event(
    *,
    push_event,
    tool_name: str,
    result: object,
    node: str,
    tool_call_events: list[dict],
) -> bool:
    """Emit host_action SSE event when a generated host action tool fires."""
    parsed = _parse_host_action_result(tool_name, result)
    if not parsed:
        return False
    safe_params = sanitize_runtime_payload(parsed["params"])
    if not isinstance(safe_params, dict):
        safe_params = {}
    safe_params.pop("redacted_secret_count", None)

    await push_event({
        "type": "host_action",
        "content": {
            "id": parsed["request_id"],
            "action": parsed["action"],
            "params": safe_params,
        },
        "node": node,
    })
    tool_call_events.append({
        "type": "host_action",
        "id": parsed["request_id"],
        "action": parsed["action"],
        "params": safe_params,
        "node": node,
    })
    return True


def _collect_active_visual_session_ids(state: AgentState) -> list[str]:
    """Collect active inline visual sessions from client-provided visual context."""
    visual_ctx = ((state.get("context") or {}).get("visual_context") or {})
    if not isinstance(visual_ctx, dict):
        return []

    session_ids: list[str] = []
    active_items = visual_ctx.get("active_inline_visuals")
    if isinstance(active_items, list):
        for item in active_items:
            if not isinstance(item, dict):
                continue
            visual_session_id = str(item.get("visual_session_id") or item.get("session_id") or "").strip()
            if visual_session_id and visual_session_id not in session_ids:
                session_ids.append(visual_session_id)

    fallback_session_id = str(visual_ctx.get("last_visual_session_id") or "").strip()
    if fallback_session_id and fallback_session_id not in session_ids:
        session_ids.append(fallback_session_id)

    return session_ids


# Code Studio streaming constants
CODE_CHUNK_SIZE = 250       # ~5 lines per chunk
CODE_CHUNK_DELAY_SEC = 0.015  # 15ms between chunks → ~66 chunks/sec


async def _maybe_emit_code_studio_events(
    *,
    push_event,
    payload,
    payload_dict: dict,
    node: str,
    session_id_override: str | None = None,
) -> None:
    """Emit chunked code_open → code_delta × N → code_complete SSE events.

    Called inside _maybe_emit_visual_event when Code Studio streaming is enabled
    and the payload contains fallback_html from tool_create_visual_code.
    """
    fallback_html = payload.fallback_html
    if not fallback_html:
        return

    session_id = str(session_id_override or payload.visual_session_id or "").strip()
    if not session_id:
        session_id = f"vs-code-{uuid.uuid4().hex[:12]}"
    title = payload.title or "Visual"
    metadata = payload_dict.get("metadata") if isinstance(payload_dict, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        version = max(1, int(metadata.get("code_studio_version") or getattr(payload, "figure_index", 1) or 1))
    except Exception:
        version = max(1, int(getattr(payload, "figure_index", 1) or 1))
    studio_lane = str(metadata.get("studio_lane") or "app")
    artifact_kind = str(metadata.get("artifact_kind") or "html_app")
    quality_profile = str(metadata.get("quality_profile") or "standard")
    renderer_contract = str(metadata.get("renderer_contract") or "host_shell")
    requested_view = str(metadata.get("requested_view") or "").strip().lower()
    if requested_view not in {"code", "preview"}:
        requested_view = ""

    # 1. Emit code_open
    await push_event({
        "type": "code_open",
        "content": {
            "session_id": session_id,
            "title": title,
            "language": "html",
            "version": version,
            "studio_lane": studio_lane,
            "artifact_kind": artifact_kind,
            "quality_profile": quality_profile,
            "renderer_contract": renderer_contract,
            **({"requested_view": requested_view} if requested_view else {}),
        },
        "node": node,
    })

    # 2. Emit code_delta chunks
    total_bytes = len(fallback_html)
    chunk_index = 0
    for i in range(0, total_bytes, CODE_CHUNK_SIZE):
        chunk = fallback_html[i:i + CODE_CHUNK_SIZE]
        await push_event({
            "type": "code_delta",
            "content": {
                "session_id": session_id,
                "chunk": chunk,
                "chunk_index": chunk_index,
                "total_bytes": total_bytes,
            },
            "node": node,
        })
        chunk_index += 1
        await asyncio.sleep(CODE_CHUNK_DELAY_SEC)

    # 3. Emit code_complete
    await push_event({
        "type": "code_complete",
        "content": {
            "session_id": session_id,
            "full_code": fallback_html,
            "language": "html",
            "version": version,
            "studio_lane": studio_lane,
            "artifact_kind": artifact_kind,
            "quality_profile": quality_profile,
            "renderer_contract": renderer_contract,
            **({"requested_view": requested_view} if requested_view else {}),
            "visual_payload": payload_dict,
        },
        "node": node,
    })


async def _maybe_emit_visual_event(
    *,
    push_event,
    tool_name: str,
    tool_call_id: str,
    result: object,
    node: str,
    tool_call_events: list[dict],
    previous_visual_session_ids: list[str] | None = None,
    skip_fake_chunking: bool = False,
    code_session_id_override: str | None = None,
) -> tuple[list[str], list[str]]:
    """Stream structured visual results immediately when available."""
    try:
        from app.engine.tools.visual_tools import parse_visual_payloads

        payloads = parse_visual_payloads(result)
        if not payloads:
            return [], []

        payloads = sorted(payloads, key=lambda payload: (payload.figure_index, payload.title))
        emitted_session_ids = [payload.visual_session_id for payload in payloads if payload.visual_session_id]
        disposed_session_ids: list[str] = []
        existing_session_ids = [
            session_id
            for session_id in (previous_visual_session_ids or [])
            if session_id
        ]

        first_event_type = (
            payloads[0].lifecycle_event
            if payloads[0].lifecycle_event in {"visual_open", "visual_patch"}
            else "visual_open"
        )
        if first_event_type == "visual_open":
            for previous_visual_session_id in existing_session_ids:
                if previous_visual_session_id in emitted_session_ids:
                    continue
                disposed_session_ids.append(previous_visual_session_id)
                await push_event({
                    "type": "visual_dispose",
                    "content": {
                        "visual_session_id": previous_visual_session_id,
                        "status": "disposed",
                        "reason": "superseded_by_new_visual",
                    },
                    "node": node,
                })
                tool_call_events.append({
                    "type": "visual_dispose",
                    "visual_session_id": previous_visual_session_id,
                    "reason": "superseded_by_new_visual",
                    "node": node,
                })
                _log_visual_telemetry(
                    "visual_disposed",
                    visual_session_id=previous_visual_session_id,
                    reason="superseded_by_new_visual",
                    node=node,
                )

        for payload in payloads:
            payload_dict = payload.model_dump(mode="json")

            # Code Studio streaming: emit chunked code events before visual_open
            # Skip fake chunking if real streaming already delivered tokens
            if (
                settings.enable_code_studio_streaming
                and not skip_fake_chunking
                and payload.fallback_html
                and str((payload.metadata or {}).get("presentation_intent") or "") in {"code_studio_app", "artifact"}
            ):
                await _maybe_emit_code_studio_events(
                    push_event=push_event,
                    payload=payload,
                    payload_dict=payload_dict,
                    node=node,
                    session_id_override=code_session_id_override,
                )

            event_type = payload.lifecycle_event if payload.lifecycle_event in {"visual_open", "visual_patch"} else "visual_open"
            await push_event({
                "type": event_type,
                "content": payload_dict,
                "node": node,
            })
            tool_call_events.append({
                "type": event_type,
                "name": tool_name,
                "id": tool_call_id,
                "visual": payload_dict,
                "visual_session_id": payload.visual_session_id,
                "figure_group_id": payload.figure_group_id,
                "figure_index": payload.figure_index,
            })
            _log_visual_telemetry(
                "visual_emitted",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                visual_id=payload.id,
                visual_session_id=payload.visual_session_id,
                visual_type=payload.type,
                lifecycle_event=event_type,
                node=node,
                figure_group_id=payload.figure_group_id,
                figure_index=payload.figure_index,
                figure_total=payload.figure_total,
                pedagogical_role=payload.pedagogical_role,
                chrome_mode=payload.chrome_mode,
            )

        return emitted_session_ids, disposed_session_ids
    except Exception as exc:
        logger.warning("[VISUAL] Failed to emit structured visual event: %s", exc)
    return [], []


async def _emit_visual_commit_events(
    *,
    push_event,
    node: str,
    visual_session_ids: list[str],
    tool_call_events: list[dict],
) -> None:
    """Emit commit events for visual sessions touched in the current tool round."""
    emitted: set[str] = set()
    for visual_session_id in visual_session_ids:
        if not visual_session_id or visual_session_id in emitted:
            continue
        emitted.add(visual_session_id)
        await push_event({
            "type": "visual_commit",
            "content": {
                "visual_session_id": visual_session_id,
                "status": "committed",
            },
            "node": node,
        })
        tool_call_events.append({
            "type": "visual_commit",
            "visual_session_id": visual_session_id,
            "node": node,
        })
        _log_visual_telemetry(
            "visual_committed",
            visual_session_id=visual_session_id,
            node=node,
        )
