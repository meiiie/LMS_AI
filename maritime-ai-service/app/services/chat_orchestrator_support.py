"""Support helpers for ChatOrchestrator side-effect orchestration."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Callable, Optional

from app.services.post_turn_lifecycle import (
    PostTurnLifecycleContext,
    schedule_post_turn_lifecycle,
)


logger = logging.getLogger(__name__)


def _fold_post_response_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    without_marks = without_marks.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"\s+", " ", without_marks.lower()).strip()


def _is_ephemeral_direct_post_response_turn(
    *,
    current_agent: str,
    message: str,
) -> bool:
    agent = str(current_agent or "").strip().lower()
    if agent != "direct":
        return False

    folded = _fold_post_response_text(message)
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
    if any(
        marker in folded
        for marker in (
            "ban buon khong",
            "wiii buon khong",
            "ban co buon khong",
            "wiii co buon khong",
        )
    ):
        return True
    if "wiii" in folded and any(
        marker in folded
        for marker in ("xu ly duoc anh", "tao anh", "file word", "excel", "video")
    ):
        return True
    if any(marker in folded for marker in ("visible thinking", "chain-of-thought")):
        return True

    return False


def should_skip_post_response_fact_extraction_impl(
    *,
    current_agent: str,
    message: str,
) -> bool:
    """Avoid costly durable extraction for ephemeral deterministic direct turns."""
    agent = str(current_agent or "").strip().lower()
    if agent == "memory_agent":
        return True
    return _is_ephemeral_direct_post_response_turn(
        current_agent=current_agent,
        message=message,
    )


def finalize_response_turn_impl(
    *,
    logger_obj: Any,
    session_manager: Any,
    persist_chat_message: Callable[..., None],
    upsert_thread_view: Callable[..., None],
    background_runner: Any,
    post_response_context_cls: Any,
    schedule_post_response_continuity_fn: Callable[..., Any],
    session_id: Any,
    user_id: str,
    user_role: Any,
    message: str,
    response_text: str,
    context: Any,
    domain_id: str | None,
    organization_id: str | None,
    current_agent: str,
    background_save: Optional[Callable],
    save_response_immediately: bool,
    include_lms_insights: bool,
    continuity_channel: str,
    transport_type: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run post-response continuity, persistence, and thread sync."""
    used_name = (
        bool(context and context.user_name)
        and context.user_name.lower() in response_text.lower()
    ) if response_text else False
    opening = response_text[:50].strip() if response_text else None
    session_manager.update_state(
        session_id=session_id,
        phrase=opening,
        used_name=used_name,
        organization_id=organization_id,
    )

    persist_chat_message(
        session_id=session_id,
        role="assistant",
        content=response_text,
        user_id=user_id,
        organization_id=organization_id,
        background_save=background_save,
        immediate=save_response_immediately,
    )
    session_manager.append_message(
        session_id=session_id,
        role="assistant",
        content=response_text,
        organization_id=organization_id,
    )

    if response_text:
        if (
            transport_type == "stream"
            and background_save is not None
            and not save_response_immediately
        ):
            background_save(
                upsert_thread_view,
                user_id=user_id,
                session_id=session_id,
                domain_id=domain_id,
                title=message,
                organization_id=organization_id,
            )
        else:
            upsert_thread_view(
                user_id=user_id,
                session_id=session_id,
                domain_id=domain_id,
                title=message,
                organization_id=organization_id,
            )

    ephemeral_direct_turn = _is_ephemeral_direct_post_response_turn(
        current_agent=current_agent,
        message=message,
    )
    skip_fact_extraction = should_skip_post_response_fact_extraction_impl(
        current_agent=current_agent,
        message=message,
    )
    post_turn_lifecycle = schedule_post_turn_lifecycle(
        PostTurnLifecycleContext(
            background_save=background_save,
            background_runner=background_runner,
            user_id=user_id,
            session_id=session_id,
            message=message,
            response_text=response_text,
            organization_id=organization_id,
            transport_type=transport_type,
            skip_fact_extraction=skip_fact_extraction,
            ephemeral_direct_turn=ephemeral_direct_turn,
        )
    )
    background_tasks_scheduled = post_turn_lifecycle.background_tasks_scheduled

    include_lms_insights_for_turn = include_lms_insights and not ephemeral_direct_turn

    scheduled_hooks = schedule_post_response_continuity_fn(
        post_response_context_cls(
            user_id=user_id,
            user_role=user_role,
            message=message,
            response_text=response_text,
            session_id=str(session_id) if session_id else None,
            request_id=request_id,
            domain_id=domain_id or "",
            organization_id=organization_id,
            channel=continuity_channel,
        ),
        include_lms_insights=include_lms_insights_for_turn,
    )

    continuity_summary = {
        "session_id": str(session_id),
        "request_id": str(request_id or ""),
        "user_id": str(user_id),
        "domain_id": domain_id or "",
        "organization_id": organization_id or "",
        "transport_type": transport_type,
        "continuity_channel": continuity_channel,
        "include_lms_insights": include_lms_insights_for_turn,
        "scheduled_hooks": list(scheduled_hooks),
        "background_tasks_scheduled": background_tasks_scheduled,
        "post_turn_lifecycle": post_turn_lifecycle.to_summary(),
        "response_persistence": (
            "immediate"
            if save_response_immediately or background_save is None
            else "background"
        ),
    }
    logger_obj.info(
        "[CONTINUITY] Finalized turn summary: %s",
        json.dumps(continuity_summary, sort_keys=True),
    )
    return post_turn_lifecycle.to_summary()


