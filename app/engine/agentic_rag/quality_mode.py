"""
Quality Mode Presets - SOTA 2025 Self-Reflective RAG.

Provides preset configurations for different RAG quality/speed trade-offs.

Pattern References:
- LangGraph: Configurable agent parameters
- Self-RAG: Adaptive iteration based on context
- OpenAI/Anthropic: Quality tiers

Modes:
- speed: Fastest response, minimal iteration
- balanced: Default, good quality/speed balance  
- quality: Maximum accuracy, full reflection

Feature: self-reflective-rag-phase4
"""

from dataclasses import dataclass
from typing import Dict, Any
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class QualityModePreset:
    """Preset configuration for a quality mode."""
    name: str
    confidence_high: float
    confidence_medium: float
    max_iterations: int
    enable_reflection: bool
    early_exit: bool
    thinking_level: str
    enable_verification: bool
    description: str


# Quality mode presets
QUALITY_PRESETS: Dict[str, QualityModePreset] = {
    "speed": QualityModePreset(
        name="speed",
        confidence_high=0.70,      # Lower threshold = fewer iterations
        confidence_medium=0.50,
        max_iterations=1,           # Single pass only
        enable_reflection=False,    # Skip reflection for speed
        early_exit=True,
        thinking_level="low",       # Minimal Gemini thinking
        enable_verification=False,  # Skip verification
        description="Fastest response, minimal iteration. Best for simple queries."
    ),
    "balanced": QualityModePreset(
        name="balanced",
        confidence_high=0.85,       # Default threshold
        confidence_medium=0.60,
        max_iterations=2,           # Allow one correction
        enable_reflection=True,     # Enable Self-RAG
        early_exit=True,
        thinking_level="medium",    # Moderate reasoning
        enable_verification=True,   # Verify when complex
        description="Good quality/speed balance. Default for most queries."
    ),
    "quality": QualityModePreset(
        name="quality",
        confidence_high=0.92,       # High threshold = more thorough
        confidence_medium=0.75,
        max_iterations=3,           # Allow multiple corrections
        enable_reflection=True,     # Full Self-RAG
        early_exit=False,           # Don't exit early
        thinking_level="high",      # Maximum reasoning
        enable_verification=True,   # Always verify
        description="Maximum accuracy, full reflection. Best for complex/critical queries."
    ),
}


def get_quality_preset(mode: str = None) -> QualityModePreset:
    """
    Get quality mode preset.
    
    Args:
        mode: Quality mode name, uses settings.rag_quality_mode if None
        
    Returns:
        QualityModePreset for the specified mode
    """
    mode = mode or settings.rag_quality_mode
    
    if mode not in QUALITY_PRESETS:
        logger.warning(f"Unknown quality mode '{mode}', using 'balanced'")
        mode = "balanced"
    
    preset = QUALITY_PRESETS[mode]
    logger.debug(f"[QualityMode] Using preset: {preset.name}")
    
    return preset


def apply_quality_preset(mode: str = None) -> Dict[str, Any]:
    """
    Get quality mode settings as dictionary.
    
    Useful for passing to components that accept kwargs.
    
    Args:
        mode: Quality mode name
        
    Returns:
        Dictionary of settings from the preset
    """
    preset = get_quality_preset(mode)
    
    return {
        "confidence_high": preset.confidence_high,
        "confidence_medium": preset.confidence_medium,
        "max_iterations": preset.max_iterations,
        "enable_reflection": preset.enable_reflection,
        "early_exit": preset.early_exit,
        "thinking_level": preset.thinking_level,
        "enable_verification": preset.enable_verification,
    }


def get_effective_settings() -> Dict[str, Any]:
    """
    Get effective RAG settings by merging preset with explicit config.
    
    Explicit settings in config.py override preset values.
    
    Returns:
        Dictionary of effective settings
    """
    preset = get_quality_preset()
    
    # Start with preset values
    effective = {
        "confidence_high": preset.confidence_high,
        "confidence_medium": preset.confidence_medium,
        "max_iterations": preset.max_iterations,
        "enable_reflection": preset.enable_reflection,
        "early_exit": preset.early_exit,
        "thinking_level": preset.thinking_level,
        "enable_verification": preset.enable_verification,
    }
    
    # Override with explicit config if different from defaults
    # (allowing explicit config to take precedence)
    if settings.rag_confidence_high != 0.85:  # Not default
        effective["confidence_high"] = settings.rag_confidence_high
    if settings.rag_confidence_medium != 0.60:
        effective["confidence_medium"] = settings.rag_confidence_medium
    if settings.rag_max_iterations != 2:
        effective["max_iterations"] = settings.rag_max_iterations
    
    return effective


def describe_quality_modes() -> str:
    """Get human-readable description of all quality modes."""
    lines = ["# RAG Quality Modes\n"]
    
    for name, preset in QUALITY_PRESETS.items():
        current = " (CURRENT)" if name == settings.rag_quality_mode else ""
        lines.append(f"\n## {name.upper()}{current}")
        lines.append(f"- {preset.description}")
        lines.append(f"- Confidence: HIGH >= {preset.confidence_high}, MEDIUM >= {preset.confidence_medium}")
        lines.append(f"- Iterations: {preset.max_iterations}, Reflection: {preset.enable_reflection}")
        lines.append(f"- Thinking: {preset.thinking_level}, Verification: {preset.enable_verification}")
    
    return "\n".join(lines)
