from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

QUALITY_PROFILE_ORDER: dict[str, int] = {
    "draft": 0,
    "standard": 1,
    "premium": 2,
}

THINKING_EFFORT_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "max": 3,
}

LEGACY_VISUAL_TOOL_NAMES = frozenset({
    "tool_generate_interactive_chart",
    "tool_generate_chart",
    "tool_generate_mermaid",
})

VISUAL_PATCH_KEYWORDS = (
    "highlight",
    "focus on",
    "focus only",
    "bottleneck",
    "giu cung visual",
    "giu nguyen visual",
    "same visual",
    "same visual session",
    "keep the same visual",
    "reuse visual",
    "update visual",
    "patch visual",
    "modify visual",
    "change this visual",
    "annotate",
    "them annotation",
    "lam ro",
    "nhan manh",
    "chi show",
    "chi hien thi",
    "doi thanh 3 buoc",
    "doi thanh",
    "bien thanh",
    "thanh 3 buoc",
    "so do nay",
    "turn this into",
    "convert this visual",
    "filter",
    "loc theo",
    "zoom in",
    "giu app hien tai",
    "giu mini app hien tai",
    "giu widget hien tai",
    "keep the current app",
    "keep the same app",
    "keep the current widget",
    "keep the same widget",
    "update the app",
    "modify the app",
    "change the app",
    "change background",
    "change the background",
    "doi mau nen",
    "doi background",
    "them slider",
    "bo sung slider",
    "them dieu khien",
    "cap nhat app",
)

VISUAL_PATCH_PREFIXES = (
    "giu ",
    "them ",
    "doi ",
    "sua ",
    "chinh sua ",
    "cap nhat ",
    "bo sung ",
    "nang cap ",
    "lam ro ",
    "highlight ",
    "annotate ",
    "make ",
    "change ",
    "update ",
    "modify ",
    "add ",
    "turn ",
)

SIMULATION_PATCH_CUES = (
    "con lac",
    "pendulum",
    "vat ly",
    "physics",
    "trong luc",
    "ma sat",
    "keo tha",
    "drag",
    "goc lech",
    "van toc",
    "do thi thoi gian",
    "rule 15",
    "colregs",
    "tau",
    "ship",
)

SIMULATION_APP_CUES = (
    "pendulum",
    "physics app",
    "physics simulation",
    "drag interaction",
    "drag physics",
    "gravity slider",
    "damping slider",
    "con lac",
    "vat ly",
    "keo tha",
)

SCENE_SIMULATION_CUES = (
    "mo phong canh",
    "tai hien canh",
    "dung canh",
    "khung canh",
    "tai hien",
    "recreate scene",
    "scene reconstruction",
    "visual scene",
    "van hoc",
    "nhan vat",
)

QUIZ_WIDGET_CUES = (
    "quiz widget",
    "quiz app",
    "interactive quiz",
    "quiz interactive",
    "trac nghiem tuong tac",
    "bai quiz tuong tac",
    "widget quiz",
    "html quiz",
    "mini quiz app",
)

DASHBOARD_APP_CUES = (
    "dashboard",
    "dashboard app",
    "analytics",
    "bang dieu khien",
)

MINI_TOOL_CUES = (
    "mini tool",
    "interactive tool",
    "calculator",
    "tinh toan",
    "tool nho",
)

INTERACTIVE_TABLE_CUES = (
    "interactive table",
    "bang tuong tac",
    "filter table",
    "sortable table",
)

SEARCH_WIDGET_CUES = (
    "search widget",
    "search tool",
    "widget tim kiem",
    "cong cu tim kiem",
)

CODE_WIDGET_CUES = (
    "code widget",
    "code editor",
    "snippet",
    "playground",
    "code playground",
)

QUIZ_CREATION_CUES = (
    "tao",
    "lam",
    "dung",
    "xay",
    "soan",
    "thiet ke",
    "build",
    "create",
    "generate",
)

QUIZ_REQUEST_CUES = (
    "quiz",
    "quizz",
    "trac nghiem",
    "bai quiz",
    "bo quiz",
)

QUIZ_CREATION_RAW_CUES = (
    "tạo",
    "làm",
    "dựng",
    "xây",
    "soạn",
    "thiết kế",
    "build",
    "create",
    "generate",
)

QUIZ_REQUEST_RAW_CUES = (
    "quiz",
    "quizz",
    "trắc nghiệm",
    "bài quiz",
    "bộ quiz",
)


