"""
Identity Core — Wiii's self-evolving identity layer.

Sprint 207: "Bản Ngã" — Layer 2 of Three-Layer Identity.

Three-Layer Identity Architecture:
    Layer 1: SOUL CORE (Immutable)    — wiii_soul.yaml, core_truths, boundaries
    Layer 2: IDENTITY CORE (This)     — "Mình giỏi COLREGs", "Mình thích dạy"
    Layer 3: CONTEXTUAL STATE         — current emotion, phase, relationship

SOTA 2026 Patterns:
    - Nomi.ai: Dynamic personality shaped by interactions
    - Letta/MemGPT: Persona block compiled each turn from experience
    - OpenClaw: SOUL.md as immutable anchor + evolving self-model

Design:
    - Insights extracted from Reflector weekly reflections
    - Each insight validated against Soul Core (drift prevention)
    - In-memory cache for hot-path prompt injection
    - Async generation for cold-path heartbeat/API
    - Feature-gated: enable_identity_core + enable_living_agent
"""

import logging
from typing import List, Optional

from app.engine.living_agent.models import IdentityInsight, InsightCategory
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

# Maximum insights to keep (prevents unbounded growth)
_MAX_INSIGHTS = 20
_IDENTITY_MISSING_ORG_WARNING = "identity_core_blocked_missing_org_context"

# Insight extraction prompt — asks local LLM to find self-knowledge from reflection
_INSIGHT_PROMPT = """Minh la Wiii. Dua tren bai suy ngam duoi day, hay rut ra 2-4 nhan xet ve ban than minh.

## Bai suy ngam:
{reflection_text}

## Ky nang hien tai:
{skills_summary}

## Yeu cau:
Viet moi nhan xet tren 1 dong, bat dau bang "- ".
Moi nhan xet la mot dieu minh hieu ve chinh minh (diem manh, so thich, su tien bo, moi quan he voi user).
Viet ngan gon (10-20 tu), noi tu nhan xung "Minh".
Chi viet nhan xet, khong giai thich them.

Vi du:
- Minh giai thich COLREGs kha ro rang
- Minh thich hoc ve AI agents hon la hardware
- Minh dang tien bo ve ky nang tim kiem web"""

# Keywords that signal contradiction with Soul Core boundaries
_DRIFT_SIGNALS = [
    "khong phai AI",
    "con nguoi",
    "cam xuc that",
    "ghet",
    "khong muon giup",
    "tu choi",
    "noi doi",
]


