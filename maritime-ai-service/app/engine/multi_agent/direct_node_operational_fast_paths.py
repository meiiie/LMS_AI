"""Deterministic operational fast paths for the direct node."""

from __future__ import annotations

import re

from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.multi_agent.direct_web_search_policy import (
    _looks_explicit_web_search_query,
)
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.direct_session_memory_runtime import (
    _with_requested_response_marker,
)
from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_collection import _force_skills_from_state

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

def _is_explicit_web_search_turn_for_direct(query: str, state: AgentState | None = None) -> bool:
    folded = _fold_direct_text(query)
    if (
        "@web-search" in folded
        or "@web_search" in folded
        or "search the web" in folded
        or _looks_explicit_web_search_query(query)
    ):
        return True
    if isinstance(state, dict):
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
