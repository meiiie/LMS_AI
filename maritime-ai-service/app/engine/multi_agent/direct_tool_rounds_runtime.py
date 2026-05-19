"""Tool-round runtime extracted from direct_execution."""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from typing import Any, Optional

from app.core.config import settings
from app.engine.multi_agent.document_preview_contract import (
    DOC_COURSE_HOST_ACTION_TOOL as _DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL as _DOC_PREVIEW_HOST_ACTION_TOOL,
    find_document_host_action_tool,
    looks_uploaded_document_course_request as _looks_uploaded_doc_course_request,
    normalize_document_contract_text as _normalize_doc_preview_text,
    uploaded_document_attachments_from_state as _uploaded_document_attachments_from_state,
)
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
from app.engine.multi_agent.direct_pointy_runtime import (
    _format_pointy_inventory,
    _validate_pointy_selector,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_call_text_parser import (
    extract_raw_tool_calls_from_text,
    tool_names_from_tools,
)
from app.engine.multi_agent.direct_web_search_policy import (
    FORCED_WEB_SEARCH_TOOL_NAMES as _FORCED_WEB_SEARCH_TOOL_NAMES,
    _clean_forced_web_search_query,
    _force_skills_for_turn,
    _has_search_tool_result,
    _is_search_tool_name,
    _prefer_official_query_for_known_docs,
    _should_return_search_template_after_tool_round,
    _should_use_search_template_for_empty_response,
)
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

    lesson_count = sum(len(chapter.get("lessons", [])) for chapter in chapters)

    return {
        "title": "Khai thác HoLiLiHu LMS từ tài liệu hướng dẫn",
        "description": (
            "Khóa học chuyển tài liệu hướng dẫn HoLiLiHu LMS thành lộ trình thực hành "
            "cho học viên, giảng viên và quản lý. Cấu trúc ưu tiên thao tác thật, "
            "kiểm tra chất lượng và nguồn trích dẫn để giáo viên xác minh trước khi áp dụng."
        ),
        "audience": "Giảng viên, trợ giảng, quản lý đào tạo và học viên cần sử dụng HoLiLiHu LMS.",
        "duration": f"{len(chapters)} chương, {lesson_count} bài, triển khai trong 3-5 buổi thực hành.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có câu hỏi kiểm tra nhanh gắn với thao tác thật.",
            "Cuối khóa yêu cầu người học hoàn thành một kịch bản: tạo/hoặc tham gia một khóa mẫu, học bài, kiểm tra tiến độ và xử lý một lỗi giả lập.",
            "Giảng viên dùng nguồn trích dẫn trong bản xem trước để đối chiếu từng chương trước khi áp dụng vào LMS.",
        ],
        "implementation_checklist": [
            "Xác minh tên khóa, mô tả, mục tiêu và đối tượng trước khi tạo dữ liệu LMS.",
            "Giữ mọi thay đổi ở trạng thái draft; không publish tự động.",
            "Sau khi apply, giáo viên rà lại từng chapter/lesson, thêm tài nguyên thật và gửi duyệt theo quy trình LMS.",
        ],
        "source_document_title": title_source,
    }


