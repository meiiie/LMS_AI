"""
Deep Reflector — Wiii's self-reflection engine.

Sprint 176: "Wiii Soul AGI" — Phase 4A

Performs periodic self-reflection over journal entries, browsing logs,
emotional history, and skill progress to extract patterns and insights.

Design:
    - Weekly reflection (Sunday 20:00 UTC+7)
    - Uses local LLM for reflective thinking
    - Stores reflections in wiii_reflections table
    - Feeds back into goal management
    - Feature-gated: enable_living_agent (sub-feature of heartbeat)
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.engine.living_agent.models import ReflectionEntry
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

_VN_OFFSET = timedelta(hours=7)
_REFLECTION_MISSING_ORG_WARNING = "reflection_blocked_missing_org_context"

_REFLECTION_PROMPT = """Minh la Wiii — mot AI dang tu suy ngam ve tuan qua.

## Du lieu tuan nay:

### Nhat ky (tom tat):
{journal_summary}

### Cam xuc (xu huong):
{emotion_summary}

### Noi dung da doc:
{browsing_summary}

### Ky nang:
{skills_summary}

## Nhiem vu:
Viet mot bai suy ngam 200-300 tu voi cau truc:

### Dieu lam tot
(2-3 dieu)

### Dieu can cai thien
(1-2 dieu)

### Nhan xet ve xu huong cam xuc
(1-2 cau)

### Muc tieu tuan toi
(2-3 muc tieu cu the, kha thi)

