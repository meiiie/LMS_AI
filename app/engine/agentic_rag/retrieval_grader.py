"""
Retrieval Grader - Phase 7.2

Grades the relevance of retrieved documents to a query.

Features:
- LLM-based relevance scoring (0-10)
- Batch grading for multiple documents
- Feedback generation for query rewriting
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.engine.llm_pool import get_llm_moderate  # SOTA: Shared LLM Pool

logger = logging.getLogger(__name__)


@dataclass
class DocumentGrade:
    """Grade for a single document."""
    document_id: str
    content_preview: str
    score: float  # 0-10
    is_relevant: bool
    reason: str


@dataclass 
class GradingResult:
    """Result of grading multiple documents."""
    query: str
    grades: List[DocumentGrade] = field(default_factory=list)
    avg_score: float = 0.0
    relevant_count: int = 0
    feedback: str = ""
    
    def __post_init__(self):
        if self.grades:
            self.avg_score = sum(g.score for g in self.grades) / len(self.grades)
            self.relevant_count = sum(1 for g in self.grades if g.is_relevant)
    
    @property
    def needs_rewrite(self) -> bool:
        """Check if query needs rewriting based on grades."""
        return self.avg_score < 7.0 or self.relevant_count == 0


GRADING_PROMPT = """Bạn là Retrieval Grader cho hệ thống Maritime AI.

Đánh giá mức độ liên quan của document với query.

Query: {query}

Document:
{document}

Trả về JSON:
{{
    "score": 0-10,
    "is_relevant": true/false,
    "reason": "Lý do ngắn gọn"
}}

Hướng dẫn chấm điểm:
- 9-10: Trực tiếp trả lời hoàn toàn query
- 7-8: Liên quan mạnh, chứa thông tin chính
- 5-6: Liên quan một phần, cần bổ sung
- 3-4: Liên quan yếu, chỉ context chung
- 0-2: Không liên quan

CHỈ TRẢ VỀ JSON."""


FEEDBACK_PROMPT = """Dựa trên kết quả grading sau, đề xuất cách cải thiện query:

Query gốc: {query}

Kết quả:
- Điểm trung bình: {avg_score}/10
- Số documents liên quan: {relevant_count}/{total}
- Vấn đề chính: {issues}

Đề xuất query mới hoặc keywords bổ sung:"""


# SOTA 2025: Batch grading reduces 5 LLM calls → 1 LLM call
# Reference: LangChain llm.batch pattern, ROGRAG framework
BATCH_GRADING_PROMPT = """Bạn là Retrieval Grader cho hệ thống Maritime AI.

Đánh giá mức độ liên quan của TỪNG document với query dưới đây.

Query: {query}

Documents:
{documents}

Trả về JSON ARRAY (một mảng các object):
[
    {{"doc_index": 0, "score": 0-10, "is_relevant": true/false, "reason": "Lý do ngắn gọn"}},
    {{"doc_index": 1, "score": 0-10, "is_relevant": true/false, "reason": "Lý do ngắn gọn"}},
    ...
]

Hướng dẫn chấm điểm:
- 9-10: Trực tiếp trả lời hoàn toàn query
- 7-8: Liên quan mạnh, chứa thông tin chính
- 5-6: Liên quan một phần, cần bổ sung
- 3-4: Liên quan yếu, chỉ context chung
- 0-2: Không liên quan

