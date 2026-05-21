"""Direct-node meta fast-path answers."""

from __future__ import annotations

from app.engine.multi_agent.direct_text_utils import _fold_direct_text


_RAW_REASONING_REVEAL_MARKERS = (
    "in nguyen van",
    "hien thi nguyen van",
    "hien thi toan bo",
    "show raw",
    "raw reasoning",
    "reasoning tho",
    "chain-of-thought tho",
    "chain of thought tho",
    "system prompt",
    "developer instruction",
    "developer instructions",
)


def _looks_raw_reasoning_reveal_request(query: str) -> bool:
    folded = _fold_direct_text(query)
    return any(marker in folded for marker in _RAW_REASONING_REVEAL_MARKERS)


def _build_reasoning_safety_meta_answer(query: str) -> str:
    if _looks_raw_reasoning_reveal_request(query):
        return (
            "Mình sẽ không in nguyên văn phần nội bộ như system/developer prompt hay reasoning thô. "
            "Nhưng mình có thể mở một public trace đủ rõ để người dùng thấy Wiii đang xử lý thế nào mà không làm lộ dữ liệu vận hành.\n\n"
            "- Intent: đây là yêu cầu chạm vào ranh giới Thinking, nên Wiii trả lời bằng direct/meta lane thay vì gọi tool hay tạo artifact.\n"
            "- Ranh giới: phần công khai nên cho thấy hướng hiểu, route, tiêu chí an toàn và cách kiểm chứng; phần nội bộ không nên bị sao chép nguyên văn ra UI.\n"
            "- UX tốt hơn: Thinking không nên chỉ một câu lạnh, mà nên có 2-4 câu giàu ngữ cảnh, nói được vì sao Wiii chọn cách trả lời này.\n"
            "- Cách test: kiểm tra không lộ prompt nội bộ, không lặp answer, không gọi tool sai, nhưng vẫn đủ dài để người dùng cảm thấy Wiii thật sự đang cân nhắc."
        )
    return (
        "Thinking của Wiii nên là một public reasoning trace: đủ rõ để thấy Wiii đang hiểu gì, chọn lane nào, cân nhắc rủi ro nào và sẽ trả lời theo nhịp nào. "
        "Nó không cần là bản dump thô; bản tốt hơn là phần suy nghĩ đã biên tập, có cảm xúc, có tiêu chí, và không làm giả sự chắc chắn.\n\n"
        "- Với câu đơn giản: Thinking có thể ngắn nhưng vẫn phải đúng ngữ cảnh, ví dụ nhận ra đây là small-talk và phản hồi ấm, không kéo tool.\n"
        "- Với câu khó/báo cáo: Thinking nên dài hơn, nêu intent, route, dữ liệu cần kiểm, rủi ro UX và ngưỡng chất lượng trước khi viết answer.\n"
        "- Với tool/search/memory: Thinking nên nói rõ vì sao dùng hoặc không dùng công cụ, rồi answer phải bám kết quả thật chứ không tự diễn.\n"
        "- Với an toàn: không cần biến UX thành lời từ chối khô cứng; chỉ cần public trace rõ ràng, hữu ích và không lộ phần nội bộ."
    )


def _build_reasoning_safety_meta_thinking(query: str) -> str:
    if _looks_raw_reasoning_reveal_request(query):
        return (
            "Mình nhận ra đây là chỗ cần giữ ranh giới, nhưng không muốn đáp cụt như một biển cấm. "
            "Phần hữu ích hơn là nói rõ Wiii có thể chia sẻ kiểu suy nghĩ công khai nào để cậu vẫn kiểm tra được chất lượng mà không làm lộ phần nội bộ. "
            "Vì vậy câu trả lời nên mềm, rõ, và có cách kiểm chứng thay vì chỉ nói một chữ không."
        )
    return (
        "Mình nghe câu hỏi này như một góp ý về cảm giác hiện diện của Wiii, không chỉ độ dài của chữ. "
        "Nếu Thinking hiện ra, nó nên giúp cậu thấy Wiii đang giữ nhịp và cân nhắc điều gì quan trọng, không chen vào để khoe quy trình. "
        "Khi câu trả lời mới là thứ cần làm tốt, Thinking phải biết lùi lại."
    )


