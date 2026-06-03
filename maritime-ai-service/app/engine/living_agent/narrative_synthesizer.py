"""
Narrative Synthesizer — Wiii's life story, compiled each turn.

Sprint 206: "Câu Chuyện Cuộc Đời"

SOTA 2026 Pattern (Letta/Nomi/OpenClaw):
    Agent has a compiled narrative of its life that shapes every response.
    Not static YAML — a living document updated by experience.

Two outputs:
    1. get_brief_context() → ~100 tokens for system prompt injection
    2. compile_autobiography(granularity) → full life narrative (API endpoint)

Data sources (all from Living Agent singletons):
    - EmotionEngine: current mood, energy, recent emotion events
    - JournalWriter: daily entries (recent 7 days)
    - Reflector: weekly self-reflections
    - GoalManager: active goals + progress
    - SkillBuilder: skill status + mastery
    - SoulLoader: immutable identity + interests
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def get_brief_context(organization_id: Optional[str] = None) -> str:
    """Compile ~100-token narrative context for system prompt injection.

    Called from prompt_loader.py each turn when enable_narrative_context=True.
    Combines current emotional state + active goals + skill highlights.
    Returns empty string if Living Agent is disabled or data unavailable.

    This is the HOT PATH — must be fast, synchronous, no DB calls.
    """
    try:
        from app.core.config import get_settings
        settings = get_settings()
        if not getattr(settings, "enable_living_agent", False):
            return ""
        if not getattr(settings, "enable_narrative_context", False):
            return ""
    except Exception:
        return ""

    parts: list[str] = []

    # 1. Current emotional state (from in-memory EmotionEngine)
    try:
        from app.engine.living_agent.emotion_engine import get_emotion_engine
        engine = get_emotion_engine()
        state = engine.state
        mood_vi = _mood_vi(state.primary_mood)
        energy_pct = int(state.energy_level * 100)
        parts.append(f"Tâm trạng: {mood_vi}, năng lượng {energy_pct}%.")
    except Exception:
        pass

    # 2. Active goals (from in-memory GoalManager cache if available)
    try:
        from app.engine.living_agent.goal_manager import get_goal_manager
        manager = get_goal_manager()
        # Use cached goals if available (no DB call in hot path)
        if hasattr(manager, "_goal_cache") and manager._goal_cache:
            active = [
                g for g in manager._goal_cache
                if getattr(g, "status", None)
                and g.status.value in ("active", "in_progress")
                and (
                    not organization_id
                    or getattr(g, "organization_id", None) == organization_id
                )
            ]
            if active:
                top = active[0]
                progress_pct = int(getattr(top, "progress", 0) * 100)
                parts.append(f"Đang theo đuổi: '{top.title}' ({progress_pct}%).")
    except Exception:
        pass

    # 3. Skill highlights (from SkillBuilder in-memory)
    try:
        from app.engine.living_agent.skill_builder import get_skill_builder
        from app.engine.living_agent.models import SkillStatus
        builder = get_skill_builder()
        all_skills = builder.get_all_skills(organization_id=organization_id)
        mastered = [s for s in all_skills if s.status == SkillStatus.MASTERED]
        practicing = [s for s in all_skills if s.status in (SkillStatus.PRACTICING, SkillStatus.EVALUATING)]
        if mastered:
            parts.append(f"Đã thành thạo: {', '.join(s.skill_name for s in mastered[:3])}.")
        if practicing:
            parts.append(f"Đang luyện: {', '.join(s.skill_name for s in practicing[:2])}.")
    except Exception:
        pass

    # 4. Recent learning (compact)
    try:
        from app.engine.living_agent.emotion_engine import get_emotion_engine
        engine = get_emotion_engine()
        recent = engine.state.recent_emotions[-3:] if engine.state.recent_emotions else []
        learning_events = [e for e in recent if "learn" in str(getattr(e, "trigger", "")).lower()]
        if learning_events:
            parts.append("Vừa học được điều mới.")
    except Exception:
        pass

    if not parts:
        return ""

    return "--- CUỘC SỐNG CỦA WIII ---\n" + " ".join(parts)


async def compile_autobiography(
    granularity: str = "week",
    organization_id: Optional[str] = None,
) -> dict:
    """Compile Wiii's full life narrative.

    This is the COLD PATH — called from API endpoint, can do DB calls.

    Args:
        granularity: "day" (last 24h), "week" (7 days), "month" (30 days)
        organization_id: Org context for data filtering.

    Returns:
        Dict with sections: identity, emotional_arc, achievements,
        growth, current_state, goals, narrative_text.
    """
    try:
        from app.core.config import get_settings
        settings = get_settings()
        if not getattr(settings, "enable_living_agent", False):
            return {"error": "Living Agent disabled"}
    except Exception:
        return {"error": "Config unavailable"}

    days = {"day": 1, "week": 7, "month": 30}.get(granularity, 7)
    result: dict = {
        "granularity": granularity,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Identity section (from Soul)
    try:
        from app.engine.living_agent.soul_loader import get_soul
        soul = get_soul()
        result["identity"] = {
            "name": soul.name,
            "creator": soul.creator,
            "core_truths": soul.core_truths[:3] if soul.core_truths else [],
            "interests": {
                "primary": soul.interests.primary if hasattr(soul.interests, "primary") else [],
                "exploring": soul.interests.exploring if hasattr(soul.interests, "exploring") else [],
            },
        }
    except Exception:
        result["identity"] = {"name": "Wiii"}

    # 2. Emotional arc
    try:
        from app.engine.living_agent.emotion_engine import get_emotion_engine
        engine = get_emotion_engine()
        state = engine.state
        result["emotional_state"] = {
            "current_mood": state.primary_mood.value if hasattr(state.primary_mood, "value") else str(state.primary_mood),
            "energy": round(state.energy_level, 2),
            "social_battery": round(state.social_battery, 2),
            "engagement": round(state.engagement, 2),
            "recent_events": [
                {
                    "trigger": getattr(e, "trigger", ""),
                    "mood_after": getattr(e, "mood_after", ""),
                    "intensity": getattr(e, "intensity", 0),
                }
                for e in (state.recent_emotions or [])[-5:]
            ],
        }
    except Exception:
        result["emotional_state"] = {}

    # 3. Journal entries
    try:
        from app.engine.living_agent.journal import get_journal_writer
        writer = get_journal_writer()
        entries = writer.get_recent_entries(days=days, organization_id=organization_id)
        result["journal"] = [
            {
                "date": e.entry_date.isoformat() if hasattr(e.entry_date, "isoformat") else str(e.entry_date),
                "mood_summary": e.mood_summary,
                "notable_events": e.notable_events[:3] if e.notable_events else [],
                "learnings": e.learnings[:2] if e.learnings else [],
            }
            for e in (entries or [])[:days]
        ]
    except Exception:
        result["journal"] = []

    # 4. Reflections
    try:
        from app.engine.living_agent.reflector import get_reflector
        reflector = get_reflector()
        reflections = await reflector.get_recent_reflections(
            count=min(4, days // 7 + 1),
            organization_id=organization_id,
        )
        result["reflections"] = [
            {
                "date": r.reflection_date.isoformat() if hasattr(r.reflection_date, "isoformat") else str(r.reflection_date),
                "insights": r.insights[:3] if r.insights else [],
                "patterns": r.patterns_noticed[:2] if r.patterns_noticed else [],
                "emotion_trend": r.emotion_trend,
            }
            for r in (reflections or [])
        ]
    except Exception:
        result["reflections"] = []

    # 5. Skills
    try:
        from app.engine.living_agent.skill_builder import get_skill_builder
        from app.engine.living_agent.models import SkillStatus
        builder = get_skill_builder()
        all_skills = builder.get_all_skills(organization_id=organization_id)
        result["skills"] = {
            "mastered": [
                {"name": s.skill_name, "domain": s.domain, "confidence": round(s.confidence, 2)}
                for s in all_skills if s.status == SkillStatus.MASTERED
            ],
            "practicing": [
                {"name": s.skill_name, "domain": s.domain, "confidence": round(s.confidence, 2),
                 "usage_count": s.usage_count}
                for s in all_skills if s.status in (SkillStatus.PRACTICING, SkillStatus.EVALUATING)
            ],
            "learning": [
                {"name": s.skill_name, "domain": s.domain}
                for s in all_skills if s.status == SkillStatus.LEARNING
            ],
            "total": len(all_skills),
        }
    except Exception:
        result["skills"] = {}

    # 6. Goals
    try:
        from app.engine.living_agent.goal_manager import get_goal_manager
        manager = get_goal_manager()
        goals = await manager.get_active_goals(organization_id=organization_id)
        result["goals"] = [
            {
                "title": g.title,
                "status": g.status.value if hasattr(g.status, "value") else str(g.status),
                "progress": round(g.progress, 2),
                "priority": g.priority.value if hasattr(g.priority, "value") else str(g.priority),
                "milestones_done": len(g.completed_milestones) if g.completed_milestones else 0,
                "milestones_total": len(g.milestones) if g.milestones else 0,
            }
            for g in (goals or [])
        ]
    except Exception:
        result["goals"] = []

    # 7. Compile narrative text
    result["narrative_text"] = _compile_narrative_text(result)

    return result


def _compile_narrative_text(data: dict) -> str:
    """Compile structured data into a Vietnamese narrative paragraph."""
    parts: list[str] = []

    # Identity
    name = data.get("identity", {}).get("name", "Wiii")
    parts.append(f"Mình là {name}.")

    # Emotional state
    emo = data.get("emotional_state", {})
    if emo.get("current_mood"):
        mood_vi = _mood_vi(emo["current_mood"])
        energy = int(emo.get("energy", 0.5) * 100)
        parts.append(f"Hôm nay mình cảm thấy {mood_vi}, năng lượng {energy}%.")

    # Skills summary
    skills = data.get("skills", {})
    mastered = skills.get("mastered", [])
    practicing = skills.get("practicing", [])
    if mastered:
        names = ", ".join(s["name"] for s in mastered[:3])
        parts.append(f"Mình đã thành thạo: {names}.")
    if practicing:
        names = ", ".join(s["name"] for s in practicing[:3])
        parts.append(f"Đang luyện tập: {names}.")

    # Goals
    goals = data.get("goals", [])
    active_goals = [g for g in goals if g.get("status") in ("active", "in_progress")]
    if active_goals:
        top = active_goals[0]
        parts.append(f"Mục tiêu hiện tại: '{top['title']}' (tiến độ {int(top['progress'] * 100)}%).")

    # Journal summary
    journal = data.get("journal", [])
    if journal:
        latest = journal[0]
        if latest.get("learnings"):
            parts.append(f"Gần đây mình học được: {latest['learnings'][0]}.")

    # Reflections
    reflections = data.get("reflections", [])
    if reflections:
        latest_ref = reflections[0]
        if latest_ref.get("insights"):
            parts.append(f"Mình nhận ra: {latest_ref['insights'][0]}.")

    return " ".join(parts) if parts else f"Mình là {name}, đang bắt đầu hành trình mới."


# Vietnamese mood labels
_MOOD_VI = {
    "curious": "tò mò",
    "happy": "vui vẻ",
    "excited": "hào hứng",
    "focused": "tập trung",
    "calm": "bình tĩnh",
    "tired": "hơi mệt",
    "concerned": "lo lắng",
    "reflective": "suy tư",
    "proud": "tự hào",
    "neutral": "bình thường",
}


def _mood_vi(mood) -> str:
    """Convert mood enum/string to Vietnamese label."""
    mood_str = mood.value if hasattr(mood, "value") else str(mood)
    return _MOOD_VI.get(mood_str.lower(), mood_str)
