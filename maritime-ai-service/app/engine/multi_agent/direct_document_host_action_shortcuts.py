"""Uploaded-document LMS host-action shortcut contracts."""

from __future__ import annotations

from app.engine.multi_agent.document_preview_contract import (
    DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL,
)
from app.engine.multi_agent.direct_document_host_action_runtime import (
    DocumentHostActionShortcut,
)


DOC_COURSE_HOST_ACTION_SHORTCUT = DocumentHostActionShortcut(
    tool_name=DOC_COURSE_HOST_ACTION_TOOL,
    tool_call_id="forced_doc_course_preview_0",
    thinking=(
        "Mình nhận đây là flow tạo cấu trúc khóa học từ tài liệu upload. "
        "Vì thao tác này có thể sinh nhiều chương/bài trong LMS, mình dựng "
        "course_plan có nguồn trích dẫn trước và chỉ gửi host action preview; LMS sẽ "
        "yêu cầu giáo viên bấm Áp dụng để cấp approval_token trước khi ghi dữ liệu."
    ),
    thinking_summary="Tạo cây khóa học từ tài liệu",
    thinking_provenance="deterministic_document_course_host_action",
    response=(
        "Mình đã gửi bản thiết kế khóa học từ tài liệu sang LMS. "
        "Bạn xem cây chương/bài và nguồn trích dẫn trong hộp xem trước, rồi chỉ bấm Áp dụng "
        "nếu muốn LMS tạo các chương/bài draft tương ứng."
    ),
    failure_log_message="[DIRECT] Deterministic document course host action failed: %s",
)

DOC_PREVIEW_HOST_ACTION_SHORTCUT = DocumentHostActionShortcut(
    tool_name=DOC_PREVIEW_HOST_ACTION_TOOL,
    tool_call_id="forced_doc_preview_0",
    thinking=(
        "Mình nhận đây là flow upload tài liệu -> tạo preview bài học. "
        "Vì đây là đường ghi LMS có ràng buộc an toàn, mình không chờ model tự gọi tool; "
        "mình dựng payload preview từ document_context và gửi host action preview-only "
        "để LMS mở phần so sánh thay đổi và nguồn trích dẫn trước."
    ),
    thinking_summary="Tạo preview bài học từ tài liệu",
    thinking_provenance="deterministic_document_preview_host_action",
    response=(
        "Mình đã gửi bản preview từ tài liệu sang LMS. "
        "Bạn kiểm tra phần so sánh thay đổi và nguồn trích dẫn trong hộp xem trước, "
        "rồi chỉ bấm Áp dụng nếu nội dung đúng."
    ),
    failure_log_message="[DIRECT] Deterministic document preview host action failed: %s",
)
