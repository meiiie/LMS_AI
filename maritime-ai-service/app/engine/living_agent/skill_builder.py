"""Autonomous learning and skill development for Wiii."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.engine.living_agent.models import SkillStatus, WiiiSkill
from app.engine.living_agent.skill_singleton_registry import (
    get_or_create_registered_skill_builder,
    get_or_create_registered_skill_learner,
    register_skill_builder_factory,
)
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)
_SKILL_MISSING_ORG_WARNING = "skill_builder_blocked_missing_org_context"

_SKILL_COLUMNS = """
    id, skill_name, domain, status, confidence, notes, sources,
    usage_count, success_rate, discovered_at, last_practiced, mastered_at,
    organization_id, metadata
"""


class SkillBuilder:
    """Manages Wiii's self-built skill lifecycle."""

    def discover(
        self,
        skill_name: str,
        domain: str = "general",
        source: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[WiiiSkill]:
        """Discover a new skill and add it to org-scoped tracking."""
        from app.core.config import settings

        scope = self._resolve_skill_scope(organization_id, write=True)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("discover", scope, skill_name=skill_name)
            return None

        recent_count = self._count_recent_discoveries(scope=scope)
        if recent_count >= settings.living_agent_max_skills_per_week:
            logger.debug("[SKILL] Weekly discovery limit reached (%d)", recent_count)
            return None

        existing = self._find_by_name(skill_name, scope=scope)
        if existing:
            logger.debug(
                "[SKILL] Skill already tracked skill_hash=%s",
                hash_memory_identifier(skill_name),
            )
            return None

        skill = WiiiSkill(
            skill_name=skill_name,
            domain=domain,
            status=SkillStatus.DISCOVERED,
            sources=[source] if source else [],
            organization_id=scope.org_id,
        )

        self._save_skill(skill, scope=scope)
        logger.info(
            "[SKILL] Discovered skill_hash=%s (domain=%s)",
            hash_memory_identifier(skill_name),
            domain,
        )
        return skill

    async def learn_step(
        self,
        topic: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Execute one local-LLM learning step for an org-scoped topic."""
        scope = self._resolve_skill_scope(organization_id, write=True)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("learn_step", scope, skill_name=topic)
            return False

        skill = self._find_by_name(topic, scope=scope)
        if not skill:
            skill = self.discover(topic, organization_id=scope.org_id)
            if not skill:
                return False

        if skill.status == SkillStatus.MASTERED:
            return False

        if skill.status == SkillStatus.DISCOVERED:
            skill.status = SkillStatus.LEARNING

        from app.engine.living_agent.local_llm import get_local_llm

        llm = get_local_llm()
        prompt = (
            f"Mình là Wiii và mình đang học về: {topic}\n\n"
            f"Ghi chú hiện tại: {skill.notes[:500] if skill.notes else '(chưa có)'}\n\n"
            "Hãy tạo ghi chú học tập ngắn gọn (100-200 từ) về chủ đề này. "
            "Tập trung vào kiến thức cốt lõi và ví dụ thực tế."
        )
        notes = await llm.generate(prompt, temperature=0.5, max_tokens=512)

        if not notes:
            return False

        separator = "\n\n---\n\n" if skill.notes else ""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        skill.notes = f"{skill.notes}{separator}[{timestamp}] {notes}"
        skill.confidence = min(1.0, skill.confidence + 0.1)

        if skill.can_advance():
            skill.advance()
            logger.info(
                "[SKILL] Advanced skill_hash=%s -> %s",
                hash_memory_identifier(topic),
                skill.status.value,
            )

        self._update_skill(skill, scope=scope)
        logger.debug(
            "[SKILL] Learned skill_hash=%s (confidence=%.2f)",
            hash_memory_identifier(topic),
            skill.confidence,
        )
        return True

    def record_usage(
        self,
        skill_name: str,
        success: bool = True,
        organization_id: Optional[str] = None,
    ) -> None:
        """Record successful or failed use of a skill in the current org."""
        scope = self._resolve_skill_scope(organization_id, write=True)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("record_usage", scope, skill_name=skill_name)
            return

        skill = self._find_by_name(skill_name, scope=scope)
        if not skill:
            return

        skill.usage_count += 1
        skill.last_practiced = datetime.now(timezone.utc)

        alpha = 0.3
        new_success = 1.0 if success else 0.0
        skill.success_rate = alpha * new_success + (1 - alpha) * skill.success_rate

        if skill.status == SkillStatus.LEARNING and skill.can_advance():
            skill.advance()

        if skill.status == SkillStatus.PRACTICING and skill.can_advance():
            skill.advance()
        if skill.status == SkillStatus.EVALUATING and skill.confidence >= 0.8:
            skill.advance()
            logger.info(
                "[SKILL] Mastered skill_hash=%s",
                hash_memory_identifier(skill_name),
            )

        self._update_skill(skill, scope=scope)

    def get_all_skills(
        self,
        status: Optional[SkillStatus] = None,
        domain: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> List[WiiiSkill]:
        """Get all tracked skills, optionally filtered."""
        scope = self._resolve_skill_scope(organization_id, write=False)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("get_all_skills", scope)
            return []
        return self._query_skills(status=status, domain=domain, scope=scope)

    def get_active_learning(
        self,
        organization_id: Optional[str] = None,
    ) -> List[WiiiSkill]:
        """Get skills currently being learned or practiced."""
        scope = self._resolve_skill_scope(organization_id, write=False)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("get_active_learning", scope)
            return []
        learning = self._query_skills(status=SkillStatus.LEARNING, scope=scope)
        practicing = self._query_skills(status=SkillStatus.PRACTICING, scope=scope)
        return learning + practicing

    async def learn_from_material(self, topic: str, material) -> bool:
        """Learn from actual content material via SkillLearner."""
        learner = get_skill_learner()
        return await learner.learn_from_content(topic, material)

    def get_skills_for_review(self) -> List[WiiiSkill]:
        """Get skills due for spaced repetition review."""
        learner = get_skill_learner()
        return learner.get_skills_due_for_review()

    def update_skill_metadata(
        self,
        skill: WiiiSkill,
        organization_id: Optional[str] = None,
    ) -> None:
        """Persist skill metadata JSON changes to the current org row."""
        scope = self._resolve_skill_scope(organization_id or skill.organization_id, write=True)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked(
                "update_skill_metadata",
                scope,
                skill_name=skill.skill_name,
                skill_id=str(skill.id),
            )
            return
        skill.organization_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        UPDATE wiii_skills SET
                            metadata = :meta,
                            updated_at = NOW()
                        WHERE id = :id
                        AND organization_id = :org_id
                    """),
                    {
                        "id": str(skill.id),
                        "org_id": scope.org_id,
                        "meta": json.dumps(skill.metadata, ensure_ascii=False),
                    },
                )
                session.commit()
        except Exception as e:
            logger.error("[SKILL] Failed to update skill metadata: %s", e)

    # =========================================================================
    # Database operations
    # =========================================================================

    def _save_skill(
        self,
        skill: WiiiSkill,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Insert a new skill into the database."""
        scope = scope or self._resolve_skill_scope(skill.organization_id, write=True)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("save_skill", scope, skill_name=skill.skill_name)
            return
        skill.organization_id = scope.org_id

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_skills
                        (id, skill_name, domain, status, confidence, notes, sources,
                         usage_count, success_rate, discovered_at, organization_id, metadata)
                        VALUES (:id, :name, :domain, :status, :confidence, :notes, :sources,
                                :usage, :rate, :discovered, :org_id, :meta)
                    """),
                    {
                        "id": str(skill.id),
                        "name": skill.skill_name,
                        "domain": skill.domain,
                        "status": skill.status.value,
                        "confidence": skill.confidence,
                        "notes": skill.notes,
                        "sources": json.dumps(skill.sources, ensure_ascii=False),
                        "usage": skill.usage_count,
                        "rate": skill.success_rate,
                        "discovered": skill.discovered_at,
                        "org_id": scope.org_id,
                        "meta": json.dumps(skill.metadata, ensure_ascii=False),
                    },
                )
                session.commit()
        except Exception as e:
            logger.error("[SKILL] Failed to save skill: %s", e)

    def _update_skill(
        self,
        skill: WiiiSkill,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Update an existing skill in the database."""
        scope = scope or self._resolve_skill_scope(skill.organization_id, write=True)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked(
                "update_skill",
                scope,
                skill_name=skill.skill_name,
                skill_id=str(skill.id),
            )
            return
        skill.organization_id = scope.org_id

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        UPDATE wiii_skills SET
                            status = :status, confidence = :confidence, notes = :notes,
                            sources = :sources, usage_count = :usage, success_rate = :rate,
                            last_practiced = :practiced, mastered_at = :mastered,
                            metadata = :meta, updated_at = NOW()
                        WHERE id = :id
                        AND organization_id = :org_id
                    """),
                    {
                        "id": str(skill.id),
                        "org_id": scope.org_id,
                        "status": skill.status.value,
                        "confidence": skill.confidence,
                        "notes": skill.notes,
                        "sources": json.dumps(skill.sources, ensure_ascii=False),
                        "usage": skill.usage_count,
                        "rate": skill.success_rate,
                        "practiced": skill.last_practiced,
                        "mastered": skill.mastered_at,
                        "meta": json.dumps(skill.metadata, ensure_ascii=False),
                    },
                )
                session.commit()
        except Exception as e:
            logger.error("[SKILL] Failed to update skill: %s", e)

    def _find_by_name(
        self,
        name: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> Optional[WiiiSkill]:
        """Find a skill by name, scoped by org_id."""
        scope = scope or self._resolve_skill_scope(None, write=False)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("find_by_name", scope, skill_name=name)
            return None

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                row = session.execute(
                    text(f"""
                        SELECT {_SKILL_COLUMNS}
                        FROM wiii_skills
                        WHERE LOWER(skill_name) = LOWER(:name)
                        AND organization_id = :org_id
                        LIMIT 1
                    """),
                    {"name": name, "org_id": scope.org_id},
                ).fetchone()
                if row:
                    return self._row_to_skill(row)
        except Exception as e:
            logger.error("[SKILL] Failed to find skill: %s", e)
        return None

    def _query_skills(
        self,
        status: Optional[SkillStatus] = None,
        domain: Optional[str] = None,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> List[WiiiSkill]:
        """Query skills with optional filters, scoped by org_id."""
        scope = scope or self._resolve_skill_scope(None, write=False)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("query_skills", scope)
            return []

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = f"""
                    SELECT {_SKILL_COLUMNS}
                    FROM wiii_skills
                    WHERE organization_id = :org_id
                """
                params: dict[str, Any] = {"org_id": scope.org_id}

                if status:
                    query += " AND status = :status"
                    params["status"] = status.value
                if domain:
                    query += " AND domain = :domain"
                    params["domain"] = domain
                query += " ORDER BY discovered_at DESC"

                rows = session.execute(text(query), params).fetchall()
                return [self._row_to_skill(r) for r in rows]
        except Exception as e:
            logger.error("[SKILL] Failed to query skills: %s", e)
            return []

    def _count_recent_discoveries(
        self,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> int:
        """Count skills discovered in the last 7 days, scoped by org_id."""
        scope = scope or self._resolve_skill_scope(None, write=False)
        if not self._scope_allows_skills(scope):
            self._log_scope_blocked("count_recent_discoveries", scope)
            return 0

        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                result = session.execute(
                    text("""
                        SELECT COUNT(*) FROM wiii_skills
                        WHERE discovered_at >= NOW() - INTERVAL '7 days'
                        AND organization_id = :org_id
                    """),
                    {"org_id": scope.org_id},
                ).scalar()
                return result or 0
        except Exception:
            return 0

    def _resolve_skill_scope(
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

    def _scope_allows_skills(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(
        self,
        operation: str,
        scope: MemoryWriteScope,
        *,
        skill_name: Optional[str] = None,
        skill_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_SKILL_MISSING_ORG_WARNING)
        logger.warning(
            "[SKILL] %s blocked skill_hash=%s skill_id_hash=%s org_hash=%s "
            "org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(skill_name),
            hash_memory_identifier(skill_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    @staticmethod
    def _row_to_skill(row) -> WiiiSkill:
        """Convert a database row to WiiiSkill model."""
        return WiiiSkill(
            id=SkillBuilder._row_get(row, 0),
            skill_name=SkillBuilder._row_get(row, 1, ""),
            domain=SkillBuilder._row_get(row, 2) or "general",
            status=SkillBuilder._status_from_row(row),
            confidence=SkillBuilder._row_get(row, 4) or 0.0,
            notes=SkillBuilder._row_get(row, 5) or "",
            sources=SkillBuilder._json_list(SkillBuilder._row_get(row, 6)),
            usage_count=SkillBuilder._row_get(row, 7) or 0,
            success_rate=SkillBuilder._row_get(row, 8) or 0.0,
            discovered_at=SkillBuilder._row_get(row, 9),
            last_practiced=SkillBuilder._row_get(row, 10),
            mastered_at=SkillBuilder._row_get(row, 11),
            organization_id=SkillBuilder._row_get(row, 12),
            metadata=SkillBuilder._json_dict(SkillBuilder._row_get(row, 13)),
        )

    @staticmethod
    def _row_get(row, index: int, default: Any = None) -> Any:
        try:
            return row[index]
        except (IndexError, KeyError, TypeError):
            return default

    @staticmethod
    def _status_from_row(row) -> SkillStatus:
        value = SkillBuilder._row_get(row, 3)
        try:
            return SkillStatus(value) if value else SkillStatus.DISCOVERED
        except ValueError:
            return SkillStatus.DISCOVERED

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @staticmethod
    def _json_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}


# =============================================================================
# Singleton
# =============================================================================


def get_skill_builder() -> SkillBuilder:
    """Get the singleton SkillBuilder instance."""
    builder = get_or_create_registered_skill_builder()
    if builder is None:
        builder = SkillBuilder()
    return builder


def get_skill_learner():
    """Get the shared SkillLearner singleton without a direct module edge."""
    learner = get_or_create_registered_skill_learner()
    return learner


register_skill_builder_factory(SkillBuilder)
