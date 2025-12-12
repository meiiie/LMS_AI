"""
Insight Validator - CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN
Validate and process insights before storage.

SOTA Upgrade: Embedding-based semantic similarity for duplicate detection.

Requirements: 5.1, 5.2, 5.3, 5.4
"""
import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

from app.models.semantic_memory import Insight, InsightCategory

if TYPE_CHECKING:
    from app.engine.gemini_embedding import GeminiOptimizedEmbeddings

logger = logging.getLogger(__name__)

# SOTA Thresholds
DUPLICATE_SIMILARITY_THRESHOLD = 0.85  # Cosine similarity for duplicates
CONTRADICTION_SIMILARITY_THRESHOLD = 0.70  # Lower threshold for contradictions


@dataclass
class ValidationResult:
    """Result of insight validation."""
    is_valid: bool
    reason: Optional[str] = None
    action: Optional[str] = None  # "store", "merge", "update", "reject"
    target_insight: Optional[Insight] = None  # For merge/update operations
    similarity_score: Optional[float] = None  # SOTA: Include similarity score


class InsightValidator:
    """Validate and process insights before storage."""
    
    MIN_INSIGHT_LENGTH = 20
    
    def __init__(self, embeddings: Optional["GeminiOptimizedEmbeddings"] = None):
        """
        Initialize the validator.
        
        Args:
            embeddings: Optional embeddings model for SOTA semantic similarity
        """
        self._embeddings = embeddings
        self._embedding_cache = {}  # Cache embeddings for efficiency
        
    def _compute_embedding(self, text: str) -> Optional[np.ndarray]:
        """Compute embedding for text with caching."""
        if not self._embeddings:
            return None
            
        # Check cache first
        cache_key = hash(text[:100])  # Use first 100 chars as key
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]
        
        try:
            embedding = self._embeddings.embed_documents([text])[0]
            embedding_array = np.array(embedding)
            self._embedding_cache[cache_key] = embedding_array
            return embedding_array
        except Exception as e:
            logger.warning(f"Failed to compute embedding: {e}")
            return None
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if vec1 is None or vec2 is None:
            return 0.0
        
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
            
        return float(np.dot(vec1, vec2) / (norm1 * norm2))
    
    def validate(self, insight: Insight, existing_insights: List[Insight] = None) -> ValidationResult:
        """
        Validate insight quality and determine action (SOTA: semantic matching).
        
        Args:
            insight: Insight to validate
            existing_insights: List of existing insights for duplicate/contradiction detection
            
        Returns:
            ValidationResult with action to take and similarity score
        """
        existing_insights = existing_insights or []
        
        # 1. Basic validation
        basic_result = self._validate_basic(insight)
        if not basic_result.is_valid:
            return basic_result
        
        # 2. Check for duplicates (SOTA: embedding similarity)
        duplicate, similarity_score = self.find_duplicate(insight, existing_insights)
        if duplicate:
            return ValidationResult(
                is_valid=True,
                reason=f"Duplicate insight found (similarity: {similarity_score:.2f})",
                action="merge",
                target_insight=duplicate,
                similarity_score=similarity_score
            )
        
        # 3. Check for contradictions
        contradiction = self.detect_contradiction(insight, existing_insights)
        if contradiction:
            return ValidationResult(
                is_valid=True,
                reason="Contradicting insight found",
                action="update",
                target_insight=contradiction
            )
        
        # 4. All good, store as new
        return ValidationResult(
            is_valid=True,
            reason="Valid new insight",
            action="store",
            similarity_score=similarity_score if similarity_score > 0 else None
        )

    
    def _validate_basic(self, insight: Insight) -> ValidationResult:
        """Validate basic insight properties."""
        # Check content length
        if len(insight.content.strip()) < self.MIN_INSIGHT_LENGTH:
            return ValidationResult(
                is_valid=False,
                reason=f"Content too short (min {self.MIN_INSIGHT_LENGTH} chars)",
                action="reject"
            )
        
        # Check if content is behavioral (not atomic fact)
        if not self.is_behavioral(insight.content):
            return ValidationResult(
                is_valid=False,
                reason="Content appears to be atomic fact, not behavioral insight",
                action="reject"
            )
        
        # Check category validity
        try:
            InsightCategory(insight.category.value)
        except ValueError:
            return ValidationResult(
                is_valid=False,
                reason=f"Invalid category: {insight.category}",
                action="reject"
            )
        
        return ValidationResult(is_valid=True)
    
    def is_behavioral(self, content: str) -> bool:
        """
        Check if content describes behavior, not just fact.
        
        Behavioral indicators:
        - Contains verbs describing actions/preferences
        - Describes patterns or tendencies
        - Uses contextual language
        
        Atomic fact indicators:
        - Simple name/value pairs
        - Single words or short phrases
        - No context or explanation
        """
        content = content.lower().strip()
        
        # Too short is likely atomic
        if len(content) < 20:
            return False
        
        # Behavioral indicators
        behavioral_patterns = [
            # Preference patterns
            "thích", "prefer", "quan tâm", "interested in", "yêu thích",
            "không thích", "dislike", "tránh", "avoid",
            # Learning patterns  
            "học", "learn", "hiểu", "understand", "nắm bắt", "grasp",
            "tiếp cận", "approach", "phương pháp", "method", "cách",
            # Behavioral patterns
            "thường", "usually", "có xu hướng", "tend to", "có thói quen", "habit",
            "luôn", "always", "thỉnh thoảng", "sometimes", "hay", "often",
            # Evolution patterns
            "đã chuyển", "changed from", "bây giờ", "now", "trước đây", "previously",
            "phát triển", "develop", "tiến bộ", "progress", "cải thiện", "improve",
            # Gap patterns
            "chưa hiểu", "don't understand", "nhầm lẫn", "confuse", "khó khăn", "difficulty",
            "cần học thêm", "need to learn", "yếu", "weak at", "thiếu", "lack"
        ]
        
        # Check for behavioral indicators
        behavioral_score = sum(1 for pattern in behavioral_patterns if pattern in content)
        
        # Atomic fact indicators (negative score)
        atomic_patterns = [
            "tên là", "name is", "tuổi", "age", "sinh năm", "born",
            "địa chỉ", "address", "số điện thoại", "phone", "email",
            "làm việc tại", "work at", "công ty", "company"
        ]
        
        atomic_score = sum(1 for pattern in atomic_patterns if pattern in content)
        
        # Must have behavioral indicators and minimal atomic indicators
        return behavioral_score >= 1 and atomic_score == 0
    
    def find_duplicate(
        self,
        insight: Insight,
        existing: List[Insight]
    ) -> tuple[Optional[Insight], float]:
        """
        Find duplicate or very similar insight (SOTA: semantic similarity).
        
        Two insights are considered duplicates if:
        1. Same category
        2. Similar content (>=0.85 cosine similarity with embeddings)
        
        Returns:
            Tuple of (duplicate_insight, similarity_score)
        """
        best_match = None
        best_score = 0.0
        
        for existing_insight in existing:
            # Same category check is mandatory
            if existing_insight.category != insight.category:
                continue
            
            # Check content similarity using embeddings
            is_similar, score = self._is_similar_content(
                insight.content, 
                existing_insight.content
            )
            
            # Track best match
            if score > best_score:
                best_score = score
                if is_similar:
                    best_match = existing_insight
        
        return (best_match, best_score)
    
    def detect_contradiction(
        self,
        insight: Insight,
        existing: List[Insight]
    ) -> Optional[Insight]:
        """
        Detect if insight contradicts existing insight.
        
        Contradictions occur when:
        1. Same category and sub_topic
        2. Content expresses opposite meaning
        """
        for existing_insight in existing:
            # Same category check
            if existing_insight.category != insight.category:
                continue
            
            # Same sub_topic check
            if (insight.sub_topic and existing_insight.sub_topic and 
                insight.sub_topic.lower() == existing_insight.sub_topic.lower()):
                # Check for contradiction
                if self._is_contradicting_content(insight.content, existing_insight.content):
                    return existing_insight
        
        return None
    
    def _is_similar_content(self, content1: str, content2: str, threshold: float = None) -> tuple[bool, float]:
        """
        Check if two contents are semantically similar (SOTA: embedding-based).
        
        Uses cosine similarity of embeddings when available, falls back to Jaccard.
        
        Args:
            content1: First content string
            content2: Second content string
            threshold: Similarity threshold (default: DUPLICATE_SIMILARITY_THRESHOLD)
            
        Returns:
            Tuple of (is_similar, similarity_score)
        """
        threshold = threshold or DUPLICATE_SIMILARITY_THRESHOLD
        
        # SOTA: Try embedding-based similarity first
        if self._embeddings:
            emb1 = self._compute_embedding(content1)
            emb2 = self._compute_embedding(content2)
            
            if emb1 is not None and emb2 is not None:
                similarity = self._cosine_similarity(emb1, emb2)
                logger.debug(f"Embedding similarity: {similarity:.3f} (threshold: {threshold})")
                return (similarity >= threshold, similarity)
        
        # Fallback: Jaccard similarity (legacy)
        words1 = set(content1.lower().split())
        words2 = set(content2.lower().split())
        
        # Remove common words
        common_words = {"user", "người", "dùng", "học", "tập", "là", "có", "và", "the", "a", "an", "is", "has", "and"}
        words1 = words1 - common_words
        words2 = words2 - common_words
        
        if not words1 or not words2:
            return (False, 0.0)
        
        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        similarity = intersection / union if union > 0 else 0
        
        # Lower threshold for fallback (0.6 Jaccard ≈ 0.85 cosine)
        return (similarity > 0.6, similarity)
    
    def _is_contradicting_content(self, content1: str, content2: str) -> bool:
        """Check if two contents contradict each other."""
        content1_lower = content1.lower()
        content2_lower = content2.lower()
        
        # Contradiction patterns
        contradiction_pairs = [
            (["thích", "prefer", "yêu thích"], ["không thích", "dislike", "tránh"]),
            (["giỏi", "good at", "mạnh"], ["yếu", "weak", "kém"]),
            (["hiểu", "understand", "nắm"], ["không hiểu", "don't understand", "chưa hiểu"]),
            (["lý thuyết", "theory", "theoretical"], ["thực hành", "practical", "hands-on"]),
            (["nhanh", "fast", "quick"], ["chậm", "slow", "careful"]),
        ]
        
        for positive_words, negative_words in contradiction_pairs:
            # Check if content1 has positive and content2 has negative (or vice versa)
            content1_positive = any(word in content1_lower for word in positive_words)
            content1_negative = any(word in content1_lower for word in negative_words)
            content2_positive = any(word in content2_lower for word in positive_words)
            content2_negative = any(word in content2_lower for word in negative_words)
            
            # Contradiction detected
            if ((content1_positive and content2_negative) or 
                (content1_negative and content2_positive)):
                return True
        
        return False