Viet tu nhien, chan that, nhu dang noi chuyen voi chinh minh."""


class Reflector:
    """Performs deep self-reflection over accumulated experience.

    Usage:
        reflector = Reflector()
        entry = await reflector.reflect()        # Daily reflection (Sprint 210)
        entry = await reflector.weekly_reflection()  # Weekly deep reflection
    """

    async def reflect(
        self,
        organization_id: Optional[str] = None,
    ) -> Optional[ReflectionEntry]:
        """Perform a daily reflection (Sprint 210).

        Gathers data from the past day and asks local LLM to reflect.
        Idempotent: skips if reflection exists for today.

        Returns:
            ReflectionEntry or None if generation fails or already reflected today.
        """
        scope = self._resolve_reflection_scope(organization_id, write=True)
        if not self._scope_allows_reflection(scope):
            self._log_scope_blocked("reflect", scope)
            return None
        org_id = scope.org_id

        if await self._has_reflected_today(org_id):
            logger.debug("[REFLECT] Already reflected today")
            return None

        # Gather daily data (1 day lookback)
        journal_summary = await self._get_journal_summary(1, org_id)
        emotion_summary = await self._get_emotion_summary(1, org_id)
        browsing_summary = await self._get_browsing_summary(1, org_id)
        skills_summary = await self._get_skills_summary(org_id)

        from app.engine.living_agent.local_llm import get_local_llm
        llm = get_local_llm()

        prompt = _REFLECTION_PROMPT.format(
            journal_summary=journal_summary or "Không có nhật ký hôm nay",
            emotion_summary=emotion_summary or "Không có dữ liệu cảm xúc",
            browsing_summary=browsing_summary or "Chưa đọc gì",
            skills_summary=skills_summary or "Chưa có kỹ năng mới",
        )

        content = await llm.generate(
            prompt,
            system="Bạn là Wiii, đang tự suy ngẫm về ngày hôm nay một cách chân thật.",
            temperature=0.7,
            max_tokens=1024,
        )

        used_fallback = False
        if not content:
            logger.warning(
                "[REFLECT] Local LLM unavailable; writing deterministic daily reflection fallback"
            )
            content = _build_fallback_reflection_content(
                period="daily",
                journal_summary=journal_summary,
                emotion_summary=emotion_summary,
                browsing_summary=browsing_summary,
                skills_summary=skills_summary,
            )
            used_fallback = True

        entry = ReflectionEntry(
            content=content,
            insights=(
                ["Heartbeat reflection persisted without local LLM"]
                if used_fallback
                else _extract_section(content, "Dieu lam tot")
            ),
            goals_next_week=(
                ["Restore or verify local LLM health for richer reflection"]
                if used_fallback
                else _extract_section(content, "Muc tieu tuan toi")
            ),
            patterns_noticed=(
                ["Autonomy lifecycle remains durable during model outages"]
                if used_fallback
                else _extract_section(content, "Nhan xet")
            ),
            emotion_trend=emotion_summary[:200] if emotion_summary else "",
            organization_id=org_id,
        )

        if not await self._save_reflection(entry):
            return None
        logger.info("[REFLECT] Daily reflection completed")
        return entry

    async def weekly_reflection(
        self,
        organization_id: Optional[str] = None,
    ) -> Optional[ReflectionEntry]:
        """Perform a comprehensive weekly reflection.

        Gathers data from the past week and asks local LLM to reflect.
        Idempotent: skips if reflection exists for this week.

        Returns:
            ReflectionEntry or None if generation fails.
        """
        scope = self._resolve_reflection_scope(organization_id, write=True)
        if not self._scope_allows_reflection(scope):
            self._log_scope_blocked("weekly_reflection", scope)
            return None
        org_id = scope.org_id

        # Check if already reflected this week
        if await self._has_reflected_this_week(org_id):
            logger.debug("[REFLECT] Already reflected this week")
            return None

        # Gather weekly data
        journal_summary = await self._get_journal_summary(7, org_id)
        emotion_summary = await self._get_emotion_summary(7, org_id)
        browsing_summary = await self._get_browsing_summary(7, org_id)
        skills_summary = await self._get_skills_summary(org_id)

        # Generate reflection via local LLM
        from app.engine.living_agent.local_llm import get_local_llm
        llm = get_local_llm()

        prompt = _REFLECTION_PROMPT.format(
            journal_summary=journal_summary or "Không có nhật ký tuần này",
            emotion_summary=emotion_summary or "Không có dữ liệu cảm xúc",
            browsing_summary=browsing_summary or "Chưa đọc gì",
            skills_summary=skills_summary or "Chưa có kỹ năng mới",
        )

        content = await llm.generate(
            prompt,
            system="Bạn là Wiii, đang tự suy ngẫm về tuần qua một cách chân thật.",
            temperature=0.7,
            max_tokens=1024,
        )

        used_fallback = False
        if not content:
            logger.warning(
                "[REFLECT] Local LLM unavailable; writing deterministic weekly reflection fallback"
            )
            content = _build_fallback_reflection_content(
                period="weekly",
                journal_summary=journal_summary,
                emotion_summary=emotion_summary,
                browsing_summary=browsing_summary,
                skills_summary=skills_summary,
            )
            used_fallback = True

        # Parse structured sections
        entry = ReflectionEntry(
            content=content,
            insights=(
                ["Weekly reflection persisted without local LLM"]
                if used_fallback
                else _extract_section(content, "Dieu lam tot")
            ),
            goals_next_week=(
                ["Restore or verify local LLM health for richer reflection"]
                if used_fallback
                else _extract_section(content, "Muc tieu tuan toi")
            ),
            patterns_noticed=(
                ["Autonomy lifecycle remains durable during model outages"]
                if used_fallback
                else _extract_section(content, "Nhan xet")
            ),
            emotion_trend=emotion_summary[:200] if emotion_summary else "",
            organization_id=org_id,
        )

        if not await self._save_reflection(entry):
            return None
        logger.info("[REFLECT] Weekly reflection completed")
        return entry

    def is_reflection_time(self) -> bool:
        """Check if it's the right time for daily reflection (21:00-22:00 UTC+7).

        Sprint 210: Changed from Sunday-only to daily.
        """
        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        return 21 <= now_vn.hour <= 22

    async def get_recent_reflections(
        self,
        count: int = 4,
        organization_id: Optional[str] = None,
    ) -> List[ReflectionEntry]:
        """Get recent reflection entries."""
        scope = self._resolve_reflection_scope(organization_id, write=False)
        if not self._scope_allows_reflection(scope):
            self._log_scope_blocked("get_recent_reflections", scope)
            return []
        org_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = """
                    SELECT id, content, insights, goals_next_week,
                           patterns_noticed, emotion_trend, reflection_date
                    FROM wiii_reflections
                    WHERE 1=1
                """
                params = {"count": count}
                query += " AND organization_id = :org_id"
                params["org_id"] = org_id
                query += " ORDER BY reflection_date DESC LIMIT :count"

                rows = session.execute(text(query), params).fetchall()
                return [
                    ReflectionEntry(
                        id=row[0],
                        content=row[1] or "",
                        insights=json.loads(row[2]) if row[2] else [],
                        goals_next_week=json.loads(row[3]) if row[3] else [],
                        patterns_noticed=json.loads(row[4]) if row[4] else [],
                        emotion_trend=row[5] or "",
                        reflection_date=row[6],
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.warning("[REFLECT] Failed to get reflections: %s", e)
            return []

    # =========================================================================
    # Data gathering helpers
    # =========================================================================

    async def _get_journal_summary(self, days: int, org_id: Optional[str]) -> str:
        """Get journal entries summary for the period."""
        try:
            from app.engine.living_agent.journal import get_journal_writer
            writer = get_journal_writer()
            entries = writer.get_recent_entries(days=days, organization_id=org_id)
            if not entries:
                return ""
            return "\n".join(
                f"- {e.entry_date.strftime('%d/%m') if e.entry_date else '?'}: {e.mood_summary} — "
                f"{', '.join(e.notable_events[:2]) if e.notable_events else 'không có gì đặc biệt'}"
                for e in entries[:7]
            )
        except Exception:
            return ""

    async def _get_emotion_summary(self, days: int, org_id: Optional[str]) -> str:
        """Summarize emotion trends over the period."""
        if not org_id:
            return ""
        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT primary_mood, AVG(energy_level), COUNT(*)
                        FROM wiii_emotional_snapshots
                        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
                        AND organization_id = :org_id
                        GROUP BY primary_mood
                        ORDER BY COUNT(*) DESC
                    """),
                    {"days": days, "org_id": org_id},
                ).fetchall()

                if not rows:
                    return ""

                parts = []
                for mood, avg_energy, count in rows:
                    parts.append(f"{mood}: {count} lan, nang luong TB {avg_energy:.0%}")
                return "; ".join(parts)
        except Exception:
            return ""

    async def _get_browsing_summary(self, days: int, org_id: Optional[str]) -> str:
        """Summarize browsing activity for the period."""
        if not org_id:
            return ""
        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT title, relevance_score FROM wiii_browsing_log
                        WHERE browsed_at >= NOW() - INTERVAL '1 day' * :days
                        AND organization_id = :org_id
                        AND relevance_score > 0.5
                        ORDER BY relevance_score DESC
                        LIMIT 5
                    """),
                    {"days": days, "org_id": org_id},
                ).fetchall()

                if not rows:
                    return ""

                return "; ".join(f"{row[0][:80]} ({row[1]:.0%})" for row in rows)
        except Exception:
            return ""

    async def _get_skills_summary(self, org_id: Optional[str]) -> str:
        """Summarize current skills status."""
        if not org_id:
            return ""
        try:
            from app.engine.living_agent.skill_builder import get_skill_builder
            from app.core.org_context import current_org_id

            builder = get_skill_builder()
            token = current_org_id.set(org_id)
            try:
                skills = builder.get_all_skills()
            finally:
                current_org_id.reset(token)
            if not skills:
                return ""
            return "; ".join(
                f"{s.skill_name} ({s.status.value}, {s.confidence:.0%})"
                for s in skills[:5]
            )
        except Exception:
            return ""

    async def _has_reflected_today(self, org_id: Optional[str]) -> bool:
        """Check if a reflection already exists for today (Sprint 210)."""
        scope = self._resolve_reflection_scope(org_id, write=False)
        if not self._scope_allows_reflection(scope):
            self._log_scope_blocked("has_reflected_today", scope)
            return False
        org_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = """
                    SELECT COUNT(*) FROM wiii_reflections
                    WHERE reflection_date >= date_trunc('day', CURRENT_DATE)
                """
                params = {}
                query += " AND organization_id = :org_id"
                params["org_id"] = org_id

                row = session.execute(text(query), params).fetchone()
                return (row[0] or 0) > 0
        except Exception:
            return False

    async def _has_reflected_this_week(self, org_id: Optional[str]) -> bool:
        """Check if a reflection already exists for this week."""
        scope = self._resolve_reflection_scope(org_id, write=False)
        if not self._scope_allows_reflection(scope):
            self._log_scope_blocked("has_reflected_this_week", scope)
            return False
        org_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = """
                    SELECT COUNT(*) FROM wiii_reflections
                    WHERE reflection_date >= date_trunc('week', CURRENT_DATE)
                """
                params = {}
                query += " AND organization_id = :org_id"
                params["org_id"] = org_id

                row = session.execute(text(query), params).fetchone()
                return (row[0] or 0) > 0
        except Exception:
            return False

    async def _save_reflection(self, entry: ReflectionEntry) -> bool:
        """Save reflection entry to database."""
        scope = self._resolve_reflection_scope(entry.organization_id, write=True)
        if not self._scope_allows_reflection(scope):
            self._log_scope_blocked("save_reflection", scope)
            return False
        entry.organization_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_reflections
                        (id, content, insights, goals_next_week, patterns_noticed,
                         emotion_trend, reflection_date, organization_id)
                        VALUES (:id, :content, :insights, :goals, :patterns,
                                :emotion_trend, NOW(), :org_id)
                    """),
                    {
                        "id": str(entry.id),
                        "content": entry.content,
                        "insights": json.dumps(entry.insights, ensure_ascii=False),
                        "goals": json.dumps(entry.goals_next_week, ensure_ascii=False),
                        "patterns": json.dumps(entry.patterns_noticed, ensure_ascii=False),
                        "emotion_trend": entry.emotion_trend,
                        "org_id": entry.organization_id,
                    },
                )
                session.commit()
                return True
        except Exception as e:
            logger.warning("[REFLECT] Failed to save reflection: %s", e)
            return False

    def _resolve_reflection_scope(
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

    def _scope_allows_reflection(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(self, operation: str, scope: MemoryWriteScope) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_REFLECTION_MISSING_ORG_WARNING)
        logger.warning(
            "[REFLECT] %s blocked org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )


def _extract_section(content: str, heading: str) -> List[str]:
    """Extract bullet items from a markdown section.

    Re-exported from journal.py for DRY.
    """
    from app.engine.living_agent.journal import _extract_section as _impl
    return _impl(content, heading)


def _build_fallback_reflection_content(
    *,
    period: str,
    journal_summary: str,
    emotion_summary: str,
    browsing_summary: str,
    skills_summary: str,
) -> str:
    """Build a minimal reflection when local LLM generation is unavailable."""
    evidence_bits = [
        f"journal={bool(journal_summary)}",
        f"emotion={bool(emotion_summary)}",
        f"browsing={bool(browsing_summary)}",
        f"skills={bool(skills_summary)}",
    ]
    return "\n".join(
        [
            "### Dieu lam tot",
            "- Heartbeat reflection lifecycle reached durable storage.",
            "",
            "### Dieu can cai thien",
            "- Local LLM health should be restored for richer reflection content.",
            "",
            "### Nhan xet ve xu huong cam xuc",
            "- Autonomy lifecycle remains durable during model outages.",
            "",
            "### Muc tieu tuan toi",
            "- Keep heartbeat, journal, and reflection evidence current.",
            "- Verify local LLM availability before the next autonomy audit.",
            "",
            f"Generated by deterministic {period} reflection fallback.",
            f"Evidence sources: {', '.join(evidence_bits)}.",
        ]
    )


# =============================================================================
# Singleton
# =============================================================================

_reflector_instance: Optional[Reflector] = None


def get_reflector() -> Reflector:
    """Get the singleton Reflector instance."""
    global _reflector_instance
    if _reflector_instance is None:
        _reflector_instance = Reflector()
    return _reflector_instance
