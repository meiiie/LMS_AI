"""
Memory Lifecycle — Active Pruning of Decayed Memories

Sprint 123 (P4): Stanford Generative Agents pattern.
`should_prune()` existed in importance_decay.py since Sprint 73 but was
never called. This module provides the cold-path pruning operation used by
post-response semantic-memory maintenance.

Feature-gated via `settings.enable_memory_pruning` (default True).
"""

import logging
from datetime import datetime, timezone

from app.engine.semantic_memory.privacy import (
    hash_memory_identifier,
    memory_log_reference,
)
from app.engine.semantic_memory.write_audit import (
    append_semantic_memory_write_audit_event,
    build_semantic_memory_write_audit,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)


async def prune_stale_memories(user_id: str, session_id: str | None = None) -> int:
    """
    Active garbage collection for decayed memories.

    Runs in post-response memory maintenance, not in the chat/extraction hot
    path. Deletes facts whose effective importance has dropped below
    `settings.memory_prune_threshold`.

    Returns:
        Number of facts pruned
    """
    audit_scope = None
    try:
        from app.core.config import settings
        if not settings.enable_memory_pruning:
            return 0

        audit_scope = resolve_memory_write_scope()
        if not audit_scope.write_allowed:
            await append_semantic_memory_write_audit_event(
                session_id=session_id,
                org_id=audit_scope.org_id,
                payload=build_semantic_memory_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    message="",
                    response="",
                    scope=audit_scope,
                    write_kind="memory_pruning",
                    message_saved=False,
                    response_saved=False,
                    extract_facts=False,
                    stored_fact_count=0,
                    status="blocked",
                    warnings=["memory_pruning_blocked_missing_org_context"],
                ),
            )
            logger.warning(
                "Memory pruning blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                audit_scope.state,
            )
            return 0

        from app.repositories.semantic_memory_repository import get_semantic_memory_repository
        from app.engine.semantic_memory.importance_decay import (
            calculate_effective_importance_from_timestamps,
        )

        repo = get_semantic_memory_repository()
        all_facts = repo.get_all_user_facts(user_id)

        if not all_facts:
            await append_semantic_memory_write_audit_event(
                session_id=session_id,
                org_id=audit_scope.org_id,
                payload=build_semantic_memory_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    message="",
                    response="",
                    scope=audit_scope,
                    write_kind="memory_pruning",
                    message_saved=False,
                    response_saved=False,
                    extract_facts=False,
                    stored_fact_count=0,
                    status="skipped",
                ),
            )
            return 0

        prune_threshold = settings.memory_prune_threshold
        now = datetime.now(timezone.utc)
        pruned = 0

        for fact in all_facts:
            meta = fact.metadata or {}
            fact_type = meta.get("fact_type", "unknown")
            access_count = meta.get("access_count", 0)

            effective = calculate_effective_importance_from_timestamps(
                base_importance=fact.importance,
                fact_type=fact_type,
                last_accessed=meta.get("last_accessed"),
                created_at=fact.created_at,
                access_count=access_count,
                now=now,
            )

            if effective < prune_threshold:
                success = repo.delete_memory(user_id, str(fact.id))
                if success:
                    pruned += 1
                    logger.info(
                        "Pruned stale fact for user_hash=%s: type=%s, "
                        "effective_importance=%.3f, content_ref=%s",
                        hash_memory_identifier(user_id),
                        fact_type,
                        effective,
                        memory_log_reference(fact.content),
                    )

        if pruned > 0:
            logger.info(
                "Memory pruning complete for user_hash=%s: removed %d/%d stale facts",
                hash_memory_identifier(user_id),
                pruned,
                len(all_facts),
            )
        await append_semantic_memory_write_audit_event(
            session_id=session_id,
            org_id=audit_scope.org_id,
            payload=build_semantic_memory_write_audit(
                user_id=user_id,
                session_id=session_id,
                message="",
                response="",
                scope=audit_scope,
                write_kind="memory_pruning",
                message_saved=False,
                response_saved=False,
                extract_facts=False,
                stored_fact_count=0,
                status="saved" if pruned else "skipped",
            ),
        )
        return pruned

    except Exception as e:
        if audit_scope is not None:
            await append_semantic_memory_write_audit_event(
                session_id=session_id,
                org_id=audit_scope.org_id,
                payload=build_semantic_memory_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    message="",
                    response="",
                    scope=audit_scope,
                    write_kind="memory_pruning",
                    message_saved=False,
                    response_saved=False,
                    extract_facts=False,
                    stored_fact_count=0,
                    status="failed",
                    warnings=["memory_pruning_failed"],
                ),
            )
        logger.warning(
            "Memory pruning failed for user_hash=%s: %s",
            hash_memory_identifier(user_id),
            e,
        )
        return 0
