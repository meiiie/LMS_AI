"""
Query Rewriter - Phase 7.3

Rewrites queries when initial retrieval results are poor.

Features:
- Query expansion with synonyms
- Query decomposition for complex questions
- Feedback-based rewriting
"""

import logging
from typing import List, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.engine.llm_pool import get_llm_light  # SOTA: Shared LLM Pool

logger = logging.getLogger(__name__)


REWRITE_PROMPT = """Bạn là Query Rewriter cho hệ thống Maritime AI.

Query gốc không tìm được kết quả tốt. Hãy viết lại query để tìm kiếm hiệu quả hơn.

Query gốc: {query}
Feedback: {feedback}

Yêu cầu:
1. Giữ nguyên ý nghĩa câu hỏi
2. Thêm từ khóa liên quan (maritime, COLREGs, SOLAS, etc.)
3. Sử dụng thuật ngữ chuẩn tiếng Anh nếu phù hợp
4. Đơn giản hóa nếu quá phức tạp

Chỉ trả về query mới, không giải thích."""


EXPAND_PROMPT = """Mở rộng query với các từ đồng nghĩa và thuật ngữ liên quan:

Query: {query}

Trả về query mở rộng với các variations:"""


DECOMPOSE_PROMPT = """Query này quá phức tạp. Hãy chia thành các sub-queries nhỏ hơn:

Query: {query}

Trả về danh sách sub-queries (mỗi dòng một query):"""


class QueryRewriter:
    """
    Rewrites queries for better retrieval.
    
    Usage:
        rewriter = QueryRewriter()
        new_query = await rewriter.rewrite(query, feedback)
    """
    
    def __init__(self):
        """Initialize with Gemini LLM."""
        self._llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize Gemini LLM from shared pool."""
        try:
            # SOTA: Use shared LLM from pool (memory optimized)
            self._llm = get_llm_light()
            logger.info(f"QueryRewriter initialized with shared LIGHT tier LLM")
        except Exception as e:
            logger.error(f"Failed to initialize QueryRewriter LLM: {e}")
            self._llm = None
    
    async def rewrite(self, query: str, feedback: str = "") -> str:
        """
        Rewrite query based on feedback.
        
        Args:
            query: Original query
            feedback: Feedback from grading (why it failed)
            
        Returns:
            Rewritten query
        """
        if not self._llm:
            return self._rule_based_rewrite(query)
        
        try:
            messages = [
                SystemMessage(content="You are a query optimizer. Return only the improved query."),
                HumanMessage(content=REWRITE_PROMPT.format(
                    query=query,
                    feedback=feedback or "Documents retrieved were not relevant"
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            new_query = text_content.strip()
            
            # Clean up
            new_query = new_query.strip('"\'')
            
            logger.info(f"[REWRITER] '{query[:30]}...' → '{new_query[:30]}...'")
            return new_query
            
        except Exception as e:
            logger.warning(f"LLM rewrite failed: {e}")
            return self._rule_based_rewrite(query)
    
    async def expand(self, query: str) -> str:
        """
        Expand query with synonyms and related terms.
        
        Args:
            query: Original query
            
        Returns:
            Expanded query
        """
        if not self._llm:
            return self._add_maritime_keywords(query)
        
        try:
            messages = [
                HumanMessage(content=EXPAND_PROMPT.format(query=query))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            return text_content.strip()
            
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}")
            return self._add_maritime_keywords(query)
    
    async def decompose(self, query: str) -> List[str]:
        """
        Decompose complex query into sub-queries.
        
        Args:
            query: Complex query
            
        Returns:
            List of simpler sub-queries
        """
        if not self._llm:
            return [query]  # Can't decompose without LLM
        
        try:
            messages = [
                HumanMessage(content=DECOMPOSE_PROMPT.format(query=query))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            lines = text_content.strip().split("\n")
            
            # Clean up
            sub_queries = []
            for line in lines:
                line = line.strip()
                # Remove numbering
                if line and line[0].isdigit():
                    line = line.lstrip("0123456789.-) ")
                if line:
                    sub_queries.append(line)
            
            logger.info(f"[DECOMPOSE] '{query[:30]}...' → {len(sub_queries)} sub-queries")
            return sub_queries if sub_queries else [query]
            
        except Exception as e:
            logger.warning(f"Query decomposition failed: {e}")
            return [query]
    
    def _rule_based_rewrite(self, query: str) -> str:
        """Fallback rule-based rewriting."""
        # Add maritime context if missing
        query_lower = query.lower()
        
        if "maritime" not in query_lower and "hàng hải" not in query_lower:
            query = f"maritime {query}"
        
        # Translate common Vietnamese terms
        translations = {
            "điều": "rule",
            "quy tắc": "regulation",
            "tàu": "vessel ship",
            "nhường đường": "give-way"
        }
        
        for vn, en in translations.items():
            if vn in query_lower:
                query = f"{query} {en}"
                break
        
        return query
    
    def _add_maritime_keywords(self, query: str) -> str:
        """Add maritime keywords to query."""
        keywords = ["COLREGs", "maritime", "vessel", "navigation"]
        query_lower = query.lower()
        
        additions = []
        for kw in keywords:
            if kw.lower() not in query_lower:
                additions.append(kw)
                break  # Add only one
        
        if additions:
            return f"{query} {' '.join(additions)}"
        return query
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_rewriter: Optional[QueryRewriter] = None

def get_query_rewriter() -> QueryRewriter:
    """Get or create QueryRewriter singleton."""
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter
