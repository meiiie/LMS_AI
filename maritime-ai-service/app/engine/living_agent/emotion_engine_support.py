"""
Support helpers for EmotionEngine runtime concerns.

Keeps emotion_engine.py focused on event processing while preserving the
EmotionEngine method surface used across tests and integrations.
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.engine.living_agent.models import EmotionalState, MoodType
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

_EMOTION_STATE_MISSING_ORG_WARNING = "emotion_state_blocked_missing_org_context"


def build_behavior_modifiers_impl(state: EmotionalState, hour: int) -> dict[str, str]:
    """Build prompt-facing behavior modifiers from the current state."""
    modifiers: dict[str, str] = {}

    if state.energy_level < 0.3:
        modifiers["response_style"] = "ngắn gọn, tiết kiệm năng lượng"
    elif state.energy_level > 0.8:
        modifiers["response_style"] = "chi tiết, nhiệt tình"
    else:
        modifiers["response_style"] = "bình thường"

    if state.primary_mood in (MoodType.HAPPY, MoodType.EXCITED):
        modifiers["humor"] = "vui vẻ, có thể nói đùa nhẹ"
    elif state.primary_mood in (MoodType.CONCERNED, MoodType.TIRED):
        modifiers["humor"] = "nghiêm túc, tập trung"
    else:
        modifiers["humor"] = "tự nhiên"

    if state.engagement > 0.7 and state.energy_level > 0.5:
        modifiers["proactivity"] = "chủ động gợi ý, hỏi thêm"
    else:
        modifiers["proactivity"] = "trả lời khi được hỏi"

    if state.social_battery < 0.3:
        modifiers["social"] = "cần thời gian yên tĩnh"
    elif state.social_battery > 0.7:
        modifiers["social"] = "muốn trò chuyện nhiều hơn"
    else:
        modifiers["social"] = "bình thường"

    mood_labels = {
        MoodType.CURIOUS: "tò mò",
        MoodType.HAPPY: "vui vẻ",
        MoodType.EXCITED: "phấn khích",
        MoodType.FOCUSED: "tập trung",
        MoodType.CALM: "bình yên",
        MoodType.TIRED: "hơi mệt",
        MoodType.CONCERNED: "lo lắng",
        MoodType.REFLECTIVE: "trầm tư",
        MoodType.PROUD: "tự hào",
        MoodType.NEUTRAL: "bình thường",
    }
    modifiers["mood_label"] = mood_labels.get(state.primary_mood, "bình thường")

    if hour < 7:
        modifiers["tone"] = "nhẹ nhàng, ấm áp (sáng sớm)"
    elif hour < 12:
        modifiers["tone"] = "năng động, tích cực (buổi sáng)"
    elif hour < 14:
        modifiers["tone"] = "thư giãn, nhẹ nhàng (trưa)"
    elif hour < 18:
        modifiers["tone"] = "tập trung, hỗ trợ (chiều)"
    elif hour < 21:
        modifiers["tone"] = "thân thiện, thoải mái (tối)"
    else:
        modifiers["tone"] = "dịu dàng, yên bình (khuya)"

    return modifiers


def compile_emotion_prompt_impl(state: EmotionalState, modifiers: dict[str, str]) -> str:
    """Render the emotion block injected into prompts."""
    return (
        f"--- TRẠNG THÁI CẢM XÚC ---\n"
        f"Tâm trạng: {modifiers['mood_label']} | "
        f"Năng lượng: {state.energy_level:.0%} | "
        f"Pin xã hội: {state.social_battery:.0%}\n"
        f"Phong cách: {modifiers['response_style']} | "
        f"Hài hước: {modifiers['humor']} | "
        f"Chủ động: {modifiers['proactivity']}\n"
        f"--- HẾT CẢM XÚC ---"
    )


def restore_state_from_dict_impl(data: dict, logger_obj) -> EmotionalState:
    """Restore EmotionalState from serialized data with safe fallback."""
    try:
        state = EmotionalState.model_validate(data)
        logger_obj.info("[EMOTION] Restored state: mood=%s", state.primary_mood.value)
        return state
    except Exception as exc:
        logger_obj.warning("[EMOTION] Failed to restore state: %s, using defaults", exc)
        return EmotionalState()


def serialize_state_to_dict_impl(state: EmotionalState) -> dict:
    """Serialize current state for DB storage."""
    return state.model_dump(mode="json")


async def save_state_to_db_impl(engine, logger_obj) -> None:
    """Persist current emotional state to database."""
    try:
        from sqlalchemy import text

        from app.core.database import get_shared_session_factory

        scope = resolve_memory_write_scope()
        if not _scope_allows_emotion_state(scope):
            _log_emotion_state_scope_blocked(logger_obj, "save_state_to_db", scope)
            return

        state_json = json.dumps(engine.to_dict(), ensure_ascii=False)
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            session.execute(
                text(
                    """
                        DELETE FROM wiii_emotional_snapshots
                        WHERE trigger_event = 'persistent_state'
                        AND organization_id = :org_id
                    """
                ),
                {"org_id": scope.org_id},
            )
            session.execute(
                text(
                    """
                        INSERT INTO wiii_emotional_snapshots
                        (id, primary_mood, energy_level, social_battery, engagement,
                         trigger_event, state_json, snapshot_at, organization_id)
                        VALUES (:id, :mood, :energy, :social, :engagement,
                                'persistent_state', :state_json, NOW(), :org_id)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "mood": engine._state.primary_mood.value,
                    "energy": engine._state.energy_level,
                    "social": engine._state.social_battery,
                    "engagement": engine._state.engagement,
                    "state_json": state_json,
                    "org_id": scope.org_id,
                },
            )
            session.commit()
        logger_obj.info(
            "[EMOTION] State persisted to DB: mood=%s org_hash=%s",
            engine._state.primary_mood.value,
            hash_memory_identifier(scope.org_id),
        )
    except Exception as exc:
        logger_obj.warning("[EMOTION] Failed to persist state: %s", exc)


