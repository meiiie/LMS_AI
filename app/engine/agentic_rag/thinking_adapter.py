"""
Thinking Adapter - SOTA 2025 Cache-Augmented Generation.

Adapts cached responses with fresh thinking for natural UX.

Instead of returning raw cached responses (anti-pattern),
this adapter generates contextual, adapted responses using
cached knowledge as context.

Pattern References:
- CAG (Cache-Augmented Generation)
- IoT (Iteration of Thought)
- Think in Blocks (adaptive depth reasoning)

Feature: semantic-cache-phase2
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.engine.llm_pool import get_llm_light

logger = logging.getLogger(__name__)


@dataclass
class AdaptedResponse:
    """Result of thinking adapter processing."""
    answer: str
    thinking: str
    original_cached: bool = True
    adaptation_time_ms: float = 0.0
    adaptation_method: str = "light_llm"


class ThinkingAdapter:
    """
    SOTA 2025: Adapt cached responses with context-aware thinking.
    
    When cache hit occurs, don't return raw response.
    Instead, use LIGHT tier LLM to:
    1. Analyze conversation context
    2. Consider why user is asking (again)
    3. Generate natural, adapted response
    
    This follows patterns from ChatGPT/Claude/Gemini where
    cached knowledge is used as context but response is always fresh.
    
    **Feature: semantic-cache-phase2**
    
    Usage:
        adapter = ThinkingAdapter()
        
        # When cache hit
        if cache_result.hit:
            adapted = await adapter.adapt(
                query=query,
                cached_response=cache_result.value,
                context=user_context
            )
            return adapted
    """
    
    def __init__(self):
        """Initialize thinking adapter with LIGHT tier LLM."""
        self._llm = None  # Lazy initialization
        self._initialized = False
        
        # Configuration
        self._max_thinking_tokens = 500
        self._max_response_tokens = 2000
        
        logger.info("[ThinkingAdapter] Initialized (LIGHT tier)")
    
    def _ensure_llm(self):
        """Lazily initialize LLM on first use."""
        if not self._initialized:
            self._llm = get_llm_light()
            self._initialized = True
    
    async def adapt(
        self,
        query: str,
        cached_response: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        similarity: float = 1.0
    ) -> AdaptedResponse:
        """
        Adapt cached response with fresh thinking.
        
        Args:
            query: Current user query
            cached_response: Previously cached answer data
            context: Conversation context (history, user info)
            similarity: Cache hit similarity score
            
        Returns:
            AdaptedResponse with fresh thinking and natural answer
        """
        start_time = time.time()
        self._ensure_llm()
        
        try:
            # Extract cached data
            cached_answer = cached_response.get("answer", "")
            cached_sources = cached_response.get("sources", [])
            cached_thinking = cached_response.get("thinking", "")
            
            # Build context for adaptation
            history_summary = self._build_history_summary(context)
            user_profile = self._build_user_profile(context)
            
            # Generate adapted response
            prompt = self._build_adaptation_prompt(
                query=query,
                cached_answer=cached_answer,
                cached_thinking=cached_thinking,
                history_summary=history_summary,
                user_profile=user_profile,
                similarity=similarity
            )
            
            # Use LIGHT tier for speed (~2-3s)
            response = await self._llm.ainvoke(prompt)
            
            # Parse response
            thinking, adapted_answer = self._parse_response(response.content)
            
            adaptation_time = (time.time() - start_time) * 1000
            
            logger.info(
                f"[ThinkingAdapter] Adapted response in {adaptation_time:.0f}ms "
                f"(similarity={similarity:.3f})"
            )
            
            return AdaptedResponse(
                answer=adapted_answer if adapted_answer else cached_answer,
                thinking=thinking if thinking else f"[Adapted from cache] {cached_thinking[:200]}...",
                original_cached=False,
                adaptation_time_ms=adaptation_time,
                adaptation_method="light_llm"
            )
            
        except Exception as e:
            logger.warning(f"[ThinkingAdapter] Adaptation failed: {e}, using raw cache")
            
            # Fallback to raw cached response
            return AdaptedResponse(
                answer=cached_response.get("answer", ""),
                thinking=f"[Cache fallback] {cached_response.get('thinking', 'No thinking available')}",
                original_cached=True,
                adaptation_time_ms=(time.time() - start_time) * 1000,
                adaptation_method="fallback"
            )
    
    def _build_adaptation_prompt(
        self,
        query: str,
        cached_answer: str,
        cached_thinking: str,
        history_summary: str,
        user_profile: str,
        similarity: float
    ) -> str:
        """Build prompt for response adaptation."""
        
        # Determine adaptation strategy based on similarity
        if similarity >= 0.99:
            adaptation_instruction = """
            Câu hỏi gần như giống hệt câu đã hỏi trước đó.
            Nhiệm vụ: Trả lời tự nhiên, có thể:
            - Xác nhận lại thông tin
            - Bổ sung chi tiết nếu cần
            - Điều chỉnh ngôn ngữ phù hợp ngữ cảnh
            """
        else:
            adaptation_instruction = """
            Câu hỏi tương tự nhưng có thể có góc độ khác.
            Nhiệm vụ: 
            - Phân tích xem người dùng cần gì khác
            - Điều chỉnh câu trả lời phù hợp
            - Giữ nguyên thông tin chính xác
            """
        
        return f"""Bạn là Maritime AI Tutor. Bạn đã có sẵn kiến thức từ lần trả lời trước.

