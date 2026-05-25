from app.engine.multi_agent.code_studio_context import (
    _build_code_studio_terminal_failure_response,
    _format_code_studio_progress_message,
    _infer_pendulum_fast_path_title,
)
from app.engine.multi_agent.code_studio_fast_paths import _ARTIFACT_FAST_PATH_HTML


def test_code_studio_elapsed_status_uses_accented_vietnamese() -> None:
    assert _format_code_studio_progress_message("Đang dựng preview...", 12) == (
        "Đang dựng preview... (đã 12s)"
    )


def test_code_studio_pendulum_title_uses_accented_vietnamese() -> None:
    assert _infer_pendulum_fast_path_title("mô phỏng con lắc", {}) == "Mô phỏng con lắc"


def test_code_studio_terminal_failure_copy_does_not_include_ascii_parenthetical() -> None:
    message = _build_code_studio_terminal_failure_response("tạo artifact html")

    assert "kết nối" in message
    assert "ket noi" not in message.lower()


def test_artifact_fast_path_scaffold_copy_is_vietnamese_first() -> None:
    assert "Khung Artifact" in _ARTIFACT_FAST_PATH_HTML
    assert "Mini HTML app đã sẵn sàng" in _ARTIFACT_FAST_PATH_HTML
    assert "Sẵn sàng nhúng" in _ARTIFACT_FAST_PATH_HTML
    assert "Đã nhấn một lần - khung artifact đang hoạt động" in _ARTIFACT_FAST_PATH_HTML
    assert "Ready to embed" not in _ARTIFACT_FAST_PATH_HTML
    assert "Clicked once" not in _ARTIFACT_FAST_PATH_HTML
