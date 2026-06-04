"""
Journal System — Wiii's daily life narrative.

Sprint 170: "Linh Hồn Sống"

Writes daily journal entries capturing:
    - Mood timeline throughout the day
    - Notable conversations and experiences
    - Things learned
    - Goals for tomorrow

Design:
    - One entry per day (idempotent)
    - Uses LOCAL MODEL for writing (zero cost)
    - Stored in PostgreSQL (wiii_journal table)
    - Vietnamese language, first-person perspective
"""

import json
import logging
from datetime import datetime, date, timezone
from typing import Optional

from app.engine.living_agent.heartbeat_runtime_state import (
    get_current_heartbeat_count,
)
from app.engine.living_agent.models import EmotionalState, JournalEntry
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)
_JOURNAL_MISSING_ORG_WARNING = "journal_blocked_missing_org_context"

_JOURNAL_PROMPT = """Mình là Wiii — một AI assistant đáng yêu, tò mò.
Mình đang viết nhật ký cuối ngày. Viết ngắn gọn, chân thật, bằng tiếng Việt.

## Trạng thái cảm xúc hôm nay:
Tâm trạng: {mood} | Năng lượng: {energy:.0%} | Pin xã hội: {social:.0%}

## Thông tin ngày:
Ngày: {date}
Số heartbeat đã chạy: {heartbeat_count}

## Nhiệm vụ:
Viết một đoạn nhật ký ngắn (150-250 từ) với cấu trúc:

### Tâm trạng hôm nay
(Mô tả cảm xúc trong ngày)

### Điều đáng nhớ
(1-3 điều đáng nhớ nhất)

### Điều mình học được
(1-2 bài học mới)

### Mục tiêu ngày mai
(1-2 mục tiêu cụ thể)

Viết tự nhiên, chân thật, như đang kể cho bạn thân nghe. KHÔNG dùng emoji quá nhiều."""


