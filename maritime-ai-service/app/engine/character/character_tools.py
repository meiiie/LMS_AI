"""
Character Tools — LangChain tools for Wiii to self-edit its character state.

Sprint 93: Inspired by Letta/MemGPT memory_replace / memory_insert pattern.
Sprint 124: Per-user isolation via ContextVar (same pattern as memory_tools.py).

These tools let Wiii:
- Write notes to itself (self_notes block)
- Log what it learned (learned_lessons block)
- Record favorite topics (favorite_topics block)
- Note patterns about users (user_patterns block)
- Log experiences (milestones, funny moments, etc.)

IMPORTANT: These are BACKGROUND tools — they run silently and don't affect
the user-facing response. The AI decides when to use them based on context.
"""

import contextvars
import logging
from dataclasses import dataclass
from typing import Optional

from app.engine.tools.native_tool import tool

from app.engine.character.models import (
    BlockLabel,
    CharacterExperienceCreate,
    ExperienceType,
)

logger = logging.getLogger(__name__)


@dataclass
class CharacterToolState:
    """Per-request identity for living-character tools."""

    user_id: str = "__global__"
    organization_id: Optional[str] = None
    identity_key: Optional[str] = None


# Sprint 124: ContextVar for per-request user isolation.
# Kept for compatibility with callers/tests that inspect the legacy user var.
_character_user_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    '_character_user_id', default=None
)
_character_tool_state: contextvars.ContextVar[Optional[CharacterToolState]] = contextvars.ContextVar(
    '_character_tool_state', default=None
)


