"""
Memory Summarizer - Compress conversation history into summaries.

CHỈ THỊ KỸ THUẬT SỐ 16: MEMORY COMPRESSION
- Tiered Memory Architecture (3 tầng)
- Tầng 1: Raw Short-term (5-10 tin nhắn gần nhất)
- Tầng 2: Summarized Episodic (Tóm tắt theo đợt)
- Tầng 3: Semantic/Long-term (Facts lâu dài)

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 16**
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ConversationSummary:
    """Summary of a conversation segment."""
    summary_text: str
    message_count: int
    topics: List[str] = field(default_factory=list)
    user_state: Optional[str] = None  # "đói", "mệt", etc.
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TieredMemoryState:
    """
    Tiered Memory State for a conversation.
    
    Tầng 1: raw_messages - 5-10 tin nhắn gần nhất (nguyên văn)
    Tầng 2: summaries - Tóm tắt các đoạn hội thoại trước
    Tầng 3: user_facts - Facts lâu dài (từ Semantic Memory)
    """
    raw_messages: List[Dict[str, str]] = field(default_factory=list)
    summaries: List[ConversationSummary] = field(default_factory=list)
    user_facts: List[str] = field(default_factory=list)
    total_messages_processed: int = 0
    
    def get_context_for_prompt(self, max_raw: int = 6) -> str:
        """
        Build context string for LLM prompt.
        
        Returns:
            Formatted context with summaries + recent messages
        """
        parts = []
        
        # Add summaries first (older context)
        if self.summaries:
            summary_texts = [s.summary_text for s in self.summaries[-3:]]  # Last 3 summaries
            parts.append("TÓM TẮT HỘI THOẠI TRƯỚC:")
            parts.extend(summary_texts)
            parts.append("")
        
        # Add user state if recent
        recent_state = self._get_recent_user_state()
        if recent_state:
            parts.append(f"TRẠNG THÁI USER: {recent_state}")
            parts.append("")
        
        # Add recent messages
        if self.raw_messages:
            parts.append("HỘI THOẠI GẦN ĐÂY:")
            for msg in self.raw_messages[-max_raw:]:
                role = "User" if msg.get("role") == "user" else "AI"
                parts.append(f"{role}: {msg.get('content', '')}")
        
        return "\n".join(parts)
    
    def _get_recent_user_state(self) -> Optional[str]:
        """Get user's emotional state from recent summaries."""
        for summary in reversed(self.summaries):
            if summary.user_state:
                return summary.user_state
        return None


