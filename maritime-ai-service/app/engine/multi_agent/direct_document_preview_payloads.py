"""Uploaded-document preview and course-plan payload builders."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.document_preview_contract import (
    DOC_COURSE_HOST_ACTION_TOOL as _DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL as _DOC_PREVIEW_HOST_ACTION_TOOL,
    find_document_host_action_tool,
    looks_uploaded_document_course_request as _looks_uploaded_doc_course_request,
    looks_uploaded_document_lesson_preview_request as _looks_uploaded_doc_lesson_preview_request,
    normalize_document_contract_text as _normalize_doc_preview_text,
    uploaded_document_attachments_from_state as _uploaded_document_attachments_from_state,
)
from app.engine.multi_agent.direct_prompt_tool_binding import _tool_name
from app.engine.multi_agent.direct_document_preview_text import (
    _DOC_PREVIEW_LOW_VALUE_LABELS,
    _clean_doc_preview_line,
    _clip_doc_preview_line,
    _extract_doc_preview_title_from_query,
    _extract_marker,
    _extract_relevant_lines,
    _extract_source_pages,
    _first_nonempty_line,
    _focus_doc_preview_markdown,
    _is_doc_preview_admonition_line,
    _is_doc_preview_cover_metadata_line,
    _is_doc_preview_low_value_line,
    _is_doc_preview_ordered_action_line,
    _is_doc_preview_scaffold_line,
    _is_low_value_doc_preview_title,
    _polish_doc_preview_vietnamese_title,
    _repair_doc_preview_common_truncations,
    _score_doc_preview_title_candidate,
    _select_doc_preview_title_line,
    _shape_doc_preview_learning_goal,
    _strip_doc_preview_goal_label,
    _strip_doc_preview_ordered_action_prefix,
    _supplement_doc_preview_learning_goals,
)
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
from app.engine.multi_agent.direct_document_course_analysis import (
    _build_document_course_quality_report,
    _build_generic_document_course_plan,
    _classify_uploaded_document_course_domain,
    _cluster_document_course_sections,
    _cluster_title,
    _copy_doc_refs_with_indices,
    _document_course_section_candidates,
    _extract_doc_course_title_from_query,
    _extract_doc_headings,
    _extract_doc_section_references,
    _lesson_refs_for_candidate,
    _looks_holilihu_lms_manual_document,
    _looks_maritime_training_lms_document,
    _looks_maritime_vessel_management_document,
    _section_candidate_markers,
    _select_lesson_section_candidates,
)
from app.engine.multi_agent.state import AgentState

_DIRECT_DOCUMENT_PREVIEW_TEXT_COMPAT_EXPORTS = (
    _DOC_PREVIEW_LOW_VALUE_LABELS,
    _clean_doc_preview_line,
    _clip_doc_preview_line,
    _is_doc_preview_cover_metadata_line,
    _is_doc_preview_scaffold_line,
    _repair_doc_preview_common_truncations,
    _score_doc_preview_title_candidate,
    _select_doc_preview_title_line,
)

_DIRECT_DOCUMENT_COURSE_ANALYSIS_COMPAT_EXPORTS = (
    _extract_doc_course_title_from_query,
    _doc_source_reference,
    _extract_doc_section_references,
    _match_doc_refs,
    _looks_holilihu_lms_manual_document,
    _looks_maritime_vessel_management_document,
    _looks_maritime_training_lms_document,
    _dedupe_doc_refs,
    _lms_manual_lesson,
    _extract_doc_headings,
    _section_candidate_markers,
    _copy_doc_refs_with_indices,
    _document_course_section_candidates,
    _cluster_document_course_sections,
    _select_lesson_section_candidates,
    _cluster_title,
    _lesson_refs_for_candidate,
    _classify_uploaded_document_course_domain,
    _build_document_course_quality_report,
    _build_generic_document_course_plan,
)


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
    return _looks_uploaded_doc_lesson_preview_request(query)


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
