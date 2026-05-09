"""Runtime helpers for living-agent API routes."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import HTTPException

from app.api.v1.living_agent_models import (
    AutonomyStatusResponse,
    CreateGoalRequest,
    EmotionalStateResponse,
    GoalResponse,
    HeartbeatInfoResponse,
    HeartbeatTriggerResponse,
    JournalEntryResponse,
    LivingAgentStatusResponse,
    ReflectionResponse,
    RoutineResponse,
    SkillResponse,
    UpdateGoalProgressRequest,
)

logger = logging.getLogger(__name__)


def check_living_agent_enabled() -> None:
    """Raise 404 when the living agent feature is disabled."""
    from app.core.config import settings

    if not settings.enable_living_agent:
        raise HTTPException(
            status_code=404,
            detail="Living Agent is not enabled. Set ENABLE_LIVING_AGENT=true.",
        )


def _build_emotional_state_response(engine) -> EmotionalStateResponse:
    state = engine.state
    modifiers = engine.get_behavior_modifiers()
    return EmotionalStateResponse(
        primary_mood=state.primary_mood.value,
        energy_level=round(state.energy_level, 3),
        social_battery=round(state.social_battery, 3),
        engagement=round(state.engagement, 3),
        mood_label=modifiers.get("mood_label", "bình thường"),
        behavior_modifiers=modifiers,
        last_updated=state.last_updated.isoformat() if state.last_updated else None,
    )


def get_living_agent_status_response() -> LivingAgentStatusResponse:
    """Build the overall living-agent status payload."""
    from app.core.config import settings

    if not settings.enable_living_agent:
        return LivingAgentStatusResponse(enabled=False)

    try:
        from app.engine.living_agent.emotion_engine import get_emotion_engine
        from app.engine.living_agent.heartbeat import get_heartbeat_scheduler
        from app.engine.living_agent.journal import get_journal_writer
        from app.engine.living_agent.skill_builder import get_skill_builder
        from app.engine.living_agent.soul_loader import get_soul

        soul = get_soul()
        engine = get_emotion_engine()
        scheduler = get_heartbeat_scheduler()

        try:
            skills_count = len(get_skill_builder().get_all_skills())
        except Exception:
            skills_count = 0

        try:
            journal_entries_count = len(get_journal_writer().get_recent_entries(limit=100))
        except Exception:
            journal_entries_count = 0

        return LivingAgentStatusResponse(
            enabled=True,
            emotional_state=_build_emotional_state_response(engine),
            heartbeat=HeartbeatInfoResponse(
                is_running=scheduler.is_running,
                heartbeat_count=scheduler.heartbeat_count,
                interval_seconds=settings.living_agent_heartbeat_interval,
                active_hours=(
                    f"{settings.living_agent_active_hours_start:02d}:00-"
                    f"{settings.living_agent_active_hours_end:02d}:00 UTC+7"
                ),
            ),
            skills_count=skills_count,
            journal_entries_count=journal_entries_count,
            soul_loaded=True,
            soul_name=soul.name,
        )
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Status error: %s", exc)
        return LivingAgentStatusResponse(enabled=True)


def get_emotional_state_response() -> EmotionalStateResponse:
    """Build Wiii's current emotional state payload."""
    from app.core.config import settings

    if not settings.enable_living_agent:
        return EmotionalStateResponse()

    try:
        from app.engine.living_agent.emotion_engine import get_emotion_engine

        return _build_emotional_state_response(get_emotion_engine())
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Emotional state error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def list_journal_entry_responses(days: int) -> List[JournalEntryResponse]:
    """Fetch recent journal entries."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.journal import get_journal_writer

        entries = get_journal_writer().get_recent_entries(days=days)
        return [
            JournalEntryResponse(
                id=str(entry.id),
                entry_date=entry.entry_date.isoformat() if entry.entry_date else "",
                content=entry.content,
                mood_summary=entry.mood_summary,
                energy_avg=entry.energy_avg,
                notable_events=entry.notable_events,
                learnings=entry.learnings,
                goals_next=entry.goals_next,
            )
            for entry in entries
        ]
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Journal error: %s", exc)
        return []


def list_skill_responses(
    *,
    status: Optional[str],
    domain: Optional[str],
) -> List[SkillResponse]:
    """Fetch tracked skills with optional filtering."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.models import SkillStatus
        from app.engine.living_agent.skill_builder import get_skill_builder

        status_enum = None
        if status:
            try:
                status_enum = SkillStatus(status)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status: {status}. Valid: {[s.value for s in SkillStatus]}",
                ) from exc

        skills = get_skill_builder().get_all_skills(status=status_enum, domain=domain)
        return [
            SkillResponse(
                id=str(skill.id),
                skill_name=skill.skill_name,
                domain=skill.domain,
                status=skill.status.value,
                confidence=round(skill.confidence, 3),
                usage_count=skill.usage_count,
                success_rate=round(skill.success_rate, 3),
                discovered_at=skill.discovered_at.isoformat() if skill.discovered_at else None,
                last_practiced=skill.last_practiced.isoformat() if skill.last_practiced else None,
                mastered_at=skill.mastered_at.isoformat() if skill.mastered_at else None,
            )
            for skill in skills
        ]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Skills error: %s", exc)
        return []