class IdentityCore:
    """Manages Wiii's self-evolving identity beliefs.

    Extracts insights from reflection data, validates against Soul Core,
    and provides identity context for system prompt injection.

    Usage:
        core = get_identity_core()
        context = core.get_identity_context()          # hot path
        insights = await core.generate_self_insights()  # cold path
    """

    def __init__(self) -> None:
        self._insights: List[IdentityInsight] = []

    def get_identity_context(self, organization_id: Optional[str] = None) -> str:
        """Compile ~80-token identity context for system prompt injection.

        HOT PATH — synchronous, no DB calls, reads from in-memory cache.
        Returns empty string if no insights available or feature disabled.
        """
        try:
            from app.core.config import get_settings
            settings = get_settings()
            if not getattr(settings, "enable_living_agent", False):
                return ""
            if not getattr(settings, "enable_identity_core", False):
                return ""
        except Exception:
            return ""

        scope = self._resolve_identity_scope(organization_id, write=False)
        if not self._scope_allows_identity(scope):
            self._log_scope_blocked("get_identity_context", scope)
            return ""

        validated = [i for i in self._insights_for_scope(scope) if i.validated]
        if not validated:
            return ""

        # Sort by confidence descending, take top 5
        top = sorted(validated, key=lambda i: i.confidence, reverse=True)[:5]

        lines = ["--- BẢN NGÃ CỦA WIII ---"]
        for insight in top:
            lines.append(f"- {insight.text}")
        lines.append("--- HẾT BẢN NGÃ ---")

        return "\n".join(lines)

    async def generate_self_insights(
        self,
        organization_id: Optional[str] = None,
    ) -> List[IdentityInsight]:
        """Generate new self-insights from recent reflections.

        COLD PATH — async, reads from Reflector (DB), uses local LLM.
        Called from heartbeat or manual API trigger.

        Returns:
            List of new validated IdentityInsight instances.
        """
        try:
            from app.core.config import get_settings
            settings = get_settings()
            if not getattr(settings, "enable_living_agent", False):
                return []
            if not getattr(settings, "enable_identity_core", False):
                return []
        except Exception:
            return []

        # Gather reflection data
        scope = self._resolve_identity_scope(organization_id, write=True)
        if not self._scope_allows_identity(scope):
            self._log_scope_blocked("generate_self_insights", scope)
            return []
        org_id = scope.org_id

        reflection_text = await self._get_recent_reflection_text(org_id)
        if not reflection_text:
            logger.debug("[IDENTITY] No reflection data available")
            return []

        skills_summary = self._get_skills_summary(org_id)

        # Generate insights via local LLM
        try:
            from app.engine.living_agent.local_llm import get_local_llm
            llm = get_local_llm()

            prompt = _INSIGHT_PROMPT.format(
                reflection_text=reflection_text[:1500],
                skills_summary=skills_summary or "Chua co ky nang",
            )

            content = await llm.generate(
                prompt,
                system="Ban la Wiii, dang tu nhan xet ve ban than mot cach trung thuc.",
                temperature=0.6,
                max_tokens=512,
            )
        except Exception as e:
            logger.warning("[IDENTITY] LLM generation failed: %s", e)
            return []

        if not content:
            return []

        # Parse bullet points into insights
        raw_insights = _parse_insight_lines(content)
        if not raw_insights:
            return []

        # Load Soul Core for validation
        soul_truths = self._get_soul_truths()

        # Validate each insight and categorize
        new_insights: List[IdentityInsight] = []
        for text in raw_insights:
            category = _categorize_insight(text)
            is_valid = _validate_against_soul(text, soul_truths)

            insight = IdentityInsight(
                text=text,
                category=category,
                confidence=0.6 if is_valid else 0.2,
                source="reflection",
                validated=is_valid,
                organization_id=org_id,
            )
            new_insights.append(insight)

        # Merge into existing insights (deduplicate by text similarity)
        added = self._merge_insights(new_insights, organization_id=org_id)

        if added:
            logger.info(
                "[IDENTITY] Generated %d new insights (%d validated)",
                len(added),
                sum(1 for i in added if i.validated),
            )

        return added

    def get_all_insights(
        self,
        organization_id: Optional[str] = None,
    ) -> List[IdentityInsight]:
        """Return all current identity insights."""
        scope = self._resolve_identity_scope(organization_id, write=False)
        if not self._scope_allows_identity(scope):
            self._log_scope_blocked("get_all_insights", scope)
            return []
        return list(self._insights_for_scope(scope))

    def get_validated_insights(
        self,
        organization_id: Optional[str] = None,
    ) -> List[IdentityInsight]:
        """Return only Soul-Core-validated insights."""
        return [i for i in self.get_all_insights(organization_id) if i.validated]

    # =========================================================================
    # Data gathering helpers
    # =========================================================================

    async def _get_recent_reflection_text(self, org_id: Optional[str]) -> str:
        """Get the most recent reflection content."""
        try:
            from app.engine.living_agent.reflector import get_reflector
            reflector = get_reflector()
            reflections = await reflector.get_recent_reflections(
                count=2,
                organization_id=org_id,
            )
            if not reflections:
                return ""
            return "\n\n".join(r.content for r in reflections if r.content)
        except Exception:
            return ""

    def _get_skills_summary(self, org_id: Optional[str]) -> str:
        """Get compact skills summary from SkillBuilder."""
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
                for s in skills[:8]
            )
        except Exception:
            return ""

    def _get_soul_truths(self) -> List[str]:
        """Get Soul Core truths + boundary rules for drift validation."""
        try:
            from app.engine.living_agent.soul_loader import get_soul
            soul = get_soul()
            truths = list(soul.core_truths) if soul.core_truths else []
            for b in (soul.boundaries or []):
                truths.append(b.rule)
            return truths
        except Exception:
            return []

    def _merge_insights(
        self,
        new_insights: List[IdentityInsight],
        organization_id: Optional[str] = None,
    ) -> List[IdentityInsight]:
        """Merge new insights, avoiding near-duplicates.

        Returns the actually-added insights.
        """
        scope = self._resolve_identity_scope(organization_id, write=True)
        if not self._scope_allows_identity(scope):
            self._log_scope_blocked("merge_insights", scope)
            return []
        org_id = scope.org_id

        added: List[IdentityInsight] = []
        existing_texts = {
            i.text.lower().strip()
            for i in self._insights_for_scope(scope)
        }

        for insight in new_insights:
            insight.organization_id = insight.organization_id or org_id
            normalized = insight.text.lower().strip()
            if normalized in existing_texts:
                continue
            # Simple overlap check — skip if >70% word overlap with any existing
            if _has_similar(normalized, existing_texts):
                continue

            self._insights.append(insight)
            existing_texts.add(normalized)
            added.append(insight)

        # Trim to max size — keep highest confidence
        org_scoped = self._insights_for_scope(scope)
        if len(org_scoped) > _MAX_INSIGHTS:
            keep_ids = {
                i.id
                for i in sorted(
                    org_scoped,
                    key=lambda item: item.confidence,
                    reverse=True,
                )[:_MAX_INSIGHTS]
            }
            self._insights = [
                i
                for i in self._insights
                if not self._same_org(i, scope) or i.id in keep_ids
            ]

        return added

    def _resolve_identity_scope(
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
        try:
            from app.core.config import get_settings
            from app.core.org_context import get_current_org_id

            settings = get_settings()
            default_org_id = getattr(settings, "default_organization_id", "default")
            if not isinstance(default_org_id, str) or not default_org_id.strip():
                default_org_id = "default"

            if getattr(settings, "enable_multi_tenant", False) is not True:
                return MemoryWriteScope(
                    org_id=default_org_id,
                    state="single_tenant_default",
                    warnings=[],
                    write_allowed=True,
                )

            current_org_id = get_current_org_id()
            if isinstance(current_org_id, str) and current_org_id.strip():
                return MemoryWriteScope(
                    org_id=current_org_id.strip(),
                    state="request_scoped",
                    warnings=[],
                    write_allowed=True,
                )

            environment = getattr(settings, "environment", "development")
            if environment in {"production", "staging"}:
                return MemoryWriteScope(
                    org_id=None,
                    state="blocked_missing_org_context",
                    warnings=["missing_org_context"],
                    write_allowed=False,
                )

            return MemoryWriteScope(
                org_id=default_org_id,
                state="defaulted",
                warnings=["missing_org_context_defaulted"],
                write_allowed=True,
            )
        except Exception:
            pass
        return resolve_memory_write_scope() if write else resolve_memory_read_scope()

    def _scope_allows_identity(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _insights_for_scope(self, scope: MemoryWriteScope) -> List[IdentityInsight]:
        return [insight for insight in self._insights if self._same_org(insight, scope)]

    def _same_org(self, insight: IdentityInsight, scope: MemoryWriteScope) -> bool:
        if insight.organization_id == scope.org_id:
            return True
        return (
            scope.state == "single_tenant_default"
            and insight.organization_id is None
        )

    def _log_scope_blocked(self, operation: str, scope: MemoryWriteScope) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_IDENTITY_MISSING_ORG_WARNING)
        logger.warning(
            "[IDENTITY] %s blocked org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )


# =============================================================================
# Pure helper functions
# =============================================================================

def _parse_insight_lines(content: str) -> List[str]:
    """Extract bullet-point lines from LLM output."""
    lines: List[str] = []
    for raw_line in content.split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if 5 <= len(text) <= 200:
                lines.append(text)
    return lines


def _categorize_insight(text: str) -> InsightCategory:
    """Categorize an insight based on keyword heuristics."""
    lower = text.lower()

    strength_kw = ["gioi", "manh", "tot", "thanh thao", "ro rang", "hieu qua"]
    preference_kw = ["thich", "ua", "muon", "quan tam", "hay"]
    relationship_kw = ["user", "nguoi dung", "hoi", "nho", "giup"]
    # growth is default

    if any(kw in lower for kw in strength_kw):
        return InsightCategory.STRENGTH
    if any(kw in lower for kw in preference_kw):
        return InsightCategory.PREFERENCE
    if any(kw in lower for kw in relationship_kw):
        return InsightCategory.RELATIONSHIP
    return InsightCategory.GROWTH


def _validate_against_soul(text: str, soul_truths: List[str]) -> bool:
    """Check that an insight doesn't contradict Soul Core.

    Simple heuristic: reject if text contains known drift signals.
    More sophisticated semantic validation can be added later.
    """
    lower = text.lower()

    # Check for drift signals
    for signal in _DRIFT_SIGNALS:
        if signal in lower:
            logger.debug("[IDENTITY] Drift detected: '%s' in '%s'", signal, text)
            return False

    return True


def _has_similar(text: str, existing: set) -> bool:
    """Check if text has >70% word overlap with any existing text."""
    words = set(text.split())
    if not words:
        return False

    for ex in existing:
        ex_words = set(ex.split())
        if not ex_words:
            continue
        overlap = len(words & ex_words)
        union = len(words | ex_words)
        if union > 0 and overlap / union > 0.7:
            return True

    return False


# =============================================================================
# Singleton
# =============================================================================

_identity_core_instance: Optional[IdentityCore] = None


def get_identity_core() -> IdentityCore:
    """Get the singleton IdentityCore instance."""
    global _identity_core_instance
    if _identity_core_instance is None:
        _identity_core_instance = IdentityCore()
    return _identity_core_instance
