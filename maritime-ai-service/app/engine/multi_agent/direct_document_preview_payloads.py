"""Uploaded-document preview and course-plan payload builders."""

from __future__ import annotations

import re
from typing import Any

from app.engine.multi_agent.document_preview_contract import (
    DOC_COURSE_HOST_ACTION_TOOL as _DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL as _DOC_PREVIEW_HOST_ACTION_TOOL,
    find_document_host_action_tool,
    looks_uploaded_document_course_request as _looks_uploaded_doc_course_request,
    normalize_document_contract_text as _normalize_doc_preview_text,
    uploaded_document_attachments_from_state as _uploaded_document_attachments_from_state,
)
from app.engine.multi_agent.direct_prompts import _tool_name
from app.engine.multi_agent.direct_document_source_refs import (
    _dedupe_doc_refs as _dedupe_doc_refs,
    _doc_source_reference,
    _match_doc_refs,
    _top_course_source_references,
)
from app.engine.multi_agent.direct_document_course_domain_plans import (
    _build_lms_manual_course_plan,
    _build_maritime_training_lms_course_plan,
    _build_maritime_vessel_management_course_plan,
    _lms_manual_lesson,
)
from app.engine.multi_agent.state import AgentState

_DOC_PREVIEW_LOW_VALUE_LABELS = {
    "buoc",
    "checkpoint",
    "cong trinh",
    "de tai",
    "ket qua",
    "ket qua dung",
    "ket qua mong doi",
    "muc tieu",
    "muc tieu hoc tap",
    "muc tieu sau khi doc",
    "noi dung",
    "thao tac",
    "vai tro",
}


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
    normalized = _normalize_doc_preview_text(line).strip(" #-:\t\r\n|")
    if normalized in _DOC_PREVIEW_LOW_VALUE_LABELS:
        return True
    parts = [
        part.strip(" #-:\t\r\n|")
        for part in re.split(r"\s+-\s+|\s*[|:]\s*", normalized)
        if part.strip(" #-:\t\r\n|")
    ]
    if parts and all(part in _DOC_PREVIEW_LOW_VALUE_LABELS for part in parts):
        return True
    if normalized.startswith(("buoc - thao tac", "hinh ", "vai tro -")):
        return True
    return bool(re.match(r"^\d+(?:\.\d+)*[.)]\s+\S+", line))


def _find_doc_preview_host_action_tool(tools: list[Any]) -> Any | None:
    return find_document_host_action_tool(
        tools,
        _DOC_PREVIEW_HOST_ACTION_TOOL,
        tool_name_resolver=_tool_name,
    )


