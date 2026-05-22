"""Text cleanup helpers for uploaded-document preview payloads.

These functions normalize parsed Word/PDF markdown into stable preview titles,
learning goals, checklist lines, markers, and source-page hints. They are kept
separate from host-action payload assembly so document provenance shaping stays
reviewable.
"""

from __future__ import annotations

import re

from app.engine.multi_agent.document_preview_contract import (
    normalize_document_contract_text as _normalize_doc_preview_text,
)

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
