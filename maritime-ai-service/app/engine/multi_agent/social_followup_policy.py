"""Shared policy for short social follow-up turns.

These turns are not greetings, but they are still ordinary chat: the user is
reacting to the previous assistant message and is not asking for tools, RAG, or
host actions. Keeping this policy shared prevents the supervisor fast-path and
the direct tool governor from drifting.
"""

from __future__ import annotations

import re

from app.engine.multi_agent.direct_text_utils import _fold_direct_text


_EXACT_SHORT_SOCIAL_FOLLOWUPS = frozenset(
    {
        "ngu di",
        "the ngu di",
        "sao lai",
        "sao lai z",
        "sao lai vay",
        "sao lai the",
        "sao vay",
        "sao the",
        "sao lo lung",
        "la sao",
        "la sao z",
        "la sao vay",
        "noi de",
        "noi di",
        "noi tiep di",
        "vay la sao",
        "vay ha",
        "vay a",
        "the ha",
        "the a",
    }
)

_SAFE_SAO_LAI_TAILS = frozenset(
    {
        "z",
        "v",
        "vay",
        "the",
        "ha",
        "a",
        "nhi",
        "ta",
        "vay nhi",
        "vay ta",
    }
)

_TASK_OR_TOOL_BLOCKERS = (
    "assignment",
    "bai hoc",
    "bao cao",
    "bao do",
    "chart",
    "click",
    "code",
    "colreg",
    "css",
    "deadline",
    "deploy",
    "diem",
    "docker",
    "docx",
    "excel",
    "file",
    "fix",
    "giai thich",
    "gia",
    "hang hai",
    "html",
    "huong dan",
    "javascript",
    "kiem tra",
    "legal",
    "lms",
    "log",
    "marpol",
    "mo phong",
    "news",
    "nhiet do",
    "pdf",
    "phan tich",
    "python",
    "quy dinh",
    "quy tac",
    "react",
    "rule",
    "search",
    "so sanh",
    "solas",
    "sua",
    "tai lieu",
    "tao",
    "tau",
    "test",
    "thoi tiet",
    "tin tuc",
    "tim",
    "tra cuu",
    "ve",
    "viet",
    "weather",
    "word",
)


def _clean_social_followup_text(value: str) -> str:
    folded = _fold_direct_text(value)
    return " ".join(re.sub(r"[^\w\s]", " ", folded).split())


def _contains_phrase(haystack: str, phrase: str) -> bool:
    if " " in phrase:
        return phrase in haystack
    return f" {phrase} " in f" {haystack} "


def looks_short_social_followup_turn(query: str) -> bool:
    """Return True for short, no-tool follow-ups to the previous message."""

    normalized = _clean_social_followup_text(query)
    if not normalized:
        return False

    tokens = [token for token in normalized.split() if token]
    if len(tokens) > 6:
        return False

    if any(_contains_phrase(normalized, blocker) for blocker in _TASK_OR_TOOL_BLOCKERS):
        return False

    if normalized in _EXACT_SHORT_SOCIAL_FOLLOWUPS:
        return True

    if normalized.startswith("sao lai "):
        tail = normalized.removeprefix("sao lai ").strip()
        return tail in _SAFE_SAO_LAI_TAILS

    return False


__all__ = ["looks_short_social_followup_turn"]