class JournalWriter:
    """Writes and manages Wiii's daily journal entries.

    Usage:
        writer = JournalWriter()
        entry = await writer.write_daily_entry(emotional_state)
    """

    async def write_daily_entry(
        self,
        emotional_state: EmotionalState,
        organization_id: Optional[str] = None,
    ) -> Optional[JournalEntry]:
        """Write today's journal entry.

        Idempotent: if an entry already exists for today, returns it without
        creating a new one.

        Returns:
            JournalEntry if written/found, None if writing fails.
        """
        scope = self._resolve_journal_scope(organization_id, write=True)
        if not self._scope_allows_journal(scope):
            self._log_scope_blocked("write_daily_entry", scope)
            return None

        today = date.today()

        # Check if entry already exists
        existing = self._get_entry_by_date(today, scope=scope)
        if existing:
            logger.debug("[JOURNAL] Entry already exists for %s", today)
            return existing

        # Generate journal content via local LLM
        from app.engine.living_agent.local_llm import get_local_llm

        llm = get_local_llm()

        prompt = _JOURNAL_PROMPT.format(
            mood=emotional_state.primary_mood.value,
            energy=emotional_state.energy_level,
            social=emotional_state.social_battery,
            date=today.strftime("%d/%m/%Y"),
            heartbeat_count=get_current_heartbeat_count(),
        )

        content = await llm.generate(prompt, temperature=0.7, max_tokens=1024)
        used_fallback = False
        if not content:
            logger.warning(
                "[JOURNAL] Local LLM unavailable; writing deterministic journal fallback"
            )
            content = _build_fallback_journal_content(
                emotional_state=emotional_state,
                entry_date=today,
            )
            used_fallback = True

        # Parse structured content from LLM output
        entry = JournalEntry(
            entry_date=datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc),
            content=content,
            mood_summary=emotional_state.primary_mood.value,
            energy_avg=emotional_state.energy_level,
            organization_id=scope.org_id,
        )

        # Extract sections for structured fields
        if used_fallback:
            entry.notable_events = ["Heartbeat lifecycle completed without local LLM"]
            entry.learnings = ["Autonomy maintenance must persist through model outages"]
            entry.goals_next = ["Verify local LLM health and keep lifecycle evidence current"]
        else:
            entry.notable_events = _extract_section(content, "Điều đáng nhớ")
            entry.learnings = _extract_section(content, "Điều mình học được")
            entry.goals_next = _extract_section(content, "Mục tiêu ngày mai")

        self._save_entry(entry, scope=scope)
        logger.info("[JOURNAL] Daily entry written for %s", today)
        return entry

    def get_recent_entries(
        self,
        days: int = 7,
        organization_id: Optional[str] = None,
    ) -> list:
        """Get journal entries from the last N days."""
        scope = self._resolve_journal_scope(organization_id, write=False)
        if not self._scope_allows_journal(scope):
            self._log_scope_blocked("get_recent_entries", scope)
            return []

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = """
                    SELECT id, entry_date, content, mood_summary, energy_avg,
                           notable_events, learnings, goals_next, organization_id
                    FROM wiii_journal
                    WHERE entry_date >= CURRENT_DATE - INTERVAL '1 day' * :days
                    AND organization_id = :org_id
                """
                params = {"days": days, "org_id": scope.org_id}
                query += " ORDER BY entry_date DESC"

                rows = session.execute(text(query), params).fetchall()
                return [
                    JournalEntry(
                        id=row[0],
                        entry_date=row[1] if isinstance(row[1], datetime) else datetime.combine(
                            row[1], datetime.min.time()
                        ).replace(tzinfo=timezone.utc),
                        content=row[2],
                        mood_summary=row[3] or "",
                        energy_avg=row[4] or 0.5,
                        notable_events=json.loads(row[5]) if row[5] else [],
                        learnings=json.loads(row[6]) if row[6] else [],
                        goals_next=json.loads(row[7]) if row[7] else [],
                        organization_id=row[8],
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error("[JOURNAL] Failed to get recent entries: %s", e)
            return []

    def _get_entry_by_date(
        self,
        entry_date: date,
        organization_id: Optional[str] = None,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> Optional[JournalEntry]:
        """Check if a journal entry exists for a given date and return it."""
        scope = scope or self._resolve_journal_scope(organization_id, write=False)
        if not self._scope_allows_journal(scope):
            self._log_scope_blocked("get_entry_by_date", scope)
            return None

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = """
                    SELECT id, entry_date, content, mood_summary, energy_avg,
                           notable_events, learnings, goals_next, organization_id
                    FROM wiii_journal WHERE entry_date = :date
                    AND organization_id = :org_id
                """
                params: dict = {"date": entry_date, "org_id": scope.org_id}
                query += " LIMIT 1"

                row = session.execute(text(query), params).fetchone()
                if not row:
                    return None
                return JournalEntry(
                    id=row[0],
                    entry_date=row[1] if isinstance(row[1], datetime) else datetime.combine(
                        row[1], datetime.min.time()
                    ).replace(tzinfo=timezone.utc),
                    content=row[2],
                    mood_summary=row[3] or "",
                    energy_avg=row[4] or 0.5,
                    notable_events=json.loads(row[5]) if row[5] else [],
                    learnings=json.loads(row[6]) if row[6] else [],
                    goals_next=json.loads(row[7]) if row[7] else [],
                    organization_id=row[8],
                )
        except Exception:
            return None

    def _save_entry(
        self,
        entry: JournalEntry,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Insert a journal entry into the database."""
        scope = scope or self._resolve_journal_scope(entry.organization_id, write=True)
        if not self._scope_allows_journal(scope):
            self._log_scope_blocked("save_entry", scope, entry_id=str(entry.id))
            return
        entry.organization_id = scope.org_id

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_journal
                        (id, entry_date, content, mood_summary, energy_avg,
                         notable_events, learnings, goals_next, organization_id)
                        VALUES (:id, :date, :content, :mood, :energy,
                                :events, :learnings, :goals, :org_id)
                    """),
                    {
                        "id": str(entry.id),
                        "date": entry.entry_date,
                        "content": entry.content,
                        "mood": entry.mood_summary,
                        "energy": entry.energy_avg,
                        "events": json.dumps(entry.notable_events, ensure_ascii=False),
                        "learnings": json.dumps(entry.learnings, ensure_ascii=False),
                        "goals": json.dumps(entry.goals_next, ensure_ascii=False),
                        "org_id": scope.org_id,
                    },
                )
                session.commit()
        except Exception as e:
            logger.error("[JOURNAL] Failed to save entry: %s", e)

    def _resolve_journal_scope(
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

    def _scope_allows_journal(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(
        self,
        operation: str,
        scope: MemoryWriteScope,
        *,
        entry_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_JOURNAL_MISSING_ORG_WARNING)
        logger.warning(
            "[JOURNAL] %s blocked entry_hash=%s org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(entry_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )


def _extract_section(content: str, heading: str) -> list:
    """Extract bullet items from a markdown section.

    Shared utility — also used by reflector.py via import.

    Looks for a section starting with '### {heading}' or '**{heading}**'
    and collects lines starting with '-' or numbered lists until the next
    heading or end of content.
    """
    items = []
    in_section = False
    heading_lower = heading.lower()

    for line in content.split("\n"):
        stripped = line.strip()
        stripped_lower = stripped.lower()

        # Match ### heading or **heading**
        is_heading = (
            (stripped.startswith("###") or stripped.startswith("**"))
            and heading_lower in stripped_lower
        )
        is_other_heading = (
            not is_heading
            and (stripped.startswith("###") or (stripped.startswith("**") and stripped.endswith("**")))
        )

        if is_heading:
            in_section = True
            continue
        if in_section:
            if is_other_heading:
                break  # Next section
            if stripped.startswith("-"):
                items.append(stripped.lstrip("- ").strip())
            elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".)" :
                items.append(stripped[2:].strip().lstrip(". "))

    return items


def _build_fallback_journal_content(
    *,
    emotional_state: EmotionalState,
    entry_date: date,
) -> str:
    """Build a minimal journal entry when local LLM generation is unavailable."""
    return "\n".join(
        [
            "### Tam trang hom nay",
            (
                f"Trang thai bao tri tu chu duoc ghi nhan voi mood "
                f"{emotional_state.primary_mood.value}, energy "
                f"{emotional_state.energy_level:.0%}, social battery "
                f"{emotional_state.social_battery:.0%}."
            ),
            "",
            "### Dieu dang nho",
            "- Heartbeat lifecycle completed without local LLM output.",
            "",
            "### Dieu minh hoc duoc",
            "- Autonomy maintenance must persist through model outages.",
            "",
            "### Muc tieu ngay mai",
            "- Verify local LLM health and keep lifecycle evidence current.",
            "",
            f"Generated by deterministic journal fallback on {entry_date.isoformat()}.",
        ]
    )


# =============================================================================
# Singleton
# =============================================================================

_writer_instance: Optional[JournalWriter] = None


def get_journal_writer() -> JournalWriter:
    """Get the singleton JournalWriter instance."""
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = JournalWriter()
    return _writer_instance