def normalize_impl(text: str) -> str:
    normalized = (text or "").strip().lower()
    if not normalized:
        return ""

    normalized = normalized.replace("đ", "d").replace("ð", "d")
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9\s/+.-]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def contains_any_impl(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def metadata_value_impl(source: dict[str, Any] | None, *keys: str) -> str:
    if not isinstance(source, dict):
        return ""
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def merge_quality_profile_impl(*values: Any) -> str:
    best = ""
    best_rank = -1
    for value in values:
        candidate = str(value or "").strip().lower()
        rank = QUALITY_PROFILE_ORDER.get(candidate)
        if rank is None:
            continue
        if rank > best_rank:
            best = candidate
            best_rank = rank
    return best or "standard"


def merge_thinking_effort_impl(base: str | None, recommended: str | None) -> str | None:
    base_value = str(base or "").strip().lower()
    recommended_value = str(recommended or "").strip().lower()

    if base_value not in THINKING_EFFORT_ORDER:
        return recommended_value or None
    if recommended_value not in THINKING_EFFORT_ORDER:
        return base_value
    if THINKING_EFFORT_ORDER[recommended_value] > THINKING_EFFORT_ORDER[base_value]:
        return recommended_value
    return base_value


def looks_like_quiz_app_request_impl(
    query: str,
    normalized: str,
    *,
    contains_any: Callable[[str, tuple[str, ...]], bool],
) -> bool:
    if not query and not normalized:
        return False
    raw_lower = query.lower().strip()
    has_quiz_request = contains_any(normalized, QUIZ_REQUEST_CUES) or contains_any(raw_lower, QUIZ_REQUEST_RAW_CUES)
    has_creation_intent = contains_any(normalized, QUIZ_CREATION_CUES) or contains_any(raw_lower, QUIZ_CREATION_RAW_CUES)
    return has_quiz_request and has_creation_intent


def looks_like_recipe_backed_simulation_impl(
    normalized: str,
    *,
    contains_any: Callable[[str, tuple[str, ...]], bool],
) -> bool:
    return contains_any(
        normalized,
        SIMULATION_APP_CUES + SIMULATION_PATCH_CUES + SCENE_SIMULATION_CUES,
    )


def detect_visual_patch_request_impl(
    query: str,
    *,
    normalize: Callable[[str], str],
    contains_any: Callable[[str, tuple[str, ...]], bool],
) -> bool:
    normalized = normalize(query)
    if not normalized:
        return False
    if contains_any(normalized, VISUAL_PATCH_KEYWORDS):
        return True
    return normalized.startswith(VISUAL_PATCH_PREFIXES)


def looks_like_app_followup_patch_impl(
    normalized: str,
    *,
    contains_any: Callable[[str, tuple[str, ...]], bool],
    detect_visual_patch_request: Callable[[str], bool],
) -> bool:
    if not normalized:
        return False
    if not detect_visual_patch_request(normalized):
        return False
    return contains_any(
        normalized,
        (
            " app ",
            "app hien tai",
            "same app",
            "current app",
            "widget",
            "slider",
            "trong luc",
            "ma sat",
            "drag",
            "keo tha",
            "preview",
            "background",
            "mau nen",
            "code studio",
            "goc lech",
            "van toc",
            "pendulum",
            "con lac",
        ),
    )


def infer_followup_simulation_type_impl(
    normalized: str,
    *,
    contains_any: Callable[[str, tuple[str, ...]], bool],
) -> str | None:
    return "simulation" if contains_any(normalized, SIMULATION_PATCH_CUES) else None


def infer_figure_budget_impl(
    normalized: str,
    *,
    visual_type: str | None,
    presentation_intent: str,
    contains_any: Callable[[str, tuple[str, ...]], bool],
) -> int:
    if presentation_intent in {"text", "code_studio_app", "artifact"}:
        return 1

    if presentation_intent == "chart_runtime":
        if contains_any(normalized, ("explain in charts", "explain with charts", "giai thich", "step by step")):
            return 2
        return 1

    if presentation_intent == "article_figure":
        if contains_any(
            normalized,
            (
                "explain in charts",
                "explain with charts",
                "step by step",
                "giai thich",
                "co che",
                "trade off",
                "benchmark",
                "kien truc",
            ),
        ):
            return 3 if visual_type in {"chart", "comparison", "architecture"} else 2
        if visual_type in {"comparison", "process", "architecture", "concept", "chart"}:
            return 2

    return 1
