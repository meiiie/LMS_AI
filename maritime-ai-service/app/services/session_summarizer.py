"""
Session Summarizer — Cross-session context via conversation summaries

Sprint 17: Virtual Agent-per-User Architecture (Layer 3)

Provides:
1. summarize_thread() — Generate 2-3 sentence summary of a conversation
2. get_recent_summaries() — Get formatted summaries for context injection (Layer 3)

Context Model (4-layer, priority-based):
  P0 (Layer 0): System prompt + domain config
  P1 (Layer 1): Current conversation messages (last N)
  P2 (Layer 2): User facts from semantic_memory (permanent)
  P2 (Layer 3): Session summaries (cross-session context) ← THIS MODULE
  P3 (Layer 4): Learning graph + knowledge gaps

The summarizer uses LLM LIGHT tier for cost efficiency.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Prompt template for Vietnamese summarization
SUMMARIZE_PROMPT = """Tóm tắt cuộc trò chuyện sau bằng 2-3 câu ngắn gọn bằng tiếng Việt.
Tập trung vào: (1) chủ đề chính, (2) kết quả/kết luận quan trọng, (3) yêu cầu chưa hoàn thành nếu có.

Cuộc trò chuyện:
{messages}

Tóm tắt:"""


class SessionSummarizer:
    """
    Generates and retrieves cross-session context summaries.

    Uses LLM LIGHT tier for cost efficiency.
    Stores summaries in thread_views.extra_data['summary'].
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        """Lazy-load LLM LIGHT tier."""
        if self._llm is None:
            try:
                from app.engine.llm_pool import get_llm_light
                self._llm = get_llm_light()
            except Exception as e:
                logger.warning("SessionSummarizer: LLM not available: %s", e)
        return self._llm

    async def summarize_thread(
        self,
        thread_id: str,
        user_id: str,
        messages: Optional[list[dict]] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a 2-3 sentence summary of a conversation thread.

        If messages are not provided, returns None (checkpointer removed).
        Saves the summary to thread_views.extra_data['summary'].

        Args:
            thread_id: Composite thread ID
            user_id: User ID for ownership verification
            messages: Optional list of message dicts [{role, content}]
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            Summary string, or None on failure
        """
        llm = self._get_llm()
        if not llm:
            return None

        # If no messages provided, try to reconstruct from recent history
        if not messages:
            messages = await self._load_thread_messages(thread_id)
            if not messages:
                logger.debug("No messages found for thread %s", thread_id)
                return None

        # Build conversation text for summarization
        conversation_text = self._format_messages(messages)
        if not conversation_text or len(conversation_text) < 20:
            return None

        try:
            prompt = SUMMARIZE_PROMPT.format(messages=conversation_text[:3000])
            response = await llm.ainvoke(prompt)
            summary = response.content.strip() if hasattr(response, 'content') else str(response).strip()

            # Save summary to thread_views
            self._save_summary(
                thread_id,
                user_id,
                summary,
                organization_id=organization_id,
            )

            logger.info("[SESSION_SUMMARY] Generated for %s: %d chars", thread_id, len(summary))
            return summary

        except Exception as e:
            logger.warning("Session summarization failed: %s", e)
            return None

    async def get_recent_summaries(
        self,
        user_id: str,
        limit: int = 15,
        organization_id: Optional[str] = None,
    ) -> str:
        """
        Get formatted summaries of recent conversations for context injection.

        This is injected as Layer 3 context in InputProcessor.build_context().

        Args:
            user_id: User ID
            limit: Max number of recent summaries
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            Formatted string of recent session summaries, or empty string
        """
        try:
            from app.repositories.thread_repository import get_thread_repository
            repo = get_thread_repository()

            threads = repo.get_threads_with_summaries(
                user_id=user_id,
                limit=limit,
                organization_id=organization_id,
            )
            if not threads:
                return ""

            parts = [
                "=== LỊCH SỬ CÁC PHIÊN TRƯỚC (Tham khảo — KHÔNG phải cuộc trò chuyện hiện tại) ===",
                "⚠️ Đây là tóm tắt từ các phiên CŨ. KHÔNG tuyên bố user 'vừa nói' hay 'vừa hỏi' nội dung này.",
            ]
            for t in threads:
                summary = t.get("summary", "")
                title = t.get("title", "")
                if summary:
                    parts.append(f"• [Phiên cũ] {title}: {summary}")

            result = "\n".join(parts)
            logger.info("[SESSION_SUMMARY] Layer 3 context: %d summaries for %s", len(threads), user_id)
            return result

        except Exception as e:
            logger.warning("Failed to get recent summaries: %s", e)
            return ""

    def _save_summary(
        self,
        thread_id: str,
        user_id: str,
        summary: str,
        organization_id: Optional[str] = None,
    ) -> None:
        """Save summary to thread_views.extra_data."""
        try:
            from app.repositories.thread_repository import get_thread_repository
            repo = get_thread_repository()
            repo.update_extra_data(
                thread_id=thread_id,
                user_id=user_id,
                extra_data={"summary": summary},
                organization_id=organization_id,
            )
        except Exception as e:
            logger.debug("Failed to save summary: %s", e)

    async def _load_thread_messages(self, thread_id: str) -> list[dict]:
        """
        Load messages from a thread.

        Note: LangGraph checkpointer removed (De-LangGraphing Phase 3).
        Returns empty list — callers should pass messages explicitly.
        """
        return []

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """Format messages into text for summarization."""
        parts = []
        for msg in messages[-15:]:  # Last 15 messages for summarization
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                label = "Người dùng" if role in ("human", "user") else "Trợ lý"
                parts.append(f"{label}: {content[:300]}")
        return "\n".join(parts)


# =============================================================================
# Singleton
# =============================================================================

_summarizer: Optional[SessionSummarizer] = None


def get_session_summarizer() -> SessionSummarizer:
    """Get or create the SessionSummarizer singleton."""
    global _summarizer
    if _summarizer is None:
        _summarizer = SessionSummarizer()
    return _summarizer
