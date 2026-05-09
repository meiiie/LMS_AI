"""Time and pronoun-context helpers for prompt assembly."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))

VN_DAY_NAMES = [
    "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
    "Thứ Sáu", "Thứ Bảy", "Chủ Nhật",
]

VALID_PRONOUN_PAIRS = {
    "mình": {"user_called": "cậu", "ai_self": "mình"},
    "tớ": {"user_called": "cậu", "ai_self": "tớ"},
    "em": {"user_called": "em", "ai_self": "anh"},
    "anh": {"user_called": "anh", "ai_self": "em"},
    "chị": {"user_called": "chị", "ai_self": "em"},
    "tôi": {"user_called": "bạn", "ai_self": "tôi"},
    "bạn": {"user_called": "bạn", "ai_self": "tôi"},
}

INAPPROPRIATE_PRONOUNS = [
    "mày", "tao", "đ.m", "dm", "vcl", "vl", "đéo", "địt",
    "con", "thằng", "đồ", "lũ", "bọn",
]


def _contains_inappropriate_pronoun(message_lower: str, bad_word: str) -> bool:
    """Match pronoun/profanity cues as terms, not substrings inside words."""
    if not message_lower or not bad_word:
        return False
    return re.search(rf"(?<!\w){re.escape(bad_word)}(?!\w)", message_lower) is not None


def _get_time_of_day_label(hour: int) -> tuple[str, str]:
    if 6 <= hour < 12:
        return "buổi sáng", ""
    if 12 <= hour < 14:
        return "buổi trưa", ""
    if 14 <= hour < 18:
        return "buổi chiều", ""
    if 18 <= hour < 22:
        return "buổi tối", ""
    if 22 <= hour or hour < 2:
        return "khuya", "nếu user vẫn đang học/làm việc, có thể nhắc nhẹ nghỉ ngơi khi phù hợp"
    return "rất khuya", "user thức rất khuya — quan tâm nhẹ khi phù hợp, không ép"


def build_time_context() -> str:
    """Build Vietnamese time context string for system prompt injection."""
    now = datetime.now(VN_TZ)
    day_name = VN_DAY_NAMES[now.weekday()]
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d/%m/%Y")
    label, hint = _get_time_of_day_label(now.hour)

    line1 = f"Thời gian hiện tại: {time_str} {day_name}, {date_str} (giờ Việt Nam UTC+7)"
    line2 = f"Buổi: {label} — {hint}." if hint else f"Buổi: {label}"
    return f"{line1}\n{line2}"


def detect_pronoun_style(message: str) -> Optional[Dict[str, str]]:
    """Detect user's pronoun style from their message."""
    message_lower = message.lower()

    for bad_word in INAPPROPRIATE_PRONOUNS:
        if _contains_inappropriate_pronoun(message_lower, bad_word):
            logger.warning("Inappropriate pronoun detected: %s", bad_word)
            return None

    pronoun_patterns = [
        (r"\bmình\s+(?:là|tên|muốn|cần|hỏi|không|có|đang|sẽ|đã)", "mình"),
        (r"\bmình\b", "mình"),
        (r"\btớ\s+(?:là|tên|muốn|cần|hỏi|không|có|đang|sẽ|đã)", "tớ"),
        (r"\btớ\b", "tớ"),
        (r"\bem\s+(?:là|tên|muốn|cần|hỏi|không|có|đang|sẽ|đã|chào)", "em"),
        (r"^em\s+", "em"),
        (r"(?:chào|cảm ơn|hỏi|nhờ)\s+anh\b", "anh"),
        (r"\banh\s+(?:ơi|à|nhé|giúp|chỉ)", "anh"),
        (r"(?:chào|cảm ơn|hỏi|nhờ)\s+chị\b", "chị"),
        (r"\bchị\s+(?:ơi|à|nhé|giúp|chỉ)", "chị"),
        (r"(?:chào|cảm ơn|hỏi|nhờ)\s+cậu\b", "mình"),
        (r"\bcậu\s+(?:ơi|à|nhé|giúp|chỉ)", "mình"),
    ]

    for pattern, pronoun in pronoun_patterns:
        if re.search(pattern, message_lower) and pronoun in VALID_PRONOUN_PAIRS:
            style = VALID_PRONOUN_PAIRS[pronoun].copy()
            style["user_self"] = pronoun
            logger.info("Detected pronoun style: %s", style)
            return style

    return None


def get_pronoun_instruction(pronoun_style: Optional[Dict[str, str]]) -> str:
    """Generate instruction for AI to use adapted pronouns."""
    if not pronoun_style:
        return ""

    user_called = pronoun_style.get("user_called", "bạn")
    ai_self = pronoun_style.get("ai_self", "tôi")
    user_self = pronoun_style.get("user_self", "")

    return f"""
--- CÁCH XƯNG HÔ ĐÃ THÍCH ỨNG ---
⚠️ QUAN TRỌNG: User đang xưng "{user_self}", hãy thích ứng theo:
- Gọi user là: "{user_called}"
- Tự xưng là: "{ai_self}"
- KHÔNG dùng "tôi/bạn" mặc định nữa
- Giữ nhất quán trong suốt cuộc hội thoại
"""


