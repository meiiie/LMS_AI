"""Tool-round runtime extracted from direct_execution."""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import unicodedata
from typing import Any, Optional

from app.core.config import settings
from app.engine.multi_agent.direct_opening_runtime import (
    finalize_direct_opening_phase_impl,
    start_direct_opening_phase_impl,
)
from app.engine.multi_agent.direct_prompts import _resolve_tool_choice, _tool_name
from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _build_direct_tool_reflection,
    _infer_direct_reasoning_cue,
    _infer_direct_thinking_mode,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.visual_events import (
    _collect_active_visual_session_ids,
    _emit_visual_commit_events,
    _maybe_emit_host_action_event,
    _maybe_emit_visual_event,
    _summarize_tool_result_for_stream,
)
from app.engine.multi_agent.visual_intent_resolver import (
    required_visual_tool_names,
    resolve_visual_intent,
)
from app.engine.reasoning import record_thinking_snapshot


logger = logging.getLogger(__name__)

_FORCED_WEB_SEARCH_TOOL_NAMES = (
    "tool_web_search",
    "web_search",
)
_RICH_SEARCH_RESULT_CHAR_FLOOR = 1200
_DOC_PREVIEW_HOST_ACTION_TOOL = "host_action__authoring__preview_lesson_patch"
_DOC_COURSE_HOST_ACTION_TOOL = "host_action__authoring__generate_course_from_document"


def _normalize_doc_preview_text(value: Any) -> str:
    text = str(value or "").replace("\\_", "_")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _is_doc_preview_scaffold_line(value: str) -> bool:
    line = str(value or "").strip()
    if not line:
        return True
    normalized = _normalize_doc_preview_text(line).strip(" #-:\t\r\n|")
    if normalized.startswith(
        (
            "tai lieu upload",
            "muc luc phat hien",
            "trich doan dau tai lieu",
            "trich doan uu tien",
            "trich doan uu tien theo vai tro",
            "trich doan cuoi tai lieu",
        )
    ):
        return True
    return bool(re.match(r"^-\s*\d+(?:\.\d+)*\.\s+\S+", line))


def _is_doc_preview_low_value_line(value: str) -> bool:
    line = str(value or "").strip()
    if not line:
        return True
    normalized = _normalize_doc_preview_text(line).strip()
    if normalized.startswith(("buoc - thao tac", "hinh ", "vai tro -")):
        return True
    return bool(re.match(r"^\d+(?:\.\d+)*\.\s+\S+", line))


def _uploaded_document_attachments_from_state(state: AgentState | None) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    ctx = state.get("context")
    if not isinstance(ctx, dict):
        return []
    document_context = ctx.get("document_context")
    if not isinstance(document_context, dict):
        return []
    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return []
    return [
        item
        for item in attachments
        if isinstance(item, dict) and str(item.get("markdown") or "").strip()
    ]


def _find_doc_preview_host_action_tool(tools: list[Any]) -> Any | None:
    for tool in tools or []:
        if _tool_name(tool).lower() == _DOC_PREVIEW_HOST_ACTION_TOOL:
            return tool
    return None


def _find_doc_course_host_action_tool(tools: list[Any]) -> Any | None:
    for tool in tools or []:
        if _tool_name(tool).lower() == _DOC_COURSE_HOST_ACTION_TOOL:
            return tool
    return None


def _looks_uploaded_doc_course_request(query: str) -> bool:
    normalized = _normalize_doc_preview_text(query)
    if any(
        marker in normalized
        for marker in (
            "preview_lesson_patch",
            "lesson patch",
            "bai hoc hien tai",
            "cap nhat bai hoc",
        )
    ):
        return False
    return any(
        marker in normalized
        for marker in (
            "generate_course_from_document",
            "course architect",
            "course plan",
            "course outline",
            "full course",
            "toan bo khoa",
            "cay khoa",
            "chia khoa",
            "tao khoa hoc",
            "thiet ke khoa hoc",
            "cau truc khoa hoc",
            "chuong/bai",
            "chuong bai",
            "module",
            "outline",
        )
    )


def _should_request_uploaded_doc_course_preview(
    *,
    query: str,
    state: AgentState | None,
    tools: list[Any],
) -> bool:
    if _find_doc_course_host_action_tool(tools) is None:
        return False
    if not _uploaded_document_attachments_from_state(state):
        return False
    return _looks_uploaded_doc_course_request(query)


def _should_request_uploaded_doc_preview(
    *,
    query: str,
    state: AgentState | None,
    tools: list[Any],
) -> bool:
    if _find_doc_preview_host_action_tool(tools) is None:
        return False
    if not _uploaded_document_attachments_from_state(state):
        return False
    normalized = _normalize_doc_preview_text(query)
    return any(
        marker in normalized
        for marker in (
            "preview",
            "xem truoc",
            "ban xem truoc",
            "ban nhap",
            "draft",
            "cap nhat bai hoc",
            "tao ban xem truoc",
            "lesson patch",
            "preview_lesson_patch",
            "source_references",
            "citation",
            "trich dan",
            "nguon",
        )
    )


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").replace("\\_", "_").splitlines():
        line = _clean_doc_preview_line(line)
        if (
            line
            and not _is_doc_preview_scaffold_line(line)
            and not _is_doc_preview_low_value_line(line)
        ):
            return line[:140]
    return "Tài liệu đã tải lên"


def _clean_doc_preview_line(value: str) -> str:
    line = str(value or "").replace("\\_", "_").strip()
    if not line:
        return ""
    lowered = line.lower()
    if line.startswith("![") or "data:image" in lowered or "base64" in lowered:
        return ""
    if "<w:" in lowered or "</w:" in lowered:
        return ""
    if line.startswith("|") and line.endswith("|"):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        cells = [
            re.sub(r"[*_`]+", "", cell).strip()
            for cell in cells
            if cell.strip()
        ]
        while cells and _normalize_doc_preview_text(cells[0]) in {"□", "☐", "☑", "✓", "x"}:
            cells = cells[1:]
        if not cells or all(set(cell) <= {"-", " ", ":"} for cell in cells):
            return ""
        line = " - ".join(cells)
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
    line = re.sub(r"[*_`]+", "", line)
    line = re.sub(r"\s+", " ", line).strip(" #*-:\t\r\n|")
    if not line or not re.search(r"[\wÀ-ỹ]", line, flags=re.IGNORECASE):
        return ""
    if set(line) <= {"-", "|", " ", ":"}:
        return ""
    return line[:220]


def _extract_marker(text: str) -> str:
    cleaned = str(text or "").replace("\\_", "_")
    match = re.search(r"\bWIII_DOC_GOAL_[0-9A-Za-z_-]+\b", cleaned)
    return match.group(0) if match else ""


def _strip_doc_preview_goal_label(line: str) -> str:
    cleaned = str(line or "").strip()
    if _normalize_doc_preview_text(cleaned).startswith("muc tieu "):
        cleaned = re.sub(r"^(?:Mục tiêu|Muc tieu)\s*[-:–]?\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or str(line or "").strip()


def _extract_relevant_lines(markdown: str, markers: tuple[str, ...], *, limit: int) -> list[str]:
    normalized_markers = tuple(_normalize_doc_preview_text(marker) for marker in markers)
    selected: list[str] = []
    for raw_line in str(markdown or "").replace("\\_", "_").splitlines():
        line = _clean_doc_preview_line(raw_line)
        if (
            not line
            or _is_doc_preview_scaffold_line(line)
            or _is_doc_preview_low_value_line(line)
        ):
            continue
        normalized_line = _normalize_doc_preview_text(line)
        if any(marker in normalized_line for marker in normalized_markers):
            selected.append(line[:220])
        if len(selected) >= limit:
            break
    return selected


def _extract_doc_preview_title_from_query(query: str) -> str:
    match = re.search(
        r"(?:title|tiêu đề|tieu de)\s*(?:là|la|is|:)\s*[\"“”']([^\"“”']{3,140})[\"“”']",
        str(query or ""),
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_doc_preview_line(match.group(1))
    return ""


def _focus_doc_preview_markdown(query: str, markdown: str) -> str:
    normalized_query = _normalize_doc_preview_text(query)
    role_markers: tuple[str, ...] = ()
    if any(marker in normalized_query for marker in ("giang vien", "giao vien", "teacher")):
        role_markers = ("huong dan cho giang vien", "danh cho giang vien", "giang vien")
    elif any(marker in normalized_query for marker in ("hoc vien", "student")):
        role_markers = ("huong dan cho hoc vien", "danh cho hoc vien")
    elif any(marker in normalized_query for marker in ("quan ly", "manager", "admin")):
        role_markers = ("huong dan cho quan ly", "quan tri", "admin")
    if not role_markers:
        return markdown

    lines = str(markdown or "").replace("\\_", "_").splitlines()
    normalized_markers = tuple(_normalize_doc_preview_text(marker) for marker in role_markers)
    best_match: tuple[int, int] | None = None
    for index, raw_line in enumerate(lines):
        cleaned = _clean_doc_preview_line(raw_line)
        if not cleaned:
            continue
        normalized_line = _normalize_doc_preview_text(cleaned)
        if any(marker in normalized_line for marker in normalized_markers):
            raw_stripped = raw_line.strip()
            score = 10
            if raw_stripped.startswith("#"):
                score += 120
            if raw_stripped.startswith("-") or _is_doc_preview_scaffold_line(cleaned):
                score -= 80
            if normalized_line.startswith(tuple(normalized_markers)):
                score += 20
            if best_match is None or score > best_match[0]:
                best_match = (score, index)
    if best_match is not None:
        _score, index = best_match
        raw_stripped = lines[index].strip()
        start = index if raw_stripped.startswith("#") else max(0, index - 2)
        end = min(len(lines), index + 140)
        return "\n".join(lines[start:end])
    return markdown


def _extract_source_pages(query: str, markdown: str) -> tuple[int | None, int | None]:
    text = _normalize_doc_preview_text(f"{query}\n{markdown}")
    range_match = re.search(r"(?:page|trang)\s*(\d{1,3})\s*[-–]\s*(\d{1,3})", text)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))
    page_match = re.search(r"(?:page|trang)\s*(\d{1,3})", text)
    if page_match:
        page = int(page_match.group(1))
        return page, page
    return None, None


def _resolve_doc_preview_lesson_id(state: AgentState | None) -> str:
    if not isinstance(state, dict):
        return ""
    ctx = state.get("context")
    candidates: list[Any] = []
    if isinstance(ctx, dict):
        candidates.extend([ctx.get("lesson_id"), ctx.get("lessonId")])
        for key in ("page_context", "host_context"):
            value = ctx.get(key)
            if isinstance(value, dict):
                candidates.extend([value.get("lesson_id"), value.get("lessonId")])
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return ""


def _resolve_doc_preview_course_id(state: AgentState | None) -> str:
    if not isinstance(state, dict):
        return ""
    ctx = state.get("context")
    candidates: list[Any] = []
    if isinstance(ctx, dict):
        candidates.extend([ctx.get("course_id"), ctx.get("courseId")])
        for key in ("page_context", "host_context"):
            value = ctx.get(key)
            if isinstance(value, dict):
                candidates.extend([value.get("course_id"), value.get("courseId")])
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return ""