def _find_doc_course_host_action_tool(tools: list[Any]) -> Any | None:
    return find_document_host_action_tool(
        tools,
        _DOC_COURSE_HOST_ACTION_TOOL,
        tool_name_resolver=_tool_name,
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
            selected = _select_doc_preview_title_line(text)
            return selected or line[:140]
    return "Tài liệu đã tải lên"


def _select_doc_preview_title_line(text: str) -> str:
    fallback = ""
    best_line = ""
    best_score = -10_000
    for raw_line in str(text or "").replace("\\_", "_").splitlines()[:120]:
        line = _clean_doc_preview_line(raw_line)
        if (
            not line
            or _is_doc_preview_scaffold_line(line)
            or _is_doc_preview_low_value_line(line)
            or _is_low_value_doc_preview_title(line)
            or _is_doc_preview_cover_metadata_line(line)
        ):
            continue
        if not fallback:
            fallback = line[:140]
        score = _score_doc_preview_title_candidate(line)
        if score > best_score:
            best_score = score
            best_line = line[:140]
        if best_score >= 150:
            break
    if best_line and best_score >= 120:
        return best_line
    return fallback


def _score_doc_preview_title_candidate(value: str) -> int:
    cleaned = _clean_doc_preview_line(value)
    normalized = _normalize_doc_preview_text(cleaned)
    if not cleaned or _is_doc_preview_cover_metadata_line(cleaned):
        return -10_000
    score = min(len(cleaned), 160) // 4
    word_count = len(re.findall(r"\w+", cleaned, flags=re.IGNORECASE))
    if word_count >= 6:
        score += 25
    if word_count >= 12:
        score += 25
    for marker in (
        "nghien cuu",
        "xay dung he thong",
        "thiet ke he thong",
        "quan ly van hanh",
        "ho so tau",
        "tau thuy",
        "van tai bien",
        "nghiep vu chuyen mon",
        "thuy thu",
    ):
        if marker in normalized:
            score += 40
    if normalized in {"loi cam on", "muc luc", "danh muc bang", "danh muc hinh"}:
        score -= 100
    return score


def _is_doc_preview_cover_metadata_line(value: str) -> bool:
    normalized = _normalize_doc_preview_text(value).strip(" #-:\t\r\n|")
    if not normalized:
        return True
    if normalized in {
        "bo xay dung",
        "bo giao duc va dao tao",
        "bo xay dung - bo giao duc va dao tao",
        "truong dai hoc hang hai viet nam",
        "truong dai hoc",
        "thuc tap tot nghiep",
        "do an tot nghiep",
        "khoa luan tot nghiep",
        "bao cao thuc tap",
        "hai phong - 2026",
        "hai phong 2026",
    }:
        return True
    if any(
        marker in normalized
        for marker in (
            "giang vien huong dan",
            "sinh vien thuc hien",
            "nguoi huong dan",
            "giao vien huong dan",
        )
    ):
        return True
    if re.search(r"\b\d{5,}\b", normalized) and re.search(r"\b[a-z]{2,}\d{2}", normalized):
        return True
    return bool(re.fullmatch(r"(?:hai phong|ha noi|tp\.? ho chi minh)\s*[-–]?\s*\d{4}", normalized))


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
    direct_match = re.search(r"\bWIII_[0-9A-Za-z][0-9A-Za-z_-]{2,140}\b", cleaned)
    if direct_match:
        return direct_match.group(0)

    label_match = re.search(
        r"(?:marker|test marker|exact marker|ma kiem thu|chuoi kiem thu)"
        r"[^0-9A-Za-z_]{0,60}"
        r"([0-9A-Za-z][0-9A-Za-z_.:-]{2,140})",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not label_match:
        return ""
    marker = label_match.group(1).strip("`'\".,;:()[]{}<>")
    if len(marker) < 3 or re.fullmatch(r"(?:kiem|thu|chinh|xac|exact|marker|test)", marker, flags=re.IGNORECASE):
        return ""
    return marker


def _strip_doc_preview_goal_label(line: str) -> str:
    cleaned = str(line or "").strip()
    if _is_doc_preview_low_value_line(cleaned):
        return ""
    if _normalize_doc_preview_text(cleaned).startswith("muc tieu"):
        cleaned = re.sub(
            r"^(?:Mục tiêu(?: học tập)?|Muc tieu(?: hoc tap)?)\s*[-:–]?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = cleaned.strip()
    if _is_doc_preview_low_value_line(cleaned):
        return ""
    return cleaned


def _is_doc_preview_ordered_action_line(value: str) -> bool:
    normalized = _normalize_doc_preview_text(value).strip()
    return bool(re.match(r"^\d+\s*[-.)]\s+\S+", normalized))


def _strip_doc_preview_ordered_action_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    return re.sub(r"^\s*\d+\s*[-.)]\s*", "", cleaned).strip()


def _is_doc_preview_admonition_line(value: str) -> bool:
    normalized = _normalize_doc_preview_text(value).strip(" -:\t\r\n")
    return normalized.startswith(
        (
            "can luu y",
            "khong duoc",
            "khong nen",
            "luu y",
            "tranh ",
        )
    )


def _repair_doc_preview_common_truncations(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    return re.sub(r"(?:xuất|xuat)\s+b[ảa]\s*$", "xuất bản", cleaned, flags=re.IGNORECASE)


def _clip_doc_preview_line(value: str, *, limit: int = 260) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) <= limit:
        return _repair_doc_preview_common_truncations(cleaned)
    clipped = cleaned[:limit].rstrip()
    boundary = max(clipped.rfind(" "), clipped.rfind("\t"))
    if boundary >= int(limit * 0.72):
        clipped = clipped[:boundary].rstrip()
    return _repair_doc_preview_common_truncations(clipped.rstrip(" ,;:-"))


def _shape_doc_preview_learning_goal(value: str, *, is_lms_manual: bool) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or not is_lms_manual:
        return _repair_doc_preview_common_truncations(cleaned)
    normalized = _normalize_doc_preview_text(cleaned)
    if normalized.startswith("phan nay tap trung vao"):
        detail = re.sub(
            r"^(?:Phần|Phan)\s+(?:này|nay)\s+(?:tập trung|tap trung)\s+(?:vào|vao)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" .")
        if detail:
            repaired = _repair_doc_preview_common_truncations(detail)
            return f"Giáo viên thực hiện được {repaired} trong LMS."
    return _repair_doc_preview_common_truncations(cleaned)



def _supplement_doc_preview_learning_goals(
    goals: list[str],
    *,
    is_lms_manual: bool,
) -> list[str]:
    supplements = (
        [
            "Giáo viên kiểm tra phần so sánh thay đổi và nguồn trích dẫn trước khi áp dụng thay đổi vào LMS.",
            "Giáo viên tạo hoặc cập nhật bài học ở trạng thái nháp, không xuất bản khi chưa rà soát nội dung.",
            "Giáo viên xác nhận nội dung, tài liệu, video hoặc câu hỏi liên quan trước khi bấm Áp dụng.",
        ]
        if is_lms_manual
        else [
            "Người học xác định ý chính, bằng chứng nguồn và tình huống áp dụng từ tài liệu.",
            "Người học chuyển nội dung nguồn thành checklist thực hành có thể kiểm chứng.",
            "Người học trả lời câu hỏi nhanh dựa trên nguồn trích dẫn thay vì ghi nhớ rời rạc.",
        ]
    )
    normalized_seen = {_normalize_doc_preview_text(goal) for goal in goals}
    completed = list(goals)
    for supplement in supplements:
        if len(completed) >= 3:
            break
        normalized = _normalize_doc_preview_text(supplement)
        if normalized in normalized_seen:
            continue
        completed.append(supplement)
        normalized_seen.add(normalized)
    return completed


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
            selected.append(_clip_doc_preview_line(line))
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


def _polish_doc_preview_vietnamese_title(value: str) -> str:
    title = _clean_doc_preview_line(value)
    if not title:
        return ""
    replacements = (
        (r"\bHuong\s+dan\s+su\s+dung\b", "Hướng dẫn sử dụng"),
        (r"\bcho\s+giao\s+vien\b", "cho giáo viên"),
        (r"\bgiao\s+vien\b", "giáo viên"),
        (r"\bgiang\s+vien\b", "giảng viên"),
        (r"\bhoc\s+vien\b", "học viên"),
        (r"\bquan\s+ly\b", "quản lý"),
        (r"\bkhoa\s+hoc\b", "khóa học"),
        (r"\bbai\s+hoc\b", "bài học"),
    )
    polished = title
    for pattern, replacement in replacements:
        polished = re.sub(pattern, replacement, polished, flags=re.IGNORECASE)
    return polished


def _is_low_value_doc_preview_title(value: str) -> bool:
    normalized = _normalize_doc_preview_text(value)
    if not normalized:
        return True
    if re.fullmatch(r"tmp[a-z0-9_-]{4,}", normalized):
        return True
    return normalized in {
        "cong trinh",
        "de tai",
        "parser provenance",
        "document context",
        "uploaded document context",
        "uploaded source",
        "tai lieu da tai len",
    } or normalized.startswith("parser ")


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
            _extend_doc_context_id_candidates(
                candidates,
                ctx.get(key),
                snake_key="lesson_id",
                camel_key="lessonId",
            )
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
            _extend_doc_context_id_candidates(
                candidates,
                ctx.get(key),
                snake_key="course_id",
                camel_key="courseId",
            )
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return ""


def _extend_doc_context_id_candidates(
    candidates: list[Any],
    value: Any,
    *,
    snake_key: str,
    camel_key: str,
    depth: int = 0,
) -> None:
    if not isinstance(value, dict) or depth > 3:
        return
    candidates.extend([value.get(snake_key), value.get(camel_key)])
    for nested_key in (
        "metadata",
        "entity_refs",
        "page",
        "page_context",
        "selection",
        "editable_scope",
    ):
        nested = value.get(nested_key)
        if isinstance(nested, dict):
            _extend_doc_context_id_candidates(
                candidates,
                nested,
                snake_key=snake_key,
                camel_key=camel_key,
                depth=depth + 1,
            )


def _extract_doc_course_title_from_query(query: str) -> str:
    match = re.search(
        r"(?:course title|ten khoa hoc|tên khóa học|title)\s*(?:la|là|is|:)\s*[\"“”']([^\"“”']{3,140})[\"“”']",
        str(query or ""),
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_doc_preview_line(match.group(1))
    return ""




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
        if not source_match:
            source_match = re.search(
                r"Nguồn section:\s*(.+?)\s*\(trang\s*(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?\)",
                stripped,
                flags=re.IGNORECASE,
            )
        if not source_match:
            source_match = re.search(
                r"Ngu.n section:\s*(.+?)\s*\(trang\s*(\d{1,4})(?:\s*[-–]\s*(\d{1,4}))?\)",
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
        return refs[:96]

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




def _looks_holilihu_lms_manual_document(
    *,
    title_source: str,
    markdown: str,
    query: str = "",
) -> bool:
    manual_markers = (
        "huong dan su dung",
        "huong dan cho hoc vien",
        "huong dan cho giang vien",
        "huong dan cho quan ly",
        "tao khoa hoc",
        "them video",
        "video tuong tac",
        "dang nhap",
        "xuat ban",
        "quiz",
    )
    guide_markers = (
        "huong dan",
        "huong dan su dung",
        "huong dan chi tiet",
        "manual",
        "user guide",
    )
    title_text = _normalize_doc_preview_text(title_source)
    query_text = _normalize_doc_preview_text(query)
    title_has_guide_frame = any(marker in title_text for marker in guide_markers)
    title_has_holilihu = "holilihu" in title_text
    query_explicitly_requests_holilihu_manual = (
        "holilihu" in query_text and any(marker in query_text for marker in guide_markers)
    )
    research_title_markers = (
        "nghien cuu",
        "cong trinh",
        "de tai",
        "bao cao",
        "luan van",
        "khoa luan",
        "xay dung he thong",
        "thiet ke he thong",
    )
    maritime_training_title_markers = (
        "thuy thu",
        "hang hai",
        "nghiep vu chuyen mon",
        "van tai bien",
        "tau thuy",
    )
    title_is_research_lms = bool(
        title_text
        and re.search(r"(^|[^a-z0-9])lms([^a-z0-9]|$)", title_text)
        and any(marker in title_text for marker in research_title_markers)
    )
    title_is_maritime_training_research = bool(
        title_text
        and any(marker in title_text for marker in research_title_markers)
        and any(marker in title_text for marker in maritime_training_title_markers)
    )
    if (
        (title_is_research_lms or title_is_maritime_training_research)
        and not title_has_holilihu
        and not title_has_guide_frame
        and not query_explicitly_requests_holilihu_manual
    ):
        return False

    document_text = _normalize_doc_preview_text(
        f"{title_source}\n{str(markdown or '')[:8000]}"
    )
    if "holilihu" in document_text:
        return any(marker in document_text for marker in guide_markers + manual_markers)
    has_manual_frame = any(marker in document_text for marker in guide_markers)
    if re.search(r"(^|[^a-z0-9])lms([^a-z0-9]|$)", document_text):
        return has_manual_frame and any(marker in document_text for marker in manual_markers)
    query_says_lms = "holilihu" in query_text or re.search(r"(^|[^a-z0-9])lms([^a-z0-9]|$)", query_text)
    if query_says_lms and has_manual_frame and any(marker in document_text for marker in manual_markers):
        return True
    return False


def _looks_maritime_vessel_management_document(*, title_source: str, markdown: str) -> bool:
    document_text = _normalize_doc_preview_text(
        f"{title_source}\n{str(markdown or '')[:12000]}"
    )
    markers = (
        "tau thuy",
        "ho so tau",
        "van tai bien",
        "quan ly van hanh",
        "doanh nghiep van tai",
        "he thong tau",
        "he thong bo",
    )
    return sum(1 for marker in markers if marker in document_text) >= 2


def _looks_maritime_training_lms_document(*, title_source: str, markdown: str) -> bool:
    document_text = _normalize_doc_preview_text(
        f"{title_source}\n{str(markdown or '')[:12000]}"
    )
    has_lms_frame = bool(
        re.search(r"(^|[^a-z0-9])lms([^a-z0-9]|$)", document_text)
        or any(
            marker in document_text
            for marker in (
                "learning management",
                "quan ly hoc tap",
                "e-learning",
                "elearning",
                "dao tao truc tuyen",
            )
        )
    )
    training_markers = (
        "thuy thu",
        "thuyen vien",
        "hang hai",
        "nghiep vu chuyen mon",
        "dao tao hang hai",
        "boi duong nghiep vu",
        "stcw",
    )
    research_markers = (
        "nghien cuu",
        "xay dung he thong",
        "thiet ke he thong",
        "cong trinh",
        "de tai",
        "bao cao",
        "luan van",
        "khoa luan",
    )
    training_score = sum(1 for marker in training_markers if marker in document_text)
    research_score = sum(1 for marker in research_markers if marker in document_text)
    return has_lms_frame and training_score >= 1 and (
        research_score >= 1 or "dao tao" in document_text or "boi duong" in document_text
    )






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


def _section_candidate_markers(title: str) -> tuple[str, ...]:
    normalized = _normalize_doc_preview_text(title)
    compact = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", normalized).strip()
    markers = [marker for marker in (normalized, compact) if marker]
    return tuple(dict.fromkeys(markers))


def _copy_doc_refs_with_indices(
    refs: list[dict[str, Any]],
    *,
    chapter_index: int | None = None,
    lesson_index: int | None = None,
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for ref in refs[:3]:
        next_ref = dict(ref)
        if chapter_index is not None:
            next_ref["chapter_index"] = chapter_index
        if lesson_index is not None:
            next_ref["lesson_index"] = lesson_index
        copied.append(next_ref)
    return copied


def _document_course_section_candidates(
    *,
    markdown: str,
    refs: list[dict[str, Any]],
    fallback_title: str,
) -> list[dict[str, Any]]:
    """Build a stable document map from source references plus headings.

    The previous generic builder used the first six headings, which is brittle
    for long manuals/research reports. This map keeps the source order and then
    clusters the whole document into course chapters.
    """

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(title: str, source_refs: list[dict[str, Any]]) -> None:
        clean_title = _clean_doc_preview_line(title)
        if not clean_title or _is_doc_preview_scaffold_line(clean_title):
            return
        normalized = _normalize_doc_preview_text(clean_title)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(
            {
                "title": clean_title[:140],
                "markers": _section_candidate_markers(clean_title),
                "source_refs": source_refs,
                "source_index": len(candidates) + 1,
            }
        )

    for ref in refs:
        title = str(ref.get("title") or ref.get("excerpt") or "").strip()
        if not title:
            continue
        add_candidate(title, [ref])
        if len(candidates) >= 96:
            break

    for heading in _extract_doc_headings(markdown):
        if len(candidates) >= 96:
            break
        if refs:
            heading_refs = _match_doc_refs(
                refs,
                _section_candidate_markers(heading),
                fallback_title=fallback_title,
            )
        else:
            heading_refs = [
                _doc_source_reference(
                    title=heading,
                    excerpt=heading,
                )
            ]
        add_candidate(heading, heading_refs)

    if candidates:
        return candidates

    fallback_refs = refs[:1] or [_doc_source_reference(title=fallback_title)]
    return [
        {
            "title": fallback_title,
            "markers": _section_candidate_markers(fallback_title),
            "source_refs": fallback_refs,
            "source_index": 1,
        }
    ]


def _cluster_document_course_sections(
    candidates: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    if not candidates:
        return []
    section_count = len(candidates)
    if section_count >= 18:
        chapter_count = 6
    elif section_count >= 12:
        chapter_count = 5
    elif section_count >= 6:
        chapter_count = 4
    else:
        chapter_count = max(1, section_count)

    clusters: list[list[dict[str, Any]]] = []
    base_size = section_count // chapter_count
    remainder = section_count % chapter_count
    cursor = 0
    for index in range(chapter_count):
        size = base_size + (1 if index < remainder else 0)
        cluster = candidates[cursor : cursor + size]
        if cluster:
            clusters.append(cluster)
        cursor += size
    return clusters


def _select_lesson_section_candidates(
    cluster: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(cluster) <= 3:
        return cluster
    indexes = [0, len(cluster) // 2, len(cluster) - 1]
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index in indexes:
        if index in seen:
            continue
        seen.add(index)
        selected.append(cluster[index])
    return selected


def _cluster_title(cluster: list[dict[str, Any]], *, chapter_index: int) -> str:
    primary = str((cluster[0] if cluster else {}).get("title") or "").strip()
    if not primary:
        return f"Chương {chapter_index}: Nền tảng tài liệu"
    normalized = _normalize_doc_preview_text(primary)
    if normalized.startswith(("tong quan", "gioi thieu", "mo dau")):
        return f"Bối cảnh và mục tiêu: {primary}"
    if any(marker in normalized for marker in ("ket luan", "tong ket", "danh gia")):
        return f"Tổng kết và đánh giá: {primary}"
    return f"Trục nội dung {chapter_index}: {primary}"


def _lesson_refs_for_candidate(
    candidate: dict[str, Any],
    refs: list[dict[str, Any]],
    *,
    fallback_title: str,
    chapter_index: int,
    lesson_index: int,
) -> list[dict[str, Any]]:
    direct_refs = candidate.get("source_refs")
    if isinstance(direct_refs, list) and direct_refs:
        return _copy_doc_refs_with_indices(
            [ref for ref in direct_refs if isinstance(ref, dict)],
            chapter_index=chapter_index,
            lesson_index=lesson_index,
        )
    return _match_doc_refs(
        refs,
        tuple(candidate.get("markers") or (candidate.get("title") or "",)),
        fallback_title=fallback_title,
        chapter_index=chapter_index,
        lesson_index=lesson_index,
    )


def _classify_uploaded_document_course_domain(
    *,
    query: str,
    title_source: str,
    markdown: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    lms_manual = _looks_holilihu_lms_manual_document(
        title_source=title_source,
        markdown=markdown,
        query=query,
    )
    maritime_training_lms = _looks_maritime_training_lms_document(
        title_source=title_source,
        markdown=markdown,
    )
    maritime_vessel = _looks_maritime_vessel_management_document(
        title_source=title_source,
        markdown=markdown,
    )
    if lms_manual:
        domain_id = "holilihu_lms_manual"
        confidence = 0.86
    elif maritime_training_lms:
        domain_id = "maritime_training_lms"
        confidence = 0.84
    elif maritime_vessel:
        domain_id = "maritime_vessel_management"
        confidence = 0.82
    else:
        domain_id = "generic_document_course"
        confidence = 0.64

    headings = _extract_doc_headings(markdown)
    return {
        "domain_id": domain_id,
        "confidence": confidence,
        "evidence": {
            "heading_count": len(headings),
            "source_reference_count": len(refs),
            "document_chars": len(markdown or ""),
            "maritime_training_lms": maritime_training_lms,
            "query_lms_mention": bool(
                re.search(
                    r"(^|[^a-z0-9])(lms|holilihu)([^a-z0-9]|$)",
                    _normalize_doc_preview_text(query),
                )
            ),
        },
    }


def _build_document_course_quality_report(
    *,
    course_plan: dict[str, Any],
    classification: dict[str, Any],
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapters = course_plan.get("chapters") if isinstance(course_plan, dict) else []
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    lesson_count = 0
    lessons_missing_refs = 0
    lessons_missing_activity = 0
    iterable_chapters = chapters if isinstance(chapters, list) else []
    for chapter in iterable_chapters:
        lessons = chapter.get("lessons") if isinstance(chapter, dict) else []
        if not isinstance(lessons, list):
            continue
        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue
            lesson_count += 1
            if not lesson.get("source_references"):
                lessons_missing_refs += 1
            if not str(lesson.get("activity") or "").strip():
                lessons_missing_activity += 1

    warnings: list[str] = []
    if chapter_count < 3:
        warnings.append("course_has_too_few_chapters")
    if lesson_count < 6:
        warnings.append("course_has_too_few_lessons")
    if lessons_missing_refs:
        warnings.append("lesson_missing_source_references")
    if lessons_missing_activity:
        warnings.append("lesson_missing_activity")
    if not refs:
        warnings.append("document_has_no_extractable_source_references")

    return {
        "status": "pass" if not warnings else "warn",
        "domain_id": classification.get("domain_id"),
        "domain_confidence": classification.get("confidence"),
        "chapter_count": chapter_count,
        "lesson_count": lesson_count,
        "source_reference_count": len(refs),
        "lessons_missing_source_references": lessons_missing_refs,
        "lessons_missing_activity": lessons_missing_activity,
        "warnings": warnings,
    }


def _build_generic_document_course_plan(
    *,
    title_source: str,
    markdown: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = _document_course_section_candidates(
        markdown=markdown,
        refs=refs,
        fallback_title=title_source,
    )
    clusters = _cluster_document_course_sections(candidates)
    chapters: list[dict[str, Any]] = []
    for chapter_index, cluster in enumerate(clusters, start=1):
        chapter_refs = _copy_doc_refs_with_indices(
            [
                ref
                for candidate in cluster
                for ref in candidate.get("source_refs", [])
                if isinstance(ref, dict)
            ],
            chapter_index=chapter_index,
        )
        if not chapter_refs:
            chapter_refs = _match_doc_refs(
                refs,
                tuple(
                    marker
                    for candidate in cluster
                    for marker in candidate.get("markers", ())
                ),
                fallback_title=title_source,
                chapter_index=chapter_index,
            )
        lesson_candidates = _select_lesson_section_candidates(cluster)
        lessons: list[dict[str, Any]] = []
        for lesson_index, candidate in enumerate(lesson_candidates, start=1):
            section_title = str(candidate.get("title") or title_source).strip()
            lesson_refs = _lesson_refs_for_candidate(
                candidate,
                refs,
                fallback_title=title_source,
                chapter_index=chapter_index,
                lesson_index=lesson_index,
            )
            if lesson_index == 1:
                title = f"Đọc hiểu trọng tâm: {section_title}"
                summary = (
                    f"Xác định vấn đề, mục tiêu và khái niệm cốt lõi trong phần {section_title}."
                )
                activity = (
                    "Người học ghi lại 3 ý chính, 1 giả định cần kiểm chứng và nguồn trích dẫn tương ứng."
                )
                quick_check = "Điểm nào trong nguồn là căn cứ quan trọng nhất cho phần này?"
                duration = 18
            elif lesson_index == len(lesson_candidates):
                title = f"Vận dụng và kiểm chứng: {section_title}"
                summary = (
                    f"Chuyển nội dung {section_title} thành bài tập, checklist hoặc quyết định có thể đánh giá."
                )
                activity = (
                    "Làm một tình huống ngắn, nộp câu trả lời kèm nguồn trích dẫn chứng minh lựa chọn."
                )
                quick_check = "Nếu áp dụng sai phần này, rủi ro hoặc hệ quả dễ thấy nhất là gì?"
                duration = 24
            else:
                title = f"Thiết kế hoạt động học từ: {section_title}"
                summary = (
                    f"Biến phần {section_title} thành hoạt động học giúp người học tự thao tác thay vì chỉ đọc."
                )
                activity = (
                    "Theo nhóm, dựng một sơ đồ/quy trình nhỏ rồi đối chiếu lại với nguồn tài liệu."
                )
                quick_check = "Hoạt động này đo được năng lực nào, và nguồn trích dẫn nào hỗ trợ?"
                duration = 22
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=lesson_refs,
                    duration_minutes=duration,
                )
            )
        if len(lessons) == 1:
            only_candidate = lesson_candidates[0]
            section_title = str(only_candidate.get("title") or title_source).strip()
            lessons.append(
                _lms_manual_lesson(
                    title=f"Thực hành tổng hợp: {section_title}",
                    summary=(
                        f"Áp dụng phần {section_title} vào một tình huống hoặc sản phẩm học tập cụ thể."
                    ),
                    activity="Hoàn thiện một sản phẩm nhỏ và ghi rõ nguồn đã dùng để kiểm chứng.",
                    quick_check="Sản phẩm này có thể được giáo viên đánh giá bằng tiêu chí nào?",
                    refs=_lesson_refs_for_candidate(
                        only_candidate,
                        refs,
                        fallback_title=title_source,
                        chapter_index=chapter_index,
                        lesson_index=2,
                    ),
                    duration_minutes=24,
                )
            )
        focus_titles = [str(item.get("title") or "").strip() for item in cluster[:4]]
        chapters.append(
            {
                "title": _cluster_title(cluster, chapter_index=chapter_index),
                "summary": (
                    "Chương này gom các phần liên tiếp của tài liệu thành một nhịp học có mục tiêu, "
                    "hoạt động và kiểm tra dựa trên nguồn."
                ),
                "learning_objectives": [
                    f"Giải thích được trọng tâm của {focus_titles[0] if focus_titles else title_source}.",
                    "Kết nối các mục liên quan trong tài liệu thành một luồng học có thứ tự.",
                    "Hoàn thành hoạt động/kiểm tra nhanh có nguồn trích dẫn để giáo viên xác minh.",
                ],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )
    lesson_count = sum(len(ch.get("lessons", [])) for ch in chapters)
    return {
        "title": f"Khóa học từ tài liệu: {title_source[:90]}",
        "description": (
            "Bản thiết kế khóa học được tạo từ tài liệu upload, có cấu trúc chương/bài, "
            "hoạt động học và nguồn trích dẫn để giáo viên kiểm chứng trước khi áp dụng."
        ),
        "audience": "Người học cần chuyển tài liệu nguồn thành năng lực thực hành.",
        "duration": f"{len(chapters)} chương, {lesson_count} bài.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có kiểm tra nhanh gắn với nguồn trích dẫn.",
            "Cuối khóa dùng một tình huống tổng hợp để xác nhận khả năng áp dụng.",
        ],
        "implementation_checklist": [
            "Giáo viên rà lại tiêu đề chương/bài trước khi apply.",
            "Không publish tự động; mọi nội dung sinh ra ở trạng thái draft.",
        ],
        "source_document_title": title_source,
        "document_map_summary": {
            "strategy": "cluster_full_document_map",
            "candidate_section_count": len(candidates),
            "chapter_count": len(chapters),
            "lesson_count": lesson_count,
        },
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
    attachment_title = str(first_attachment.get("title") or "").strip()
    if _is_low_value_doc_preview_title(attachment_title):
        attachment_title = ""
    title_source = (
        query_title
        or attachment_title
        or _first_nonempty_line(combined_markdown)
        or str(first_attachment.get("file_name") or "").strip()
        or "Tài liệu đã tải lên"
    )
    refs = _extract_doc_section_references(combined_markdown, title_source)
    classification = _classify_uploaded_document_course_domain(
        query=query,
        title_source=title_source,
        markdown=combined_markdown,
        refs=refs,
    )
    domain_id = str(classification.get("domain_id") or "generic_document_course")
    is_lms_manual = domain_id == "holilihu_lms_manual"
    if domain_id == "holilihu_lms_manual":
        course_plan = _build_lms_manual_course_plan(title_source=title_source, refs=refs)
    elif domain_id == "maritime_training_lms":
        course_plan = _build_maritime_training_lms_course_plan(
            title_source=title_source,
            refs=refs,
        )
    elif domain_id == "maritime_vessel_management":
        course_plan = _build_maritime_vessel_management_course_plan(
            title_source=title_source,
            refs=refs,
        )
    else:
        course_plan = _build_generic_document_course_plan(
            title_source=title_source,
            markdown=combined_markdown,
            refs=refs,
        )
    if isinstance(course_plan, dict):
        course_plan["document_domain"] = {
            "id": domain_id,
            "confidence": classification.get("confidence"),
            "evidence": classification.get("evidence"),
        }
        course_plan.setdefault(
            "document_map_summary",
            {
                "strategy": "domain_pack",
                "source_reference_count": len(refs),
            },
        )

    chapters = course_plan.get("chapters") if isinstance(course_plan, dict) else []
    lesson_count = sum(
        len(chapter.get("lessons") or [])
        for chapter in chapters
        if isinstance(chapter, dict)
    )
    quality_report = _build_document_course_quality_report(
        course_plan=course_plan if isinstance(course_plan, dict) else {},
        classification=classification,
        refs=refs,
    )
    if isinstance(course_plan, dict):
        course_plan["quality_report"] = quality_report
    params: dict[str, Any] = {
        "action": "preview_course_plan_from_document",
        "title": course_plan.get("title") or title_source,
        "summary": (
            f"Wiii đã dựng cây khóa học nháp gồm {len(chapters)} chương và "
            f"{lesson_count} bài từ tài liệu upload."
        ),
        "course_plan": course_plan,
        "changed_fields": ["course_structure"],
        "source_references": _top_course_source_references(
            refs,
            title_source=title_source,
            is_lms_manual=is_lms_manual,
        ),
        "document_domain": course_plan.get("document_domain"),
        "quality_report": quality_report,
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
    attachment_title = str(first_attachment.get("title") or "").strip()
    if _is_low_value_doc_preview_title(attachment_title):
        attachment_title = ""
    fallback_title = _first_nonempty_line(combined_markdown)
    if _is_low_value_doc_preview_title(fallback_title):
        fallback_title = ""
    title_source = (
        query_title
        or attachment_title
        or fallback_title
        or str(first_attachment.get("file_name") or "").strip()
        or "Tài liệu đã tải lên"
    )
    title_source = _polish_doc_preview_vietnamese_title(title_source)
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
    is_lms_manual = _looks_holilihu_lms_manual_document(
        title_source=title_source,
        markdown=combined_markdown,
        query=query,
    )
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
    clean_goals: list[str] = []
    for line in goals[:4]:
        cleaned = _strip_doc_preview_goal_label(line)
        if (
            not cleaned
            or _is_doc_preview_ordered_action_line(cleaned)
            or _is_doc_preview_admonition_line(cleaned)
        ):
            continue
        clean_goals.append(
            _shape_doc_preview_learning_goal(cleaned, is_lms_manual=is_lms_manual)
        )

    if not clean_goals:
        fallback_goal = _strip_doc_preview_goal_label(
            _first_nonempty_line(focused_markdown) or _first_nonempty_line(combined_markdown)
        )
        if (
            fallback_goal
            and not _is_doc_preview_ordered_action_line(fallback_goal)
            and not _is_doc_preview_admonition_line(fallback_goal)
            and _normalize_doc_preview_text(fallback_goal)
            != _normalize_doc_preview_text(title_source)
        ):
            clean_goals.append(
                _shape_doc_preview_learning_goal(fallback_goal, is_lms_manual=is_lms_manual)
            )
    if not clean_goals:
        clean_goals = [
            (
                "Giáo viên xác định đúng thao tác cần làm trong LMS và kiểm tra nguồn trước khi lưu."
                if is_lms_manual
                else "Người học xác định nội dung trọng tâm, bằng chứng nguồn và bước thực hành an toàn."
            )
        ]
    clean_goals = _supplement_doc_preview_learning_goals(
        clean_goals,
        is_lms_manual=is_lms_manual,
    )

    clean_checklist: list[str] = []
    for line in checklist[:5]:
        if not line or _is_doc_preview_low_value_line(line):
            continue
        cleaned = _strip_doc_preview_ordered_action_prefix(line)
        if cleaned and not _is_doc_preview_low_value_line(cleaned):
            clean_checklist.append(cleaned)
    content_lines = [
        f"# Bản nháp bài học từ tài liệu: {title_source}",
        "",
        *([f"Marker kiểm thử: {marker}", ""] if marker else []),
        "## Mục tiêu học tập",
        *[f"- {line}" for line in clean_goals],
        "",
        checklist_heading,
        *[f"- {line}" for line in clean_checklist],
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
