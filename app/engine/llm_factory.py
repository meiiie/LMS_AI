"""
LLM Factory - Centralized Gemini LLM Creation with Tiered Thinking

CHỈ THỊ KỸ THUẬT SỐ 28: SOTA 2025 Gemini Thinking Configuration

4-Tier Thinking Strategy based on Chain of Draft (CoD) pattern:
- DEEP (8192): Teaching agents - requires full explanation
- MODERATE (4096): RAG synthesis - requires summarization  
- LIGHT (1024): Quick check - basic self-check
- MINIMAL (512): Structured tasks - minimal buffer

"Uốn lưỡi 7 lần trước khi nói" - All components need thinking, but level varies.
"""

from enum import Enum
from typing import Optional
import logging

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# THINKING TIER ENUM
# =============================================================================

class ThinkingTier(Enum):
    """
    4-Tier Thinking Strategy.
    
    Values correspond to thinking_budget tokens.
    """
    DEEP = "deep"         # Teaching agents (tutor, unified_agent)
    MODERATE = "moderate" # RAG synthesis (rag_agent, grader)
    LIGHT = "light"       # Quick check (analyzer, verifier)
    MINIMAL = "minimal"   # Structured tasks (extraction, memory)
    DYNAMIC = "dynamic"   # Let Gemini auto-decide (-1)
    OFF = "off"           # Disabled (0) - use sparingly!


def get_thinking_budget(tier: ThinkingTier) -> int:
    """
    Get thinking budget for a tier from config.
    
    Args:
        tier: ThinkingTier enum value
        
    Returns:
        Token budget for thinking (0-24576, or -1 for dynamic)
    """
    if not settings.thinking_enabled:
        return 0
    
    budget_map = {
        ThinkingTier.DEEP: settings.thinking_budget_deep,
        ThinkingTier.MODERATE: settings.thinking_budget_moderate,
        ThinkingTier.LIGHT: settings.thinking_budget_light,
        ThinkingTier.MINIMAL: settings.thinking_budget_minimal,
        ThinkingTier.DYNAMIC: -1,
        ThinkingTier.OFF: 0,
    }
    
    return budget_map.get(tier, settings.thinking_budget_moderate)


# =============================================================================
# LLM FACTORY
# =============================================================================

def create_llm(
    tier: ThinkingTier = ThinkingTier.MODERATE,
    temperature: float = 0.7,
    include_thoughts: Optional[bool] = None,
    model: Optional[str] = None,
) -> ChatGoogleGenerativeAI:
    """
    Factory function for creating Gemini LLM with proper thinking config.
    
    SOTA Pattern: Centralized LLM creation with configurable thinking.
    
    Args:
        tier: Thinking tier (DEEP, MODERATE, LIGHT, MINIMAL, DYNAMIC, OFF)
        temperature: LLM temperature (0.0-2.0)
        include_thoughts: Include thought summaries in response (default from config)
        model: Override model name (default from config)
        
    Returns:
        ChatGoogleGenerativeAI instance with thinking config
        
    Note:
        Response format when include_thoughts=True:
        response.content = [
            {'type': 'thinking', 'thinking': '...'},  # Reasoning
            {'type': 'text', 'text': '...'}           # Answer
        ]
        
    Example:
        >>> llm = create_llm(tier=ThinkingTier.DEEP)
        >>> response = await llm.ainvoke(messages)
    """
    thinking_budget = get_thinking_budget(tier)
    
    # Default include_thoughts from config
    if include_thoughts is None:
        include_thoughts = settings.include_thought_summaries
    
    # Model selection
    model_name = model or settings.google_model
    
    logger.info(
        f"[LLM_FACTORY] Creating LLM: model={model_name}, tier={tier.value}, "
        f"budget={thinking_budget}, include_thoughts={include_thoughts}"
    )
    
    # LangChain ChatGoogleGenerativeAI supports direct params (langchain-google-genai >= 3.1.0)
    # thinking_budget and include_thoughts are TOP-LEVEL parameters, not nested!
    llm_kwargs = {
        "model": model_name,
        "temperature": temperature,
        "google_api_key": settings.google_api_key,
    }
    
    # Add thinking config if enabled (requires langchain-google-genai >= 3.0.0)
    if settings.thinking_enabled and thinking_budget != 0:
        llm_kwargs["thinking_budget"] = thinking_budget
        if include_thoughts:
            llm_kwargs["include_thoughts"] = True
    
    return ChatGoogleGenerativeAI(**llm_kwargs)


# =============================================================================
# CONVENIENCE FUNCTIONS (Per-Component)
# =============================================================================

def create_tutor_llm(temperature: float = 0.7) -> ChatGoogleGenerativeAI:
    """
    LLM for student-facing teaching agents.
    
    Uses DEEP tier (8192 tokens) for full explanation capability.
    Includes thought summaries for educational transparency.
    """
    return create_llm(
        tier=ThinkingTier.DEEP,
        temperature=temperature,
        include_thoughts=True,  # Always show thinking for teaching
    )


def create_rag_llm(temperature: float = 0.5) -> ChatGoogleGenerativeAI:
    """
    LLM for RAG synthesis and grading.
    
    Uses MODERATE tier (4096 tokens) for summarization.
    Lower temperature for more consistent outputs.
    """
    return create_llm(
        tier=ThinkingTier.MODERATE,
        temperature=temperature,
        include_thoughts=False,  # Internal processing
    )


def create_analyzer_llm(temperature: float = 0.3) -> ChatGoogleGenerativeAI:
    """
    LLM for quick analysis tasks (intent detection, query analysis).
    
    Uses LIGHT tier (1024 tokens) for basic self-check.
    Lower temperature for deterministic outputs.
    """
    return create_llm(
        tier=ThinkingTier.LIGHT,
        temperature=temperature,
        include_thoughts=False,
    )


def create_extraction_llm(temperature: float = 0.2) -> ChatGoogleGenerativeAI:
    """
    LLM for structured extraction tasks (fact extraction, entity extraction).
    
    Uses MINIMAL tier (512 tokens) for minimal buffer.
    Very low temperature for consistent structured outputs.
    """
    return create_llm(
        tier=ThinkingTier.MINIMAL,
        temperature=temperature,
        include_thoughts=False,
    )


# =============================================================================
# LEGACY COMPATIBILITY
# =============================================================================

def create_default_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
) -> ChatGoogleGenerativeAI:
    """
    Create LLM with default settings (MODERATE tier).
    
    For backward compatibility with existing code.
    """
    return create_llm(
        tier=ThinkingTier.MODERATE,
        temperature=temperature,
        model=model,
    )
