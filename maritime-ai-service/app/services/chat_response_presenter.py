"""Presentation helpers for the LMS chat JSON response."""

import re

from app.core.constants import (
    CONFIDENCE_BASE,
    CONFIDENCE_MAX,
    CONFIDENCE_PER_SOURCE,
)
from app.engine.multi_agent.runtime_flow_ledger import sanitize_runtime_flow_trace
from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ChatResponseData,
    ChatResponseMetadata,
    InternalChatResponse,
    SourceInfo,
    ToolUsageInfo,
)
from app.services.model_switch_prompt_service import (
    build_model_switch_prompt_for_failover,
)

# ── Soul Emotion Tag Stripper (Sprint 35e follow-up) ───────────────────────
# DeepSeek + other LLMs occasionally emit ``<!-- WIII_SOUL:{...} -->`` HTML
# comments at the start of the synthesizer prose. Those are an internal
# directive for the mascot/avatar emotion engine — they must NEVER reach the
# user-facing JSON ``answer`` field. The SSE presenter has its own stripper
# (``chat_stream_presenter._strip_soul_tags``); this is the matching guard
# for the sync ``/api/v1/chat`` JSON path so the leak cannot bypass either
# transport.
_SOUL_TAG_RE = re.compile(r"<!--\s*WIII_SOUL:.*?-->", re.DOTALL)


def _strip_soul_tags(text: str | None) -> str:
    """Remove ``<!--WIII_SOUL:{...}-->`` comments + leading whitespace."""
    if not text or "WIII_SOUL" not in text:
        return text or ""
    return _SOUL_TAG_RE.sub("", text).lstrip()


def _safe_metadata(value: dict | None) -> dict:
    safe = sanitize_runtime_payload(value or {})
    return safe if isinstance(safe, dict) else {}


def _safe_text(value: object) -> str:
    return redact_runtime_secret_text(value)


def _safe_optional_text(value: object) -> str | None:
    text = _safe_text(value).strip()
    return text or None


def _safe_dict(value: object) -> dict | None:
    safe = sanitize_runtime_payload(value)
    return safe if isinstance(safe, dict) else None


def get_tool_description(tool: dict) -> str:
    """Generate a short human-readable description for a used tool."""
    name = _safe_text(tool.get("name", "unknown"))
    args = tool.get("args", {})
    args = args if isinstance(args, dict) else {}
    result = _safe_text(tool.get("result", ""))

    if name in ("tool_knowledge_search", "tool_maritime_search"):
        query = _safe_text(args.get("query", ""))
        return f"Tra cứu: {query}" if query else "Tra cứu kiến thức"
    if name == "tool_save_user_info":
        key = _safe_text(args.get("key", ""))
        value = _safe_text(args.get("value", ""))
        return f"Lưu thông tin: {key}={value}" if key else "Lưu thông tin người dùng"
    if name == "tool_get_user_info":
        key = _safe_text(args.get("key", "all"))
        return f"Lấy thông tin: {key}"
    return result[:100] if result else f"Gọi tool: {name}"


def classify_query_type(message: str) -> str:
    """Classify query type for LMS analytics."""
    message_lower = message.lower()
    code_keywords = [
        "python", "code", "chart", "plot", "bieu do", "html", "landing page",
        "excel", "word", "docx", "xlsx", "javascript", "react",
    ]

    procedural_keywords = [
        "làm thế nào", "như thế nào", "cách", "thủ tục", "quy trình",
        "bước", "how to", "steps", "process", "procedure",
    ]
    factual_keywords = [
        "điều", "khoản", "quy định", "là gì", "what is", "định nghĩa",
        "nghĩa là", "rule", "article", "regulation",
    ]

    for keyword in code_keywords:
        if keyword in message_lower:
            return "code_generation"
    for keyword in procedural_keywords:
        if keyword in message_lower:
            return "procedural"
    for keyword in factual_keywords:
        if keyword in message_lower:
            return "factual"
    return "conceptual"


