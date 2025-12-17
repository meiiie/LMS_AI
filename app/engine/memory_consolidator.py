"""
Memory Consolidator - CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN
Consolidate memories when approaching capacity.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.models.semantic_memory import Insight, InsightCategory

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """Result of memory consolidation."""
    success: bool
    original_count: int
    final_count: int
    consolidated_insights: List[Insight]
    error: Optional[str] = None


class MemoryConsolidator:
    """Consolidate memories when approaching capacity."""
    
    CONSOLIDATION_THRESHOLD = 40
    TARGET_COUNT = 30
    
    def __init__(self):
        """Initialize the consolidator."""
        self._llm = None
        if settings.google_api_key:
            try:
                from app.engine.llm_pool import get_llm_light
                # SOTA: Use shared LLM from pool (memory optimized)
                self._llm = get_llm_light()
                logger.info("MemoryConsolidator initialized with shared LIGHT tier LLM")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
    
    async def should_consolidate(self, memory_count: int) -> bool:
        """Check if consolidation is needed."""
        return memory_count >= self.CONSOLIDATION_THRESHOLD

    
    async def consolidate(self, insights: List[Insight]) -> ConsolidationResult:
        """
        Run consolidation process.
        
        Args:
            insights: List of insights to consolidate
            
        Returns:
            ConsolidationResult with consolidated insights
        """
        original_count = len(insights)
        
        if not self._llm:
            return ConsolidationResult(
                success=False,
                original_count=original_count,
                final_count=original_count,
                consolidated_insights=insights,
                error="LLM not available"
            )
        
        try:
            # Build consolidation prompt
            prompt = self._build_consolidation_prompt(insights)
            
            # Call LLM for consolidation
            response = await self._llm.ainvoke(prompt)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            
            # Parse consolidated insights
            consolidated = self._parse_consolidation_response(text_content, insights)
            
            # Verify we achieved target count
            final_count = len(consolidated)
            if final_count > self.TARGET_COUNT:
                logger.warning(f"Consolidation didn't reach target: {final_count} > {self.TARGET_COUNT}")
                # Keep only the most recent ones
                consolidated = sorted(consolidated, key=lambda x: x.created_at or datetime.min, reverse=True)
                consolidated = consolidated[:self.TARGET_COUNT]
                final_count = len(consolidated)
            
            logger.info(f"Consolidation: {original_count} → {final_count} insights")
            
            return ConsolidationResult(
                success=True,
                original_count=original_count,
                final_count=final_count,
                consolidated_insights=consolidated
            )
            
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return ConsolidationResult(
                success=False,
                original_count=original_count,
                final_count=original_count,
                consolidated_insights=insights,
                error=str(e)
            )
    
    def _build_consolidation_prompt(self, insights: List[Insight]) -> str:
        """Build prompt for LLM consolidation."""
        # Build insight list for prompt
        insight_list = []
        for i, insight in enumerate(insights):
            insight_list.append(f"{i+1}. [{insight.category.value}] {insight.content}")
            if insight.sub_topic:
                insight_list[-1] += f" (Topic: {insight.sub_topic})"
            if insight.created_at:
                insight_list[-1] += f" (Created: {insight.created_at.strftime('%Y-%m-%d')})"
        
        insights_text = "\n".join(insight_list)
        
        prompt = f"""
Bạn là chuyên gia quản lý bộ nhớ AI. Nhiệm vụ của bạn là consolidate (gộp và tinh gọn) danh sách insights về người dùng.

HIỆN TẠI: {len(insights)} insights
MỤC TIÊU: Giảm xuống tối đa {self.TARGET_COUNT} insights cốt lõi

NGUYÊN TẮC CONSOLIDATION:
1. **Merge duplicates**: Gộp các insights tương tự thành một
2. **Update evolution**: Nếu có thay đổi theo thời gian, ghi nhận sự phát triển
3. **Keep recent**: Ưu tiên thông tin mới nhất và quan trọng nhất
4. **Preserve diversity**: Giữ đa dạng các categories (learning_style, knowledge_gap, etc.)
5. **Remove redundant**: Loại bỏ thông tin không còn quan trọng

