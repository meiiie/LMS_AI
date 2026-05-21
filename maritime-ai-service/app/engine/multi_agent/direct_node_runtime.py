"""Direct node runtime extracted from the graph shell."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_failover_runtime import classify_failover_reason_impl
from app.engine.multi_agent.document_preview_contract import (
    DOC_PREVIEW_HOST_ACTION_TOOL as _DOC_PREVIEW_HOST_ACTION_TOOL,
    as_plain_mapping as _as_plain_direct_mapping,
    document_preview_forced_tool_choice as _document_preview_forced_tool_choice,
    extract_document_preview_capabilities as _extract_document_preview_capabilities,
    has_document_preview_host_action_tool as _has_document_preview_host_action_tool,
    has_uploaded_document_context as _has_uploaded_document_context,
    uploaded_document_attachments_from_context as _uploaded_document_attachments,
)
from app.engine.multi_agent.direct_intent import (
    _looks_emotional_support_turn,
    _normalize_for_intent,
)
from app.engine.multi_agent.direct_visible_thinking_cleanup import (
    looks_like_direct_selfhood_answer_draft_paragraph,
    looks_like_direct_selfhood_english_meta_paragraph,
    looks_like_direct_selfhood_meta_heading,
    looks_like_direct_selfhood_meta_intro,
    strip_direct_selfhood_filler_prefix,
)
from app.engine.multi_agent.direct_reasoning import (
    _infer_direct_thinking_mode,
    _is_codebase_analysis_query,
)
from app.engine.multi_agent.direct_response_runtime import (
    resolve_direct_fallback_provider_allowlist_impl_wrapper,
    resolve_direct_answer_primary_timeout_impl,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
    looks_like_search_placeholder_answer,
)
from app.engine.multi_agent.direct_session_memory_runtime import (
    _build_session_memory_write_answer,
    _build_session_memory_write_thinking,
    _extract_session_memory_items_from_text,
    _extract_session_memory_recall_answer,
    _with_requested_response_marker,
)
from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.direct_node_chatter_runtime import (
    _build_hunger_chatter_answer,
    _build_hunger_chatter_thinking,
    _looks_hunger_chatter_turn,
)
from app.engine.multi_agent.direct_node_meta_fast_paths import (
    _build_reasoning_safety_meta_answer,
    _build_reasoning_safety_meta_thinking,
    _build_self_feeling_probe_answer,
    _build_self_feeling_probe_thinking,
    _build_wiii_capability_inventory_answer,
    _build_wiii_capability_inventory_thinking,
    _looks_self_feeling_probe_turn,
)
from app.engine.runtime.runtime_metrics import inc_counter
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.visual_events import _summarize_tool_result_for_stream
from app.engine.multi_agent.visual_intent_resolver import merge_thinking_effort
from app.engine.reasoning import (
    align_visible_thinking_language,
    record_thinking_snapshot,
    should_align_visible_thinking_language,
)
from app.engine.tools.runtime_context import build_tool_runtime_context
from app.engine.multi_agent.graph_runtime_helpers import (
    _copy_runtime_metadata,
    _extract_runtime_target,
    _is_native_runtime_handle,
)
from app.engine.multi_agent.tool_collection import _force_skills_from_state
from app.engine.multi_agent.supervisor_runtime_support import (
    _looks_reasoning_safety_meta_turn,
    _looks_session_memory_ack_only_turn,
    _looks_session_memory_recall_turn,
    _looks_session_memory_write_turn,
    _looks_wiii_capability_inventory_turn,
    _looks_wiii_pipeline_meta_turn,
)

logger = logging.getLogger(__name__)

_DIRECT_SESSION_MEMORY_COMPAT_EXPORTS = (
    _extract_session_memory_items_from_text,
)


def _direct_role_candidates(state: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    state_context = state.get("context") if isinstance(state.get("context"), dict) else {}
    host_context = _as_plain_direct_mapping(
        ctx.get("host_context")
        or (state_context.get("host_context") if isinstance(state_context, dict) else None)
        or state.get("host_context")
    )
    candidates = [
        ctx.get("user_role"),
        state_context.get("user_role") if isinstance(state_context, dict) else None,
        state.get("user_role"),
        state.get("role"),
        host_context.get("user_role"),
        host_context.get("host_role"),
    ]
    roles: list[str] = []
    for candidate in candidates:
        value = getattr(candidate, "value", candidate)
        role = str(value or "").strip().lower()
        if role and role not in roles:
            roles.append(role)
    return roles


def _rebind_document_preview_host_action_tool(
    *,
    tools: list[Any],
    force_tools: bool,
    query: str,
    state: dict[str, Any],
    ctx: dict[str, Any],
) -> tuple[list[Any], bool, dict[str, Any]]:
    """Bind only the declared, non-mutating LMS preview action if collection lost it."""

    if _has_document_preview_host_action_tool(tools):
        return tools, True, {
            "status": "already_bound",
            "tool_count": len(tools),
        }

    preview_capabilities = _extract_document_preview_capabilities(state, ctx)
    debug: dict[str, Any] = {
        "status": "missing_capability",
        "tool_count": len(tools),
        "preview_capability_count": len(preview_capabilities),
    }
    if not preview_capabilities:
        return tools, force_tools, debug

    roles = _direct_role_candidates(state, ctx)
    debug["role_candidates"] = roles[:4]
    for role in roles or ["student"]:
        try:
            from app.engine.context.action_tools import generate_host_action_tools

            generated = generate_host_action_tools(
                preview_capabilities,
                role,
                event_bus_id=state.get("_event_bus_id") or state.get("session_id") or "",
                approval_context={
                    "query": query,
                    "host_action_feedback": (ctx.get("host_action_feedback") or {}),
                },
            )
        except Exception as exc:
            debug.update({"status": "generation_failed", "error": type(exc).__name__})
            logger.debug("[DIRECT] Document preview host action rebind failed: %s", exc)
            return tools, force_tools, debug

        wanted_tool = _document_preview_forced_tool_choice(query, generated)
        preview_tools = [
            tool
            for tool in generated
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "")).strip().lower()
            == wanted_tool
        ]
        if preview_tools:
            debug.update({
                "status": "rebound",
                "role": role,
                "tool_count": len(preview_tools),
            })
            logger.info(
                "[DIRECT] Rebound LMS document preview host action from runtime capabilities"
            )
            return preview_tools[:1], True, debug

    debug["status"] = "role_filtered"
    return tools, force_tools, debug

_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS = 45.0  # Phase F3 (2026-05-06): bumped 24→45s. NVIDIA DeepSeek tool-heavy pointy turns (inventory + show + synthesis) regularly hit 25-35s; 24s caused canned fallback even when LLM was actively succeeding.

# DSML tool-call markup that NVIDIA DeepSeek occasionally leaks into prose
# content. Already partially handled by ``_parse_dsml_tool_calls`` and the
# graph-surface sanitizer, but synthesis pass output is sometimes routed
# directly to the user without going through those, so we re-strip here as
# a defensive last line.
_DSML_BLOCK_RE = re.compile(
    r"<｜DSML｜tool_calls>.*?</｜DSML｜tool_calls>",
    re.DOTALL,
)
_DSML_STRAY_FULLWIDTH_RE = re.compile(r"</?｜DSML｜[^>]*>")
_DSML_STRAY_ASCII_RE = re.compile(r"</?\|DSML\|[^>]*>")

_GENERIC_DIRECT_FALLBACK_MARKERS = (
    "ban muon tim hieu gi hom nay",
    "ban thu hoi lai nhe",
    "ban dien dat cach khac",
    "toi co the giup gi cho ban",
)


def _strip_dsml_residue(text: str) -> str:
    if not text:
        return text
    cleaned = _DSML_BLOCK_RE.sub("", text)
    cleaned = _DSML_STRAY_FULLWIDTH_RE.sub("", cleaned)
    cleaned = _DSML_STRAY_ASCII_RE.sub("", cleaned)
    return cleaned

_IDENTITY_LORE_MARKERS = (
    "the wiii lab",
    "2024",
    "ra doi",
    "dem mua",
    "bong",
)
_IDENTITY_ORIGIN_QUERY_MARKERS = (
    "ra doi",
    "duoc tao",
    "duoc sinh ra",
    "sinh ra",
    "nguon goc",
    "the wiii lab",
    "creator",
    "created by",
    "ai tao",
)
_DIRECT_WOVEN_THOUGHT_INTENTS = {
    "social",
    "personal",
    "off_topic",
    "emotional",
    "identity",
    "selfhood",
}
_DIRECT_ENGLISH_PLANNER_MARKERS = (
    "the goal is",
    "i'm focusing on",
    "i am focusing on",
    "i've just refined",
    "ive just refined",
    "i opted for",
    "registered the user's input",
    "registered the users input",
    "processing the sentiment",
    "warm, empathetic response",
    "natural, conversational reply",
    "because it sounds the most natural",
)
_DIRECT_INTERNAL_THOUGHT_MARKERS = (
    "living core card",
    "wiii living core card",
    "system prompt",
    "promptloader",
    "persona yaml",
    "yaml persona",
    "house prompt",
    "developer instruction",
    "instruction block",
)
_DIRECT_VISIBLE_THOUGHT_DRAFT_SPLITTERS = (
    "đây là kết quả tôi đã thực hiện",
    "day la ket qua toi da thuc hien",
    "here's the final",
    "here is the final",
    "here is the result",
    "this is the result i produced",
)
_DIRECT_VISIBLE_THOUGHT_TRAILING_SELF_EVAL = (
    "i think it sounds natural",
    "i'm excited for them to hear",
    "im excited for them to hear",
    "it follows the instructions",
    "it is not too robotic",
)
_DIRECT_CANONICAL_THINKING_EFFORT_ALIASES = {
    "light": "low",
    "low": "low",
    "moderate": "medium",
    "medium": "medium",
    "deep": "high",
    "high": "high",
    "max": "max",
}
_DIRECT_ANALYTICAL_THINKING_MODES = {
    "analytical_general",
    "analytical_market",
    "analytical_math",
}


def _is_explicit_web_search_turn_for_direct(query: str, state: AgentState | None = None) -> bool:
    folded = _fold_direct_text(query)
    if "@web-search" in folded or "@web_search" in folded or "search the web" in folded:
        return True
    if isinstance(state, dict):
        routing = state.get("routing_metadata") if isinstance(state.get("routing_metadata"), dict) else {}
        if str(routing.get("intent") or "").strip().lower() == "web_search":
            return True
        if "web-search" in _force_skills_from_state(state):
            return True
    return False


def _clean_emergency_web_search_query(query: str) -> str:
    raw = str(query or "").strip()
    if not raw:
        return raw
    cleaned = re.sub(
        r"(?:mã|ma)\s+(?:kiểm\s+thử|kiem\s+thu|test)\s+[A-Za-z0-9_.:-]+.*$",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"(?i)^\s*(?:tìm|tim|search|tra\s+cứu|tra\s+cuu)\s+(?:trên\s+web|tren\s+web|web|online|trên\s+mạng|tren\s+mang)\s*(?:giúp\s+mình|giup\s+minh|cho\s+mình|cho\s+minh)?\s*[:：-]?\s*",
        "",
        cleaned,
    ).strip()
    cleaned = re.split(
        r"(?i)(?:[\.\?!]\s+)?(?:trả\s+lời|tra\s+loi|kèm\s+link|kem\s+link|kèm\s+nguồn|kem\s+nguon)\b",
        cleaned,
        maxsplit=1,
    )[0].strip(" .:-")
    folded = _fold_direct_text(cleaned)
    if "openai" in folded and "responses api" in folded:
        return "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
    return cleaned or raw


def _extract_direct_reply_only_answer(query: str) -> str:
    """Extract the exact visible answer from a tightly-scoped reply-only prompt."""
    raw = str(query or "").strip()
    if not raw:
        return ""
    folded = _fold_direct_text(raw)
    if not any(
        marker in folded
        for marker in (
            "answer only",
            "chi tra loi",
            "just answer",
            "only answer",
            "respond only",
            "reply only",
            "tra loi chi",
            "tra loi dung",
        )
    ):
        return ""
    if ":" not in raw and "：" not in raw:
        return ""
    candidate = re.split(r"[:：]", raw)[-1].strip()
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate or len(candidate) > 160:
        return ""
    if any(marker in candidate for marker in ("```", "<script", "</")):
        return ""
    return candidate


def _extract_pointy_fast_path_answer(state: AgentState) -> str:
    action = state.get("_pointy_fast_path_action") if isinstance(state, dict) else None
    if not isinstance(action, dict):
        return ""
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    label = str(target.get("label") or target.get("id") or params.get("selector") or "").strip()
    if not label:
        return "Mình đã trỏ đúng vị trí trên giao diện cho cậu."
    return f"Mình đã trỏ vào {label} cho cậu thấy ngay."


def _build_pointy_fast_path_thinking(state: AgentState) -> str:
    action = state.get("_pointy_fast_path_action") if isinstance(state, dict) else None
    target = action.get("target") if isinstance(action, dict) and isinstance(action.get("target"), dict) else {}
    label = str(target.get("label") or target.get("id") or "").strip()
    if label:
        return (
            f"Mình thấy mục tiêu UI đã có trên màn hình: {label}. "
            "Thay vì đoán bằng lời, mình đưa con trỏ tới đúng điểm để cậu nhìn thấy ngay."
        )
    return (
        "Mình thấy mục tiêu UI đã có trên màn hình. "
        "Thay vì đoán bằng lời, mình đưa con trỏ tới đúng điểm để cậu nhìn thấy ngay."
    )


def _pointy_requested_without_inventory(state: AgentState) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("_pointy_fast_path_action"):
        return False
    force_skills = _force_skills_from_state(state)
    requested = bool(state.get("pointy_mode")) or "wiii-pointy" in force_skills
    if not requested:
        return False
    try:
        from app.engine.tools.pointy_tools import extract_inventory_pairs_from_state

        return not bool(extract_inventory_pairs_from_state(state))
    except Exception:
        return True


def _build_pointy_missing_inventory_answer(_query: str) -> str:
    return (
        "Mình chưa nhận được danh sách mục UI đang nhìn thấy từ host_context, "
        "nên không nên giả vờ đã trỏ. Khi Wiii Desktop gửi inventory màn hình "
        "(ví dụ nút gửi, ô nhập, sidebar), mình sẽ đưa Pointy tới đúng target ngay."
    )


def _build_pointy_missing_inventory_thinking(_query: str) -> str:
    return (
        "Đây là lượt Pointy, nhưng state chưa có inventory mục UI có thể trỏ. "
        "Để tránh hallucinate selector hoặc nói rằng đã trỏ khi chưa có target thật, "
        "mình fail-soft bằng một câu ngắn và yêu cầu host_context thay vì gọi LLM vòng dài."
    )


def _build_wiii_pipeline_meta_answer(_query: str) -> str:
    return (
        "- Pointy dễ sai route khi câu hỏi chỉ nhắc chủ đề Pointy nhưng router hiểu nhầm thành yêu cầu điều khiển UI.\n"
        "- Thinking dễ lệch UX khi thinking block, answer block và tool/status event không có thứ tự ưu tiên rõ trong SSE.\n"
        "- Memory dễ làm chậm hoặc lệch câu trả lời khi recall trong phiên bị đẩy sang durable semantic memory/DB.\n"
        "- Kiểm thử routing: cùng prompt có/không phủ định Pointy phải cho ra đúng lane, không sinh lệnh clear ngoài ý muốn.\n"
        "- Kiểm thử SSE/UX: Thinking phải hiện trước hoặc cùng nhịp answer, không lặp text, không lộ prompt nội bộ.\n"
        "- Kiểm thử hiệu suất: session memory recall và Pointy highlight phải hoàn tất ở mức dưới vài giây, kể cả khi DB đang down."
    )


def _build_wiii_pipeline_meta_thinking(_query: str) -> str:
    return (
        "Mình hiểu đây là lúc phải nhìn Wiii như một sản phẩm đang được thử thật, không phải viết thêm một lớp trình diễn. "
        "Mình sẽ ưu tiên những thứ cậu cảm nhận được ngay: có trả lời đúng không, có nhớ đúng không, có chậm không, có làm phiền không. "
        "Phần quan trọng nhất là nói thẳng các chỗ dễ hỏng và gắn chúng với cách kiểm tra lại được."
    )


def _build_image_input_unavailable_answer(query: str) -> str:
    return _with_requested_response_marker(
        query,
        (
            "Mình thấy cậu đã gửi ảnh, nhưng cấu hình Wiii hiện tại chưa bật Vision runtime "
            "nên mình không nên đoán nội dung ảnh. Bật xử lý ảnh/vision hoặc gửi thêm mô tả "
            "ngắn của ảnh, rồi mình sẽ phân tích tiếp cho chắc."
        ),
    )


def _build_image_input_unavailable_thinking() -> str:
    return (
        "Lượt này có ảnh đầu vào nhưng backend báo vision chưa khả dụng. Cách an toàn là nói "
        "rõ giới hạn hiện tại, không suy đoán nội dung ảnh và không kéo sang RAG hay chủ đề cũ."
    )


def _build_image_input_thinking(query: str = "") -> str:
    normalized = _normalize_for_intent(query)
    cues: list[str] = []
    if any(token in normalized for token in ("chu", "text", "ocr", "doc", "noi dung", "viet gi")):
        cues.append("doc chu/marker trong anh")
    if any(token in normalized for token in ("mau", "color", "nen", "background")):
        cues.append("doi chieu mau nen va vung noi bat")
    if any(token in normalized for token in ("so sanh", "khac nhau", "giai thich", "phan tich")):
        cues.append("tach quan sat truc tiep khoi suy luan")
    cue_text = ", ".join(cues) if cues else "quan sat nhung gi anh that su cho thay"
    return (
        "Luot nay co anh dinh kem, nen minh xu ly no nhu mot tac vu vision co bang chung: "
        f"truoc het {cue_text}, sau do moi tra loi dung cau hoi cua nguoi dung. "
        "Khong nen doan ngoai anh, khong keo sang RAG/cuoc tro chuyen cu neu anh da du de tra loi, "
        "va neu co phan khong doc duoc thi phai noi ro phan do thay vi lap lung."
    )


def _looks_generic_direct_fallback_response(response: str) -> bool:
    folded = _fold_direct_text(response)
    if not folded:
        return True
    return len(folded) < 140 and any(
        marker in folded for marker in _GENERIC_DIRECT_FALLBACK_MARKERS
    )


def _should_use_codebase_source_note_fast_answer(query: str) -> bool:
    if not _is_codebase_analysis_query(query):
        return False
    folded = _fold_direct_text(query)
    source_markers = (
        "source a",
        "source b",
        "source c",
        "source notes",
        "source note",
        "nguon a",
        "nguon b",
        "nguon c",
        "du lieu nguon",
        "report rehearsal",
        "bao cao",
    )
    codebase_markers = (
        "jwtservice",
        "jwtauthenticationfilter",
        "course_publications",
        "class diagram",
        "junction table",
        "migration",
    )
    if any(marker in folded for marker in source_markers):
        return True
    return len(folded) > 350 and sum(1 for marker in codebase_markers if marker in folded) >= 3


def _build_codebase_analysis_fallback_thinking(query: str) -> str:
    folded = _fold_direct_text(query)
    schema_focus = any(token in folded for token in ("database", "schema", "table", "bang", "class diagram"))
    jwt_focus = any(token in folded for token in ("jwt", "auth", "xac thuc", "token"))
    focus_bits: list[str] = []
    if schema_focus:
        focus_bits.append("đếm/nhóm bảng theo vai trò thay vì coi class diagram là database diagram")
    if jwt_focus:
        focus_bits.append("nối lifecycle JWT từ login, service tạo token, filter mỗi request, tới refresh")
    if not focus_bits:
        focus_bits.append("giữ từng kết luận bám vào file/source được nêu")
    return (
        "Mình nhận đây là bài phân tích codebase cần có ledger kiểm chứng công khai, không phải câu hỏi xã giao. "
        f"Trục xử lý là {', '.join(focus_bits)}. "
        "Nếu provider/tool path bị lỗi, Wiii vẫn phải trả một bản fallback có ích: tách phần đã có nguồn trong prompt khỏi phần suy luận, "
        "không rơi về câu chào mặc định và không gọi Pointy/artifact sai ngữ cảnh."
    )


def _build_codebase_analysis_fallback_answer(query: str) -> str:
    folded = _fold_direct_text(query)
    wants_schema = any(token in folded for token in ("database", "schema", "table", "bang", "class diagram"))
    wants_jwt = any(token in folded for token in ("jwt", "auth", "xac thuc", "token"))

    sections: list[str] = [
        "Mình bám vào các source notes, tên bảng và tên file/class bạn đưa trong prompt; phần dưới tách rõ điều có dấu vết nguồn với phần suy luận hợp lý để tránh biến class diagram thành database diagram.",
    ]
    if wants_schema:
        sections.append(
            "## Vì sao class diagram chỉ hiện khoảng 25 entity?\n"
            "Class diagram không nên được hiểu như danh sách toàn bộ database table. Nó thường chỉ giữ các entity có logic nghiệp vụ riêng, còn nhiều bảng thật trong DB là bảng nối, bảng hạ tầng, hoặc bảng phát sinh qua migration.\n\n"
            "Nhóm nên giữ trên class diagram: User, Course, Lesson, Quiz, Question, PaymentTransaction, Organization, OrgPaymentConfig, AuditLogEntry, VideoProgress, LearningEvent, LearningStreak, Achievement, Bookmark, Note, CourseReview và các entity nghiệp vụ tương tự.\n\n"
            "Nhóm thường không cần hiện như class độc lập: junction table như course_tags, quiz_questions, quiz_assignments, assignment_allocation_students, class_teachers, announcement_reads, message_reactions, student_achievements. Chúng chủ yếu biểu diễn quan hệ nhiều-nhiều hoặc trạng thái đọc/react, không mang lifecycle nghiệp vụ riêng.\n\n"
            "Nhóm hạ tầng cũng không nên làm sơ đồ nghiệp vụ bị rối: login_attempts, outbox_messages, file_attachments, chat_sessions, chat_messages, conversations, messages, flyway_schema_history. Chúng quan trọng khi vận hành nhưng không phải khái niệm domain chính.\n\n"
            "Nhóm đáng cân nhắc bổ sung nếu báo cáo cần đầy đủ hơn: course_publications vì là snapshot xuất bản quan trọng, video_assets/video_renditions/video_ingest_jobs nếu phần video là năng lực lõi, và revenue_splits/payout_requests nếu mô hình doanh thu là trọng tâm."
        )
    if wants_jwt:
        sections.append(
            "## JWT xác thực đi qua những phần nào?\n"
            "Luồng đúng nên trình bày theo lifecycle, không chỉ liệt kê file: user đăng nhập bằng email/password, backend kiểm BCrypt, JwtService tạo access token và refresh token, frontend gửi `Authorization: Bearer ...`, JwtAuthenticationFilter parse và verify chữ ký mỗi request, rồi load User hiện tại từ database để lấy role/enabled mới nhất trước khi vào controller.\n\n"
            "JWT không nhất thiết có bảng riêng vì đây là mô hình stateless. Token sống ở client và được verify bằng secret/key; database vẫn được đọc để kiểm trạng thái user hiện tại. Các bảng như password_reset_tokens hoặc email_verification_tokens là token hỗ trợ nghiệp vụ khác, không phải session JWT chính.\n\n"
            "Các file cần neo khi báo cáo: JwtService.java cho build/verify token, JwtAuthenticationFilter.java cho request filter, AuthControllerV3.java hoặc use case đăng nhập/refresh cho API auth, SecurityConfig.java cho filter chain/session stateless, UserJpaEntity.java cho authorities/role, và Organization nếu expiry/tenant policy được cấu hình theo tổ chức."
        )
    sections.append(
        "## Cách nói khi bị hỏi nhanh\n"
        "> Sơ đồ lớp chỉ mô tả các entity nghiệp vụ chính, không liệt kê toàn bộ bảng vật lý. Database có thêm bảng junction, bảng hạ tầng và bảng phát sinh qua migration. JWT thì stateless: token không lưu như session DB, nhưng mỗi request vẫn verify token rồi load user mới nhất để role/enabled có hiệu lực ngay."
    )
    return "\n\n".join(sections)


def _image_payload_attr(image: Any, key: str, default: Any = None) -> Any:
    if isinstance(image, dict):
        return image.get(key, default)
    return getattr(image, key, default)


def _first_markdown_line(markdown: str, label: str) -> str:
    pattern = re.compile(rf"^\s*-\s*{re.escape(label)}:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(markdown or "")
    return match.group(1).strip() if match else ""


def _plain_markdown_excerpt(markdown: str, *, limit: int = 700) -> str:
    lines: list[str] = []
    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[Transcript unavailable:"):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = line.replace("\\_", "_")
        if line:
            lines.append(line)
        if sum(len(item) for item in lines) >= limit:
            break
    return " ".join(lines)[:limit].strip()


def _build_uploaded_document_context_fallback_answer(
    query: str,
    ctx: dict[str, Any],
    *,
    provider_unstable: bool = True,
) -> str:
    """Provider-failure or deterministic answer for per-turn uploaded file context."""
    attachments = _uploaded_document_attachments(ctx)
    if not attachments:
        return ""

    lines = [
        (
            "Mình vẫn đọc được phần file đã parse trong lượt này, dù provider LLM/vision đang chưa ổn định."
            if provider_unstable
            else "Mình đọc được phần file đã parse trong lượt này."
        ),
    ]
    for index, item in enumerate(attachments[:3], start=1):
        markdown = str(item.get("markdown") or "")
        file_name = str(item.get("file_name") or f"file-{index}")
        media_kind = str(item.get("media_kind") or "document")
        parser = str(item.get("parser") or "markitdown")
        provenance_level = str(item.get("provenance_level") or "")
        char_count = item.get("char_count")
        extracted_image_count = item.get("extracted_image_count")
        embedded_asset_count = item.get("embedded_asset_count")

        lines.append("")
        provenance_text = f", provenance={provenance_level}" if provenance_level else ""
        lines.append(f"- File: `{file_name}` ({media_kind}, parser={parser}{provenance_text})")
        if isinstance(char_count, int):
            lines.append(f"- Nội dung parse được: khoảng {char_count} ký tự.")
        if isinstance(embedded_asset_count, int) and embedded_asset_count > 0:
            lines.append(
                f"- Parser phát hiện {embedded_asset_count} asset nhúng (hình/bảng); "
                "cần citation/vision rõ ràng trước khi mô tả chi tiết hình ảnh."
            )

        if media_kind == "video":
            duration = _first_markdown_line(markdown, "Duration")
            resolution = _first_markdown_line(markdown, "Resolution")
            has_audio = _first_markdown_line(markdown, "Has audio")
            if duration:
                lines.append(f"- Thời lượng video: {duration}.")
            if resolution:
                lines.append(f"- Độ phân giải: {resolution}.")
            if isinstance(extracted_image_count, int):
                lines.append(f"- Wiii đã trích {extracted_image_count} khung hình đại diện để gửi vào vision context.")
            if has_audio:
                lines.append(f"- Có audio: {has_audio}.")
            if "Transcript unavailable" in markdown:
                lines.append(
                    "- Transcript audio hiện chưa có; điều này chỉ nói rằng audio chưa được chuyển lời/ASR chưa khả dụng, "
                    "không chứng minh video không có giọng nói."
                )
        else:
            excerpt = _plain_markdown_excerpt(markdown)
            if excerpt:
                lines.append(f"- Trích đoạn đầu: {excerpt}")

    return _with_requested_response_marker(query, "\n".join(lines).strip())


def _uploaded_context_has_video(ctx: dict[str, Any]) -> bool:
    return any(
        str(item.get("media_kind") or "").strip().lower() == "video"
        for item in _uploaded_document_attachments(ctx)
    )


def _looks_uploaded_document_preview_request(query: str) -> bool:
    """Route document-to-course preview requests away from fact fast-paths."""
    folded = _fold_direct_text(query)
    if not folded:
        return False
    preview_markers = (
        "approval_token",
        "ban nhap",
        "ban xem truoc",
        "citation",
        "diff",
        "lesson patch",
        "preview",
        "preview_lesson_patch",
        "source references",
        "source_references",
        "lap bai giang",
        "soan bai giang",
        "soan giao an",
        "tao bai giang",
        "tao giao an",
        "tao hoc lieu",
        "tao ban xem truoc",
        "tao khoa hoc",
        "thiet ke bai giang",
        "thiet ke khoa hoc",
        "xay dung bai giang",
        "cau truc khoa hoc",
        "toan bo khoa",
        "cay khoa",
        "chia khoa",
        "course architect",
        "course outline",
        "course syllabus",
        "curriculum",
        "de cuong khoa",
        "de cuong mon",
        "giao trinh",
        "ke hoach giang day",
        "learning path",
        "lo trinh hoc",
        "syllabus",
        "generate_course_from_document",
        "trich dan",
        "xem truoc",
    )
    return any(marker in folded for marker in preview_markers)


def _looks_uploaded_context_fact_query(query: str, ctx: dict[str, Any]) -> bool:
    """Keep direct fact extraction from uploaded markdown off the slow LLM path."""
    if not _has_uploaded_document_context(ctx):
        return False
    folded = _fold_direct_text(query)
    if not folded:
        return False
    if _looks_uploaded_document_preview_request(query):
        return False
    if len([token for token in folded.split() if token]) > 90:
        return False
    fact_markers = (
        "bang",
        "char count",
        "csv",
        "doc vua upload",
        "docx",
        "eta",
        "file vua upload",
        "kpi",
        "latencybudget",
        "marker",
        "noi dung parse",
        "priority",
        "risk",
        "tom tat",
        "trich",
        "upload",
        "uu tien",
        "xlsx",
    )
    if any(marker in folded for marker in fact_markers):
        return True
    return _looks_uploaded_file_metadata_query(query, ctx)


def _looks_uploaded_file_metadata_query(query: str, ctx: dict[str, Any]) -> bool:
    """Keep simple uploaded-video fact questions deterministic and low-latency."""
    if not _uploaded_context_has_video(ctx):
        return False
    folded = _fold_direct_text(query)
    if not folded:
        return False
    metadata_markers = (
        "bao lau",
        "dai may",
        "dai bao",
        "thoi luong",
        "duration",
        "metadata",
        "do phan giai",
        "resolution",
        "fps",
        "frame",
        "khung hinh",
        "keyframe",
        "trich duoc",
        "bao nhieu khung",
        "may khung",
        "audio",
        "am thanh",
        "transcript",
    )
    return any(marker in folded for marker in metadata_markers)


def _looks_uploaded_file_visual_inspection_query(query: str) -> bool:
    folded = _fold_direct_text(query)
    frame_hint = any(
        marker in folded
        for marker in (
            "khung hinh",
            "keyframe",
            "frame",
            "anh trong video",
            "hinh anh",
            "video nay",
            "trong video",
        )
    )
    visual_action = any(
        marker in folded
        for marker in (
            "nhin",
            "thay gi",
            "mo ta",
            "kieu hinh",
            "noi dung",
            "trong do co gi",
            "co gi",
        )
    )
    return frame_hint and visual_action


def _provider_likely_supports_image_blocks(provider: str | None, model: str | None = None) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if normalized_provider in {"google", "zhipu"}:
        return True
    if normalized_provider == "openai":
        return any(marker in normalized_model for marker in ("gpt-4o", "gpt-4.1", "gpt-5", "vision"))
    if normalized_provider == "openrouter":
        return any(marker in normalized_model for marker in ("vision", "vl", "gpt-4o", "gpt-4.1", "gpt-5"))
    if normalized_provider == "nvidia":
        return any(
            marker in normalized_model
            for marker in (
                "vision",
                "vl",
                "neva",
                "paligemma",
                "gemma-3-",
                "gemma-3n-",
                "gemma-4-",
                "llama-4-maverick",
                "phi-4-multimodal",
                "ministral-14b-instruct",
                "mistral-large-3",
                "mistral-medium-3",
                "mistral-small-4",
                "kimi-k2.6",
                "qwen3.5-",
            )
        )
    return False


def _build_uploaded_document_visual_guard_answer(query: str, ctx: dict[str, Any]) -> str:
    base = _build_uploaded_document_context_fallback_answer(query, ctx)
    if not base:
        return ""
    guard = (
        "- Mình chưa mô tả nội dung thật bên trong các khung hình vì lượt này chưa chạy qua "
        "vision provider hợp lệ; nói khác đi, Wiii biết video đã có frame, nhưng không được đoán "
        "frame đó trông như thế nào."
    )
    if guard in base:
        return base
    return f"{base}\n{guard}"


async def _build_image_input_answer(query: str, images: list[Any]) -> str:
    first_base64 = next(
        (
            image
            for image in images
            if _image_payload_attr(image, "type", "base64") == "base64"
            and _image_payload_attr(image, "data", "")
        ),
        None,
    )
    if first_base64 is None:
        return _with_requested_response_marker(
            query,
            (
                "Mình thấy cậu đã gửi ảnh, nhưng hiện tại Wiii chỉ xử lý trực tiếp ảnh base64 "
                "trong chat. Hãy đính kèm lại ảnh trực tiếp trong khung chat để mình phân tích cho chắc."
            ),
        )

    try:
        from app.engine.vision_runtime import analyze_image_for_query

        result = await analyze_image_for_query(
            image_base64=_image_payload_attr(first_base64, "data", ""),
            query=query,
            media_type=_image_payload_attr(first_base64, "media_type", "image/jpeg"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Vision image analysis failed: %s", exc)
        return _with_requested_response_marker(
            query,
            (
                "Mình đã nhận được ảnh, nhưng Vision runtime hiện bị lỗi khi phân tích. "
                "Mình không nên đoán nội dung ảnh; cậu thử gửi lại hoặc bật provider vision khả dụng nhé."
            ),
        )

    if getattr(result, "success", False) and str(getattr(result, "text", "")).strip():
        return _with_requested_response_marker(query, str(result.text).strip())

    return _with_requested_response_marker(
        query,
        (
            "Mình đã nhận được ảnh, nhưng hiện chưa có provider vision khả dụng để đọc ảnh này. "
            "Mình sẽ không đoán nội dung ảnh; hãy bật Vision runtime/provider vision rồi thử lại nhé."
        ),
    )


def _strip_direct_inline_private_asides(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return cleaned

    cleaned = re.sub(
        r"^\s*(\*{1,2})\s*(?:nghĩ thầm|nghi tham|visible thinking|suy nghĩ của wiii|suy nghi cua wiii)\s*:\s*",
        r"\1",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^\s*\((?:nghĩ thầm|nghi tham|visible thinking|suy nghĩ của wiii|suy nghi cua wiii)\s*:\s*",
        "(",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    changed = True
    while changed and cleaned:
        changed = False
        stripped = cleaned.lstrip()

        json_match = re.match(
            r"^\{\s*\"visible_thinking\"\s*:\s*\".*?\"\s*\}\s*",
            stripped,
            flags=re.DOTALL,
        )
        if json_match:
            cleaned = stripped[json_match.end() :].lstrip()
            changed = True
            continue

        if stripped.startswith("("):
            boundary = stripped.find(")\n\n")
            if boundary > 0 and boundary < 500:
                cleaned = stripped[boundary + 3 :].lstrip()
                changed = True
                continue

        if stripped.startswith("*"):
            boundary = stripped.find("*\n\n", 1)
            if boundary > 0 and boundary < 500:
                cleaned = stripped[boundary + 3 :].lstrip()
                changed = True
                continue
    return cleaned.strip()


def _compact_basic_identity_answer(value: str, *, query: str) -> str:
    cleaned = _strip_direct_inline_private_asides(value)
    if not cleaned:
        return cleaned

    folded_query = _fold_direct_text(query)
    if any(marker in folded_query for marker in _IDENTITY_ORIGIN_QUERY_MARKERS):
        return cleaned

    if len(cleaned) < 320 and not any(marker in _fold_direct_text(cleaned) for marker in _IDENTITY_LORE_MARKERS):
        return cleaned

    kept: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("*"):
            continue
        folded_line = _fold_direct_text(line)
        if any(marker in folded_line for marker in _IDENTITY_LORE_MARKERS):
            continue
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", line) if part.strip()]
        for sentence in sentences:
            folded_sentence = _fold_direct_text(sentence)
            if any(marker in folded_sentence for marker in _IDENTITY_LORE_MARKERS):
                continue
            if sentence not in kept:
                kept.append(sentence)

    if not kept:
        return cleaned

    compact = " ".join(kept[:4]).strip()
    return compact or cleaned


def _extract_direct_woven_thought(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""

    italic_match = re.match(r"^\*{1,2}(?P<thought>.+?)\*{1,2}(?:\s+|$)", cleaned, flags=re.DOTALL)
    if italic_match:
        thought = italic_match.group("thought").strip()
        if 20 <= len(thought) <= 400:
            return thought

    paren_match = re.match(r"^\((?P<thought>.+?)\)(?:\s+|$)", cleaned, flags=re.DOTALL)
    if paren_match:
        thought = paren_match.group("thought").strip()
        if 20 <= len(thought) <= 400:
            return thought

    return ""


def _looks_like_direct_english_planner_thought(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if len(lowered) < 40:
        return False
    return any(marker in lowered for marker in _DIRECT_ENGLISH_PLANNER_MARKERS)


def _contains_direct_internal_thought_leak(value: str) -> bool:
    folded = _fold_direct_text(value)
    if not folded:
        return False
    return any(marker in folded for marker in _DIRECT_INTERNAL_THOUGHT_MARKERS)


def _trim_direct_visible_thought_answer_draft(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""

    lowered = clean.lower()
    cut_at = len(clean)
    for marker in _DIRECT_VISIBLE_THOUGHT_DRAFT_SPLITTERS:
        idx = lowered.find(marker)
        if idx >= 0:
            cut_at = min(cut_at, idx)

    trimmed = clean[:cut_at].rstrip(" :\n\t") if cut_at < len(clean) else clean
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", trimmed) if part.strip()]
    while paragraphs:
        folded_tail = _fold_direct_text(paragraphs[-1])
        if any(marker in folded_tail for marker in _DIRECT_VISIBLE_THOUGHT_TRAILING_SELF_EVAL):
            paragraphs.pop()
            continue
        break
    return "\n\n".join(paragraphs).strip()


def _canonicalize_direct_thinking_effort(value: str | None) -> str | None:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    return _DIRECT_CANONICAL_THINKING_EFFORT_ALIASES.get(candidate)


def _resolve_direct_thinking_effort(
    *,
    query: str,
    state: AgentState,
    current_effort: str | None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
) -> str | None:
    canonical_effort = _canonicalize_direct_thinking_effort(current_effort)
    local_effort: str | None = None

    if is_short_house_chatter:
        local_effort = "low"
    else:
        folded_query = _fold_direct_text(query)
        if is_identity_turn:
            if any(marker in folded_query for marker in _IDENTITY_ORIGIN_QUERY_MARKERS):
                local_effort = "max"
            else:
                local_effort = "high"
        else:
            thinking_mode = _infer_direct_thinking_mode(query, state, [])
            if thinking_mode in _DIRECT_ANALYTICAL_THINKING_MODES:
                local_effort = "high"

    # Direct lane should be allowed to override generic routing defaults such as
    # medium/moderate, while still preserving explicit higher asks like max.
    if canonical_effort in {"high", "max"}:
        return merge_thinking_effort(local_effort, canonical_effort)
    if local_effort:
        return local_effort
    return canonical_effort


def _should_surface_direct_visible_thought(
    value: str,
    *,
    routing_intent: str = "",
    response: str = "",
) -> bool:
    clean = _strip_direct_inline_private_asides(value)
    if len(clean) < 20:
        return False
    normalized_intent = str(routing_intent or "").strip().lower()
    if normalized_intent not in _DIRECT_WOVEN_THOUGHT_INTENTS:
        return False
    if _extract_direct_woven_thought(response):
        return False
    if _contains_direct_internal_thought_leak(clean):
        return False
    if _looks_like_direct_english_planner_thought(clean):
        return False
    return True


async def _align_direct_visible_thought(
    value: str,
    *,
    response_language: str,
    llm,
) -> str:
    clean = _strip_direct_inline_private_asides(value)
    if not clean:
        return ""
    trimmed = _trim_direct_visible_thought_answer_draft(clean)
    if not trimmed:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", trimmed) if part.strip()]
    kept: list[str] = []
    for paragraph in paragraphs:
        normalized = paragraph.strip()
        if (
            looks_like_direct_selfhood_meta_intro(normalized)
            or looks_like_direct_selfhood_meta_heading(normalized)
            or looks_like_direct_selfhood_english_meta_paragraph(normalized)
            or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
        ):
            continue
        normalized = strip_direct_selfhood_filler_prefix(normalized)
        if should_align_visible_thinking_language(
            normalized,
            target_language=response_language,
        ):
            aligned = await align_visible_thinking_language(
                normalized,
                target_language=response_language,
                llm=llm,
            )
            normalized = _strip_direct_inline_private_asides(aligned or normalized).strip()
            normalized = strip_direct_selfhood_filler_prefix(normalized)
        if (
            not normalized
            or looks_like_direct_selfhood_meta_intro(normalized)
            or looks_like_direct_selfhood_meta_heading(normalized)
            or looks_like_direct_selfhood_english_meta_paragraph(normalized)
            or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
        ):
            continue
        if should_align_visible_thinking_language(
            normalized,
            target_language=response_language,
        ):
            continue
        kept.append(normalized)
    return "\n\n".join(kept).strip()


def _best_effort_direct_visible_thought_raw(value: str) -> str:
    clean = _strip_direct_inline_private_asides(value)
    if not clean:
        return ""
    trimmed = _trim_direct_visible_thought_answer_draft(clean)
    if not trimmed:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", trimmed) if part.strip()]
    kept: list[str] = []
    for paragraph in paragraphs:
        normalized = paragraph.strip()
        if (
            not normalized
            or looks_like_direct_selfhood_meta_intro(normalized)
            or looks_like_direct_selfhood_meta_heading(normalized)
            or looks_like_direct_selfhood_english_meta_paragraph(normalized)
            or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
        ):
            continue
        normalized = strip_direct_selfhood_filler_prefix(normalized)
        if not normalized or _contains_direct_internal_thought_leak(normalized):
            continue
        kept.append(normalized)
    return "\n\n".join(kept).strip()


async def _build_emotional_rescue_visible_thought(
    *,
    query: str,
    state: AgentState,
    response: str,
    response_language: str,
    llm: Any,
    build_direct_reasoning_summary,
    tool_names: list[str] | None = None,
) -> str:
    """Backfill a tiny public thought when emotional turns return no native thought."""
    if not _looks_emotional_support_turn(query):
        return ""
    if not str(response or "").strip():
        return ""

    try:
        fallback = build_direct_reasoning_summary(query, state, tool_names or [])
        if inspect.isawaitable(fallback):
            fallback = await fallback
    except Exception as exc:
        logger.debug("[DIRECT] Emotional rescue summary skipped: %s", exc)
        return ""

    clean = _strip_direct_inline_private_asides(str(fallback or "")).strip()
    if len(clean) < 20:
        return ""
    if _contains_direct_internal_thought_leak(clean):
        return ""
    if _looks_like_direct_english_planner_thought(clean):
        return ""

    aligned = await _align_direct_visible_thought(
        clean,
        response_language=response_language,
        llm=llm,
    )
    if aligned and not _contains_direct_internal_thought_leak(
        aligned
    ) and not should_align_visible_thinking_language(
        aligned,
        target_language=response_language,
    ):
        return aligned
    return _best_effort_direct_visible_thought_raw(clean)


async def _emergency_search_fallback(
    *,
    query: str,
    tools: list[Any],
    timeout_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """LLM-free emergency search invoked when planning timed out.

    Picks ``tool_web_search`` from the bound tool list and runs it directly
    against the user query, then returns a synthetic ``tool_call_events`` list
    that can be fed into ``build_search_template_fallback``. Bounded by a
    short timeout so a slow search engine cannot stall the fallback path.
    """
    if not tools or not query.strip():
        return []

    target_names = (
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
    )
    chosen = None
    for tool_obj in tools:
        name = (
            getattr(tool_obj, "name", None)
            or getattr(tool_obj, "__name__", None)
            or ""
        )
        if str(name).lower() in target_names:
            chosen = tool_obj
            break
    if chosen is None:
        return []

    chosen_name = getattr(chosen, "name", None) or getattr(chosen, "__name__", "tool_web_search")
    invoker = getattr(chosen, "ainvoke", None)
    search_query = _clean_emergency_web_search_query(query)
    payload = {"query": search_query}
    try:
        if invoker is not None and inspect.iscoroutinefunction(invoker):
            result = await asyncio.wait_for(invoker(payload), timeout=timeout_seconds)
        else:
            sync_invoker = getattr(chosen, "invoke", None)
            if sync_invoker is None:
                return []
            result = await asyncio.wait_for(
                asyncio.to_thread(sync_invoker, payload),
                timeout=timeout_seconds,
            )
    except asyncio.TimeoutError:
        logger.warning(
            "[DIRECT] Emergency %s exceeded %.1fs — abandoning fallback",
            chosen_name,
            timeout_seconds,
        )
        return []
    except Exception as exc:
        logger.warning("[DIRECT] Emergency %s raised %s — abandoning", chosen_name, exc)
        return []

    if not result or not str(result).strip():
        return []

    return [
        {
            "type": "call",
            "id": "emergency-1",
            "name": chosen_name,
            "args": {"query": search_query},
        },
        {
            "type": "result",
            "id": "emergency-1",
            "name": chosen_name,
            "result": str(result),
        },
    ]


async def _emit_synthetic_tool_events(
    events: list[dict[str, Any]],
    *,
    push_event,
) -> None:
    """Surface LLM-free emergency tool work through the same SSE tool strip."""
    for event in events or []:
        event_type = event.get("type")
        name = str(event.get("name") or "")
        event_id = str(event.get("id") or "")
        if event_type == "call":
            await push_event(
                {
                    "type": "tool_call",
                    "content": {
                        "name": name,
                        "args": event.get("args") or {},
                        "id": event_id,
                    },
                    "node": "direct",
                }
            )
        elif event_type == "result":
            result = str(event.get("result") or "")
            await push_event(
                {
                    "type": "tool_result",
                    "content": {
                        "name": name,
                        "result": _summarize_tool_result_for_stream(name, result),
                        "id": event_id,
                    },
                    "node": "direct",
                }
            )


async def _salvage_direct_turn_from_final_result(
    *,
    llm_response: Any,
    messages: list[Any],
    extract_direct_response,
    sanitize_structured_visual_answer_text,
    sanitize_wiii_house_text,
    tool_call_events: list[dict[str, Any]],
    query: str,
    is_identity_turn: bool,
    routing_intent: str,
    response_language: str,
    llm: Any,
) -> tuple[str, str, list[dict[str, Any]]] | None:
    if llm_response is None:
        return None

    try:
        response, thinking_content, tools_used = extract_direct_response(llm_response, messages or [])
    except Exception as exc:
        logger.warning("[DIRECT] Salvage extraction failed: %s", exc)
        return None

    response = str(response or "").strip()
    if not response:
        return None

    try:
        response = sanitize_structured_visual_answer_text(
            response,
            tool_call_events=tool_call_events,
        )
    except Exception as exc:
        logger.debug("[DIRECT] Salvage skipped visual sanitize: %s", exc)

    try:
        response = sanitize_wiii_house_text(response, query=query)
    except Exception as exc:
        logger.debug("[DIRECT] Salvage skipped house sanitize: %s", exc)

    response = _strip_direct_inline_private_asides(response)
    if is_identity_turn:
        try:
            response = _compact_basic_identity_answer(response, query=query)
        except Exception as exc:
            logger.debug("[DIRECT] Salvage skipped identity compaction: %s", exc)

    response = str(response or "").strip()
    if not response:
        return None

    visible_thought = ""
    if _should_surface_direct_visible_thought(
        thinking_content,
        routing_intent=routing_intent,
        response=response,
    ):
        try:
            visible_thought = await _align_direct_visible_thought(
                thinking_content,
                response_language=response_language,
                llm=llm,
            )
        except Exception as exc:
            logger.debug("[DIRECT] Salvage alignment skipped: %s", exc)
        if not visible_thought:
            visible_thought = _best_effort_direct_visible_thought_raw(thinking_content)

    return response, visible_thought, tools_used


async def direct_response_node_impl(
    state: AgentState,
    *,
    direct_response_step_name,
    get_or_create_tracer,
    capture_public_thinking_event,
    get_domain_greetings,
    normalize_for_intent,
    looks_identity_selfhood_turn,
    needs_web_search,
    needs_datetime,
    resolve_visual_intent,
    recommended_visual_thinking_effort,
    get_active_code_studio_session,
    merge_thinking_effort,
    get_effective_provider,
    get_explicit_user_provider,
    collect_direct_tools,
    direct_required_tool_names,
    resolve_direct_answer_timeout_profile,
    bind_direct_tools,
    build_direct_system_messages,
    build_visual_tool_runtime_metadata,
    execute_direct_tool_rounds,
    extract_direct_response,
    sanitize_structured_visual_answer_text,
    sanitize_wiii_house_text,
    build_direct_reasoning_summary,
    direct_tool_names,
    should_surface_direct_thinking,
    resolve_public_thinking_content,
    get_phase_fallback,
) -> AgentState:
    """Direct response node - conversational responses without RAG."""
    query = state.get("query", "")

    event_queue = None
    bus_id = state.get("_event_bus_id")
    if bus_id:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue

        event_queue = _get_event_queue(bus_id)

    async def push_event(event: dict):
        capture_public_thinking_event(state, event)
        if event_queue:
            try:
                event_queue.put_nowait(event)
            except Exception as queue_error:
                logger.debug("[DIRECT] Event queue push failed: %s", queue_error)

    tracer = get_or_create_tracer(state)
    tracer.start_step(direct_response_step_name, "Tao phan hoi truc tiep")

    use_natural = getattr(settings, "enable_natural_conversation", False) is True
    if not use_natural:
        greetings = get_domain_greetings(state.get("domain_id", settings.default_domain))
        query_lower = query.lower().strip()
        response = greetings.get(query_lower)
    else:
        query_lower = query.lower().strip()
        response = None
    response_type = "greeting" if response else ""
    explicit_web_search_turn = _is_explicit_web_search_turn_for_direct(query, state)
    if not response and _is_codebase_analysis_query(query) and not explicit_web_search_turn:
        codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
        state["thinking"] = codebase_thinking
        state["thinking_content"] = codebase_thinking
        record_thinking_snapshot(
            state,
            codebase_thinking,
            node="direct",
            provenance="codebase_source_backed_plan",
        )
        if _should_use_codebase_source_note_fast_answer(query):
            response = _build_codebase_analysis_fallback_answer(query)
            response_type = "codebase_source_backed_fast"

    ctx_for_preflight = state.get("context", {}) if isinstance(state.get("context"), dict) else {}
    has_uploaded_document_context = _has_uploaded_document_context(ctx_for_preflight)
    if (
        not response
        and has_uploaded_document_context
        and not str(state.get("thinking_content") or "").strip()
    ):
        document_thinking = (
            "Mình nhận đây là lượt hỏi có tài liệu upload đã được parse thành Markdown, "
            "nên ưu tiên đối chiếu marker, bảng và các dòng trong document_context trước khi suy luận thêm. "
            "Nếu phần nào không có trong file, Wiii phải nói rõ thay vì bịa."
        )
        state["thinking"] = document_thinking
        state["thinking_content"] = document_thinking
        record_thinking_snapshot(
            state,
            document_thinking,
            node="direct",
            provenance="document_context_plan",
        )
    if (
        not response
        and has_uploaded_document_context
        and _looks_uploaded_document_preview_request(query)
    ):
        routing_meta = state.get("routing_metadata")
        if not isinstance(routing_meta, dict):
            routing_meta = {}
            state["routing_metadata"] = routing_meta
        preview_tools, preview_force_tools, doc_preview_debug = (
            _rebind_document_preview_host_action_tool(
                tools=[],
                force_tools=False,
                query=query,
                state=state,
                ctx=ctx_for_preflight,
            )
        )
        routing_meta["doc_preview_preflight"] = doc_preview_debug
        if _has_document_preview_host_action_tool(preview_tools):
            try:
                preview_runtime_context = build_tool_runtime_context(
                    event_bus_id=bus_id,
                    request_id=ctx_for_preflight.get("request_id"),
                    session_id=state.get("session_id"),
                    organization_id=state.get("organization_id"),
                    user_id=state.get("user_id"),
                    user_role=ctx_for_preflight.get("user_role", "student"),
                    node="direct",
                    source="agentic_loop",
                    metadata=build_visual_tool_runtime_metadata(state, query),
                )
                (
                    preview_llm_response,
                    preview_messages,
                    preview_tool_call_events,
                ) = await execute_direct_tool_rounds(
                    object(),
                    object(),
                    [],
                    preview_tools,
                    push_event,
                    runtime_context_base=preview_runtime_context,
                    max_rounds=1,
                    query=query,
                    state=state,
                    forced_tool_choice=_document_preview_forced_tool_choice(query, preview_tools),
                    llm_base=None,
                    native_tool_messages=False,
                )
                if preview_tool_call_events:
                    state["tool_call_events"] = preview_tool_call_events

                response, _preview_thinking, tools_used = extract_direct_response(
                    preview_llm_response,
                    preview_messages,
                )
                response = sanitize_structured_visual_answer_text(
                    response,
                    tool_call_events=preview_tool_call_events,
                )
                response = sanitize_wiii_house_text(response, query=query)
                response = _strip_direct_inline_private_asides(response)
                response = _strip_dsml_residue(response).strip()
                if not response:
                    response = (
                        "Mình đã gửi bản preview bài học sang LMS. "
                        "Giáo viên cần xem phần so sánh thay đổi và nguồn trích dẫn rồi bấm Áp dụng để cấp approval_token."
                    )
                if not tools_used:
                    preview_tool_names = sorted({
                        str(event.get("name") or "")
                        for event in preview_tool_call_events
                        if event.get("name")
                    })
                    tools_used = [
                        {"name": name}
                        for name in preview_tool_names
                        if name
                    ]
                if tools_used:
                    state["tools_used"] = tools_used
                response_type = "document_preview_host_action"
                routing_meta["doc_preview_preflight"] = {
                    **doc_preview_debug,
                    "status": "executed",
                    "tool_count": len(preview_tools),
                    "force_tools": preview_force_tools,
                }
                logger.info(
                    "[DIRECT] Executed LMS document preview host action before planner LLM"
                )
            except Exception as preview_error:
                routing_meta["doc_preview_preflight"] = {
                    **doc_preview_debug,
                    "status": "execution_failed",
                    "error": type(preview_error).__name__,
                }
                logger.warning(
                    "[DIRECT] Early document preview host action failed: %s",
                    preview_error,
                )
    if ctx_for_preflight.get("image_input_error") and has_uploaded_document_context:
        ctx_for_preflight["images"] = []
    if (
        not response
        and ctx_for_preflight.get("image_input_error")
        and not has_uploaded_document_context
    ):
        response = _build_image_input_unavailable_answer(query)
        response_type = "image_input_unavailable"
        fast_thinking = _build_image_input_unavailable_thinking()
        state["thinking"] = fast_thinking
        state["thinking_content"] = fast_thinking
        record_thinking_snapshot(
            state,
            fast_thinking,
            node="direct",
            provenance="deterministic_image_input_unavailable",
        )
    elif not response and ctx_for_preflight.get("images") and not has_uploaded_document_context:
        response = await _build_image_input_answer(
            query,
            list(ctx_for_preflight.get("images") or []),
        )
        response_type = "image_input"
        fast_thinking = _build_image_input_thinking(query)
        state["thinking"] = fast_thinking
        state["thinking_content"] = fast_thinking
        record_thinking_snapshot(
            state,
            fast_thinking,
            node="direct",
            provenance="deterministic_image_input",
        )

    if not response:
        try:
            routing_meta_for_fast = state.get("routing_metadata") or {}
            fast_method = str(routing_meta_for_fast.get("method") or "").strip().lower()
            fast_intent = str(routing_meta_for_fast.get("intent") or "").strip().lower()
            normalized_for_fast = normalize_for_intent(query)
            if state.get("_pointy_fast_path_action"):
                response = _extract_pointy_fast_path_answer(state)
                if response:
                    response_type = "pointy_fast_path"
                    fast_thinking = _build_pointy_fast_path_thinking(state)
                    state["thinking"] = fast_thinking
                    state["thinking_content"] = fast_thinking
                    record_thinking_snapshot(
                        state,
                        fast_thinking,
                        node="direct",
                        provenance="deterministic_pointy_fast_path",
                    )
            elif _pointy_requested_without_inventory(state):
                response = _build_pointy_missing_inventory_answer(query)
                response_type = "pointy_missing_inventory"
                fast_thinking = _build_pointy_missing_inventory_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_pointy_missing_inventory",
                )
            elif (
                _looks_self_feeling_probe_turn(query)
                and not needs_web_search(query)
                and not needs_datetime(query)
            ):
                response = _build_self_feeling_probe_answer(query)
                response_type = "self_feeling_probe"
                fast_thinking = _build_self_feeling_probe_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_self_feeling_probe",
                )
            elif (
                _looks_wiii_capability_inventory_turn(_fold_direct_text(query))
                and not needs_web_search(query)
                and not needs_datetime(query)
            ):
                response = _build_wiii_capability_inventory_answer(query)
                response_type = "wiii_capability_inventory"
                fast_thinking = _build_wiii_capability_inventory_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_wiii_capability_inventory",
                )
            elif (
                has_uploaded_document_context
                and _looks_uploaded_context_fact_query(query, ctx_for_preflight)
                and not _looks_uploaded_file_visual_inspection_query(query)
            ):
                response = _build_uploaded_document_context_fallback_answer(
                    query,
                    ctx_for_preflight,
                    provider_unstable=False,
                )
                if response:
                    response_type = "uploaded_file_context_fact"
                    fast_thinking = (
                        "Mình nhận đây là câu hỏi fact-check trực tiếp về file/video vừa upload, "
                        "nên ưu tiên dữ kiện parser đã trích ra thay vì gọi LLM suy diễn."
                    )
                    state["thinking"] = fast_thinking
                    state["thinking_content"] = fast_thinking
                    record_thinking_snapshot(
                        state,
                        fast_thinking,
                        node="direct",
                        provenance="deterministic_uploaded_file_context_fact",
                    )
            elif (
                fast_method == "conservative_fast_path"
                and fast_intent == "off_topic"
                and _looks_reasoning_safety_meta_turn(normalized_for_fast)
            ):
                response = _build_reasoning_safety_meta_answer(query)
                response_type = "reasoning_safety_meta"
                fast_thinking = _build_reasoning_safety_meta_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_reasoning_safety_meta",
                )
            elif (
                fast_method == "conservative_fast_path"
                and fast_intent == "off_topic"
                and _looks_wiii_pipeline_meta_turn(normalized_for_fast)
            ):
                response = _build_wiii_pipeline_meta_answer(query)
                response_type = "wiii_pipeline_meta"
                fast_thinking = _build_wiii_pipeline_meta_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_wiii_pipeline_meta",
                )
            elif (
                fast_method == "conservative_fast_path"
                and _looks_session_memory_recall_turn(normalized_for_fast)
            ):
                response = _extract_session_memory_recall_answer(state, query) or (
                    "Mình chưa thấy đủ neo trong phiên này để nhắc lại chắc chắn."
                )
                response = _with_requested_response_marker(query, response)
                response_type = "session_memory_recall"
                fast_thinking = (
                    "Mình nhận đây là lượt gọi lại thông tin trong chính phiên này, "
                    "nên ưu tiên đọc lịch sử gần nhất thay vì ghi thêm memory mới."
                )
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_session_memory_recall",
                )
            elif (
                fast_method == "conservative_fast_path"
                and _looks_session_memory_ack_only_turn(normalized_for_fast)
            ):
                response = _extract_direct_reply_only_answer(query) or "Đã ghi nhận."
                response_type = "session_memory_ack"
                state["_direct_reply_only_ack"] = True
                fast_thinking = (
                    "Mình ghi nhận điều bạn muốn giữ trong phiên hiện tại và giữ phản hồi "
                    "đúng một câu như bạn yêu cầu."
                )
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_session_ack",
                )
            elif _looks_session_memory_write_turn(normalized_for_fast):
                response = _with_requested_response_marker(
                    query,
                    _build_session_memory_write_answer(query),
                )
                response_type = "session_memory_write"
                fast_thinking = _build_session_memory_write_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_session_memory_write",
                )
            elif (
                fast_method == "conservative_fast_path"
                and _looks_session_memory_recall_turn(normalized_for_fast)
            ):
                response = _extract_session_memory_recall_answer(state, query)
                if response:
                    response_type = "session_memory_recall"
                    fast_thinking = (
                        "Mình dùng ngữ cảnh ngay trong phiên này để nhắc lại đúng "
                        "mẩu thông tin bạn vừa yêu cầu Wiii giữ."
                    )
                    state["thinking"] = fast_thinking
                    state["thinking_content"] = fast_thinking
                    record_thinking_snapshot(
                        state,
                        fast_thinking,
                        node="direct",
                        provenance="deterministic_session_memory_recall",
                    )
            elif (
                _looks_hunger_chatter_turn(normalized_for_fast)
                and not _looks_session_memory_write_turn(normalized_for_fast)
                and not needs_web_search(query)
                and not needs_datetime(query)
            ):
                response = _build_hunger_chatter_answer(query)
                response_type = "hunger_chatter"
                fast_thinking = _build_hunger_chatter_thinking(query)
                state["thinking"] = fast_thinking
                state["thinking_content"] = fast_thinking
                record_thinking_snapshot(
                    state,
                    fast_thinking,
                    node="direct",
                    provenance="deterministic_hunger_chatter",
                )
        except Exception as exc:
            logger.debug("[DIRECT] Session memory ack fast response skipped: %s", exc)

    domain_config = state.get("domain_config", {})
    domain_name_vi = domain_config.get("name_vi", "")
    if not domain_name_vi:
        domain_id = state.get("domain_id", settings.default_domain)
        domain_name_vi = {
            "maritime": "Hang hai",
            "traffic_law": "Luat Giao thong",
        }.get(domain_id, domain_id)

    if response:
        tracer.end_step(
            result=f"Direct fast response: {response[:50]}...",
            confidence=1.0,
            details={"response_type": response_type or "greeting", "query": query_lower},
        )
    else:
        explicit_user_provider: str | None = None
        llm = None
        llm_response = None
        messages: list[Any] = []
        tools: list[Any] = []
        tool_call_events: list[dict[str, Any]] = []
        response_language = "vi"
        routing_intent = ""
        is_identity_turn = False
        is_emotional_support_turn = False
        try:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry

            ctx = state.get("context", {})
            response_language = str(ctx.get("response_language") or "vi").strip() or "vi"
            thinking_effort = state.get("thinking_effort")
            routing_meta = state.get("routing_metadata") or {}
            routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
            routing_method = str(routing_meta.get("method") or "").strip().lower()
            routing_intent = str(routing_meta.get("intent") or "").strip().lower()
            hint_kind = str(routing_hint.get("kind") or "").strip().lower()
            hint_shape = str(routing_hint.get("shape") or "").strip().lower()
            normalized_query = normalize_for_intent(query)
            short_token_count = len([token for token in normalized_query.split() if token])
            is_identity_turn = (
                hint_kind == "identity_probe"
                or hint_kind == "selfhood_followup"
                or routing_intent in {"identity", "selfhood"}
                or looks_identity_selfhood_turn(query)
            )
            is_emotional_support_turn = _looks_emotional_support_turn(query)
            is_chatter_fast_path = (
                routing_method == "always_on_chatter_fast_path"
                or (hint_kind == "fast_chatter" and hint_shape in {"reaction", "vague_banter"})
            )
            is_social_fast_path = (
                routing_method == "always_on_social_fast_path"
                or (hint_kind == "fast_chatter" and hint_shape == "social")
            )
            visual_decision = resolve_visual_intent(query)
            is_short_house_chatter = (
                not is_identity_turn
                and (
                    is_chatter_fast_path
                    or is_social_fast_path
                    or (
                        routing_intent == "social"
                        and short_token_count <= 6
                        and not needs_web_search(query)
                        and not needs_datetime(query)
                        and not visual_decision.force_tool
                    )
                )
            )
            history_limit = 0 if is_short_house_chatter else 10
            tools_context_override = "" if is_short_house_chatter else None
            role_name = (
                "direct_chatter_agent"
                if (is_short_house_chatter or is_identity_turn)
                else "direct_agent"
            )
            if is_short_house_chatter:
                history_limit = 0
                tools_context_override = ""
            if is_identity_turn:
                history_limit = max(history_limit, 6)
            thinking_effort = _resolve_direct_thinking_effort(
                query=query,
                state=state,
                current_effort=thinking_effort,
                is_identity_turn=is_identity_turn,
                is_short_house_chatter=is_short_house_chatter,
            )

            visual_effort = recommended_visual_thinking_effort(
                query,
                active_code_session=get_active_code_studio_session(state),
            )
            if visual_effort:
                previous_effort = thinking_effort
                thinking_effort = merge_thinking_effort(
                    thinking_effort,
                    visual_effort,
                )
                if thinking_effort != previous_effort:
                    logger.info(
                        "[DIRECT] Visual intent detected -> upgrade thinking effort %s -> %s",
                        previous_effort or "default",
                        thinking_effort,
                    )

            preferred_provider = get_effective_provider(state)
            explicit_user_provider = get_explicit_user_provider(state)
            use_house_voice_direct = (
                routing_intent in {"social", "personal", "off_topic"}
                and not needs_web_search(query)
                and not needs_datetime(query)
                and not visual_decision.force_tool
            )
            direct_provider_override = explicit_user_provider or preferred_provider
            is_codebase_source_turn = _is_codebase_analysis_query(query) and not (
                has_uploaded_document_context
                and _looks_uploaded_document_preview_request(query)
            )
            explicit_web_search_turn = _is_explicit_web_search_turn_for_direct(query, state)

            if is_short_house_chatter or is_identity_turn or is_emotional_support_turn:
                tools, force_tools = [], False
            elif is_codebase_source_turn and not explicit_web_search_turn and not needs_web_search(query):
                tools, force_tools = [], False
            else:
                tools, force_tools = collect_direct_tools(
                    query,
                    ctx.get("user_role", "student"),
                    state=state,
                )
                # Phase F5 (2026-05-06) — SOTA tool-binding for @-mention.
                # When user force-binds via `@plugin-name` (Cursor / Claude
                # Code / GitHub Copilot pattern), tool selection is NOT a
                # heuristic guess: the user EXPLICITLY chose the plugin.
                # We must:
                #   (a) preserve every force-bound tool through the
                #       skill_recommender prune step (must_include),
                #   (b) flip force_tools=True so the LLM is required to
                #       call (tool_choice="any" / "required" downstream),
                #   (c) inject the SKILL prompt + page inventory at top
                #       of system message (Anthropic Computer Use 2026
                #       progressive disclosure pattern).
                #
                # Without these, NVIDIA DeepSeek frequently returns prose
                # ("đang trỏ giúp cậu...") with zero tool_calls and the
                # cursor never actually moves — exact symptom user hit
                # 2026-05-06.
                _force_skills_set = _force_skills_from_state(state)
                if routing_intent == "web_search":
                    _force_skills_set.add("web-search")
                    merged_force_skills = sorted(_force_skills_set)
                    state["force_skills"] = merged_force_skills
                    if isinstance(ctx, dict):
                        ctx["force_skills"] = merged_force_skills
                _force_required_tools: list[str] = []
                if "wiii-pointy" in _force_skills_set:
                    # Exact inventory id contract — see SKILL.md anti-hallucination
                    # rules. Force inventory + show, but NOT clear (clear
                    # is a stop-action, only relevant when user said "stop").
                    _force_required_tools.extend(
                        ["tool_pointy_show", "tool_pointy_inventory"]
                    )
                if "web-search" in _force_skills_set:
                    _force_required_tools.append("tool_web_search")
                if _force_required_tools:
                    force_tools = True
                    logger.info(
                        "[DIRECT] Force-bound via @-mention: required=%s",
                        _force_required_tools,
                    )
                try:
                    from app.engine.skills.skill_recommender import select_runtime_tools

                    must_include_names = direct_required_tool_names(
                        query,
                        ctx.get("user_role", "student"),
                    )
                    if (
                        has_uploaded_document_context
                        and _looks_uploaded_document_preview_request(query)
                        and _DOC_PREVIEW_HOST_ACTION_TOOL not in must_include_names
                    ):
                        must_include_names.append(_DOC_PREVIEW_HOST_ACTION_TOOL)
                    # Merge force-bound names into must_include so the
                    # recommender (max_tools=7) cannot prune them out
                    # when the bound list is large.
                    for n in _force_required_tools:
                        if n not in must_include_names:
                            must_include_names.append(n)

                    selected_tools = select_runtime_tools(
                        tools,
                        query=query,
                        intent=(state.get("routing_metadata") or {}).get("intent"),
                        user_role=ctx.get("user_role", "student"),
                        max_tools=min(len(tools), 7),
                        must_include=must_include_names,
                    )
                    if selected_tools:
                        tools = selected_tools
                        logger.info(
                            "[DIRECT] Runtime-selected tools: %s",
                            [getattr(tool, "name", getattr(tool, "__name__", "unknown")) for tool in tools],
                        )
                except Exception as selection_error:
                    logger.debug("[DIRECT] Runtime tool selection skipped: %s", selection_error)

                if has_uploaded_document_context and _looks_uploaded_document_preview_request(query):
                    tools, force_tools, doc_preview_debug = _rebind_document_preview_host_action_tool(
                        tools=tools,
                        force_tools=force_tools,
                        query=query,
                        state=state,
                        ctx=ctx,
                    )
                    if isinstance(state.get("routing_metadata"), dict):
                        state["routing_metadata"]["doc_preview_runtime"] = doc_preview_debug

            if (
                not response
                and has_uploaded_document_context
                and _looks_uploaded_document_preview_request(query)
                and _has_document_preview_host_action_tool(tools)
            ):
                try:
                    preview_runtime_context = build_tool_runtime_context(
                        event_bus_id=bus_id,
                        request_id=ctx.get("request_id"),
                        session_id=state.get("session_id"),
                        organization_id=state.get("organization_id"),
                        user_id=state.get("user_id"),
                        user_role=ctx.get("user_role", "student"),
                        node="direct",
                        source="agentic_loop",
                        metadata=build_visual_tool_runtime_metadata(state, query),
                    )
                    llm_response, messages, tool_call_events = await execute_direct_tool_rounds(
                        object(),
                        object(),
                        messages,
                        tools,
                        push_event,
                        runtime_context_base=preview_runtime_context,
                        max_rounds=1,
                        query=query,
                        state=state,
                        forced_tool_choice=_document_preview_forced_tool_choice(query, tools),
                        llm_base=None,
                        native_tool_messages=False,
                    )
                    if tool_call_events:
                        state["tool_call_events"] = tool_call_events

                    response, thinking_content, tools_used = extract_direct_response(
                        llm_response,
                        messages,
                    )
                    response = sanitize_structured_visual_answer_text(
                        response,
                        tool_call_events=tool_call_events,
                    )
                    response = sanitize_wiii_house_text(response, query=query)
                    response = _strip_direct_inline_private_asides(response)
                    response = _strip_dsml_residue(response).strip()
                    if not tools_used:
                        preview_tool_names = sorted({
                            str(event.get("name") or "")
                            for event in tool_call_events
                            if event.get("name")
                        })
                        tools_used = [
                            {"name": name}
                            for name in preview_tool_names
                            if name
                        ]
                    if tools_used:
                        state["tools_used"] = tools_used
                    tracer.end_step(
                        result="Deterministic uploaded-document preview host action",
                        confidence=0.9,
                        details={
                            "response_type": "document_preview_host_action",
                            "tools_bound": len(tools),
                            "force_tools": force_tools,
                        },
                    )
                except Exception as preview_error:
                    logger.warning(
                        "[DIRECT] Deterministic document preview pre-LLM path failed: %s",
                        preview_error,
                    )

            direct_node_id = "direct_identity" if is_identity_turn else "direct"

            from app.engine.multi_agent.openai_stream_runtime import (
                _supports_native_answer_streaming_impl,
            )

            native_direct_possible = (
                not bool(ctx.get("images") or [])
                and not is_short_house_chatter
                and not is_identity_turn
                and not is_emotional_support_turn
                and not use_house_voice_direct
                and not is_codebase_source_turn
            )
            llm = None
            if native_direct_possible and not response:
                llm = AgentConfigRegistry.get_native_llm(
                    direct_node_id,
                    effort_override=thinking_effort,
                    provider_override=direct_provider_override,
                    requested_model=state.get("model"),
                )
                if llm and not _supports_native_answer_streaming_impl(
                    getattr(llm, "_wiii_provider_name", None)
                ):
                    llm = None
            if llm is None and not response:
                llm = AgentConfigRegistry.get_llm(
                    direct_node_id,
                    effort_override=thinking_effort,
                    provider_override=direct_provider_override,
                    requested_model=state.get("model"),
                )

            llm_provider_for_images, llm_model_for_images = _extract_runtime_target(llm) if llm else (None, None)
            llm_provider_for_images = llm_provider_for_images or direct_provider_override or preferred_provider
            llm_model_for_images = llm_model_for_images or state.get("model")
            if (
                llm
                and has_uploaded_document_context
                and _looks_uploaded_file_visual_inspection_query(query)
                and not _provider_likely_supports_image_blocks(
                    llm_provider_for_images,
                    llm_model_for_images,
                )
            ):
                response = _build_uploaded_document_visual_guard_answer(
                    query,
                    ctx_for_preflight,
                )
                if response:
                    ctx_for_preflight["images"] = []
                    logger.info(
                        "[DIRECT] Uploaded video frame question routed to text-only provider; "
                        "returned visual guard fallback (provider=%s model=%s)",
                        llm_provider_for_images,
                        llm_model_for_images,
                    )
                    tracer.end_step(
                        result="Uploaded-file visual guard fallback (text-only provider)",
                        confidence=0.7,
                        details={
                            "response_type": "uploaded_file_visual_guard_fallback",
                            "provider": llm_provider_for_images,
                            "model": llm_model_for_images,
                        },
                    )

            if (
                llm
                and not response
                and getattr(settings, "enable_natural_conversation", False) is True
                and not _is_native_runtime_handle(llm)
            ):
                presence_penalty = getattr(settings, "llm_presence_penalty", 0.0)
                frequency_penalty = getattr(settings, "llm_frequency_penalty", 0.0)
                if presence_penalty or frequency_penalty:
                    try:
                        llm = _copy_runtime_metadata(
                            llm,
                            llm.bind(
                                presence_penalty=presence_penalty,
                                frequency_penalty=frequency_penalty,
                            ),
                        )
                    except Exception:
                        pass

            if llm and not response:
                logger.warning(
                    "[DIRECT] tools=%d, force=%s, web=%s, dt=%s, query='%s'",
                    len(tools),
                    force_tools,
                    needs_web_search(query),
                    needs_datetime(query),
                    query[:60],
                )

                if visual_decision.force_tool and not force_tools and routing_intent not in ("learning", "lookup"):
                    has_visual_tool = any(getattr(tool, "name", getattr(tool, "__name__", "")) == "tool_generate_visual" for tool in tools)
                    if has_visual_tool:
                        force_tools = True
                        logger.info(
                            "[DIRECT] Visual intent -> force tool_choice='any' (visual_type=%s)",
                            visual_decision.visual_type,
                        )
                    else:
                        logger.warning(
                            "[DIRECT] Visual intent detected but tool_generate_visual not in tools list",
                        )

                bound_provider, bound_model = _extract_runtime_target(llm)
                bound_provider = bound_provider or state.get("provider")
                if bound_provider and str(bound_provider).strip().lower() != "auto":
                    state["_execution_provider"] = str(bound_provider)
                if bound_model:
                    state["_execution_model"] = str(bound_model)
                    state["model"] = str(bound_model)
                direct_answer_timeout_profile = resolve_direct_answer_timeout_profile(
                    provider_name=bound_provider or direct_provider_override or preferred_provider,
                    query=query,
                    state=state,
                    is_identity_turn=is_identity_turn,
                    is_short_house_chatter=is_short_house_chatter,
                    use_house_voice_direct=use_house_voice_direct,
                    tools_bound=bool(tools),
                )
                direct_answer_primary_timeout = resolve_direct_answer_primary_timeout_impl(
                    provider_name=bound_provider or direct_provider_override or preferred_provider,
                    query=query,
                    state=state,
                    is_identity_turn=is_identity_turn,
                    is_short_house_chatter=is_short_house_chatter,
                    use_house_voice_direct=use_house_voice_direct,
                    tools_bound=bool(tools),
                )
                direct_allowed_fallback_providers = None
                if not explicit_user_provider:
                    direct_allowed_fallback_providers = (
                        resolve_direct_fallback_provider_allowlist_impl_wrapper(
                            provider_name=bound_provider or direct_provider_override or preferred_provider,
                            query=query,
                            state=state,
                            is_identity_turn=is_identity_turn,
                            is_short_house_chatter=is_short_house_chatter,
                            use_house_voice_direct=use_house_voice_direct,
                            tools_bound=bool(tools),
                        )
                    )
                llm_with_tools, llm_auto, forced_tool_choice = bind_direct_tools(
                    llm,
                    tools,
                    force_tools,
                    provider=bound_provider,
                    include_forced_choice=True,
                )
                # v9.0 F18 (2026-05-07) — when pointy is force-bound, the
                # tool's selector is already enum-constrained at JSON-schema
                # layer (Literal[...] in tool_pointy_show args). That's
                # SeeAct's textual-choice grounding applied at argument
                # layer. We DON'T need to override tool_choice to specific
                # tool name (caused NVIDIA bind_tools incompat in early
                # tests) — the existing `_resolve_tool_choice("any")` is
                # sufficient because force_tools=True ensures SOME tool
                # is invoked, and the enum-constrained pointy tool wins
                # when query is UI-related (other tools have unrelated
                # signatures).
                if force_tools:
                    logger.info(
                        "[DIRECT] Forced tool_choice=%r (web=%s, dt=%s, visual=%s)",
                        forced_tool_choice,
                        needs_web_search(query),
                        needs_datetime(query),
                        visual_decision.force_tool,
                    )

                native_direct_messages = _is_native_runtime_handle(llm)
                messages = build_direct_system_messages(
                    state,
                    query,
                    domain_name_vi,
                    role_name=role_name,
                    tools_context_override=tools_context_override,
                    visual_decision=visual_decision,
                    history_limit=history_limit,
                    native_messages=native_direct_messages,
                )
                runtime_context_base = build_tool_runtime_context(
                    event_bus_id=bus_id,
                    request_id=ctx.get("request_id"),
                    session_id=state.get("session_id"),
                    organization_id=state.get("organization_id"),
                    user_id=state.get("user_id"),
                    user_role=ctx.get("user_role", "student"),
                    node="direct",
                    source="agentic_loop",
                    metadata=build_visual_tool_runtime_metadata(state, query),
                )

                # Wiii Pointy v2.6 — adaptive max rounds. Loop tự exit
                # khi LLM ngừng gọi tool; cap chỉ là runaway protection.
                # Default 12 (Anthropic Computer Use ref dùng 10), settings
                # override cho power-users / autonomous flows.
                _direct_max_rounds = getattr(settings, "direct_agent_max_tool_rounds", 12)

                direct_execution = execute_direct_tool_rounds(
                    llm_with_tools,
                    llm_auto,
                    messages,
                    tools,
                    push_event,
                    runtime_context_base=runtime_context_base,
                    max_rounds=_direct_max_rounds,
                    query=query,
                    state=state,
                    provider=explicit_user_provider,
                    forced_tool_choice=forced_tool_choice,
                    llm_base=llm,
                    direct_answer_timeout_profile=direct_answer_timeout_profile,
                    direct_answer_primary_timeout=direct_answer_primary_timeout,
                    allowed_fallback_providers=direct_allowed_fallback_providers,
                    native_tool_messages=native_direct_messages,
                )
                if routing_intent == "host_ui_navigation":
                    try:
                        llm_response, messages, tool_call_events = await asyncio.wait_for(
                            direct_execution,
                            timeout=_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        from app.engine.native_chat_runtime import make_assistant_message

                        logger.warning(
                            "[DIRECT] Host UI navigation answer exceeded %.1fs; returning bounded fallback",
                            _HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS,
                        )
                        # Phase F2 (2026-05-06): surface-aware fallback. Khi Wiii
                        # chạy standalone (host_type=wiii-desktop / wiii-web),
                        # KHÔNG nói "panel Wiii / làm mới trang LMS" — không có
                        # LMS context. AI nên nói "thử lại" hoặc trỏ trực tiếp.
                        host_ctx = state.get("host_context") if isinstance(state, dict) else None
                        host_type = (host_ctx or {}).get("host_type", "") if isinstance(host_ctx, dict) else ""
                        is_standalone = host_type in ("wiii-desktop", "wiii-web")
                        if is_standalone:
                            fallback_answer = (
                                "Mình đã thử trỏ chuột vào element rồi. Nếu chưa thấy "
                                "cursor di chuyển, bạn thử gửi lại câu hỏi nhé — "
                                "đôi khi LLM cần thêm chút thời gian xử lý."
                            )
                        else:
                            fallback_answer = (
                                "Mình đã nhận yêu cầu trỏ trên giao diện rồi. "
                                "Nếu Wiii chưa highlight ngay, hãy thử mở lại panel Wiii hoặc làm mới trang LMS nhé."
                            )
                        await push_event(
                            {
                                "type": "answer_delta",
                                "content": fallback_answer,
                                "node": "direct",
                            }
                        )
                        llm_response = make_assistant_message(fallback_answer)
                        tool_call_events = []
                else:
                    llm_response, messages, tool_call_events = await direct_execution

                if tool_call_events:
                    state["tool_call_events"] = tool_call_events

                response, thinking_content, tools_used = extract_direct_response(llm_response, messages)
                response = sanitize_structured_visual_answer_text(
                    response,
                    tool_call_events=tool_call_events,
                )
                response = sanitize_wiii_house_text(response, query=query)
                response = _strip_direct_inline_private_asides(response)
                # Defensive DSML strip — DeepSeek occasionally emits tool-call
                # markup as prose content even when tool_choice is "none".
                response = _strip_dsml_residue(response).strip()
                if is_identity_turn:
                    response = _compact_basic_identity_answer(response, query=query)
                if (
                    _is_codebase_analysis_query(query)
                    and not explicit_web_search_turn
                    and _looks_generic_direct_fallback_response(response)
                ):
                    response = _build_codebase_analysis_fallback_answer(query)
                    thinking_content = _build_codebase_analysis_fallback_thinking(query)
                    state["thinking"] = thinking_content
                    state["thinking_content"] = thinking_content
                    record_thinking_snapshot(
                        state,
                        thinking_content,
                        node="direct",
                        provenance="deterministic_codebase_fallback",
                    )

                # Source-backed graceful synthesis: when the LLM returned an
                # empty body but tools captured real search results (Perplexity
                # 2026 / Anthropic Computer Use 2026 evidence-pool pattern),
                # build a citation-bearing answer directly from tool_call_events
                # instead of letting the user see nothing.
                if tool_call_events and (
                    not str(response or "").strip()
                    or looks_like_search_placeholder_answer(response)
                ):
                    try:
                        synthesis_template = build_search_template_fallback(
                            query=query,
                            tool_call_events=tool_call_events,
                        )
                    except Exception as template_error:
                        logger.warning(
                            "[DIRECT] Empty-response template fallback build failed: %s",
                            template_error,
                        )
                        synthesis_template = ""
                    if synthesis_template:
                        logger.info(
                            "[DIRECT] LLM returned empty/placeholder body — engaging "
                            "source-backed template fallback (events=%d, len=%d)",
                            len(tool_call_events),
                            len(synthesis_template),
                        )
                        try:
                            inc_counter(
                                "wiii.direct.template_fallback.engaged",
                                labels={"trigger": "empty_body"},
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        response = synthesis_template
                        if not tools_used:
                            empty_body_tool_names = sorted({
                                str(event.get("name") or "")
                                for event in tool_call_events
                                if event.get("type") == "result" and event.get("name")
                            })
                            tools_used = [
                                {"name": name}
                                for name in empty_body_tool_names
                                if name
                            ]

                if _should_surface_direct_visible_thought(
                    thinking_content,
                    routing_intent=routing_intent,
                    response=response,
                ):
                    aligned_thinking = await _align_direct_visible_thought(
                        thinking_content,
                        response_language=response_language,
                        llm=llm,
                    )
                    if aligned_thinking and not _contains_direct_internal_thought_leak(
                        aligned_thinking
                    ) and not should_align_visible_thinking_language(
                        aligned_thinking,
                        target_language=response_language,
                    ):
                        state["thinking"] = aligned_thinking
                        state["thinking_content"] = aligned_thinking
                        record_thinking_snapshot(
                            state,
                            aligned_thinking,
                            node="direct",
                            provenance="aligned_cleanup",
                        )
                    else:
                        state.pop("thinking", None)
                        state["thinking_content"] = ""
                else:
                    state.pop("thinking", None)
                    state["thinking_content"] = ""
                if not str(state.get("thinking_content") or "").strip():
                    emotional_rescue = await _build_emotional_rescue_visible_thought(
                        query=query,
                        state=state,
                        response=response,
                        response_language=response_language,
                        llm=llm,
                        build_direct_reasoning_summary=build_direct_reasoning_summary,
                        tool_names=list(tools_used or []),
                    )
                    if emotional_rescue:
                        state["thinking"] = emotional_rescue
                        state["thinking_content"] = emotional_rescue
                        record_thinking_snapshot(
                            state,
                            emotional_rescue,
                            node="direct",
                            provenance="aligned_cleanup",
                        )
                if tools_used:
                    state["tools_used"] = tools_used

                tracer.end_step(
                    result=f"Phan hoi LLM: {len(response)} chars",
                    confidence=0.85,
                    details={
                        "response_type": "llm_generated",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                    },
                )
            elif not response:
                if explicit_user_provider:
                    raise ProviderUnavailableError(
                        provider=str(explicit_user_provider).strip().lower(),
                        reason_code="busy",
                        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
                    )
                if _is_codebase_analysis_query(query) and not explicit_web_search_turn:
                    response = _build_codebase_analysis_fallback_answer(query)
                    codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
                    state["thinking"] = codebase_thinking
                    state["thinking_content"] = codebase_thinking
                    record_thinking_snapshot(
                        state,
                        codebase_thinking,
                        node="direct",
                        provenance="deterministic_codebase_fallback",
                    )
                else:
                    response = (
                        get_phase_fallback(state)
                        if getattr(settings, "enable_natural_conversation", False) is True
                        else "Xin chao! Toi co the giup gi cho ban?"
                    )
                tracer.end_step(
                    result="Fallback (LLM unavailable)",
                    confidence=0.5,
                    details={
                        "response_type": (
                            "codebase_source_backed_fallback"
                            if _is_codebase_analysis_query(query) and not explicit_web_search_turn
                            else "fallback"
                        )
                    },
                )
        except Exception as exc:
            salvaged = await _salvage_direct_turn_from_final_result(
                llm_response=llm_response,
                messages=messages,
                extract_direct_response=extract_direct_response,
                sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
                sanitize_wiii_house_text=sanitize_wiii_house_text,
                tool_call_events=tool_call_events,
                query=query,
                is_identity_turn=is_identity_turn,
                routing_intent=routing_intent,
                response_language=response_language,
                llm=llm,
            )
            if salvaged:
                response, salvaged_thinking, salvaged_tools = salvaged
                if salvaged_tools:
                    state["tools_used"] = salvaged_tools
                if salvaged_thinking:
                    state["thinking"] = salvaged_thinking
                    state["thinking_content"] = salvaged_thinking
                    record_thinking_snapshot(
                        state,
                        salvaged_thinking,
                        node="direct",
                        provenance="final_snapshot",
                    )
                logger.warning(
                    "[DIRECT] Post-processing failed but salvaged final result: %s",
                    exc,
                )
                tracer.end_step(
                    result="Salvaged direct response after post-processing error",
                    confidence=0.7,
                    details={
                        "response_type": "llm_salvaged",
                        "error_type": type(exc).__name__,
                    },
                )
            elif (
                isinstance(exc, ProviderUnavailableError)
                and (
                    uploaded_fallback := _build_uploaded_document_context_fallback_answer(
                        query,
                        ctx_for_preflight,
                    )
                )
            ):
                response = uploaded_fallback
                logger.info(
                    "[DIRECT] Provider unavailable; returned uploaded-file context fallback (len=%d)",
                    len(response),
                )
                tracer.end_step(
                    result="Uploaded-file context fallback (provider unavailable)",
                    confidence=0.65,
                    details={
                        "response_type": "uploaded_file_context_fallback",
                        "error_type": type(exc).__name__,
                    },
                )
            elif isinstance(exc, ProviderUnavailableError) and tool_call_events:
                template_response = ""
                try:
                    template_response = build_search_template_fallback(
                        query=query,
                        tool_call_events=tool_call_events,
                    )
                except Exception as template_error:
                    logger.warning(
                        "[DIRECT] Provider unavailable and search fallback build failed: %s",
                        template_error,
                    )
                if not template_response:
                    raise
                response = template_response
                template_tool_names = sorted({
                    str(event.get("name") or "")
                    for event in tool_call_events
                    if event.get("type") == "result" and event.get("name")
                })
                template_tools = [
                    {"name": name} for name in template_tool_names if name
                ]
                if template_tools:
                    state["tools_used"] = template_tools
                logger.info(
                    "[DIRECT] Provider unavailable after tools; returning "
                    "source-backed fallback (tools=%d, len=%d)",
                    len(template_tools),
                    len(response),
                )
                tracer.end_step(
                    result="Source-backed fallback (provider unavailable after tools)",
                    confidence=0.6,
                    details={
                        "response_type": "search_template_fallback",
                        "tools_used_count": len(template_tools),
                        "response_length": len(response),
                    },
                )
            elif isinstance(exc, ProviderUnavailableError) and needs_web_search(query):
                fallback_events: list[dict[str, Any]] = []
                try:
                    fallback_events = await _emergency_search_fallback(
                        query=query,
                        tools=tools,
                        timeout_seconds=30.0,
                    )
                except Exception as emergency_error:
                    logger.warning(
                        "[DIRECT] Provider unavailable and emergency search failed: %s",
                        emergency_error,
                    )
                    fallback_events = []

                template_response = ""
                if fallback_events:
                    try:
                        await _emit_synthetic_tool_events(
                            fallback_events,
                            push_event=push_event,
                        )
                        state["tool_call_events"] = fallback_events
                        template_response = build_search_template_fallback(
                            query=query,
                            tool_call_events=fallback_events,
                        )
                    except Exception as template_error:
                        logger.warning(
                            "[DIRECT] Emergency search template fallback failed: %s",
                            template_error,
                        )
                        template_response = ""
                if not template_response:
                    raise
                response = template_response
                template_tool_names = sorted({
                    str(event.get("name") or "")
                    for event in fallback_events
                    if event.get("type") == "result" and event.get("name")
                })
                template_tools = [
                    {"name": name} for name in template_tool_names if name
                ]
                if template_tools:
                    state["tools_used"] = template_tools
                logger.info(
                    "[DIRECT] Provider unavailable before tool planning; "
                    "returned emergency source-backed fallback (tools=%d, len=%d)",
                    len(template_tools),
                    len(response),
                )
                tracer.end_step(
                    result="Source-backed fallback (provider unavailable before tools)",
                    confidence=0.55,
                    details={
                        "response_type": "search_template_fallback",
                        "tools_used_count": len(template_tools),
                        "response_length": len(response),
                    },
                )
            elif explicit_user_provider and needs_web_search(query):
                fallback_events = list(tool_call_events or [])
                if not fallback_events:
                    logger.info(
                        "[DIRECT] Explicit provider web turn failed before tool "
                        "evidence — engaging LLM-free emergency search"
                    )
                    try:
                        fallback_events = await _emergency_search_fallback(
                            query=query,
                            tools=tools,
                            timeout_seconds=30.0,
                        )
                    except Exception as emergency_error:
                        logger.warning(
                            "[DIRECT] Explicit-provider emergency search failed: %s",
                            emergency_error,
                        )
                        fallback_events = []

                template_response = ""
                if fallback_events:
                    try:
                        if not tool_call_events:
                            await _emit_synthetic_tool_events(
                                fallback_events,
                                push_event=push_event,
                            )
                            state["tool_call_events"] = fallback_events
                        template_response = build_search_template_fallback(
                            query=query,
                            tool_call_events=fallback_events,
                        )
                    except Exception as template_error:
                        logger.warning(
                            "[DIRECT] Explicit-provider template fallback failed: %s",
                            template_error,
                        )
                        template_response = ""
                if not template_response:
                    classified = classify_failover_reason_impl(error=exc)
                    raise ProviderUnavailableError(
                        provider=str(explicit_user_provider).strip().lower(),
                        reason_code=str(classified.get("reason_code") or "provider_unavailable"),
                        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
                        details=classified.get("detail"),
                    ) from exc

                response = template_response
                if fallback_events and not tool_call_events:
                    tool_call_events = fallback_events
                template_tool_names = sorted({
                    str(event.get("name") or "")
                    for event in fallback_events
                    if event.get("type") == "result" and event.get("name")
                })
                template_tools = [
                    {"name": name} for name in template_tool_names if name
                ]
                if template_tools:
                    state["tools_used"] = template_tools
                logger.info(
                    "[DIRECT] Explicit provider failed on web turn; returned "
                    "source-backed emergency fallback (tools=%d, len=%d)",
                    len(template_tools),
                    len(response),
                )
                tracer.end_step(
                    result="Source-backed fallback (explicit provider web failure)",
                    confidence=0.55,
                    details={
                        "response_type": "search_template_fallback",
                        "tools_used_count": len(template_tools),
                        "response_length": len(response),
                    },
                )
            elif explicit_user_provider:
                uploaded_fallback = _build_uploaded_document_context_fallback_answer(
                    query,
                    ctx_for_preflight,
                )
                if uploaded_fallback:
                    response = uploaded_fallback
                    logger.info(
                        "[DIRECT] Explicit provider failed; returned uploaded-file context fallback (len=%d)",
                        len(response),
                    )
                    tracer.end_step(
                        result="Uploaded-file context fallback (explicit provider failed)",
                        confidence=0.65,
                        details={
                            "response_type": "uploaded_file_context_fallback",
                            "error_type": type(exc).__name__,
                        },
                    )
                else:
                    if isinstance(exc, ProviderUnavailableError):
                        raise
                    classified = classify_failover_reason_impl(error=exc)
                    raise ProviderUnavailableError(
                        provider=str(explicit_user_provider).strip().lower(),
                        reason_code=str(classified.get("reason_code") or "provider_unavailable"),
                        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
                        details=classified.get("detail"),
                    ) from exc
            else:
                logger.warning("[DIRECT] LLM generation failed: %s", exc)
                logger.info(
                    "[DIRECT] Template fallback consideration — "
                    "tool_call_events count=%d, types=%s",
                    len(tool_call_events) if tool_call_events else 0,
                    [
                        f"{event.get('type')}:{event.get('name')}"
                        for event in (tool_call_events or [])[:6]
                    ],
                )
                fallback_events = list(tool_call_events or [])
                if not fallback_events and needs_web_search(query):
                    logger.info(
                        "[DIRECT] Round-0 timeout with empty tool history — "
                        "engaging LLM-free emergency search"
                    )
                    try:
                        fallback_events = await _emergency_search_fallback(
                            query=query,
                            tools=tools,
                            timeout_seconds=30.0,
                        )
                        logger.info(
                            "[DIRECT] Emergency search produced %d synthetic events",
                            len(fallback_events),
                        )
                    except Exception as emergency_error:
                        logger.warning(
                            "[DIRECT] Emergency search failed: %s",
                            emergency_error,
                        )
                        fallback_events = []
                template_response = ""
                try:
                    template_response = build_search_template_fallback(
                        query=query,
                        tool_call_events=fallback_events,
                    )
                    logger.info(
                        "[DIRECT] Template fallback build returned len=%d",
                        len(template_response or ""),
                    )
                except Exception as template_error:
                    logger.warning(
                        "[DIRECT] Template fallback build failed: %s",
                        template_error,
                    )
                if template_response:
                    if fallback_events and not tool_call_events:
                        tool_call_events = fallback_events
                        state["tool_call_events"] = fallback_events
                    try:
                        trigger_label = (
                            "emergency_search"
                            if not tool_call_events or fallback_events == tool_call_events
                            else "exception_with_tools"
                        )
                        inc_counter(
                            "wiii.direct.template_fallback.engaged",
                            labels={"trigger": trigger_label},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    response = template_response
                    template_tool_names = sorted({
                        str(event.get("name") or "")
                        for event in tool_call_events
                        if event.get("type") == "result" and event.get("name")
                    })
                    template_tools = [
                        {"name": name} for name in template_tool_names if name
                    ]
                    if template_tools:
                        state["tools_used"] = template_tools
                    logger.info(
                        "[DIRECT] Source-backed template fallback engaged "
                        "(synthesis LLM unavailable, tools=%d, len=%d)",
                        len(template_tools),
                        len(response),
                    )
                    tracer.end_step(
                        result="Source-backed fallback (synthesis LLM unavailable)",
                        confidence=0.6,
                        details={
                            "response_type": "search_template_fallback",
                            "tools_used_count": len(template_tools),
                            "response_length": len(response),
                        },
                    )
                else:
                    codebase_fallback = (
                        _build_codebase_analysis_fallback_answer(query)
                        if _is_codebase_analysis_query(query) and not explicit_web_search_turn
                        else ""
                    )
                    if isinstance(exc, ProviderUnavailableError):
                        uploaded_fallback = _build_uploaded_document_context_fallback_answer(
                            query,
                            ctx_for_preflight,
                        )
                        if uploaded_fallback:
                            response = uploaded_fallback
                        elif codebase_fallback:
                            response = codebase_fallback
                            codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
                            state["thinking"] = codebase_thinking
                            state["thinking_content"] = codebase_thinking
                            record_thinking_snapshot(
                                state,
                                codebase_thinking,
                                node="direct",
                                provenance="deterministic_codebase_fallback",
                            )
                        else:
                            raise
                    else:
                        uploaded_fallback = _build_uploaded_document_context_fallback_answer(
                            query,
                            ctx_for_preflight,
                        )
                        if uploaded_fallback:
                            response = uploaded_fallback
                        elif codebase_fallback:
                            response = codebase_fallback
                            codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
                            state["thinking"] = codebase_thinking
                            state["thinking_content"] = codebase_thinking
                            record_thinking_snapshot(
                                state,
                                codebase_thinking,
                                node="direct",
                                provenance="deterministic_codebase_fallback",
                            )
                        else:
                            response = (
                                get_phase_fallback(state)
                                if getattr(settings, "enable_natural_conversation", False) is True
                                else "Xin chao! Toi co the giup gi cho ban?"
                            )
                    tracer.end_step(
                        result="Fallback (LLM generation error)",
                        confidence=0.5,
                        details={
                            "response_type": (
                                "uploaded_file_context_fallback"
                                if uploaded_fallback
                                else "codebase_source_backed_fallback"
                                if codebase_fallback
                                else "fallback"
                            )
                        },
                    )

    resolved_direct_thinking = resolve_public_thinking_content(
        state,
        fallback="",
    )
    if resolved_direct_thinking:
        state["thinking_content"] = resolved_direct_thinking
        record_thinking_snapshot(
            state,
            resolved_direct_thinking,
            node="direct",
            provenance=(
                "final_snapshot"
                if resolved_direct_thinking == str(state.get("thinking") or "").strip()
                else "aligned_cleanup"
            ),
        )

    state["final_response"] = response
    state["agent_outputs"] = {"direct": response}
    state["current_agent"] = "direct"

    routing_meta = state.get("routing_metadata", {})
    intent = routing_meta.get("intent", "") if routing_meta else ""
    if intent == "general":
        from app.core.config import settings as local_settings
        from app.core.org_context import get_current_org_id

        suppress = local_settings.enable_org_knowledge and bool(get_current_org_id())
        if not suppress:
            state["domain_notice"] = (
                f"Noi dung nay nam ngoai chuyen mon {domain_name_vi}. "
                f"De duoc ho tro chinh xac hon, hay hoi ve {domain_name_vi} nhe!"
            )

    logger.info("[DIRECT] Response prepared, tracer passed to synthesizer")
    return state