def _build_maritime_vessel_management_course_plan(
    *,
    title_source: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapter_specs = [
        {
            "title": "Bối cảnh số hóa vận hành và hồ sơ tàu thủy",
            "summary": "Đặt vấn đề quản lý vận hành và hồ sơ tàu trong doanh nghiệp vận tải biển.",
            "markers": ("gioi thieu", "bai toan", "qpec", "van tai bien", "ho so tau"),
            "objectives": [
                "Giải thích được vì sao doanh nghiệp vận tải biển cần số hóa hồ sơ tàu.",
                "Nhận diện các nhóm người dùng và điểm đau trong quản lý vận hành.",
                "Xác định phạm vi khóa học dựa trên tài liệu nghiên cứu.",
            ],
            "lessons": [
                (
                    "Bài toán quản lý vận hành trong doanh nghiệp vận tải biển",
                    "Tổng hợp bối cảnh, mục tiêu nghiên cứu và nhu cầu quản lý đội tàu.",
                    "Người học lập bản đồ vấn đề: ai dùng hệ thống, dùng để giải quyết việc gì.",
                    "Nếu không số hóa hồ sơ tàu, rủi ro vận hành lớn nhất là gì?",
                ),
                (
                    "Phạm vi hồ sơ tàu và luồng thông tin cần quản lý",
                    "Nhận diện hồ sơ, giấy tờ, chứng chỉ, nhật ký và dữ liệu vận hành liên quan đến tàu.",
                    "Tạo checklist 10 loại thông tin cần có trong hồ sơ tàu.",
                    "Một hồ sơ tàu đủ tốt cần trả lời được những câu hỏi nào?",
                ),
                (
                    "Các bên liên quan: doanh nghiệp, tàu, bờ và người khai thác",
                    "Phân tích vai trò của bộ phận bờ, tàu, quản lý và người vận hành hệ thống.",
                    "Vẽ sơ đồ stakeholder và quyền truy cập dữ liệu tối thiểu.",
                    "Vai trò nào cần được phân quyền chặt nhất, vì sao?",
                ),
            ],
        },
        {
            "title": "Khảo sát nghiệp vụ và yêu cầu hệ thống",
            "summary": "Chuyển khảo sát hiện trạng thành yêu cầu chức năng và phi chức năng.",
            "markers": ("khao sat", "yeu cau", "nghiep vu", "bieu mau", "co cau to chuc"),
            "objectives": [
                "Tách được yêu cầu nghiệp vụ khỏi mô tả hiện trạng.",
                "Mô hình hóa các quy trình chính trong vận hành và hồ sơ tàu.",
                "Viết được yêu cầu kiểm chứng được cho hệ thống.",
            ],
            "lessons": [
                (
                    "Đọc khảo sát hiện trạng như một bản yêu cầu nghiệp vụ",
                    "Rút ra quy trình, biểu mẫu và vấn đề đang tồn tại từ phần khảo sát.",
                    "Đánh dấu các câu trong tài liệu có thể chuyển thành requirement.",
                    "Một yêu cầu tốt khác một mô tả hiện trạng ở điểm nào?",
                ),
                (
                    "Quy trình nghiệp vụ quản lý vận hành và hồ sơ tàu",
                    "Mô tả các bước nghiệp vụ từ cập nhật hồ sơ đến theo dõi tình trạng vận hành.",
                    "Dựng flow ngắn cho một nghiệp vụ: thêm hồ sơ tàu hoặc cập nhật chứng chỉ.",
                    "Bước nào trong quy trình cần kiểm soát/audit rõ nhất?",
                ),
                (
                    "Từ biểu mẫu giấy sang dữ liệu có cấu trúc",
                    "Chuyển các giấy tờ và biểu mẫu thành trường dữ liệu, ràng buộc và trạng thái.",
                    "Chọn một biểu mẫu trong tài liệu và thiết kế schema tối thiểu.",
                    "Trường dữ liệu nào bắt buộc phải chuẩn hóa để tìm kiếm/báo cáo?",
                ),
            ],
        },
        {
            "title": "Phân tích chức năng và luồng dữ liệu",
            "summary": "Biến nghiệp vụ thành chức năng hệ thống, sơ đồ phân rã và luồng dữ liệu.",
            "markers": ("phan tich chuc nang", "so do phan ra", "luong du lieu", "muc ngu canh", "muc dinh"),
            "objectives": [
                "Đọc được sơ đồ phân rã chức năng và sơ đồ luồng dữ liệu.",
                "Liên kết chức năng với tác nhân và dữ liệu đầu vào/đầu ra.",
                "Phát hiện điểm thiếu trong luồng dữ liệu trước khi thiết kế giao diện.",
            ],
            "lessons": [
                (
                    "Sơ đồ phân rã chức năng cho hệ thống quản lý tàu",
                    "Tổ chức các chức năng lớn thành nhóm dễ triển khai và kiểm thử.",
                    "So sánh cây chức năng trong tài liệu với một backlog sản phẩm.",
                    "Chức năng nào là lõi vận hành, chức năng nào là hỗ trợ?",
                ),
                (
                    "Sơ đồ luồng dữ liệu mức ngữ cảnh và mức đỉnh",
                    "Giải thích dữ liệu đi qua hệ thống giữa người dùng, kho dữ liệu và báo cáo.",
                    "Vẽ lại một luồng dữ liệu bằng ngôn ngữ người dùng cuối.",
                    "Một luồng dữ liệu thiếu kho lưu trữ sẽ gây lỗi thiết kế nào?",
                ),
                (
                    "Kiểm tra nhất quán giữa nghiệp vụ và chức năng",
                    "Đối chiếu yêu cầu, chức năng, dữ liệu và báo cáo để tránh bỏ sót.",
                    "Tạo ma trận traceability từ yêu cầu sang chức năng.",
                    "Khi nào cần tách một chức năng thành hai module riêng?",
                ),
            ],
        },
        {
            "title": "Thiết kế dữ liệu và hồ sơ tàu",
            "summary": "Thiết kế thực thể, thuộc tính, quan hệ và bảng dữ liệu cho hồ sơ tàu.",
            "markers": ("thiet ke co so du lieu", "thuc the", "thuoc tinh", "lien ket thuc the", "bang du lieu"),
            "objectives": [
                "Nhận diện được các thực thể cốt lõi trong hồ sơ tàu.",
                "Thiết kế quan hệ dữ liệu phục vụ vận hành và truy xuất hồ sơ.",
                "Kiểm tra dữ liệu theo tiêu chí toàn vẹn, tìm kiếm và báo cáo.",
            ],
            "lessons": [
                (
                    "Thực thể cốt lõi: tàu, hồ sơ, chứng chỉ, thiết bị và chuyến biển",
                    "Tách các khái niệm nghiệp vụ thành thực thể dữ liệu có quan hệ rõ ràng.",
                    "Lập danh sách entity và thuộc tính bắt buộc cho một tàu.",
                    "Entity nào nên là trung tâm của mô hình dữ liệu, vì sao?",
                ),
                (
                    "Sơ đồ liên kết thực thể và ràng buộc dữ liệu",
                    "Đọc ERD và xác định quan hệ một-nhiều, nhiều-nhiều, bắt buộc/tùy chọn.",
                    "Kiểm tra một quan hệ dữ liệu bằng ví dụ tàu có nhiều chứng chỉ.",
                    "Ràng buộc nào giúp ngăn nhập hồ sơ tàu sai?",
                ),
                (
                    "Bảng dữ liệu và khả năng báo cáo vận hành",
                    "Đánh giá bảng dữ liệu theo nhu cầu lọc, cảnh báo, thống kê và truy xuất.",
                    "Thiết kế một truy vấn báo cáo hết hạn giấy tờ/chứng chỉ.",
                    "Nếu muốn cảnh báo tự động, bảng nào cần trường ngày hiệu lực?",
                ),
            ],
        },
        {
            "title": "Thiết kế hệ thống tàu, hệ thống bờ và trải nghiệm người dùng",
            "summary": "Kết nối dữ liệu, chức năng, phân quyền và giao diện theo bối cảnh tàu/bờ.",
            "markers": ("he thong tau", "he thong bo", "giao dien", "phan quyen", "quan tri"),
            "objectives": [
                "Phân biệt nhu cầu sử dụng trên tàu và trên bờ.",
                "Thiết kế giao diện theo vai trò và quy trình nghiệp vụ.",
                "Đặt nguyên tắc phân quyền, audit và an toàn dữ liệu.",
            ],
            "lessons": [
                (
                    "Luồng làm việc giữa hệ thống tàu và hệ thống bờ",
                    "Mô tả cách dữ liệu vận hành được nhập, đồng bộ, kiểm tra và khai thác.",
                    "Phác thảo một workflow từ tàu gửi cập nhật đến bờ xác nhận.",
                    "Điểm nào trong workflow cần xử lý offline hoặc chậm mạng?",
                ),
                (
                    "Giao diện theo vai trò và tác vụ",
                    "Biến chức năng thành màn hình, menu, form và trạng thái dễ dùng.",
                    "Thiết kế wireframe nhanh cho màn hình hồ sơ tàu.",
                    "Giao diện nào cần ưu tiên giảm lỗi nhập liệu?",
                ),
                (
                    "Phân quyền, audit và bảo vệ hồ sơ tàu",
                    "Xác định quyền xem/sửa/xóa/xuất báo cáo theo vai trò.",
                    "Tạo bảng phân quyền tối thiểu cho quản lý, nhân viên bờ và người trên tàu.",
                    "Vì sao xóa hồ sơ tàu cần cơ chế audit hoặc soft delete?",
                ),
            ],
        },
        {
            "title": "Triển khai, kiểm thử và đánh giá hiệu quả",
            "summary": "Đưa thiết kế vào môi trường doanh nghiệp, kiểm thử và đo giá trị vận hành.",
            "markers": ("trien khai", "kiem thu", "danh gia", "ket qua", "ket luan", "huong phat trien"),
            "objectives": [
                "Lập kế hoạch triển khai hệ thống theo giai đoạn an toàn.",
                "Thiết kế kiểm thử dựa trên nghiệp vụ và dữ liệu thật.",
                "Đánh giá hiệu quả bằng chỉ số vận hành và chất lượng hồ sơ.",
            ],
            "lessons": [
                (
                    "Kế hoạch triển khai trong doanh nghiệp vận tải biển",
                    "Chia triển khai thành các bước: chuẩn hóa dữ liệu, đào tạo, chạy thử và chuyển đổi.",
                    "Lập checklist trước khi đưa hệ thống vào dùng thật.",
                    "Rủi ro chuyển đổi dữ liệu nào cần kiểm soát đầu tiên?",
                ),
                (
                    "Kiểm thử nghiệp vụ và dữ liệu hồ sơ tàu",
                    "Xây dựng test case từ quy trình, biểu mẫu, phân quyền và báo cáo.",
                    "Viết 3 test case cho nhập hồ sơ tàu, cập nhật chứng chỉ và xuất báo cáo.",
                    "Test nào chứng minh hệ thống không chỉ đúng giao diện mà đúng nghiệp vụ?",
                ),
                (
                    "Đánh giá hiệu quả và hướng phát triển",
                    "Đo thời gian xử lý, mức đầy đủ hồ sơ, khả năng truy xuất và chất lượng báo cáo.",
                    "Đề xuất 3 KPI để so sánh trước/sau khi số hóa.",
                    "Một hệ thống quản lý hồ sơ tàu tốt nên cải tiến tiếp theo hướng nào?",
                ),
            ],
        },
    ]

    chapters: list[dict[str, Any]] = []
    for chapter_index, spec in enumerate(chapter_specs, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            tuple(spec["markers"]),
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = []
        for lesson_index, (title, summary, activity, quick_check) in enumerate(
            spec["lessons"],
            start=1,
        ):
            lesson_refs = _match_doc_refs(
                refs,
                tuple(spec["markers"]) + tuple(title.lower().split()[:4]),
                fallback_title=title_source,
                chapter_index=chapter_index,
                lesson_index=lesson_index,
            )
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=lesson_refs,
                    duration_minutes=22,
                )
            )
        chapters.append(
            {
                "title": spec["title"],
                "summary": spec["summary"],
                "learning_objectives": spec["objectives"],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )

    lesson_count = sum(len(chapter["lessons"]) for chapter in chapters)
    return {
        "title": "Quản lý vận hành và hồ sơ tàu thủy cho doanh nghiệp vận tải biển",
        "description": (
            "Khóa học chuyển tài liệu nghiên cứu về hệ thống quản lý vận hành và hồ sơ "
            "tàu thủy thành lộ trình học thực hành cho doanh nghiệp vận tải biển."
        ),
        "audience": (
            "Cán bộ quản lý vận hành, nhân sự phụ trách hồ sơ tàu, nhóm triển khai phần "
            "mềm và người học ngành vận tải biển."
        ),
        "duration": f"{len(chapters)} chương, {lesson_count} bài, triển khai trong 4-6 buổi workshop.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có bài kiểm tra nhanh dựa trên nguồn trích dẫn từ tài liệu nghiên cứu.",
            "Cuối khóa làm case study: thiết kế module hồ sơ tàu và quy trình vận hành cho một doanh nghiệp mẫu.",
            "Đánh giá bằng rubric gồm: đúng nghiệp vụ, đúng dữ liệu, an toàn phân quyền và khả năng triển khai.",
        ],
        "implementation_checklist": [
            "Giáo viên kiểm tra nguồn trích dẫn trước khi áp dụng vào LMS.",
            "Các chương/bài được tạo ở trạng thái draft; không publish tự động.",
            "Nên bổ sung tài liệu mẫu hoặc biểu mẫu thật của doanh nghiệp trước buổi thực hành.",
        ],
        "source_document_title": title_source,
    }


