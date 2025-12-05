"""
Prompt Management Module
CHỈ THỊ KỸ THUẬT SỐ 16: HUMANIZATION

Provides YAML-based persona configuration for AI responses.
"""

from .prompt_loader import PromptLoader, get_prompt_loader

__all__ = ["PromptLoader", "get_prompt_loader"]
