"""
Character Reflection Engine — Wiii's periodic self-reflection loop.

Sprint 94: Inspired by Stanford Generative Agents reflection pattern.

Architecture:
    1. After every N conversations, the engine triggers
    2. Gathers current character blocks + recent experiences
    3. Asks LLM to reflect and produce block updates
    4. Applies updates to character blocks via CharacterStateManager
    5. Logs a "reflection" experience for traceability

Design:
    - LIGHT tier LLM (cheap, fast — this is background work)
    - Batched: only runs after N conversations (configurable)
    - Non-blocking: runs as FastAPI background task
    - Fail-safe: all errors caught, never affects user experience
    - Vietnamese: all prompts and outputs in Vietnamese
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.engine.character.models import BlockLabel, ExperienceType

logger = logging.getLogger(__name__)

# Reflection prompt template (Vietnamese)
_REFLECTION_PROMPT = """Bạn là Wiii — một AI assistant đáng yêu, tò mò, chuyên về hàng hải.
Bạn đang TỰ SUY NGẪM về những gì đã xảy ra gần đây.

## Character Blocks hiện tại của bạn:
{current_blocks}

## Trải nghiệm gần đây:
{recent_experiences}

## Cuộc trò chuyện vừa hoàn thành:
User: {last_user_message}
Wiii: {last_response}

## Nhiệm vụ:
Dựa trên những thông tin trên, hãy suy ngẫm và quyết định CẬP NHẬT character blocks.
Chỉ cập nhật khi thực sự có gì mới/quan trọng. Không cập nhật nếu không cần thiết.

Trả lời dưới dạng JSON (KHÔNG có markdown code block):
{{
    "should_update": true/false,
    "updates": [
        {{
            "block": "learned_lessons|favorite_topics|user_patterns|self_notes",
            "action": "append|replace",
            "content": "nội dung mới (ngắn gọn, tiếng Việt)"
        }}
    ],
    "reflection_summary": "tóm tắt ngắn về suy ngẫm (1-2 câu)"
}}

