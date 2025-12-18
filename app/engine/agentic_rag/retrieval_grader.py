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
        documents: List[Dict[str, Any]],
        query_embedding: Optional[List[float]] = None
    ) -> GradingResult:
        """
        Grade multiple documents.
        
        SOTA 2025 Phase 3: Tiered grading with embedding fast-pass.
        - Tier 1: Embedding similarity → Auto PASS/FAIL (skip LLM)
        - Tier 2: LLM grading → Only for uncertain docs
        
        Expected speedup: 70-75% reduction in grader latency.
        
        Args:
            query: User query
            documents: List of document dicts
            query_embedding: Pre-computed query embedding (optional, for tiered grading)
            
        Returns:
            GradingResult with all grades and summary
        """
        if not documents:
            return GradingResult(
                query=query,
                grades=[],
                feedback="No documents retrieved. Try different keywords."
            )
        
        # ====================================================================
        # PHASE 3.5: LLM MINI-JUDGE PRE-GRADING (SOTA 2025)
        # ====================================================================
        # Root Cause Fix: Bi-encoder similarity ≠ Relevance (65-80% accuracy)
        # Solution: LLM Mini-Judge for binary relevance (85-95% accuracy)
        # ====================================================================
        from app.engine.agentic_rag.mini_judge_grader import get_mini_judge_grader
        
        mini_judge = get_mini_judge_grader()
        
        # Pre-grade all documents with binary relevance (parallel)
        judge_results = await mini_judge.pre_grade_batch(query, documents)
        
        # Separate relevant vs needs-full-grading
        relevant_docs = []
        relevant_results = []
        uncertain_docs = []
        
        for doc, result in zip(documents, judge_results):
            if result.is_relevant and result.confidence in ("high", "medium"):
                # Already confirmed relevant by Mini-Judge
                relevant_docs.append(doc)
                relevant_results.append(result)
            else:
                # Not relevant or low confidence → needs full grading
                uncertain_docs.append(doc)
        
        # Build grades from Mini-Judge results
        grades = []
        
        # Add relevant docs with high score
        for doc, result in zip(relevant_docs, relevant_results):
            grades.append(DocumentGrade(
                document_id=result.document_id,
                content_preview=result.content_preview,
                score=8.5,  # High score for Mini-Judge approved
                is_relevant=True,
                reason=f"[Mini-Judge] {result.reason}"
            ))
        
        # Full LLM grading only for uncertain docs (limit to 5)
        if uncertain_docs:
            llm_grades = await self.batch_grade_documents(query, uncertain_docs[:5])
            grades.extend(llm_grades)
        
        logger.info(
            f"[GRADER] Mini-Judge: {len(documents)} docs → "
            f"Relevant={len(relevant_docs)}, LLM called on {min(len(uncertain_docs), 5)} "
            f"(saved {len(relevant_docs)} calls)"
        )
        
        result = GradingResult(query=query, grades=grades)
        
        # ====================================================================
        # SOTA FIX: Direct rule-based feedback (NO LLM call!)
        # ====================================================================
        # Root Cause: _generate_feedback() used MODERATE LLM (~19s latency)
        # SOTA Pattern: GradingResult already has avg_score + grades[].reason
        # Reference: LangChain CRAG, Meta CRAG Benchmark, OpenAI RAG 2025
        # ====================================================================
        if result.needs_rewrite:
            issues = [g.reason for g in grades if not g.is_relevant][:3]
            result.feedback = self._build_feedback_direct(
                result.avg_score, result.relevant_count, len(grades), issues
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
    
    def _build_feedback_direct(
        self,
        avg_score: float,
        relevant_count: int,
        total: int,
        issues: List[str]
    ) -> str:
        """
        SOTA: Zero-latency feedback generation using rule-based approach.
        
        Replaces LLM call (~19s) with direct string formatting (0ms).
        Reference: LangChain CRAG, Meta CRAG Benchmark, OpenAI RAG 2025
        
        Args:
            avg_score: Average relevance score (0-10)
            relevant_count: Number of relevant documents
            total: Total documents graded
            issues: List of reasons why documents weren't relevant
            
        Returns:
            Formatted feedback string for QueryRewriter
        """
        # Format issues - take top 3 unique issues
        unique_issues = list(dict.fromkeys(issues))[:3]
        issues_text = "; ".join(unique_issues) if unique_issues else "Documents không trực tiếp trả lời query"
        
        # Rule-based feedback based on score severity
        if avg_score < 3.0:
            severity = "Rất thấp"
            suggestion = "Thử sử dụng thuật ngữ hàng hải chuẩn (SOLAS, COLREGs, MARPOL)"
        elif avg_score < 5.0:
            severity = "Thấp"
            suggestion = "Thêm từ khóa cụ thể hoặc diễn đạt lại câu hỏi"
        else:
            severity = "Trung bình"
            suggestion = "Cân nhắc thêm context hoặc phạm vi cụ thể hơn"
        
        return (
            f"Độ liên quan {severity} ({avg_score:.1f}/10, {relevant_count}/{total} docs). "
            f"Vấn đề: {issues_text[:200]}. "
            f"Gợi ý: {suggestion}"
        )
    
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
