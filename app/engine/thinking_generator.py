"""
Thinking Generator - Natural Vietnamese Thinking from Structured Trace

CHỈ THỊ SỐ 29: SOTA Natural Thinking Display

SOTA Pattern: Qwen QwQ / Claude Extended Thinking
- Generates natural Vietnamese thinking prose
- Uses "người dùng" terminology (not "bạn")
- Based on structured reasoning trace

**Feature: natural-thinking**
"""

import logging
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.engine.llm_factory import create_llm, ThinkingTier
from app.models.schemas import ReasoningTrace

logger = logging.getLogger(__name__)


# =============================================================================
# THINKING PROMPT (Vietnamese)
# =============================================================================

THINKING_SYSTEM_PROMPT = """Bạn là AI chuyên gia phân tích quá trình suy nghĩ.
Nhiệm vụ: Viết QUÁ TRÌNH SUY NGHĨ tự nhiên từ tiến trình xử lý cho sẵn.

QUY TẮC BẮT BUỘC:
1. Viết bằng Tiếng Việt tự nhiên, như đang suy nghĩ thầm
2. Gọi người hỏi là "người dùng" (TUYỆT ĐỐI KHÔNG dùng "bạn", "anh/chị", "em")
3. Giọng văn: tự nhiên, chuyên nghiệp, như nội tâm của chuyên gia
4. Độ dài: 3-5 câu, súc tích nhưng đầy đủ
5. KHÔNG bắt đầu bằng "Đây là..." hay "Tôi sẽ viết..."
6. Bắt đầu trực tiếp với phân tích

CẤU TRÚC:
- Câu 1: Người dùng đang hỏi về gì?
- Câu 2-3: Quá trình tìm kiếm/phân tích cho thấy điều gì?
- Câu 4-5: Tại sao tôi chọn cách trả lời như vậy?

VÍ DỤ OUTPUT:
"Người dùng đang hỏi về Rule 15 COLREGs - quy tắc về tình huống cắt hướng. Sau khi tra cứu cơ sở dữ liệu, tôi tìm thấy Rule 15 quy định khi hai tàu máy cắt hướng nhau, tàu nhìn thấy tàu kia ở mạn phải phải nhường đường. Đây là quy tắc quan trọng trong an toàn hàng hải. Tôi sẽ giải thích với ví dụ thực tế để người dùng dễ hình dung hơn."
"""

THINKING_USER_PROMPT_TEMPLATE = """
TIẾN TRÌNH XỬ LÝ:
{trace_summary}

CÂU HỎI CỦA NGƯỜI DÙNG:
{question}

TÓM TẮT CÂU TRẢ LỜI SẼ ĐƯA RA:
{answer_preview}

Hãy viết quá trình suy nghĩ tự nhiên (chỉ nội dung, không cần tag):
"""


# =============================================================================
# THINKING GENERATOR CLASS
# =============================================================================

class ThinkingGenerator:
    """
    Generates natural Vietnamese thinking from structured reasoning trace.
    
    SOTA Pattern: Qwen QwQ / Claude Extended Thinking
    CHỈ THỊ SỐ 29: Natural Thinking Display
    
    Usage:
        generator = ThinkingGenerator()
        thinking = await generator.generate(trace, question, answer)
    """
    
    def __init__(self):
        """Initialize with LIGHT tier LLM for cost efficiency."""
        self._llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM with LIGHT tier for thinking generation."""
        try:
            # Use LIGHT tier for cost efficiency
            # Thinking generation doesn't need deep reasoning
            self._llm = create_llm(
                tier=ThinkingTier.LIGHT,
                temperature=0.7,  # Slightly creative for natural prose
                include_thoughts=False  # No need for nested thinking
            )
            logger.info("[ThinkingGenerator] Initialized with LIGHT tier LLM")
        except Exception as e:
            logger.error(f"[ThinkingGenerator] Failed to initialize LLM: {e}")
            self._llm = None
    
    def _format_trace_summary(self, trace: ReasoningTrace) -> str:
        """
        Format reasoning trace into readable summary for prompt.
        
        Args:
            trace: Structured reasoning trace
            
        Returns:
            Human-readable summary string
        """
        if not trace or not trace.steps:
            return "Không có thông tin tiến trình"
        
        lines = []
        for i, step in enumerate(trace.steps, 1):
            step_desc = f"{i}. {step.description}: {step.result}"
            if step.confidence is not None:
                step_desc += f" (độ tin cậy: {step.confidence * 100:.0f}%)"
            lines.append(step_desc)
        
        # Add correction note if applicable
        if trace.was_corrected and trace.correction_reason:
            lines.append(f"\n⚠️ Đã điều chỉnh: {trace.correction_reason}")
        
        return "\n".join(lines)
    
    async def generate(
        self,
        trace: ReasoningTrace,
        question: str,
        answer: str,
        max_chars: int = 500
    ) -> Optional[str]:
        """
        Generate natural Vietnamese thinking from structured trace.
        
        SOTA Pattern: Qwen QwQ / Claude Extended Thinking
        
        Args:
            trace: Structured reasoning trace from CRAG
            question: Original user question
            answer: Generated answer (first 200 chars used as preview)
            max_chars: Maximum characters for thinking output
            
        Returns:
            Natural Vietnamese thinking prose, or None if generation fails
        """
        if not self._llm:
            logger.warning("[ThinkingGenerator] LLM not available, skipping")
            return None
        
        if not trace or not trace.steps:
            logger.warning("[ThinkingGenerator] No trace provided, skipping")
            return None
        
        try:
            # Format trace summary
            trace_summary = self._format_trace_summary(trace)
            
            # Truncate answer for preview
            answer_preview = answer[:200] + "..." if len(answer) > 200 else answer
            
            # Build messages
            user_prompt = THINKING_USER_PROMPT_TEMPLATE.format(
                trace_summary=trace_summary,
                question=question,
                answer_preview=answer_preview
            )
            
            messages = [
                SystemMessage(content=THINKING_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt)
            ]
            
            # Generate thinking
            logger.info("[ThinkingGenerator] Generating natural thinking...")
            response = await self._llm.ainvoke(messages)
            
            thinking = response.content.strip()
            
            # Clean up any accidental formatting
            thinking = thinking.strip('"\'')
            
            # Truncate if too long
            if len(thinking) > max_chars:
                thinking = thinking[:max_chars] + "..."
            
            logger.info(f"[ThinkingGenerator] Generated {len(thinking)} chars")
            return thinking
            
        except Exception as e:
            logger.error(f"[ThinkingGenerator] Generation failed: {e}")
            return None


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

_thinking_generator: Optional[ThinkingGenerator] = None


def get_thinking_generator() -> ThinkingGenerator:
    """
    Get singleton ThinkingGenerator instance.
    
    Returns:
        ThinkingGenerator instance
    """
    global _thinking_generator
    if _thinking_generator is None:
        _thinking_generator = ThinkingGenerator()
    return _thinking_generator
