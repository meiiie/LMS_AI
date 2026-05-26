"""Fast routing-hint and surface classification helpers for supervisor flows."""

from __future__ import annotations

import re

from app.engine.multi_agent.direct_node_chatter_runtime import (
    _looks_social_status_chatter_turn,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.direct_intent import _looks_selfhood_followup_turn
from app.engine.multi_agent.social_followup_policy import (
    looks_short_social_followup_turn,
)
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

_NORMALIZED_SOCIAL_PREFIXES = (
    "xin chao",
    "chao",
    "hello",
    "hi",
    "hey",
    "cam on",
    "thanks",
    "thank",
    "thank you",
    "tam biet",
    "bye",
    "goodbye",
    "hen gap lai",
)

_SOCIAL_LAUGH_TOKENS = {
    "he",
    "hehe",
    "hehehe",
    "ha",
    "haha",
    "hahaha",
    "hi",
    "hihi",
    "hihihi",
    "hoho",
    "kk",
    "kkk",
    "keke",
    "alo",
    "alooo",
}

_REACTION_TOKENS = {
    "wow",
    "woah",
    "whoa",
    "oa",
    "oaa",
    "oi",
    "oii",
    "ui",
    "uii",
    "uay",
    "uayy",
    "ah",
    "a",
    "oh",
    "hmm",
    "hm",
    "uh",
    "umm",
    "um",
    "uhm",
}

_VAGUE_BANTER_PHRASES = {
    "gi do",
    "cai gi do",
    "gi ay",
    "cai gi ay",
}

_HUNGER_CHATTER_MARKERS = (
    "doi phet",
    "doi qua",
    "hoi doi",
    "bung doi",
    "dang doi",
    "minh doi",
    "hungry",
    "starving",
)

_HUNGER_CHATTER_MEMORY_BLOCKERS = (
    "ghi nho",
    "hay nho",
    "luu lai",
    "nho rang",
    "trong phien nay",
)

_IDENTITY_PROBE_MARKERS = (
    "ban la ai",
    "ban ten gi",
    "ten gi",
    "ten cua ban",
    "wiii la ai",
    "wiii ten gi",
    "cuoc song the nao",
    "cuoc song cua ban",
    "song the nao",
    "gioi thieu ve ban",
)

_FAST_CHATTER_BLOCKERS = (
    "tai sao",
    "la gi",
    "the nao",
    "giai thich",
    "huong dan",
    "tra cuu",
    "quy dinh",
    "tin tuc",
    "search",
    "tim",
    "mo phong",
    "simulation",
    "canvas",
    "chart",
    "code",
    "python",
    "javascript",
    "html",
    "css",
    "react",
    "excel",
    "word",
    "pdf",
    "bao nhieu",
    "o dau",
    "nhu nao",
    "phan tich",
    "so sanh",
    "thay doi",
    "viet",
)

_ROUTING_ARTIFACT_MARKERS = (
    "```",
    "<!doctype",
    "<html",
    "<body",
    "<div",
    "<svg",
    "function ",
    "const ",
    "let ",
    "class ",
    "import ",
    "export ",
    "visual_session_id",
    '"type": "visual"',
)

_FAST_WEB_KEYWORDS = [
    "tim tren web",
    "tim tren mang",
    "tim tren internet",
    "search",
    "tin tuc",
    "moi nhat",
    "hom nay",
    "nghi dinh",
    "thong tu",
    "van ban phap luat",
    "maritime news",
    "shipping news",
]

_FAST_PRODUCT_KEYWORDS = [
    "shopee",
    "lazada",
    "tiktok shop",
    "facebook marketplace",
    "google shopping",
    "mua",
    "tim san pham",
    "so sanh gia",
    "gia re nhat",
    "mua o dau",
]


def _normalize_router_text_impl(text: str) -> str:
    lowered = " ".join((text or "").lower().split())
    try:
        from app.engine.content_filter import TextNormalizer

        return TextNormalizer.strip_diacritics(lowered)
    except Exception:
        import unicodedata

        nfkd = unicodedata.normalize("NFD", lowered)
        return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


def _contains_router_phrase(normalized: str, phrase: str) -> bool:
    """Match routing cues as standalone words/phrases, not substrings."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized) is not None


def _needs_code_studio_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    decision = resolve_visual_intent(query)
    if decision.presentation_intent in {"code_studio_app", "artifact"}:
        if "quiz" in normalized and not any(
            keyword in normalized
            for keyword in (
                "widget",
                "app",
                "html",
                "interactive",
                "artifact",
                "javascript",
                "canvas",
                "svg",
                "mini tool",
            )
        ):
            return False
        return True
    narrowed_keywords = (
        "python",
        "code",
        "viet code",
        "chay code",
        "javascript",
        "typescript",
        "html",
        "css",
        "react",
        "landing page",
        "website",
        "web app",
        "microsite",
        "artifact",
        "sandbox",
        "excel",
        "xlsx",
        "spreadsheet",
        "word",
        "docx",
        "report",
        "memo",
        "proposal",
        "screenshot",
        "browser sandbox",
    )
    return any(_contains_router_phrase(normalized, kw) for kw in narrowed_keywords)


def _looks_clear_social_impl(normalized: str) -> bool:
    if len(normalized.split()) > 6:
        return False
    if any(marker in normalized for marker in ("giai thich", "explain", "quy dinh", "mo phong", "ve bieu do")):
        return False
    if (
        _looks_clear_learning_turn_impl(normalized)
        or _looks_clear_web_intent_impl(normalized)
        or _looks_clear_product_intent_impl(normalized)
    ):
        return False
    normalized = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", normalized)).strip()
    letters_only = re.sub(r"[^a-z]", "", normalized)
    tokens = [token for token in normalized.split() if token]
    if tokens and len(tokens) <= 4 and all(token in _SOCIAL_LAUGH_TOKENS for token in tokens):
        return True
    if letters_only and re.fullmatch(r"(he|ha|hi|ho|kk|alo){1,6}", letters_only):
        return True
    if letters_only.startswith(
        (
            "xinch",
            "chao",
            "hello",
            "hi",
            "hey",
            "cam",
            "thank",
            "thanks",
            "tambiet",
            "bye",
            "goodbye",
            "hengaplai",
        )
    ):
        return True
    return any(normalized == keyword or normalized.startswith(f"{keyword} ") for keyword in _NORMALIZED_SOCIAL_PREFIXES)


def _looks_hunger_chatter_impl(normalized: str) -> bool:
    """Detect short hunger chatter so it does not wait on LLM routing."""
    query = normalized or ""
    if not query:
        return False
    if any(marker in query for marker in _HUNGER_CHATTER_MEMORY_BLOCKERS):
        return False
    if any(marker in query for marker in _FAST_CHATTER_BLOCKERS):
        return False
    tokens = [token for token in re.sub(r"[^\w\s]", " ", query).split() if token]
    # Realistic smoke prompts often carry a marker plus "answer naturally/no
    # tool" instructions. Keep those obvious hunger/social turns off RAG.
    if len(tokens) > 40:
        return False
    return any(_contains_router_phrase(query, marker) for marker in _HUNGER_CHATTER_MARKERS)


def is_obvious_social_turn_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    return (
        _looks_clear_social_impl(normalized)
        or _looks_hunger_chatter_impl(normalized)
        or looks_short_social_followup_turn(normalized)
    )


def classify_fast_chatter_turn_impl(query: str) -> tuple[str, str] | None:
    normalized = _normalize_router_text_impl(query)
    if not normalized:
        return None
    if any(marker in normalized for marker in _FAST_CHATTER_BLOCKERS):
        return None
    if _looks_hunger_chatter_impl(normalized):
        return ("social", "hunger_chatter")
    if _looks_social_status_chatter_turn(normalized):
        return ("social", "social_status")
    if looks_short_social_followup_turn(normalized):
        return ("social", "social_followup")
    if _looks_clear_social_impl(normalized):
        return ("social", "social")
    tokens = [token for token in re.sub(r"[^\w\s]", " ", normalized).split() if token]
    if tokens and len(tokens) <= 3 and all(token in _REACTION_TOKENS for token in tokens):
        return ("social", "reaction")
    if normalized in _VAGUE_BANTER_PHRASES:
        return ("off_topic", "vague_banter")
    return None


def _looks_identity_probe_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    if not normalized:
        return False
    if any(marker in normalized for marker in _IDENTITY_PROBE_MARKERS):
        return True
    tokens = [token for token in re.sub(r"[^\w\s]", " ", normalized).split() if token]
    return bool(tokens) and len(tokens) <= 8 and normalized in {
        "ban la ai",
        "ten gi",
        "ten cua ban",
        "wiii la ai",
        "wiii ten gi",
        "cuoc song the nao",
    }


def _looks_short_capability_probe_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    tokens = [token for token in normalized.split() if token]
    if not tokens or len(tokens) > 10:
        return False
    if not any(
        marker in normalized
        for marker in ("duoc", "khong", "co the", "chua", "sao", "mo phong", "simulation", "canvas", "widget", "app", "artifact")
    ):
        return False
    return _needs_code_studio_impl(query) or any(
        marker in normalized for marker in ("mo phong", "simulation", "canvas", "widget", "app", "artifact")
    )


def _looks_like_visual_data_request_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    if not normalized:
        return False
    visual_markers = ("visual", "bieu do", "chart", "do thi", "thong ke", "so lieu", "du lieu", "xu huong")
    data_markers = (
        "gia ",
        "gia dau",
        "hien tai",
        "hom nay",
        "moi nhat",
        "ngay gan day",
        "gan day",
        "recent",
        "latest",
        "trend",
        "so sanh",
    )
    blockers = (
        "mo phong",
        "simulation",
        "canvas",
        "widget",
        "app",
        "artifact",
        "html",
        "excel",
        "word",
        "pdf",
        "python",
        "javascript",
        "typescript",
        "file",
        "xuat file",
        "tai file",
    )
    if any(marker in normalized for marker in blockers):
        return False
    return any(marker in normalized for marker in visual_markers) and any(marker in normalized for marker in data_markers)


def _looks_like_short_natural_question_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    tokens = [token for token in normalized.split() if token]
    if not tokens or len(tokens) > 10:
        return False
    question_markers = (
        "?",
        "co the",
        "duoc khong",
        "duoc ko",
        "khong",
        "sao",
        "the nao",
        "tai sao",
        "lam sao",
        "nen khong",
        "co nen",
        "co phai",
        "hay khong",
        "co the nao",
        "nen",
        "neu",
    )
    return any(marker in normalized for marker in question_markers)


def _looks_visual_followup_request_impl(query: str) -> bool:
    normalized = _normalize_router_text_impl(query)
    tokens = [token for token in normalized.split() if token]
    if not tokens or len(tokens) > 12:
        return False
    visual_markers = (
        "visual",
        "minh hoa",
        "so do",
        "bieu do",
        "ve cho",
        "tao visual",
        "tao hinh",
    )
    followup_markers = (
        "duoc chu",
        "duoc khong",
        "cho minh xem",
        "xem duoc",
        "cho de hinh dung",
    )
    if not any(marker in normalized for marker in visual_markers):
        return False
    return any(marker in normalized for marker in followup_markers)


def _has_domain_learning_context_signal_impl(state: AgentState) -> bool:
    context = state.get("context", {}) or {}
    context_parts: list[str] = []
    summary = _normalize_router_text_impl(str(context.get("conversation_summary", "") or ""))
    if summary:
        context_parts.append(summary)
    conversation_history = _normalize_router_text_impl(str(context.get("conversation_history", "") or ""))
    if conversation_history:
        context_parts.append(conversation_history)

    for item in (context.get("history_list") or [])[-6:]:
        if not isinstance(item, dict):
            normalized = _normalize_router_text_impl(str(item or ""))
            if normalized:
                context_parts.append(normalized)
            continue
        normalized = _normalize_router_text_impl(
            str(item.get("content") or item.get("message") or item.get("text") or "")
        )
        if normalized:
            context_parts.append(normalized)

    for message in (context.get("langchain_messages") or [])[-6:]:
        content = getattr(message, "content", message)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = str(block.get("text") or block.get("content") or "")
                else:
                    text = str(block or "")
                normalized = _normalize_router_text_impl(text)
                if normalized:
                    context_parts.append(normalized)
        else:
            normalized = _normalize_router_text_impl(str(content or ""))
            if normalized:
                context_parts.append(normalized)

    context_blob = "\n".join(context_parts)
    if any(
        marker in context_blob
        for marker in (
            "giai thich",
            "nguoi hoc",
            "quy tac",
            "rule ",
            "colregs",
            "solas",
            "marpol",
            "phan biet",
            "bai hoc",
            "cat huong",
            "tranh va",
        )
    ):
        return True

    raw_keywords = (state.get("domain_config", {}) or {}).get("routing_keywords") or []
    flattened_keywords: list[str] = []
    for item in raw_keywords:
        parts = str(item or "").split(",")
        flattened_keywords.extend(
            _normalize_router_text_impl(part.strip())
            for part in parts
            if part.strip()
        )
    return any(keyword and keyword in context_blob for keyword in flattened_keywords)


def _should_use_compact_routing_prompt_impl(query: str, fast_chatter_hint: tuple[str, str] | None) -> bool:
    normalized = _normalize_router_text_impl(query)
    token_count = len([token for token in normalized.split() if token])
    if fast_chatter_hint is not None:
        return True
    if _looks_short_capability_probe_impl(query):
        return True
    if _looks_like_short_natural_question_impl(query):
        return False
    return 0 < token_count <= 4


def _apply_routing_hint_impl(state: AgentState, query: str) -> dict[str, str]:
    if _looks_identity_probe_impl(query):
        hint = {"kind": "identity_probe", "intent": "selfhood", "shape": "identity"}
        state["_routing_hint"] = hint
        return hint
    if _looks_selfhood_followup_turn(query, state):
        hint = {"kind": "selfhood_followup", "intent": "selfhood", "shape": "lore_followup"}
        state["_routing_hint"] = hint
        return hint
    if _looks_visual_followup_request_impl(query) and _has_domain_learning_context_signal_impl(state):
        hint = {"kind": "visual_followup", "intent": "learning", "shape": "visual_followup"}
        state["_routing_hint"] = hint
        return hint
    fast_chatter = classify_fast_chatter_turn_impl(query)
    if fast_chatter is not None:
        hint = {"kind": "fast_chatter", "intent": fast_chatter[0], "shape": fast_chatter[1]}
        state["_routing_hint"] = hint
        return hint
    if _looks_short_capability_probe_impl(query):
        hint = {
            "kind": "capability_probe",
            "intent": "code_execution" if _needs_code_studio_impl(query) else "unknown",
            "shape": "short_probe",
        }
        state["_routing_hint"] = hint
        return hint
    state.pop("_routing_hint", None)
    return {}


def _looks_like_artifact_payload_impl(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if len(normalized) > 320 and normalized.count("\n") >= 8:
        return True
    return any(marker in normalized for marker in _ROUTING_ARTIFACT_MARKERS)


def _looks_clear_web_intent_impl(normalized: str) -> bool:
    if any(marker in normalized for marker in ("quiz", "giai thich", "on bai", "mo phong")):
        return False
    return any(keyword in normalized for keyword in _FAST_WEB_KEYWORDS)


def _looks_clear_product_intent_impl(normalized: str) -> bool:
    if any(marker in normalized for marker in ("code", "html", "svg", "canvas", "python")):
        return False
    return any(keyword in normalized for keyword in _FAST_PRODUCT_KEYWORDS)


def _looks_clear_learning_turn_impl(normalized: str) -> bool:
    if any(
        marker in normalized
        for marker in (
            "widget",
            "mini app",
            "mini tool",
            "interactive quiz",
            "quiz widget",
            "quiz app",
            "html quiz",
            "artifact",
            "canvas",
            "svg",
            "javascript",
            "react",
            "python",
            "code",
        )
    ):
        return False
    return any(
        marker in normalized
        for marker in (
            "quiz",
            "quizz",
            "trac nghiem",
            "luyen tap",
            "on tap",
            "flashcard",
            "bai tap",
            "practice",
            "learn",
            "hoc ",
            "giai thich",
            "day minh",
            "day toi",
            "huong dan",
        )
    )
