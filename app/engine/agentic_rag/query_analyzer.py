"""
Query Analyzer - Phase 7.1

Analyzes query complexity and determines processing strategy.

Features:
- Complexity classification (simple/moderate/complex)
- Multi-step detection
- Verification requirements
- Query decomposition suggestions
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class QueryComplexity(str, Enum):
    """Query complexity levels."""
    SIMPLE = "simple"      # Direct lookup, single fact
    MODERATE = "moderate"  # Requires context, comparison
    COMPLEX = "complex"    # Multi-step reasoning, synthesis


@dataclass
class QueryAnalysis:
    """Result of query analysis."""
    original_query: str
    complexity: QueryComplexity
    requires_multi_step: bool = False
    requires_verification: bool = False
    is_maritime_related: bool = True
    suggested_sub_queries: List[str] = field(default_factory=list)
    detected_topics: List[str] = field(default_factory=list)
    confidence: float = 0.8
    
    def __str__(self):
        return f"QueryAnalysis(complexity={self.complexity.value}, multi_step={self.requires_multi_step})"


ANALYSIS_PROMPT = """Bạn là Query Analyzer cho hệ thống Maritime AI.

Phân tích query sau và trả về JSON:

Query: {query}

Trả về JSON với format:
{{
    "complexity": "simple" | "moderate" | "complex",
    "requires_multi_step": true/false,
    "requires_verification": true/false,
    "is_maritime_related": true/false,
    "detected_topics": ["topic1", "topic2"],
    "sub_queries": ["sub_query1", "sub_query2"] (nếu complex),
    "confidence": 0.0-1.0
}}

Hướng dẫn:
- SIMPLE: Câu hỏi trực tiếp, tra cứu đơn (VD: "Rule 15 là gì?")
- MODERATE: Cần so sánh hoặc context (VD: "So sánh Rule 15 và Rule 17")
- COMPLEX: Cần tổng hợp nhiều nguồn (VD: "Phân tích tất cả quy tắc nhường đường")

CHỈ TRẢ VỀ JSON, KHÔNG CÓ TEXT KHÁC."""


class QueryAnalyzer:
    """
    Analyzes query complexity for Agentic RAG.
    
    Usage:
        analyzer = QueryAnalyzer()
        analysis = await analyzer.analyze("What is Rule 15?")
        if analysis.complexity == QueryComplexity.COMPLEX:
            # Use multi-step retrieval
    """
    
    def __init__(self):
        """Initialize with Gemini LLM."""
        self._llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize Gemini LLM for analysis."""
        try:
            self._llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=settings.google_api_key,
                temperature=0.1,  # Low temperature for consistent analysis
                max_output_tokens=500
            )
            logger.info("QueryAnalyzer initialized with Gemini")
        except Exception as e:
            logger.error(f"Failed to initialize QueryAnalyzer LLM: {e}")
            self._llm = None
    
    async def analyze(self, query: str) -> QueryAnalysis:
        """
        Analyze query complexity.
        
        Args:
            query: User query to analyze
            
        Returns:
            QueryAnalysis with complexity and recommendations
        """
        if not self._llm:
            # Fallback to rule-based analysis
            return self._rule_based_analysis(query)
        
        try:
            # Use LLM for analysis
            messages = [
                SystemMessage(content="You are a query analyzer. Return only valid JSON."),
                HumanMessage(content=ANALYSIS_PROMPT.format(query=query))
            ]
            
            response = await self._llm.ainvoke(messages)
            content = response.content.strip()
            
            # Parse JSON response
            import json
            
            # Clean up response (remove markdown if present)
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            
            data = json.loads(content)
            
            return QueryAnalysis(
                original_query=query,
                complexity=QueryComplexity(data.get("complexity", "moderate")),
                requires_multi_step=data.get("requires_multi_step", False),
                requires_verification=data.get("requires_verification", False),
                is_maritime_related=data.get("is_maritime_related", True),
                suggested_sub_queries=data.get("sub_queries", []),
                detected_topics=data.get("detected_topics", []),
                confidence=data.get("confidence", 0.8)
            )
            
        except Exception as e:
            logger.warning(f"LLM analysis failed, using rule-based: {e}")
            return self._rule_based_analysis(query)
    
    def _rule_based_analysis(self, query: str) -> QueryAnalysis:
        """
        Fallback rule-based analysis.
        
        Uses keyword patterns to determine complexity.
        """
        query_lower = query.lower()
        
        # Detect topics
        topics = []
        maritime_keywords = {
            "colregs": "COLREGs",
            "solas": "SOLAS", 
            "marpol": "MARPOL",
            "rule": "Regulations",
            "điều": "Regulations",
            "tàu": "Ships",
            "thuyền": "Ships",
            "hàng hải": "Maritime"
        }
        
        for keyword, topic in maritime_keywords.items():
            if keyword in query_lower:
                topics.append(topic)
        
        is_maritime = len(topics) > 0
        
        # Determine complexity
        complex_indicators = ["so sánh", "compare", "phân tích", "analyze", 
                            "tất cả", "all", "liệt kê", "list", "tổng hợp"]
        moderate_indicators = ["tại sao", "why", "như thế nào", "how", 
                              "giải thích", "explain", "khác nhau", "difference"]
        
        complexity = QueryComplexity.SIMPLE
        requires_multi_step = False
        requires_verification = False
        
        for indicator in complex_indicators:
            if indicator in query_lower:
                complexity = QueryComplexity.COMPLEX
                requires_multi_step = True
                requires_verification = True
                break
        
        if complexity == QueryComplexity.SIMPLE:
            for indicator in moderate_indicators:
                if indicator in query_lower:
                    complexity = QueryComplexity.MODERATE
                    requires_verification = True
                    break
        
        return QueryAnalysis(
            original_query=query,
            complexity=complexity,
            requires_multi_step=requires_multi_step,
            requires_verification=requires_verification,
            is_maritime_related=is_maritime,
            detected_topics=topics,
            confidence=0.7  # Lower confidence for rule-based
        )
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_analyzer: Optional[QueryAnalyzer] = None

def get_query_analyzer() -> QueryAnalyzer:
    """Get or create QueryAnalyzer singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = QueryAnalyzer()
    return _analyzer
