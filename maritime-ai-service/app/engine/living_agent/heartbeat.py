"""
Heartbeat Scheduler — Wiii's periodic autonomy engine.

Sprint 170: "Linh Hồn Sống"
Sprint 171: "Quyền Tự Chủ" — Safety-first autonomy.

Wakes Wiii at configurable intervals to:
1. Load soul and emotional state
2. Check active goals
3. Choose and execute an action (browse, learn, reflect, journal)
4. Enforce human approval gate for external actions (Sprint 171)
5. Update emotional state based on results
6. Save audit record for every cycle (Sprint 171)
7. Log experience for long-term memory

Safety features (Sprint 171):
    - Human approval gate: external actions queued when require_human_approval=True
    - Audit logging: every heartbeat cycle persisted to wiii_heartbeat_audit
    - Daily cycle cap: max 48 cycles/day (prevent runaway)
    - Search rate limit: max 3 web searches per heartbeat cycle

Design:
    - Reuses existing ScheduledTaskExecutor pattern (asyncio poll loop)
    - Active hours support (e.g., 08:00-23:00 UTC+7)
    - Uses LOCAL MODEL (Ollama) for zero API cost
    - Feature-gated: enable_living_agent=False by default
    - Non-blocking: all errors caught, never affects user chat
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.engine.living_agent.models import (
    ActionType,
    HeartbeatAction,
    HeartbeatResult,
    LifeEvent,
    LifeEventType,
)
from app.engine.living_agent.heartbeat_action_runtime import (
    action_browse_impl,
    action_check_goals_impl,
    action_check_weather_impl,
    action_deep_reflect_impl,
    action_journal_impl,
    action_learn_impl,
    action_reengage_impl,
    action_reflect_impl,
    action_review_skill_impl,
    action_send_briefing_impl,
    notify_discovery_impl,
    self_answer_quiz_impl,
)
from app.engine.living_agent.heartbeat_runtime_state import (
    set_current_heartbeat_count,
)
from app.engine.runtime.runtime_metrics import inc_counter, record_latency_ms

logger = logging.getLogger(__name__)

# Actions that require human approval when require_human_approval=True
# Low-risk actions (no external I/O) are always auto-approved.
_APPROVAL_REQUIRED_ACTIONS = {ActionType.BROWSE_SOCIAL, ActionType.LEARN_TOPIC}
_ACTION_TYPE_LABELS = {action_type.value for action_type in ActionType}


def _action_type_metric_label(action: HeartbeatAction) -> str:
    value = getattr(action.action_type, "value", None)
    if value in _ACTION_TYPE_LABELS:
        return str(value)
    return "unknown"


def _emit_action_metric(
    *,
    action: HeartbeatAction,
    status: str,
    started: float,
) -> None:
    labels = {
        "action_type": _action_type_metric_label(action),
        "status": status,
    }
    inc_counter("runtime.living_agent.heartbeat.actions", labels=labels)
    elapsed_ms = (time.monotonic() - started) * 1000.0
    record_latency_ms(
        "runtime.living_agent.heartbeat.action_duration_ms",
        elapsed_ms,
        labels=labels,
    )


class HeartbeatScheduler:
    """Periodic autonomy engine for Wiii's living agent.

    Runs as a background asyncio task, waking Wiii at configured intervals
    during active hours. Each heartbeat cycle:
    1. Checks if within active hours
    2. Loads current emotional state + soul
    3. Plans actions based on mood, energy, and goals
    4. Enforces approval gate for external actions (Sprint 171)
    5. Executes actions (browse, learn, reflect, journal)
    6. Updates emotional state
    7. Saves snapshot + audit record

    Usage:
        scheduler = HeartbeatScheduler()
        await scheduler.start()
        # ... runs in background ...
        await scheduler.stop()
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._running = False
        self._heartbeat_count = 0
        set_current_heartbeat_count(self._heartbeat_count)
        self._daily_cycle_count = 0
        self._daily_reset_date: Optional[str] = None  # "YYYY-MM-DD" in UTC+7
        self._emotion_loaded = False  # Phase 1A: Track if emotion restored from DB
        self._graduation_checked_date: Optional[str] = None  # Sprint 208: daily graduation check

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def heartbeat_count(self) -> int:
        return self._heartbeat_count

    @property
    def daily_cycle_count(self) -> int:
        return self._daily_cycle_count

    def _time_monotonic(self) -> float:
        return time.monotonic()

    async def start(self) -> None:
        """Start the heartbeat loop as a background task."""
        if self._running:
            logger.warning("[HEARTBEAT] Already running, skipping start")
            return

        self._shutdown_event.clear()
        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info("[HEARTBEAT] Wiii's heartbeat started")

    async def stop(self) -> None:
        """Gracefully stop the heartbeat loop."""
        if not self._running:
            return

        self._shutdown_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._running = False
        logger.info("[HEARTBEAT] Wiii's heartbeat stopped (total: %d cycles)", self._heartbeat_count)

    async def _heartbeat_loop(self) -> None:
        """Main loop: sleep, check active hours, execute heartbeat."""
        from app.core.config import settings

        interval = settings.living_agent_heartbeat_interval

        while not self._shutdown_event.is_set():
            try:
                if self._is_active_hours():
                    # Check daily cycle cap (Sprint 171)
                    if self._check_daily_limit():
                        result = await self._execute_heartbeat()
                        if result.error:
                            logger.warning("[HEARTBEAT] Cycle error: %s", result.error)
                        elif result.is_noop:
                            logger.debug("[HEARTBEAT] NOOP — nothing to do")
                        else:
                            logger.info(
                                "[HEARTBEAT] Cycle #%d complete: %d actions, %d insights, %dms",
                                self._heartbeat_count,
                                len(result.actions_taken),
                                result.insights_gained,
                                result.duration_ms,
                            )
                    else:
                        logger.warning("[HEARTBEAT] Daily cycle limit reached, skipping")
                else:
                    logger.debug("[HEARTBEAT] Outside active hours, sleeping")
            except Exception as e:
                logger.error("[HEARTBEAT] Unexpected error: %s", e, exc_info=True)

            # Wait for interval or shutdown signal
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=interval,
                )
                break  # Shutdown signal received
            except asyncio.TimeoutError:
                pass  # Interval elapsed, continue

    async def _execute_heartbeat(self) -> HeartbeatResult:
        """Execute a single heartbeat cycle."""
        from app.engine.living_agent.heartbeat_runtime_support import (
            execute_heartbeat_cycle_impl,
        )

        return await execute_heartbeat_cycle_impl(
            scheduler=self,
            approval_required_actions=_APPROVAL_REQUIRED_ACTIONS,
            logger_obj=logger,
        )

    async def execute_approved_action(self, action_id: str) -> HeartbeatResult:
        """Execute a previously approved pending action.

        Called by the API when a human approves a queued action.

        Args:
            action_id: The ID of the pending action in wiii_pending_actions.

        Returns:
            HeartbeatResult with the action execution outcome.
        """
        from app.engine.living_agent.emotion_engine import get_emotion_engine
        from app.engine.living_agent.soul_loader import get_soul

        start_time = time.monotonic()
        result = HeartbeatResult()

        try:
            # Load pending action from DB
            action_data = await self._load_pending_action(action_id)
            if not action_data:
                result.error = f"Pending action {action_id} not found or not approved"
                return result

            soul = get_soul()
            engine = get_emotion_engine()

            action = HeartbeatAction(
                action_type=ActionType(action_data["action_type"]),
                target=action_data.get("target", ""),
                priority=action_data.get("priority", 0.5),
            )

            await self._execute_action(action, soul, engine)
            result.actions_taken.append(action)

            # Mark as completed in DB
            await self._mark_action_completed(action_id)

        except Exception as e:
            result.error = str(e)
            logger.error("[HEARTBEAT] Approved action execution failed: %s", e)

        result.duration_ms = int((time.monotonic() - start_time) * 1000)
        return result

    async def _plan_actions(self, mood: str, energy: float) -> list:
        """Plan actions for this heartbeat based on mood and energy.

        Returns list of HeartbeatAction, max limited by config.
        Enhanced with Soul AGI phases: weather, briefing, reflection, goals.
        """
        from app.core.config import settings
        max_actions = settings.living_agent_max_actions_per_heartbeat

        candidates = []

        # Always available: check goals (low energy cost)
        candidates.append(HeartbeatAction(
            action_type=ActionType.CHECK_GOALS,
            priority=0.8,
        ))

        # Phase 1B: Weather check (morning hours, 05-07 UTC+7)
        if settings.living_agent_enable_weather and self._is_morning():
            candidates.append(HeartbeatAction(
                action_type=ActionType.CHECK_WEATHER,
                priority=0.95,
            ))

        # Phase 2A: Briefing delivery
        if settings.living_agent_enable_briefing and self._is_briefing_time():
            candidates.append(HeartbeatAction(
                action_type=ActionType.SEND_BRIEFING,
                priority=0.9,
            ))

        if energy > 0.5:
            # Good energy — can browse and learn
            if settings.living_agent_enable_social_browse:
                candidates.append(HeartbeatAction(
                    action_type=ActionType.BROWSE_SOCIAL,
                    target="auto",  # Phase 3A: smart topic selection
                    priority=0.6,
                ))
            if settings.living_agent_enable_skill_building:
                candidates.append(HeartbeatAction(
                    action_type=ActionType.LEARN_TOPIC,
                    priority=0.5,
                ))
        elif energy > 0.3:
            # Medium energy — light tasks
            candidates.append(HeartbeatAction(
                action_type=ActionType.REFLECT,
                priority=0.7,
            ))
        else:
            # Low energy — rest
            candidates.append(HeartbeatAction(
                action_type=ActionType.REST,
                priority=0.9,
            ))

        # Sprint 177: Review skills due for spaced repetition
        if settings.living_agent_enable_skill_learning:
            try:
                from app.engine.living_agent.skill_learner import get_skill_learner
                learner = get_skill_learner()
                due_skills = learner.get_skills_due_for_review()
                if due_skills:
                    candidates.append(HeartbeatAction(
                        action_type=ActionType.REVIEW_SKILL,
                        target=due_skills[0].skill_name,
                        priority=0.75,
                        metadata={"due_count": len(due_skills)},
                    ))
            except Exception as e:
                logger.debug("[HEARTBEAT] Review check failed: %s", e)

        # Daily journal (once per day, evening)
        if settings.living_agent_enable_journal and self._is_journal_time():
            candidates.append(HeartbeatAction(
                action_type=ActionType.WRITE_JOURNAL,
                priority=0.9,
            ))

        # Phase 4A: Weekly deep reflection (Sunday 20:00)
        if self._is_reflection_time():
            candidates.append(HeartbeatAction(
                action_type=ActionType.DEEP_REFLECT,
                priority=0.95,
            ))

        # Sprint 208: Proactive re-engagement — check for inactive users
        if settings.living_agent_enable_proactive_messaging and energy > 0.4:
            try:
                from app.engine.living_agent.routine_tracker import get_routine_tracker
                tracker = get_routine_tracker()
                inactive = await tracker.get_inactive_users(days=2)
                if inactive:
                    candidates.append(HeartbeatAction(
                        action_type=ActionType.SEND_BRIEFING,
                        target=f"reengage:{inactive[0]}",
                        priority=0.55,
                        metadata={"trigger": "inactive_user", "user_id": inactive[0]},
                    ))
            except Exception as e:
                logger.debug("[HEARTBEAT] Inactive user check failed: %s", e)

        # Sort by priority descending, take top N
        candidates.sort(key=lambda a: a.priority, reverse=True)
        return candidates[:max_actions]

    async def _execute_action(self, action: HeartbeatAction, soul, engine) -> None:
        """Execute a single heartbeat action with timeout protection.

        Sprint 210: 60s timeout per action prevents Ollama CPU blocking.
        Each action type delegates to the appropriate subsystem.
        Extensible: add new action types by adding cases here.
        """
        started = time.monotonic()
        try:
            async with asyncio.timeout(60):
                await self._dispatch_action(action, soul, engine)
            _emit_action_metric(action=action, status="success", started=started)
        except asyncio.TimeoutError:
            logger.warning("[HEARTBEAT] Action %s timed out (60s)", action.action_type.value)
            _emit_action_metric(action=action, status="timeout", started=started)
        except Exception as e:
            logger.warning("[HEARTBEAT] Action %s error: %s", action.action_type.value, e)
            _emit_action_metric(action=action, status="error", started=started)

    async def _dispatch_action(self, action: HeartbeatAction, soul, engine) -> None:
        """Dispatch action to the appropriate handler (internal, called with timeout)."""
        if action.action_type == ActionType.CHECK_GOALS:
            await self._action_check_goals(soul)

        elif action.action_type == ActionType.BROWSE_SOCIAL:
            await self._action_browse(action, soul, engine)

        elif action.action_type == ActionType.LEARN_TOPIC:
            await self._action_learn(soul, engine)

        elif action.action_type == ActionType.REFLECT:
            await self._action_reflect(engine)

        elif action.action_type == ActionType.WRITE_JOURNAL:
            await self._action_journal(engine)

        elif action.action_type == ActionType.CHECK_WEATHER:
            await self._action_check_weather()

        elif action.action_type == ActionType.SEND_BRIEFING:
            # Sprint 208: Re-engagement via ProactiveMessenger
            if action.target and action.target.startswith("reengage:"):
                await self._action_reengage(action, engine)
            else:
                await self._action_send_briefing(engine)

        elif action.action_type == ActionType.DEEP_REFLECT:
            await self._action_deep_reflect(engine)

        elif action.action_type == ActionType.REVIEW_SKILL:
            await self._action_review_skill(action, engine)

        elif action.action_type == ActionType.QUIZ_SKILL:
            await self._action_quiz_skill(action, engine)

        elif action.action_type == ActionType.REST:
            # Rest = do nothing, let natural energy recovery happen
            logger.debug("[HEARTBEAT] Resting — energy recovery in progress")

    async def _action_check_goals(self, soul) -> None:
        """Check current goals and identify priorities.

        Sprint 210: Seeds initial goals from soul definition on first call.
        """
        await action_check_goals_impl(self, soul, logger)

    async def _action_browse(self, action, soul, engine) -> None:
        """Browse content based on interests. Delegates to social_browser."""
        await action_browse_impl(self, action, soul, engine)

    async def _action_learn(self, soul, engine) -> None:
        """Learn about a topic from wants_to_learn list."""
        await action_learn_impl(soul, engine, logger)

    async def _action_reflect(self, engine) -> None:
        """Trigger self-reflection using the Reflector.

        Sprint 210: Actually calls Reflector.reflect() instead of just firing event.
        """
        await action_reflect_impl(engine, logger)

    async def _action_journal(self, engine) -> None:
        """Write daily journal entry."""
        await action_journal_impl(engine)

    async def _action_check_weather(self) -> None:
        """Check weather and cache for briefing use."""
        await action_check_weather_impl(logger)

    async def _action_send_briefing(self, engine) -> None:
        """Compose and deliver a scheduled briefing."""
        await action_send_briefing_impl(logger)

    async def _action_reengage(self, action: HeartbeatAction, engine) -> None:
        """Send a re-engagement proactive message to an inactive user.

        Sprint 208: Uses ProactiveMessenger with anti-spam guardrails.
        """
        await action_reengage_impl(action, logger)

    async def _action_deep_reflect(self, engine) -> None:
        """Perform weekly deep reflection and propose goals."""
        await action_deep_reflect_impl(engine)

    async def _action_review_skill(self, action: HeartbeatAction, engine) -> None:
        """Review a skill due for spaced repetition — generate and self-evaluate quiz."""
        await action_review_skill_impl(self, action, engine, logger)

    async def _action_quiz_skill(self, action: HeartbeatAction, engine) -> None:
        """Dedicated quiz action — same as review but explicitly requested."""
        await self._action_review_skill(action, engine)

    async def _self_answer_quiz(self, questions) -> list:
        """Use local LLM to self-answer quiz questions (simulate student)."""
        return await self_answer_quiz_impl(questions)

    def _is_morning(self) -> bool:
        """Check if it's morning hours (05-07 UTC+7)."""
        now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
        return 5 <= now_vn.hour < 7

    def _is_briefing_time(self) -> bool:
        """Check if it's time for any briefing (morning/midday/evening)."""
        now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
        hour = now_vn.hour
        return (6 <= hour < 7) or (12 <= hour < 13) or (20 <= hour < 21)

    def _is_reflection_time(self) -> bool:
        """Check if it's time for daily reflection (21:00-22:00 UTC+7)."""
        now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
        return 21 <= now_vn.hour <= 22

    async def _save_emotional_snapshot(self, engine) -> None:
        """Persist current emotional state to database."""
        from app.engine.living_agent.heartbeat_runtime_support import save_emotional_snapshot_impl

        await save_emotional_snapshot_impl(engine)

    # =========================================================================
    # Sprint 171: Approval gate helpers
    # =========================================================================

    async def _queue_pending_actions(self, actions: List[HeartbeatAction]) -> None:
        """Queue actions to wiii_pending_actions table for human approval."""
        # organization_id / get_effective_org_id behavior lives in runtime support.
        from app.engine.living_agent.heartbeat_runtime_support import queue_pending_actions_impl

        await queue_pending_actions_impl(actions)

    async def _load_pending_action(self, action_id: str) -> Optional[dict]:
        """Load a pending action from DB if it has 'approved' status, scoped by org."""
        # org_where_clause is preserved in runtime support to keep org isolation intact.
        from app.engine.living_agent.heartbeat_runtime_support import load_pending_action_impl

        return await load_pending_action_impl(action_id)

    async def _mark_action_completed(self, action_id: str) -> None:
        """Mark a pending action as completed after execution, scoped by org."""
        from app.engine.living_agent.heartbeat_runtime_support import mark_action_completed_impl

        await mark_action_completed_impl(action_id)

    # =========================================================================
    # Sprint 171: Audit logging
    # =========================================================================

    async def _save_heartbeat_audit(self, result: HeartbeatResult) -> None:
        """Persist heartbeat cycle result to wiii_heartbeat_audit table."""
        # organization_id / get_effective_org_id are handled in runtime support.
        from app.engine.living_agent.heartbeat_runtime_support import save_heartbeat_audit_impl

        await save_heartbeat_audit_impl(self._heartbeat_count, result)

    # =========================================================================
    # Sprint 171: Rate limiting
    # =========================================================================

    def _check_daily_limit(self) -> bool:
        """Check if daily cycle limit has been reached. Resets at midnight UTC+7."""
        from app.engine.living_agent.heartbeat_runtime_support import check_daily_limit_impl

        return check_daily_limit_impl(self)

    def _is_active_hours(self) -> bool:
        """Check if current time is within configured active hours (UTC+7)."""
        from app.core.config import settings

        now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
        hour = now_vn.hour
        start = settings.living_agent_active_hours_start
        end = settings.living_agent_active_hours_end

        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _is_journal_time(self) -> bool:
        """Check if it's the right time for daily journal (morning or evening).

        Sprint 210: Expanded from evening-only to morning+evening windows.
        """
        now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
        return (8 <= now_vn.hour <= 9) or (20 <= now_vn.hour <= 22)

    # =========================================================================
    # Sprint 208: Autonomy graduation daily check
    # =========================================================================

    async def _check_graduation_daily(self) -> None:
        """Check autonomy graduation once per day (idempotent)."""
        from app.engine.living_agent.heartbeat_runtime_support import check_graduation_daily_impl

        await check_graduation_daily_impl(self)

    # =========================================================================
    # Sprint 213: SoulBridge status broadcast
    # =========================================================================

    async def _broadcast_soul_bridge(self, engine, result: HeartbeatResult) -> None:
        """Broadcast heartbeat status to connected peer souls via SoulBridge."""
        from app.engine.living_agent.heartbeat_runtime_support import broadcast_soul_bridge_impl

        await broadcast_soul_bridge_impl(self._heartbeat_count, engine, result)

    # =========================================================================
    # Sprint 171b: Messenger notification for discoveries
    # =========================================================================

    async def _notify_discovery(self, items: list, topic: str) -> None:
        """Send notification about interesting discoveries via configured channel.

        Called when browsing finds high-relevance items (score > 0.7).
        Uses NotificationDispatcher to route to Messenger/WebSocket/Telegram.
        """
        await notify_discovery_impl(items, topic, logger)


# =============================================================================
# Singleton
# =============================================================================

_scheduler_instance: Optional[HeartbeatScheduler] = None


def get_heartbeat_scheduler() -> HeartbeatScheduler:
    """Get the singleton HeartbeatScheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = HeartbeatScheduler()
    return _scheduler_instance
