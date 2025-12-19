"""
Self-Reflection Parser - SOTA 2025 Self-RAG Pattern.

Parses reflection tokens from LLM responses for quality assessment.

Pattern References:
- Self-RAG (Asai et al.): Reflection tokens for quality control
- Gemini 3.0: Native thinking blocks
- LangGraph: Self-reflective agents

Key Reflection Tokens (Self-RAG):
- IsSupported: Is the answer supported by retrieved documents?
- IsUseful: Does the answer actually address the user's query?
- NeedsCorrection: Should we iterate to improve the answer?

Feature: self-reflective-rag-phase3
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)


class ReflectionConfidence(Enum):
    """Confidence levels for reflection assessment."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class ReflectionResult:
    """
    Result from Self-RAG reflection parsing.
    
    Attributes:
        is_supported: Answer is supported by documents
        is_useful: Answer addresses the query
        needs_correction: Should iterate to improve
        confidence: Overall reflection confidence
        thinking_content: Extracted thinking/reasoning
        answer_content: Extracted answer
        correction_reason: Why correction is needed (if any)
    """
    is_supported: bool
    is_useful: bool
    needs_correction: bool
    confidence: ReflectionConfidence
    thinking_content: str
    answer_content: str
    correction_reason: Optional[str] = None
    raw_response: Optional[str] = None


# Patterns for parsing reflection tokens
REFLECTION_PATTERNS = {
    # Explicit Self-RAG style tokens
    "supported": re.compile(
        r'\[(?:IS_?)?SUPPORTED[:\s]*([^\]]+)\]|'
        r'is_?supported[:\s]*([^\n,}]+)',
        re.IGNORECASE
    ),
    "useful": re.compile(
        r'\[(?:IS_?)?USEFUL[:\s]*([^\]]+)\]|'
        r'is_?useful[:\s]*([^\n,}]+)',
        re.IGNORECASE
    ),
    "needs_correction": re.compile(
        r'\[NEEDS_?CORRECTION[:\s]*([^\]]+)\]|'
        r'needs_?correction[:\s]*([^\n,}]+)',
        re.IGNORECASE
    ),
    # JSON style
    "json_confidence": re.compile(
        r'"(?:confidence|chính xác|độ tin cậy)"[:\s]*["\']?(\d+(?:\.\d+)?)["\']?',
        re.IGNORECASE
    ),
}

# Negative indicators suggesting need for correction
CORRECTION_INDICATORS = [
    # Vietnamese
    "không chắc chắn", "cần xác minh", "thiếu thông tin",
    "không đủ", "có thể không chính xác", "cần kiểm tra",
    # English
    "not sure", "uncertain", "need verification",
    "insufficient", "may be incorrect", "need to check",
    "i don't know", "cannot determine", "unclear",
]

# Positive indicators suggesting answer is good
POSITIVE_INDICATORS = [
    # Vietnamese
    "chắc chắn", "rõ ràng", "đúng", "chính xác",
    "theo điều", "căn cứ", "dựa trên",
    # English
    "certain", "clear", "correct", "accurate",
    "according to", "based on", "as stated in",
]


