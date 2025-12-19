"""
Hybrid Confidence Evaluator - SOTA 2025 Self-Reflective RAG.

Fast confidence scoring WITHOUT LLM calls.

Pattern References:
- Anthropic Contextual Retrieval: BM25 + embeddings hybrid
- Self-RAG: Confidence-based iteration control
- Meta CRAG: Lightweight retrieval evaluator

Key Features:
- BM25 keyword matching (exact terms)
- Embedding cosine similarity (semantic)
- Domain-specific boosting (maritime terms)
- No LLM calls = ~0.1s vs 14s for LLM grading

Expected Improvement:
- Latency: 14s -> 0.1s per grading batch
- Accuracy: 80-85% (vs 65% pure embedding, 85-95% LLM)
- Cost: Zero tokens (vs 1000+ tokens per grading)

Feature: self-reflective-rag-phase2
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
import math

from app.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# MARITIME DOMAIN VOCABULARY (for boosting)
# =============================================================================
# High-value maritime terms that indicate relevance
MARITIME_CORE_TERMS = {
    # Regulations
    "colregs", "solas", "marpol", "stcw", "imdg", "imsbc", "isps",
    # Vietnamese articles
    "điều", "khoản", "mục", "chương", "phần",
    # Navigation
    "tàu", "thuyền", "boong", "mũi", "lái", "hải đồ", "la bàn",
    "tốc độ", "hải lý", "hướng", "phương vị",
    # Safety
    "an toàn", "cứu sinh", "cứu hỏa", "áo phao", "phao bè",
    # Technical
    "máy chính", "máy phụ", "buồng máy", "hầm hàng", "ballast",
    # Rule numbers
    "rule", "quy tắc", "regulation",
}

# Rule number pattern for Vietnamese maritime law
RULE_PATTERN = re.compile(r'điều\s*(\d+)', re.IGNORECASE)


@dataclass
class ConfidenceResult:
    """Result from hybrid confidence evaluation."""
    score: float  # 0.0 - 1.0 normalized confidence
    bm25_score: float
    embedding_score: float
    maritime_boost: float
    matched_terms: List[str]
    is_high_confidence: bool
    is_medium_confidence: bool
    evaluation_method: str = "hybrid"


@dataclass 
class HybridEvaluatorConfig:
    """Configuration for hybrid confidence evaluator."""
    
    # Weight distribution (must sum to 1.0)
    bm25_weight: float = 0.35
    embedding_weight: float = 0.45
    maritime_boost_weight: float = 0.20
    
    # BM25 parameters
    bm25_k1: float = 1.5  # Term frequency saturation
    bm25_b: float = 0.75  # Document length normalization
    
    # Enable/disable components
    use_bm25: bool = True
    use_embedding: bool = True
    use_maritime_boost: bool = True
    
    # Fallback if embedding unavailable
    fallback_to_bm25_only: bool = True


class HybridConfidenceEvaluator:
    """
    SOTA 2025: Fast confidence scoring without LLM calls.
    
    Combines:
    1. BM25 keyword matching (exact terms, rule numbers)
    2. Embedding cosine similarity (semantic matching)
    3. Maritime domain boosting (domain vocabulary)
    
    Usage:
        evaluator = HybridConfidenceEvaluator()
        
        # Evaluate single document
        result = evaluator.evaluate(query, doc_content, query_embedding, doc_embedding)
        
        # Batch evaluation with pre-computed embeddings
        results = evaluator.evaluate_batch(query, documents, query_embedding)
        
        # Get aggregate confidence for retrieval
        confidence = evaluator.aggregate_confidence(results)
    """
    
    def __init__(self, config: Optional[HybridEvaluatorConfig] = None):
        """Initialize hybrid confidence evaluator."""
        self._config = config or HybridEvaluatorConfig()
        
        # Validate weights
        total = self._config.bm25_weight + self._config.embedding_weight + self._config.maritime_boost_weight
        if abs(total - 1.0) > 0.01:
            logger.warning(f"[HybridEval] Weights don't sum to 1.0 ({total}), normalizing")
            self._config.bm25_weight /= total
            self._config.embedding_weight /= total
            self._config.maritime_boost_weight /= total
        
        logger.info(
            f"[HybridEval] Initialized with weights: "
            f"BM25={self._config.bm25_weight:.2f}, "
            f"Embedding={self._config.embedding_weight:.2f}, "
            f"Maritime={self._config.maritime_boost_weight:.2f}"
        )
    
    def evaluate(
        self,
        query: str,
        doc_content: str,
        query_embedding: Optional[List[float]] = None,
        doc_embedding: Optional[List[float]] = None
    ) -> ConfidenceResult:
        """
        Evaluate confidence for a single document.
        
        Args:
            query: User query string
            doc_content: Document content
            query_embedding: Pre-computed query embedding (optional)
            doc_embedding: Pre-computed document embedding (optional)
            
        Returns:
            ConfidenceResult with normalized confidence score
        """
        # Calculate individual scores
        bm25_score = 0.0
        embedding_score = 0.0
        maritime_boost = 0.0
        matched_terms = []
        
        # BM25 scoring
        if self._config.use_bm25:
            bm25_score, matched = self._calculate_bm25(query, doc_content)
            matched_terms.extend(matched)
        
        # Embedding cosine similarity
        if self._config.use_embedding and query_embedding and doc_embedding:
            embedding_score = self._calculate_cosine_similarity(query_embedding, doc_embedding)
        elif self._config.fallback_to_bm25_only:
            # Increase BM25 weight if no embeddings
            bm25_score *= 1.5
        
        # Maritime domain boosting
        if self._config.use_maritime_boost:
            maritime_boost, maritime_matched = self._calculate_maritime_boost(query, doc_content)
            matched_terms.extend(maritime_matched)
        
        # Weighted combination
        final_score = (
            self._config.bm25_weight * bm25_score +
            self._config.embedding_weight * embedding_score +
            self._config.maritime_boost_weight * maritime_boost
        )
        
        # Clamp to [0, 1]
        final_score = max(0.0, min(1.0, final_score))
        
        return ConfidenceResult(
            score=final_score,
            bm25_score=bm25_score,
            embedding_score=embedding_score,
            maritime_boost=maritime_boost,
            matched_terms=list(set(matched_terms)),
            is_high_confidence=final_score >= settings.rag_confidence_high,
            is_medium_confidence=final_score >= settings.rag_confidence_medium,
            evaluation_method="hybrid"
        )
    
    def evaluate_batch(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        query_embedding: Optional[List[float]] = None
    ) -> List[ConfidenceResult]:
        """
        Evaluate confidence for multiple documents.
        
        Args:
            query: User query string
            documents: List of document dicts with 'content' and optionally 'embedding'
            query_embedding: Pre-computed query embedding
            
        Returns:
            List of ConfidenceResult for each document
        """
        results = []
        
        for doc in documents:
            content = doc.get("content", doc.get("text", ""))
            doc_embedding = doc.get("embedding")
            
            result = self.evaluate(query, content, query_embedding, doc_embedding)
            results.append(result)
        
        return results
    
    def aggregate_confidence(self, results: List[ConfidenceResult]) -> float:
        """
        Calculate aggregate confidence from multiple document evaluations.
        
        Uses weighted average boosted by high-confidence documents.
        
        Args:
            results: List of ConfidenceResult
            
        Returns:
            Aggregate confidence score (0.0 - 1.0)
        """
        if not results:
            return 0.0
        
        # Weight high-confidence docs more heavily
        total_weight = 0.0
        weighted_sum = 0.0
        
        for result in results:
            if result.is_high_confidence:
                weight = 2.0  # Double weight for high confidence
            elif result.is_medium_confidence:
                weight = 1.0
            else:
                weight = 0.5
            
            weighted_sum += result.score * weight
            total_weight += weight
        
        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def _calculate_bm25(self, query: str, doc_content: str) -> Tuple[float, List[str]]:
        """
        Calculate BM25-inspired keyword matching score.
        
        Simplified BM25 without IDF (single document context).
        
        Returns:
            Tuple of (score, matched_terms)
        """
        # Tokenize
        query_tokens = self._tokenize(query)
        doc_tokens = self._tokenize(doc_content)
        
        if not query_tokens or not doc_tokens:
            return 0.0, []
        
        # Count term frequencies
        doc_term_counts = Counter(doc_tokens)
        doc_length = len(doc_tokens)
        avg_doc_length = 500  # Assume average document length
        
        matched_terms = []
        score = 0.0
        
        for term in query_tokens:
            if term in doc_term_counts:
                matched_terms.append(term)
                tf = doc_term_counts[term]
                
                # BM25 term frequency component
                numerator = tf * (self._config.bm25_k1 + 1)
                denominator = tf + self._config.bm25_k1 * (
                    1 - self._config.bm25_b + 
                    self._config.bm25_b * (doc_length / avg_doc_length)
                )
                
                score += numerator / denominator
        
        # Normalize by query length
        normalized_score = score / len(query_tokens)
        
        # Scale to [0, 1] (empirical cap at 2.0)
        return min(1.0, normalized_score / 2.0), matched_terms
    
    def _calculate_cosine_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> float:
        """Calculate cosine similarity between two embeddings."""
        if not embedding1 or not embedding2:
            return 0.0
        
        if len(embedding1) != len(embedding2):
            logger.warning("[HybridEval] Embedding dimension mismatch")
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        norm1 = math.sqrt(sum(a * a for a in embedding1))
        norm2 = math.sqrt(sum(b * b for b in embedding2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        # Cosine similarity is in [-1, 1], normalize to [0, 1]
        similarity = dot_product / (norm1 * norm2)
        return (similarity + 1) / 2
    
    def _calculate_maritime_boost(
        self,
        query: str,
        doc_content: str
    ) -> Tuple[float, List[str]]:
        """
        Calculate maritime domain-specific boost.
        
        Rewards documents with maritime terminology and rule references.
        
        Returns:
            Tuple of (boost_score, matched_maritime_terms)
        """
        query_lower = query.lower()
        doc_lower = doc_content.lower()
        combined = query_lower + " " + doc_lower
        
        matched_terms = []
        boost = 0.0
        
        # Check for rule number match (highest boost)
        query_rules = set(RULE_PATTERN.findall(query_lower))
        doc_rules = set(RULE_PATTERN.findall(doc_lower))
        
        if query_rules and query_rules.intersection(doc_rules):
            # Direct rule number match - very high confidence
            matched_terms.append(f"Điều {list(query_rules)[0]}")
            boost += 0.5
        
        # Check maritime vocabulary
        maritime_matches = 0
        for term in MARITIME_CORE_TERMS:
            if term in combined:
                maritime_matches += 1
                if maritime_matches <= 5:  # Limit matched terms
                    matched_terms.append(term)
        
        # Scale maritime matches (diminishing returns)
        if maritime_matches > 0:
            boost += min(0.5, maritime_matches * 0.1)
        
        return min(1.0, boost), matched_terms
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        # Lowercase and split on non-alphanumeric
        text = text.lower()
        tokens = re.findall(r'[\w]+', text)
        # Filter very short tokens
        return [t for t in tokens if len(t) >= 2]


# =============================================================================
# SINGLETON
# =============================================================================

_evaluator: Optional[HybridConfidenceEvaluator] = None


def get_hybrid_confidence_evaluator(
    config: Optional[HybridEvaluatorConfig] = None
) -> HybridConfidenceEvaluator:
    """Get or create HybridConfidenceEvaluator singleton."""
    global _evaluator
    if _evaluator is None:
        _evaluator = HybridConfidenceEvaluator(config)
    return _evaluator
