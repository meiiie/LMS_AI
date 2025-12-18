"""
Tiered Grading - SOTA 2025 Phase 3 Optimization.

Fast-pass grading using embedding similarity before LLM grading.

Pattern References:
- Meta FAISS: Embedding similarity fast-pass
- Cohere Rerank: Tiered scoring
- Anthropic Constitutional AI: Confidence-based early exit

Expected Improvement:
- Before: 10 docs × LLM = 11-20s
- After: ~4 docs × LLM + fast-pass = 3-5s
- Reduction: 70-75%

Feature: semantic-cache-phase3
"""

import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

from app.engine.gemini_embedding import get_embeddings

logger = logging.getLogger(__name__)


@dataclass
class TieredGradeConfig:
    """Configuration for tiered grading thresholds."""
    
    # Tier 1: Fast-pass thresholds (skip LLM)
    high_similarity_threshold: float = 0.88  # Auto-PASS if >= this
    low_similarity_threshold: float = 0.65   # Auto-FAIL if < this
    
    # Enable/disable tiered grading
    enabled: bool = True
    
    # Minimum docs to keep even if low similarity
    min_docs_to_keep: int = 2


@dataclass
class TieredGradeResult:
    """Result of tiered grading classification."""
    document_id: str
    content_preview: str
    similarity: float
    tier: str  # "pass", "fail", or "uncertain"
    skip_llm: bool
    auto_score: Optional[float] = None


