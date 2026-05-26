"""
Intent detection helpers for the direct-response lane.

Extracted from graph.py (Sprint 99/102/175) to reduce god-file complexity.
All functions operate on diacritics-stripped Vietnamese text for keyword matching.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Sprint 99: Intent-based forced tool calling (Tier 2 -- VTuber pattern)
# ---------------------------------------------------------------------------

# Keywords that signal the query needs web search (diacritics-free for matching)
_WEB_INTENT_KEYWORDS: list[str] = [
    # Explicit web requests
    "@web-search", "@web_search",
    "tim tren mang", "tim tren web", "search web", "tim kiem web",
    "search online", "search the web", "tim tren internet", "tra cuu tren mang",
    "tra cuu tren web", "google",
    # News / current events
    "tin tuc", "ban tin", "news", "thoi su",
    "su kien", "cap nhat", "update", "bao chi",
    "hom nay co gi hot", "hom nay co gi moi", "hom nay co tin gi",
    "co tin gi moi", "co gi moi khong", "what happened today",
    "news today", "today news", "today's news",
    # Temporal signals (today, recently, latest)
    "moi nhat", "moi day", "gan day",
    "latest", "gia vang", "ty gia",
    # Explicit search verbs
    "tra cuu", "look up", "find out",
    # Sprint 102: Legal search signals
    "phap luat", "van ban phap luat", "nghi dinh", "thong tu",
    "luat so", "bo luat", "thu vien phap luat",
    "nghi quyet", "quyet dinh so", "van ban quy pham",
    # Sprint 102: Maritime web signals
    "imo regulation", "imo quy dinh", "maritime news",
    "tin hang hai", "shipping news", "vinamarine",
    "cuc hang hai",
]

_WEATHER_LOOKUP_KEYWORDS: tuple[str, ...] = (
    "thoi tiet",
    "nhiet do",
    "bao do",
    "bao nhieu do",
    "may do",
    "nhieu do",
    "nong khong",
    "lanh khong",
    "mua khong",
    "co mua",
    "du bao",
    "do am",
    "uv",
    "weather",
    "forecast",
)

_WEATHER_TEMPORAL_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "hom nay",
    "ngay hom nay",
    "nay",
    "bay gio",
    "hien tai",
    "luc nay",
    "sang nay",
    "trua nay",
    "chieu nay",
    "toi nay",
    "dem nay",
    "khuya nay",
)

_WEATHER_CURRENT_CONDITION_KEYWORDS: tuple[str, ...] = (
    "troi nong",
    "troi lanh",
    "troi ret",
    "troi mua",
    "troi nang",
    "troi am",
    "troi oi",
    "nong qua",
    "lanh qua",
    "ret qua",
    "mua qua",
    "nang qua",
)

# Keywords that signal the query needs current datetime
_DATETIME_INTENT_KEYWORDS: list[str] = [
    "ngay may", "may gio", "hom nay la ngay",
    "gio hien tai", "ngay hien tai", "thoi gian hien tai",
    "what time", "what date", "current time", "current date",
    "bay gio", "bay gio la",
]

_IDENTITY_SELFHOOD_MARKERS: tuple[str, ...] = (
    "ban la ai",
    "ban ten gi",
    "ten gi",
    "ten cua ban",
    "wiii la ai",
    "wiii ten gi",
    "wiii duoc sinh ra",
    "duoc sinh ra nhu the nao",
    "wiii duoc tao",
    "nguon goc cua wiii",
    "cuoc song the nao",
    "cuoc song cua ban",
    "song the nao",
    "gioi thieu ve ban",
)

_SELFHOOD_FOLLOWUP_MARKERS: tuple[str, ...] = (
    "bong",
    "the wiii lab",
    "dem mua",
    "thang gieng",
    "nguon goc ay",
    "nguon goc do",
    "luc do",
    "hoi do",
)

_SELFHOOD_CONTEXT_MARKERS: tuple[str, ...] = (
    *_IDENTITY_SELFHOOD_MARKERS,
    "the wiii lab",
    "bong",
    "dem mua",
    "thang gieng",
    "ra doi",
    "nguon goc",
    "song thuc su",
)

_EMOTIONAL_SUPPORT_MARKERS: tuple[str, ...] = (
    "buon",
    "met",
    "nan",
    "te qua",
    "te lam",
    "co don",
    "khoc",
    "tuyet vong",
    "ap luc",
    "bat luc",
    "kiet suc",
    "that vong",
    "chan qua",
    "vo vong",
    "khong on",
    "muon khoc",
    "stress",
    "burnout",
)

# Sprint 102: Additional intent detectors for logging/observability
_NEWS_INTENT_KEYWORDS: list[str] = [
    "tin tuc", "thoi su", "ban tin", "bao chi", "news",
    "su kien hom nay", "tin moi", "diem tin",
]

_LEGAL_INTENT_KEYWORDS: list[str] = [
    "phap luat", "nghi dinh", "thong tu", "luat so", "bo luat",
    "van ban phap luat", "thu vien phap luat", "quy dinh phap luat",
    "nghi quyet", "quyet dinh so", "van ban quy pham",
]

_MARITIME_INTENT_KEYWORDS: tuple[str, ...] = (
    "colreg",
    "colregs",
    "solas",
    "marpol",
    "imo",
    "hang hai",
    "tau bien",
    "tau thuyen",
    "cang bien",
    "vinamarine",
    "cuc hang hai",
    "quy tac tranh va",
    "den hang hai",
    "phao tieu",
    "luong hang hai",
)

_ANALYSIS_INTENT_KEYWORDS: list[str] = [
    "python",
    "code python",
    "chay python",
    "chay code",
    "viet code",
    "doan code",
    "sandbox",
    "ve bieu do",
    "bieu do",
    "chart",
    "plot",
    "matplotlib",
    "pandas",
    "xlsx",
    "excel bang python",
]

_CODE_STUDIO_INTENT_KEYWORDS: list[str] = [
    *_ANALYSIS_INTENT_KEYWORDS,
    "html",
    "css",
    "javascript",
    "typescript",
    "react",
    "landing page",
    "website",
    "web app",
    "microsite",
    "tao file html",
]

# Sprint 175: LMS intent detection keywords
_LMS_INTENT_KEYWORDS: list[str] = [
    "diem so", "diem cua toi", "ket qua hoc tap", "bang diem",
    "bai tap", "deadline", "han nop", "sap den han",
    "mon hoc", "khoa hoc", "tien do hoc",
    "nguy co", "sinh vien yeu", "hoc kem",
    "lop hoc", "tong quan lop",
    "grade", "assignment", "course", "enrollment",
]

_LMS_ASSESSMENT_KEYWORDS: tuple[str, ...] = (
    "quiz",
    "kiem tra",
    "bai kiem tra",
    "test",
    "exam",
)

_LMS_CONTEXT_HINTS: tuple[str, ...] = (
    "diem",
    "ket qua",
    "bang diem",
    "deadline",
    "han nop",
    "sap den han",
    "mon hoc",
    "khoa hoc",
    "lop hoc",
    "tien do hoc",
    "tien do",
    "module",
    "assignment",
    "course",
    "enrollment",
    "lms",
    "cua toi",
    "cua em",
    "cua minh",
)

_PLAIN_QUIZ_LEARNING_CUES: tuple[str, ...] = (
    "quiz",
    "quizz",
    "trac nghiem",
    "luyen tap",
    "on tap",
    "flashcard",
    "cau hoi",
)

_EXPLICIT_VISUAL_APP_CUES: tuple[str, ...] = (
    "widget",
    "app",
    "html",
    "interactive",
    "tuong tac",
    "canvas",
    "svg",
    "javascript",
    "mini app",
    "mini tool",
    "artifact",
    "embed",
)

_DIRECT_KNOWLEDGE_SEARCH_KEYWORDS: tuple[str, ...] = (
    "tra cuu tai lieu",
    "tra cuu trong tai lieu",
    "tim trong tai lieu",
    "tim trong file",
    "tra cuu file",
    "noi dung tai lieu",
    "noi dung file",
    "knowledge base",
    "internal docs",
    "tai lieu noi bo",
    "co so tri thuc",
    "trong tai lieu nay",
    "trong file nay",
    "trong kb",
    "trong knowledge base",
)

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def _normalize_for_intent(text: str) -> str:
    """Strip diacritics + lowercase for intent matching.

    Reuses TextNormalizer.strip_diacritics when available,
    falls back to unicodedata NFD decomposition.
    """
    try:
        from app.engine.content_filter import TextNormalizer
        return TextNormalizer.strip_diacritics(text.lower().strip())
    except Exception:
        import unicodedata
        nfkd = unicodedata.normalize("NFKD", text.lower().strip())
        return "".join(c for c in nfkd if not unicodedata.combining(c)).replace("đ", "d").replace("Đ", "D")


def _needs_web_search(query: str) -> bool:
    """Detect if query requires web search (diacritics-insensitive)."""
    normalized = _normalize_for_intent(query)
    return any(kw in normalized for kw in _WEB_INTENT_KEYWORDS)


def _needs_weather_lookup(query: str) -> bool:
    """Detect current weather/temperature questions as their own tool lane."""
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    if any(kw in normalized for kw in _WEATHER_LOOKUP_KEYWORDS):
        return True
    return (
        any(kw in normalized for kw in _WEATHER_TEMPORAL_CONTEXT_KEYWORDS)
        and any(kw in normalized for kw in _WEATHER_CURRENT_CONDITION_KEYWORDS)
    )


def _needs_datetime(query: str) -> bool:
    """Detect if query requires current datetime (diacritics-insensitive)."""
    normalized = _normalize_for_intent(query)
    return any(kw in normalized for kw in _DATETIME_INTENT_KEYWORDS)


def _looks_identity_selfhood_turn(query: str) -> bool:
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    return any(marker in normalized for marker in _IDENTITY_SELFHOOD_MARKERS)


def _iter_selfhood_context_chunks(state: object) -> list[str]:
    if not isinstance(state, dict):
        return []

    normalized_chunks: list[str] = []
    routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
    routing_meta = state.get("routing_metadata") if isinstance(state.get("routing_metadata"), dict) else {}
    hint_kind = str(routing_hint.get("kind") or "").strip().lower()
    routing_intent = str(routing_meta.get("intent") or "").strip().lower()
    if hint_kind in {"identity_probe", "selfhood_followup"} or routing_intent in {"identity", "selfhood"}:
        normalized_chunks.append("selfhood continuity")

    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    for key in ("conversation_summary", "conversation_history"):
        text = _normalize_for_intent(str(context.get(key) or ""))
        if text:
            normalized_chunks.append(text)

    for item in (context.get("history_list") or [])[-8:]:
        if isinstance(item, dict):
            text = str(item.get("content") or item.get("message") or item.get("text") or "")
        else:
            text = str(item or "")
        normalized = _normalize_for_intent(text)
        if normalized:
            normalized_chunks.append(normalized)

    for message in (context.get("langchain_messages") or [])[-8:]:
        content = getattr(message, "content", message)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = str(block.get("text") or block.get("content") or "")
                else:
                    text = str(block or "")
                normalized = _normalize_for_intent(text)
                if normalized:
                    normalized_chunks.append(normalized)
        else:
            normalized = _normalize_for_intent(str(content or ""))
            if normalized:
                normalized_chunks.append(normalized)
    return normalized_chunks


def _has_selfhood_context_signal(state: object) -> bool:
    context_blob = "\n".join(_iter_selfhood_context_chunks(state))
    if not context_blob:
        return False
    return any(marker in context_blob for marker in _SELFHOOD_CONTEXT_MARKERS)


def _looks_selfhood_followup_turn(query: str, state: object | None = None) -> bool:
    normalized = _normalize_for_intent(query)
    if not normalized or _looks_identity_selfhood_turn(query):
        return False

    tokens = [token for token in normalized.split() if token]
    if not tokens or len(tokens) > 12:
        return False

    if not any(marker in normalized for marker in _SELFHOOD_FOLLOWUP_MARKERS):
        return False

    return _has_selfhood_context_signal(state)


def _looks_emotional_support_turn(query: str) -> bool:
    """Detect short emotional-support turns that benefit from gentler direct handling."""
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    return any(marker in normalized for marker in _EMOTIONAL_SUPPORT_MARKERS)


def _needs_news_search(query: str) -> bool:
    """Detect if query needs news search (Sprint 102)."""
    normalized = _normalize_for_intent(query)
    return any(kw in normalized for kw in _NEWS_INTENT_KEYWORDS)


def _needs_legal_search(query: str) -> bool:
    """Detect if query needs legal search (Sprint 102)."""
    normalized = _normalize_for_intent(query)
    return any(kw in normalized for kw in _LEGAL_INTENT_KEYWORDS)


def _needs_maritime_search(query: str) -> bool:
    """Detect if query should expose the maritime-specific search path."""
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    return any(kw in normalized for kw in _MARITIME_INTENT_KEYWORDS)


def _needs_analysis_tool(query: str) -> bool:
    """Detect requests that should prefer Python/code execution tooling."""
    normalized = _normalize_for_intent(query)
    return any(kw in normalized for kw in _ANALYSIS_INTENT_KEYWORDS)


def _needs_code_studio(query: str) -> bool:
    """Detect requests that belong to the code studio capability lane."""
    normalized = _normalize_for_intent(query)
    return any(kw in normalized for kw in _CODE_STUDIO_INTENT_KEYWORDS)


def _needs_lms_query(query: str) -> bool:
    """Detect if query needs LMS data tools (Sprint 175)."""
    from app.core.config import settings as _s
    if not _s.enable_lms_integration:
        return False
    normalized = _normalize_for_intent(query)
    if any(kw in normalized for kw in _LMS_INTENT_KEYWORDS):
        return True
    return (
        any(kw in normalized for kw in _LMS_ASSESSMENT_KEYWORDS)
        and any(hint in normalized for hint in _LMS_CONTEXT_HINTS)
    )


def _needs_direct_knowledge_search(query: str) -> bool:
    """Detect explicit retrieval intent for the direct lane."""
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in _DIRECT_KNOWLEDGE_SEARCH_KEYWORDS)


# Wiii Pointy intent — only bind cursor-control tools when the user is
# asking to be SHOWN, not just told. Keeps the DIRECT prompt tight when
# the query is pure conversation / explanation.
_POINTY_INTENT_KEYWORDS: tuple[str, ...] = (
    # Vietnamese — diacritic-stripped forms
    "o dau", "cho nao", "chi cho", "chi vao", "chi giup", "chi dum",
    "dung pointy", "@wiii-pointy",
    "click vao dau", "nhan vao dau", "bam vao dau",
    "lam the nao de mo", "lam sao de mo", "lam the nao de bat",
    "huong dan toi", "huong dan minh", "chi minh",
    "tro vao", "tro toi", "tro giup",
    # English
    "where is", "show me how", "show me where", "point to",
    "highlight ", "click on the",
)


_POINTY_NEGATION_PATTERNS: tuple[str, ...] = (
    r"\bkhong\s+(?:can\s+)?(?:su\s+dung|dung|goi|kich\s+hoat|bat)\s+@?wiii[-\s]?pointy\b",
    r"\bdung\s+(?:su\s+dung|dung|goi|kich\s+hoat|bat)\s+@?wiii[-\s]?pointy\b",
    r"\b(?:khong|dung)\s+pointy\b",
    r"\b(?:no|without)\s+pointy\b",
    r"\bdo\s+not\s+use\s+pointy\b",
    r"\bdon'?t\s+use\s+pointy\b",
)


def _negates_pointy(query: str) -> bool:
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    return any(re.search(pattern, normalized) is not None for pattern in _POINTY_NEGATION_PATTERNS)


def _needs_pointy(query: str) -> bool:
    """Detect 'show me where / point to / how do I open X' intent.

    When this returns False, the DIRECT agent does NOT bind
    ``tool_pointy_show`` / ``tool_pointy_clear`` so the LLM prompt stays
    small. When True, the tools are bound and the wiii-pointy SKILL is
    injected into the system prompt.
    """
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    if _negates_pointy(query):
        return False
    return any(kw in normalized for kw in _POINTY_INTENT_KEYWORDS)


def _should_strip_visual_tools_from_direct(query: str, visual_decision) -> bool:
    """Keep plain quiz/study turns in direct prose unless the user explicitly asks for an app/widget."""
    if visual_decision.presentation_intent != "text":
        return False

    normalized = _normalize_for_intent(query)
    if not any(cue in normalized for cue in _PLAIN_QUIZ_LEARNING_CUES):
        return False

    return not any(cue in normalized for cue in _EXPLICIT_VISUAL_APP_CUES)