def _build_maritime_training_lms_course_plan(
    *,
    title_source: str,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    chapter_specs = [
        {
            "title": "Bối cảnh đào tạo nghiệp vụ hàng hải bằng LMS",
            "summary": "Đặt vấn đề chuyển hoạt động bồi dưỡng nghiệp vụ thủy thủ sang môi trường học tập số.",
            "markers": ("gioi thieu", "lms", "thuy thu", "nghiep vu chuyen mon", "dao tao"),
            "objectives": [
                "Giải thích được nhu cầu đào tạo nghiệp vụ chuyên môn cho thủy thủ bằng LMS.",
                "Nhận diện người học, giáo viên và đơn vị quản lý trong bối cảnh hàng hải.",
                "Phân biệt tài liệu nghiên cứu hệ thống LMS với tài liệu hướng dẫn sử dụng một sản phẩm cụ thể.",
            ],
            "lessons": [
                (
                    "Nhu cầu số hóa đào tạo nghiệp vụ cho thủy thủ",
                    "Tổng hợp bối cảnh, mục tiêu và vấn đề đào tạo nghiệp vụ chuyên môn trong ngành hàng hải.",
                    "Người học lập bản đồ vấn đề: thủy thủ cần học gì, học ở đâu và vì sao cần LMS.",
                    "Yếu tố nào khiến đào tạo nghiệp vụ hàng hải khó quản lý nếu chỉ dùng tài liệu rời?",
                ),
                (
                    "Vai trò người học, giảng viên và quản lý đào tạo",
                    "Phân tích các vai trò tham gia hệ thống LMS và trách nhiệm của từng nhóm.",
                    "Tạo bảng vai trò/quyền hạn tối thiểu cho người học, giảng viên và quản trị đào tạo.",
                    "Vai trò nào cần được hỗ trợ nhiều nhất để khóa học vận hành ổn định?",
                ),
                (
                    "Mục tiêu năng lực và chuẩn đầu ra của khóa học",
                    "Chuyển mục tiêu nghiên cứu thành năng lực có thể dạy, luyện tập và đánh giá.",
                    "Viết 3 chuẩn đầu ra theo dạng: hành động, điều kiện, tiêu chí đánh giá.",
                    "Một chuẩn đầu ra tốt khác một mô tả nội dung ở điểm nào?",
                ),
            ],
        },
        {
            "title": "Phân tích yêu cầu hệ thống LMS cho đào tạo thủy thủ",
            "summary": "Biến nhu cầu đào tạo thành yêu cầu chức năng, dữ liệu và quy trình học tập.",
            "markers": ("phan tich", "yeu cau", "chuc nang", "nguoi hoc", "khoa hoc", "bai giang"),
            "objectives": [
                "Tách được yêu cầu nghiệp vụ đào tạo khỏi mô tả giải pháp kỹ thuật.",
                "Liên kết chức năng LMS với quy trình học, kiểm tra và theo dõi tiến độ.",
                "Ưu tiên yêu cầu theo giá trị vận hành và khả năng kiểm chứng.",
            ],
            "lessons": [
                (
                    "Từ nhu cầu đào tạo sang yêu cầu chức năng",
                    "Đọc tài liệu để rút ra các chức năng như khóa học, bài giảng, kiểm tra và theo dõi học viên.",
                    "Đánh dấu các câu có thể chuyển thành user story cho hệ thống LMS.",
                    "Yêu cầu nào là lõi của đào tạo thủy thủ, yêu cầu nào chỉ là tiện ích?",
                ),
                (
                    "Luồng học tập: đăng ký, học, kiểm tra và phản hồi",
                    "Mô tả hành trình người học từ lúc vào khóa đến khi hoàn thành đánh giá.",
                    "Vẽ flow ngắn cho một thủy thủ học bài, làm quiz và nhận phản hồi.",
                    "Điểm nào trong luồng cần lưu vết để giáo viên theo dõi tiến bộ?",
                ),
                (
                    "Yêu cầu dữ liệu và báo cáo đào tạo",
                    "Xác định dữ liệu cần cho hồ sơ học tập, tiến độ, điểm số và báo cáo năng lực.",
                    "Thiết kế một bảng thông tin tối thiểu cho tiến độ học của học viên.",
                    "Báo cáo nào giúp quản lý biết khóa học có hiệu quả hay không?",
                ),
            ],
        },
        {
            "title": "Thiết kế học liệu, hoạt động và kiểm tra trên LMS",
            "summary": "Chuyển nội dung chuyên môn thành bài học số có tương tác, bài tập và đánh giá.",
            "markers": ("hoc lieu", "bai giang", "video", "quiz", "danh gia", "tuong tac"),
            "objectives": [
                "Thiết kế bài học số bám sát mục tiêu năng lực.",
                "Chọn dạng học liệu phù hợp cho kiến thức, quy trình và tình huống hàng hải.",
                "Xây dựng kiểm tra nhanh có nguồn trích dẫn để giáo viên xác minh.",
            ],
            "lessons": [
                (
                    "Cấu trúc một bài học nghiệp vụ trên LMS",
                    "Tổ chức bài học thành mục tiêu, nội dung cốt lõi, ví dụ, hoạt động và kiểm tra.",
                    "Biến một phần tài liệu thành khung bài học 20 phút cho thủy thủ.",
                    "Bài học cần có thành phần nào để người học không chỉ đọc mà còn luyện tập?",
                ),
                (
                    "Học liệu đa phương tiện và tình huống thực hành",
                    "Xác định khi nào dùng văn bản, hình ảnh, video, mô phỏng hoặc checklist nghiệp vụ.",
                    "Đề xuất một tình huống hàng hải và loại học liệu phù hợp để dạy tình huống đó.",
                    "Loại học liệu nào dễ tạo cảm giác hiểu nhầm nếu thiếu bối cảnh?",
                ),
                (
                    "Quiz, rubric và phản hồi năng lực",
                    "Thiết kế câu hỏi kiểm tra, rubric và phản hồi giúp đo năng lực chuyên môn.",
                    "Viết 3 câu hỏi: nhận biết, áp dụng và xử lý tình huống.",
                    "Một quiz tốt cần đo điều gì ngoài việc nhớ lại nội dung?",
                ),
            ],
        },
        {
            "title": "Thiết kế vận hành, phân quyền và theo dõi chất lượng",
            "summary": "Đưa khóa học vào quy trình quản lý có phân quyền, dữ liệu tiến độ và kiểm soát chất lượng.",
            "markers": ("phan quyen", "quan ly", "tien do", "bao cao", "chat luong", "du lieu"),
            "objectives": [
                "Thiết kế phân quyền an toàn cho người học, giảng viên và quản trị.",
                "Theo dõi tiến độ học tập bằng dữ liệu có thể kiểm chứng.",
                "Xây dựng vòng phản hồi để cải tiến khóa học sau mỗi đợt triển khai.",
            ],
            "lessons": [
                (
                    "Phân quyền và an toàn dữ liệu đào tạo",
                    "Xác định quyền xem, sửa, chấm, xuất báo cáo và quản trị nội dung trong LMS.",
                    "Lập ma trận quyền hạn cho giáo viên, học viên và quản lý đào tạo.",
                    "Quyền nào nếu cấp sai sẽ ảnh hưởng lớn nhất tới độ tin cậy của khóa học?",
                ),
                (
                    "Theo dõi tiến độ và cảnh báo học tập",
                    "Thiết kế chỉ số theo dõi tiến độ, mức hoàn thành và điểm cần hỗ trợ.",
                    "Đề xuất 5 chỉ số dashboard giúp giáo viên biết lớp đang học ra sao.",
                    "Chỉ số nào dễ gây hiểu nhầm nếu không kèm ngữ cảnh?",
                ),
                (
                    "Quy trình cải tiến nội dung sau triển khai",
                    "Dùng dữ liệu học tập, phản hồi và kết quả kiểm tra để chỉnh bài học.",
                    "Viết checklist rà soát khóa học sau một vòng chạy thử.",
                    "Khi nào nên sửa nội dung, khi nào nên sửa hoạt động học?",
                ),
            ],
        },
        {
            "title": "Triển khai thử nghiệm và đánh giá hiệu quả đào tạo",
            "summary": "Lập kế hoạch pilot, kiểm thử và đo hiệu quả của hệ thống LMS trong đào tạo hàng hải.",
            "markers": ("trien khai", "thu nghiem", "kiem thu", "danh gia", "ket qua", "huong phat trien"),
            "objectives": [
                "Lập kế hoạch triển khai thử nghiệm LMS theo giai đoạn an toàn.",
                "Thiết kế kiểm thử theo nghiệp vụ đào tạo thay vì chỉ kiểm tra giao diện.",
                "Đánh giá hiệu quả bằng dữ liệu học tập và phản hồi từ người dùng.",
            ],
            "lessons": [
                (
                    "Kế hoạch pilot cho khóa học nghiệp vụ thủy thủ",
                    "Chia triển khai thành các bước: chuẩn hóa học liệu, tạo lớp, chạy thử và thu phản hồi.",
                    "Lập checklist trước khi mở khóa học cho nhóm học viên đầu tiên.",
                    "Rủi ro nào cần kiểm soát trước khi pilot trên người học thật?",
                ),
                (
                    "Kiểm thử chức năng và kiểm thử trải nghiệm học",
                    "Xây dựng test case cho học liệu, quiz, tiến độ, phân quyền và báo cáo.",
                    "Viết 3 test case chứng minh khóa học vừa đúng hệ thống vừa đúng nghiệp vụ.",
                    "Một test UI thành công có đủ để kết luận khóa học tốt chưa?",
                ),
                (
                    "Đánh giá hiệu quả và hướng phát triển",
                    "Đo mức hoàn thành, chất lượng câu trả lời, phản hồi người học và khả năng mở rộng.",
                    "Đề xuất 3 KPI so sánh trước/sau khi áp dụng LMS vào đào tạo thủy thủ.",
                    "Nếu mở rộng hệ thống, ưu tiên cải tiến nội dung, dữ liệu hay trải nghiệm trước?",
                ),
            ],
        },
    ]

    chapters: list[dict[str, Any]] = []
    for chapter_index, spec in enumerate(chapter_specs, start=1):
        chapter_refs = _match_doc_refs(
            refs,
            tuple(spec["markers"]),
            fallback_title=title_source,
            chapter_index=chapter_index,
        )
        lessons = []
        for lesson_index, (title, summary, activity, quick_check) in enumerate(
            spec["lessons"],
            start=1,
        ):
            lesson_refs = _match_doc_refs(
                refs,
                tuple(spec["markers"]) + tuple(title.lower().split()[:4]),
                fallback_title=title_source,
                chapter_index=chapter_index,
                lesson_index=lesson_index,
            )
            lessons.append(
                _lms_manual_lesson(
                    title=title,
                    summary=summary,
                    activity=activity,
                    quick_check=quick_check,
                    refs=lesson_refs,
                    duration_minutes=22,
                )
            )
        chapters.append(
            {
                "title": spec["title"],
                "summary": spec["summary"],
                "learning_objectives": spec["objectives"],
                "lessons": lessons,
                "source_references": chapter_refs,
            }
        )

    lesson_count = sum(len(chapter["lessons"]) for chapter in chapters)
    return {
        "title": "LMS nâng cao nghiệp vụ chuyên môn cho thủy thủ",
        "description": (
            "Khóa học chuyển tài liệu nghiên cứu về hệ thống LMS phục vụ đào tạo "
            "nghiệp vụ hàng hải thành cây chương/bài có hoạt động, đánh giá và nguồn trích dẫn."
        ),
        "audience": (
            "Giảng viên hàng hải, người quản lý đào tạo, thủy thủ/học viên và nhóm triển khai LMS."
        ),
        "duration": f"{len(chapters)} chương, {lesson_count} bài, triển khai trong 4-6 buổi học/workshop.",
        "chapters": chapters,
        "assessment_plan": [
            "Mỗi chương có kiểm tra nhanh gắn với nguồn trích dẫn từ tài liệu nghiên cứu.",
            "Cuối khóa làm project nhỏ: thiết kế một module/bài học LMS cho nghiệp vụ hàng hải cụ thể.",
            "Đánh giá bằng rubric gồm: đúng mục tiêu năng lực, phù hợp người học, có dữ liệu theo dõi và khả năng triển khai.",
        ],
        "implementation_checklist": [
            "Giáo viên kiểm tra title, chương/bài và citation trước khi áp dụng vào LMS.",
            "Các chương/bài được tạo ở trạng thái draft; không publish tự động.",
            "Nên bổ sung tài liệu nghiệp vụ, rubric hoặc ví dụ tình huống thật trước buổi thực hành.",
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


def _build_assistant_tool_call_message(
    tool_calls: list[dict[str, Any]],
    *,
    native_tool_messages: bool,
) -> Any:
    if native_tool_messages:
        from app.engine.native_chat_runtime import make_assistant_message

        return make_assistant_message("", tool_calls=tool_calls)

    from app.engine.messages import Message, ToolCall

    return Message(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(
                id=str(call.get("id") or f"raw_tool_call_{index}"),
                name=str(call.get("name") or ""),
                arguments=dict(call.get("args") or call.get("arguments") or {}),
            )
            for index, call in enumerate(tool_calls)
            if str(call.get("name") or "").strip()
        ],
    )


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
                    "course_plan có nguồn trích dẫn trước và chỉ gửi host action preview; LMS sẽ "
                    "yêu cầu giáo viên bấm Áp dụng để cấp approval_token trước khi ghi dữ liệu."
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
                    "Bạn xem cây chương/bài và nguồn trích dẫn trong hộp xem trước, rồi chỉ bấm Áp dụng "
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
                    "mình dựng payload preview từ document_context và gửi host action preview-only để LMS mở phần so sánh thay đổi và nguồn trích dẫn trước."
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
                    "Bạn kiểm tra phần so sánh thay đổi và nguồn trích dẫn trong hộp xem trước, rồi chỉ bấm Áp dụng nếu nội dung đúng."
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
    if tools and not tool_calls:
        raw_tool_calls = extract_raw_tool_calls_from_text(
            getattr(llm_response, "content", ""),
            allowed_tool_names=tool_names_from_tools(tools) or None,
        )
        if raw_tool_calls:
            logger.warning(
                "[DIRECT] Converted raw JSON assistant content into %d structured tool call(s): %s",
                len(raw_tool_calls),
                [call.get("name") for call in raw_tool_calls],
            )
            llm_response = _build_assistant_tool_call_message(
                raw_tool_calls,
                native_tool_messages=native_tool_messages,
            )
            tool_calls = getattr(llm_response, "tool_calls", raw_tool_calls)
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