def generate_suggested_questions(user_message: str, ai_response: str) -> list[str]:
    """Generate follow-up suggestions from the current exchange."""
    user_lower = user_message.lower()
    response_lower = ai_response.lower()

    if any(keyword in user_lower for keyword in [
        "python", "code", "chart", "plot", "bieu do", "html", "landing page",
        "excel", "word", "docx", "xlsx", "javascript", "react",
    ]):
        return [
            "Bạn muốn mình dùng dữ liệu cụ thể nào để làm lại phiên bản chuẩn hơn?",
            "Bạn có muốn đổi kiểu hiển thị hoặc màu sắc của artifact không?",
            "Bạn muốn mình xuất thêm một file khác như HTML, Excel, hoặc Word không?",
        ]

    if any(keyword in response_lower for keyword in ["quy tắc", "rule", "điều", "quy định"]):
        return [
            "Khi nào áp dụng quy tắc này?",
            "Có ngoại lệ nào không?",
            "Bạn có thể giải thích chi tiết hơn không?",
        ]
    if any(keyword in response_lower for keyword in ["an toàn", "safety", "thiết bị"]):
        return [
            "Yêu cầu cụ thể là gì?",
            "Quy trình kiểm tra như thế nào?",
            "Có tiêu chuẩn nào liên quan không?",
        ]
    if any(keyword in user_lower for keyword in ["học", "tìm hiểu", "giải thích", "dạy"]):
        return [
            "Bạn muốn tìm hiểu thêm về chủ đề nào?",
            "Bạn cần giải thích chi tiết hơn không?",
            "Bạn muốn làm bài tập thực hành không?",
        ]
    return [
        "Bạn muốn tìm hiểu thêm về chủ đề nào?",
        "Bạn có câu hỏi nào khác không?",
        "Tôi có thể giúp gì thêm cho bạn?",
    ]


def build_chat_response(
    *,
    chat_request: ChatRequest,
    internal_response: InternalChatResponse,
    processing_time: float,
    provider_name: str | None,
    model_name: str | None,
    runtime_authoritative: bool = True,
) -> ChatResponse:
    """Build the LMS-facing JSON response from the internal response."""
    sources = []
    if internal_response.sources:
        for src in internal_response.sources:
            safe_bounding_boxes = sanitize_runtime_payload(
                getattr(src, "bounding_boxes", None),
            )
            sources.append(
                SourceInfo(
                    title=_safe_text(src.title),
                    content=_safe_text(src.content_snippet or ""),
                    image_url=_safe_optional_text(getattr(src, "image_url", None)),
                    page_number=getattr(src, "page_number", None),
                    document_id=_safe_optional_text(getattr(src, "document_id", None)),
                    bounding_boxes=(
                        safe_bounding_boxes
                        if isinstance(safe_bounding_boxes, list)
                        else None
                    ),
                )
            )

    tools_used = []
    metadata = _safe_metadata(internal_response.metadata)
    for tool in metadata.get("tools_used", []):
        if not isinstance(tool, dict):
            continue
        tools_used.append(
            ToolUsageInfo(
                name=_safe_text(tool.get("name", "unknown")),
                description=get_tool_description(tool),
            )
        )

    topics_accessed = [src.title for src in sources if src.title] or None
    document_ids_used = list({src.document_id for src in sources if src.document_id}) or None
    confidence_score = None
    if sources:
        confidence_score = min(
            CONFIDENCE_BASE + len(sources) * CONFIDENCE_PER_SOURCE,
            CONFIDENCE_MAX,
        )

    cleaned_message = _safe_text(_strip_soul_tags(internal_response.message))
    thinking_lifecycle = _safe_dict(metadata.get("thinking_lifecycle"))
    public_thinking = (
        str((thinking_lifecycle or {}).get("final_text") or "").strip()
        or str(metadata.get("thinking_content") or "").strip()
        or str(metadata.get("thinking") or "").strip()
        or None
    )
    failover = _safe_dict(metadata.get("failover"))
    model_switch_prompt = _safe_dict(
        build_model_switch_prompt_for_failover(
            failover=failover,
            requested_provider=getattr(chat_request, "provider", None),
        )
    )
    return ChatResponse(
        status="success",
        data=ChatResponseData(
            answer=cleaned_message,
            sources=sources,
            suggested_questions=generate_suggested_questions(
                chat_request.message,
                cleaned_message,
            ),
            domain_notice=_safe_optional_text(metadata.get("domain_notice")),
        ),
        metadata=ChatResponseMetadata(
            processing_time=round(processing_time, 3),
            provider=_safe_optional_text(provider_name),
            model=_safe_text(model_name or ""),
            agent_type=internal_response.agent_type,
            session_id=_safe_optional_text(metadata.get("session_id")),
            tools_used=tools_used,
            reasoning_trace=_safe_dict(metadata.get("reasoning_trace")),
            thinking_content=public_thinking,
            thinking=public_thinking,
            thinking_lifecycle=thinking_lifecycle,
            failover=failover,
            model_switch_prompt=model_switch_prompt,
            routing_metadata=_safe_dict(metadata.get("routing_metadata")),
            runtime_flow_trace=(
                sanitize_runtime_flow_trace(metadata.get("runtime_flow_trace"))
                if metadata.get("runtime_flow_trace")
                else None
            ),
            post_turn_lifecycle=_safe_dict(metadata.get("post_turn_lifecycle")),
            topics_accessed=topics_accessed,
            confidence_score=round(confidence_score, 2) if confidence_score else None,
            document_ids_used=document_ids_used,
            query_type=classify_query_type(chat_request.message),
            runtime_authoritative=runtime_authoritative,
        ),
    )
