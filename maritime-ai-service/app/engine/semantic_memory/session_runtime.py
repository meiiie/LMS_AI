"""Session summarization and maintenance helpers for SemanticMemoryEngine."""

from __future__ import annotations

import json
from typing import List, Optional

from app.engine.semantic_memory.privacy import (
    hash_memory_identifier,
    memory_log_reference,
)
from app.engine.semantic_memory.write_audit import resolve_memory_write_scope
from app.engine.semantic_memory.write_audit import resolve_memory_read_scope
from app.models.semantic_memory import (
    ConversationSummary,
    Insight,
    InsightCategory,
    MemoryType,
    SemanticMemorySearchResult,
)


def count_tokens_impl(text: str, logger_obj) -> int:
    """Count tokens with tiktoken fallback."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except ImportError:
        return len(text) // 4
    except Exception as exc:
        logger_obj.warning("Token counting failed: %s", exc)
        return len(text) // 4


def get_session_messages_impl(repository, user_id: str, session_id: str, logger_obj) -> List[SemanticMemorySearchResult]:
    """Load chronological session messages using the repository fast path."""
    scope = resolve_memory_read_scope()
    if not scope.write_allowed:
        logger_obj.warning(
            "Session memory read blocked for user_hash=%s: %s",
            hash_memory_identifier(user_id),
            scope.state,
        )
        return []

    try:
        session_messages = repository.get_memories_by_type(
            user_id=user_id,
            memory_type=MemoryType.MESSAGE,
            session_id=session_id,
        )
        session_messages.sort(key=lambda item: item.created_at)
        return session_messages
    except Exception as exc:
        logger_obj.error("Failed to get session messages: %s", exc)
        return []


def count_session_tokens_impl(repository, user_id: str, session_id: str, count_tokens_fn, logger_obj) -> int:
    """Count tokens for all message memories in a session."""
    scope = resolve_memory_read_scope()
    if not scope.write_allowed:
        logger_obj.warning(
            "Session token memory read blocked for user_hash=%s: %s",
            hash_memory_identifier(user_id),
            scope.state,
        )
        return 0

    try:
        messages = repository.get_memories_by_type(
            user_id=user_id,
            memory_type=MemoryType.MESSAGE,
            session_id=session_id,
        )
        total = 0
        for message in messages:
            total += count_tokens_fn(message.content)
        return total
    except Exception as exc:
        logger_obj.error("Failed to count session tokens: %s", exc)
        return 0


async def generate_summary_impl(llm, conversation_text: str, extract_thinking_fn, logger_obj) -> tuple[str, list[str]]:
    """Generate a summary JSON payload with the configured LLM."""
    prompt = f"""Summarize the following conversation between a user and an AI tutor.

Conversation:
{conversation_text}

Provide:
1. A concise summary (2-3 paragraphs) capturing the main points discussed
2. A list of key topics covered

Format your response as JSON:
{{
    "summary": "Your summary here...",
    "key_topics": ["topic1", "topic2", "topic3"]
}}

