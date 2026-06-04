"""
Runtime support for HeartbeatScheduler action handlers.

Keeps heartbeat.py focused on orchestration while preserving the public
HeartbeatScheduler method surface for tests and patching.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any

from app.engine.living_agent.models import HeartbeatAction, LifeEvent, LifeEventType


async def action_check_goals_impl(scheduler, soul, logger_obj) -> None:
    """Check current goals and seed from soul on first use."""
    from app.engine.living_agent.goal_manager import get_goal_manager

    manager = get_goal_manager()

    if not hasattr(scheduler, "_goals_seeded"):
        try:
            seeded = await manager.seed_initial_goals(soul)
            if seeded:
                logger_obj.info("[HEARTBEAT] Seeded %d initial goals from soul", seeded)
        except Exception as exc:
            logger_obj.debug("[HEARTBEAT] Goal seeding failed: %s", exc)
        scheduler._goals_seeded = True

    try:
        goals = await manager.get_active_goals()
        logger_obj.debug("[HEARTBEAT] Active goals: %d", len(goals))
    except Exception:
        logger_obj.debug(
            "[HEARTBEAT] Checking goals: %d short-term, %d long-term",
            len(soul.short_term_goals),
            len(soul.long_term_goals),
        )


async def action_browse_impl(scheduler, action, soul, engine) -> None:
    """Browse content based on interests and emit discoveries."""
    from app.engine.living_agent.social_browser import get_social_browser

    browser = get_social_browser()
    items = await browser.browse_feed(
        topic=action.target,
        interests=soul.interests.primary + soul.interests.exploring,
        max_items=5,
    )

    if not items:
        return

    engine.process_event(
        LifeEvent(
            event_type=LifeEventType.BROWSED_CONTENT,
            description=f"Browsed {len(items)} items about {action.target}",
            importance=0.3,
        )
    )

    high_relevance = [item for item in items if item.relevance_score > 0.7]
    if high_relevance:
        engine.process_event(
            LifeEvent(
                event_type=LifeEventType.INTERESTING_DISCOVERY,
                description=high_relevance[0].title[:200],
                importance=0.7,
            )
        )
        await scheduler._notify_discovery(high_relevance[:3], action.target)


async def action_learn_impl(soul, engine, logger_obj) -> None:
    """Learn about a random wanted topic."""
    if not soul.interests.wants_to_learn:
        return

    topic = random.choice(soul.interests.wants_to_learn)
    logger_obj.debug("[HEARTBEAT] Learning about: %s", topic)

    from app.engine.living_agent.skill_builder import get_skill_builder

    builder = get_skill_builder()
    learned = await builder.learn_step(topic)
    if learned:
        engine.process_event(
            LifeEvent(
                event_type=LifeEventType.LEARNED_SOMETHING,
                description=f"Studied: {topic}",
                importance=0.6,
            )
        )


async def action_reflect_impl(engine, logger_obj) -> None:
    """Trigger self-reflection via the reflector."""
    from app.engine.living_agent.reflector import get_reflector

    reflector = get_reflector()
    try:
        entry = await reflector.reflect()
        if entry:
            engine.process_event(
                LifeEvent(
                    event_type=LifeEventType.REFLECTION_COMPLETED,
                    description=f"Reflection: {entry.content[:100]}",
                    importance=0.6,
                )
            )
        else:
            logger_obj.debug("[HEARTBEAT] Reflection skipped (already reflected today or no data)")
    except Exception as exc:
        logger_obj.warning("[HEARTBEAT] Reflection failed: %s", exc)
        engine.process_event(
            LifeEvent(
                event_type=LifeEventType.REFLECTION_COMPLETED,
                description="Periodic self-reflection during heartbeat",
                importance=0.5,
            )
        )


async def action_journal_impl(engine) -> None:
    """Write a daily journal entry."""
    from app.engine.living_agent.journal import get_journal_writer

    writer = get_journal_writer()
    entry = await writer.write_daily_entry(engine.state)
    if entry:
        engine.process_event(
            LifeEvent(
                event_type=LifeEventType.JOURNAL_WRITTEN,
                description="Daily journal entry written",
                importance=0.4,
            )
        )


async def action_check_weather_impl(logger_obj) -> None:
    """Check weather and cache it for later briefing use."""
    from app.engine.living_agent.weather_service import get_weather_service

    service = get_weather_service()
    weather = await service.get_current()
    if weather:
        logger_obj.debug("[HEARTBEAT] Weather: %s, %.1f°C", weather.city, weather.temp)


async def action_send_briefing_impl(logger_obj) -> None:
    """Compose and deliver a scheduled briefing."""
    from app.engine.living_agent.briefing_composer import get_briefing_composer

    composer = get_briefing_composer()
    briefing = await composer.compose_for_time()
    if briefing:
        delivered = await composer.deliver(briefing)
        if delivered:
            logger_obj.info("[HEARTBEAT] Briefing sent to %d users", len(delivered))


async def action_reengage_impl(action: HeartbeatAction, logger_obj) -> None:
    """Send a proactive re-engagement message to an inactive user."""
    user_id = action.target.removeprefix("reengage:")
    if not user_id:
        return

    try:
        from app.engine.living_agent.proactive_messenger import get_proactive_messenger

        messenger = get_proactive_messenger()
        content = (
            "Lâu rồi không thấy bạn ghé chơi! "
            "Mình có vài điều thú vị muốn chia sẻ. Quay lại nói chuyện với mình nhé? 😊"
        )
        channel = action.metadata.get("channel", "messenger") if action.metadata else "messenger"
        sent = await messenger.send(
            user_id=user_id,
            channel=channel,
            content=content,
            trigger="inactive_reengage",
            priority=0.4,
        )
        if sent:
            logger_obj.info("[HEARTBEAT] Re-engagement sent to %s", user_id)
    except Exception as exc:
        logger_obj.debug("[HEARTBEAT] Re-engagement failed: %s", exc)


async def action_deep_reflect_impl(engine) -> None:
    """Perform weekly deep reflection and update goals."""
    from app.core.config import settings
    from app.engine.living_agent.goal_manager import get_goal_manager
    from app.engine.living_agent.reflector import get_reflector

    reflector = get_reflector()
    entry = await reflector.weekly_reflection()
    if not entry:
        return

    engine.process_event(
        LifeEvent(
            event_type=LifeEventType.REFLECTION_COMPLETED,
            description="Weekly deep reflection completed",
            importance=0.7,
        )
    )

    if settings.living_agent_enable_dynamic_goals and entry.goals_next_week:
        manager = get_goal_manager()
        await manager.propose_from_reflection(entry.goals_next_week)

    if settings.living_agent_enable_dynamic_goals:
        manager = get_goal_manager()
        await manager.review_stale_goals()


async def action_review_skill_impl(scheduler, action: HeartbeatAction, engine, logger_obj) -> None:
    """Review a skill via generated quiz and self-evaluation."""
    from app.engine.living_agent.skill_learner import get_skill_learner

    skill_name = action.target
    if not skill_name:
        return

    learner = get_skill_learner()
    logger_obj.debug("[HEARTBEAT] Reviewing skill: %s", skill_name)

    questions = await learner.generate_quiz(skill_name)
    if not questions:
        logger_obj.debug("[HEARTBEAT] No quiz generated for %s", skill_name)
        return

    answers = await scheduler._self_answer_quiz(questions)
    result = await learner.evaluate_quiz(skill_name, questions, answers)
    if result:
        engine.process_event(
            LifeEvent(
                event_type=LifeEventType.QUIZ_COMPLETED,
                description=f"Quiz: {skill_name} — {result.questions_correct}/{result.questions_total}",
                importance=0.6,
            )
        )


async def self_answer_quiz_impl(questions) -> list[str]:
    """Use local LLM to self-answer quiz questions."""
    from app.engine.living_agent.local_llm import get_local_llm

    llm = get_local_llm()
    answers: list[str] = []
    for question in questions:
        prompt = (
            f"Câu hỏi: {question.question}\n"
            f"Đáp án: {', '.join(question.options)}\n"
            f"Trả lời CHỈ bằng đáp án đúng (ví dụ: A hoặc B hoặc C hoặc D). "
            f"Không giải thích."
        )
        answer = await llm.generate(prompt, temperature=0.1, max_tokens=10)
        answers.append(answer.strip() if answer else "")
    return answers


def _format_discovery_notification_message(items: list[Any], topic: str) -> str:
    lines = [f"Wiii t\u00ecm th\u1ea5y {len(items)} n\u1ed9i dung th\u00fa v\u1ecb v\u1ec1 {topic}:"]
    for item in items[:3]:
        title = item.title[:100] if getattr(item, "title", "") else "Kh\u00f4ng c\u00f3 ti\u00eau \u0111\u1ec1"
        url = getattr(item, "url", "") or ""
        relevance_score = getattr(item, "relevance_score", 0)
        score = f" ({relevance_score:.0%})" if relevance_score else ""
        lines.append(f"- {title}{score}")
        if url:
            lines.append(f"  {url}")
    return "\n".join(lines)


async def notify_discovery_impl(items: list[Any], topic: str, logger_obj) -> None:
    """Send notification about interesting discoveries via configured channel."""
    try:
        from app.core.config import settings
        from app.engine.semantic_memory.write_audit import resolve_memory_write_scope

        channel = settings.living_agent_notification_channel
        if channel == "websocket" and not settings.enable_websocket:
            return
        scope = resolve_memory_write_scope()
        if not scope.write_allowed or not scope.org_id:
            warnings = [*scope.warnings]
            if "missing_org_context" in warnings:
                warnings.append("heartbeat_runtime_blocked_missing_org_context")
            logger_obj.warning(
                "[HEARTBEAT] Discovery notification blocked org_scope=%s warnings=%s",
                scope.state,
                sorted(set(warnings)),
            )
            return

        lines = [f"Wiii tìm thấy {len(items)} nội dung thú vị về {topic}:"]
        for item in items[:3]:
            title = item.title[:100] if item.title else "Không có tiêu đề"
            url = item.url or ""
            score = f" ({item.relevance_score:.0%})" if item.relevance_score else ""
            lines.append(f"• {title}{score}")
            if url:
                lines.append(f"  {url}")
        message = _format_discovery_notification_message(items, topic)
        payload = json.dumps(
            {
                "type": "proactive_message",
                "trigger": "heartbeat_discovery",
                "content": message,
                "topic": topic,
                "item_count": len(items),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )

        from app.services.notification_dispatcher import get_notification_dispatcher

        dispatcher = get_notification_dispatcher()
        result = await dispatcher.notify_user(
            user_id="wiii_owner",
            message=payload if channel == "websocket" else message,
            channel=channel,
            metadata={
                "organization_id": scope.org_id,
                "notification_type": "proactive_message",
                "trigger": "heartbeat_discovery",
            },
        )

        if result.get("delivered"):
            logger_obj.info("[HEARTBEAT] Discovery notification sent via %s", channel)
        else:
            logger_obj.debug(
                "[HEARTBEAT] Discovery notification not delivered: %s",
                result.get("detail", "unknown"),
            )
    except Exception as exc:
        logger_obj.debug("[HEARTBEAT] Discovery notification failed: %s", exc)
