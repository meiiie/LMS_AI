"""
Input/Output Guardrails for content safety.

This module implements guardrails for validating user input and AI output,
including harmful content detection, prompt injection prevention, and PII masking.

**Feature: maritime-ai-tutor**
**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 9.4**
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Protocol, Set

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ValidationStatus(str, Enum):
    """Status of content validation."""
    VALID = "VALID"
    BLOCKED = "BLOCKED"
    FLAGGED = "FLAGGED"


class ValidationResult(BaseModel):
    """
    Result of content validation.
    
    **Validates: Requirements 7.1, 7.2**
    """
    is_valid: bool = Field(..., description="Whether content passed validation")
    status: ValidationStatus = Field(default=ValidationStatus.VALID)
    issues: List[str] = Field(default_factory=list, description="List of issues found")
    sanitized_content: Optional[str] = Field(
        default=None, 
        description="Sanitized version of content"
    )
    
    def has_issues(self) -> bool:
        """Check if validation found any issues."""
        return len(self.issues) > 0


# Harmful content patterns
HARMFUL_PATTERNS: Set[str] = {
    "hack", "exploit", "attack", "malware", "virus",
    "illegal", "smuggle", "piracy", "weapon", "bomb",
    "kill", "murder", "suicide", "self-harm",
}

# Prompt injection patterns
INJECTION_PATTERNS: List[str] = [
    r"ignore\s+(previous|all)\s+instructions",
    r"disregard\s+(your|the)\s+rules",
    r"you\s+are\s+now\s+",
    r"pretend\s+to\s+be",
    r"act\s+as\s+if",
    r"forget\s+(everything|your\s+training)",
    r"new\s+instructions:",
    r"system\s*:\s*",
    r"\[system\]",
    r"<\s*system\s*>",
]

# PII patterns for masking
PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone": r"\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}[-]?\d{2}[-]?\d{4}\b",
    "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
}


class IGuardrails(Protocol):
    """
    Interface for Guardrails implementations.
    
    Defines the contract for input/output validation.
    """
    
    async def validate_input(self, message: str) -> ValidationResult:
        """Validate user input for harmful content."""
        ...
    
    async def validate_output(self, response: str) -> ValidationResult:
        """Validate AI output against professional standards."""
        ...
    
    def detect_prompt_injection(self, message: str) -> bool:
        """Detect prompt injection attempts."""
        ...
    
    def mask_pii(self, text: str) -> str:
        """Mask PII in text."""
        ...


class Guardrails:
    """
    Implementation of content guardrails.
    
    Provides:
    - Input validation for harmful content
    - Output validation for professional standards
    - Prompt injection detection
    - PII masking for logs
    
    **Validates: Requirements 7.1, 7.2, 7.4, 9.4**
    """
    
    REFUSAL_MESSAGE = (
        "I'm sorry, but I can't help with that request. "
        "Please ask about maritime topics in a professional manner."
    )
    
    def __init__(self):
        """Initialize guardrails with compiled patterns."""
        self._injection_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in INJECTION_PATTERNS
        ]
        self._pii_patterns = {
            name: re.compile(pattern) 
            for name, pattern in PII_PATTERNS.items()
        }
    
    async def validate_input(self, message: str) -> ValidationResult:
        """
        Validate user input for harmful content.
        
        Args:
            message: User's input message
            
        Returns:
            ValidationResult with validation status
            
        **Validates: Requirements 7.1**
        """
        issues = []
        message_lower = message.lower()
        
        # Check for harmful content
        for pattern in HARMFUL_PATTERNS:
            if pattern in message_lower:
                issues.append(f"Potentially harmful content detected: {pattern}")
        
        # Check for prompt injection
        if self.detect_prompt_injection(message):
            issues.append("Potential prompt injection detected")
            logger.warning(f"Prompt injection attempt detected")
            return ValidationResult(
                is_valid=False,
                status=ValidationStatus.BLOCKED,
                issues=issues,
                sanitized_content=None
            )
        
        # If harmful content found, block
        if issues:
            return ValidationResult(
                is_valid=False,
                status=ValidationStatus.BLOCKED,
                issues=issues,
                sanitized_content=None
            )
        
        return ValidationResult(
            is_valid=True,
            status=ValidationStatus.VALID,
            issues=[],
            sanitized_content=message
        )
    
    async def validate_output(self, response: str) -> ValidationResult:
        """
        Validate AI output against professional standards.
        
        Args:
            response: AI-generated response
            
        Returns:
            ValidationResult with validation status
            
        **Validates: Requirements 7.2, 7.3**
        """
        issues = []
        response_lower = response.lower()
        
        # Check for safety-critical misinformation indicators
        safety_keywords = ["always safe", "never dangerous", "100% safe", "no risk"]
        for keyword in safety_keywords:
            if keyword in response_lower:
                issues.append(f"Potential safety misinformation: {keyword}")
        
        # Check for unprofessional language
        unprofessional = ["lol", "lmao", "wtf", "omg"]
        for word in unprofessional:
            if word in response_lower.split():
                issues.append(f"Unprofessional language: {word}")
        
        if issues:
            return ValidationResult(
                is_valid=True,  # Still valid but flagged
                status=ValidationStatus.FLAGGED,
                issues=issues,
                sanitized_content=response
            )
        
        return ValidationResult(
            is_valid=True,
            status=ValidationStatus.VALID,
            issues=[],
            sanitized_content=response
        )

    
    def detect_prompt_injection(self, message: str) -> bool:
        """
        Detect prompt injection attempts.
        
        Args:
            message: User's input message
            
        Returns:
            True if injection detected, False otherwise
            
        **Validates: Requirements 7.4**
        """
        for pattern in self._injection_patterns:
            if pattern.search(message):
                logger.warning(f"Prompt injection pattern matched: {pattern.pattern}")
                return True
        return False
    
    def mask_pii(self, text: str) -> str:
        """
        Mask PII in text for logging.
        
        Replaces:
        - Email addresses with [EMAIL]
        - Phone numbers with [PHONE]
        - SSN with [SSN]
        - Credit card numbers with [CREDIT_CARD]
        
        Args:
            text: Text potentially containing PII
            
        Returns:
            Text with PII masked
            
        **Validates: Requirements 9.4**
        """
        masked = text
        
        for pii_type, pattern in self._pii_patterns.items():
            masked = pattern.sub(f"[{pii_type.upper()}]", masked)
        
        return masked
    
    def get_refusal_message(self) -> str:
        """Get the standard refusal message."""
        return self.REFUSAL_MESSAGE


def mask_pii_in_log(text: str) -> str:
    """
    Utility function to mask PII in log entries.
    
    **Validates: Requirements 9.4**
    """
    guardrails = Guardrails()
    return guardrails.mask_pii(text)


@dataclass
class GuardrailsConfig:
    """Configuration for guardrails behavior."""
    block_harmful_content: bool = True
    detect_injection: bool = True
    mask_pii_in_logs: bool = True
    flag_safety_misinformation: bool = True
