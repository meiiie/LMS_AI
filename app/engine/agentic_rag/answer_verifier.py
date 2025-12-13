"""
Answer Verifier - Phase 7.4

Verifies generated answers for hallucinations and accuracy.

Features:
- Factual consistency checking
- Citation verification
- Confidence scoring
- Warning generation
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of answer verification."""
    is_valid: bool
    confidence: float  # 0-100
    issues: List[str]
    warning: Optional[str] = None
    
    @property
    def needs_warning(self) -> bool:
        """Check if answer needs a warning."""
        return not self.is_valid or self.confidence < 70


VERIFY_PROMPT = """Bạn là Answer Verifier cho hệ thống Maritime AI.

Kiểm tra xem câu trả lời có chính xác với nguồn không.

Câu trả lời:
{answer}

Nguồn tham khảo:
{sources}

Trả về JSON:
{{
    "is_factually_correct": true/false,
    "confidence": 0-100,
    "issues": ["issue1", "issue2"],
    "has_unsupported_claims": true/false
}}

Kiểm tra:
1. Thông tin trong câu trả lời có xuất hiện trong nguồn không?
2. Có thông tin bịa đặt (hallucination) không?
3. Số liệu, tên, điều luật có chính xác không?

CHỈ TRẢ VỀ JSON."""


class AnswerVerifier:
    """
    Verifies answers for hallucinations.
    
    Usage:
        verifier = AnswerVerifier()
        result = await verifier.verify(answer, sources)
        if result.needs_warning:
            answer = f"⚠️ {result.warning}\\n{answer}"
    """
    
    def __init__(self, min_confidence: float = 70.0):
        """
        Initialize verifier.
        
        Args:
            min_confidence: Minimum confidence to pass verification
        """
        self._llm = None
        self._min_confidence = min_confidence
        self._init_llm()
    
    def _init_llm(self):
        """Initialize Gemini LLM for verification."""
        try:
            self._llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=settings.google_api_key,
                temperature=0.0,  # Strict verification
                max_output_tokens=500
            )
            logger.info("AnswerVerifier initialized with Gemini")
        except Exception as e:
            logger.error(f"Failed to initialize AnswerVerifier LLM: {e}")
            self._llm = None
    
    async def verify(
        self,
        answer: str,
        sources: List[Dict[str, Any]]
    ) -> VerificationResult:
        """
        Verify answer against sources.
        
        Args:
            answer: Generated answer to verify
            sources: Source documents used for generation
            
        Returns:
            VerificationResult with validity and confidence
        """
        if not answer:
            return VerificationResult(
                is_valid=False,
                confidence=0,
                issues=["Empty answer"],
                warning="Không có câu trả lời"
            )
        
        if not sources:
            # No sources to verify against
            return VerificationResult(
                is_valid=True,
                confidence=50,  # Uncertain
                issues=["No sources to verify against"],
                warning="Câu trả lời có thể không chính xác do thiếu nguồn tham khảo"
            )
        
        if not self._llm:
            return self._rule_based_verify(answer, sources)
        
        try:
            # Format sources
            source_text = "\n---\n".join([
                s.get("content", s.get("text", ""))[:500]
                for s in sources[:3]  # Limit to 3 sources
            ])
            
            messages = [
                SystemMessage(content="You are a fact-checker. Return only valid JSON."),
                HumanMessage(content=VERIFY_PROMPT.format(
                    answer=answer[:1500],  # Limit answer length
                    sources=source_text
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            result = response.content.strip()
            
            # Parse JSON
            import json
            if result.startswith("```"):
                result = result.split("```")[1]
                if result.startswith("json"):
                    result = result[4:]
            result = result.strip()
            
            data = json.loads(result)
            
            is_correct = data.get("is_factually_correct", True)
            confidence = float(data.get("confidence", 80))
            issues = data.get("issues", [])
            has_unsupported = data.get("has_unsupported_claims", False)
            
            is_valid = is_correct and not has_unsupported and confidence >= self._min_confidence
            
            warning = None
            if not is_valid:
                if has_unsupported:
                    warning = "Câu trả lời có thể chứa thông tin chưa được xác minh"
                elif confidence < self._min_confidence:
                    warning = f"Độ tin cậy thấp ({confidence:.0f}%). Vui lòng kiểm tra lại với nguồn chính thức"
                else:
                    warning = "Một số thông tin có thể không chính xác"
            
            logger.info(f"[VERIFIER] valid={is_valid} confidence={confidence:.0f}% issues={len(issues)}")
            
            return VerificationResult(
                is_valid=is_valid,
                confidence=confidence,
                issues=issues,
                warning=warning
            )
            
        except Exception as e:
            logger.warning(f"LLM verification failed: {e}")
            return self._rule_based_verify(answer, sources)
    
    async def check_citations(
        self,
        answer: str,
        sources: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        Check if citations in answer match sources.
        
        Args:
            answer: Answer with citations
            sources: Source documents
            
        Returns:
            Dict mapping citation to validity
        """
        # Simple rule-based citation check
        import re
        
        # Find patterns like "Điều 15", "Rule 15", "SOLAS Chapter II-2"
        citation_patterns = [
            r"Điều\s+\d+",
            r"Rule\s+\d+",
            r"SOLAS\s+Chapter\s+[\w-]+",
            r"MARPOL\s+Annex\s+\w+"
        ]
        
        citations_found = []
        for pattern in citation_patterns:
            matches = re.findall(pattern, answer, re.IGNORECASE)
            citations_found.extend(matches)
        
        # Check if citations appear in sources
        source_text = " ".join([
            s.get("content", s.get("text", ""))
            for s in sources
        ]).lower()
        
        results = {}
        for citation in citations_found:
            results[citation] = citation.lower() in source_text
        
        return results
    
    def _rule_based_verify(
        self,
        answer: str,
        sources: List[Dict[str, Any]]
    ) -> VerificationResult:
        """Fallback rule-based verification."""
        # Simple keyword overlap check
        source_text = " ".join([
            s.get("content", s.get("text", ""))
            for s in sources
        ]).lower()
        
        answer_words = set(answer.lower().split())
        source_words = set(source_text.split())
        
        overlap = answer_words.intersection(source_words)
        overlap_ratio = len(overlap) / max(len(answer_words), 1)
        
        confidence = min(100, overlap_ratio * 150)  # Scale to 0-100
        
        issues = []
        if overlap_ratio < 0.3:
            issues.append("Low keyword overlap with sources")
        
        return VerificationResult(
            is_valid=confidence >= self._min_confidence,
            confidence=confidence,
            issues=issues,
            warning="Không thể xác minh hoàn toàn do giới hạn hệ thống" if confidence < self._min_confidence else None
        )
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_verifier: Optional[AnswerVerifier] = None

def get_answer_verifier() -> AnswerVerifier:
    """Get or create AnswerVerifier singleton."""
    global _verifier
    if _verifier is None:
        _verifier = AnswerVerifier()
    return _verifier
