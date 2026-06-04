"""
Skill Learner — Browsing→Learning→Quiz→Review pipeline with SM-2 spaced repetition.

Sprint 177: "Học Thật — Nhớ Sâu"

Orchestrates the full learning lifecycle:
    1. Process browsing results → auto-discover skills from high-relevance items
    2. Learn from content → actual article URL+summary → deep notes via local LLM
    3. Generate quizzes → test comprehension via local LLM
    4. Evaluate quizzes → SM-2 grading → update confidence + schedule
    5. Review scheduling → spaced repetition intervals (1d→3d→7d→14d→30d)

Design:
    - Singleton pattern (get_skill_learner())
    - Uses LOCAL MODEL (Ollama) for zero-cost 24/7 operation
    - All state stored in existing wiii_skills.metadata JSON field (no migration)
    - Feature-gated: living_agent_enable_skill_learning=False
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.engine.living_agent.models import (
    BrowsingItem,
    LearningMaterial,
    QuizQuestion,
    QuizResult,
    ReviewSchedule,
    SkillStatus,
    WiiiSkill,
)
from app.engine.living_agent.skill_singleton_registry import (
    get_or_create_registered_skill_builder,
    get_or_create_registered_skill_learner,
    register_skill_learner_factory,
)
from app.engine.semantic_memory.privacy import hash_memory_identifier

logger = logging.getLogger(__name__)

# SM-2 interval steps (days)
_SM2_INITIAL_INTERVALS = [1.0, 3.0, 7.0, 14.0, 30.0]


class SkillLearner:
    """Orchestrates browsing→learning→quiz→review pipeline.

    Usage:
        learner = get_skill_learner()
        # After browsing:
        await learner.process_browsing_results(items, soul_interests)
        # During heartbeat review:
        due = learner.get_skills_due_for_review()
        quiz = await learner.generate_quiz(skill_name)
        result = await learner.evaluate_quiz(skill_name, quiz, answers)
    """

    def process_browsing_results(
        self,
        items: List[BrowsingItem],
        soul_interests: List[str],
    ) -> List[str]:
        """Auto-discover skills from high-relevance browsing items.

        Items with relevance > 0.6 are fed into the skill pipeline.
        Creates LearningMaterial entries in skill metadata for later learning.

        Args:
            items: Browsing results from SocialBrowser.
            soul_interests: Wiii's interest keywords for domain matching.

        Returns:
            List of skill names that received new material.
        """
        builder = get_skill_builder()
        updated_skills: List[str] = []

        for item in items:
            if item.relevance_score < 0.6:
                continue

            # Determine domain from matching interests
            domain = self._match_domain(item, soul_interests)

            # Discover or find existing skill
            skill_name = self._extract_skill_name(item)
            if not skill_name:
                continue

            skill = builder._find_by_name(skill_name)
            if not skill:
                skill = builder.discover(
                    skill_name=skill_name,
                    domain=domain,
                    source=item.url,
                )
                if not skill:
                    continue

            # Add learning material to skill metadata
            material = LearningMaterial(
                url=item.url or "",
                title=item.title,
                summary=item.summary,
                relevance_score=item.relevance_score,
            )
            self._add_material_to_skill(skill, material, builder)
            updated_skills.append(skill_name)

        if updated_skills:
            logger.info(
                "[SKILL_LEARNER] Fed %d skills from %d browsing items",
                len(updated_skills), len(items),
            )

        return updated_skills

    async def learn_from_content(
        self,
        skill_name: str,
        material: LearningMaterial,
    ) -> bool:
        """Learn from actual article content using local LLM for deep notes.

        Unlike generic learn_step(), this uses real article URL+summary to
        generate contextual notes. Confidence boost proportional to content quality.

        Args:
            skill_name: Name of the skill to learn.
            material: Content to learn from.

        Returns:
            True if learning occurred.
        """
        from app.engine.living_agent.local_llm import get_local_llm
        builder = get_skill_builder()
        skill = builder._find_by_name(skill_name)
        if not skill:
            return False

        if skill.status == SkillStatus.MASTERED:
            return False

        # Transition to LEARNING if still DISCOVERED
        if skill.status == SkillStatus.DISCOVERED:
            skill.status = SkillStatus.LEARNING

        llm = get_local_llm()
        prompt = (
            f"Mình đang học về: {skill_name}\n\n"
            f"Bài viết: {material.title}\n"
            f"URL: {material.url}\n"
            f"Tóm tắt: {material.summary[:500]}\n\n"
            f"Ghi chú hiện tại: {skill.notes[:300] if skill.notes else '(chưa có)'}\n\n"
            f"Hãy tạo ghi chú học tập chuyên sâu (150-300 từ) từ bài viết này. "
            f"Tập trung vào kiến thức mới, so sánh với ghi chú cũ, và rút ra bài học thực tế."
        )
        deep_notes = await llm.generate(prompt, temperature=0.4, max_tokens=768)

        if deep_notes:
            material.deep_notes = deep_notes

            # Append to skill notes
            separator = "\n\n---\n\n" if skill.notes else ""
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            skill.notes = (
                f"{skill.notes}{separator}"
                f"[{timestamp}] Nguồn: {material.title}\n{deep_notes}"
            )

            # Add source URL
            if material.url and material.url not in skill.sources:
                skill.sources.append(material.url)

            # Confidence boost proportional to relevance
            boost = 0.05 + 0.1 * material.relevance_score
            skill.confidence = min(1.0, skill.confidence + boost)

            # Check for advancement
            if skill.can_advance():
                skill.advance()
                logger.info(
                    "[SKILL_LEARNER] Advanced skill_hash=%s -> %s",
                    hash_memory_identifier(skill_name),
                    skill.status.value,
                )

            builder._update_skill(skill)
            self._update_skill_metadata(skill, builder)
            logger.debug(
                "[SKILL_LEARNER] Learned from material_hash=%s (confidence=%.2f)",
                hash_memory_identifier(material.title),
                skill.confidence,
            )
            return True

        return False

    async def generate_quiz(
        self,
        skill_name: str,
        num_questions: int = 0,
    ) -> List[QuizQuestion]:
        """Generate quiz questions from accumulated skill notes.

        Uses local LLM to create questions testing comprehension.

        Args:
            skill_name: Skill to quiz on.
            num_questions: Override for question count (0 = use config default).

        Returns:
            List of QuizQuestion objects.
        """
        from app.core.config import settings
        from app.engine.living_agent.local_llm import get_local_llm
        if num_questions <= 0:
            num_questions = settings.living_agent_quiz_questions_per_session

        builder = get_skill_builder()
        skill = builder._find_by_name(skill_name)
        if not skill or not skill.notes:
            return []

        llm = get_local_llm()
        prompt = (
            f"Dựa trên ghi chú sau về chủ đề '{skill_name}':\n\n"
            f"{skill.notes[:1500]}\n\n"
            f"Tạo {num_questions} câu hỏi trắc nghiệm (4 đáp án mỗi câu). "
            f"Trả lời dạng JSON array:\n"
            f'[{{"question": "...", "options": ["A", "B", "C", "D"], '
            f'"correct_answer": "A", "explanation": "...", "difficulty": "medium"}}]\n'
            f"CHỈ trả lời JSON, không giải thích thêm."
        )
        raw = await llm.generate(prompt, temperature=0.3, max_tokens=1024)

        if not raw:
            return []

        return self._parse_quiz_response(raw, skill)

    async def evaluate_quiz(
        self,
        skill_name: str,
        questions: List[QuizQuestion],
        answers: List[str],
    ) -> Optional[QuizResult]:
        """Evaluate quiz answers, update confidence via EMA, update SM-2 schedule.

        Args:
            skill_name: Skill being quizzed.
            questions: The quiz questions.
            answers: User/self-test answers (same order as questions).

        Returns:
            QuizResult with score and quality factor.
        """
        from app.core.config import settings
        if not questions or not answers:
            return None

        builder = get_skill_builder()
        skill = builder._find_by_name(skill_name)
        if not skill:
            return None

        # Grade answers
        correct = 0
        for q, a in zip(questions, answers):
            if a.strip().lower() == q.correct_answer.strip().lower():
                correct += 1

        total = len(questions)
        score = correct / total if total > 0 else 0.0

        # SM-2 quality factor (0-1 mapped from score)
        quality = score

        result = QuizResult(
            skill_name=skill_name,
            questions_total=total,
            questions_correct=correct,
            score=score,
            quality_factor=quality,
        )

        # Update confidence via EMA
        alpha = settings.living_agent_review_confidence_weight
        skill.confidence = alpha * score + (1 - alpha) * skill.confidence
        skill.confidence = max(0.0, min(1.0, skill.confidence))

        # Update SM-2 review schedule
        self.update_review_schedule(skill, quality)

        # Record quiz in metadata
        quiz_history = skill.metadata.get("quiz_history", [])
        quiz_history.append({
            "score": score,
            "correct": correct,
            "total": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        skill.metadata["quiz_history"] = quiz_history[-10:]  # Keep last 10

        # Update usage tracking
        skill.usage_count += 1
        skill.last_practiced = datetime.now(timezone.utc)

        # Check for advancement
        if skill.can_advance():
            skill.advance()

        builder._update_skill(skill)
        self._update_skill_metadata(skill, builder)

        logger.info(
            "[SKILL_LEARNER] Quiz skill_hash=%s - %d/%d correct (%.0f%%), confidence=%.2f",
            hash_memory_identifier(skill_name),
            correct,
            total,
            score * 100,
            skill.confidence,
        )
        return result

    def get_skills_due_for_review(self) -> List[WiiiSkill]:
        """Get skills whose SM-2 review schedule is due.

        Returns:
            List of WiiiSkill objects that need review.
        """
        builder = get_skill_builder()
        # Get all skills in learning/practicing/evaluating stages
        all_skills = builder.get_all_skills()
        now = datetime.now(timezone.utc)

        due_skills = []
        for skill in all_skills:
            if skill.status in (SkillStatus.MASTERED, SkillStatus.ARCHIVED, SkillStatus.DISCOVERED):
                continue

            schedule_data = skill.metadata.get("review_schedule")
            if not schedule_data:
                # No schedule yet — due for first review if has notes
                if skill.notes:
                    due_skills.append(skill)
                continue

            next_review_str = schedule_data.get("next_review_at")
            if not next_review_str:
                due_skills.append(skill)
                continue

            try:
                next_review = datetime.fromisoformat(next_review_str)
                # Make aware if naive
                if next_review.tzinfo is None:
                    next_review = next_review.replace(tzinfo=timezone.utc)
                if now >= next_review:
                    due_skills.append(skill)
            except (ValueError, TypeError):
                due_skills.append(skill)

        return due_skills

    def update_review_schedule(self, skill: WiiiSkill, quality: float) -> None:
        """Update SM-2 spaced repetition schedule based on quiz quality.

        SM-2 algorithm:
        - quality >= 0.6: advance interval (multiply by ease_factor)
        - quality < 0.6: reset to interval 1 day
        - ease_factor adjusts: EF' = EF + (0.1 - (1 - q) * (0.08 + (1 - q) * 0.02))
        - ease_factor minimum: 1.3

        Args:
            skill: The skill to update schedule for.
            quality: Quiz quality factor (0.0 to 1.0).
        """
        schedule_data = skill.metadata.get("review_schedule", {})
        schedule = ReviewSchedule(
            next_review_at=None,
            interval_days=schedule_data.get("interval_days", 1.0),
            ease_factor=schedule_data.get("ease_factor", 2.5),
            repetition_count=schedule_data.get("repetition_count", 0),
        )

        if quality >= 0.6:
            # Successful review — advance
            schedule.repetition_count += 1
            if schedule.repetition_count == 1:
                schedule.interval_days = 1.0
            elif schedule.repetition_count == 2:
                schedule.interval_days = 3.0
            else:
                schedule.interval_days = schedule.interval_days * schedule.ease_factor
            # Cap at 30 days
            schedule.interval_days = min(30.0, schedule.interval_days)
        else:
            # Failed review — reset
            schedule.repetition_count = 0
            schedule.interval_days = 1.0

        # Update ease factor (SM-2 formula)
        q = quality
        ef_delta = 0.1 - (1 - q) * (0.08 + (1 - q) * 0.02)
        schedule.ease_factor = max(1.3, schedule.ease_factor + ef_delta)

        # Set next review time
        schedule.next_review_at = datetime.now(timezone.utc) + timedelta(
            days=schedule.interval_days
        )

        # Persist in metadata
        skill.metadata["review_schedule"] = {
            "next_review_at": schedule.next_review_at.isoformat(),
            "interval_days": schedule.interval_days,
            "ease_factor": round(schedule.ease_factor, 4),
            "repetition_count": schedule.repetition_count,
        }

    # =========================================================================
    # Private helpers
    # =========================================================================

    @staticmethod
    def _extract_skill_name(item: BrowsingItem) -> str:
        """Extract a concise skill name from browsing item title.

        Simple heuristic: use the first meaningful segment of the title,
        capped at 80 characters.
        """
        title = item.title.strip()
        if not title:
            return ""

        # Remove common prefixes/suffixes
        for noise in ["- YouTube", "| Facebook", "...", "—"]:
            if noise in title:
                title = title.split(noise)[0].strip()

        return title[:80] if title else ""

    @staticmethod
    def _match_domain(item: BrowsingItem, interests: List[str]) -> str:
        """Match browsing item to a domain based on interest keywords."""
        text = f"{item.title} {item.summary}".lower()
        domain_keywords = {
            "maritime": ["maritime", "colregs", "solas", "marpol", "imo", "hàng hải", "tàu"],
            "tech": ["ai", "machine learning", "llm", "python", "programming", "công nghệ"],
            "science": ["research", "discovery", "study", "paper", "khoa học"],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in text for kw in keywords):
                return domain
        return "general"

    @staticmethod
    def _add_material_to_skill(
        skill: WiiiSkill,
        material: LearningMaterial,
        builder,
    ) -> None:
        """Add a LearningMaterial entry to skill.metadata.learning_materials."""
        materials = skill.metadata.get("learning_materials", [])
        # Avoid duplicates by URL
        existing_urls = {m.get("url", "") for m in materials}
        if material.url and material.url in existing_urls:
            return

        materials.append({
            "url": material.url,
            "title": material.title,
            "summary": material.summary[:500],
            "relevance_score": material.relevance_score,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 20 materials
        skill.metadata["learning_materials"] = materials[-20:]
        builder._update_skill(skill)

    @staticmethod
    def _update_skill_metadata(skill: WiiiSkill, builder) -> None:
        """Persist skill metadata changes through SkillBuilder's org guard."""
        try:
            builder.update_skill_metadata(skill)
        except Exception as e:
            logger.warning("[SKILL_LEARNER] Failed to update metadata: %s", e)

    @staticmethod
    def _parse_quiz_response(raw: str, skill: WiiiSkill) -> List[QuizQuestion]:
        """Parse LLM response into QuizQuestion objects."""
        # Try to extract JSON from the response
        raw = raw.strip()

        # Find JSON array boundaries
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return []

        json_str = raw[start:end + 1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.debug("[SKILL_LEARNER] Failed to parse quiz JSON")
            return []

        questions = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                q = QuizQuestion(
                    question=item.get("question", ""),
                    options=item.get("options", []),
                    correct_answer=item.get("correct_answer", ""),
                    explanation=item.get("explanation", ""),
                    difficulty=item.get("difficulty", "medium"),
                    source_url="",
                )
                if q.question and q.options:
                    questions.append(q)
            except Exception:
                continue

        return questions


# =============================================================================
# Singleton
# =============================================================================

def get_skill_learner() -> SkillLearner:
    """Get the singleton SkillLearner instance."""
    learner = get_or_create_registered_skill_learner()
    if learner is None:
        learner = SkillLearner()
    return learner


def get_skill_builder():
    """Get the shared SkillBuilder singleton without a direct module edge."""
    builder = get_or_create_registered_skill_builder()
    return builder


register_skill_learner_factory(SkillLearner)