DANH SÁCH INSIGHTS HIỆN TẠI:
{insights_text}

YÊU CẦU OUTPUT:
- Trả về JSON array với tối đa {self.TARGET_COUNT} insights đã được consolidate
- Mỗi insight phải giữ format gốc nhưng content có thể được merge/update
- Nếu merge nhiều insights, ghi rõ trong evolution_notes
- Ưu tiên giữ insights về knowledge_gap và learning_style

FORMAT:
[
  {{
    "category": "learning_style",
    "content": "User thích học qua ví dụ thực tế và case studies, đã phát triển từ việc chỉ đọc lý thuyết sang áp dụng thực hành",
    "sub_topic": "practical_learning",
    "confidence": 0.9,
    "evolution_notes": ["Merged from insights #1, #3, #7", "Updated based on recent behavior"]
  }}
]

Hãy consolidate một cách thông minh để giữ lại thông tin quan trọng nhất!
"""
        return prompt

    
    def _parse_consolidation_response(
        self, 
        response: str, 
        original_insights: List[Insight]
    ) -> List[Insight]:
        """Parse LLM consolidation response into Insight objects."""
        consolidated = []
        
        try:
            # Extract JSON from response
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            
            # Parse JSON
            data = json.loads(response)
            
            if not isinstance(data, list):
                logger.warning(f"Expected list, got {type(data)}")
                return original_insights[:self.TARGET_COUNT]  # Fallback
            
            # Get user_id from original insights
            user_id = original_insights[0].user_id if original_insights else "unknown"
            
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                # Validate required fields
                category = item.get("category", "").lower()
                content = item.get("content", "").strip()
                
                if not category or not content:
                    continue
                
                # Validate category
                try:
                    insight_category = InsightCategory(category)
                except ValueError:
                    logger.warning(f"Invalid category in consolidation: {category}")
                    continue
                
                # Create consolidated insight
                insight = Insight(
                    user_id=user_id,
                    content=content,
                    category=insight_category,
                    sub_topic=item.get("sub_topic"),
                    confidence=float(item.get("confidence", 0.8)),
                    evolution_notes=item.get("evolution_notes", []),
                    created_at=datetime.now(),  # New creation time for consolidated insight
                    last_accessed=datetime.now()
                )
                consolidated.append(insight)
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse consolidation JSON: {e}")
            logger.debug(f"Response was: {response}")
            return original_insights[:self.TARGET_COUNT]  # Fallback
        except Exception as e:
            logger.error(f"Failed to parse consolidation response: {e}")
            return original_insights[:self.TARGET_COUNT]  # Fallback
        
        # If we got too few insights, pad with most recent originals
        if len(consolidated) < min(self.TARGET_COUNT, len(original_insights)):
            remaining_slots = min(self.TARGET_COUNT, len(original_insights)) - len(consolidated)
            # Sort originals by creation time (most recent first)
            sorted_originals = sorted(
                original_insights, 
                key=lambda x: x.created_at or datetime.min, 
                reverse=True
            )
            # Add most recent originals that weren't consolidated
            for original in sorted_originals[:remaining_slots]:
                # Check if this insight wasn't already represented in consolidated
                if not any(self._is_similar_insight(original, cons) for cons in consolidated):
                    consolidated.append(original)
        
        return consolidated[:self.TARGET_COUNT]
    
    def _is_similar_insight(self, insight1: Insight, insight2: Insight) -> bool:
        """Check if two insights are similar (to avoid duplication)."""
        # Same category and similar content
        if insight1.category != insight2.category:
            return False
        
        # Simple content similarity check
        words1 = set(insight1.content.lower().split())
        words2 = set(insight2.content.lower().split())
        
        if not words1 or not words2:
            return False
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        similarity = intersection / union if union > 0 else 0
        
        return similarity > 0.5  # 50% similarity threshold
