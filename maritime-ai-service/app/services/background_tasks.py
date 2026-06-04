"""
Background Tasks - Async Task Management for Chat Processing

Extracted from chat_service.py as part of Clean Architecture refactoring.
Centralizes all background task logic for chat processing.

**Pattern:** Task Runner Service
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional
from uuid import UUID

from app.engine.runtime.runtime_metrics import inc_counter

logger = logging.getLogger(__name__)
BACKGROUND_TASK_SCHEDULE_SUMMARY_VERSION = "wiii.background_task_schedule.v1"
_SAFE_LABEL_RE = re.compile(r"[^a-z0-9._:/-]+")


def _safe_label(value: Any, *, fallback: str = "unknown") -> str:
    label = str(value or "").strip().casefold()
    label = _SAFE_LABEL_RE.sub("_", label).strip("_")
    return (label or fallback)[:96]


@dataclass(frozen=True, slots=True)
class BackgroundTaskGroupSchedule:
    group: str
    status: str
    reason: str

    def to_summary(self) -> dict[str, str]:
        return {
            "group": self.group,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class BackgroundTaskScheduleSummary:
    task_count: int
    groups: tuple[BackgroundTaskGroupSchedule, ...]

    def to_summary(self) -> dict[str, Any]:
        return {
            "schema_version": BACKGROUND_TASK_SCHEDULE_SUMMARY_VERSION,
            "task_count": max(int(self.task_count or 0), 0),
            "groups": [group.to_summary() for group in self.groups],
            "privacy": {
                "raw_content_included": False,
                "identifier_strategy": "status_only",
            },
        }


def _schedule_group(
    groups: list[BackgroundTaskGroupSchedule],
    *,
    group: str,
    status: str,
    reason: str,
) -> None:
    groups.append(
        BackgroundTaskGroupSchedule(
            group=group,
            status=status,
            reason=reason,
        )
    )
    inc_counter(
        "runtime.background_tasks.scheduling",
        labels={
            "group": _safe_label(group),
            "status": _safe_label(status),
            "reason": _safe_label(reason),
        },
    )


class BackgroundTaskRunner:
    """
    Manages background tasks for chat processing.

    Responsibilities:
    - Store semantic memory interactions
    - Cold-path semantic memory maintenance
    - Memory summarization
    - Update learning profile stats

    NOTE: Message persistence (user + assistant) is handled by ChatOrchestrator
    directly to avoid double-saving. See Sprint 83 audit (H7).

    **Pattern:** Task Runner with lazy initialization
    """
    
    def __init__(
        self,
        chat_history=None,
        semantic_memory=None,
        memory_summarizer=None,
        profile_repo=None
    ):
        """
        Initialize with optional dependencies (lazy loaded).
        
        Args:
            chat_history: ChatHistoryRepository
            semantic_memory: SemanticMemoryEngine
            memory_summarizer: MemorySummarizer
            profile_repo: LearningProfileRepository
        """
        self._chat_history = chat_history
        self._semantic_memory = semantic_memory
        self._memory_summarizer = memory_summarizer
        self._profile_repo = profile_repo
        
        logger.info("BackgroundTaskRunner initialized")
    
    def schedule_all(
        self,
        background_save: Callable,
        user_id: str,
        session_id: UUID,
        message: str,
        response: str,
        skip_fact_extraction: bool = False,
        org_id: str = "",
    ) -> BackgroundTaskScheduleSummary:
        """
        Schedule all background tasks after response is sent.

        Args:
            background_save: FastAPI BackgroundTasks.add_task
            user_id: User identifier
            session_id: Session UUID
            message: User's message
            response: AI's response
            skip_fact_extraction: If True, skip fact extraction (memory agent
                already handled it). Prevents double/triple LLM calls.
            org_id: Organization ID for multi-tenant context (Sprint 175b).
                Background tasks run AFTER middleware resets ContextVar,
                so org_id must be passed explicitly.
        """
        # NOTE: Message saving (user + assistant) is handled by ChatOrchestrator
        # directly — do NOT duplicate here. See Sprint 83 audit fix (H7).

        from app.services.post_turn_lifecycle import (
            PostTurnLifecycleContext,
            schedule_post_turn_background_tasks,
        )

        return schedule_post_turn_background_tasks(
            PostTurnLifecycleContext(
                background_save=background_save,
                background_runner=self,
                user_id=user_id,
                session_id=session_id,
                message=message,
                response_text=response,
                organization_id=org_id,
                transport_type="unknown",
                skip_fact_extraction=skip_fact_extraction,
                ephemeral_direct_turn=False,
            )
        )

    def schedule_non_semantic_tasks(
        self,
        background_save: Callable,
        user_id: str,
        session_id: UUID,
        message: str,
        response: str,
        org_id: str = "",
    ) -> BackgroundTaskScheduleSummary:
        """
        Schedule post-turn tasks that do not own semantic-memory writes.

        Raw semantic interaction writes and maintenance scheduling are owned by
        app.services.post_turn_lifecycle so sync/stream finalization has one
        explicit raw-input boundary.
        """
        task_count = 0
        groups: list[BackgroundTaskGroupSchedule] = []

        # Task 2: Summarize memory if needed
        if self._memory_summarizer:
            background_save(
                self._summarize_memory,
                str(session_id), message, response
            )
            task_count += 1
            _schedule_group(
                groups,
                group="memory_summarizer",
                status="scheduled",
                reason="dependency_available",
            )
        else:
            _schedule_group(
                groups,
                group="memory_summarizer",
                status="skipped",
                reason="missing_dependency",
            )
        
        # Task 3: Update learning profile stats
        if self._profile_repo and self._profile_repo.is_available():
            background_save(
                self._update_profile_stats,
                user_id
            )
            task_count += 1
            _schedule_group(
                groups,
                group="profile_stats",
                status="scheduled",
                reason="dependency_available",
            )
        else:
            _schedule_group(
                groups,
                group="profile_stats",
                status="skipped",
                reason="missing_or_unavailable_dependency",
            )

        # Task 4: Character reflection (Sprint 94)
        try:
            from app.core.config import settings
            if settings.enable_character_reflection:
                background_save(
                    self._trigger_reflection,
                    user_id, message, response, org_id
                )
                task_count += 1
                _schedule_group(
                    groups,
                    group="character_reflection",
                    status="scheduled",
                    reason="enabled",
                )
            else:
                _schedule_group(
                    groups,
                    group="character_reflection",
                    status="skipped",
                    reason="disabled",
                )
        except Exception:
            _schedule_group(
                groups,
                group="character_reflection",
                status="skipped",
                reason="config_unavailable",
            )
            pass  # Config not available — skip silently
        return BackgroundTaskScheduleSummary(
            task_count=task_count,
            groups=tuple(groups),
        )

    def save_message(
        self,
        background_save: Callable,
        session_id: UUID,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        is_blocked: bool = False,
        block_reason: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> None:
        """
        Save a single message to chat history (background).
        
        Args:
            background_save: FastAPI BackgroundTasks.add_task
            session_id: Session UUID
            role: 'user' or 'assistant'
            content: Message content
            user_id: Optional user ID for blocked message logging
            is_blocked: Whether message was blocked
            block_reason: Reason for blocking
            organization_id: Organization boundary for the write
        """
        if self._chat_history and self._chat_history.is_available():
            if is_blocked:
                self._chat_history.save_message(
                    session_id=session_id,
                    role=role,
                    content=content,
                    user_id=user_id,
                    is_blocked=True,
                    block_reason=block_reason,
                    organization_id=organization_id,
                )
            else:
                background_save(
                    self._chat_history.save_message,
                    session_id, role, content, user_id,
                    organization_id=organization_id,
                )
    
    # =========================================================================
    # PRIVATE TASK IMPLEMENTATIONS
    # =========================================================================
    
    async def _store_semantic_interaction(
        self,
        user_id: str,
        message: str,
        response: str,
        session_id: str,
        skip_fact_extraction: bool = False,
        org_id: str = "",
    ) -> None:
        """
        Store interaction in Semantic Memory.

        Args:
            skip_fact_extraction: When True, skips both fact and insight
                extraction (memory agent already did it). Only stores the
                raw interaction.
            org_id: Organization ID — set as ContextVar for this background task
                since middleware already reset it before this runs (Sprint 175b).
        """
        # Sprint 175b: Restore org context for background task
        _org_token = None
        if org_id:
            try:
                from app.core.org_context import current_org_id
                _org_token = current_org_id.set(org_id)
            except Exception:
                pass

        try:
            if not skip_fact_extraction:
                # Extract behavioral insights
                conversation_history = []
                if self._chat_history and self._chat_history.is_available():
                    from uuid import UUID as UUIDType
                    try:
                        session_uuid = UUIDType(session_id)
                        recent_messages = self._chat_history.get_recent_messages(
                            session_uuid,
                            organization_id=org_id or None,
                        )
                        conversation_history = [msg.content for msg in recent_messages[-5:]]
                    except ValueError:
                        pass

                insights = await self._semantic_memory.extract_and_store_insights(
                    user_id=user_id,
                    message=message,
                    conversation_history=conversation_history,
                    session_id=session_id
                )
                if insights:
                    logger.info("[INSIGHT ENGINE] Extracted %d behavioral insights for user %s", len(insights), user_id)

            # Store raw interaction (message + response embeddings)
            # skip fact extraction if memory agent already handled it
            await self._semantic_memory.store_interaction(
                user_id=user_id,
                message=message,
                response=response,
                session_id=session_id,
                extract_facts=not skip_fact_extraction,
            )

            logger.debug("Background stored semantic interaction for user %s (skip_extract=%s)", user_id, skip_fact_extraction)
        except Exception as e:
            logger.error("Failed to store semantic interaction: %s", e)
        finally:
            # Sprint 175b: Reset org ContextVar to prevent leakage
            if _org_token is not None:
                try:
                    from app.core.org_context import current_org_id
                    current_org_id.reset(_org_token)
                except Exception:
                    pass

    async def _run_semantic_memory_maintenance(
        self,
        user_id: str,
        session_id: str,
        org_id: str = "",
    ) -> None:
        """
        Run cold-path semantic memory maintenance after interaction storage.

        This keeps pruning and LLM summarization out of fact extraction and
        out of the minimum interaction-write task.
        """
        from app.tasks.semantic_memory_tasks import run_semantic_memory_maintenance

        await run_semantic_memory_maintenance(
            user_id=user_id,
            session_id=session_id,
            org_id=org_id,
            semantic_memory=self._semantic_memory,
            executor="local_fallback",
        )

    async def _enqueue_or_run_semantic_memory_maintenance(
        self,
        user_id: str,
        session_id: str,
        org_id: str = "",
    ) -> None:
        """Enqueue maintenance to the task broker or fall back locally."""
        try:
            from app.tasks.semantic_memory_tasks import (
                enqueue_semantic_memory_maintenance,
            )

            enqueued = await enqueue_semantic_memory_maintenance(
                user_id=user_id,
                session_id=session_id,
                org_id=org_id,
            )
            if enqueued:
                return
        except Exception as exc:
            logger.debug("Semantic memory maintenance enqueue skipped: %s", exc)

        await self._run_semantic_memory_maintenance(
            user_id=user_id,
            session_id=session_id,
            org_id=org_id,
        )
    
    async def _summarize_memory(
        self,
        session_id: str,
        message: str,
        response: str
    ) -> None:
        """
        Summarize conversation memory if needed.
        
        CHỈ THỊ KỸ THUẬT SỐ 17: Memory Summarizer Integration
        """
        try:
            await self._memory_summarizer.add_message_async(session_id, "user", message)
            await self._memory_summarizer.add_message_async(session_id, "assistant", response)
            
            logger.debug("Background added messages to MemorySummarizer for session %s", session_id)
        except Exception as e:
            logger.error("Failed to summarize memory: %s", e)
    
    async def _trigger_reflection(
        self,
        user_id: str,
        message: str,
        response: str,
        org_id: str = "",
    ) -> None:
        """
        Trigger character reflection (Sprint 94).

        Delegates to CharacterReflectionEngine which handles
        counting, batching, and LLM reflection.
        """
        try:
            from app.engine.character.reflection_engine import trigger_character_reflection
            await trigger_character_reflection(
                user_id=user_id,
                message=message,
                response=response,
                organization_id=org_id or None,
            )
        except Exception as e:
            logger.warning("Character reflection failed: %s", e)

    async def _update_profile_stats(self, user_id: str) -> None:
        """
        Update learning profile stats.
        
        **Spec:** CHỈ THỊ KỸ THUẬT SỐ 04
        """
        try:
            await self._profile_repo.increment_stats(user_id, messages=2)  # user + assistant
            logger.debug("Background updated profile stats for user %s", user_id)
        except Exception as e:
            logger.error("Failed to update profile stats in background: %s", e)


# =============================================================================
# SINGLETON
# =============================================================================

_background_runner: Optional[BackgroundTaskRunner] = None


def get_background_runner(
    chat_history=None,
    semantic_memory=None,
    memory_summarizer=None,
    profile_repo=None
) -> BackgroundTaskRunner:
    """Get or create BackgroundTaskRunner singleton."""
    global _background_runner
    if _background_runner is None:
        _background_runner = BackgroundTaskRunner(
            chat_history=chat_history,
            semantic_memory=semantic_memory,
            memory_summarizer=memory_summarizer,
            profile_repo=profile_repo
        )
    return _background_runner


def init_background_runner(
    chat_history=None,
    semantic_memory=None,
    memory_summarizer=None,
    profile_repo=None
) -> BackgroundTaskRunner:
    """Initialize BackgroundTaskRunner with dependencies."""
    global _background_runner
    _background_runner = BackgroundTaskRunner(
        chat_history=chat_history,
        semantic_memory=semantic_memory,
        memory_summarizer=memory_summarizer,
        profile_repo=profile_repo
    )
    return _background_runner
