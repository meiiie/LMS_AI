"""
HyDE (Hypothetical Document Embeddings) Service.

SOTA Dec 2025: Generates hypothetical documents to improve retrieval.
Bridges the query-document semantic gap for +20-30% accuracy on complex queries.

Reference: "Precise Zero-Shot Dense Retrieval without Relevance Labels" (Google, MIT)

**Feature: hyde-query-enhancement**
**Validates: Requirements 2.5**
"""

import logging
import re
from typing import List, Optional
from dataclasses import dataclass

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


# Maritime-specific HyDE prompt (Vietnamese)
HYDE_PROMPT_TEMPLATE = """Bạn là chuyên gia về luật hàng hải Việt Nam.

Hãy viết một đoạn văn ngắn (100-200 từ) trả lời câu hỏi sau.
Viết như thể đây là trích đoạn từ văn bản pháp luật hoặc tài liệu hàng hải chính thức.
Sử dụng thuật ngữ chuyên ngành và ngôn ngữ trang trọng.

Câu hỏi: {question}

Yêu cầu:
- Trả lời trực tiếp, không mở đầu bằng "Theo..."
- Sử dụng thuật ngữ chính xác (ví dụ: chủ tàu, thuyền viên, tàu biển)
- Nếu liên quan đến COLREG/SOLAS, đề cập các quy tắc cụ thể
- CHỈ trả về nội dung, không có giải thích thêm

Đoạn văn:"""


# English version for COLREG queries
HYDE_PROMPT_TEMPLATE_EN = """You are an expert in maritime law and COLREG regulations.

Write a short paragraph (100-200 words) answering the following question.
Write as if this is an excerpt from official maritime documentation or COLREG rules.
Use precise technical terminology.

Question: {question}

Requirements:
- Answer directly, formal language
- Use exact terms (vessel, give-way, stand-on, crossing situation)
- Reference specific Rule numbers if applicable
- ONLY return the content, no explanations

Paragraph:"""


@dataclass
class HyDEResult:
    """Result of HyDE query enhancement."""
    original_query: str
    hypothetical_document: str
    language: str
    success: bool
    error: Optional[str] = None


class HyDEService:
    """
    Hypothetical Document Embeddings for query enhancement.
    
    SOTA Dec 2025: Generate hypothetical answers to bridge semantic gap.
    
    Benefits:
    - +20-30% retrieval accuracy for vague/complex queries
    - Works particularly well for legal domain
    - Bridges vocabulary mismatch between query and documents
    
    **Feature: hyde-query-enhancement**
    """
    
    # Query patterns that benefit most from HyDE
    VAGUE_PATTERNS = [
        r'^(what|how|why|when|where|who|which)\s',  # WH-questions in English
        r'^(là gì|như thế nào|tại sao|khi nào|ở đâu|ai|cái gì)\b',  # Vietnamese
        r'^(giải thích|mô tả|định nghĩa|nêu)\s',  # Vietnamese explanation requests
        r'^(explain|describe|define|what is)\s',  # English explanation requests
    ]
    
    # Query patterns that should NOT use HyDE
    SPECIFIC_PATTERNS = [
        r'\b(rule|quy tắc|điều)\s*\d+\b',  # Specific rule numbers
        r'\b\d{2,}\b',  # Numeric queries
        r'^".*"$',  # Quoted exact phrase
    ]
    
    def __init__(self, llm: Optional[ChatGoogleGenerativeAI] = None):
        """
        Initialize HyDE Service.
        
        Args:
            llm: Optional LLM instance, will create if not provided
        """
        self._llm = llm
        self._available = True
        
        logger.info("HyDEService initialized")
    
    def _ensure_llm(self) -> ChatGoogleGenerativeAI:
        """Lazy initialize LLM when first needed."""
        if self._llm is None:
            # SOTA Pattern: Use centralized config, no hardcoded model names
            self._llm = ChatGoogleGenerativeAI(
                model=settings.google_model,  # Use config instead of hardcoded
                temperature=0.3,  # Low temp for consistent output
                google_api_key=settings.google_api_key,
            )
        return self._llm
    
    def _detect_language(self, text: str) -> str:
        """Detect if text is Vietnamese or English."""
        vietnamese_chars = 'ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ'
        has_vietnamese = any(char in text.lower() for char in vietnamese_chars)
        return 'vi' if has_vietnamese else 'en'
    
    def should_use_hyde(self, query: str) -> bool:
        """
        Determine if HyDE should be used for this query.
        
        Returns True for vague/complex queries, False for specific ones.
        """
        query_lower = query.lower().strip()
        
        # Skip HyDE for specific patterns (rule numbers, etc.)
        for pattern in self.SPECIFIC_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.debug(f"HyDE skipped: specific pattern detected in '{query}'")
                return False
        
        # Use HyDE for vague patterns
        for pattern in self.VAGUE_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.debug(f"HyDE recommended: vague pattern detected in '{query}'")
                return True
        
        # Default: use HyDE for longer queries (likely complex)
        if len(query.split()) >= 5:
            return True
        
        return False
    
    async def generate_hypothetical_document(
        self,
        question: str
    ) -> HyDEResult:
        """
        Generate a hypothetical document for the given question.
        
        Args:
            question: User's search query
            
        Returns:
            HyDEResult with hypothetical document
            
        **Feature: hyde-query-enhancement**
        """
        try:
            llm = self._ensure_llm()
            
            # Detect language and choose prompt
            language = self._detect_language(question)
            if language == 'vi':
                prompt = HYDE_PROMPT_TEMPLATE.format(question=question)
            else:
                prompt = HYDE_PROMPT_TEMPLATE_EN.format(question=question)
            
            # Generate hypothetical document
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            hypo_doc = text_content.strip()
            
            # Validate response
            if len(hypo_doc) < 50:
                logger.warning(f"HyDE generated short response: {len(hypo_doc)} chars")
            
            logger.info(f"HyDE generated {len(hypo_doc)} chars for: {question[:50]}...")
            
            return HyDEResult(
                original_query=question,
                hypothetical_document=hypo_doc,
                language=language,
                success=True
            )
            
        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}")
            return HyDEResult(
                original_query=question,
                hypothetical_document=question,  # Fallback to original
                language='unknown',
                success=False,
                error=str(e)
            )
    
    async def enhance_query(
        self,
        query: str,
        force: bool = False
    ) -> str:
        """
        Enhance query using HyDE if beneficial.
        
        Args:
            query: Original search query
            force: If True, always use HyDE regardless of pattern matching
            
        Returns:
            Enhanced query (hypothetical document) or original query
            
        **Feature: hyde-query-enhancement**
        """
        # Check if HyDE is beneficial for this query
        if not force and not self.should_use_hyde(query):
            logger.debug(f"HyDE not used for: {query}")
            return query
        
        # Generate hypothetical document
        result = await self.generate_hypothetical_document(query)
        
        if result.success:
            return result.hypothetical_document
        else:
            return query  # Fallback to original


# Singleton instance
_hyde_service: Optional[HyDEService] = None


def get_hyde_service() -> HyDEService:
    """Get or create singleton HyDEService instance."""
    global _hyde_service
    if _hyde_service is None:
        _hyde_service = HyDEService()
    return _hyde_service
