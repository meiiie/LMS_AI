"""Source-reference helpers for uploaded-document preview/course payloads."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.document_preview_contract import (
    normalize_document_contract_text as _normalize_doc_preview_text,
)

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