class MemorySummarizer:
    """
    Summarize and compress conversation history.
    
    Uses LLM to create summaries when conversation gets too long.
    """
    
    # Thresholds
    MAX_RAW_MESSAGES = 10  # Trigger summarization after this many messages
    SUMMARIZE_BATCH_SIZE = 4  # Number of messages to summarize at once
    
    def __init__(self):
        """Initialize MemorySummarizer."""
        self._llm = None
        self._states: Dict[str, TieredMemoryState] = {}  # session_id -> state
        
        self._init_llm()
    
    def _init_llm(self) -> None:
        """Initialize LLM from shared pool for summarization."""
        try:
            from app.engine.llm_pool import get_llm_light
            
            if settings.google_api_key:
                # SOTA: Use shared LLM from pool (memory optimized)
                self._llm = get_llm_light()
                logger.info(f"MemorySummarizer initialized with shared LIGHT tier LLM")
            else:
                logger.warning("No Google API key for MemorySummarizer")
        except Exception as e:
            logger.error(f"Failed to initialize summarizer LLM: {e}")
    
    def get_state(self, session_id: str) -> TieredMemoryState:
        """Get or create memory state for a session."""
        if session_id not in self._states:
            self._states[session_id] = TieredMemoryState()
        return self._states[session_id]
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> TieredMemoryState:
        """
        Add a message to the memory state.
        
        Args:
            session_id: Session identifier
            role: "user" or "assistant"
            content: Message content
            
        Returns:
            Updated memory state
        """
        state = self.get_state(session_id)
        
        # Add to raw messages
        state.raw_messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        state.total_messages_processed += 1
        
        # Check if we need to summarize
        if len(state.raw_messages) > self.MAX_RAW_MESSAGES:
            self._trigger_summarization(session_id)
        
        return state
    
    async def add_message_async(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> TieredMemoryState:
        """Async version of add_message with summarization."""
        state = self.get_state(session_id)
        
        state.raw_messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        state.total_messages_processed += 1
        
        # Async summarization
        if len(state.raw_messages) > self.MAX_RAW_MESSAGES:
            await self._trigger_summarization_async(session_id)
        
        return state
    
    def _trigger_summarization(self, session_id: str) -> None:
        """Trigger synchronous summarization (fallback)."""
        state = self.get_state(session_id)
        
        if not self._llm:
            # No LLM, just trim old messages
            state.raw_messages = state.raw_messages[-6:]
            return
        
        # Get oldest messages to summarize
        to_summarize = state.raw_messages[:self.SUMMARIZE_BATCH_SIZE]
        
        try:
            summary = self._create_summary_sync(to_summarize)
            if summary:
                state.summaries.append(summary)
                # Remove summarized messages
                state.raw_messages = state.raw_messages[self.SUMMARIZE_BATCH_SIZE:]
                logger.info(f"Summarized {self.SUMMARIZE_BATCH_SIZE} messages for session {session_id}")
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            # Fallback: just trim
            state.raw_messages = state.raw_messages[-6:]
    
    async def _trigger_summarization_async(self, session_id: str) -> None:
        """Trigger async summarization."""
        state = self.get_state(session_id)
        
        if not self._llm:
            state.raw_messages = state.raw_messages[-6:]
            return
        
        to_summarize = state.raw_messages[:self.SUMMARIZE_BATCH_SIZE]
        
        try:
            summary = await self._create_summary_async(to_summarize)
            if summary:
                state.summaries.append(summary)
                state.raw_messages = state.raw_messages[self.SUMMARIZE_BATCH_SIZE:]
                logger.info(f"Async summarized {self.SUMMARIZE_BATCH_SIZE} messages")
        except Exception as e:
            logger.error(f"Async summarization failed: {e}")
            state.raw_messages = state.raw_messages[-6:]
    
    def _create_summary_sync(self, messages: List[Dict]) -> Optional[ConversationSummary]:
        """Create summary synchronously."""
        if not messages or not self._llm:
            return None
        
        prompt = self._build_summary_prompt(messages)
        
        try:
            response = self._llm.invoke(prompt)
            return self._parse_summary_response(response.content, len(messages))
        except Exception as e:
            logger.error(f"Summary creation failed: {e}")
            return None
    
    async def _create_summary_async(self, messages: List[Dict]) -> Optional[ConversationSummary]:
        """Create summary asynchronously."""
        if not messages or not self._llm:
            return None
        
        prompt = self._build_summary_prompt(messages)
        
        try:
            response = await self._llm.ainvoke(prompt)
            return self._parse_summary_response(response.content, len(messages))
        except Exception as e:
            logger.error(f"Async summary creation failed: {e}")
            return None
    
    def _build_summary_prompt(self, messages: List[Dict]) -> str:
        """Build prompt for summarization."""
        conversation = "\n".join([
            f"{'User' if m['role'] == 'user' else 'AI'}: {m['content']}"
            for m in messages
        ])
        
        return f"""Tóm tắt ngắn gọn đoạn hội thoại sau (1-2 câu).
Giữ lại:
- Chủ đề chính đang thảo luận
- Trạng thái cảm xúc của user nếu có (đói, mệt, vui...)
- Thông tin quan trọng user chia sẻ

Hội thoại:
{conversation}

Trả lời theo format:
SUMMARY: [tóm tắt 1-2 câu]
USER_STATE: [trạng thái cảm xúc nếu có, hoặc "none"]
TOPICS: [chủ đề 1, chủ đề 2]"""
    
    def _parse_summary_response(self, response: str, msg_count: int) -> ConversationSummary:
        """Parse LLM response into ConversationSummary."""
        summary_text = ""
        user_state = None
        topics = []
        
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("SUMMARY:"):
                summary_text = line[8:].strip()
            elif line.startswith("USER_STATE:"):
                state = line[11:].strip().lower()
                if state and state != "none":
                    user_state = state
            elif line.startswith("TOPICS:"):
                topics_str = line[7:].strip()
                topics = [t.strip() for t in topics_str.split(",") if t.strip()]
        
        # Fallback if parsing failed
        if not summary_text:
            summary_text = response[:200]  # Use first 200 chars
        
        return ConversationSummary(
            summary_text=summary_text,
            message_count=msg_count,
            topics=topics,
            user_state=user_state
        )
    
    def get_context_for_prompt(self, session_id: str) -> str:
        """Get formatted context for LLM prompt."""
        state = self.get_state(session_id)
        return state.get_context_for_prompt()
    
    async def get_summary_async(self, session_id: str) -> Optional[str]:
        """
        Get conversation summary for a session (async).
        
        This method is called by ChatService to get a summary of the conversation
        to pass to UnifiedAgent for context.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Formatted summary string, or None if no summaries exist
        """
        state = self.get_state(session_id)
        
        # If no summaries yet, return None
        if not state.summaries:
            return None
        
        # Build summary from tiered memory
        parts = []
        
        # Add summaries (episodic memory - Tầng 2)
        if state.summaries:
            summary_texts = [s.summary_text for s in state.summaries[-3:]]  # Last 3 summaries
            parts.append("TÓM TẮT HỘI THOẠI:")
            parts.extend(summary_texts)
        
        # Add user state if detected
        recent_state = state._get_recent_user_state()
        if recent_state:
            parts.append(f"\nTRẠNG THÁI USER: {recent_state}")
        
        # Add topics discussed
        all_topics = []
        for summary in state.summaries:
            all_topics.extend(summary.topics)
        if all_topics:
            unique_topics = list(dict.fromkeys(all_topics))  # Preserve order, remove duplicates
            parts.append(f"\nCHỦ ĐỀ ĐÃ THẢO LUẬN: {', '.join(unique_topics[:5])}")
        
        return "\n".join(parts) if parts else None
    
    def get_summary(self, session_id: str) -> Optional[str]:
        """
        Sync version of get_summary_async.
        
        For use in non-async contexts.
        """
        state = self.get_state(session_id)
        
        if not state.summaries:
            return None
        
        parts = []
        
        if state.summaries:
            summary_texts = [s.summary_text for s in state.summaries[-3:]]
            parts.append("TÓM TẮT HỘI THOẠI:")
            parts.extend(summary_texts)
        
        recent_state = state._get_recent_user_state()
        if recent_state:
            parts.append(f"\nTRẠNG THÁI USER: {recent_state}")
        
        all_topics = []
        for summary in state.summaries:
            all_topics.extend(summary.topics)
        if all_topics:
            unique_topics = list(dict.fromkeys(all_topics))
            parts.append(f"\nCHỦ ĐỀ ĐÃ THẢO LUẬN: {', '.join(unique_topics[:5])}")
        
        return "\n".join(parts) if parts else None
    
    def clear_session(self, session_id: str) -> None:
        """Clear memory state for a session."""
        if session_id in self._states:
            del self._states[session_id]
    
    def is_available(self) -> bool:
        """Check if summarizer is available."""
        return self._llm is not None


# Singleton
_memory_summarizer: Optional[MemorySummarizer] = None


def get_memory_summarizer() -> MemorySummarizer:
    """Get or create MemorySummarizer singleton."""
    global _memory_summarizer
    if _memory_summarizer is None:
        _memory_summarizer = MemorySummarizer()
    return _memory_summarizer