def get_heartbeat_info_response() -> HeartbeatInfoResponse:
    """Build heartbeat scheduler information."""
    check_living_agent_enabled()

    try:
        from app.core.config import settings
        from app.engine.living_agent.heartbeat import get_heartbeat_scheduler

        scheduler = get_heartbeat_scheduler()
        return HeartbeatInfoResponse(
            is_running=scheduler.is_running,
            heartbeat_count=scheduler.heartbeat_count,
            interval_seconds=settings.living_agent_heartbeat_interval,
            active_hours=(
                f"{settings.living_agent_active_hours_start:02d}:00-"
                f"{settings.living_agent_active_hours_end:02d}:00 UTC+7"
            ),
        )
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Heartbeat info error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def trigger_heartbeat_response() -> HeartbeatTriggerResponse:
    """Trigger one heartbeat cycle manually."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.heartbeat import get_heartbeat_scheduler

        result = await get_heartbeat_scheduler()._execute_heartbeat()
        return HeartbeatTriggerResponse(
            success=not result.error,
            actions_taken=len(result.actions_taken),
            duration_ms=result.duration_ms,
            error=result.error,
        )
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Trigger error: %s", exc)
        return HeartbeatTriggerResponse(success=False, error=str(exc))


def _goal_to_response(goal) -> GoalResponse:
    return GoalResponse(
        id=str(goal.id),
        title=goal.title,
        description=goal.description,
        status=goal.status.value,
        priority=goal.priority.value,
        progress=round(goal.progress, 3),
        source=goal.source,
        milestones=goal.milestones,
        completed_milestones=goal.completed_milestones,
        created_at=goal.created_at.isoformat() if goal.created_at else None,
        target_date=goal.target_date.isoformat() if goal.target_date else None,
        completed_at=goal.completed_at.isoformat() if goal.completed_at else None,
    )


async def list_goal_responses(active_only: bool) -> List[GoalResponse]:
    """Fetch goal list."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.goal_manager import get_goal_manager

        manager = get_goal_manager()
        goals = await (manager.get_active_goals() if active_only else manager.get_all_goals())
        return [_goal_to_response(goal) for goal in goals]
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Goals error: %s", exc)
        return []


async def create_goal_response(body: CreateGoalRequest) -> GoalResponse:
    """Create a new living-agent goal."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.goal_manager import get_goal_manager

        goal = await get_goal_manager().create_goal(
            title=body.title,
            description=body.description,
            priority=body.priority,
            source="api",
            milestones=body.milestones,
        )
        return _goal_to_response(goal)
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Create goal error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def update_goal_progress_response(
    goal_id: str,
    body: UpdateGoalProgressRequest,
):
    """Update goal progress and optional milestone state."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.goal_manager import get_goal_manager

        success = await get_goal_manager().update_progress(
            goal_id,
            body.progress,
            body.milestone,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Goal not found")
        return {"status": "updated", "progress": body.progress}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def activate_goal_response(goal_id: str):
    """Activate a proposed goal."""
    check_living_agent_enabled()

    from app.engine.living_agent.goal_manager import get_goal_manager

    success = await get_goal_manager().activate_goal(goal_id)
    if not success:
        raise HTTPException(status_code=404, detail="Goal not found or update failed")
    return {"status": "activated"}


async def complete_goal_response(goal_id: str):
    """Mark a goal as completed."""
    check_living_agent_enabled()

    from app.engine.living_agent.goal_manager import get_goal_manager

    success = await get_goal_manager().complete_goal(goal_id)
    if not success:
        raise HTTPException(status_code=404, detail="Goal not found or update failed")
    return {"status": "completed"}


def _reflection_to_response(entry) -> ReflectionResponse:
    return ReflectionResponse(
        id=str(entry.id),
        content=entry.content,
        insights=entry.insights,
        goals_next_week=entry.goals_next_week,
        patterns_noticed=entry.patterns_noticed,
        emotion_trend=entry.emotion_trend,
        reflection_date=entry.reflection_date.isoformat() if entry.reflection_date else None,
    )


async def list_reflection_responses(count: int) -> List[ReflectionResponse]:
    """Fetch recent reflections."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.reflector import get_reflector

        entries = await get_reflector().get_recent_reflections(count=count)
        return [_reflection_to_response(entry) for entry in entries]
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Reflections error: %s", exc)
        return []


async def trigger_reflection_response() -> ReflectionResponse:
    """Trigger a weekly reflection generation."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.reflector import get_reflector

        entry = await get_reflector().weekly_reflection()
        if not entry:
            raise HTTPException(
                status_code=409,
                detail="Already reflected this week or generation failed",
            )
        return _reflection_to_response(entry)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def get_autonomy_status_response() -> AutonomyStatusResponse:
    """Fetch current autonomy level/status."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.autonomy_manager import get_autonomy_manager

        status = get_autonomy_manager().get_status()
        return AutonomyStatusResponse(
            level=status["level"],
            level_name=status["level_name"],
            allowed_actions=status["allowed_actions"],
            needs_approval=status["needs_approval"],
            graduation_criteria=status["graduation_criteria"],
        )
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Autonomy status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def get_user_routine_response(user_id: str) -> Optional[RoutineResponse]:
    """Fetch learned routine for a user."""
    check_living_agent_enabled()

    try:
        from app.engine.living_agent.routine_tracker import get_routine_tracker

        routine = await get_routine_tracker().get_routine(user_id)
        if not routine:
            return None

        return RoutineResponse(
            user_id=routine.user_id,
            typical_active_hours=routine.typical_active_hours,
            preferred_briefing_time=routine.preferred_briefing_time,
            conversation_frequency=routine.conversation_frequency,
            common_topics=routine.common_topics,
            total_messages=routine.total_messages,
            last_seen=routine.last_seen.isoformat() if routine.last_seen else None,
        )
    except Exception as exc:
        logger.error("[LIVING_AGENT_API] Routine error: %s", exc)
        return None
