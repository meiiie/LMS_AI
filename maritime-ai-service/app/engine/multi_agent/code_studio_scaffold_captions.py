"""Vietnamese captions for Code Studio scaffold fallback previews."""

from __future__ import annotations

from app.engine.multi_agent.code_studio_scaffold_contract import (
    PRIMITIVE_DATA_BAND,
    PRIMITIVE_FUNCTION_PLOT,
    PRIMITIVE_OSCILLATION,
    PRIMITIVE_PARTICLE_FIELD,
    PRIMITIVE_SCENE,
    PRIMITIVE_TIMELINE,
)


_CAPTIONS_BY_PRIMITIVE = {
    PRIMITIVE_PARTICLE_FIELD: (
        "Mình đã dựng khung hạt tương tác. Kéo thanh trượt để thay đổi "
        "mật độ. Cho mình biết bạn muốn thêm hiệu ứng hoặc khung cảnh gì "
        "để mở rộng nhé."
    ),
    PRIMITIVE_OSCILLATION: (
        "Mình đã dựng khung mô phỏng dao động đầu tiên. Cho mình biết "
        "tham số như chiều dài, ma sát, trọng trường hoặc hiện tượng cụ "
        "thể để thay phần lõi bằng vật lý chính xác."
    ),
    PRIMITIVE_FUNCTION_PLOT: (
        "Mình đã mở canvas với khung lưới toạ độ. Cho mình biết hàm số "
        "hoặc phạm vi trục để vẽ đúng đồ thị bạn cần."
    ),
    PRIMITIVE_TIMELINE: (
        "Mình đã dựng khung dòng thời gian. Cho mình biết bạn quan tâm "
        "tới mặt trận, nhân vật hoặc chiến dịch nào để mở rộng cảnh."
    ),
    PRIMITIVE_SCENE: (
        "Mình đã mở canvas và dựng khung scene đầu tiên. Hãy mô tả thêm "
        "về tâm trạng, bối cảnh hoặc đoạn thơ trích dẫn để mình mở rộng "
        "cảnh đúng hướng nhé."
    ),
    PRIMITIVE_DATA_BAND: (
        "Mình đã mở canvas và dựng khung tạm để bạn không phải chờ. "
        "Hãy mô tả cụ thể hơn về nội dung bạn muốn dựng, Wiii sẽ mở rộng "
        "đúng hướng."
    ),
}


def caption_for_scaffold_primitive(primitive: str | None) -> str:
    """Return a Vietnamese caption for the selected scaffold primitive."""
    return _CAPTIONS_BY_PRIMITIVE.get(
        primitive,
        _CAPTIONS_BY_PRIMITIVE[PRIMITIVE_DATA_BAND],
    )