def _extract_doc_course_title_from_query(query: str) -> str:
    match = re.search(
        r"(?:course title|ten khoa hoc|tên khóa học|title)\s*(?:la|là|is|:)\s*[\"“”']([^\"“”']{3,140})[\"“”']",
        str(query or ""),
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_doc_preview_line(match.group(1))
    return ""


def _doc_source_reference(
    *,
    title: str,
    excerpt: str = "",
    page_start: int | None = None,
    page_end: int | None = None,
    chapter_index: int | None = None,
    lesson_index: int | None = None,
    kind: str = "document_section",
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "kind": kind,
        "title": title[:160] if title else "Tài liệu đã tải lên",
    }
    if excerpt:
        ref["excerpt"] = excerpt[:360]
    if page_start is not None:
        ref["page_start"] = page_start
    if page_end is not None:
        ref["page_end"] = page_end
    if chapter_index is not None:
        ref["chapter_index"] = chapter_index
    if lesson_index is not None:
        ref["lesson_index"] = lesson_index
    return ref


def _extract_doc_section_references(markdown: str, fallback_title: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    current_heading = ""
    for raw_line in str(markdown or "").replace("\\_", "_").splitlines():
        stripped = raw_line.strip()
        heading_match = re.match(r"^#{1,4}\s+(.+)$", stripped)
        if heading_match:
            heading = _clean_doc_preview_line(heading_match.group(1))
            if heading and not _is_doc_preview_scaffold_line(heading):
                current_heading = heading
            continue
        source_match = re.search(
            r"Nguồn section:\s*(.+?)\s*\(trang\s*(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?\)",
            stripped,
            flags=re.IGNORECASE,
        )
        if not source_match:
            source_match = re.search(
                r"Nguon section:\s*(.+?)\s*\(trang\s*(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?\)",
                stripped,
                flags=re.IGNORECASE,
            )
        if source_match:
            title = _clean_doc_preview_line(source_match.group(1)) or current_heading or fallback_title
            page_start = int(source_match.group(2))
            page_end = int(source_match.group(3) or source_match.group(2))
            refs.append(
                _doc_source_reference(
                    title=title,
                    excerpt=title,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
    if refs:
        return refs[:16]

    heading_refs: list[dict[str, Any]] = []
    for heading in _extract_doc_headings(markdown)[:80]:
        heading_refs.append(
            _doc_source_reference(
                title=heading,
                excerpt=heading,
            )
        )
    if heading_refs:
        return heading_refs

    page_start, page_end = _extract_source_pages("", markdown)
    return [
        _doc_source_reference(
            title=fallback_title,
            excerpt=_first_nonempty_line(markdown),
            page_start=page_start,
            page_end=page_end,
            kind="document",
        )
    ]


def _match_doc_refs(
    refs: list[dict[str, Any]],
    markers: tuple[str, ...],
    *,
    fallback_title: str,
    chapter_index: int | None = None,
    lesson_index: int | None = None,
) -> list[dict[str, Any]]:
    normalized_markers = tuple(_normalize_doc_preview_text(marker) for marker in markers)
    matches: list[dict[str, Any]] = []
    for ref in refs:
        ref_text = _normalize_doc_preview_text(
            f"{ref.get('title', '')} {ref.get('excerpt', '')}"
        )
        if any(marker and marker in ref_text for marker in normalized_markers):
            next_ref = dict(ref)
            if chapter_index is not None:
                next_ref["chapter_index"] = chapter_index
            if lesson_index is not None:
                next_ref["lesson_index"] = lesson_index
            matches.append(next_ref)
    if matches:
        return matches[:3]
    base = dict(refs[0]) if refs else _doc_source_reference(title=fallback_title)
    if chapter_index is not None:
        base["chapter_index"] = chapter_index
    if lesson_index is not None:
        base["lesson_index"] = lesson_index
    return [base]


def _dedupe_doc_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for ref in refs:
        key = (
            str(ref.get("kind") or ""),
            str(ref.get("title") or ""),
            str(ref.get("page_start") or ref.get("page") or ""),
            str(ref.get("page_end") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _top_course_source_references(
    refs: list[dict[str, Any]],
    *,
    title_source: str,
    is_lms_manual: bool,
) -> list[dict[str, Any]]:
    if not is_lms_manual:
        return _dedupe_doc_refs(refs)[:12]
    marker_groups = (
        ("dang nhap", "truy cap"),
        ("hoc vien",),
        ("giang vien",),
        ("tao khoa", "4.2"),
        ("video", "quiz", "4.5"),
        ("quan ly", "duyet"),
        ("su co", "troubleshooting", "xu ly loi"),
    )
    selected: list[dict[str, Any]] = []
    for markers in marker_groups:
        selected.extend(
            _match_doc_refs(
                refs,
                markers,
                fallback_title=title_source,
            )
        )
    selected.extend(refs)
    return _dedupe_doc_refs(selected)[:12]


def _lms_manual_lesson(
    *,
    title: str,
    summary: str,
    activity: str,
    quick_check: str,
    refs: list[dict[str, Any]],
    duration_minutes: int = 18,
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "activity": activity,
        "quick_check": quick_check,
        "duration_minutes": duration_minutes,
        "source_references": refs,
    }


def _build_lms_manual_course_plan(
    *,
    title_source: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapter_specs = [
        {
            "title": "Khởi động: truy cập, đăng nhập và định hướng vai trò",
            "summary": "Giúp người học hiểu bản đồ hệ thống HoLiLiHu LMS trước khi đi vào từng vai trò.",
            "markers": ("dang nhap", "vai tro", "trang chu", "tong quan", "lms"),
            "objectives": [
                "Phân biệt luồng công khai, học viên, giảng viên và quản lý.",
                "Đăng nhập đúng tài khoản và nhận diện workspace theo vai trò.",
                "Biết nơi cần kiểm tra khi không thấy khóa học hoặc chức năng.",
            ],
            "lessons": [
                (
                    "Bản đồ HoLiLiHu LMS và các vai trò chính",
                    "Đọc hệ thống như một bản đồ: trang công khai, khu học viên, khu giảng viên và khu quản lý.",
                    "Cho học viên nối từng vai trò với 3 tác vụ thường gặp.",
                    "Khi một người dùng không thấy nút tạo khóa, cần kiểm tra điều gì trước?",
                    ("vai tro", "tong quan", "lms"),
                ),
                (
                    "Đăng nhập, xác thực và xử lý lỗi truy cập",
                    "Chuẩn hóa thao tác đăng nhập, xác minh tài khoản và nhận biết lỗi phiên đăng nhập.",
                    "Thực hành checklist: email, mật khẩu, trạng thái tài khoản, tổ chức.",
                    "Cần thu thập bằng chứng nào trước khi báo lỗi đăng nhập?",
                    ("dang nhap", "xac thuc", "tai khoan"),
                ),
                (
                    "Điều hướng theo vai trò sau khi vào hệ thống",
                    "Nhận diện đúng menu, sidebar, khóa học hiện tại và các điểm vào nhanh.",
                    "Mỗi nhóm chụp lại một đường đi đến khóa học và giải thích vì sao chọn đường đó.",
                    "Dấu hiệu nào cho thấy người dùng đang ở sai vai trò?",
                    ("menu", "sidebar", "vai tro", "dieu huong"),
                ),
            ],
        },
        {
            "title": "Hành trình học viên: học bài, video tương tác và tiến độ",
            "summary": "Biến phần hướng dẫn học viên thành kịch bản học thật: vào khóa, học bài, làm quiz và theo dõi tiến độ.",
            "markers": ("hoc vien", "video", "quiz", "tien do", "offline"),
            "objectives": [
                "Mở khóa học và đi qua một bài học có nhiều loại nội dung.",
                "Sử dụng video tương tác, tài liệu, quiz và ghi chú đúng ngữ cảnh.",
                "Tự kiểm tra tiến độ, lỗi thường gặp và chế độ học trên thiết bị di động.",
            ],
            "lessons": [
                (
                    "Từ danh sách khóa học đến bài học đầu tiên",
                    "Học viên tìm khóa học, đọc mô tả, vào chương và chọn bài học cần học.",
                    "Mô phỏng một học viên mới nhận lớp và cần tìm bài đầu tiên trong 2 phút.",
                    "Nếu học viên đã ghi danh nhưng không thấy khóa, cần kiểm tra những điểm nào?",
                    ("hoc vien", "khoa hoc", "ghi danh"),
                ),
                (
                    "Học với video, tài liệu và nội dung tương tác",
                    "Khai thác video tương tác, tài liệu đính kèm và các khối nội dung trong một bài học.",
                    "Đánh dấu các điểm cần dừng video để hỏi hoặc kiểm tra nhanh.",
                    "Video tương tác khác video thường ở điểm nào trong trải nghiệm học?",
                    ("video", "tuong tac", "tai lieu"),
                ),
                (
                    "Quiz, bài tập và phản hồi sau khi học",
                    "Hoàn thành kiểm tra, đọc phản hồi và dùng kết quả để quay lại đúng bài học.",
                    "Thiết kế một câu hỏi kiểm tra nhanh cho cuối bài.",
                    "Khi kết quả quiz thấp, học viên nên quay lại thông tin nào?",
                    ("quiz", "bai tap", "kiem tra"),
                ),
                (
                    "Theo dõi tiến độ, học offline và xử lý sự cố học tập",
                    "Đọc thanh tiến độ, trạng thái hoàn thành và các vấn đề thường gặp trên mobile/offline.",
                    "Lập checklist tự xử lý trước khi gửi hỗ trợ.",
                    "Cần gửi ảnh chụp màn hình nào để hỗ trợ kiểm tra nhanh hơn?",
                    ("tien do", "offline", "mobile", "su co"),
                ),
            ],
        },
        {
            "title": "Tác nghiệp giảng viên: thiết kế và soạn khóa học",
            "summary": "Đây là trục trọng tâm cho giáo viên: từ ý tưởng khóa học đến chương, bài, tài liệu, video và quiz.",
            "markers": ("giang vien", "tao khoa", "chuong", "bai hoc", "xuat ban"),
            "objectives": [
                "Tạo khóa học có tiêu đề, mô tả và mục tiêu đủ rõ để duyệt.",
                "Chia nội dung thành chương/bài theo logic học tập thay vì chỉ chép mục lục.",
                "Thêm video, tài liệu và quiz với checklist kiểm tra trước khi gửi duyệt.",
            ],
            "lessons": [
                (
                    "Tạo khóa học mới và viết thông tin khóa học",
                    "Giảng viên nhập tiêu đề, mô tả, mục tiêu, đối tượng và thông tin cần thiết trước khi soạn bài.",
                    "Biến một mô tả mơ hồ thành mô tả khóa học có kết quả học tập đo được.",
                    "Một mô tả khóa học đủ duyệt cần trả lời những câu hỏi nào?",
                    ("tao khoa", "thong tin khoa", "muc tieu"),
                ),
                (
                    "Chia chương/bài theo năng lực cần đạt",
                    "Sắp xếp chương và bài theo hành trình học, tránh bê nguyên mục lục nếu không tạo được tiến trình.",
                    "Từ một tài liệu dài, nhóm thành 4-6 chương có nhịp học rõ.",
                    "Dấu hiệu nào cho thấy một chương đang quá rộng?",
                    ("chuong", "bai hoc", "cau truc"),
                ),
                (
                    "Thêm video, tài liệu và nội dung tương tác",
                    "Gắn đúng loại tài nguyên vào bài học, đặt tên rõ và kiểm tra khả năng xem lại của học viên.",
                    "Soạn checklist trước khi upload video/tài liệu vào bài.",
                    "Tài liệu đính kèm cần có tên và mô tả như thế nào để học viên không bị lạc?",
                    ("video", "tai lieu", "upload", "tuong tac"),
                ),
                (
                    "Soạn quiz và kiểm tra chất lượng trước khi gửi duyệt",
                    "Thiết kế kiểm tra nhanh, câu hỏi tổng kết và kiểm tra trạng thái xuất bản một cách an toàn.",
                    "Viết 3 câu hỏi đo đúng mục tiêu học tập của bài.",
                    "Vì sao quiz không nên được publish trực tiếp khi chưa xem preview?",
                    ("quiz", "kiem tra", "xuat ban", "duyet"),
                ),
            ],
        },
        {
            "title": "Quản lý và vận hành: duyệt khóa, người dùng và chất lượng",
            "summary": "Dành cho người quản lý hoặc tổ chuyên trách vận hành LMS để đảm bảo khóa học lên production an toàn.",
            "markers": ("quan ly", "admin", "duyet", "nguoi dung", "bao cao"),
            "objectives": [
                "Hiểu trách nhiệm duyệt khóa và kiểm tra trước khi mở cho học viên.",
                "Theo dõi người dùng, vai trò, tiến độ và báo cáo vận hành.",
                "Biết khi nào cần trả khóa về cho giảng viên chỉnh sửa.",
            ],
            "lessons": [
                (
                    "Duyệt khóa học theo checklist chất lượng",
                    "Quản lý kiểm tra mục tiêu, chương/bài, nội dung, quiz, tài liệu và khả năng học thật.",
                    "Chấm một khóa mẫu theo checklist duyệt.",
                    "Ba lỗi nào nên trả về cho giảng viên thay vì duyệt ngay?",
                    ("duyet", "chat luong", "xuat ban"),
                ),
                (
                    "Quản lý người dùng, vai trò và quyền truy cập",
                    "Xác minh vai trò, lớp/khóa, tổ chức và phạm vi truy cập để tránh nhầm quyền.",
                    "Vẽ ma trận vai trò - quyền cho một lớp học mẫu.",
                    "Vì sao đổi vai trò cần kiểm tra lại ngay trên phiên kế tiếp?",
                    ("nguoi dung", "vai tro", "quyen"),
                ),
                (
                    "Theo dõi tiến độ, báo cáo và tín hiệu rủi ro",
                    "Đọc tiến độ học tập, phát hiện bài bị bỏ qua, quiz bất thường hoặc lớp ít tương tác.",
                    "Tạo 3 tín hiệu cần theo dõi hằng tuần cho một khóa mới.",
                    "Tín hiệu nào cho thấy nội dung cần được chỉnh lại chứ không phải chỉ nhắc học viên?",
                    ("tien do", "bao cao", "analytics"),
                ),
            ],
        },
        {
            "title": "Triển khai lớp học thật và xử lý sự cố",
            "summary": "Khóa lại bằng checklist vận hành: chuẩn bị trước lớp, hỗ trợ trong lớp và cải tiến sau lớp.",
            "markers": ("troubleshooting", "su co", "checklist", "ho tro", "offline"),
            "objectives": [
                "Chuẩn bị khóa học trước ngày mở lớp bằng checklist có thể kiểm chứng.",
                "Xử lý các lỗi phổ biến: đăng nhập, không thấy khóa, video/tài liệu, quiz và tiến độ.",
                "Thu thập bằng chứng hỗ trợ và cải tiến khóa sau khi chạy thật.",
            ],
            "lessons": [
                (
                    "Checklist trước khi mở lớp",
                    "Kiểm tra người học, nội dung, tài liệu, quiz, quyền truy cập và kênh hỗ trợ trước ngày học.",
                    "Chạy thử một học viên mẫu từ đăng nhập đến hoàn thành bài đầu tiên.",
                    "Điểm nào phải kiểm tra trên tài khoản học viên thật, không chỉ trên tài khoản giảng viên?",
                    ("checklist", "mo lop", "hoc vien"),
                ),
                (
                    "Xử lý lỗi đăng nhập, video, tài liệu và quiz",
                    "Chuẩn hóa cách thu thập thông tin lỗi để hỗ trợ nhanh và không đoán mò.",
                    "Viết mẫu ticket hỗ trợ có đủ bằng chứng.",
                    "Một ticket thiếu ảnh/video lỗi sẽ làm chậm hỗ trợ ở bước nào?",
                    ("su co", "dang nhap", "video", "quiz"),
                ),
                (
                    "Đánh giá sau lớp và cải tiến khóa học",
                    "Dùng phản hồi, tiến độ và lỗi phát sinh để cập nhật tài liệu, quiz và hướng dẫn.",
                    "Chọn 3 cải tiến sau buổi học đầu tiên và gắn với bằng chứng.",
                    "Khi nào nên sửa nội dung bài học thay vì chỉ thêm thông báo?",
                    ("phan hoi", "cai tien", "bao cao"),
                ),
            ],
        },
    ]

    chapters: list[dict[str, Any]] = []
    for chapter_index, chapter in enumerate(chapter_specs, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            chapter["markers"],
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = []
        for lesson_index, (title, summary, activity, quick_check, markers) in enumerate(
            chapter["lessons"],
            start=1,
        ):
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=_match_doc_refs(
                        refs,
                        markers,
                        fallback_title=title_source,
                        chapter_index=chapter_index,
                        lesson_index=lesson_index,
                    ),
                )
            )
        chapters.append(
            {
                "title": chapter["title"],
                "summary": chapter["summary"],
                "learning_objectives": chapter["objectives"],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )

    return {
        "title": "Khai thác HoLiLiHu LMS từ tài liệu hướng dẫn",
        "description": (
            "Khóa học chuyển tài liệu hướng dẫn HoLiLiHu LMS thành lộ trình thực hành "
            "cho học viên, giảng viên và quản lý. Cấu trúc ưu tiên thao tác thật, "
            "kiểm tra chất lượng và citation để giáo viên xác minh trước khi áp dụng."
        ),
        "audience": "Giảng viên, trợ giảng, quản lý đào tạo và học viên cần sử dụng HoLiLiHu LMS.",
        "duration": "5 chương, 16 bài, triển khai trong 3-5 buổi thực hành.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có câu hỏi kiểm tra nhanh gắn với thao tác thật.",
            "Cuối khóa yêu cầu người học hoàn thành một kịch bản: tạo/hoặc tham gia một khóa mẫu, học bài, kiểm tra tiến độ và xử lý một lỗi giả lập.",
            "Giảng viên dùng citation trong preview để đối chiếu từng chương trước khi apply vào LMS.",
        ],
        "implementation_checklist": [
            "Xác minh tên khóa, mô tả, mục tiêu và đối tượng trước khi tạo dữ liệu LMS.",
            "Giữ mọi thay đổi ở trạng thái draft; không publish tự động.",
            "Sau khi apply, giáo viên rà lại từng chapter/lesson, thêm tài nguyên thật và gửi duyệt theo quy trình LMS.",
        ],
        "source_document_title": title_source,
    }


def _extract_doc_headings(markdown: str) -> list[str]:
    headings: list[str] = []
    for raw_line in str(markdown or "").replace("\\_", "_").splitlines():
        stripped = raw_line.strip()
        match = re.match(r"^#{1,4}\s+(.+)$", stripped) or re.match(
            r"^(\d+(?:\.\d+)*\.\s+.{4,120})$",
            stripped,
        )
        if not match:
            continue
        heading = _clean_doc_preview_line(match.group(1))
        if (
            heading
            and not _is_doc_preview_scaffold_line(heading)
            and heading not in headings
        ):
            headings.append(heading[:120])
        if len(headings) >= 80:
            break
    return headings


def _build_generic_document_course_plan(
    *,
    title_source: str,
    markdown: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    headings = _extract_doc_headings(markdown)
    if not headings:
        headings = [
            "Tổng quan tài liệu và mục tiêu học tập",
            "Quy trình chính và khái niệm nền tảng",
            "Thực hành theo tình huống",
            "Kiểm tra, phản hồi và cải tiến",
        ]
    chapter_titles = headings[:6]
    chapters: list[dict[str, Any]] = []
    for chapter_index, heading in enumerate(chapter_titles, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            (heading,),
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = [
            _lms_manual_lesson(
                title=f"Nắm bối cảnh: {heading}",
                summary=f"Rút ra khái niệm, mục tiêu và phạm vi cần học từ phần {heading}.",
                activity="Người học đánh dấu 3 ý chính và 1 điểm còn mơ hồ cần hỏi lại.",
                quick_check="Ý nào trong tài liệu là bằng chứng mạnh nhất cho phần này?",
                refs=chapter_refs,
                duration_minutes=15,
            ),
            _lms_manual_lesson(
                title=f"Thực hành áp dụng: {heading}",
                summary=f"Chuyển nội dung {heading} thành thao tác, checklist hoặc quyết định thực tế.",
                activity="Làm một tình huống ngắn, ghi quyết định và nguồn đối chiếu.",
                quick_check="Nếu áp dụng sai phần này, rủi ro rõ nhất là gì?",
                refs=chapter_refs,
                duration_minutes=20,
            ),
        ]
        chapters.append(
            {
                "title": heading,
                "summary": f"Chương này biến phần {heading} thành nội dung học có mục tiêu, hoạt động và kiểm tra.",
                "learning_objectives": [
                    f"Giải thích được ý chính của {heading}.",
                    "Đối chiếu thao tác với nguồn tài liệu thay vì học thuộc rời rạc.",
                    "Hoàn thành một kiểm tra nhanh dựa trên bằng chứng trong tài liệu.",
                ],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )
    return {
        "title": f"Khóa học từ tài liệu: {title_source[:90]}",
        "description": "Bản thiết kế khóa học được tạo từ tài liệu upload, có cấu trúc chương/bài và nguồn để giáo viên kiểm chứng trước khi áp dụng.",
        "audience": "Người học cần chuyển tài liệu nguồn thành năng lực thực hành.",
        "duration": f"{len(chapters)} chương, {sum(len(ch.get('lessons', [])) for ch in chapters)} bài.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có kiểm tra nhanh gắn với citation.",
            "Cuối khóa dùng một tình huống tổng hợp để xác nhận khả năng áp dụng.",
        ],
        "implementation_checklist": [
            "Giáo viên rà lại tiêu đề chương/bài trước khi apply.",
            "Không publish tự động; mọi nội dung sinh ra ở trạng thái draft.",
        ],
        "source_document_title": title_source,
    }


def _build_uploaded_doc_course_params(query: str, state: AgentState | None) -> dict[str, Any]:
    attachments = _uploaded_document_attachments_from_state(state)
    combined_markdown = "\n\n".join(
        str(item.get("markdown") or "").strip()
        for item in attachments
        if str(item.get("markdown") or "").strip()
    )
    first_attachment = attachments[0] if attachments else {}
    query_title = _extract_doc_course_title_from_query(query)
    title_source = (
        query_title
        or str(first_attachment.get("title") or "").strip()
        or _first_nonempty_line(combined_markdown)
        or str(first_attachment.get("file_name") or "").strip()
        or "Tài liệu đã tải lên"
    )
    refs = _extract_doc_section_references(combined_markdown, title_source)
    domain_text = _normalize_doc_preview_text(
        f"{query}\n{title_source}\n{combined_markdown[:5000]}"
    )
    is_lms_manual = any(
        marker in domain_text
        for marker in ("holilihu", "lms", "giang vien", "hoc vien", "quan ly")
    )
    if is_lms_manual:
        course_plan = _build_lms_manual_course_plan(title_source=title_source, refs=refs)
    else:
        course_plan = _build_generic_document_course_plan(
            title_source=title_source,
            markdown=combined_markdown,
            refs=refs,
        )

    chapters = course_plan.get("chapters") if isinstance(course_plan, dict) else []
    lesson_count = sum(
        len(chapter.get("lessons") or [])
        for chapter in chapters
        if isinstance(chapter, dict)
    )
    params: dict[str, Any] = {
        "action": "preview_course_plan_from_document",
        "title": course_plan.get("title") or title_source,
        "summary": (
            f"Wiii đã dựng cây khóa học nháp gồm {len(chapters)} chương và "
            f"{lesson_count} bài từ tài liệu upload. Giáo viên cần xem citation "
            "trước khi áp dụng vào LMS."
        ),
        "course_plan": course_plan,
        "changed_fields": ["course_structure"],
        "source_references": _top_course_source_references(
            refs,
            title_source=title_source,
            is_lms_manual=is_lms_manual,
        ),
    }
    course_id = _resolve_doc_preview_course_id(state)
    if course_id:
        params["course_id"] = course_id
    return params


def _build_uploaded_doc_preview_params(query: str, state: AgentState | None) -> dict[str, Any]:
    attachments = _uploaded_document_attachments_from_state(state)
    combined_markdown = "\n\n".join(
        str(item.get("markdown") or "").strip()
        for item in attachments
        if str(item.get("markdown") or "").strip()
    )
    first_attachment = attachments[0] if attachments else {}
    query_title = _extract_doc_preview_title_from_query(query)
    title_source = (
        str(first_attachment.get("title") or "").strip()
        or query_title
        or _first_nonempty_line(combined_markdown)
        or str(first_attachment.get("file_name") or "").strip()
        or "Tài liệu đã tải lên"
    )
    focused_markdown = _focus_doc_preview_markdown(query, combined_markdown)
    marker = _extract_marker(query) or _extract_marker(combined_markdown)
    goals = _extract_relevant_lines(
        focused_markdown,
        ("muc tieu hoc tap", "learning objective", "objective", "muc tieu"),
        limit=4,
    )
    if not goals:
        goals = _extract_relevant_lines(
            focused_markdown,
            ("giang vien", "teacher", "hoc vien", "lms", "khoa hoc", "bai hoc"),
            limit=4,
        )
    checklist = _extract_relevant_lines(
        focused_markdown,
        (
            "checklist",
            "nguon trang",
            "source page",
            "approval_token",
            "quy trinh",
            "thao tac",
            "tao khoa",
            "soan",
            "xuat ban",
            "quiz",
        ),
        limit=5,
    )
    if not goals:
        goals = [_first_nonempty_line(focused_markdown) or _first_nonempty_line(combined_markdown)]
    if not checklist:
        checklist = _extract_relevant_lines(focused_markdown, ("quy trinh", "kiem tra", "xac nhan"), limit=4)
    if not checklist:
        checklist = goals[:2]

    source_excerpt = " ".join(checklist[:2])[:360] or _first_nonempty_line(focused_markdown) or _first_nonempty_line(combined_markdown)
    page_start, page_end = _extract_source_pages(query, combined_markdown)
    domain_text = _normalize_doc_preview_text(f"{query}\n{title_source}\n{combined_markdown[:2000]}")
    is_lms_manual = any(marker in domain_text for marker in ("lms", "holilihu", "giang vien", "hoc vien", "quan ly"))
    checklist_heading = (
        "## Checklist thao tác / nội dung cần nắm"
        if is_lms_manual
        else "## Checklist trực ca / nội dung cần nắm"
    )
    discussion_lines = (
        [
            "- Giảng viên thực hành mở đúng khu vực quản lý khóa học, kiểm tra bài học và xác nhận dữ liệu trước khi lưu.",
            "- Nhóm nhỏ ghi lại lỗi thường gặp khi đăng nhập, tạo nội dung hoặc kiểm tra tiến độ học viên.",
        ]
        if is_lms_manual
        else [
            "- Học viên đối chiếu checklist trong tài liệu với một tình huống trực ca thực tế.",
            "- Nhóm nhỏ xác định rủi ro, người cần báo cáo và bằng chứng cần ghi vào nhật ký.",
        ]
    )
    quick_questions = (
        [
            "- Khi tạo hoặc cập nhật bài học trong LMS, giảng viên cần kiểm tra những mục nào trước khi xuất bản?",
            "- Khi học viên báo lỗi đăng nhập hoặc không thấy nội dung, cần thu thập thông tin nào để hỗ trợ?",
        ]
        if is_lms_manual
        else [
            "- Khi tầm nhìn hạn chế, người trực ca cần xác nhận những nguồn thông tin nào trước khi đổi hướng?",
            "- Khi có nguy cơ va chạm, quy trình báo cáo và ghi log nên diễn ra như thế nào?",
        ]
    )
    content_lines = [
        f"# Bản nháp bài học từ tài liệu: {title_source}",
        "",
        *([f"Marker kiểm thử: {marker}", ""] if marker else []),
        "## Mục tiêu học tập",
        *[f"- {_strip_doc_preview_goal_label(line)}" for line in goals[:4]],
        "",
        checklist_heading,
        *[f"- {line}" for line in checklist[:5]],
        "",
        "## Hoạt động thảo luận",
        *discussion_lines,
        "",
        "## Câu hỏi kiểm tra nhanh",
        *quick_questions,
    ]
    description = (
        "Bài học giúp giảng viên chuyển tài liệu hướng dẫn HoLiLiHu LMS thành "
        "các thao tác tạo khóa, soạn chương/bài, thêm video/tài liệu/quiz, "
        "kiểm tra và gửi duyệt một cách an toàn."
        if is_lms_manual
        else "Bài học giúp người học chuyển tài liệu nguồn thành checklist thao tác, "
        "tình huống thực hành và câu hỏi kiểm tra nhanh."
    )

    params: dict[str, Any] = {
        "title": f"Bản nháp: {title_source[:90]}",
        "description": description,
        "content": "\n".join(content_lines),
        "source_references": [
            {
                "kind": "document",
                "title": title_source,
                "page_start": page_start,
                "page_end": page_end,
                "excerpt": source_excerpt,
            }
        ],
    }
    lesson_id = _resolve_doc_preview_lesson_id(state)
    if lesson_id:
        params["lesson_id"] = lesson_id
    return params


def _extract_direct_visible_text(content: Any) -> str:
    """Return the answer text that would be visible to the user."""
    try:
        from app.services.output_processor import extract_thinking_from_response

        text_content, _thinking_content = extract_thinking_from_response(content)
        return str(text_content or "").strip()
    except Exception:
        return str(content or "").strip()


def _build_direct_final_synthesis_instruction(
    query: str,
    state: AgentState,
    tool_names: list[str],
) -> str:
    """Build a mode-aware final synthesis instruction after tool rounds."""
    thinking_mode = _infer_direct_thinking_mode(query, state, tool_names)
    axes = _build_direct_analytical_axes(query, state, tool_names)
    plan = _build_direct_evidence_plan(query, state, tool_names)

    base = (
        "Du lieu da du cho luot nay. Khong goi them cong cu. "
        "Hay tong hop ngay thanh cau tra loi cuoi cung bang tieng Viet, "
        "dua tren cac ket qua cong cu da co."
    )

    if thinking_mode == "analytical_market":
        return (
            base
            + " Mo dau bang mot cau thesis ve mat bang thi truong hien tai, sau do tach cac luc keo chinh "
            + "(cung-cau, OPEC+, ton kho, dia chinh tri) thay vi liet ke tin tuc. "
            + "Neu cac tin hieu xung nhau, hay noi ro truc nao dang giu mat bang gia va truc nao chi tao nhieu ngan han. "
            + "Mac dinh uu tien 2-3 doan chat; chi dung bullet ngan neu can tach watchlist. "
            + "KHONG dung heading Markdown nhu #, ##, ###, va KHONG dung bullet/bold kieu ban tin tong hop. "
            + "Ket bang takeaway hoac dieu can theo doi tiep theo."
        )
    if thinking_mode == "analytical_math":
        return (
            base
            + " Mo dau bang mot cau thesis ve mo hinh dang dung, roi trinh bay theo nhip mo hinh/gia dinh -> phuong trinh hoac suy dan -> y nghia vat ly. "
            + "Noi ro cac gia dinh nhu "
            + (", ".join(axes[:3]) if axes else "mo hinh, goc nho, va phuong trinh")
            + ". Neu ket luan phu thuoc gan dung, noi ro pham vi ma gan dung do con hop le. "
            + "Mac dinh uu tien 2-3 doan chat; KHONG dung heading Markdown nhu #, ##, ### neu user khong yeu cau."
        )
    if thinking_mode == "analytical_general":
        plan_hint = ", ".join(plan[:2]) if plan else "cac bien so chinh va chung cu manh nhat"
        return (
            base
            + " Mo dau bang mot cau thesis co the kiem cheo, di thang vao luan diem, tach dieu chac khoi dieu con nhieu, va neo lai "
            + plan_hint
            + ". Neu co tin hieu trai chieu, noi ro cai nao dang nang ky hon. "
            + "Mac dinh uu tien 2-3 doan chat; chi dung bullet ngan khi user can tach checklist/watchlist. "
            + "KHONG dung heading Markdown nhu #, ##, ###."
        )
    return base


def _build_tool_result_message(
    content: str,
    *,
    tool_call_id: str,
    native_tool_messages: bool,
) -> Any:
    """Create the post-tool message without depending on LangChain."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_tool_message

        return make_tool_message(content, tool_call_id=tool_call_id)

    from app.engine.messages import Message

    return Message(role="tool", content=content, tool_call_id=tool_call_id)


def _validate_pointy_selector(selector: str, state: Any) -> str | None:
    """Validate LLM-provided pointy selector vs available_targets.

    Returns None khi selector OK, hoặc error message string khi hallucinated.
    Error message được trả về như tool_result để LLM thấy + correct round
    tiếp với exact id từ inventory.

    v3.0 anti-hallucination defense (server-side). Compound CSS, aria-label
    patterns, .class selectors đều bị reject vì:

    1. Bypass Wiii's data-wiii-id stable handle priority (architectural)
    2. Brittle vs UI refactors (Tailwind classes, BEM names change)
    3. Silent fail mode trên frontend khi không match real DOM
    """
    if not selector:
        return (
            "ERROR: Empty selector. Required: exact `id` from "
            "tool_pointy_inventory. Example: tool_pointy_show("
            'selector="chat-send-button", caption="..."). Call '
            "tool_pointy_inventory first if unsure."
        )

    # Exact Wiii ids include annotated handles (chat-send-button) and
    # scanner-generated synthetic ids (auto:button:gui-tin-nhan).
    import re
    wiii_id_re = re.compile(
        r"^(?:[a-zA-Z][a-zA-Z0-9_-]*|auto:[a-z0-9_-]+:[a-z0-9_-]+(?:-\d+)?)$"
    )
    is_wiii_id = bool(wiii_id_re.match(selector))

    # Verbose [data-wiii-id="..."] form cũng OK (Wiii's documented selector form).
    is_data_wiii_id_form = bool(
        re.match(r'^\[data-wiii-id=("[\w-]+"|\'[\w-]+\'|[\w-]+)\]$', selector)
    )

    # v9.0 F18: read inventory from BOTH state forms (dict + attr).
    # state can be plain dict (graph_stream_runtime) OR SimpleNamespace.
    def _read_inventory_ids(s: Any) -> list[str]:
        host = None
        if isinstance(s, dict):
            host = s.get("host_context") or (s.get("context") or {}).get("host_context")
        else:
            host = getattr(s, "host_context", None)
        if not isinstance(host, dict):
            return []
        page = host.get("page") or {}
        metadata = page.get("metadata") or {} if isinstance(page, dict) else {}
        targets = metadata.get("available_targets") or []
        if not isinstance(targets, list):
            return []
        return [str(t.get("id")) for t in targets if isinstance(t, dict) and t.get("id")]

    inventory_ids = _read_inventory_ids(state)
    if inventory_ids and selector in inventory_ids:
        return None

    # Bất kỳ form nào KHÔNG phải Wiii id và KHÔNG phải data-wiii-id form
    # → likely hallucination (compound CSS, aria-label, .class, ...).
    if not (is_wiii_id or is_data_wiii_id_form):
        examples = ", ".join(f'"{i}"' for i in inventory_ids[:3]) if inventory_ids else '"chat-send-button"'
        return (
            f"ERROR: Selector {selector!r} is NOT a valid Wiii Pointy id.\n"
            f"DO NOT generate CSS selectors, aria-label patterns, or .class selectors.\n"
            f"REQUIRED: exact id from current inventory. Synthetic auto ids like "
            f"`auto:button:gui-tin-nhan` are valid when they appear in inventory.\n"
            f"Available ids on this page: {inventory_ids[:10]}\n"
            f"Correct form: tool_pointy_show(selector={examples.split(',')[0] if examples else '...'}, caption=\"...\")"
        )

    # Wiii id form: verify exists trong available_targets if inventory available.
    if is_wiii_id and inventory_ids:
        available_list = sorted(set(inventory_ids))[:10]
        return (
            f"ERROR: id {selector!r} không có trong available_targets trên page hiện tại.\n"
            f"Available ids: {available_list}\n"
            f"Re-call tool_pointy_show với một id chính xác từ list trên, "
            f"hoặc nói prose nếu element không tồn tại."
        )

    return None


def _format_pointy_inventory(state: Any) -> str:
    """Format pointable elements + cursor state cho LLM.

    Reads ``state.host_context.page.metadata.available_targets`` (set
    bởi frontend qua HostContextStore Sprint 222 mechanism) plus
    ``state.host_context.page.metadata.cursor_state`` nếu có.

    v3.0 (Battleship): inventory text là PRESCRIPTIVE — mỗi item include
    inline directive ``→ call: tool_pointy_show(selector="<id>")`` để
    LLM khó ignore và không hallucinate compound CSS selectors.
    """
    if state is None:
        return "Pointy inventory unavailable (no chat state)."
    host_context = getattr(state, "host_context", None) or {}
    page = host_context.get("page", {}) if isinstance(host_context, dict) else {}
    metadata = page.get("metadata", {}) if isinstance(page, dict) else {}
    targets = metadata.get("available_targets") or []
    cursor_state = metadata.get("cursor_state")

    lines: list[str] = []
    if not targets:
        lines.append(
            "No pointable elements published by the host. The frontend "
            "may not have integrated PageScanner yet, or this turn ran "
            "without host_context. Use prose to describe locations."
        )
    else:
        visible = [t for t in targets if t.get("visible")]
        offscreen = [t for t in targets if not t.get("visible")]
        lines.append(
            f"Pointable elements ({len(visible)} visible, "
            f"{len(offscreen)} off-screen). USE EXACT id BELOW — DO NOT "
            f"generate CSS / compound / aria-label selectors:"
        )
        display = visible if visible else targets
        for t in display[:30]:
            tid = t.get("id") or t.get("selector") or "?"
            role = t.get("role", "other")
            label = t.get("label") or ""
            click_safe = " (click_safe)" if t.get("click_safe") else ""
            label_part = f' "{label}"' if label else ""
            offscreen_tag = " [offscreen]" if not t.get("visible") else ""
            # v3.0: prescriptive directive — LLM khó ignore inline call hint.
            lines.append(
                f'- id="{tid}" ({role}){label_part}{click_safe}{offscreen_tag}\n'
                f'  → call: tool_pointy_show(selector="{tid}", caption="...")'
            )
        if len(display) > 30:
            lines.append(f"… {len(display) - 30} more elements omitted.")

    if isinstance(cursor_state, dict):
        pos = cursor_state.get("position") or {}
        x = pos.get("x", "?")
        y = pos.get("y", "?")
        state_name = cursor_state.get("awarenessState", "?")
        last = cursor_state.get("currentSelector")
        last_part = f' last_target="{last}"' if last else ""
        lines.append(
            f"Wiii cursor: pos=({x}, {y}) state={state_name}{last_part}"
        )

    # User's real OS cursor (Wiii Pointy v2.5).
    user_cursor = metadata.get("user_cursor_state")
    if isinstance(user_cursor, dict):
        upos = user_cursor.get("position")
        if isinstance(upos, dict):
            ux = upos.get("x", "?")
            uy = upos.get("y", "?")
            idle = user_cursor.get("idle_ms", 0)
            hovered = user_cursor.get("hovered_id")
            hovered_label = user_cursor.get("hovered_label")
            clicked = user_cursor.get("recently_clicked", False)
            parts = [f"User cursor: pos=({ux}, {uy}) idle={idle}ms"]
            if hovered:
                hover_part = f' hovering="{hovered}"'
                if hovered_label:
                    hover_part += f' (label="{hovered_label}")'
                parts.append(hover_part)
            if clicked:
                parts.append("recently_clicked=true")
            lines.append(" ".join(parts))
        else:
            lines.append("User cursor: not yet tracked.")

    # User's attention/presence (Wiii Pointy v2.6 — tab visibility, blur, idle
    # + v2.7 behavior counters: copy/paste/right-click + selected text).
    attention = metadata.get("user_attention")
    if isinstance(attention, dict):
        status = attention.get("status", "?")
        blurs = attention.get("blur_count", 0)
        tab_switches = attention.get("tab_switch_count", 0)
        away_ms = attention.get("total_away_ms", 0)
        last_away = attention.get("last_away_duration_ms", 0)
        parts = [f"User attention: status={status}"]
        if blurs > 0 or tab_switches > 0:
            parts.append(f"blurs={blurs} tab_switches={tab_switches}")
        if away_ms > 0:
            parts.append(f"total_away={away_ms // 1000}s")
        if last_away > 0 and status == "active":
            parts.append(f"just_returned (was away {last_away // 1000}s)")
        # v2.7 behavior counters
        copies = attention.get("copy_count", 0)
        pastes = attention.get("paste_count", 0)
        right_clicks = attention.get("context_menu_count", 0)
        if copies or pastes or right_clicks:
            parts.append(
                f"behaviour: copies={copies} pastes={pastes} right_clicks={right_clicks}"
            )
        lines.append(" ".join(parts))
        # Last selected text on its own line for readability.
        selected = attention.get("last_selected_text")
        if isinstance(selected, str) and selected.strip():
            preview = selected[:60].replace("\n", " ")
            lines.append(f'User selected text: "{preview}"')

    return "\n".join(lines)


def _build_user_instruction_message(
    content: str,
    *,
    native_tool_messages: bool,
) -> Any:
    """Create a user instruction message for final synthesis."""
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_user_message

        return make_user_message(content)

    from app.engine.messages import Message

    return Message(role="user", content=content)


def _build_assistant_message(
    content: str,
    *,
    native_tool_messages: bool,
) -> Any:
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_assistant_message

        return make_assistant_message(content)

    from app.engine.messages import Message

    return Message(role="assistant", content=content)


def _force_skills_for_turn(state: AgentState | None) -> set[str]:
    if not isinstance(state, dict):
        return set()
    force_skills = state.get("force_skills")
    if not force_skills:
        ctx = state.get("context")
        if isinstance(ctx, dict):
            force_skills = ctx.get("force_skills")
    if isinstance(force_skills, (list, tuple, set)):
        return {str(skill).strip().lower() for skill in force_skills if skill}
    return set()


def _has_search_tool_result(tool_call_events: list[dict]) -> bool:
    search_tool_names = {
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
        "tool_search_legal",
        "search_legal",
        "tool_search_maritime",
        "search_maritime",
    }
    return any(
        event.get("type") == "result"
        and str(event.get("name") or "").strip().lower() in search_tool_names
        and str(event.get("result") or "").strip()
        for event in tool_call_events or []
    )


def _has_fetch_tool_result(tool_call_events: list[dict]) -> bool:
    return any(
        event.get("type") == "result"
        and str(event.get("name") or "").strip().lower() in {"tool_fetch_url", "fetch_url"}
        and str(event.get("result") or "").strip()
        for event in tool_call_events or []
    )


def _fold_tool_round_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.lower().replace("đ", "d").split())


def _looks_explicit_web_search_query(query: str) -> bool:
    folded = _fold_tool_round_text(query)
    if not folded:
        return False
    if "@web-search" in folded or "@web_search" in folded:
        return True
    if "web" in folded and any(marker in folded for marker in ("tim", "search", "tra cuu")):
        return True
    return any(
        marker in folded
        for marker in (
            "tim tren mang",
            "tim kiem tren mang",
            "search the web",
            "look up online",
        )
    )


def _is_search_tool_name(name: str) -> bool:
    return str(name or "").strip().lower() in {
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
        "tool_search_legal",
        "search_legal",
        "tool_search_maritime",
        "search_maritime",
    }


def _prefer_official_query_for_known_docs(args: Any, user_query: str) -> dict:
    normalized_args = dict(args or {}) if isinstance(args, dict) else {}
    current_query = str(normalized_args.get("query") or normalized_args.get("q") or "")
    folded = _fold_tool_round_text(f"{user_query} {current_query}")
    if "openai" in folded and "responses api" in folded:
        normalized_args["query"] = (
            "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
        )
    return normalized_args


def _should_return_search_template_after_tool_round(
    *,
    query: str,
    state: AgentState | None,
    tool_call_events: list[dict],
    tool_round: int,
) -> bool:
    if not _has_search_tool_result(tool_call_events):
        return False
    routing_meta = state.get("routing_metadata") if isinstance(state, dict) else {}
    routing_intent = str((routing_meta or {}).get("intent") or "").strip().lower()
    explicit_web = routing_intent == "web_search" or _looks_explicit_web_search_query(query)
    if not explicit_web:
        return False
    search_result_chars = sum(
        len(str(event.get("result") or ""))
        for event in tool_call_events or []
        if event.get("type") == "result" and _is_search_tool_name(str(event.get("name") or ""))
    )
    return (
        _has_fetch_tool_result(tool_call_events)
        or tool_round >= 1
        or search_result_chars >= _RICH_SEARCH_RESULT_CHAR_FLOOR
    )


def _is_explicit_web_search_turn(query: str, state: AgentState | None) -> bool:
    routing_meta = state.get("routing_metadata") if isinstance(state, dict) else {}
    routing_intent = str((routing_meta or {}).get("intent") or "").strip().lower()
    return (
        "web-search" in _force_skills_for_turn(state)
        or routing_intent == "web_search"
        or _looks_explicit_web_search_query(query)
    )


def _should_use_search_template_for_empty_response(
    *,
    query: str,
    state: AgentState | None,
    tool_call_events: list[dict],
) -> bool:
    return (
        _is_explicit_web_search_turn(query, state)
        and _has_search_tool_result(tool_call_events)
    )


def _clean_forced_web_search_query(query: str) -> str:
    """Convert an explicit @web-search turn into a clean tool query."""
    text = str(query or "").strip()
    text = re.sub(r"(?i)@web-search\b", "", text).strip()
    text = re.split(
        r"(?i)\b(?:trả\s+lời|tra\s+loi|answer|respond|reply)\b",
        text,
        maxsplit=1,
    )[0].strip()
    text = text.strip(" .:-–—")
    return text or str(query or "").strip()


async def execute_direct_tool_rounds_impl(
    llm_with_tools,
    llm_auto,
    messages: list,
    tools: list,
    push_event,
    *,
    runtime_context_base=None,
    max_rounds: int = 3,
    query: str = "",
    state: Optional[AgentState] = None,
    provider: str | None = None,
    forced_tool_choice: str | None = None,
    llm_base=None,
    direct_answer_timeout_profile: str | None = None,
    direct_answer_primary_timeout: float | None = None,
    allowed_fallback_providers: tuple[str, ...] | list[str] | set[str] | None = None,
    ainvoke_with_fallback,
    stream_direct_answer_with_fallback,
    stream_direct_wait_heartbeats,
    push_status_only_progress,
    native_tool_messages: bool = False,
):
    """Execute multi-round tool calling loop for direct response."""
    from app.engine.tools.invocation import (
        get_tool_by_name as _get_tool_by_name_impl,
        invoke_tool_with_runtime as _invoke_tool_with_runtime_impl,
    )
    from app.engine.multi_agent.direct_runtime_bindings import (
        _extract_runtime_target,
        _inject_widget_blocks_from_tool_results,
        _remember_runtime_target,
    )
    from app.engine.llm_pool import (
        FAILOVER_MODE_AUTO,
        FAILOVER_MODE_PINNED,
        TIMEOUT_PROFILE_BACKGROUND,
        TIMEOUT_PROFILE_STRUCTURED,
    )

    tool_call_events: list[dict] = []
    state = state or {}
    direct_thinking_stop = asyncio.Event()
    visual_decision = resolve_visual_intent(query)
    requires_visual_commit = (
        visual_decision.force_tool
        and visual_decision.presentation_intent in {"article_figure", "chart_runtime"}
    )
    initial_timeout_profile = (
        TIMEOUT_PROFILE_STRUCTURED if visual_decision.force_tool else None
    )
    followup_timeout_profile = (
        TIMEOUT_PROFILE_BACKGROUND
        if requires_visual_commit
        else TIMEOUT_PROFILE_STRUCTURED
    )
    visual_emitted_any = False
    request_failover_mode = (
        FAILOVER_MODE_PINNED
        if provider and str(provider).strip().lower() != "auto"
        else FAILOVER_MODE_AUTO
    )
    resolved_provider = _extract_runtime_target(llm_base or llm_auto or llm_with_tools)[0]
    graph_module = sys.modules.get("app.engine.multi_agent.graph")
    graph_ainvoke_with_fallback = getattr(
        graph_module,
        "_ainvoke_with_fallback",
        ainvoke_with_fallback,
    )
    graph_stream_direct_answer_with_fallback = getattr(
        graph_module,
        "_stream_direct_answer_with_fallback",
        stream_direct_answer_with_fallback,
    )
    graph_stream_direct_wait_heartbeats = getattr(
        graph_module,
        "_stream_direct_wait_heartbeats",
        stream_direct_wait_heartbeats,
    )
    graph_build_direct_tool_reflection = getattr(
        graph_module,
        "_build_direct_tool_reflection",
        _build_direct_tool_reflection,
    )
    graph_maybe_emit_host_action_event = getattr(
        graph_module,
        "_maybe_emit_host_action_event",
        _maybe_emit_host_action_event,
    )
    graph_maybe_emit_visual_event = getattr(
        graph_module,
        "_maybe_emit_visual_event",
        _maybe_emit_visual_event,
    )
    graph_emit_visual_commit_events = getattr(
        graph_module,
        "_emit_visual_commit_events",
        _emit_visual_commit_events,
    )
    graph_get_tool_by_name = getattr(
        graph_module,
        "get_tool_by_name",
        _get_tool_by_name_impl,
    )
    graph_invoke_tool_with_runtime = getattr(
        graph_module,
        "invoke_tool_with_runtime",
        _invoke_tool_with_runtime_impl,
    )

    def remember_execution_target(
        candidate_llm: Any,
        fallback_source: Any | None = None,
    ) -> tuple[str | None, str | None]:
        provider_name, model_name = _remember_runtime_target(state, candidate_llm)
        if (not provider_name or not model_name) and fallback_source is not None:
            fallback_provider, fallback_model = _remember_runtime_target(
                state,
                fallback_source,
            )
            provider_name = provider_name or fallback_provider
            model_name = model_name or fallback_model
        return provider_name, model_name

    def runtime_tier_for(
        candidate_llm: Any,
        fallback_source: Any | None = None,
    ) -> str:
        for source in (candidate_llm, fallback_source, llm_base, llm_auto, llm_with_tools):
            tier_value = getattr(source, "_wiii_tier_key", None) if source is not None else None
            if isinstance(tier_value, str) and tier_value.strip():
                return tier_value.strip().lower()
        return "moderate"

    opening_cue, direct_thinking_stop, initial_heartbeat, opening_thinking_started = await start_direct_opening_phase_impl(
        query=query,
        state=state,
        push_event=push_event,
        infer_direct_reasoning_cue=_infer_direct_reasoning_cue,
        stream_direct_wait_heartbeats=graph_stream_direct_wait_heartbeats,
    )
    streamed_direct_answer = False
    try:
        if tools and "web-search" in _force_skills_for_turn(state):
            forced_search_tool = None
            forced_search_tool_name = ""
            for candidate_name in _FORCED_WEB_SEARCH_TOOL_NAMES:
                forced_search_tool = graph_get_tool_by_name(tools, candidate_name)
                if forced_search_tool:
                    forced_search_tool_name = candidate_name
                    break

            if forced_search_tool is not None:
                tc_id = "forced_web_search_0"
                tc_args = {"query": _clean_forced_web_search_query(query)}
                await push_event(
                    {
                        "type": "tool_call",
                        "content": {
                            "name": forced_search_tool_name,
                            "args": tc_args,
                            "id": tc_id,
                        },
                        "node": "direct",
                    }
                )
                tool_call_events.append(
                    {
                        "type": "call",
                        "name": forced_search_tool_name,
                        "args": tc_args,
                        "id": tc_id,
                    }
                )
                try:
                    result = await graph_invoke_tool_with_runtime(
                        forced_search_tool,
                        tc_args,
                        tool_name=forced_search_tool_name,
                        runtime_context_base=runtime_context_base,
                        tool_call_id=tc_id,
                        query_snippet=str(tc_args.get("query", ""))[:100],
                        prefer_async=False,
                        run_sync_in_thread=True,
                    )
                except Exception as tool_error:
                    logger.warning(
                        "[DIRECT] Forced @web-search tool failed: %s",
                        tool_error,
                    )
                    result = "Tool unavailable"

                await push_event(
                    {
                        "type": "tool_result",
                        "content": {
                            "name": forced_search_tool_name,
                            "result": _summarize_tool_result_for_stream(
                                forced_search_tool_name,
                                result,
                            ),
                            "id": tc_id,
                        },
                        "node": "direct",
                    }
                )
                tool_call_events.append(
                    {
                        "type": "result",
                        "name": forced_search_tool_name,
                        "result": result,
                        "id": tc_id,
                    }
                )
                template_response = ""
                try:
                    template_response = build_search_template_fallback(
                        query=query,
                        tool_call_events=tool_call_events,
                    )
                except Exception as template_error:  # noqa: BLE001
                    logger.warning(
                        "[DIRECT] Forced @web-search template synthesis failed: %s",
                        template_error,
                    )
                if not template_response:
                    template_response = (
                        "Mình đã gọi web-search, nhưng chưa lấy được nguồn đủ rõ "
                        "để tổng hợp chắc tay cho lượt này. Cậu thử đổi từ khóa "
                        "hẹp hơn một chút nhé."
                    )
                web_thinking = (
                    "Mình nhận đây là lượt @web-search rõ ràng, nên ưu tiên gọi "
                    "tool_web_search trước khi viết câu trả lời. Mình chỉ tổng hợp "
                    "từ URL/snippet tool trả về; nếu synthesizer chậm hoặc rỗng thì "
                    "dùng fallback có nguồn thay vì trả lời bằng lời xin lỗi rỗng."
                )
                state["thinking"] = web_thinking
                state["thinking_content"] = web_thinking
                record_thinking_snapshot(
                    state,
                    web_thinking,
                    node="direct",
                    provenance="deterministic_forced_web_search",
                )
                await push_event(
                    {
                        "type": "thinking_start",
                        "content": "",
                        "node": "direct",
                        "summary": "Tra cứu web có nguồn",
                    }
                )
                await push_event(
                    {
                        "type": "thinking_delta",
                        "content": web_thinking,
                        "node": "direct",
                    }
                )
                await push_event(
                    {
                        "type": "thinking_end",
                        "content": "",
                        "node": "direct",
                    }
                )
                logger.info(
                    "[DIRECT] Forced @web-search executed deterministically "
                    "without planner LLM (events=%d, len=%d)",
                    len(tool_call_events),
                    len(template_response),
                )
                return (
                    _build_assistant_message(
                        template_response,
                        native_tool_messages=native_tool_messages,
                    ),
                    messages,
                    tool_call_events,
                )

        if _should_request_uploaded_doc_course_preview(query=query, state=state, tools=tools):
            forced_course_tool = _find_doc_course_host_action_tool(tools)
            if forced_course_tool is not None:
                tc_id = "forced_doc_course_preview_0"
                tc_args = _build_uploaded_doc_course_params(query, state)
                await push_event(
                    {
                        "type": "tool_call",
                        "content": {
                            "name": _DOC_COURSE_HOST_ACTION_TOOL,
                            "args": tc_args,
                            "id": tc_id,
                        },
                        "node": "direct",
                    }
                )
                tool_call_events.append(
                    {
                        "type": "call",
                        "name": _DOC_COURSE_HOST_ACTION_TOOL,
                        "args": tc_args,
                        "id": tc_id,
                    }
                )
                try:
                    result = await graph_invoke_tool_with_runtime(
                        forced_course_tool,
                        tc_args,
                        tool_name=_DOC_COURSE_HOST_ACTION_TOOL,
                        runtime_context_base=runtime_context_base,
                        tool_call_id=tc_id,
                        query_snippet=str(tc_args.get("title", ""))[:100],
                        prefer_async=False,
                        run_sync_in_thread=True,
                    )
                except Exception as tool_error:
                    logger.warning(
                        "[DIRECT] Deterministic document course host action failed: %s",
                        tool_error,
                    )
                    result = "Tool unavailable"

                await push_event(
                    {
                        "type": "tool_result",
                        "content": {
                            "name": _DOC_COURSE_HOST_ACTION_TOOL,
                            "result": _summarize_tool_result_for_stream(
                                _DOC_COURSE_HOST_ACTION_TOOL,
                                result,
                            ),
                            "id": tc_id,
                        },
                        "node": "direct",
                    }
                )
                await graph_maybe_emit_host_action_event(
                    push_event=push_event,
                    tool_name=_DOC_COURSE_HOST_ACTION_TOOL,
                    result=result,
                    node="direct",
                    tool_call_events=tool_call_events,
                )
                tool_call_events.append(
                    {
                        "type": "result",
                        "name": _DOC_COURSE_HOST_ACTION_TOOL,
                        "result": str(result),
                        "id": tc_id,
                    }
                )
                doc_course_thinking = (
                    "Mình nhận đây là flow tạo cấu trúc khóa học từ tài liệu upload. "
                    "Vì thao tác này có thể sinh nhiều chương/bài trong LMS, mình dựng "
                    "course_plan có citation trước và chỉ gửi host action preview; LMS sẽ "
                    "yêu cầu giáo viên bấm Apply để cấp approval_token trước khi ghi dữ liệu."
                )
                state["thinking"] = doc_course_thinking
                state["thinking_content"] = doc_course_thinking
                record_thinking_snapshot(
                    state,
                    doc_course_thinking,
                    node="direct",
                    provenance="deterministic_document_course_host_action",
                )
                await push_event(
                    {
                        "type": "thinking_start",
                        "content": "",
                        "node": "direct",
                        "summary": "Tạo cây khóa học từ tài liệu",
                    }
                )
                await push_event(
                    {
                        "type": "thinking_delta",
                        "content": doc_course_thinking,
                        "node": "direct",
                    }
                )
                await push_event(
                    {
                        "type": "thinking_end",
                        "content": "",
                        "node": "direct",
                    }
                )
                response = (
                    "Mình đã gửi bản thiết kế khóa học từ tài liệu sang LMS. "
                    "Bạn xem cây chương/bài và citation trong hộp preview, rồi chỉ bấm Apply "
                    "nếu muốn LMS tạo các chương/bài draft tương ứng."
                )
                logger.info(
                    "[DIRECT] Deterministic document course host action requested "
                    "(attachments=%d, source_refs=%d)",
                    len(_uploaded_document_attachments_from_state(state)),
                    len(tc_args.get("source_references") or []),
                )
                return (
                    _build_assistant_message(
                        response,
                        native_tool_messages=native_tool_messages,
                    ),
                    messages,
                    tool_call_events,
                )

        if _should_request_uploaded_doc_preview(query=query, state=state, tools=tools):
            forced_preview_tool = _find_doc_preview_host_action_tool(tools)
            if forced_preview_tool is not None:
                tc_id = "forced_doc_preview_0"
                tc_args = _build_uploaded_doc_preview_params(query, state)
                await push_event(
                    {
                        "type": "tool_call",
                        "content": {
                            "name": _DOC_PREVIEW_HOST_ACTION_TOOL,
                            "args": tc_args,
                            "id": tc_id,
                        },
                        "node": "direct",
                    }
                )
                tool_call_events.append(
                    {
                        "type": "call",
                        "name": _DOC_PREVIEW_HOST_ACTION_TOOL,
                        "args": tc_args,
                        "id": tc_id,
                    }
                )
                try:
                    result = await graph_invoke_tool_with_runtime(
                        forced_preview_tool,
                        tc_args,
                        tool_name=_DOC_PREVIEW_HOST_ACTION_TOOL,
                        runtime_context_base=runtime_context_base,
                        tool_call_id=tc_id,
                        query_snippet=str(tc_args.get("title", ""))[:100],
                        prefer_async=False,
                        run_sync_in_thread=True,
                    )
                except Exception as tool_error:
                    logger.warning(
                        "[DIRECT] Deterministic document preview host action failed: %s",
                        tool_error,
                    )
                    result = "Tool unavailable"

                await push_event(
                    {
                        "type": "tool_result",
                        "content": {
                            "name": _DOC_PREVIEW_HOST_ACTION_TOOL,
                            "result": _summarize_tool_result_for_stream(
                                _DOC_PREVIEW_HOST_ACTION_TOOL,
                                result,
                            ),
                            "id": tc_id,
                        },
                        "node": "direct",
                    }
                )
                await graph_maybe_emit_host_action_event(
                    push_event=push_event,
                    tool_name=_DOC_PREVIEW_HOST_ACTION_TOOL,
                    result=result,
                    node="direct",
                    tool_call_events=tool_call_events,
                )
                tool_call_events.append(
                    {
                        "type": "result",
                        "name": _DOC_PREVIEW_HOST_ACTION_TOOL,
                        "result": str(result),
                        "id": tc_id,
                    }
                )
                doc_preview_thinking = (
                    "Mình nhận đây là flow upload tài liệu -> tạo preview bài học. "
                    "Vì đây là đường ghi LMS có ràng buộc an toàn, mình không chờ model tự gọi tool; "
                    "mình dựng payload preview từ document_context và gửi host action preview-only để LMS mở diff/citation trước."
                )
                state["thinking"] = doc_preview_thinking
                state["thinking_content"] = doc_preview_thinking
                record_thinking_snapshot(
                    state,
                    doc_preview_thinking,
                    node="direct",
                    provenance="deterministic_document_preview_host_action",
                )
                await push_event(
                    {
                        "type": "thinking_start",
                        "content": "",
                        "node": "direct",
                        "summary": "Tao preview bai hoc tu tai lieu",
                    }
                )
                await push_event(
                    {
                        "type": "thinking_delta",
                        "content": doc_preview_thinking,
                        "node": "direct",
                    }
                )
                await push_event(
                    {
                        "type": "thinking_end",
                        "content": "",
                        "node": "direct",
                    }
                )
                response = (
                    "Mình đã gửi bản preview từ tài liệu sang LMS. "
                    "Bạn kiểm tra diff và citation trong hộp xem trước, rồi chỉ bấm Apply nếu nội dung đúng."
                )
                logger.info(
                    "[DIRECT] Deterministic document preview host action requested "
                    "(attachments=%d, source_refs=%d)",
                    len(_uploaded_document_attachments_from_state(state)),
                    len(tc_args.get("source_references") or []),
                )
                return (
                    _build_assistant_message(
                        response,
                        native_tool_messages=native_tool_messages,
                    ),
                    messages,
                    tool_call_events,
                )

        if tools and forced_tool_choice:
            # Forced tool choice — use ainvoke to ensure tool calls happen
            candidate_provider, _candidate_model = remember_execution_target(
                llm_with_tools,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response = await graph_ainvoke_with_fallback(
                llm_with_tools,
                messages,
                tools=tools,
                tool_choice=forced_tool_choice,
                tier=runtime_tier_for(llm_with_tools, llm_base),
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                push_event=push_event,
                timeout_profile=initial_timeout_profile,
                state=state,
                allowed_fallback_providers=allowed_fallback_providers,
            )
        else:
            candidate_provider, _candidate_model = remember_execution_target(
                llm_with_tools,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response, streamed_direct_answer = await graph_stream_direct_answer_with_fallback(
                llm_with_tools,
                messages,
                push_event,
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                thinking_stop_signal=direct_thinking_stop,
                thinking_block_opened=opening_thinking_started,
                state=state,
                primary_timeout=direct_answer_primary_timeout,
                timeout_profile=direct_answer_timeout_profile,
                allowed_fallback_providers=allowed_fallback_providers,
            )
    finally:
        await finalize_direct_opening_phase_impl(
            thinking_stop=direct_thinking_stop,
            heartbeat_task=initial_heartbeat,
            logger_obj=logger,
        )

    tool_calls = getattr(llm_response, "tool_calls", [])
    logger.warning(
        "[DIRECT] LLM response: tool_calls=%d, content_len=%d",
        len(tool_calls) if tool_calls else 0,
        len(str(llm_response.content)),
    )
    if not streamed_direct_answer and opening_thinking_started:
        await push_event({"type": "thinking_end", "content": "", "node": "direct"})

    # Phase 35 — normalize tool_call shapes. NVIDIA OpenAI-compat returns
    # raw dicts; Google compat + Anthropic adapter convert via
    # `from_openai_response` → pydantic `ToolCall(id, name, arguments)`.
    # Existing loop body assumes dict access (`tc.get("args")`). Normalize
    # here so both shapes work without rewriting 50+ lines downstream.
    def _normalize_tc(tc) -> dict:
        if isinstance(tc, dict):
            return tc
        return {
            "id": getattr(tc, "id", "") or "",
            "name": getattr(tc, "name", "") or "",
            "args": getattr(tc, "arguments", None)
                    or getattr(tc, "args", None)
                    or {},
        }

    for tool_round in range(max_rounds):
        if not (tools and hasattr(llm_response, "tool_calls") and llm_response.tool_calls):
            break
        normalized_tool_calls = [_normalize_tc(tc) for tc in llm_response.tool_calls]
        round_tool_names = [
            str(tc.get("name", "unknown"))
            for tc in normalized_tool_calls
            if tc.get("name")
        ]
        round_cue = _infer_direct_reasoning_cue(query, state, round_tool_names)
        messages.append(llm_response)
        visual_session_ids: list[str] = []
        active_visual_session_ids = _collect_active_visual_session_ids(state)
        for tc in normalized_tool_calls:
            tc_id = tc.get("id", f"tc_{tool_round}")
            tc_name = tc.get("name", "unknown")
            tc_args = tc.get("args", {}) or {}
            if _is_search_tool_name(str(tc_name)):
                tc_args = _prefer_official_query_for_known_docs(tc_args, query)
                tc["args"] = tc_args
            await push_event(
                {
                    "type": "tool_call",
                    "content": {"name": tc_name, "args": tc_args, "id": tc_id},
                    "node": "direct",
                }
            )
            tool_call_events.append(
                {
                    "type": "call",
                    "name": tc_name,
                    "args": tc_args,
                    "id": tc_id,
                }
            )
            matched = graph_get_tool_by_name(tools, str(tc_name).strip())
            try:
                if matched:
                    result = await graph_invoke_tool_with_runtime(
                        matched,
                        tc_args,
                        tool_name=tc_name,
                        runtime_context_base=runtime_context_base,
                        tool_call_id=tc_id,
                        query_snippet=str(tc_args.get("query", ""))[:100],
                        prefer_async=False,
                        run_sync_in_thread=True,
                    )
                else:
                    # Phase 35 — when LLM hallucinates a tool name (or DSML
                    # parser extracts a bad name), don't surface "Unknown tool"
                    # to the user's source list. Log warning + return a
                    # structured error result so the model can recover.
                    logger.warning(
                        "[DIRECT] LLM called unknown tool name=%r — skipping",
                        tc_name,
                    )
                    result = (
                        f"Lỗi: không tìm thấy tool `{tc_name}` trong registry. "
                        "Hãy gọi đúng tên tool có sẵn."
                    )
            except Exception as tool_error:
                logger.warning("[DIRECT] Tool %s failed: %s", tc_name, tool_error)
                result = "Tool unavailable"
            await push_event(
                {
                    "type": "tool_result",
                    "content": {
                        "name": tc_name,
                        "result": _summarize_tool_result_for_stream(tc_name, result),
                        "id": tc_id,
                    },
                    "node": "direct",
                }
            )
            # Wiii Pointy — agent invoked tool_pointy_show / clear.
            #
            # v3.0 anti-hallucination: validate selector vs available_targets
            # BEFORE emit SSE. Khi LLM hallucinate (compound CSS, aria-label
            # patterns, .class selectors) → return structured error trong
            # tool_result. AI nhận error message → tự correct round tiếp với
            # exact id từ inventory.
            if tc_name in ("tool_pointy_show", "tool_pointy_clear"):
                try:
                    from app.engine.tools.pointy_tools import build_pointy_event
                    if tc_name == "tool_pointy_clear":
                        pointy_payload = build_pointy_event(mode="clear")
                        validation_error = None
                    else:
                        pointy_args = tc.get("args", {}) or {}
                        raw_selector = str(pointy_args.get("selector", "")).strip()
                        # Validate selector vs inventory.
                        validation_error = _validate_pointy_selector(
                            raw_selector, state
                        )
                        if validation_error:
                            # Hallucinated → override result với error message
                            # cho LLM thấy. Skip SSE dispatch.
                            result = validation_error
                            logger.warning(
                                "[POINTY] selector validation FAILED: %s | raw=%r",
                                validation_error[:120],
                                raw_selector[:80],
                            )
                            pointy_payload = None
                        else:
                            pointy_payload = build_pointy_event(
                                selector=raw_selector,
                                caption=str(pointy_args.get("caption", "")),
                                duration_ms=int(pointy_args.get("duration_ms", 4500) or 4500),
                                mode=str(pointy_args.get("mode", "highlight") or "highlight"),
                            )
                    if pointy_payload is not None:
                        await push_event({
                            "type": "pointy_action",
                            "content": pointy_payload,
                            "node": "direct",
                        })
                        logger.info(
                            "[POINTY] dispatched action=%s selector=%r (direct)",
                            pointy_payload.get("action"),
                            pointy_payload.get("params", {}).get("selector"),
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[POINTY] direct emit failed: %s", exc)

            # Wiii Pointy inventory query — replace the tool's [POINTY:
            # inventory] ack with the actual list of available_targets
            # from host context so the LLM has something useful to read
            # in its next round.
            if tc_name == "tool_pointy_inventory":
                try:
                    inventory_text = _format_pointy_inventory(state)
                    # Replace the result the LLM will see with the
                    # actual inventory (overwrite the ack string).
                    result = inventory_text
                    logger.info(
                        "[POINTY] inventory served (%d chars)",
                        len(inventory_text),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[POINTY] inventory format failed: %s", exc)
            await graph_maybe_emit_host_action_event(
                push_event=push_event,
                tool_name=tc_name,
                result=result,
                node="direct",
                tool_call_events=tool_call_events,
            )
            emitted_visual_session_ids, disposed_visual_session_ids = await graph_maybe_emit_visual_event(
                push_event=push_event,
                tool_name=tc_name,
                tool_call_id=tc_id,
                result=result,
                node="direct",
                tool_call_events=tool_call_events,
                previous_visual_session_ids=active_visual_session_ids,
            )
            if emitted_visual_session_ids:
                visual_session_ids.extend(emitted_visual_session_ids)
                active_visual_session_ids = list(dict.fromkeys(emitted_visual_session_ids))
                visual_emitted_any = True
            elif disposed_visual_session_ids:
                disposed = set(disposed_visual_session_ids)
                active_visual_session_ids = [
                    session_id
                    for session_id in active_visual_session_ids
                    if session_id not in disposed
                ]
            reflection = await graph_build_direct_tool_reflection(state, tc_name, result)
            if reflection:
                await push_status_only_progress(
                    push_event,
                    node="direct",
                    content=reflection,
                    subtype="tool_reflection",
                )
            tool_call_events.append(
                {
                    "type": "result",
                    "name": tc_name,
                    "result": str(result),
                    "id": tc_id,
                }
            )
            messages.append(
                _build_tool_result_message(
                    str(result),
                    tool_call_id=tc_id,
                    native_tool_messages=native_tool_messages,
                )
            )

            # Phase 3: Detect handoff tool call and set state signal
            if state is not None and tc_name == "handoff_to_agent" and settings.enable_agent_handoffs:
                try:
                    from app.engine.multi_agent.handoff_tools import extract_handoff_target
                    target = extract_handoff_target(tc.get("args", {}))
                    if target:
                        state["_handoff_target"] = target
                        logger.info("[DIRECT] Agent handoff requested → %s", target)
                except Exception:
                    pass
        await graph_emit_visual_commit_events(
            push_event=push_event,
            node="direct",
            visual_session_ids=visual_session_ids,
            tool_call_events=tool_call_events,
        )

        if (
            "web-search" in _force_skills_for_turn(state)
            and _has_search_tool_result(tool_call_events)
        ):
            template_response = ""
            try:
                template_response = build_search_template_fallback(
                    query=query,
                    tool_call_events=tool_call_events,
                )
            except Exception as template_error:  # noqa: BLE001
                logger.warning(
                    "[DIRECT] Forced @web-search template synthesis failed: %s",
                    template_error,
                )
            if template_response:
                logger.info(
                    "[DIRECT] Forced @web-search returning source-backed template "
                    "immediately after tool result (events=%d, len=%d)",
                    len(tool_call_events),
                    len(template_response),
                )
                return (
                    _build_assistant_message(
                        template_response,
                        native_tool_messages=native_tool_messages,
                    ),
                    messages,
                    tool_call_events,
                )

        # Phase 35 — convergence self-eval rubric injected after round 0.
        # SOTA Anthropic Claude tool-use pattern: explicit "is info sufficient?"
        # check between rounds. ONLY inject when round 0 returned sparse content
        # (< 2500 chars) — when search already rich, avoid extra NVIDIA round
        # (each round adds 30-60s on free tier).
        if _should_return_search_template_after_tool_round(
            query=query,
            state=state,
            tool_call_events=tool_call_events,
            tool_round=tool_round,
        ):
            template_response = ""
            try:
                template_response = build_search_template_fallback(
                    query=query,
                    tool_call_events=tool_call_events,
                )
            except Exception as template_error:  # noqa: BLE001
                logger.warning(
                    "[DIRECT] Explicit web-search template synthesis failed: %s",
                    template_error,
                )
            if template_response:
                logger.info(
                    "[DIRECT] Explicit web-search returning source-backed template "
                    "after tool evidence (round=%d, events=%d, len=%d)",
                    tool_round,
                    len(tool_call_events),
                    len(template_response),
                )
                return (
                    _build_assistant_message(
                        template_response,
                        native_tool_messages=native_tool_messages,
                    ),
                    messages,
                    tool_call_events,
                )

        if tool_round == 0 and tool_call_events and not requires_visual_commit:
            search_tool_names = {
                "tool_web_search", "tool_search_news",
                "tool_search_legal", "tool_search_maritime", "tool_fetch_url",
            }
            had_search_tool = any(
                str(ev.get("name") or "").strip() in search_tool_names
                for ev in tool_call_events
                if ev.get("type") == "call"
            )
            # Compute total content volume from this round's tool results.
            total_result_chars = sum(
                len(str(ev.get("result") or ""))
                for ev in tool_call_events
                if ev.get("type") == "result"
            )
            if had_search_tool and total_result_chars < 2500:
                messages.append(
                    _build_user_instruction_message(
                        "Đánh giá nhanh kết quả vừa rồi:\n"
                        "- Số liệu cụ thể (giá / con số / ngày): ĐỦ hay THIẾU?\n"
                        "- Bối cảnh / lý do biến động: ĐỦ hay THIẾU?\n"
                        "- Tin nóng địa chính trị (Iran, OPEC+, Hormuz, Fed) "
                        "có liên quan: đã search chưa?\n\n"
                        "Nếu THIẾU mục nào → gọi 1 tool bổ sung (tool_search_news "
                        "với query KHÁC, hoặc tool_fetch_url trên URL hứa hẹn nhất).\n"
                        "Nếu ĐỦ → trả lời NGAY với cấu trúc: số liệu chính (bold) + "
                        "bối cảnh 2-3 câu + takeaway 1-2 câu. KHÔNG search lại.\n\n"
                        "Định dạng số: '110.01' KHÔNG '110, 01'; '13:18' KHÔNG '13: 18'.",
                        native_tool_messages=native_tool_messages,
                    )
                )
                logger.info(
                    "[DIRECT] Convergence self-eval injected (round 0 sparse: %d chars)",
                    total_result_chars,
                )
            elif had_search_tool:
                # Round 0 already rich → hint LLM to STOP and synthesize.
                messages.append(
                    _build_user_instruction_message(
                        "Kết quả search đã đủ phong phú. Trả lời NGAY (KHÔNG gọi "
                        "thêm tool) với cấu trúc: số liệu chính (bold) + bối cảnh "
                        "2-3 câu + takeaway 1-2 câu.\n"
                        "Định dạng số: '110.01' KHÔNG '110, 01'; '13:18' KHÔNG '13: 18'.",
                        native_tool_messages=native_tool_messages,
                    )
                )
                logger.info(
                    "[DIRECT] Convergence STOP-hint injected (round 0 rich: %d chars)",
                    total_result_chars,
                )
        post_tool_heartbeat = asyncio.create_task(
            graph_stream_direct_wait_heartbeats(
                push_event,
                query=query,
                phase="ground",
                cue=round_cue,
                tool_names=round_tool_names,
            )
        )
        try:
            # After the first forced call, keep tool declarations via llm_auto
            # but do not force another tool call; otherwise current/news turns
            # can loop through tools until max_rounds before synthesizing.
            followup_llm = llm_auto
            followup_tool_choice = None
            followup_tools = tools
            bind_source = None
            if requires_visual_commit and not visual_emitted_any:
                required_visual_tool_name_set = set(
                    required_visual_tool_names(visual_decision)
                )
                visual_only_tools = [
                    tool
                    for tool in tools
                    if _tool_name(tool) in required_visual_tool_name_set
                ]
                bind_source = (
                    llm_base
                    or (llm_auto if hasattr(llm_auto, "bind_tools") else None)
                    or (llm_with_tools if hasattr(llm_with_tools, "bind_tools") else None)
                )
                if bind_source is not None and visual_only_tools:
                    followup_tools = visual_only_tools
                    followup_tool_choice = _resolve_tool_choice(
                        True,
                        visual_only_tools,
                        resolved_provider or provider,
                    )
                    if followup_tool_choice:
                        followup_llm = bind_source.bind_tools(
                            visual_only_tools,
                            tool_choice=followup_tool_choice,
                        )
                    else:
                        followup_llm = bind_source.bind_tools(visual_only_tools)
            candidate_provider, _candidate_model = remember_execution_target(
                followup_llm,
                fallback_source=bind_source or llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response = await graph_ainvoke_with_fallback(
                followup_llm,
                messages,
                tools=followup_tools,
                tool_choice=followup_tool_choice,
                tier=runtime_tier_for(followup_llm, bind_source or llm_base),
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                push_event=push_event,
                timeout_profile=followup_timeout_profile,
                state=state,
                allowed_fallback_providers=allowed_fallback_providers,
            )
        finally:
            post_tool_heartbeat.cancel()
            try:
                await post_tool_heartbeat
            except asyncio.CancelledError:
                pass
            except Exception as heartbeat_error:
                logger.debug(
                    "[DIRECT] Post-tool heartbeat shutdown skipped: %s",
                    heartbeat_error,
                )
    if streamed_direct_answer and not tool_call_events:
        state["_answer_streamed_via_bus"] = True
        return llm_response, messages, tool_call_events

    remaining_tool_calls = bool(
        tools and hasattr(llm_response, "tool_calls") and llm_response.tool_calls
    )
    visible_response_text = _extract_direct_visible_text(
        getattr(llm_response, "content", "")
    )
    if (
        tool_call_events
        and not visible_response_text
        and _should_use_search_template_for_empty_response(
            query=query,
            state=state,
            tool_call_events=tool_call_events,
        )
    ):
        template_response = ""
        try:
            template_response = build_search_template_fallback(
                query=query,
                tool_call_events=tool_call_events,
            )
        except Exception as template_error:  # noqa: BLE001
            logger.warning(
                "[DIRECT] Web-search empty-response template synthesis failed: %s",
                template_error,
            )
        if template_response:
            logger.info(
                "[DIRECT] Web-search returning source-backed template "
                "without slow synthesis LLM (events=%d, len=%d)",
                len(tool_call_events),
                len(template_response),
            )
            llm_response = _build_assistant_message(
                template_response,
                native_tool_messages=native_tool_messages,
            )
            visible_response_text = template_response
            remaining_tool_calls = False

    if tool_call_events and (remaining_tool_calls or not visible_response_text):
        logger.warning(
            "[DIRECT] Tool loop ended without final prose "
            "(remaining_tool_calls=%s, visible_len=%d) -> forcing no-tool synthesis",
            remaining_tool_calls,
            len(visible_response_text),
        )
        synthesis_tool_names = [
            str(event.get("name", ""))
            for event in tool_call_events
            if event.get("type") == "call"
        ]
        synthesis_messages = list(messages)
        synthesis_messages.append(
            _build_user_instruction_message(
                _build_direct_final_synthesis_instruction(
                    query,
                    state,
                    synthesis_tool_names,
                ),
                native_tool_messages=native_tool_messages,
            )
        )
        synthesis_llm = llm_base or llm_auto or llm_with_tools
        synthesis_heartbeat = asyncio.create_task(
            graph_stream_direct_wait_heartbeats(
                push_event,
                query=query,
                phase="synthesize",
                cue=synthesis_cue if "synthesis_cue" in locals() else "synthesis",
                tool_names=synthesis_tool_names if "synthesis_tool_names" in locals() else None,
            )
        )
        try:
            candidate_provider, _candidate_model = remember_execution_target(
                synthesis_llm,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            # Synthesis after a successful tool round needs a longer timeout
            # than a tool-bound planning call: context is larger (full search
            # results + fetched URL bodies) and the model must produce prose
            # that obeys the SKILL Step 4 structure. The "moderate" profile
            # gives DeepSeek-light enough headroom on long prompts without
            # needing a full deep-tier model.
            llm_response = await graph_ainvoke_with_fallback(
                synthesis_llm,
                synthesis_messages,
                tier=runtime_tier_for(synthesis_llm, llm_base),
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                push_event=push_event,
                timeout_profile="moderate",
                state=state,
                allowed_fallback_providers=allowed_fallback_providers,
            )
            messages = synthesis_messages
        finally:
            synthesis_heartbeat.cancel()
            try:
                await synthesis_heartbeat
            except asyncio.CancelledError:
                pass
            except Exception as heartbeat_error:
                logger.debug(
                    "[DIRECT] Final synthesis heartbeat shutdown skipped: %s",
                    heartbeat_error,
                )

    llm_response = _inject_widget_blocks_from_tool_results(
        llm_response,
        tool_call_events,
        query=query,
        structured_visuals_enabled=getattr(settings, "enable_structured_visuals", False),
    )

    return llm_response, messages, tool_call_events