[KIẾN THỨC ĐÃ CÓ]
{cached_answer[:1500]}

[SUY NGHĨ TRƯỚC ĐÓ]
{cached_thinking[:500] if cached_thinking else "Không có"}

[NGỮ CẢNH HIỆN TẠI]
- Câu hỏi: {query}
- Lịch sử: {history_summary}
- Người dùng: {user_profile}
- Độ tương đồng: {similarity:.2%}

[HƯỚNG DẪN]
{adaptation_instruction}

[FORMAT]
<thinking>
[Suy nghĩ ngắn gọn về cách điều chỉnh câu trả lời]
</thinking>

<answer>
[Câu trả lời tự nhiên, có thể dựa trên kiến thức đã có]
</answer>

Trả lời:"""

    def _parse_response(self, content: str) -> tuple[str, str]:
        """Parse thinking and answer from response."""
        thinking = ""
        answer = ""
        
        # Extract thinking
        if "<thinking>" in content and "</thinking>" in content:
            start = content.find("<thinking>") + len("<thinking>")
            end = content.find("</thinking>")
            thinking = content[start:end].strip()
        
        # Extract answer
        if "<answer>" in content and "</answer>" in content:
            start = content.find("<answer>") + len("<answer>")
            end = content.find("</answer>")
            answer = content[start:end].strip()
        elif "</thinking>" in content:
            # If no answer tags, use everything after thinking
            answer = content[content.find("</thinking>") + len("</thinking>"):].strip()
        else:
            # No tags, use full content
            answer = content.strip()
        
        return thinking, answer
    
    def _build_history_summary(self, context: Optional[Dict]) -> str:
        """Build summary of conversation history."""
        if not context:
            return "Không có lịch sử"
        
        history = context.get("chat_history", [])
        if not history:
            return "Cuộc trò chuyện mới"
        
        # Summarize last few exchanges
        recent = history[-4:] if len(history) > 4 else history
        summary_parts = []
        for msg in recent:
            role = "Người dùng" if msg.get("role") == "user" else "AI"
            content = msg.get("content", "")[:50]
            summary_parts.append(f"{role}: {content}...")
        
        return " | ".join(summary_parts) if summary_parts else "Cuộc trò chuyện mới"
    
    def _build_user_profile(self, context: Optional[Dict]) -> str:
        """Build user profile summary."""
        if not context:
            return "Không rõ"
        
        parts = []
        
        user_name = context.get("user_name")
        if user_name:
            parts.append(f"Tên: {user_name}")
        
        role = context.get("user_role", "student")
        parts.append(f"Vai trò: {role}")
        
        # Add any semantic memory context
        semantic = context.get("semantic_context", "")
        if semantic:
            parts.append(f"Profile: {semantic[:100]}...")
        
        return ", ".join(parts) if parts else "Người dùng mới"


# Singleton
_thinking_adapter: Optional[ThinkingAdapter] = None


def get_thinking_adapter() -> ThinkingAdapter:
    """Get or create ThinkingAdapter singleton."""
    global _thinking_adapter
    if _thinking_adapter is None:
        _thinking_adapter = ThinkingAdapter()
    return _thinking_adapter
