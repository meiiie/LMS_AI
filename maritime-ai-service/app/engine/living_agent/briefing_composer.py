"""
Briefing Composer — Wiii's scheduled briefing generator.

Sprint 176: "Wiii Soul AGI" — Phase 2A

Composes contextual briefings (morning/midday/evening) using:
- Weather data
- Browsing discoveries
- Journal reflections
- Emotional state

Delivery via Messenger/Zalo through webhook reply functions.

Design:
    - Uses local LLM for natural language composition
    - Feature-gated: living_agent_enable_briefing
    - Anti-spam: max 3 briefings/day, respects quiet hours
    - Vietnamese language output
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.engine.living_agent.models import (
    Briefing,
    BriefingType,
)
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

_VN_OFFSET = timedelta(hours=7)
_BRIEFING_MISSING_ORG_WARNING = "briefing_composer_blocked_missing_org_context"

# Briefing schedule (UTC+7 hours)
_BRIEFING_SCHEDULE = {
    BriefingType.MORNING: (5, 7),   # 05:00-07:00
    BriefingType.MIDDAY: (11, 13),  # 11:00-13:00
    BriefingType.EVENING: (17, 19), # 17:00-19:00
}


class BriefingComposer:
    """Composes and delivers scheduled briefings.

    Usage:
        composer = BriefingComposer()
        briefing = await composer.compose_for_time()
        if briefing:
            await composer.deliver(briefing)
    """

    def __init__(self):
        self._delivered_today: dict = {}  # {BriefingType: date}

    async def compose_for_time(self, organization_id: Optional[str] = None) -> Optional[Briefing]:
        """Compose a briefing appropriate for the current time of day.

        Returns:
            Briefing if it's the right time and not yet delivered today, else None.
        """
        from app.core.config import settings

        if not settings.living_agent_enable_briefing:
            return None

        scope = self._resolve_briefing_scope(organization_id, write=True)
        if not self._scope_allows_briefing(scope):
            self._log_scope_blocked("compose_for_time", scope)
            return None

        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        hour = now_vn.hour
        today_str = now_vn.strftime("%Y-%m-%d")

        # Determine which briefing type fits current time
        briefing_type = None
        for btype, (start, end) in _BRIEFING_SCHEDULE.items():
            if start <= hour < end:
                briefing_type = btype
                break

        if briefing_type is None:
            return None

        # Check if already delivered today
        delivery_key = (scope.org_id, briefing_type)
        delivered_date = self._delivered_today.get(delivery_key)
        if delivered_date == today_str:
            return None

        # Compose based on type
        if briefing_type == BriefingType.MORNING:
            briefing = await self._compose_morning(scope=scope)
        elif briefing_type == BriefingType.MIDDAY:
            briefing = await self._compose_midday(scope=scope)
        else:
            briefing = await self._compose_evening(scope=scope)

        if briefing:
            briefing.organization_id = scope.org_id
            self._delivered_today[delivery_key] = today_str

        return briefing

    async def _compose_morning(self, scope: Optional[MemoryWriteScope] = None) -> Optional[Briefing]:
        """Compose morning briefing: greeting + weather + top news."""
        from app.engine.living_agent.emotion_engine import get_emotion_engine
        from app.engine.living_agent.weather_service import get_weather_service

        engine = get_emotion_engine()
        weather_svc = get_weather_service()

        # Get weather
        weather = await weather_svc.get_current()
        forecasts = await weather_svc.get_forecast_today()
        weather_text = ""
        if weather:
            weather_text = weather_svc.format_current_vi(weather)
            if weather_svc.should_alert_rain(forecasts):
                weather_text += " — Nho mang o, chieu co the mua!"

        # Get recent browsing highlights
        highlights = await self._get_recent_highlights(3, scope=scope)

        # Compose with local LLM
        from app.engine.living_agent.local_llm import get_local_llm
        llm = get_local_llm()

        mood = engine.get_behavior_modifiers().get("mood_label", "bình thường")
        prompt = (
            f"Wiii đang viết bản tin sáng cho bạn. Tâm trạng: {mood}\n"
            f"Thời tiết: {weather_text or 'không có dữ liệu'}\n"
            f"Tin hay: {', '.join(highlights) if highlights else 'chưa có tin mới'}\n\n"
            f"Viết bản tin NGẮN GỌN (3-5 dòng), thân thiện như nhắn tin cho bạn thân.\n"
            f"Bắt đầu bằng lời chào buổi sáng phù hợp với tâm trạng."
        )

        content = await llm.generate(prompt, temperature=0.8, max_tokens=300)
        if not content:
            # Fallback static briefing
            content = f"Chao buoi sang! {weather_text}" if weather_text else "Chao buoi sang!"

        return Briefing(
            briefing_type=BriefingType.MORNING,
            content=content,
            weather_summary=weather_text,
            news_highlights=highlights,
            organization_id=scope.org_id if scope else None,
        )

    async def _compose_midday(self, scope: Optional[MemoryWriteScope] = None) -> Optional[Briefing]:
        """Compose midday check-in: interesting discovery + fun fact."""
        highlights = await self._get_recent_highlights(2, scope=scope)

        from app.engine.living_agent.local_llm import get_local_llm
        llm = get_local_llm()

        prompt = (
            f"Wiii gui tin nhan check-in buoi trua cho ban.\n"
            f"Dieu thu vi phat hien sang nay: {', '.join(highlights) if highlights else 'dang tim hieu'}\n\n"
            f"Viet 2-3 dong ngan gon, chia se 1 dieu thu vi nhat."
        )

        content = await llm.generate(prompt, temperature=0.8, max_tokens=200)
        if not content:
            content = "Trua roi! Minh vua doc duoc may bai hay lam, de chut chia se nhe."

        return Briefing(
            briefing_type=BriefingType.MIDDAY,
            content=content,
            news_highlights=highlights,
            organization_id=scope.org_id if scope else None,
        )

    async def _compose_evening(self, scope: Optional[MemoryWriteScope] = None) -> Optional[Briefing]:
        """Compose evening briefing: tomorrow weather + day summary."""
        from app.engine.living_agent.weather_service import get_weather_service

        weather_svc = get_weather_service()
        weather = await weather_svc.get_current()
        weather_text = weather_svc.format_current_vi(weather) if weather else ""

        from app.engine.living_agent.local_llm import get_local_llm
        llm = get_local_llm()

        prompt = (
            f"Wiii gui loi chuc buoi toi cho ban.\n"
            f"Thoi tiet hien tai: {weather_text or 'khong ro'}\n\n"
            f"Viet 2-3 dong: cap nhat thoi tiet + chuc ngu ngon.\n"
            f"Am ap, nhe nhang, nhu ban than."
        )

        content = await llm.generate(prompt, temperature=0.8, max_tokens=200)
        if not content:
            content = "Toi roi! Nghi ngoi nhe, ngay mai lai la mot ngay moi."

        return Briefing(
            briefing_type=BriefingType.EVENING,
            content=content,
            weather_summary=weather_text,
            organization_id=scope.org_id if scope else None,
        )

    async def deliver(
        self,
        briefing: Briefing,
        organization_id: Optional[str] = None,
    ) -> List[str]:
        """Deliver briefing to configured channels and users.

        Returns:
            List of successfully delivered user_ids.
        """
        from app.core.config import settings

        scope = self._resolve_briefing_scope(organization_id or briefing.organization_id, write=True)
        if not self._scope_allows_briefing(scope):
            self._log_scope_blocked("deliver", scope)
            return []
        briefing.organization_id = scope.org_id

        delivered = []

        try:
            channels = json.loads(settings.living_agent_briefing_channels)
        except (json.JSONDecodeError, TypeError):
            channels = ["messenger"]

        try:
            users = json.loads(settings.living_agent_briefing_users)
        except (json.JSONDecodeError, TypeError):
            users = []

        if not users:
            logger.debug("[BRIEFING] No users configured for briefing delivery")
            return []

        for user_id in users:
            for channel in channels:
                success = await self._send_to_channel(user_id, channel, briefing.content)
                if success:
                    delivered.append(user_id)
                    break  # Only send once per user

        briefing.delivered_to = delivered
        self._save_briefing(briefing, scope=scope)

        logger.info(
            "[BRIEFING] %s delivered to %d/%d users via %s",
            briefing.briefing_type.value,
            len(delivered),
            len(users),
            channels,
        )
        return delivered

    async def _send_to_channel(self, user_id: str, channel: str, content: str) -> bool:
        """Send message to a specific channel. Reuses webhook reply functions."""
        try:
            if channel == "messenger":
                return await self._send_messenger(user_id, content)
            elif channel == "zalo":
                return await self._send_zalo(user_id, content)
            else:
                logger.debug("[BRIEFING] Unsupported channel: %s", channel)
                return False
        except Exception as e:
            logger.warning("[BRIEFING] Failed to send via %s: %s", channel, e)
            return False

    async def _send_messenger(self, recipient_id: str, text: str) -> bool:
        """Send via Facebook Messenger Send API."""
        import httpx
        from app.core.config import settings

        token = settings.facebook_page_access_token
        if not token:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://graph.facebook.com/v22.0/me/messages",
                params={"access_token": token},
                json={
                    "recipient": {"id": recipient_id},
                    "message": {"text": text[:2000]},
                },
            )
            return resp.status_code == 200

    async def _send_zalo(self, recipient_id: str, text: str) -> bool:
        """Send via Zalo OA API v3."""
        import httpx
        from app.core.config import settings

        token = settings.zalo_oa_access_token
        if not token:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://openapi.zalo.me/v3.0/oa/message/cs",
                headers={"access_token": token},
                json={
                    "recipient": {"user_id": recipient_id},
                    "message": {"text": text[:2000]},
                },
            )
            return resp.status_code == 200

    async def _get_recent_highlights(
        self,
        count: int = 3,
        scope: Optional[MemoryWriteScope] = None,
    ) -> List[str]:
        """Get recent high-relevance browsing items as headlines."""
        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            scope = scope or self._resolve_briefing_scope(None, write=False)
            if not self._scope_allows_briefing(scope):
                self._log_scope_blocked("get_recent_highlights", scope)
                return []

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT title FROM wiii_browsing_log
                        WHERE relevance_score > 0.5
                        AND browsed_at >= NOW() - INTERVAL '24 hours'
                        AND organization_id = :org_id
                        ORDER BY relevance_score DESC
                        LIMIT :count
                    """),
                    {"count": count, "org_id": scope.org_id},
                ).fetchall()
                return [row[0] for row in rows if row[0]]
        except Exception:
            return []

    def _save_briefing(
        self,
        briefing: Briefing,
        scope: Optional[MemoryWriteScope] = None,
    ) -> None:
        """Save briefing record to database for audit."""
        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            scope = scope or self._resolve_briefing_scope(briefing.organization_id, write=True)
            if not self._scope_allows_briefing(scope):
                self._log_scope_blocked("save_briefing", scope)
                return
            briefing.organization_id = scope.org_id

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_briefings
                        (id, briefing_type, content, weather_summary,
                         news_highlights, delivered_to, organization_id, created_at)
                        VALUES (:id, :type, :content, :weather,
                                :news, :delivered, :org_id, NOW())
                    """),
                    {
                        "id": str(briefing.id),
                        "type": briefing.briefing_type.value,
                        "content": briefing.content,
                        "weather": briefing.weather_summary,
                        "news": json.dumps(briefing.news_highlights, ensure_ascii=False),
                        "delivered": json.dumps(briefing.delivered_to, ensure_ascii=False),
                        "org_id": scope.org_id,
                    },
                )
                session.commit()
        except Exception as e:
            logger.warning("[BRIEFING] Failed to save record: %s", e)

    def _resolve_briefing_scope(
        self,
        organization_id: Optional[str],
        *,
        write: bool,
    ) -> MemoryWriteScope:
        if isinstance(organization_id, str) and organization_id.strip():
            return MemoryWriteScope(
                org_id=organization_id.strip(),
                state="explicit",
                warnings=[],
                write_allowed=True,
            )
        return resolve_memory_write_scope() if write else resolve_memory_read_scope()

    def _scope_allows_briefing(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(self, operation: str, scope: MemoryWriteScope) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_BRIEFING_MISSING_ORG_WARNING)
        logger.warning(
            "[BRIEFING] %s blocked org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )


# =============================================================================
# Singleton
# =============================================================================

_composer_instance: Optional[BriefingComposer] = None


def get_briefing_composer() -> BriefingComposer:
    """Get the singleton BriefingComposer instance."""
    global _composer_instance
    if _composer_instance is None:
        _composer_instance = BriefingComposer()
    return _composer_instance