def load_pronoun_style_from_facts_impl(
    *,
    semantic_memory: Any,
    session: Any,
    user_id: str,
) -> None:
    """Load persisted pronoun style from semantic memory."""
    try:
        if not semantic_memory or not semantic_memory.is_available():
            return

        from app.models.semantic_memory import MemoryType
        from app.repositories.semantic_memory_repository import (
            get_semantic_memory_repository,
        )

        repo = get_semantic_memory_repository()
        if not repo.is_available():
            return

        results = repo.get_memories_by_type(
            user_id=user_id,
            memory_type=MemoryType.USER_FACT,
            limit=10,
        )
        for memory in results:
            metadata = memory.metadata or {}
            if metadata.get("fact_type") != "pronoun_style":
                continue

            content = memory.content
            value = content.split(": ", 1)[-1] if ": " in content else content
            pronoun_dict = json.loads(value)
            session.state.update_pronoun_style(pronoun_dict)
            logger.debug("[SPRINT79] Loaded pronoun_style from facts for %s", user_id)
            return
    except Exception as exc:
        logger.debug("Failed to load pronoun style from facts: %s", exc)


def persist_pronoun_style_impl(
    *,
    background_save: Callable,
    user_id: str,
    pronoun_style: dict,
) -> None:
    """Store detected pronoun style as a semantic triple in the background."""
    pronoun_str = json.dumps(pronoun_style, ensure_ascii=False)

    def _store() -> None:
        try:
            from app.models.semantic_memory import Predicate, SemanticTriple
            from app.repositories.semantic_memory_repository import (
                get_semantic_memory_repository,
            )

            repo = get_semantic_memory_repository()
            if not repo.is_available():
                return

            triple = SemanticTriple(
                subject=user_id,
                predicate=Predicate.HAS_PRONOUN_STYLE,
                object=pronoun_str,
                object_type="personal",
                confidence=0.8,
            )
            repo.upsert_triple(triple)
            logger.debug("[SPRINT79] Persisted pronoun_style for %s", user_id)
        except Exception as exc:
            logger.debug("Failed to persist pronoun style: %s", exc)

    background_save(_store)


def maybe_summarize_previous_session_impl(
    *,
    background_save: Callable,
    user_id: str,
    organization_id: str | None = None,
) -> None:
    """Schedule background summarization for the previous thread when needed."""
    try:
        from app.repositories.thread_repository import get_thread_repository
        from app.tasks.summarize_tasks import summarize_thread_background

        repo = get_thread_repository()
        threads = repo.list_threads(
            user_id=user_id,
            limit=2,
            organization_id=organization_id,
        )
        if len(threads) < 2:
            return

        previous_thread = threads[1]
        extra = previous_thread.get("extra_data") or {}
        if extra.get("summary"):
            return

        background_save(
            summarize_thread_background,
            previous_thread["thread_id"],
            user_id,
            organization_id,
        )
        logger.info(
            "[SPRINT79] Triggered auto-summarize of previous session %s",
            previous_thread["thread_id"],
        )
    except Exception as exc:
        logger.debug("Auto-summarize previous session failed: %s", exc)