class ReflectionParser:
    """
    SOTA 2025: Self-RAG Reflection Token Parser.
    
    Extracts reflection signals from LLM responses to determine
    if the answer needs correction/iteration.
    
    Supports:
    - Explicit reflection tokens [IS_SUPPORTED: yes]
    - JSON-style confidence scores
    - Natural language indicators
    - Gemini 3.0 native thinking blocks
    
    Usage:
        parser = ReflectionParser()
        
        result = parser.parse(response_content)
        
        if result.needs_correction:
            # Trigger correction iteration
            corrected = await self._correct(query, result)
    """
    
    def __init__(self):
        """Initialize reflection parser."""
        self._use_thinking = settings.rag_enable_reflection
        logger.info(f"[ReflectionParser] Initialized (enabled={self._use_thinking})")
    
    def parse(self, response: Any) -> ReflectionResult:
        """
        Parse reflection tokens from LLM response.
        
        Args:
            response: Raw LLM response (string or Gemini content blocks)
            
        Returns:
            ReflectionResult with extracted reflection signals
        """
        # Extract text content and thinking from response
        from app.services.output_processor import extract_thinking_from_response
        text_content, thinking_content = extract_thinking_from_response(response)
        
        # Parse reflection signals
        is_supported = self._check_supported(text_content, thinking_content)
        is_useful = self._check_useful(text_content, thinking_content)
        confidence = self._extract_confidence(text_content, thinking_content)
        
        # Determine if correction is needed
        needs_correction, correction_reason = self._check_needs_correction(
            text_content, thinking_content, is_supported, is_useful, confidence
        )
        
        result = ReflectionResult(
            is_supported=is_supported,
            is_useful=is_useful,
            needs_correction=needs_correction,
            confidence=confidence,
            thinking_content=thinking_content or "",
            answer_content=text_content,
            correction_reason=correction_reason,
            raw_response=str(response)[:500] if response else None
        )
        
        logger.debug(
            f"[ReflectionParser] Result: supported={is_supported}, "
            f"useful={is_useful}, needs_correction={needs_correction}, "
            f"confidence={confidence.value}"
        )
        
        return result
    
    def _check_supported(
        self,
        text: str,
        thinking: Optional[str]
    ) -> bool:
        """Check if answer is supported by documents."""
        combined = f"{text} {thinking or ''}"
        
        # Check explicit token
        match = REFLECTION_PATTERNS["supported"].search(combined)
        if match:
            value = match.group(1) or match.group(2)
            return self._parse_bool(value)
        
        # Check for citation indicators
        citation_patterns = [
            r'theo điều\s*\d+', r'căn cứ', r'dựa trên',
            r'according to', r'based on', r'as per',
        ]
        for pattern in citation_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return True
        
        # Default: assume supported if no negative indicators
        return not any(ind in combined.lower() for ind in ["không có thông tin", "no information"])
    
    def _check_useful(
        self,
        text: str,
        thinking: Optional[str]
    ) -> bool:
        """Check if answer addresses the query."""
        combined = f"{text} {thinking or ''}"
        
        # Check explicit token
        match = REFLECTION_PATTERNS["useful"].search(combined)
        if match:
            value = match.group(1) or match.group(2)
            return self._parse_bool(value)
        
        # Check for unhelpful indicators
        unhelpful = ["tôi không thể", "i cannot", "không có câu trả lời", "no answer"]
        if any(ind in combined.lower() for ind in unhelpful):
            return False
        
        # Default: assume useful if has content
        return len(text.strip()) > 50
    
    def _extract_confidence(
        self,
        text: str,
        thinking: Optional[str]
    ) -> ReflectionConfidence:
        """Extract confidence level from response."""
        combined = f"{text} {thinking or ''}"
        
        # Check for explicit confidence score
        match = REFLECTION_PATTERNS["json_confidence"].search(combined)
        if match:
            try:
                score = float(match.group(1))
                if score >= 0.8 or score >= 8:
                    return ReflectionConfidence.HIGH
                elif score >= 0.5 or score >= 5:
                    return ReflectionConfidence.MEDIUM
                else:
                    return ReflectionConfidence.LOW
            except ValueError:
                pass
        
        # Check for indicator words
        positive_count = sum(1 for ind in POSITIVE_INDICATORS if ind in combined.lower())
        negative_count = sum(1 for ind in CORRECTION_INDICATORS if ind in combined.lower())
        
        if positive_count > negative_count + 2:
            return ReflectionConfidence.HIGH
        elif negative_count > positive_count:
            return ReflectionConfidence.LOW
        else:
            return ReflectionConfidence.MEDIUM
    
    def _check_needs_correction(
        self,
        text: str,
        thinking: Optional[str],
        is_supported: bool,
        is_useful: bool,
        confidence: ReflectionConfidence
    ) -> Tuple[bool, Optional[str]]:
        """
        Determine if the answer needs correction.
        
        Uses Self-RAG pattern: iterate only when confidence is low
        or explicit correction signals are present.
        """
        combined = f"{text} {thinking or ''}"
        
        # Check explicit needs_correction token
        match = REFLECTION_PATTERNS["needs_correction"].search(combined)
        if match:
            value = match.group(1) or match.group(2)
            if self._parse_bool(value):
                return True, "Explicit correction token found"
        
        # Check for correction indicators in thinking
        if thinking:
            for indicator in CORRECTION_INDICATORS:
                if indicator in thinking.lower():
                    return True, f"Correction indicator in thinking: {indicator}"
        
        # Low confidence triggers correction
        if confidence == ReflectionConfidence.LOW:
            return True, "Low confidence detected"
        
        # Not supported triggers correction
        if not is_supported:
            return True, "Answer not supported by documents"
        
        # Not useful triggers correction
        if not is_useful:
            return True, "Answer doesn't address query"
        
        # HIGH confidence with support = no correction needed
        if confidence == ReflectionConfidence.HIGH and is_supported and is_useful:
            return False, None
        
        # MEDIUM confidence: check quality mode
        if settings.rag_quality_mode == "quality":
            # Quality mode: iterate on medium confidence too
            if confidence == ReflectionConfidence.MEDIUM:
                return True, "Quality mode: medium confidence triggers correction"
        
        return False, None
    
    def _parse_bool(self, value: str) -> bool:
        """Parse boolean value from string."""
        value = value.strip().lower()
        return value in ("yes", "true", "1", "có", "đúng", "chính xác")


# =============================================================================
# SINGLETON
# =============================================================================

_parser: Optional[ReflectionParser] = None


def get_reflection_parser() -> ReflectionParser:
    """Get or create ReflectionParser singleton."""
    global _parser
    if _parser is None:
        _parser = ReflectionParser()
    return _parser
