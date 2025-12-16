"""
Corrective RAG - Phase 7.5

Main orchestrator for Agentic RAG with self-correction.

Flow:
1. Analyze query complexity
2. Retrieve documents
3. Grade relevance
4. Rewrite query if needed (self-correction)
5. Generate answer
6. Verify answer (hallucination check)

Features:
- Multi-step retrieval for complex queries
- Self-correction loop
- Hallucination prevention
- Confidence scoring
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

from app.engine.agentic_rag.query_analyzer import (
    QueryAnalyzer, QueryAnalysis, QueryComplexity, get_query_analyzer
)
from app.engine.agentic_rag.retrieval_grader import (
    RetrievalGrader, GradingResult, get_retrieval_grader
)
from app.engine.agentic_rag.query_rewriter import (
    QueryRewriter, get_query_rewriter
)
from app.engine.agentic_rag.answer_verifier import (
    AnswerVerifier, VerificationResult, get_answer_verifier
)
from app.engine.reasoning_tracer import (
    ReasoningTracer, StepNames, get_reasoning_tracer
)
# CHỈ THỊ SỐ 29 v2: SOTA Native-First Thinking (no ThinkingGenerator needed)
# Pattern: Use Gemini's native thinking directly (aligns with Claude/Qwen/Gemini 2025)
from app.models.schemas import ReasoningTrace

logger = logging.getLogger(__name__)


@dataclass
class CorrectiveRAGResult:
    """Result from Corrective RAG processing."""
    answer: str
    sources: List[Dict[str, Any]]
    query_analysis: Optional[QueryAnalysis] = None
    grading_result: Optional[GradingResult] = None
    verification_result: Optional[VerificationResult] = None
    was_rewritten: bool = False
    rewritten_query: Optional[str] = None
    iterations: int = 1
    confidence: float = 0.8
    reasoning_trace: Optional[ReasoningTrace] = None  # Feature: reasoning-trace
    thinking_content: Optional[str] = None  # Legacy: structured summary (fallback)
    thinking: Optional[str] = None  # CHỈ THỊ SỐ 29: Natural Vietnamese thinking
    
    @property
    def has_warning(self) -> bool:
        """Check if result needs a warning."""
        if self.verification_result:
            return self.verification_result.needs_warning
        return self.confidence < 70


class CorrectiveRAG:
    """
    Corrective RAG with self-correction loop.
    
    Usage:
        crag = CorrectiveRAG(rag_agent)
        result = await crag.process("What is Rule 15?", context)
        if result.has_warning:
            print(f"Warning: {result.verification_result.warning}")
    """
    
    def __init__(
        self,
        rag_agent=None,
        max_iterations: int = 2,
        grade_threshold: float = 7.0,
        enable_verification: bool = True
    ):
        """
        Initialize Corrective RAG.
        
        SOTA Pattern: Composition Pattern
        - If rag_agent is provided, use it (backward compatibility)
        - If not, auto-compose internal RAGAgent (self-contained node)
        
        This follows LangGraph CRAG architecture where nodes are self-contained
        and compose their own dependencies rather than relying on DI.
        
        Args:
            rag_agent: (Deprecated) External RAG agent. If None, auto-creates one.
            max_iterations: Maximum rewrite iterations
            grade_threshold: Minimum grade to accept retrieval (1-10 scale)
            enable_verification: Whether to verify answers against sources
        """
        self._max_iterations = max_iterations
        self._grade_threshold = grade_threshold
        self._enable_verification = enable_verification
        
        # ================================================================
        # COMPOSITION PATTERN: Self-contained RAG capability
        # ================================================================
        if rag_agent is not None:
            # Backward compatibility: Use provided rag_agent
            self._rag = rag_agent
            logger.info("[CRAG] Using provided RAG agent (legacy mode)")
        else:
            # SOTA: Auto-compose internal RAGAgent
            try:
                from app.engine.agentic_rag.rag_agent import RAGAgent
                self._rag = RAGAgent()  # RAGAgent auto-inits HybridSearchService
                logger.info("[CRAG] Auto-composed internal RAGAgent")
            except Exception as e:
                logger.error(f"[CRAG] Failed to auto-compose RAGAgent: {e}")
                self._rag = None
        
        # ================================================================
        # CRAG COMPONENTS (Query Analysis, Grading, Rewriting, Verification)
        # ================================================================
        self._analyzer = get_query_analyzer()
        self._grader = get_retrieval_grader()
        self._rewriter = get_query_rewriter()
        self._verifier = get_answer_verifier()
        
        logger.info(f"CorrectiveRAG initialized (max_iter={max_iterations}, threshold={grade_threshold})")
    
    async def process(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CorrectiveRAGResult:
        """
        Process query through Corrective RAG pipeline.
        
        Args:
            query: User query
            context: Additional context (user_id, session_id, etc.)
            
        Returns:
            CorrectiveRAGResult with answer and metadata
        
        **Feature: reasoning-trace**
        """
        context = context or {}
        
        # Initialize reasoning tracer (Feature: reasoning-trace)
        tracer = get_reasoning_tracer()
        
        # Step 1: Analyze query
        tracer.start_step(StepNames.QUERY_ANALYSIS, "Phân tích độ phức tạp câu hỏi")
        logger.info(f"[CRAG] Step 1: Analyzing query: '{query[:50]}...'")
        analysis = await self._analyzer.analyze(query)
        logger.info(f"[CRAG] Analysis: {analysis}")
        tracer.end_step(
            result=f"Độ phức tạp: {analysis.complexity.value}, Maritime: {analysis.is_maritime_related}",
            confidence=analysis.confidence,
            details={"complexity": analysis.complexity.value, "is_maritime": analysis.is_maritime_related, "topics": analysis.detected_topics}
        )
        
        # Step 2: Initial retrieval
        current_query = query
        documents = []
        grading_result = None
        was_rewritten = False
        rewritten_query = None
        iterations = 0
        
        for iteration in range(self._max_iterations):
            iterations = iteration + 1
            
            # Retrieval step
            tracer.start_step(StepNames.RETRIEVAL, f"Tìm kiếm tài liệu (lần {iterations})")
            logger.info(f"[CRAG] Step 2.{iterations}: Retrieving for '{current_query[:50]}...'")
            
            # Retrieve documents
            documents = await self._retrieve(current_query, context)
            
            if not documents:
                logger.warning(f"[CRAG] No documents retrieved")
                tracer.end_step(result="Không tìm thấy tài liệu", confidence=0.0)
                
                if iteration < self._max_iterations - 1:
                    # Try rewriting
                    tracer.start_step(StepNames.QUERY_REWRITE, "Viết lại query do không có kết quả")
                    current_query = await self._rewriter.rewrite(
                        current_query, 
                        "No documents found"
                    )
                    rewritten_query = current_query
                    was_rewritten = True
                    tracer.end_step(result=f"Query mới: {current_query[:50]}...", confidence=0.7)
                    tracer.record_correction("Không tìm thấy tài liệu")
                    continue
                break
            else:
                tracer.end_step(
                    result=f"Tìm thấy {len(documents)} tài liệu",
                    confidence=0.8,
                    details={"doc_count": len(documents)}
                )
            
            # Step 3: Grade documents
            tracer.start_step(StepNames.GRADING, "Đánh giá độ liên quan của tài liệu")
            logger.info(f"[CRAG] Step 3.{iterations}: Grading {len(documents)} documents")
            grading_result = await self._grader.grade_documents(current_query, documents)
            
            # Check if good enough
            if grading_result.avg_score >= self._grade_threshold:
                logger.info(f"[CRAG] Grade passed: {grading_result.avg_score:.1f}")
                tracer.end_step(
                    result=f"Điểm: {grading_result.avg_score:.1f}/10 - ĐẠT",
                    confidence=grading_result.avg_score / 10,
                    details={"score": grading_result.avg_score, "passed": True}
                )
                break
            else:
                tracer.end_step(
                    result=f"Điểm: {grading_result.avg_score:.1f}/10 - Cần cải thiện",
                    confidence=grading_result.avg_score / 10,
                    details={"score": grading_result.avg_score, "passed": False}
                )
            
            # Step 4: Rewrite if needed
            if iteration < self._max_iterations - 1:
                tracer.start_step(StepNames.QUERY_REWRITE, "Viết lại query để cải thiện kết quả")
                logger.info(f"[CRAG] Step 4.{iterations}: Rewriting query (score={grading_result.avg_score:.1f})")
                
                if analysis.complexity == QueryComplexity.COMPLEX:
                    # Decompose complex queries
                    sub_queries = await self._rewriter.decompose(current_query)
                    if len(sub_queries) > 1:
                        # Use first sub-query
                        current_query = sub_queries[0]
                else:
                    current_query = await self._rewriter.rewrite(
                        current_query,
                        grading_result.feedback
                    )
                
                rewritten_query = current_query
                was_rewritten = True
                tracer.end_step(
                    result=f"Query mới: {current_query[:50]}...",
                    confidence=0.8
                )
                tracer.record_correction(f"Điểm liên quan thấp ({grading_result.avg_score:.1f}/10)")
        
        # Step 5: Generate answer
        tracer.start_step(StepNames.GENERATION, "Tạo câu trả lời từ context")
        logger.info(f"[CRAG] Step 5: Generating answer")
        # CHỈ THỊ SỐ 29: Unpack native_thinking from _generate()
        answer, sources, native_thinking = await self._generate(query, documents, context)
        tracer.end_step(
            result=f"Tạo câu trả lời dựa trên {len(sources)} nguồn",
            confidence=0.85,
            details={"source_count": len(sources)}
        )
        
        # Step 6: Verify (optional)
        verification_result = None
        if self._enable_verification and analysis.requires_verification:
            tracer.start_step(StepNames.VERIFICATION, "Kiểm tra độ chính xác và hallucination")
            logger.info(f"[CRAG] Step 6: Verifying answer")
            verification_result = await self._verifier.verify(answer, sources)
            
            if verification_result.warning:
                answer = f"⚠️ {verification_result.warning}\n\n{answer}"
                tracer.end_step(
                    result=f"Cảnh báo: {verification_result.warning}",
                    confidence=verification_result.confidence / 100 if verification_result.confidence else 0.5
                )
            else:
                tracer.end_step(
                    result="Đã xác minh - Không phát hiện vấn đề",
                    confidence=verification_result.confidence / 100 if verification_result.confidence else 0.9
                )
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(
            analysis, grading_result, verification_result
        )
        
        # Build reasoning trace
        reasoning_trace = tracer.build_trace(final_confidence=confidence / 100)
        
        # CHỈ THỊ SỐ 29 v2: SOTA Native-First Thinking
        # SOTA Pattern (2025): Use native model thinking directly
        # - Claude: Extended Thinking blocks
        # - Qwen QwQ: <think> blocks  
        # - Gemini 2.5: include_thoughts=True
        # No dual LLM call needed - Gemini already provides thinking
        thinking = None
        thinking_content = None
        
        # Priority 1: Native Gemini thinking (SOTA - zero extra latency)
        if native_thinking:
            thinking = native_thinking
            logger.info(f"[CRAG] Using native Gemini thinking: {len(thinking)} chars")
        
        # Priority 2: Structured summary (fallback when native unavailable)
        thinking_content = tracer.build_thinking_summary()
        if thinking_content:
            logger.info(f"[CRAG] Built structured thinking summary: {len(thinking_content)} chars")
        
        # Fallback: if no native thinking, use structured
        if not thinking:
            thinking = thinking_content
            logger.info("[CRAG] Native thinking unavailable, using structured summary")
        
        logger.info(f"[CRAG] Complete: iterations={iterations}, confidence={confidence:.0f}%")
        
        return CorrectiveRAGResult(
            answer=answer,
            sources=sources,
            query_analysis=analysis,
            grading_result=grading_result,
            verification_result=verification_result,
            was_rewritten=was_rewritten,
            rewritten_query=rewritten_query,
            iterations=iterations,
            confidence=confidence,
            reasoning_trace=reasoning_trace,
            thinking_content=thinking_content,  # Structured summary (legacy)
            thinking=thinking  # CHỈ THỊ SỐ 29: Natural thinking
        )
    
    async def _retrieve(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Retrieve documents for grading using HybridSearchService directly.
        
        SOTA Pattern (2024-2025): CRAG grading requires FULL document content.
        
        Previous implementation used RAGAgent.query() → Citation → lost content.
        Now uses HybridSearchService.search() → HybridSearchResult → full content.
        
        Reference: LangChain CRAG grading requires knowledge strips (full chunks).
        """
        if not self._rag:
            logger.warning("[CRAG] No RAG agent available")
            return []
        
        try:
            # ================================================================
            # SOTA FIX: Use HybridSearchService directly for full content
            # ================================================================
            # Access HybridSearchService from RAGAgent
            hybrid_search = getattr(self._rag, '_hybrid_search', None)
            
            if hybrid_search and hybrid_search.is_available():
                # Direct hybrid search - returns HybridSearchResult with content
                results = await hybrid_search.search(
                    query=query,
                    limit=10
                )
                
                # Convert to grading format WITH full content
                documents = []
                for r in results:
                    doc = {
                        "node_id": r.node_id,
                        "content": r.content,  # ✅ FULL CONTENT for grading!
                        "title": r.title,
                        "score": r.rrf_score,
                        # Source highlighting fields
                        "image_url": r.image_url,
                        "page_number": r.page_number if hasattr(r, 'page_number') else None,
                        "document_id": r.document_id if hasattr(r, 'document_id') else None,
                        "bounding_boxes": r.bounding_boxes if hasattr(r, 'bounding_boxes') else None,
                    }
                    documents.append(doc)
                
                logger.info(f"[CRAG] Retrieved {len(documents)} documents via HybridSearchService (SOTA)")
                return documents
            
            # Fallback: Use RAGAgent.query() if HybridSearch unavailable
            logger.warning("[CRAG] HybridSearch unavailable, falling back to RAGAgent")
            user_role = context.get("user_role", "student")
            history = context.get("conversation_history", "")
            
            response = await self._rag.query(
                question=query,
                limit=10,
                conversation_history=history,
                user_role=user_role
            )
            
            # Convert RAGResponse.citations - use title as content (best effort)
            documents = []
            for citation in response.citations:
                doc = {
                    "node_id": getattr(citation, 'node_id', ''),
                    "content": getattr(citation, 'title', ''),  # Use title (has actual text)
                    "title": getattr(citation, 'title', 'Unknown'),
                    "score": getattr(citation, 'relevance_score', 0),
                    "image_url": getattr(citation, 'image_url', None),
                    "page_number": getattr(citation, 'page_number', None),
                    "document_id": getattr(citation, 'document_id', None),
                    "bounding_boxes": getattr(citation, 'bounding_boxes', None),
                }
                documents.append(doc)
            
            logger.info(f"[CRAG] Retrieved {len(documents)} documents via RAGAgent (fallback)")
            return documents
            
        except Exception as e:
            logger.error(f"[CRAG] RAGAgent retrieval failed: {e}")
            return []

    
    async def _generate(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
        """
        Generate answer from graded documents using RAGAgent.
        
        Since documents have been retrieved and graded, we use the content
        to generate a synthesized answer.
        
        CHỈ THỊ SỐ 29: Now returns native_thinking from Gemini for hybrid display.
        
        Returns:
            Tuple of (answer, documents, native_thinking)
        """
        if not self._rag:
            return "Không thể tạo câu trả lời do thiếu cấu hình.", documents, None
        
        if not documents:
            return "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu.", [], None
        
        try:
            # Re-query with the original question to get LLM-generated answer
            # The documents are already retrieved and graded
            user_role = context.get("user_role", "student")
            history = context.get("conversation_history", "")
            
            response = await self._rag.query(
                question=query,
                limit=10,
                conversation_history=history,
                user_role=user_role
            )
            
            # CHỈ THỊ SỐ 29: Capture native_thinking from RAGResponse
            native_thinking = response.native_thinking
            if native_thinking:
                logger.info(f"[CRAG] Native thinking from Gemini: {len(native_thinking)} chars")
            
            return response.content, documents, native_thinking
            
        except Exception as e:
            logger.error(f"[CRAG] Generation failed: {e}")
            return f"Lỗi khi tạo câu trả lời: {e}", documents, None
    
    def _calculate_confidence(
        self,
        analysis: Optional[QueryAnalysis],
        grading: Optional[GradingResult],
        verification: Optional[VerificationResult]
    ) -> float:
        """Calculate overall confidence score."""
        scores = []
        
        if analysis:
            scores.append(analysis.confidence * 100)
        
        if grading:
            scores.append(grading.avg_score * 10)  # Scale to 0-100
        
        if verification:
            scores.append(verification.confidence)
        
        if not scores:
            return 70.0  # Default
        
        return sum(scores) / len(scores)
    
    def is_available(self) -> bool:
        """Check if all components are available."""
        return (
            self._analyzer.is_available() and
            self._grader.is_available()
        )


# Singleton
_corrective_rag: Optional[CorrectiveRAG] = None

def get_corrective_rag(rag_agent=None) -> CorrectiveRAG:
    """Get or create CorrectiveRAG singleton."""
    global _corrective_rag
    if _corrective_rag is None:
        _corrective_rag = CorrectiveRAG(rag_agent=rag_agent)
    return _corrective_rag
