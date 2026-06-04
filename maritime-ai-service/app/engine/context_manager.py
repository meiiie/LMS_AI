"""
Context Manager — Sprint 78-79: SOTA Context Management System

4-layer token budget allocation with auto-compaction and persistent running summaries.

Sprint 79: Running summaries persisted to semantic_memories table for crash resilience.
           Session summaries auto-generated at message milestones for cross-session context.

SOTA Reference (Feb 2026):
  - Claude Code: Auto-compact at 65%, pause_after_compaction
  - ChatGPT: 4-layer (facts + summaries + session window), no vector search
  - OpenClawd: Pre-compaction memory flush, chars/4 token estimate, staged summarization
  - Mem0: Rolling conversation summary, 93% token reduction
  - Letta/MemGPT: FIFO buffer, sliding_window 30%, token budget allocation per section
  - LangMem: SummarizationNode, RunningSummary, max_tokens_before_summary threshold
  - FadeMem: Biologically-inspired importance decay (82.1% critical facts retained at 55% storage)

Architecture:
  Layer 1: System Prompt + Domain Context (fixed, ~15% budget)
  Layer 2: Core Memory Block / User Facts (permanent, ~5% budget)
  Layer 3: Running Conversation Summary (compressed older turns, ~10% budget)
  Layer 4: Recent Messages (verbatim sliding window, remaining ~60% budget)

Token estimation uses chars/4 heuristic (OpenClawd pattern) for speed.
Vietnamese text averages ~3.5 chars/token, English ~4 chars/token, so chars/4
is a conservative but safe approximation.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.engine.messages import Message
from app.engine.messages_adapters import to_openai_dict
from app.engine.context_budget_runtime import (
    CHARS_PER_TOKEN,
    MAX_SUMMARY_TOKENS,
    ContextBudget,
    TokenBudgetManager,
)
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

class ConversationCompactor:
    """
    Handles conversation compaction (summarization of older turns).

    SOTA patterns:
      - Claude Code: Auto-compact at 65%, staged summarization
      - OpenClawd: Pre-compaction memory flush, chars/4 estimate
      - LangMem: RunningSummary — incremental, doesn't re-summarize
      - Letta: sliding_window 30%, recursive summarization

    Uses MemorySummarizer for actual LLM summarization calls.
    """

    def __init__(self, budget_manager: Optional[TokenBudgetManager] = None):
        self._budget_manager = budget_manager or TokenBudgetManager()
        self._running_summaries: Dict[str, str] = {}  # cache_key -> summary

    @staticmethod
    def _cache_key(
        session_id: str,
        user_id: str = "",
        org_id: str | None = None,
    ) -> str:
        """Build composite cache key for user+session isolation.

        Sprint 125: Defense-in-depth — even if session IDs are already
        composite (user_{uid}__session_{sid}), adding user_id as prefix
        prevents any possibility of cross-user cache collision.
        """
        if user_id:
            if org_id:
                return f"{org_id}::{user_id}::{session_id}"
            return f"{user_id}::{session_id}"
        if org_id:
            return f"{org_id}::{session_id}"
        return session_id

    @staticmethod
    def _cache_org_id(scope: MemoryWriteScope) -> str | None:
        """Add org to cache keys only when multi-tenant isolation is active."""

        if scope.state == "request_scoped":
            return scope.org_id
        return None

    @staticmethod
    def _log_scope_blocked(
        *,
        operation: str,
        user_id: str,
        session_id: str,
        scope: MemoryWriteScope,
    ) -> None:
        logger.warning(
            "[CONTEXT_MANAGER] Running summary %s blocked for user_hash=%s "
            "session_hash=%s scope=%s",
            operation,
            hash_memory_identifier(user_id),
            hash_memory_identifier(session_id),
            scope.state,
        )

    def get_running_summary(self, session_id: str, user_id: str = "") -> str:
        """Get the running summary for a session.

        Sprint 79: Cache-first, then DB fallback when user_id is provided.
        Sprint 125: Uses composite cache key for user isolation.
        """
        read_scope: MemoryWriteScope | None = None
        if user_id:
            read_scope = resolve_memory_read_scope()
            if not read_scope.write_allowed or not read_scope.org_id:
                self._log_scope_blocked(
                    operation="read",
                    user_id=user_id,
                    session_id=session_id,
                    scope=read_scope,
                )
                return ""

        key = self._cache_key(
            session_id,
            user_id,
            org_id=self._cache_org_id(read_scope) if read_scope else None,
        )

        # Cache hit
        cached = self._running_summaries.get(key, "")
        if cached:
            return cached

        # Cache miss — try DB if user_id provided
        if user_id:
            db_summary = self._load_summary_from_db(session_id, user_id)
            if db_summary:
                self._running_summaries[key] = db_summary
                return db_summary

        return ""

    def set_running_summary(
        self, session_id: str, summary: str, user_id: str = ""
    ) -> None:
        """Store/update running summary for a session.

        Sprint 79: Also persists to DB when user_id is provided.
        Sprint 125: Uses composite cache key for user isolation.
        """
        write_scope: MemoryWriteScope | None = None
        if user_id:
            write_scope = resolve_memory_write_scope()
            if not write_scope.write_allowed or not write_scope.org_id:
                self._log_scope_blocked(
                    operation="write",
                    user_id=user_id,
                    session_id=session_id,
                    scope=write_scope,
                )
                return

        key = self._cache_key(
            session_id,
            user_id,
            org_id=self._cache_org_id(write_scope) if write_scope else None,
        )
        if summary:
            self._running_summaries[key] = summary
            if user_id:
                self._persist_summary_to_db(session_id, user_id, summary)
                self._persist_session_summary(session_id, user_id, summary)
        elif key in self._running_summaries:
            del self._running_summaries[key]
            if user_id:
                self._delete_summary_from_db(session_id, user_id)

    # ── Sprint 79: DB persistence for running summaries ──────────────────────

    def _persist_summary_to_db(
        self,
        session_id: str,
        user_id: str,
        summary: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Upsert running summary to semantic_memories table (fire-and-forget)."""
        try:
            from app.core.database import get_shared_session_factory
            from app.core.org_filter import org_where_clause
            from sqlalchemy import text as sa_text
            import json

            write_scope = scope or resolve_memory_write_scope()
            if not write_scope.write_allowed or not write_scope.org_id:
                self._log_scope_blocked(
                    operation="persist",
                    user_id=user_id,
                    session_id=session_id,
                    scope=write_scope,
                )
                return

            eff_org_id = write_scope.org_id
            org_filter = org_where_clause(eff_org_id)

            factory = get_shared_session_factory()
            with factory() as session:
                # Upsert: delete old + insert new (simple, avoids ON CONFLICT complexity)
                session.execute(
                    sa_text(
                        "DELETE FROM semantic_memories "
                        "WHERE user_id = :uid AND memory_type = 'running_summary' "
                        "AND session_id = :sid" + org_filter
                    ),
                    {"uid": user_id, "sid": session_id, "org_id": eff_org_id},
                )
                session.execute(
                    sa_text(
                        "INSERT INTO semantic_memories "
                        "(user_id, memory_type, content, session_id, organization_id, "
                        "metadata, created_at, updated_at) "
                        "VALUES (:uid, 'running_summary', :content, :sid, :org_id, "
                        ":meta::jsonb, NOW(), NOW())"
                    ),
                    {
                        "uid": user_id,
                        "sid": session_id,
                        "content": summary,
                        "org_id": eff_org_id,
                        "meta": json.dumps({"source": "compactor"}, ensure_ascii=False),
                    },
                )
                session.commit()
        except Exception as e:
            logger.debug("Failed to persist running summary to DB: %s", e)

    def _load_summary_from_db(
        self,
        session_id: str,
        user_id: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> str:
        """Load running summary from semantic_memories table."""
        try:
            from app.core.database import get_shared_session_factory
            from app.core.org_filter import org_where_clause
            from sqlalchemy import text as sa_text

            read_scope = scope or resolve_memory_read_scope()
            if not read_scope.write_allowed or not read_scope.org_id:
                self._log_scope_blocked(
                    operation="load",
                    user_id=user_id,
                    session_id=session_id,
                    scope=read_scope,
                )
                return ""

            eff_org_id = read_scope.org_id
            org_filter = org_where_clause(eff_org_id)

            factory = get_shared_session_factory()
            with factory() as session:
                row = session.execute(
                    sa_text(
                        "SELECT content FROM semantic_memories "
                        "WHERE user_id = :uid AND memory_type = 'running_summary' "
                        "AND session_id = :sid" + org_filter + " "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {"uid": user_id, "sid": session_id, "org_id": eff_org_id},
                ).fetchone()
                return row[0] if row else ""
        except Exception as e:
            logger.debug("Failed to load running summary from DB: %s", e)
            return ""

    def _delete_summary_from_db(
        self,
        session_id: str,
        user_id: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Delete running summary from DB."""
        try:
            from app.core.database import get_shared_session_factory
            from app.core.org_filter import org_where_clause
            from sqlalchemy import text as sa_text

            write_scope = scope or resolve_memory_write_scope()
            if not write_scope.write_allowed or not write_scope.org_id:
                self._log_scope_blocked(
                    operation="delete",
                    user_id=user_id,
                    session_id=session_id,
                    scope=write_scope,
                )
                return

            eff_org_id = write_scope.org_id
            org_filter = org_where_clause(eff_org_id)

            factory = get_shared_session_factory()
            with factory() as session:
                session.execute(
                    sa_text(
                        "DELETE FROM semantic_memories "
                        "WHERE user_id = :uid AND memory_type = 'running_summary' "
                        "AND session_id = :sid" + org_filter
                    ),
                    {"uid": user_id, "sid": session_id, "org_id": eff_org_id},
                )
                session.commit()
        except Exception as e:
            logger.debug("Failed to delete running summary from DB: %s", e)

    def _persist_session_summary(
        self,
        session_id: str,
        user_id: str,
        summary: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Also save as thread session summary for cross-session retrieval."""
        try:
            from app.core.thread_utils import build_thread_id
            from app.repositories.thread_repository import get_thread_repository

            write_scope = scope or resolve_memory_write_scope()
            if not write_scope.write_allowed or not write_scope.org_id:
                self._log_scope_blocked(
                    operation="thread_persist",
                    user_id=user_id,
                    session_id=session_id,
                    scope=write_scope,
                )
                return

            # Sprint 170c: Include org_id for cross-org thread isolation.
            thread_id = build_thread_id(user_id, session_id, org_id=write_scope.org_id)
            repo = get_thread_repository()
            repo.update_extra_data(
                thread_id,
                user_id,
                {"summary": summary},
                organization_id=write_scope.org_id,
            )
        except Exception as e:
            logger.debug("Failed to persist session summary: %s", e)

    async def maybe_compact(
        self,
        session_id: str,
        history_list: List[Dict[str, str]],
        system_prompt: str = "",
        core_memory: str = "",
        user_id: str = "",
    ) -> Tuple[str, List[Message], ContextBudget]:
        """Check if compaction needed and perform if so.

        Args:
            session_id: Session identifier
            history_list: Full conversation history
            system_prompt: System prompt text for budget calculation
            core_memory: Core memory block text
            user_id: Sprint 79 — enables DB persistence when provided

        Returns:
            Tuple of (running_summary, recent_messages, budget)
        """
        existing_summary = self.get_running_summary(session_id, user_id=user_id)

        budget = self._budget_manager.allocate(
            system_prompt=system_prompt,
            core_memory=core_memory,
            summary=existing_summary,
            history_list=history_list,
        )

        if budget.needs_compaction and budget.messages_dropped > 0:
            # Sprint 116: Pre-compaction memory flush (OpenClaw pattern)
            # Extract durable memories BEFORE summarization loses detail
            older = history_list[: budget.messages_dropped]
            try:
                await self._flush_memories_before_compaction(older, user_id)
            except Exception as flush_err:
                logger.debug("[MEMORY_FLUSH] Failed (non-blocking): %s", flush_err)

            # Summarize dropped messages
            new_summary = await self._summarize_messages(
                older, existing_summary
            )
            if new_summary:
                self.set_running_summary(session_id, new_summary, user_id=user_id)
                existing_summary = new_summary

                # Re-allocate with new summary
                budget = self._budget_manager.allocate(
                    system_prompt=system_prompt,
                    core_memory=core_memory,
                    summary=existing_summary,
                    history_list=history_list,
                )
                logger.info(
                    "[CONTEXT_MANAGER] Auto-compacted: %d messages summarized, "
                    "%d retained verbatim, utilization=%.1f%%",
                    len(older),
                    budget.messages_included,
                    budget.utilization * 100,
                )

        # Build final messages
        messages, budget = self._budget_manager.build_context_messages(
            history_list=history_list,
            system_prompt=system_prompt,
            core_memory=core_memory,
            summary=existing_summary,
        )

        return existing_summary, messages, budget

    async def force_compact(
        self,
        session_id: str,
        history_list: List[Dict[str, str]],
        user_id: str = "",
    ) -> str:
        """Force compaction regardless of threshold (user-triggered).

        Args:
            session_id: Session identifier
            history_list: Full conversation history
            user_id: Sprint 79 — enables DB persistence when provided

        Returns:
            The new running summary.
        """
        if not history_list:
            return ""

        existing_summary = self.get_running_summary(session_id, user_id=user_id)

        # Summarize ALL but last 4 messages (keep recent context)
        keep_recent = min(4, len(history_list))
        to_summarize = history_list[:-keep_recent] if keep_recent > 0 else history_list

        if not to_summarize:
            return existing_summary

        new_summary = await self._summarize_messages(to_summarize, existing_summary)
        if new_summary:
            self.set_running_summary(session_id, new_summary, user_id=user_id)
            logger.info(
                "[CONTEXT_MANAGER] Force compacted: %d messages → summary (%d chars)",
                len(to_summarize),
                len(new_summary),
            )
            return new_summary

        return existing_summary

    def clear_session(self, session_id: str, user_id: str = "") -> None:
        """Clear all context state for a session.

        Sprint 79: Also deletes from DB when user_id provided.
        Sprint 125: Uses composite cache key for user isolation.
        """
        write_scope: MemoryWriteScope | None = None
        if user_id:
            write_scope = resolve_memory_write_scope()
            if not write_scope.write_allowed or not write_scope.org_id:
                self._log_scope_blocked(
                    operation="clear",
                    user_id=user_id,
                    session_id=session_id,
                    scope=write_scope,
                )
                return

        key = self._cache_key(
            session_id,
            user_id,
            org_id=self._cache_org_id(write_scope) if write_scope else None,
        )
        if key in self._running_summaries:
            del self._running_summaries[key]
        if user_id:
            self._delete_summary_from_db(session_id, user_id)

    def get_context_info(
        self,
        session_id: str,
        history_list: List[Dict[str, str]],
        system_prompt: str = "",
        core_memory: str = "",
        user_id: str = "",
    ) -> Dict:
        """Get context usage info for introspection (like /context list).

        Returns dict with token budgets, utilization, layer breakdown.
        """
        existing_summary = self.get_running_summary(session_id, user_id=user_id)
        budget = self._budget_manager.allocate(
            system_prompt=system_prompt,
            core_memory=core_memory,
            summary=existing_summary,
            history_list=history_list,
        )
        info = budget.to_dict()
        info["session_id"] = session_id
        info["running_summary_chars"] = len(existing_summary)
        info["total_history_messages"] = len(history_list)
        return info

    async def _flush_memories_before_compaction(
        self,
        messages: List[Dict[str, str]],
        user_id: str = "",
    ) -> None:
        """Sprint 116: Pre-compaction memory flush (OpenClaw pattern).

        Before older messages are summarized (and detail is lost), extract
        durable facts/learnings and write them to character blocks.

        Uses LIGHT tier LLM for speed. Fail-safe: never blocks compaction.

        Extracted categories:
        - user_patterns: How the user communicates, what they struggle with
        - learned_lessons: Teaching insights Wiii gained
        - favorite_topics: Topics discussed frequently
        """
        if not messages or not user_id:
            return

        try:
            from app.engine.llm_pool import get_llm_light

            conversation = "\n".join(
                f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:300]}"
                for m in messages[:20]  # Cap at 20 messages to control cost
            )

            prompt = (
                "Phân tích hội thoại sau và trích xuất thông tin QUAN TRỌNG cần nhớ lâu dài.\n\n"
                f"Hội thoại:\n{conversation}\n\n"
                "Trả lời JSON (KHÔNG có markdown code block):\n"
                '{"facts": [\n'
                '  {"block": "user_patterns|learned_lessons|favorite_topics", '
                '"content": "nội dung ngắn gọn tiếng Việt (dưới 80 ký tự)"}\n'
                "]}\n\n"
                "Quy tắc:\n"
                "- Chỉ ghi nhận điều THỰC SỰ quan trọng (tên user, sở thích, khó khăn, bài học)\n"
                "- Tối đa 3 facts. Nếu không có gì đáng nhớ, trả về {\"facts\": []}\n"
                "- Không ghi nhận nội dung chung chung, chỉ thông tin cụ thể"
            )

            llm = get_llm_light()
            result = await llm.ainvoke([to_openai_dict(Message(role="user", content=prompt))])

            import json
            raw = result.content.strip()
            # Strip markdown fences
            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines)

            data = json.loads(raw)
            facts = data.get("facts", [])

            if not facts:
                return

            from app.engine.character.character_state import get_character_state_manager
            from app.engine.character.models import BlockLabel

            manager = get_character_state_manager()
            valid_labels = {b.value for b in BlockLabel}
            applied = 0

            for fact in facts[:3]:  # Hard cap at 3
                block = fact.get("block", "")
                content = fact.get("content", "")
                if block not in valid_labels or not content:
                    continue
                formatted = f"\n- {content.strip()}"
                manager.update_block(label=block, append=formatted)
                applied += 1

            if applied > 0:
                logger.info(
                    "[MEMORY_FLUSH] Pre-compaction: %d facts extracted from %d messages",
                    applied, len(messages),
                )

                # Sprint 118: Consolidate blocks that are filling up
                try:
                    consolidated = await manager.consolidate_full_blocks()
                    if consolidated > 0:
                        logger.info(
                            "[MEMORY_FLUSH] Consolidated %d full blocks", consolidated,
                        )
                except Exception as ce:
                    logger.debug("[MEMORY_FLUSH] Consolidation skipped: %s", ce)

        except Exception as e:
            # Fail-safe: never block compaction
            logger.debug("[MEMORY_FLUSH] Pre-compaction flush failed (non-blocking): %s", e)

    async def _summarize_messages(
        self,
        messages: List[Dict[str, str]],
        existing_summary: str = "",
    ) -> Optional[str]:
        """Summarize a batch of messages using MemorySummarizer.

        Implements incremental/running summary pattern (LangMem style):
        new_summary = summarize(existing_summary + new_messages)
        """
        if not messages:
            return existing_summary

        try:
            from app.engine.memory_summarizer import get_memory_summarizer

            summarizer = get_memory_summarizer()
            if not summarizer.is_available():
                # No LLM — fallback to simple truncated text
                return self._fallback_summary(messages, existing_summary)

            # Build prompt for incremental summarization
            prompt = self._build_summary_prompt(messages, existing_summary)

            # Use summarizer's LLM directly
            response = await summarizer._llm.ainvoke(prompt)

            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            result = text_content.strip()

            if result:
                # Truncate if too long
                max_chars = MAX_SUMMARY_TOKENS * CHARS_PER_TOKEN
                if len(result) > max_chars:
                    result = result[:max_chars] + "..."
                return result

            return self._fallback_summary(messages, existing_summary)

        except Exception as e:
            logger.warning("[CONTEXT_MANAGER] Summarization failed: %s", e)
            return self._fallback_summary(messages, existing_summary)

    def _build_summary_prompt(
        self,
        messages: List[Dict[str, str]],
        existing_summary: str = "",
    ) -> str:
        """Build incremental summarization prompt."""
        conversation = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:500]}"
            for m in messages
        )

        # Sprint 87: Append identity anchor for anti-drift in long conversations
        identity_anchor = ""
        try:
            from app.prompts.prompt_loader import get_prompt_loader
            loader = get_prompt_loader()
            anchor = loader.get_identity().get("identity", {}).get("identity_anchor", "")
            if anchor:
                identity_anchor = f"\n\n[PERSONA REMINDER: {anchor.strip()}]"
        except Exception:
            pass

        if existing_summary:
            return (
                f"Bạn là trợ lý tóm tắt hội thoại. "
                f"Đây là tóm tắt trước đó:\n{existing_summary}\n\n"
                f"Thêm các tin nhắn mới sau vào tóm tắt (5-8 câu):\n"
                f"{conversation}\n\n"
                f"Tóm tắt cập nhật (tiếng Việt, 5-8 câu). "
                f"Giữ lại: tên user, thông tin cá nhân, TẤT CẢ chủ đề đã thảo luận (liệt kê), quyết định quan trọng:"
                f"{identity_anchor}"
            )

        return (
            f"Tóm tắt hội thoại sau (5-8 câu tiếng Việt). "
            f"Giữ lại: tên user, thông tin cá nhân, TẤT CẢ chủ đề đã thảo luận, quyết định quan trọng.\n\n"
            f"{conversation}\n\n"
            f"Tóm tắt:"
            f"{identity_anchor}"
        )

    def _fallback_summary(
        self,
        messages: List[Dict[str, str]],
        existing_summary: str = "",
    ) -> str:
        """Fallback when LLM unavailable: simple text truncation."""
        parts = []
        if existing_summary:
            parts.append(existing_summary)

        for msg in messages:
            role = "User" if msg.get("role") == "user" else "AI"
            content = msg.get("content", "")[:150]
            parts.append(f"{role}: {content}")

        result = "\n".join(parts)
        max_chars = MAX_SUMMARY_TOKENS * CHARS_PER_TOKEN
        if len(result) > max_chars:
            result = result[:max_chars] + "..."
        return result


# ─── Singletons ───────────────────────────────────────────────────────────────

_budget_manager: Optional[TokenBudgetManager] = None
_compactor: Optional[ConversationCompactor] = None


def get_budget_manager() -> TokenBudgetManager:
    """Get or create TokenBudgetManager singleton."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = TokenBudgetManager()
    return _budget_manager


def get_compactor() -> ConversationCompactor:
    """Get or create ConversationCompactor singleton."""
    global _compactor
    if _compactor is None:
        _compactor = ConversationCompactor(budget_manager=get_budget_manager())
    return _compactor