class TieredGrader:
    """
    SOTA 2025: Tiered grading with embedding similarity fast-pass.
    
    Classifies documents into 3 tiers based on embedding similarity:
    - PASS (sim >= 0.88): Auto-relevant, skip LLM
    - FAIL (sim < 0.65): Auto-irrelevant, skip LLM
    - UNCERTAIN (0.65-0.88): Needs LLM grading
    
    Expected speedup: 70-75% reduction in grader latency.
    
    Usage:
        tiered = TieredGrader()
        
        # Get query embedding (reuse from retrieval)
        query_embedding = embeddings.embed_query(query)
        
        # Pre-grade documents
        results = tiered.pre_grade(query_embedding, documents)
        
        # Only send uncertain docs to LLM
        uncertain_docs = [d for d, r in zip(documents, results) if not r.skip_llm]
        llm_grades = await grader.batch_grade_documents(query, uncertain_docs)
    """
    
    def __init__(self, config: Optional[TieredGradeConfig] = None):
        """Initialize tiered grader."""
        self._config = config or TieredGradeConfig()
        self._embeddings = None
        
        logger.info(
            f"[TieredGrader] Initialized with thresholds: "
            f"high={self._config.high_similarity_threshold:.2f}, "
            f"low={self._config.low_similarity_threshold:.2f}"
        )
    
    def _ensure_embeddings(self):
        """Lazily initialize embeddings."""
        if self._embeddings is None:
            self._embeddings = get_embeddings()
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        a = np.array(vec1)
        b = np.array(vec2)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
    
    def pre_grade(
        self,
        query_embedding: List[float],
        documents: List[Dict[str, Any]]
    ) -> List[TieredGradeResult]:
        """
        Pre-grade documents using embedding similarity.
        
        Args:
            query_embedding: Pre-computed query embedding
            documents: List of retrieved documents with 'embedding' field
            
        Returns:
            List of TieredGradeResult with classification
        """
        if not self._config.enabled:
            # If disabled, mark all as uncertain (needs LLM)
            return [
                TieredGradeResult(
                    document_id=doc.get("id", f"doc_{i}"),
                    content_preview=doc.get("content", "")[:100],
                    similarity=0.0,
                    tier="uncertain",
                    skip_llm=False
                )
                for i, doc in enumerate(documents)
            ]
        
        self._ensure_embeddings()
        results = []
        
        for i, doc in enumerate(documents):
            doc_id = doc.get("id", f"doc_{i}")
            content = doc.get("content", "")
            content_preview = content[:100]
            
            # Get document embedding
            doc_embedding = doc.get("embedding")
            
            if doc_embedding is None:
                # Generate embedding if not available
                try:
                    doc_embedding = self._embeddings.embed_query(content[:500])
                except Exception as e:
                    logger.warning(f"[TieredGrader] Failed to embed doc {doc_id}: {e}")
                    # Can't compute similarity, mark as uncertain
                    results.append(TieredGradeResult(
                        document_id=doc_id,
                        content_preview=content_preview,
                        similarity=0.0,
                        tier="uncertain",
                        skip_llm=False
                    ))
                    continue
            
            # Calculate similarity
            similarity = self._cosine_similarity(query_embedding, doc_embedding)
            
            # Classify into tiers
            if similarity >= self._config.high_similarity_threshold:
                tier = "pass"
                skip_llm = True
                auto_score = 9.0 + (similarity - 0.88) * 10  # 9.0-10.0
            elif similarity < self._config.low_similarity_threshold:
                tier = "fail"
                skip_llm = True
                auto_score = similarity * 10  # 0-6.5
            else:
                tier = "uncertain"
                skip_llm = False
                auto_score = None
            
            results.append(TieredGradeResult(
                document_id=doc_id,
                content_preview=content_preview,
                similarity=similarity,
                tier=tier,
                skip_llm=skip_llm,
                auto_score=auto_score
            ))
        
        # Log statistics
        pass_count = sum(1 for r in results if r.tier == "pass")
        fail_count = sum(1 for r in results if r.tier == "fail")
        uncertain_count = sum(1 for r in results if r.tier == "uncertain")
        
        logger.info(
            f"[TieredGrader] Pre-graded {len(results)} docs: "
            f"PASS={pass_count}, FAIL={fail_count}, UNCERTAIN={uncertain_count} "
            f"(LLM calls saved: {pass_count + fail_count})"
        )
        
        return results
    
    def merge_grades(
        self,
        tiered_results: List[TieredGradeResult],
        llm_grades: List["DocumentGrade"],
        documents: List[Dict[str, Any]]
    ) -> List["DocumentGrade"]:
        """
        Merge tiered pre-grades with LLM grades.
        
        Args:
            tiered_results: Results from pre_grade()
            llm_grades: LLM grades for uncertain docs only
            documents: Original document list
            
        Returns:
            Complete list of DocumentGrade for all docs
        """
        from app.engine.agentic_rag.retrieval_grader import DocumentGrade
        
        final_grades = []
        llm_grade_map = {g.document_id: g for g in llm_grades}
        
        for result in tiered_results:
            if result.skip_llm:
                # Use auto-grade
                final_grades.append(DocumentGrade(
                    document_id=result.document_id,
                    content_preview=result.content_preview,
                    score=result.auto_score or (9.0 if result.tier == "pass" else 3.0),
                    is_relevant=(result.tier == "pass"),
                    reason=f"[Fast-pass] Similarity={result.similarity:.3f} → {result.tier.upper()}"
                ))
            else:
                # Use LLM grade
                llm_grade = llm_grade_map.get(result.document_id)
                if llm_grade:
                    final_grades.append(llm_grade)
                else:
                    # Fallback if LLM grade missing
                    final_grades.append(DocumentGrade(
                        document_id=result.document_id,
                        content_preview=result.content_preview,
                        score=6.0,  # Middle score for uncertainty
                        is_relevant=False,
                        reason="[Fallback] LLM grade not available"
                    ))
        
        return final_grades


# Singleton
_tiered_grader: Optional[TieredGrader] = None


def get_tiered_grader(config: Optional[TieredGradeConfig] = None) -> TieredGrader:
    """Get or create TieredGrader singleton."""
    global _tiered_grader
    if _tiered_grader is None:
        _tiered_grader = TieredGrader(config)
    return _tiered_grader
