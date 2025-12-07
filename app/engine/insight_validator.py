"""
Insight Validator - CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN
Validate and process insights before storage.

Requirements: 5.1, 5.2, 5.3, 5.4
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

from app.models.semantic_memory import Insight, InsightCategory

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of insight validation."""
    is_valid: bool
    reason: Optional[str] = None
    action: Optional[str] = None  # "store", "merge", "update", "reject"
    target_insight: Optional[Insight] = None  # For merge/update operations


class InsightValidator:
    """Validate and process insights before storage."""
    
    MIN_INSIGHT_LENGTH = 20
    
    def __init__(self):
        """Initialize the validator."""
        pass
    
    def validate(self, insight: Insight, existing_insights: List[Insight] = None) -> ValidationResult:
        """
        Validate insight quality and determine action.
        
        Args:
            insight: Insight to validate
            existing_insights: List of existing insights for duplicate/contradiction detection
            
        Returns:
            ValidationResult with action to take
        """
        existing_insights = existing_insights or []
        
        # 1. Basic validation
        basic_result = self._validate_basic(insight)
        if not basic_result.is_valid:
            return basic_result
        
        # 2. Check for duplicates
        duplicate = self.find_duplicate(insight, existing_insights)
        if duplicate:
            return ValidationResult(
                is_valid=True,
                reason="Duplicate insight found",
                action="merge",
                target_insight=duplicate
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
            action="store"
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
    ) -> Optional[Insight]:
        """
        Find duplicate or very similar insight.
        
        Two insights are considered duplicates if:
        1. Same category and sub_topic
        2. Similar content (semantic similarity)
        """
        for existing_insight in existing:
            # Same category check
            if existing_insight.category != insight.category:
                continue
            
            # Same sub_topic check (if both have sub_topic)
            if (insight.sub_topic and existing_insight.sub_topic and 
                insight.sub_topic.lower() == existing_insight.sub_topic.lower()):
                # Check content similarity
                if self._is_similar_content(insight.content, existing_insight.content):
                    return existing_insight
            
            # For insights without sub_topic, check content similarity only
            elif not insight.sub_topic and not existing_insight.sub_topic:
                if self._is_similar_content(insight.content, existing_insight.content):
                    return existing_insight
        
        return None
    
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
    
    def _is_similar_content(self, content1: str, content2: str) -> bool:
        """Check if two contents are semantically similar."""
        # Simple similarity check based on word overlap
        words1 = set(content1.lower().split())
        words2 = set(content2.lower().split())
        
        # Remove common words
        common_words = {"user", "người", "dùng", "học", "tập", "là", "có", "và", "the", "a", "an", "is", "has", "and"}
        words1 = words1 - common_words
        words2 = words2 - common_words
        
        if not words1 or not words2:
            return False
        
        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        similarity = intersection / union if union > 0 else 0
        
        # Consider similar if > 60% word overlap
        return similarity > 0.6
    
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