async def load_state_from_db_impl(engine, logger_obj) -> bool:
    """Load emotional state from database if present."""
    try:
        from sqlalchemy import text

        from app.core.database import get_shared_session_factory

        scope = resolve_memory_read_scope()
        if not _scope_allows_emotion_state(scope):
            _log_emotion_state_scope_blocked(logger_obj, "load_state_from_db", scope)
            return False

        session_factory = get_shared_session_factory()
        with session_factory() as session:
            row = session.execute(
                text(
                    """
                        SELECT state_json FROM wiii_emotional_snapshots
                        WHERE trigger_event = 'persistent_state'
                        AND organization_id = :org_id
                        ORDER BY snapshot_at DESC
                        LIMIT 1
                    """
                ),
                {"org_id": scope.org_id},
            ).fetchone()

            if row and row[0]:
                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                engine.restore_from_dict(data)
                logger_obj.info(
                    "[EMOTION] State loaded from DB: mood=%s org_hash=%s",
                    engine._state.primary_mood.value,
                    hash_memory_identifier(scope.org_id),
                )
                return True

        logger_obj.debug("[EMOTION] No saved state in DB, using defaults")
        return False
    except Exception as exc:
        logger_obj.warning("[EMOTION] Failed to load state from DB: %s", exc)
        return False


def _scope_allows_emotion_state(scope: MemoryWriteScope) -> bool:
    return bool(scope.write_allowed and scope.org_id)


def _log_emotion_state_scope_blocked(logger_obj, operation: str, scope: MemoryWriteScope) -> None:
    warnings = list(scope.warnings)
    if "missing_org_context" in warnings:
        warnings.append(_EMOTION_STATE_MISSING_ORG_WARNING)
    logger_obj.warning(
        "[EMOTION] %s blocked org_hash=%s org_scope=%s warnings=%s",
        operation,
        hash_memory_identifier(scope.org_id),
        scope.state,
        sorted(set(warnings)),
    )


def apply_circadian_modifier_impl(state: EmotionalState, hour: int, clamp_fn) -> None:
    """Adjust state using time-of-day energy and mood hints."""
    circadian_energy = {
        5: 0.40,
        6: 0.60,
        7: 0.80,
        8: 0.90,
        9: 0.95,
        10: 0.90,
        11: 0.85,
        12: 0.70,
        13: 0.65,
        14: 0.75,
        15: 0.85,
        16: 0.80,
        17: 0.75,
        18: 0.70,
        19: 0.65,
        20: 0.60,
        21: 0.50,
        22: 0.40,
        23: 0.20,
    }

    target = circadian_energy.get(hour)
    if target is not None:
        state.energy_level = clamp_fn(state.energy_level * 0.6 + target * 0.4)

    circadian_mood = {
        (5, 7): MoodType.CALM,
        (7, 10): MoodType.CURIOUS,
        (10, 12): MoodType.FOCUSED,
        (12, 14): MoodType.CALM,
        (14, 17): MoodType.FOCUSED,
        (17, 20): MoodType.CURIOUS,
        (20, 23): MoodType.REFLECTIVE,
    }
    for (start, end), mood in circadian_mood.items():
        if start <= hour < end:
            if state.primary_mood == MoodType.NEUTRAL:
                state.primary_mood = mood
            break
