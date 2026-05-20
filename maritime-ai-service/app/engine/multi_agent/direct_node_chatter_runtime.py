"""Small direct-node chatter fast paths."""

from __future__ import annotations

from app.engine.multi_agent.direct_text_utils import _fold_direct_text


_HUNGER_CHATTER_MARKERS = (
    "doi phet",
    "doi qua",
    "hoi doi",
    "minh doi",
    "dang doi",
    "buong doi",
    "bung doi",
    "hungry",
    "starving",
)

_HUNGER_CHATTER_TASK_BLOCKERS = (
    "bao nhieu",
    "canvas",
    "chart",
    "code",
    "css",
    "excel",
    "file",
    "giai thich",
    "html",
    "huong dan",
    "javascript",
    "la gi",
    "mo phong",
    "pdf",
    "phan tich",
    "python",
    "quy dinh",
    "react",
    "search",
    "so sanh",
    "tao anh",
    "the nao",
    "thay doi",
    "tim",
    "tin tuc",
    "tra cuu",
    "video",
    "viet",
    "word",
)


def _looks_hunger_chatter_turn(normalized_query: str) -> bool:
    folded = _fold_direct_text(normalized_query)
    if not folded:
        return False
    if any(marker in folded for marker in ("hay nho", "ghi nho", "nho rang", "luu lai")):
        return False
    if any(marker in folded for marker in _HUNGER_CHATTER_TASK_BLOCKERS):
        return False
    tokens = [token for token in folded.split() if token]
    if len(tokens) > 40:
        return False
    return any(marker in folded for marker in _HUNGER_CHATTER_MARKERS)


def _build_hunger_chatter_answer(_query: str) -> str:
    folded = _fold_direct_text(_query)
    if "bung doi" in folded:
        opener = "Bụng đói thì não tụt pin thật đó."
    elif "hoi doi" in folded:
        opener = "Hơi đói cũng nên lót bụng trước khi cố làm tiếp nha."
    else:
        opener = "Đói phết là não tụt pin thật đó."
    if "bao cao" in folded or "cang" in folded or "ap luc" in folded:
        return (
            f"{opener} Lót bụng trước đi cậu: bắt lấy thứ gì nhanh và ấm như bánh mì, "
            "trứng, súp, sữa chua hoặc chuối; uống thêm nước nữa. Báo cáo thì mình "
            "một bước một bước, không cần gồng quá ngay lúc bụng đang réo."
        )
    return (
        f"{opener} Kiếm gì dễ ăn trong 5-10 phút trước nha: cơm, mì, bánh mì, trứng, "
        "sữa chua hoặc chuối đều được; uống thêm nước, ăn xong mình ngồi đây tính tiếp cùng cậu."
    )


def _build_hunger_chatter_thinking(_query: str) -> str:
    return (
        "Cậu nói rất ngắn, nhưng mình nghe được một nhu cầu rất thật: bụng đói thì mọi thứ cũng tụt pin theo. "
        "Mình không cần làm màu ở đây; chỉ cần kéo cậu về một việc nhỏ có ích ngay, rồi ở lại cùng cậu tính tiếp."
    )