Return ONLY valid JSON:"""

    try:
        response = await llm.ainvoke(prompt)
        text_content, _ = extract_thinking_fn(response.content)
        content = text_content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        data = json.loads(content)
        return data.get("summary", ""), data.get("key_topics", [])
    except Exception as exc:
        logger_obj.error("Summary generation failed: %s", exc)
        return conversation_text[:500] + "...", []


async def summarize_session_impl(engine, user_id: str, session_id: str, token_count: int, extract_thinking_fn, logger_obj) -> Optional[ConversationSummary]:
    """Summarize a session and replace raw messages with a summary memory."""
    engine._ensure_llm()
    if not engine._llm:
        logger_obj.warning("LLM not available for summarization")
        return None

    try:
        messages = engine._get_session_messages(user_id, session_id)
        if not messages:
            return None

        conversation_text = "\n".join([message.content for message in messages])
        summary_text, key_topics = await engine._generate_summary(conversation_text)

        summary = ConversationSummary(
            user_id=user_id,
            session_id=session_id,
            summary_text=summary_text,
            original_message_count=len(messages),
            original_token_count=token_count,
            key_topics=key_topics,
        )

        summary_embeddings = await engine._embeddings.aembed_documents([summary_text])
        summary_embedding = summary_embeddings[0]
        summary_memory = summary.to_semantic_memory_create(summary_embedding)
        engine._repository.save_memory(summary_memory)
        engine._repository.delete_by_session(user_id, session_id)

        logger_obj.info(
            "Summarized session %s: %d messages -> 1 summary",
            session_id,
            len(messages),
        )
        return summary
    except Exception as exc:
        logger_obj.error("Session summarization failed: %s", exc)
        return None


async def check_and_summarize_impl(engine, user_id: str, session_id: str, threshold: int, logger_obj) -> Optional[ConversationSummary]:
    """Run threshold check before summarizing a session."""
    try:
        current_tokens = engine.count_session_tokens(user_id, session_id)
        if current_tokens < threshold:
            logger_obj.debug(
                "Session %s has %d tokens, below threshold %d",
                session_id,
                current_tokens,
                threshold,
            )
            return None

        logger_obj.info(
            "Session %s has %d tokens, triggering summarization",
            session_id,
            current_tokens,
        )
        return await engine._summarize_session(
            user_id=user_id,
            session_id=session_id,
            token_count=current_tokens,
        )
    except Exception as exc:
        logger_obj.error("Summarization check failed: %s", exc)
        return None


async def delete_memory_by_keyword_impl(repository, user_id: str, keyword: str, logger_obj) -> int:
    """Delete memories by keyword and log result."""
    scope = resolve_memory_write_scope()
    if not scope.write_allowed:
        logger_obj.warning(
            "Keyword memory delete blocked for user_hash=%s: %s",
            hash_memory_identifier(user_id),
            scope.state,
        )
        return 0

    try:
        deleted = repository.delete_memories_by_keyword(user_id=user_id, keyword=keyword)
        if deleted > 0:
            logger_obj.info(
                "Deleted %d memories matching keyword_ref=%s for user_hash=%s",
                deleted,
                memory_log_reference(keyword),
                hash_memory_identifier(user_id),
            )
        return deleted
    except Exception as exc:
        logger_obj.error("Failed to delete memories by keyword: %s", exc)
        return 0


async def delete_all_user_memories_impl(repository, user_id: str, logger_obj) -> int:
    """Delete all memories for a user."""
    scope = resolve_memory_write_scope()
    if not scope.write_allowed:
        logger_obj.warning(
            "Full memory delete blocked for user_hash=%s: %s",
            hash_memory_identifier(user_id),
            scope.state,
        )
        return 0

    try:
        deleted = repository.delete_all_user_memories(user_id=user_id)
        logger_obj.info(
            "Deleted ALL %d memories for user_hash=%s (factory reset)",
            deleted,
            hash_memory_identifier(user_id),
        )
        return deleted
    except Exception as exc:
        logger_obj.error(
            "Failed to delete all memories for user_hash=%s: %s",
            hash_memory_identifier(user_id),
            exc,
        )
        return 0


async def store_explicit_insight_impl(engine, user_id: str, insight_text: str, category: str, session_id: Optional[str], logger_obj) -> bool:
    """Store an explicit insight via InsightProvider."""
    try:
        try:
            insight_category = InsightCategory(category)
        except ValueError:
            insight_category = InsightCategory.PREFERENCE

        insight = Insight(
            user_id=user_id,
            content=insight_text,
            category=insight_category,
            confidence=1.0,
            source_messages=[insight_text],
        )

        stored = await engine._insight_provider._store_insight(insight, session_id)
        if stored:
            logger_obj.info(
                "Stored explicit insight for user_hash=%s content_ref=%s",
                hash_memory_identifier(user_id),
                memory_log_reference(insight_text),
            )
        return stored
    except Exception as exc:
        logger_obj.error("Failed to store explicit insight: %s", exc)
        return False
