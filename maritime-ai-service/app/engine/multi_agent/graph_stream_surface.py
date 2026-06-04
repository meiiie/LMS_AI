"""Surface/event helpers extracted from graph_streaming."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.engine.reasoning import ReasoningRenderRequest, get_reasoning_narrator
from app.engine.reasoning.reasoning_narrator import build_tool_context_summary
from app.engine.multi_agent.stream_utils import (
    StreamEvent,
    create_action_text_event,
    create_answer_event,
    create_artifact_event,
    create_browser_screenshot_event,
    create_code_complete_event,
    create_code_delta_event,
    create_code_open_event,
    create_emotion_event,
    create_pointy_action_event,
    create_preview_event,
    create_sources_event,
    create_status_event,
    create_thinking_delta_event,
    create_thinking_end_event,
    create_thinking_start_event,
    create_tool_call_event,
    create_tool_result_event,
    create_visual_commit_event,
    create_visual_dispose_event,
    create_visual_open_event,
    create_visual_patch_event,
)

logger = logging.getLogger(__name__)

_LABEL_PATTERN = re.compile(r"<label>(.*?)</label>", re.DOTALL | re.IGNORECASE)
_METADATA_TAG_PATTERN = re.compile(
    r"^>\s*(?:ĐIỀU HƯỚNG|GIẢI THÍCH|TRA CỨU|TRỰC TIẾP|TỔNG HỢP|ĐÁNH GIÁ|"
    r"Điều hướng|Giải thích|Tra cứu|Trực tiếp|Tổng hợp|Đánh giá)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_ANSWER_TAG_PATTERN = re.compile(r"</?answer>|‹/?answer›", re.IGNORECASE)
_VISUAL_REF_PATTERN = re.compile(
    r"\{visual-[a-f0-9]+\}|<!-- WiiiVisualBridge:visual-[a-f0-9]+ -->|"
    r"\[Biểu đồ[^\]]*\]|\[Chart[^\]]*\]|\[Visual[^\]]*\]|"
    r"\(Visuals?\s+đang[^)]*\)|\(Visual[^)]*displayed[^)]*\)",
    re.IGNORECASE,
)


async def _convert_bus_event_impl(event: dict) -> StreamEvent:
    """Convert an intra-node bus event dict to a StreamEvent."""
    etype = event.get("type", "status")
    node = event.get("node")

    if etype == "thinking_delta":
        return await create_thinking_delta_event(content=event.get("content", ""), node=node)
    if etype == "tool_call":
        tc = event.get("content", {})
        return await create_tool_call_event(
            tool_name=tc.get("name", ""),
            tool_args=tc.get("args", {}),
            tool_call_id=tc.get("id", ""),
            node=node,
        )
    if etype == "tool_result":
        tc = event.get("content", {})
        return await create_tool_result_event(
            tool_name=tc.get("name", ""),
            result_summary=tc.get("result", ""),
            tool_call_id=tc.get("id", ""),
            node=node,
        )
    if etype == "sources":
        sources = event.get("content", [])
        return await create_sources_event(sources if isinstance(sources, list) else [])
    if etype == "answer_delta":
        return await create_answer_event(event.get("content", ""))
    if etype == "thinking_start":
        details = dict(event.get("details") or {})
        if event.get("summary") and "summary" not in details:
            details["summary"] = event.get("summary")
        if event.get("summary_mode") and "summary_mode" not in details:
            details["summary_mode"] = event.get("summary_mode")
        return await create_thinking_start_event(
            label=str(event.get("content", "")),
            node=node or "",
            summary=event.get("summary"),
            details=details or None,
        )
    if etype == "thinking_end":
        return await create_thinking_end_event(node=node or "")
    if etype == "action_text":
        return await create_action_text_event(content=str(event.get("content", "")), node=node)
    if etype == "browser_screenshot":
        sc = event.get("content", {})
        return await create_browser_screenshot_event(
            url=str(sc.get("url", "")),
            image_base64=str(sc.get("image", "")),
            label=str(sc.get("label", "")),
            node=node,
            metadata=sc.get("metadata"),
        )
    if etype == "preview":
        pv = event.get("content", {})
        return await create_preview_event(
            preview_type=str(pv.get("preview_type", "document")),
            preview_id=str(pv.get("preview_id", "")),
            title=str(pv.get("title", "")),
            snippet=str(pv.get("snippet", "")),
            url=pv.get("url"),
            image_url=pv.get("image_url"),
            citation_index=pv.get("citation_index"),
            node=node,
            metadata=pv.get("metadata"),
        )
    if etype == "artifact":
        af = event.get("content", {})
        return await create_artifact_event(
            artifact_type=str(af.get("artifact_type", "code")),
            artifact_id=str(af.get("artifact_id", "")),
            title=str(af.get("title", "")),
            content=str(af.get("content", "")),
            language=str(af.get("language", "")),
            node=node,
            metadata=af.get("metadata"),
        )
    if etype in {"visual", "visual_open"}:
        visual = event.get("content", {})
        return await create_visual_open_event(
            payload=dict(visual) if isinstance(visual, dict) else {},
            node=node,
        )
    if etype == "visual_patch":
        visual = event.get("content", {})
        return await create_visual_patch_event(
            payload=dict(visual) if isinstance(visual, dict) else {},
            node=node,
        )
    if etype == "visual_commit":
        visual = event.get("content", {})
        return await create_visual_commit_event(
            visual_session_id=str(visual.get("visual_session_id", "")),
            node=node,
            status=str(visual.get("status") or "committed"),
        )
    if etype == "visual_dispose":
        visual = event.get("content", {})
        return await create_visual_dispose_event(
            visual_session_id=str(visual.get("visual_session_id", "")),
            node=node,
            reason=str(visual.get("reason") or ""),
            status=str(visual.get("status") or "disposed"),
        )
    if etype == "code_open":
        cs = event.get("content", {})
        return await create_code_open_event(
            session_id=str(cs.get("session_id", "")),
            title=str(cs.get("title", "")),
            language=str(cs.get("language", "html")),
            version=int(cs.get("version", 1)),
            studio_lane=str(cs.get("studio_lane", "") or "") or None,
            artifact_kind=str(cs.get("artifact_kind", "") or "") or None,
            quality_profile=str(cs.get("quality_profile", "") or "") or None,
            renderer_contract=str(cs.get("renderer_contract", "") or "") or None,
            node=node,
        )
    if etype == "code_delta":
        cs = event.get("content", {})
        return await create_code_delta_event(
            session_id=str(cs.get("session_id", "")),
            chunk=str(cs.get("chunk", "")),
            chunk_index=int(cs.get("chunk_index", 0)),
            total_bytes=int(cs.get("total_bytes", 0)),
            node=node,
        )
    if etype == "code_complete":
        cs = event.get("content", {})
        return await create_code_complete_event(
            session_id=str(cs.get("session_id", "")),
            full_code=str(cs.get("full_code", "")),
            language=str(cs.get("language", "html")),
            version=int(cs.get("version", 1)),
            visual_payload=cs.get("visual_payload"),
            studio_lane=str(cs.get("studio_lane", "") or "") or None,
            artifact_kind=str(cs.get("artifact_kind", "") or "") or None,
            quality_profile=str(cs.get("quality_profile", "") or "") or None,
            renderer_contract=str(cs.get("renderer_contract", "") or "") or None,
            node=node,
        )
    if etype == "pointy_action":
        # Wiii Pointy: bus event yields the canonical pointy payload as
        # `content`. Wrap it in a typed StreamEvent so the presenter
        # routes it through the `pointy_action` allowlist branch (without
        # this case the converter falls through to `create_status_event`
        # and the cursor command silently becomes a status event).
        content = event.get("content") or {}
        return await create_pointy_action_event(
            payload=content if isinstance(content, dict) else {},
            node=node,
        )
    if etype == "host_action":
        # Host action requests bypass conversion when emitted directly via
        # `create_host_action_event`; this branch covers the rare case
        # where another node enqueues a host action via the bus.
        from app.engine.multi_agent.stream_utils import create_host_action_event
        content = event.get("content") or {}
        if isinstance(content, dict):
            return await create_host_action_event(
                request_id=str(content.get("id", "")),
                action=str(content.get("action", "")),
                params=content.get("params") or {},
                node=node,
            )
    if etype == "model_switch":
        from_provider = event.get("from_provider", "")
        to_provider = event.get("to_provider", "")
        reason = event.get("reason", "rate_limit")
        return await create_status_event(
            f"Đang chuyển sang {to_provider} (do {from_provider} tạm bận)",
            node="system",
            details={
                "subtype": "model_switch",
                "from_provider": from_provider,
                "to_provider": to_provider,
                "reason": reason,
            },
        )
    return await create_status_event(
        str(event.get("content", "")),
        node=node,
        details=event.get("details"),
    )


def _normalize_tool_names_impl(tools_used: object) -> list[str]:
    names: list[str] = []
    if not isinstance(tools_used, list):
        return names
    for item in tools_used:
        if isinstance(item, dict):
            candidate = str(item.get("name") or item.get("tool_name") or item.get("tool") or "").strip()
        else:
            candidate = str(item).strip()
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def _normalize_narration_text_impl(value: str) -> str:
    return " ".join((value or "").lower().split())


def _narration_delta_chunks_impl(narration) -> list[str]:
    summary_norm = _normalize_narration_text_impl(getattr(narration, "summary", ""))
    filtered: list[str] = []
    filtered_norms: list[str] = []
    for chunk in getattr(narration, "delta_chunks", []) or []:
        if not chunk or not chunk.strip():
            continue
        chunk_norm = _normalize_narration_text_impl(chunk)
        if summary_norm and (
            chunk_norm == summary_norm
            or chunk_norm in summary_norm
            or summary_norm in chunk_norm
        ):
            continue
        # Skip exact-match duplicates (consecutive or non-consecutive).
        if chunk_norm in filtered_norms:
            continue
        # Skip substantial prefix/suffix overlap with ANY previous chunk —
        # prevents "A B", "A C" pairs that share a repeated opening from
        # stacking into display. Threshold: shorter chunk is >=80% inside longer.
        duplicate = False
        for prev_norm in filtered_norms:
            if not prev_norm or not chunk_norm:
                continue
            shorter, longer = (chunk_norm, prev_norm) if len(chunk_norm) <= len(prev_norm) else (prev_norm, chunk_norm)
            if len(shorter) >= 40 and shorter in longer:
                duplicate = True
                break
            # Detect heavy prefix overlap (new chunk repeats start of a past chunk)
            overlap = 0
            max_overlap = min(len(shorter), len(longer))
            while overlap < max_overlap and shorter[overlap] == longer[overlap]:
                overlap += 1
            if overlap >= 50 and overlap / max(len(shorter), 1) >= 0.8:
                duplicate = True
                break
        if duplicate:
            continue
        filtered.append(chunk.strip())
        filtered_norms.append(chunk_norm)
    return filtered


def _collapse_narration_impl(narration) -> str:
    chunks = _narration_delta_chunks_impl(narration)
    if chunks:
        return "\n".join(chunks)
    return narration.summary


async def _render_fallback_narration_impl(
    *,
    node: str,
    phase: str,
    query: str,
    user_id: str,
    context: Optional[dict],
    initial_state: AgentState,
    node_output: dict,
    cue: str = "",
    intent: str = "",
    next_action: str = "",
    observations: Optional[list[str]] = None,
    style_tags: Optional[list[str]] = None,
    confidence: float = 0.0,
    evidence_strength: float = 0.0,
):
    tool_names = _normalize_tool_names_impl(node_output.get("tools_used", []))
    response_hint = (
        node_output.get("final_response")
        or node_output.get("tutor_output")
        or node_output.get("memory_output")
        or ""
    )
    safe_observations = [item for item in (observations or []) if item]
    if tool_names:
        safe_observations.append(f"Đã đi qua {len(tool_names)} lớp công cụ liên quan.")
    sources = node_output.get("sources", [])
    if isinstance(sources, list) and sources:
        safe_observations.append(f"Đang giữ lại {len(sources)} nguồn hoặc mảnh chứng cứ liên quan.")

    return get_reasoning_narrator().render_fast(
        ReasoningRenderRequest(
            node=node,
            phase=phase,
            intent=intent,
            cue=cue,
            user_goal=query,
            conversation_context=str((context or {}).get("conversation_summary", "")),
            memory_context=str(node_output.get("memory_context") or initial_state.get("memory_context") or ""),
            capability_context=str(
                node_output.get("capability_context")
                or initial_state.get("capability_context")
                or ""
            ),
            tool_context=build_tool_context_summary(tool_names, response_hint or None),
            confidence=float(confidence or 0.0),
            evidence_strength=float(evidence_strength or 0.0),
            next_action=next_action,
            observations=safe_observations,
            user_id=user_id,
            organization_id=(context or {}).get("organization_id"),
            personality_mode=(context or {}).get("personality_mode"),
            mood_hint=(context or {}).get("mood_hint"),
            visibility_mode="rich",
            style_tags=style_tags or [],
            provider=initial_state.get("provider") if initial_state else None,
        )
    )


def _is_likely_english_impl(text: str) -> bool:
    if not text or len(text) < 30:
        return False
    # Several deterministic fast paths intentionally avoid an LLM call and may
    # emit romanized Vietnamese. Do not send those through a slow translation
    # pass just because they lack diacritics.
    lower = f" {text.lower()} "
    romanized_vietnamese_markers = (
        " minh ",
        " cau ",
        " ban ",
        " khong ",
        " nhung ",
        " hien ",
        " hay ",
        " giup ",
        " tra loi ",
        " nguoi dung ",
        " anh ",
        " wiii ",
    )
    marker_count = sum(1 for marker in romanized_vietnamese_markers if marker in lower)
    if marker_count >= 2:
        return False
    vn_diacritics = set(
        "àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợ"
        "ùúủũụưứừửữựỳýỷỹỵđÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆ"
        "ÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴĐ"
    )
    vn_count = sum(1 for c in text if c in vn_diacritics)
    return vn_count / max(len(text), 1) < 0.01


async def _ensure_vietnamese_impl(text: str) -> str:
    if not text or not _is_likely_english_impl(text):
        return text
    try:
        from app.engine.llm_pool import get_llm_light
        from app.engine.messages import Message
        from app.engine.messages_adapters import to_openai_dict
        from app.services.output_processor import extract_thinking_from_response

        llm = get_llm_light()
        if not llm:
            return text

        chat_messages = [
            Message(
                role="system",
                content=(
                    "Dịch đoạn văn sau sang tiếng Việt tự nhiên, chính xác. "
                    "Giữ nguyên thuật ngữ chuyên ngành hàng hải/giao thông bằng tiếng Anh "
                    "nếu cần (ví dụ: COLREGs, SOLAS, starboard). "
                    "CHỈ trả lời bản dịch tiếng Việt, KHÔNG thêm giải thích hay ghi chú. "
                    "KHÔNG bao gồm quá trình suy nghĩ."
                ),
            ),
            Message(role="user", content=text),
        ]
        response = await llm.ainvoke([to_openai_dict(m) for m in chat_messages])
        translated, _ = extract_thinking_from_response(response.content)
        result = translated.strip()
        if result and len(result) > 20:
            logger.info("[STREAM] Translated answer to Vietnamese: %d→%d chars", len(text), len(result))
            return result
        return text
    except Exception as exc:
        logger.warning("[STREAM] Translation failed, using original: %s", exc)
        return text


async def _stream_answer_tokens_impl(
    text: str,
    *,
    token_chunk_size: int,
    token_delay_sec: float,
) -> AsyncGenerator[StreamEvent, None]:
    text = await _ensure_vietnamese_impl(text)
    for i in range(0, len(text), token_chunk_size):
        chunk = text[i : i + token_chunk_size]
        yield await create_answer_event(chunk)
        await asyncio.sleep(token_delay_sec)


async def _extract_and_stream_emotion_then_answer_impl(
    text: str,
    soul_emitted: bool,
    *,
    token_chunk_size: int,
    token_delay_sec: float,
) -> AsyncGenerator[StreamEvent, None]:
    if not soul_emitted and settings.enable_soul_emotion:
        from app.engine.soul_emotion import extract_soul_emotion

        result = extract_soul_emotion(text)
        if result.emotion:
            yield await create_emotion_event(
                mood=result.emotion.mood,
                face=result.emotion.face,
                intensity=result.emotion.intensity,
            )
        text = result.clean_text

    async for event in _stream_answer_tokens_impl(
        text,
        token_chunk_size=token_chunk_size,
        token_delay_sec=token_delay_sec,
    ):
        yield event


def _is_pipeline_summary_impl(text: str) -> bool:
    prefix = text[:300]
    return "Quá trình suy nghĩ" in prefix


def _extract_thinking_label_impl(thinking_text: str) -> str:
    matches = _LABEL_PATTERN.findall(thinking_text)
    if matches:
        label = matches[-1].strip()
        if label and len(label) <= 80:
            return label
    return ""


def _clean_thinking_text_impl(text: str) -> str:
    clean = _LABEL_PATTERN.sub("", text)
    clean = _METADATA_TAG_PATTERN.sub("", clean)
    clean = _ANSWER_TAG_PATTERN.sub("", clean)
    clean = _VISUAL_REF_PATTERN.sub("", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean


def _extract_thinking_content_impl(node_output: dict) -> str:
    thinking = node_output.get("thinking", "")
    if thinking and len(thinking) > 20:
        if not _is_pipeline_summary_impl(thinking):
            clean = _clean_thinking_text_impl(thinking)
            return clean or thinking

    thinking_content = node_output.get("thinking_content", "")
    if thinking_content and len(thinking_content) > 20:
        if not _is_pipeline_summary_impl(thinking_content):
            clean = _clean_thinking_text_impl(thinking_content)
            return clean or thinking_content

    return ""


def _extract_thinking_with_label_impl(node_output: dict) -> tuple[str, str]:
    thinking = _extract_thinking_content_impl(node_output)
    if not thinking:
        return "", ""
    label = _extract_thinking_label_impl(thinking)
    clean_thinking = _LABEL_PATTERN.sub("", thinking).strip()
    clean_thinking = re.sub(r"\n{3,}", "\n\n", clean_thinking)
    return clean_thinking, label