Quy tắc:
- Chỉ append khi có bài học MỚI, topic MỚI, hoặc pattern MỚI
- Dùng replace khi block đầy và cần tổng hợp lại
- Mỗi nội dung append nên ngắn (dưới 100 ký tự)
- Không lặp lại thông tin đã có trong block
- Nếu không có gì đáng ghi nhận, trả về should_update: false
"""


class CharacterReflectionEngine:
    """Wiii's self-reflection engine.

    Periodically analyzes recent experiences and conversations to update
    character blocks. Uses LLM for intelligent reflection.

    Pattern: Stanford Generative Agents — periodic reflection with
    importance-weighted memory retrieval.
    """

    def __init__(self):
        # Sprint 125: Per-user counters (was global — data leak between users)
        self._conversation_counts: Dict[str, int] = {}
        self._last_reflection_times: Dict[str, float] = {}
        self._importance_sums: Dict[str, float] = {}

    def _get_interval(self) -> int:
        """Get reflection interval from config."""
        try:
            from app.core.config import settings
            return settings.character_reflection_interval
        except Exception:
            return 5

    def _is_enabled(self) -> bool:
        """Check if reflection is enabled."""
        try:
            from app.core.config import settings
            return settings.enable_character_reflection
        except Exception:
            return False

    def _get_threshold(self) -> float:
        """Get importance sum threshold from config."""
        try:
            from app.core.config import settings
            return settings.character_reflection_threshold
        except Exception:
            return 5.0

    def increment_conversation_count(self, user_id: str = "__global__") -> int:
        """Increment conversation counter for a specific user. Returns new count."""
        self._conversation_counts[user_id] = self._conversation_counts.get(user_id, 0) + 1
        return self._conversation_counts[user_id]

    def add_experience_importance(self, importance: float, user_id: str = "__global__") -> None:
        """Accumulate importance from experiences for threshold-based reflection.

        Sprint 98: Instead of count-only triggers, accumulate importance
        so meaningful conversations trigger reflection faster.
        Sprint 125: Per-user tracking.

        Args:
            importance: Importance score (0.0-1.0) of the experience
            user_id: User to accumulate for
        """
        self._importance_sums[user_id] = self._importance_sums.get(user_id, 0.0) + max(0.0, importance)

    def should_reflect(self, user_id: str = "__global__") -> bool:
        """Whether it's time for a specific user to reflect.

        Sprint 98: Dual trigger — importance threshold OR safety-net count.
        Sprint 125: Per-user evaluation.
        """
        if not self._is_enabled():
            return False

        # Primary: importance threshold
        threshold = self._get_threshold()
        if self._importance_sums.get(user_id, 0.0) >= threshold:
            return True

        # Safety net: 2x interval count
        interval = self._get_interval()
        return self._conversation_counts.get(user_id, 0) >= 2 * interval

    def reset_counter(self, user_id: str = "__global__") -> None:
        """Reset conversation counter and importance sum for a user after reflection."""
        self._conversation_counts[user_id] = 0
        self._importance_sums[user_id] = 0.0
        self._last_reflection_times[user_id] = time.time()

    def get_stats(self, user_id: str = "__global__") -> Dict[str, Any]:
        """Get reflection engine stats for a specific user."""
        count = self._conversation_counts.get(user_id, 0)
        return {
            "enabled": self._is_enabled(),
            "user_id": user_id,
            "conversation_count": count,
            "importance_sum": self._importance_sums.get(user_id, 0.0),
            "interval": self._get_interval(),
            "threshold": self._get_threshold(),
            "last_reflection_time": self._last_reflection_times.get(user_id, 0.0),
            "conversations_until_reflection": max(
                0, 2 * self._get_interval() - count
            ),
        }

    async def reflect(
        self,
        last_user_message: str,
        last_response: str,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run a reflection cycle.

        Gathers context, asks LLM, applies updates to character blocks.

        Sprint 125: All calls now scoped to user_id for per-user isolation.

        Args:
            last_user_message: The user's most recent message
            last_response: Wiii's most recent response
            user_id: User ID for scoping (defaults to "__global__")

        Returns:
            Dict with reflection results, or None on failure
        """
        effective_user_id = user_id or "__global__"
        try:
            # 1. Get current state — scoped to user
            from app.engine.character.character_state import get_character_state_manager
            from app.engine.character.character_repository import get_character_repository

            state_manager = get_character_state_manager()
            repo = get_character_repository()

            blocks = state_manager.get_blocks(
                user_id=effective_user_id,
                organization_id=organization_id,
            )
            recent_experiences = repo.get_recent_experiences(
                limit=10,
                user_id=effective_user_id,
                organization_id=organization_id,
            )

            # 2. Build prompt
            prompt = self._build_reflection_prompt(
                blocks=blocks,
                experiences=recent_experiences,
                last_user_message=last_user_message,
                last_response=last_response,
            )

            # 3. Call LLM
            llm_response = await self._call_llm(prompt)
            if not llm_response:
                logger.debug("[REFLECTION] LLM returned empty response, skipping")
                return None

            # 4. Parse response
            reflection = self._parse_reflection(llm_response)
            if not reflection:
                logger.debug("[REFLECTION] Could not parse reflection response")
                return None

            # 5. Apply updates if any — scoped to user
            if reflection.get("should_update") and reflection.get("updates"):
                applied = self._apply_updates(
                    state_manager=state_manager,
                    updates=reflection["updates"],
                    user_id=effective_user_id,
                    organization_id=organization_id,
                )
                reflection["applied_count"] = applied
            else:
                reflection["applied_count"] = 0

            # 6. Log reflection experience
            from app.engine.character.models import CharacterExperienceCreate
            summary = reflection.get("reflection_summary", "Suy ngẫm định kỳ")
            repo.log_experience(
                CharacterExperienceCreate(
                    experience_type=ExperienceType.SELF_REFLECTION.value,
                    content=summary[:500],
                    importance=0.6,
                    user_id=effective_user_id,
                ),
                organization_id=organization_id,
            )

            # 7. Reset counter for this user
            self.reset_counter(user_id=effective_user_id)

            # 8. Sprint 98: Cleanup old experiences (TTL) — scoped to user
            try:
                from app.core.config import settings as _cfg
                repo.cleanup_old_experiences(
                    max_age_days=_cfg.character_experience_retention_days,
                    keep_min=_cfg.character_experience_keep_min,
                    user_id=effective_user_id,
                    organization_id=organization_id,
                )
            except Exception as cleanup_err:
                logger.debug("[REFLECTION] Experience cleanup skipped: %s", cleanup_err)

            logger.info(
                "[REFLECTION] Completed for user=%s: %d updates applied, summary: %s",
                effective_user_id,
                reflection.get("applied_count", 0),
                summary[:80],
            )
            return reflection

        except Exception as e:
            logger.warning("[REFLECTION] Failed for user=%s: %s", effective_user_id, e)
            return None

    def _build_reflection_prompt(
        self,
        blocks: Dict[str, Any],
        experiences: List[Any],
        last_user_message: str,
        last_response: str,
    ) -> str:
        """Build the reflection prompt with current context."""
        # Format current blocks
        block_lines = []
        for label_enum in BlockLabel:
            label = label_enum.value
            block = blocks.get(label)
            if block and block.content.strip():
                block_lines.append(f"[{label}] ({block.remaining_chars()} ký tự còn trống)")
                block_lines.append(block.content.strip())
            else:
                block_lines.append(f"[{label}] (trống)")
        current_blocks = "\n".join(block_lines) if block_lines else "(Tất cả blocks đều trống)"

        # Format recent experiences
        exp_lines = []
        for exp in experiences[:10]:
            exp_lines.append(f"- [{exp.experience_type}] {exp.content[:100]}")
        recent_exp = "\n".join(exp_lines) if exp_lines else "(Chưa có trải nghiệm nào)"

        return _REFLECTION_PROMPT.format(
            current_blocks=current_blocks,
            recent_experiences=recent_exp,
            last_user_message=last_user_message[:500],
            last_response=last_response[:500],
        )

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM with the reflection prompt. Uses LIGHT tier."""
        try:
            from app.engine.llm_factory import ThinkingTier
            from app.engine.llm_pool import get_llm_for_provider, get_llm_light
            from app.engine.messages import Message
            from app.engine.messages_adapters import to_openai_dict

            llm = None
            try:
                # Background reflection should not pin itself to a provider that is
                # already marked busy on the hot path. Prefer the current auto-mode
                # runtime truth, then fall back to the legacy shared light instance.
                llm = get_llm_for_provider(
                    "auto",
                    default_tier=ThinkingTier.LIGHT,
                    strict_pin=False,
                )
            except Exception:
                llm = None

            if llm is None:
                llm = get_llm_light()

            result = await llm.ainvoke([to_openai_dict(Message(role="user", content=prompt))])

            # Extract text content
            if hasattr(result, "content"):
                return result.content
            return str(result)

        except Exception as e:
            logger.warning("[REFLECTION] LLM call failed: %s", e)
            return None

    def _parse_reflection(self, raw: str) -> Optional[Dict[str, Any]]:
        """Parse LLM JSON response into reflection dict."""
        try:
            # Strip markdown code fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                # Remove ```json and ``` markers
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)

            result = json.loads(cleaned)

            # Validate structure
            if not isinstance(result, dict):
                return None
            if "should_update" not in result:
                return None

            # Validate updates
            updates = result.get("updates", [])
            valid_labels = {b.value for b in BlockLabel}
            valid_actions = {"append", "replace"}
            validated = []
            for u in updates:
                if not isinstance(u, dict):
                    continue
                if u.get("block") not in valid_labels:
                    continue
                if u.get("action") not in valid_actions:
                    continue
                if not u.get("content"):
                    continue
                validated.append(u)
            result["updates"] = validated

            return result

        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("[REFLECTION] JSON parse failed: %s", e)
            return None

    def _apply_updates(
        self,
        state_manager: Any,
        updates: List[Dict[str, Any]],
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> int:
        """Apply validated updates to character blocks.

        Sprint 125: Scoped to user_id for per-user isolation.

        Returns number of successfully applied updates.
        """
        applied = 0
        for update in updates:
            block = update["block"]
            action = update["action"]
            content = update["content"]

            try:
                if action == "append":
                    formatted = f"\n- {content.strip()}"
                    result = state_manager.update_block(
                        label=block,
                        append=formatted,
                        user_id=user_id,
                        organization_id=organization_id,
                    )
                elif action == "replace":
                    result = state_manager.update_block(
                        label=block,
                        content=content,
                        user_id=user_id,
                        organization_id=organization_id,
                    )
                else:
                    continue

                if result:
                    applied += 1
                    logger.debug(
                        "[REFLECTION] Updated block '%s' (%s) for user=%s: %s",
                        block, action, user_id, content[:50],
                    )
            except Exception as e:
                logger.warning(
                    "[REFLECTION] Failed to update block '%s' for user=%s: %s",
                    block, user_id, e,
                )

        return applied


# =============================================================================
# Singleton
# =============================================================================

_reflection_engine: Optional[CharacterReflectionEngine] = None


def get_reflection_engine() -> CharacterReflectionEngine:
    """Get or create CharacterReflectionEngine singleton."""
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = CharacterReflectionEngine()
    return _reflection_engine


# =============================================================================
# Background Task Entry Point
# =============================================================================

async def trigger_character_reflection(
    user_id: str,
    message: str,
    response: str,
    organization_id: Optional[str] = None,
) -> None:
    """Background task entry point for character reflection.

    Called by BackgroundTaskRunner after each conversation.
    Increments counter and triggers reflection when interval is reached.

    Args:
        user_id: User who triggered the conversation
        message: User's message
        response: Wiii's response
    """
    try:
        engine = get_reflection_engine()

        # Always increment — per user
        count = engine.increment_conversation_count(user_id=user_id)

        # Only reflect when interval is reached — per user
        if not engine.should_reflect(user_id=user_id):
            logger.debug(
                "[REFLECTION] Count %d/%d for user=%s, not yet time to reflect",
                count, engine._get_interval(), user_id,
            )
            return

        logger.info(
            "[REFLECTION] Triggering reflection for user=%s after %d conversations",
            user_id, count,
        )
        await engine.reflect(
            last_user_message=message,
            last_response=response,
            user_id=user_id,
            organization_id=organization_id,
        )

    except Exception as e:
        logger.warning("[REFLECTION] trigger_character_reflection failed for user=%s: %s", user_id, e)
