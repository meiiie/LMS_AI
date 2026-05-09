"""Support helpers for the input processor shell."""

from __future__ import annotations

import re
from typing import Any, Optional


_NAME_PATTERNS = [
    r"t\u00ean (?:l\u00e0|t\u00f4i l\u00e0|m\u00ecnh l\u00e0|em l\u00e0)\s+(\w+)",
    r"m\u00ecnh t\u00ean l\u00e0\s+(\w+)",
    r"(?:t\u00f4i|m\u00ecnh|em) l\u00e0\s+(\w+)",
    r"(?:t\u00f4i|m\u00ecnh|em) t\u00ean\s+(\w+)",
    r"g\u1ecdi (?:t\u00f4i|m\u00ecnh|em) l\u00e0\s+(\w+)",
    r"t\u00ean\s+(\w+)",
    r"(?:i'm|i am|my name is|call me)\s+(\w+)",
]

_NOT_NAMES = {
    "l\u00e0",
    "t\u00f4i",
    "m\u00ecnh",
    "em",
    "anh",
    "ch\u1ecb",
    "b\u1ea1n",
    "the",
    "a",
    "an",
    "g\u00ec",
    "\u0111\u00e2y",
    "n\u00e0y",
    "kia",
    "h\u1ecdc",
    "sinh",
    "vi\u00ean",
    "gi\u00e1o",
    "s\u01b0",
}

_NAME_CONTEXT_BLOCKERS = {
    "cho",
    "c\u1ee7a",
    "theo",
    "v\u1edbi",
}


def _previous_word(message_lower: str, index: int) -> str:
    prefix = message_lower[:index].rstrip()
    match = re.search(r"([\w\u00c0-\u1ef9]+)$", prefix, re.IGNORECASE)
    return match.group(1) if match else ""


def extract_user_name_impl(message: str) -> Optional[str]:
    message_lower = message.lower()
    for pattern in _NAME_PATTERNS:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if not match:
            continue
        if _previous_word(message_lower, match.start()).lower() in _NAME_CONTEXT_BLOCKERS:
            continue
        name = match.group(1).capitalize()
        if name.lower() not in _NOT_NAMES:
            return name
    return None


async def validate_pronoun_request_impl(
    *,
    guardian_agent: Any,
    message: str,
    logger: Any,
) -> Optional[dict]:
    if not guardian_agent:
        return None

    try:
        pronoun_result = await guardian_agent.validate_pronoun_request(message)
        if pronoun_result.approved:
            return {
                "user_called": pronoun_result.user_called,
                "ai_self": pronoun_result.ai_self,
            }
    except Exception as exc:
        logger.warning("Failed to validate pronoun request: %s", exc)

    return None
