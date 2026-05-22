from app.engine.multi_agent.document_preview_contract import (
    normalize_document_contract_text,
)
from app.engine.multi_agent.direct_document_preview_text import (
    _clean_doc_preview_line,
    _extract_marker,
    _extract_source_pages,
    _select_doc_preview_title_line,
    _shape_doc_preview_learning_goal,
)


def test_clean_doc_preview_line_drops_checkbox_table_marker():
    assert _clean_doc_preview_line("| ☑ | Bước | Thao tác |") == "Bước - Thao tác"
    assert _clean_doc_preview_line("|---|---|") == ""
    assert _clean_doc_preview_line("![logo](data:image/png;base64,abc)") == ""


def test_select_doc_preview_title_skips_cover_metadata():
    markdown = """
    BỘ XÂY DỰNG - BỘ GIÁO DỤC VÀ ĐÀO TẠO
    TRƯỜNG ĐẠI HỌC HÀNG HẢI VIỆT NAM
    Sinh viên thực hiện: HH12345

    NGHIÊN CỨU XÂY DỰNG HỆ THỐNG LMS HỖ TRỢ ĐÀO TẠO HÀNG HẢI
    """

    title = _select_doc_preview_title_line(markdown)

    assert "NGHIÊN CỨU" in title
    assert "TRƯỜNG ĐẠI HỌC" not in title


def test_extract_marker_accepts_wiii_and_labelled_markers():
    assert _extract_marker("marker: CASE-123.A") == "CASE-123.A"
    assert _extract_marker("exact marker WIII_DOC_PREVIEW_42") == "WIII_DOC_PREVIEW_42"
    assert _extract_marker("marker: test") == ""


def test_extract_source_pages_reads_single_and_range():
    assert _extract_source_pages("", "Nguồn section: Điều động tàu (trang 4-6)") == (4, 6)
    assert _extract_source_pages("trang 12", "") == (12, 12)
    assert _extract_source_pages("", "không có trang") == (None, None)


def test_shape_doc_preview_learning_goal_rewrites_lms_manual_goal():
    goal = _shape_doc_preview_learning_goal(
        "Phần này tập trung vào tạo bài học nháp và kiểm tra nguồn trích dẫn",
        is_lms_manual=True,
    )

    normalized = normalize_document_contract_text(goal)
    assert normalized.startswith("giao vien thuc hien duoc")
    assert "tao bai hoc nhap" in normalized
