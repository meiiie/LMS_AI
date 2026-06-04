"""Living sentiment post-response scheduling helpers.

This module isolates the scheduling of Living continuity sentiment work from
the broader continuity contract while preserving the sentiment analysis
implementation where legacy compatibility tests still expect it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Awaitable, Callable

from app.core.config import settings
from app.services.living_continuity_contracts import (
    PostResponseContinuityContext,
)

logger = logging.getLogger(__name__)

__all__ = ["schedule_living_sentiment_continuity"]


def _fold_sentiment_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    without_marks = without_marks.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"\s+", " ", without_marks.lower()).strip()


def _is_low_value_sentiment_turn(context: PostResponseContinuityContext) -> bool:
    folded = _fold_sentiment_text(context.message)
    if not folded:
        return False
    if "trong phien nay" in folded and any(
        marker in folded for marker in ("hay nho", "ghi nho", "luu lai")
    ):
        return True
    if "vua bao" in folded and "nho" in folded:
        return True
    if any(marker in folded for marker in ("doi phet", "doi qua", "dang doi")):
        return True
    if "wiii" in folded and any(
        marker in folded
        for marker in ("xu ly duoc anh", "tao anh", "file word", "excel", "video")
    ):
        return True
    if any(marker in folded for marker in ("visible thinking", "chain-of-thought")):
        return True
    return False


def schedule_living_sentiment_continuity(
    context: PostResponseContinuityContext,
    *,
    analyze_and_process_sentiment: Callable[..., Awaitable[None]],
) -> bool:
    """Schedule Living continuity sentiment processing when enabled."""
    if not getattr(settings, "enable_living_continuity", False):
        return False
    if _is_low_value_sentiment_turn(context):
        return False

    try:
        asyncio.ensure_future(
            analyze_and_process_sentiment(
                user_id=context.user_id,
                user_role=context.user_role,
                message=context.message,
                response_text=context.response_text,
                organization_id=context.organization_id,
                session_id=context.session_id,
            )
        )
        return True
    except Exception as exc:
        logger.debug("[CONTINUITY] Living sentiment schedule failed: %s", exc)
        return False
