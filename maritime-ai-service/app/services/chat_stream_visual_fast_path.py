"""Deterministic structured-visual fast path for streaming turns."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

from app.engine.multi_agent.stream_utils import StreamEvent
from app.engine.multi_agent.visual_intent_resolver import (
    detect_visual_patch_request,
    resolve_visual_intent,
)
from app.engine.tools.visual_tools import parse_visual_payloads, tool_generate_visual


_VISUAL_CREATE_CUES = (
    "create",
    "draw",
    "make",
    "build",
    "dung",
    "dựng",
    "tao",
    "tạo",
    "ve ",
    "vẽ",
)
_RETRIEVAL_CUES = (
    "citation",
    "citations",
    "docx",
    "document",
    "file",
    "pdf",
    "source",
    "sources",
    "tai lieu",
    "tài liệu",
    "trich dan",
    "trích dẫn",
)
_FRESH_OR_WEB_CUES = (
    "current",
    "gia hien tai",
    "giá hiện tại",
    "latest",
    "news",
    "search web",
    "today",
    "web search",
)


@dataclass(frozen=True, slots=True)
class VisualFastPathResult:
    """Events and metadata for a deterministic visual-only stream."""

    events: list[StreamEvent]
    answer: str
    thinking: str
    routing_metadata: dict[str, Any]


def _plain_context_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _has_uploaded_document_context(chat_request: Any) -> bool:
    user_context = getattr(chat_request, "user_context", None)
    if isinstance(user_context, Mapping):
        document_context = user_context.get("document_context")
    else:
        document_context = getattr(user_context, "document_context", None)
    document_context = _plain_context_value(document_context)
    if not isinstance(document_context, Mapping):
        return False

    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return False
    return any(
        isinstance(item, Mapping) and str(item.get("markdown") or "").strip()
        for item in attachments
    )


def _has_image_input(chat_request: Any) -> bool:
    images = getattr(chat_request, "images", None)
    return isinstance(images, list) and any(images)


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def _clean_label(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,:;!?\"'")
    return cleaned[:80] or "Item"


def _comparison_spec(query: str) -> dict[str, Any]:
    patterns = (
        r"\bcompar(?:e|ing)\s+(.+?)\s+(?:and|vs\.?|versus|with)\s+(.+?)(?:[.!?]|$)",
        r"\bso sanh\s+(.+?)\s+(?:voi|va|và|vs\.?)\s+(.+?)(?:[.!?]|$)",
        r"\bso sánh\s+(.+?)\s+(?:với|và|vs\.?)\s+(.+?)(?:[.!?]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.I)
        if not match:
            continue
        left = _clean_label(match.group(1))
        right = _clean_label(match.group(2))
        if left and right:
            return {
                "left": {"title": left},
                "right": {"title": right},
            }
    return {}


def _title_from_query(query: str, visual_type: str, spec: dict[str, Any]) -> str:
    if visual_type == "comparison" and spec.get("left") and spec.get("right"):
        left = str((spec.get("left") or {}).get("title") or "Left").strip()
        right = str((spec.get("right") or {}).get("title") or "Right").strip()
        return f"{left} vs {right}"
    first_sentence = re.split(r"[.!?]\s+", query.strip(), maxsplit=1)[0]
    first_sentence = re.sub(
        r"^(create|draw|make|build|dung|dựng|tao|tạo|ve|vẽ)\s+",
        "",
        first_sentence,
        flags=re.I,
    )
    return _clean_label(first_sentence) or "Inline visual"


def should_use_visual_fast_path(chat_request: Any) -> bool:
    """Return True for explicit visual creation turns safe to handle locally."""

    query = str(getattr(chat_request, "message", "") or "").strip()
    if not query:
        return False
    normalized = query.lower()
    if _has_uploaded_document_context(chat_request) or _has_image_input(chat_request):
        return False
    if detect_visual_patch_request(query):
        return False
    if _contains_any(normalized, _RETRIEVAL_CUES) or _contains_any(normalized, _FRESH_OR_WEB_CUES):
        return False
    if not (
        _contains_any(normalized, _VISUAL_CREATE_CUES)
        or "structured visual lifecycle" in normalized
    ):
        return False

    decision = resolve_visual_intent(query)
    return bool(
        decision.force_tool
        and decision.presentation_intent in {"article_figure", "chart_runtime"}
    )


async def build_visual_fast_path_result(
    chat_request: Any,
    *,
    node: str = "visual_fast_path",
) -> VisualFastPathResult | None:
    """Build visual lifecycle events without waiting on provider tool-calling."""

    if not should_use_visual_fast_path(chat_request):
        return None

    query = str(getattr(chat_request, "message", "") or "").strip()
    decision = resolve_visual_intent(query)
    visual_type = decision.visual_type or (
        "chart" if decision.presentation_intent == "chart_runtime" else "concept"
    )
    spec = _comparison_spec(query) if visual_type == "comparison" else {}
    title = _title_from_query(query, visual_type, spec)
    summary = f"Minh họa ngắn cho yêu cầu: {query[:140]}"

    result = tool_generate_visual.invoke(
        {
            "visual_type": visual_type,
            "spec_json": json.dumps(spec, ensure_ascii=False),
            "title": title,
            "summary": summary,
        }
    )
    payloads = parse_visual_payloads(result)
    if not payloads:
        return None

    events: list[StreamEvent] = []
    visual_session_ids: list[str] = []
    for payload in sorted(payloads, key=lambda item: (item.figure_index, item.title)):
        payload_dict = payload.model_dump(mode="json")
        event_type = (
            payload.lifecycle_event
            if payload.lifecycle_event in {"visual_open", "visual_patch"}
            else "visual_open"
        )
        events.append(StreamEvent(type=event_type, content=payload_dict, node=node))
        if payload.visual_session_id and payload.visual_session_id not in visual_session_ids:
            visual_session_ids.append(payload.visual_session_id)

    for visual_session_id in visual_session_ids:
        events.append(
            StreamEvent(
                type="visual_commit",
                content={
                    "visual_session_id": visual_session_id,
                    "status": "committed",
                },
                node=node,
            )
        )

    thinking = (
        "Yêu cầu là một lượt tạo visual rõ ràng, không kèm tài liệu upload hay dữ liệu thời sự, "
        "nên Wiii dựng nhanh phần nhìn trước khi gọi mô hình."
    )
    routing_metadata = {
        "method": "structured_visual_fast_path",
        "intent": "learning",
        "final_agent": node,
        "presentation_intent": decision.presentation_intent,
        "visual_type": visual_type,
    }
    return VisualFastPathResult(
        events=events,
        answer="Mình đã dựng minh họa inline cho yêu cầu này.",
        thinking=thinking,
        routing_metadata=routing_metadata,
    )
