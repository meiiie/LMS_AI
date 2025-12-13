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
        
        Args:
            rag_agent: RAG agent for retrieval and generation
            max_iterations: Maximum rewrite iterations
            grade_threshold: Minimum grade to accept retrieval
            enable_verification: Whether to verify answers
        """
        self._rag = rag_agent
        self._max_iterations = max_iterations
        self._grade_threshold = grade_threshold
        self._enable_verification = enable_verification
        
        # Initialize components
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
        """
        context = context or {}
        
        # Step 1: Analyze query
        logger.info(f"[CRAG] Step 1: Analyzing query: '{query[:50]}...'")
        analysis = await self._analyzer.analyze(query)
        logger.info(f"[CRAG] Analysis: {analysis}")
        
        # Step 2: Initial retrieval
        current_query = query
        documents = []
        grading_result = None
        was_rewritten = False
        rewritten_query = None
        iterations = 0
        
        for iteration in range(self._max_iterations):
            iterations = iteration + 1
            logger.info(f"[CRAG] Step 2.{iterations}: Retrieving for '{current_query[:50]}...'")
            
            # Retrieve documents
            documents = await self._retrieve(current_query, context)
            
            if not documents:
                logger.warning(f"[CRAG] No documents retrieved")
                if iteration < self._max_iterations - 1:
                    # Try rewriting
                    current_query = await self._rewriter.rewrite(
                        current_query, 
                        "No documents found"
                    )
                    rewritten_query = current_query
                    was_rewritten = True
                    continue
                break
            
            # Step 3: Grade documents
            logger.info(f"[CRAG] Step 3.{iterations}: Grading {len(documents)} documents")
            grading_result = await self._grader.grade_documents(current_query, documents)
            
            # Check if good enough
            if grading_result.avg_score >= self._grade_threshold:
                logger.info(f"[CRAG] Grade passed: {grading_result.avg_score:.1f}")
                break
            
            # Step 4: Rewrite if needed
            if iteration < self._max_iterations - 1:
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
        
        # Step 5: Generate answer
        logger.info(f"[CRAG] Step 5: Generating answer")
        answer, sources = await self._generate(query, documents, context)
        
        # Step 6: Verify (optional)
        verification_result = None
        if self._enable_verification and analysis.requires_verification:
            logger.info(f"[CRAG] Step 6: Verifying answer")
            verification_result = await self._verifier.verify(answer, sources)
            
            if verification_result.warning:
                answer = f"⚠️ {verification_result.warning}\n\n{answer}"
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(
            analysis, grading_result, verification_result
        )
        
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
            confidence=confidence
        )
    
    async def _retrieve(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Retrieve documents using RAG agent."""
        if not self._rag:
            logger.warning("[CRAG] No RAG agent configured")
            return []
        
        try:
            # Call RAG agent's retrieval
            if hasattr(self._rag, 'retrieve'):
                return await self._rag.retrieve(query)
            elif hasattr(self._rag, 'search'):
                return await self._rag.search(query)
            else:
                # Fallback: use the whole agent
                result = await self._rag.process(query, context)
                return result.get("sources", [])
        except Exception as e:
            logger.error(f"[CRAG] Retrieval failed: {e}")
            return []
    
    async def _generate(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Generate answer using RAG agent."""
        if not self._rag:
            return "Không thể tạo câu trả lời do thiếu cấu hình.", documents
        
        try:
            # Call RAG agent's generation
            if hasattr(self._rag, 'generate'):
                answer = await self._rag.generate(query, documents)
                return answer, documents
            else:
                # Use full process
                result = await self._rag.process(query, context)
                return result.get("content", ""), result.get("sources", documents)
        except Exception as e:
            logger.error(f"[CRAG] Generation failed: {e}")
            return f"Lỗi khi tạo câu trả lời: {e}", documents
    
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