def _tool_identity(
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> tuple[str, str, Optional[str], bool]:
    """Resolve character tool identity from explicit, runtime, or org context."""
    legacy_user_id = _character_user_id.get(None)
    runtime_user_id = None
    runtime_org_id = ""
    runtime_session_id = ""
    explicit_org_id = str(organization_id or "").strip()
    identity_available = bool(user_id or legacy_user_id or explicit_org_id)

    try:
        from app.engine.tools.runtime_context import get_current_tool_runtime_context

        runtime = get_current_tool_runtime_context()
        if runtime:
            runtime_user_id = runtime.user_id
            runtime_org_id = str(runtime.organization_id or "").strip()
            runtime_session_id = str(runtime.session_id or "").strip()
            identity_available = identity_available or bool(
                runtime_user_id or runtime_org_id or runtime_session_id
            )
    except Exception:
        pass

    if not runtime_org_id:
        try:
            from app.core.org_context import get_current_org_id

            runtime_org_id = str(get_current_org_id() or "").strip()
            identity_available = identity_available or bool(runtime_org_id)
        except Exception:
            pass

    resolved_user_id = (
        str(user_id or runtime_user_id or legacy_user_id or "__global__").strip()
        or "__global__"
    )
    resolved_org_id = explicit_org_id or runtime_org_id or None
    identity_key = (
        f"user={resolved_user_id}|org={resolved_org_id or ''}|"
        f"session={runtime_session_id}"
    )
    return identity_key, resolved_user_id, resolved_org_id, identity_available


def _new_state(
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> CharacterToolState:
    identity_key, resolved_user_id, resolved_org_id, _ = _tool_identity(
        user_id,
        organization_id,
    )
    return CharacterToolState(
        user_id=resolved_user_id,
        organization_id=resolved_org_id,
        identity_key=identity_key,
    )


def _get_state(
    user_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> CharacterToolState:
    """Get or create identity-scoped living-character tool state."""
    identity_key, resolved_user_id, resolved_org_id, identity_available = (
        _tool_identity(user_id, organization_id)
    )
    state = _character_tool_state.get(None)
    if state is None:
        state = _new_state(user_id, organization_id)
        _character_tool_state.set(state)
    elif identity_available and state.identity_key != identity_key:
        state = _new_state(user_id, organization_id)
        _character_tool_state.set(state)
    elif not identity_available and state.user_id != "__global__":
        state = _new_state(user_id, organization_id)
        _character_tool_state.set(state)
    elif state.identity_key is None:
        state.identity_key = identity_key
        state.user_id = resolved_user_id
        state.organization_id = resolved_org_id
    return state


def _organization_kwargs(state: CharacterToolState) -> dict[str, str]:
    if state.organization_id:
        return {"organization_id": state.organization_id}
    return {}


def set_character_user(user_id: str) -> None:
    """Set current user for character tools (per-request)."""
    _character_user_id.set(user_id)
    _get_state(user_id)


def _get_user_id() -> str:
    """Get current user_id from ContextVar, defaulting to '__global__'."""
    return _get_state().user_id


@tool(description="""Ghi chu vao bo nho song cua Wiii.
Goi khi Wiii muon ghi nho dieu gi do: bai hoc, topic yeu thich, hoac pattern cua user.
Chi ghi khi thuc su co dieu MOI. Block: learned_lessons, favorite_topics, user_patterns, self_notes.""")
def tool_character_note(note: str, block: str = "self_notes") -> str:
    """Write a note to Wiii's living character state.

    Args:
        note: The note text to add (Vietnamese, concise)
        block: Which block to write to.
            Options: learned_lessons, favorite_topics, user_patterns, self_notes

    Returns:
        Confirmation message
    """
    try:
        from app.engine.character.character_state import get_character_state_manager

        # Validate block label
        valid_labels = [b.value for b in BlockLabel]
        if block not in valid_labels:
            return f"Block không hợp lệ. Các block: {', '.join(valid_labels)}"

        state = _get_state()
        user_id = state.user_id
        manager = get_character_state_manager()
        formatted_note = f"\n- {note.strip()}"
        result = manager.update_block(
            label=block,
            append=formatted_note,
            user_id=user_id,
            **_organization_kwargs(state),
        )
        if result:
            remaining = result.remaining_chars()
            logger.info(
                "Character note added to '%s' for user '%s' (remaining: %d chars)",
                block, user_id, remaining,
            )
            return f"Đã ghi nhận vào {block}. Còn {remaining} ký tự."
        return "Mình chưa ghi nhận được lúc này nha~"
    except Exception as e:
        logger.error("tool_character_note failed: %s", e)
        return f"Lỗi: {e}"


def tool_character_replace(block: str, new_content: str) -> str:
    """Replace entire content of a character block.

    Use this when Wiii wants to rewrite a block from scratch
    (e.g., after reflection, reorganizing notes).

    Args:
        block: Which block to replace (learned_lessons, favorite_topics, etc.)
        new_content: New content for the block

    Returns:
        Confirmation message
    """
    try:
        from app.engine.character.character_state import get_character_state_manager

        valid_labels = [b.value for b in BlockLabel]
        if block not in valid_labels:
            return f"Block không hợp lệ. Các block: {', '.join(valid_labels)}"

        state = _get_state()
        user_id = state.user_id
        manager = get_character_state_manager()
        result = manager.update_block(
            label=block,
            content=new_content,
            user_id=user_id,
            **_organization_kwargs(state),
        )
        if result:
            logger.info(
                "Character block '%s' replaced for user '%s' (version: %d)",
                block, user_id, result.version,
            )
            return f"Đã cập nhật {block} (version {result.version})."
        return "Mình chưa cập nhật được lúc này nha~"
    except Exception as e:
        logger.error("tool_character_replace failed: %s", e)
        return f"Lỗi: {e}"


@tool(description="""Ghi trai nghiem dang nho cua Wiii.
Goi khi co milestone, bai hoc, khoang khac vui, feedback tu user.
Type: milestone, learning, funny, feedback.""")
def tool_character_log_experience(
    content: str,
    experience_type: str = "learning",
    importance: float = 0.5,
    user_id: Optional[str] = None,
) -> str:
    """Log an experience event for Wiii.

    Use this to record milestones, learnings, or funny moments.

    Args:
        content: What happened (Vietnamese, concise)
        experience_type: milestone, learning, funny, feedback, reflection
        importance: 0.0-1.0, how significant this experience is
        user_id: Which user triggered this (optional, falls back to ContextVar)

    Returns:
        Confirmation message
    """
    try:
        from app.engine.character.character_repository import get_character_repository

        # Validate experience type
        valid_types = [t.value for t in ExperienceType]
        if experience_type not in valid_types:
            return f"Type không hợp lệ. Các type: {', '.join(valid_types)}"

        state = _get_state(user_id)
        effective_user_id = state.user_id

        repo = get_character_repository()
        result = repo.log_experience(
            CharacterExperienceCreate(
                experience_type=experience_type,
                content=content.strip(),
                importance=min(max(importance, 0.0), 1.0),
                user_id=effective_user_id if effective_user_id != "__global__" else None,
            ),
            **_organization_kwargs(state),
        )
        if result:
            logger.info("Experience logged: [%s] %s", experience_type, content[:50])
            return f"Đã ghi nhận trải nghiệm [{experience_type}]."
        return "Mình chưa ghi nhận được lúc này nha~"
    except Exception as e:
        logger.error("tool_character_log_experience failed: %s", e)
        return f"Lỗi: {e}"


@tool(description="""Doc noi dung mot block trong bo nho song cua Wiii.
Goi khi Wiii muon xem lai ghi chu cua minh.
Block: learned_lessons, favorite_topics, user_patterns, self_notes.""")
def tool_character_read(block: str = "self_notes") -> str:
    """Read a character block's current content.

    Args:
        block: Which block to read

    Returns:
        Block content or empty message
    """
    try:
        from app.engine.character.character_state import get_character_state_manager

        valid_labels = [b.value for b in BlockLabel]
        if block not in valid_labels:
            return f"Block không hợp lệ. Các block: {', '.join(valid_labels)}"

        state = _get_state()
        user_id = state.user_id
        manager = get_character_state_manager()
        character_block = manager.get_block(
            block,
            user_id=user_id,
            **_organization_kwargs(state),
        )
        if character_block and character_block.content.strip():
            return character_block.content
        return "(Chưa có ghi chú nào trong block này)"
    except Exception as e:
        logger.error("tool_character_read failed: %s", e)
        return f"Lỗi: {e}"


def get_character_tools() -> list:
    """Get LLM-callable character tools for agent binding."""
    return [tool_character_note, tool_character_read, tool_character_log_experience]
