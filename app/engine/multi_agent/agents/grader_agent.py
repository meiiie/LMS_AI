"""
Grader Agent Node - Quality Control Specialist

Evaluates response quality and provides feedback.
"""

import logging
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.engine.multi_agent.state import AgentState

logger = logging.getLogger(__name__)


GRADING_PROMPT = """Bạn là Quality Grader cho hệ thống Maritime AI.

Đánh giá chất lượng câu trả lời.

**Query gốc:** {query}

**Câu trả lời:** {answer}

Trả về JSON:
{{
    "score": 0-10,
    "is_helpful": true/false,
    "is_accurate": true/false,
    "is_complete": true/false,
    "feedback": "Góp ý ngắn gọn"
}}

Tiêu chí:
- Helpful: Có trả lời đúng câu hỏi không?
- Accurate: Thông tin có chính xác không?
- Complete: Có đầy đủ thông tin không?

CHỈ TRẢ VỀ JSON."""


class GraderAgentNode:
    """
    Grader Agent - Quality control specialist.
    
    Responsibilities:
    - Evaluate response quality
    - Check accuracy
    - Provide improvement feedback
    """
    
    def __init__(self, min_score: float = 6.0):
        """
        Initialize Grader Agent.
        
        Args:
            min_score: Minimum acceptable score
        """
        self._llm = None
        self._min_score = min_score
        self._init_llm()
        logger.info("GraderAgentNode initialized")
    
    def _init_llm(self):
        """Initialize grading LLM."""
        try:
            self._llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=settings.google_api_key,
                temperature=0.0,  # Consistent grading
                max_output_tokens=300
            )
        except Exception as e:
            logger.error(f"Failed to initialize Grader LLM: {e}")
            self._llm = None
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Grade agent outputs.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with grading results
        """
        query = state.get("query", "")
        outputs = state.get("agent_outputs", {})
        
        # Get the main output
        main_output = (
            outputs.get("rag") or 
            outputs.get("tutor") or 
            outputs.get("memory") or 
            ""
        )
        
        if not main_output:
            state["grader_score"] = 0.0
            state["grader_feedback"] = "No output to grade"
            state["current_agent"] = "grader"
            return state
        
        try:
            result = await self._grade_response(query, main_output)
            
            state["grader_score"] = result.get("score", 5.0)
            state["grader_feedback"] = result.get("feedback", "")
            state["current_agent"] = "grader"
            
            # Log result
            is_pass = result.get("score", 0) >= self._min_score
            logger.info(f"[GRADER] Score={result.get('score', 0)}/10 Pass={is_pass}")
            
        except Exception as e:
            logger.error(f"[GRADER] Error: {e}")
            state["grader_score"] = 5.0  # Default
            state["grader_feedback"] = str(e)
            state["error"] = str(e)
        
        return state
    
    async def _grade_response(self, query: str, answer: str) -> dict:
        """Grade a single response."""
        if not self._llm:
            return self._rule_based_grade(query, answer)
        
        try:
            messages = [
                SystemMessage(content="You are a quality grader. Return only valid JSON."),
                HumanMessage(content=GRADING_PROMPT.format(
                    query=query,
                    answer=answer[:1500]
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            result = response.content.strip()
            
            # Parse JSON
            import json
            if result.startswith("```"):
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            result = result.strip()
            
            return json.loads(result)
            
        except Exception as e:
            logger.warning(f"LLM grading failed: {e}")
            return self._rule_based_grade(query, answer)
    
    def _rule_based_grade(self, query: str, answer: str) -> dict:
        """Fallback rule-based grading."""
        # Simple heuristics
        score = 5.0
        
        # Length check
        if len(answer) > 100:
            score += 1.0
        if len(answer) > 500:
            score += 1.0
        
        # Query word coverage
        query_words = set(query.lower().split())
        answer_lower = answer.lower()
        coverage = sum(1 for w in query_words if w in answer_lower) / max(len(query_words), 1)
        score += coverage * 2
        
        # Cap at 10
        score = min(10.0, score)
        
        return {
            "score": score,
            "is_helpful": score >= 6,
            "is_accurate": True,  # Can't verify without LLM
            "is_complete": len(answer) > 200,
            "feedback": "Rule-based grading"
        }
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_grader_node: Optional[GraderAgentNode] = None

def get_grader_agent_node() -> GraderAgentNode:
    """Get or create GraderAgentNode singleton."""
    global _grader_node
    if _grader_node is None:
        _grader_node = GraderAgentNode()
    return _grader_node
