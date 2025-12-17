"""
Insight Extractor - CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN
Extract behavioral insights from user messages instead of atomic facts.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""
import json
import logging
from typing import List, Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.models.semantic_memory import Insight, InsightCategory

logger = logging.getLogger(__name__)


class InsightExtractor:
    """Extract behavioral insights from user messages."""
    
    INSIGHT_CATEGORIES = [
        "learning_style",    # Phong cách học tập
        "knowledge_gap",     # Lỗ hổng kiến thức
        "goal_evolution",    # Sự thay đổi mục tiêu
        "habit",             # Thói quen học tập
        "preference"         # Sở thích cá nhân
    ]
    
    def __init__(self):
        """Initialize the insight extractor."""
        self._llm = None
        if settings.google_api_key:
            try:
                from app.engine.llm_pool import get_llm_light
                # SOTA: Use shared LLM from pool (memory optimized)
                self._llm = get_llm_light()
                logger.info("InsightExtractor initialized with shared LIGHT tier LLM")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
    
    async def extract_insights(
        self,
        user_id: str,
        message: str,
        conversation_history: Optional[List[str]] = None
    ) -> List[Insight]:
        """
        Extract behavioral insights from message.
        
        Args:
            user_id: User identifier
            message: Current user message
            conversation_history: Previous messages for context
            
        Returns:
            List of extracted insights
        """
        if not self._llm:
            logger.warning("LLM not available for insight extraction")
            return []
        
        try:
            # Build extraction prompt
            prompt = self._build_insight_prompt(message, conversation_history or [])
            
            # Call LLM
            response = await self._llm.ainvoke(prompt)
            
            # Parse response
            insights = self._parse_extraction_response(user_id, response.content, message)
            
            logger.info(f"Extracted {len(insights)} insights for user {user_id}")
            return insights
            
        except Exception as e:
            logger.error(f"Failed to extract insights: {e}")
            return []

    
    def _build_insight_prompt(self, message: str, history: List[str]) -> str:
        """Build prompt for behavioral insight extraction."""
        # Context from conversation history
        context = ""
        if history:
            recent_history = history[-3:]  # Last 3 messages for context
            context = f"\n\nConversation context:\n" + "\n".join([f"- {msg}" for msg in recent_history])
        
        prompt = f"""
Bạn là chuyên gia phân tích hành vi học tập. Nhiệm vụ của bạn là trích xuất BEHAVIORAL INSIGHTS (sự thấu hiểu hành vi) từ tin nhắn của người dùng, KHÔNG PHẢI atomic facts (dữ liệu đơn lẻ).

QUAN TRỌNG: Tập trung vào HÀNH VI, PHONG CÁCH, XU HƯỚNG - không phải tên, tuổi, địa chỉ.

Tin nhắn người dùng: "{message}"{context}

Hãy trích xuất các insights thuộc 5 loại sau:

1. **learning_style**: Phong cách học tập (lý thuyết vs thực hành, tư duy phản biện, cách tiếp cận vấn đề)
   - VÍ DỤ: "User thích học qua ví dụ thực tế hơn là đọc lý thuyết khô khan"
   - VÍ DỤ: "User có xu hướng đặt câu hỏi sâu về nguyên lý thay vì chỉ học thuộc lòng"

2. **knowledge_gap**: Lỗ hổng kiến thức cụ thể (hiểu lầm, nhầm lẫn, thiếu kiến thức)
   - VÍ DỤ: "User còn nhầm lẫn giữa Rule 13 và Rule 15 trong COLREGs"
   - VÍ DỤ: "User chưa hiểu rõ khái niệm 'give-way vessel' trong tình huống cắt hướng"

3. **goal_evolution**: Sự thay đổi mục tiêu học tập theo thời gian
   - VÍ DỤ: "User đã chuyển từ học cơ bản sang chuẩn bị thi bằng thuyền trưởng hạng 3"
   - VÍ DỤ: "User ban đầu chỉ muốn hiểu COLREGs nhưng giờ muốn áp dụng vào thực tế"

4. **habit**: Thói quen học tập và làm việc
   - VÍ DỤ: "User thường học vào buổi tối và thích ôn bài nhiều lần"
   - VÍ DỤ: "User có thói quen ghi chú chi tiết và tạo sơ đồ tư duy"

5. **preference**: Sở thích cá nhân ảnh hưởng đến học tập
   - VÍ DỤ: "User thích các chủ đề liên quan đến navigation hơn là engine room"
   - VÍ DỤ: "User quan tâm đặc biệt đến các tình huống emergency và rescue"

YÊU CẦU FORMAT:
- Mỗi insight phải là câu văn HOÀN CHỈNH mô tả hành vi/xu hướng
- Tối thiểu 20 ký tự
- Bao gồm ngữ cảnh và lý do
- KHÔNG trích xuất tên, tuổi, địa chỉ, số điện thoại

Trả về JSON array:
[
  {{
    "category": "learning_style",
    "content": "User thích học qua ví dụ thực tế và case studies hơn là đọc lý thuyết",
    "sub_topic": "practical_learning",
    "confidence": 0.8
  }}
]

Nếu không tìm thấy insights hành vi nào, trả về: []
"""
        return prompt
    
    def _parse_extraction_response(
        self, 
        user_id: str, 
        response: str, 
        source_message: str
    ) -> List[Insight]:
        """Parse LLM response into Insight objects."""
        insights = []
        
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
                return []
            
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                # Validate required fields
                category = item.get("category", "").lower()
                content = item.get("content", "").strip()
                
                if not category or not content:
                    continue
                
                # Validate category
                if category not in self.INSIGHT_CATEGORIES:
                    logger.warning(f"Invalid category: {category}")
                    continue
                
                # Validate content length (min 20 chars)
                if len(content) < 20:
                    logger.warning(f"Content too short: {content}")
                    continue
                
                # Create insight
                insight = Insight(
                    user_id=user_id,
                    content=content,
                    category=InsightCategory(category),
                    sub_topic=item.get("sub_topic"),
                    confidence=float(item.get("confidence", 0.8)),
                    source_messages=[source_message]
                )
                insights.append(insight)
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response was: {response}")
        except Exception as e:
            logger.error(f"Failed to parse extraction response: {e}")
        
        return insights