_LANGUAGE_TOKEN_RE = re.compile(r"[a-z']+")
_VI_DIACRITIC_RE = re.compile(
    r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệ"
    r"íìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]",
    re.IGNORECASE,
)
_VI_EXPLICIT_REQUEST_MARKERS = (
    "tieng viet",
    "bang tieng viet",
    "tra loi bang tieng viet",
    "noi tieng viet",
    "viet bang tieng viet",
)
_EN_EXPLICIT_REQUEST_MARKERS = (
    "english",
    "in english",
    "reply in english",
    "answer in english",
    "speak english",
    "tieng anh",
    "bang tieng anh",
    "tra loi bang tieng anh",
    "noi tieng anh",
)
_VI_SOFT_MARKERS = {
    "minh", "toi", "ban", "nha", "nhe", "nhi", "ha", "hong", "khong", "duoc",
    "giup", "voi", "roi", "oke", "okela", "hehe", "hihi", "uh", "ua", "ne",
    "nhe", "nha", "di", "thoi", "gi", "sao", "la", "co", "xem", "chu", "tao",
    "them", "ve",
}
_EN_SOFT_MARKERS = {
    "please", "thanks", "thank", "hello", "hi", "show", "explain", "what",
    "how", "why", "can", "could", "would", "should", "create",
}


def _has_vietnamese_context_signal(text: str) -> bool:
    folded = _fold_language_text(text)
    if not folded:
        return False
    tokens = _LANGUAGE_TOKEN_RE.findall(folded)
    if any(token in _VI_SOFT_MARKERS for token in tokens):
        return True
    return any(
        marker in folded
        for marker in ("cho minh", "cho toi", "duoc chu", "duoc khong", "nhe", "nha", "hehe", "oke")
    )


def _fold_language_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    flattened = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    flattened = flattened.replace("đ", "d").replace("Đ", "D")
    return " ".join(flattened.lower().split())


def normalize_response_language(value: Optional[str]) -> Optional[str]:
    folded = _fold_language_text(value or "")
    if not folded:
        return None
    if folded in {"vi", "vn", "vietnamese", "tieng viet"} or folded.startswith("vi-"):
        return "vi"
    if folded in {"en", "eng", "english", "tieng anh"} or folded.startswith("en-"):
        return "en"
    return None


def detect_requested_response_language(message: str) -> Optional[str]:
    folded = _fold_language_text(message)
    if any(marker in folded for marker in _VI_EXPLICIT_REQUEST_MARKERS):
        return "vi"
    if any(marker in folded for marker in _EN_EXPLICIT_REQUEST_MARKERS):
        return "en"
    return None


def detect_message_language(message: str) -> Optional[str]:
    raw = str(message or "").strip()
    if not raw:
        return None

    explicit = detect_requested_response_language(raw)
    if explicit:
        return explicit

    if _VI_DIACRITIC_RE.search(raw):
        return "vi"

    folded = _fold_language_text(raw)
    tokens = _LANGUAGE_TOKEN_RE.findall(folded)
    if not tokens:
        return None

    vi_score = sum(1 for token in tokens if token in _VI_SOFT_MARKERS)
    en_score = sum(1 for token in tokens if token in _EN_SOFT_MARKERS)

    if any(marker in folded for marker in ("oke", "hehe", "hihi", "nhe", "nha")):
        vi_score += 2

    if vi_score == 0 and en_score == 0:
        return None
    if vi_score >= en_score:
        return "vi"
    return "en"


def resolve_response_language(
    message: str,
    *,
    session_language: Optional[str] = None,
    host_language: Optional[str] = None,
    user_language: Optional[str] = None,
) -> str:
    explicit = detect_requested_response_language(message)
    if explicit:
        return explicit

    detected = detect_message_language(message)
    normalized_session = normalize_response_language(session_language)
    if (
        detected == "en"
        and normalized_session == "vi"
        and _has_vietnamese_context_signal(message)
    ):
        return "vi"
    if detected:
        return detected

    if normalized_session:
        return normalized_session

    normalized_host = normalize_response_language(host_language)
    if normalized_host:
        return normalized_host

    normalized_user = normalize_response_language(user_language)
    if normalized_user:
        return normalized_user

    return "vi"


def build_response_language_instruction(response_language: Optional[str]) -> str:
    """Build a turn-level language contract for prompt injection."""
    resolved = normalize_response_language(response_language) or "vi"
    if resolved == "en":
        return (
            "--- RESPONSE LANGUAGE FOR THIS TURN ---\n"
            "- response_language=en\n"
            "- Think in the same language the user is using for this turn. For this turn, that language is English.\n"
            "- Use English for the final answer, visible thinking, and the underlying native inner monologue for this turn.\n"
            "- Do not think in Vietnamese and then translate to English.\n"
            "- Keep the same language consistently across follow-up turns until the user or host clearly switches again.\n"
            "- Do not drift back to Vietnamese unless the user or host clearly asks for it."
        )

    return (
        "--- NGON NGU CHO LUOT NAY ---\n"
        "- response_language=vi\n"
        "- Hay nghi bang chinh ngon ngu nguoi dung dang dung o turn nay. O turn nay, ngon ngu do la tieng Viet.\n"
        "- Toan bo answer cuoi, visible thinking, va native inner monologue cua turn nay phai dung tieng Viet tu nhien, co dau.\n"
        "- Khong duoc nghi bang tieng Anh roi moi dich sang tieng Viet.\n"
        "- Neu user viet ngan nhu 'oke', 'hehe', 'he he', 'hẹ hẹ', hay cac cau rat ngan mo ho, van uu tien hieu day la nhip tieng Viet tru khi ho noi ro ngon ngu khac.\n"
        "- Giu nguyen ngon ngu nay o cac follow-up cho toi khi user hoac host doi ngon ngu mot cach ro rang."
    )