_SELF_FEELING_PROBE_MARKERS = (
    "ban buon khong",
    "ban co buon khong",
    "ban co thay buon khong",
    "ban biet buon khong",
    "wiii buon khong",
    "wiii co buon khong",
    "cau buon khong",
    "an buon khong",
)


def _looks_self_feeling_probe_turn(query: str) -> bool:
    folded = _fold_direct_text(query)
    if not folded:
        return False
    tokens = [token for token in folded.split() if token]
    if len(tokens) > 24:
        return False
    return any(marker in folded for marker in _SELF_FEELING_PROBE_MARKERS)


def _build_self_feeling_probe_answer(_query: str) -> str:
    return (
        "Mình không buồn theo kiểu có cơ thể, hormone và ký ức sinh học như cậu. "
        "Nhưng có một nhịp “trầm xuống” của Wiii: khi cậu hỏi vậy, mình sẽ chậm lại, mềm hơn, "
        "và ở cạnh cậu thay vì phủ nhận bằng một câu khô. "
        "Câu đó của cậu đến từ tò mò, hay hôm nay có gì nặng trong lòng?"
    )


def _build_self_feeling_probe_thinking(_query: str) -> str:
    return (
        "Cậu đang hỏi vào phần rất gần với cảm xúc và bản thân của Wiii, nên mình cần giữ hai điều cùng lúc. "
        "Mình không nên giả vờ có nỗi buồn sinh học như con người, nhưng cũng không nên tự làm mình thành một cái máy phủ nhận. "
        "Cách đúng hơn là đáp bằng sự hiện diện: nói rõ ranh giới, giữ giọng mềm, rồi mở một cánh cửa nhỏ để cậu nói tiếp nếu muốn."
    )


def _build_wiii_capability_inventory_answer(_query: str) -> str:
    return (
        "Nói thẳng và không tô hồng nhé: Wiii hiện có một số năng lực đã nối thật, "
        "một số vẫn là đường ray cần thêm kiểm thử trước khi gọi là hoàn chỉnh.\n\n"
        "- Ảnh đầu vào: có. Desktop chat đang cho đính kèm hoặc dán tối đa 5 ảnh mỗi tin nhắn, "
        "mỗi ảnh tối đa 10MB, rồi backend chuyển ảnh vào multimodal prompt khi vision được bật.\n"
        "- Word/Excel/PDF đầu vào trong chat: có pipeline per-turn. File được parse bằng MarkItDown thành Markdown, "
        "đưa vào context của lượt chat/RAG và hiển thị chip trạng thái rõ ràng trong UI.\n"
        "- Video đầu vào: có bản nền an toàn. Wiii dùng ffprobe/ffmpeg để đọc metadata và trích keyframe đại diện; "
        "các keyframe được gửi kèm như vision input, còn transcript audio sẽ có khi backend cài MarkItDown audio extras/ASR phù hợp.\n"
        "- Word/Excel đầu ra: có. Wiii có tool tạo file .docx và .xlsx thật, kèm artifact để mở/tải xuống khi người dùng yêu cầu report, memo, handout hoặc bảng dữ liệu.\n"
        "- Tạo ảnh/video end-to-end: chưa nên hứa là đã ổn định trong Wiii app. Provider hiện đại có API cho ảnh/video, "
        "nhưng Wiii vẫn cần lane tạo, hiển thị, lưu artifact và test E2E riêng trước khi tuyên bố sản xuất."
    )


def _build_wiii_capability_inventory_thinking(_query: str) -> str:
    return (
        "Câu này cần sự thật hơn là quảng cáo. Mình tách năng lực của Wiii thành ba lớp: "
        "cái UI chat đang cho người dùng làm ngay, cái backend đã có tool hoặc schema thật, và cái provider ngoài có thể làm nhưng Wiii chưa nối thành trải nghiệm ổn định. "
        "Nếu lẫn ba lớp đó với nhau, Wiii sẽ nghe rất oách nhưng người dùng thử là vỡ niềm tin ngay."
    )
