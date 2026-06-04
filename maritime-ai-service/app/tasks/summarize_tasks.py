"""
Session Summarization Tasks — Background conversation summarization

Sprint 18: Virtual Agent-per-User Architecture
Background tasks for generating cross-session context summaries.

These run asynchronously after a conversation ends, so the user
doesn't wait for summarization during their chat session.
"""

import logging

logger = logging.getLogger(__name__)


async def summarize_thread_background(
    thread_id: str,
    user_id: str,
    organization_id: str | None = None,
) -> dict:
    """
    Background task to summarize a specific thread.

    Called when:
    - User starts a new conversation (summarize previous)
    - Conversation idle > 30 minutes
    - Manual trigger via memory agent tool

    Args:
        thread_id: Composite thread ID
        user_id: User ID
        organization_id: Organization ID for multi-tenant isolation

    Returns:
        Dict with summarization result
    """
    try:
        from app.services.session_summarizer import get_session_summarizer
        summarizer = get_session_summarizer()

        summary = await summarizer.summarize_thread(
            thread_id=thread_id,
            user_id=user_id,
            organization_id=organization_id,
        )

        return {
            "thread_id": thread_id,
            "summary": summary,
            "success": summary is not None,
        }

    except Exception as e:
        logger.error("Background summarization failed: %s", e)
        return {
            "thread_id": thread_id,
            "summary": None,
            "success": False,
            "error": str(e),
        }