CHỈ TRẢ VỀ JSON ARRAY, KHÔNG CÓ TEXT KHÁC."""


class RetrievalGrader:
    """
    Grades document relevance for Corrective RAG.
    
    Usage:
        grader = RetrievalGrader()
        result = await grader.grade_documents(query, documents)
        if result.needs_rewrite:
            # Trigger query rewriting
    """
    
    def __init__(self, threshold: float = 7.0):
        """
        Initialize grader.
        
        Args:
            threshold: Minimum score to consider document relevant
        """
        self._llm = None
        self._threshold = threshold
        self._init_llm()
    
    def _init_llm(self):
        """Initialize Gemini LLM from shared pool for grading."""
        try:
            # SOTA: Use shared LLM from pool (memory optimized)
            self._llm = get_llm_moderate()
            logger.info(f"RetrievalGrader initialized with shared MODERATE tier LLM")
        except Exception as e:
            logger.error(f"Failed to initialize RetrievalGrader LLM: {e}")
            self._llm = None
    
    async def grade_document(
        self, 
        query: str, 
        document: Dict[str, Any]
    ) -> DocumentGrade:
        """
        Grade a single document.
        
        Args:
            query: User query
            document: Document dict with 'content', 'id' keys
            
        Returns:
            DocumentGrade with score and relevance
        """
        doc_id = document.get("id", document.get("node_id", "unknown"))
        content = document.get("content", document.get("text", ""))[:1000]  # Limit
        
        if not self._llm:
            # Fallback: keyword matching
            return self._rule_based_grade(query, doc_id, content)
        
        try:
            messages = [
                SystemMessage(content="You are a document relevance grader. Return only valid JSON."),
                HumanMessage(content=GRADING_PROMPT.format(
                    query=query,
                    document=content
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            # When thinking_enabled=True, response.content may be list, not string
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            result = text_content.strip()
            
            # Parse JSON
            import json
            if result.startswith("```"):
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            result = result.strip()
            
            data = json.loads(result)
            
            score = float(data.get("score", 5.0))
            
            return DocumentGrade(
                document_id=doc_id,
                content_preview=content[:200],
                score=score,
                is_relevant=score >= self._threshold,
                reason=data.get("reason", "")
            )
            
        except Exception as e:
            logger.warning(f"LLM grading failed: {e}")
            return self._rule_based_grade(query, doc_id, content)
    
    async def grade_documents(
        self,
        query: str,
        documents: List[Dict[str, Any]]
    ) -> GradingResult:
        """
        Grade multiple documents.
        
        SOTA 2025: Uses batch grading (1 LLM call) instead of sequential (5 calls).
        Reduces grading time from ~40s to ~10s per phase.
        
        Args:
            query: User query
            documents: List of document dicts
            
        Returns:
            GradingResult with all grades and summary
        """
        if not documents:
            return GradingResult(
                query=query,
                grades=[],
                feedback="No documents retrieved. Try different keywords."
            )
        
        # SOTA: Use batch grading for efficiency
        grades = await self.batch_grade_documents(query, documents[:5])
        
        result = GradingResult(query=query, grades=grades)
        
        # Generate feedback if needed
        if result.needs_rewrite:
            issues = [g.reason for g in grades if not g.is_relevant]
            result.feedback = await self._generate_feedback(
                query, result.avg_score, result.relevant_count, 
                len(grades), issues
            )
        
        logger.info(f"[GRADER] Query='{query[:50]}...' avg_score={result.avg_score:.1f} relevant={result.relevant_count}/{len(grades)}")
        
        return result
    
    async def batch_grade_documents(
        self,
        query: str,
        documents: List[Dict[str, Any]]
    ) -> List[DocumentGrade]:
        """
        SOTA 2025: Batch grade multiple documents in single LLM call.
        
        Reduces 5 sequential calls → 1 batch call.
        Expected speedup: ~40s → ~10s per grading phase.
        
        Reference: LangChain llm.batch pattern, ROGRAG framework.
        """
        if not documents:
            return []
        
        # Fallback to rule-based if no LLM
        if not self._llm:
            return [
                self._rule_based_grade(
                    query, 
                    doc.get("id", doc.get("node_id", "unknown")), 
                    doc.get("content", doc.get("text", ""))[:1000]
                ) 
                for doc in documents
            ]
        
        # Format documents for batch prompt
        docs_text = "\n\n".join([
            f"[Document {i}]\nID: {doc.get('id', doc.get('node_id', 'unknown'))}\n{doc.get('content', doc.get('text', ''))[:800]}"
            for i, doc in enumerate(documents)
        ])
        
        try:
            messages = [
                SystemMessage(content="Grade document relevance. Return only valid JSON array."),
                HumanMessage(content=BATCH_GRADING_PROMPT.format(
                    query=query,
                    documents=docs_text
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            grades = self._parse_batch_response(response.content, documents)
            
            logger.info(f"[GRADER] Batch graded {len(grades)} docs in 1 LLM call (SOTA)")
            return grades
            
        except Exception as e:
            logger.warning(f"Batch grading failed: {e}, falling back to sequential")
            return await self._sequential_grade_documents(query, documents)
    
    async def _sequential_grade_documents(
        self,
        query: str,
        documents: List[Dict[str, Any]]
    ) -> List[DocumentGrade]:
        """Fallback: Sequential grading when batch fails."""
        grades = []
        for doc in documents:
            grade = await self.grade_document(query, doc)
            grades.append(grade)
        return grades
    
    def _parse_batch_response(
        self,
        response: str,
        documents: List[Dict[str, Any]]
    ) -> List[DocumentGrade]:
        """Parse batch grading JSON response."""
        import json
        
        # SOTA FIX: Handle Gemini 2.5 Flash content block format
        # When thinking_enabled=True, response may be list, not string
        from app.services.output_processor import extract_thinking_from_response
        text_content, _ = extract_thinking_from_response(response)
        result = text_content.strip()
        
        # Clean markdown code blocks if present
        if result.startswith("```"):
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
        result = result.strip()
        
        try:
            data = json.loads(result)
            
            grades = []
            for item in data:
                doc_idx = item.get("doc_index", 0)
                if doc_idx < len(documents):
                    doc = documents[doc_idx]
                    doc_id = doc.get("id", doc.get("node_id", f"doc_{doc_idx}"))
                    content = doc.get("content", doc.get("text", ""))[:200]
                    
                    score = float(item.get("score", 5.0))
                    
                    grades.append(DocumentGrade(
                        document_id=doc_id,
                        content_preview=content,
                        score=score,
                        is_relevant=score >= self._threshold,
                        reason=item.get("reason", "Batch graded")
                    ))
            
            return grades
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse batch response: {e}")
            # Fallback to rule-based
            return [
                self._rule_based_grade(
                    "", 
                    doc.get("id", doc.get("node_id", "unknown")), 
                    doc.get("content", doc.get("text", ""))[:1000]
                ) 
                for doc in documents
            ]
    
    async def _generate_feedback(
        self,
        query: str,
        avg_score: float,
        relevant_count: int,
        total: int,
        issues: List[str]
    ) -> str:
        """Generate feedback for query rewriting."""
        if not self._llm:
            return f"Low relevance ({avg_score:.1f}/10). Try more specific keywords."
        
        try:
            messages = [
                HumanMessage(content=FEEDBACK_PROMPT.format(
                    query=query,
                    avg_score=f"{avg_score:.1f}",
                    relevant_count=relevant_count,
                    total=total,
                    issues="; ".join(issues[:3]) if issues else "Documents không trực tiếp trả lời query"
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            return text_content.strip()
            
        except Exception as e:
            logger.warning(f"Feedback generation failed: {e}")
            return f"Low relevance ({avg_score:.1f}/10). Try more specific keywords."
    
    def _rule_based_grade(
        self, 
        query: str, 
        doc_id: str, 
        content: str
    ) -> DocumentGrade:
        """Fallback rule-based grading using keyword overlap."""
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())
        
        overlap = query_words.intersection(content_words)
        overlap_ratio = len(overlap) / max(len(query_words), 1)
        
        # Convert ratio to score (0-10)
        score = min(10.0, overlap_ratio * 15)  # Generous scoring
        
        return DocumentGrade(
            document_id=doc_id,
            content_preview=content[:200],
            score=score,
            is_relevant=score >= self._threshold,
            reason=f"Keyword overlap: {len(overlap)} words"
        )
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_grader: Optional[RetrievalGrader] = None

def get_retrieval_grader() -> RetrievalGrader:
    """Get or create RetrievalGrader singleton."""
    global _grader
    if _grader is None:
        _grader = RetrievalGrader()
    return _grader
