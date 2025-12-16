"""
Centralized Thinking Post-Processor (CHỈ THỊ SỐ 29 v8)

SOTA Pattern: Response Post-Processor Middleware
- Single point for all thinking extraction/normalization
- Handles both <thinking> tags and Gemini native format
- Priority: text-based tags (Vietnamese) over native (English)

Usage:
    from app.services.thinking_post_processor import get_thinking_processor
    
    processor = get_thinking_processor()
    text, thinking = processor.process(response.content)

**Pattern:** Post-Processor Middleware (LangChain 2025 SOTA)
**Spec:** CHỈ THỊ SỐ 29 v8
"""

import re
import logging
from typing import Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ThinkingResult:
    """Standardized thinking extraction result."""
    text: str                     # Main response content (cleaned)
    thinking: Optional[str]       # Extracted thinking (Vietnamese preferred)
    source: str                   # 'text_tags' | 'gemini_native' | 'none'


class ThinkingPostProcessor:
    """
    Centralized thinking extraction and normalization.
    
    SOTA Pattern: Single point of processing for all LLM responses.
    
    Handles (in priority order):
    1. Text-based <thinking>...</thinking> tags (preferred - Vietnamese)
    2. Gemini native format {'type': 'thinking', 'thinking': '...'}
    3. Plain text responses (no thinking)
    
    The text-based format is preferred because:
    - Model writes in Vietnamese (follows system prompt language)
    - Works consistently across all agents (unified_agent, rag_agent, etc.)
    
    Example:
        >>> processor = ThinkingPostProcessor()
        >>> text, thinking = processor.process(response.content)
        >>> if thinking:
        ...     print(f"Thinking: {thinking[:100]}...")
    """
    
    # Pattern to extract <thinking>...</thinking> from text
    # Case-insensitive, handles multiline content
    THINKING_PATTERN = re.compile(
        r'<thinking>(.*?)</thinking>',
        re.DOTALL | re.IGNORECASE
    )
    
    def process(self, content: Any) -> Tuple[str, Optional[str]]:
        """
        Process LLM response and extract thinking content.
        
        This is the main entry point. It handles all response formats
        and returns a normalized (text, thinking) tuple.
        
        Args:
            content: Raw LLM response content
                     - str: Plain text (check for <thinking> tags)
                     - list: Gemini native format with content blocks
                     - other: Converted to string
                     
        Returns:
            Tuple of (cleaned_text, thinking_content)
            - cleaned_text: Response with <thinking> tags removed
            - thinking_content: Extracted thinking or None
        """
        result = self._extract(content)
        
        if result.thinking:
            logger.debug(
                f"[THINKING] Source: {result.source}, "
                f"Length: {len(result.thinking)} chars"
            )
        
        return result.text, result.thinking
    
    def _extract(self, content: Any) -> ThinkingResult:
        """
        Internal extraction logic with format detection.
        
        Priority:
        1. Check for <thinking> tags in text (Vietnamese - preferred)
        2. Check Gemini native format blocks
        3. Return plain text with no thinking
        """
        # Case 1: String - check for <thinking> tags first
        if isinstance(content, str):
            return self._extract_from_text(content)
        
        # Case 2: List (Gemini native format)
        if isinstance(content, list):
            return self._extract_from_list(content)
        
        # Case 3: Unknown format - convert to string and try
        text = str(content)
        return self._extract_from_text(text)
    
    def _extract_from_text(self, text: str) -> ThinkingResult:
        """
        Extract <thinking> tags from text response.
        
        This is the PREFERRED format because:
        - Model writes thinking in Vietnamese (follows system prompt)
        - Works consistently across unified_agent, rag_agent, etc.
        """
        match = self.THINKING_PATTERN.search(text)
        
        if match:
            thinking = match.group(1).strip()
            # Remove thinking tags from visible text
            clean_text = self.THINKING_PATTERN.sub('', text).strip()
            
            # Also clean up any extra whitespace left behind
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
            
            return ThinkingResult(
                text=clean_text,
                thinking=thinking,
                source='text_tags'
            )
        
        return ThinkingResult(text=text, thinking=None, source='none')
    
    def _extract_from_list(self, blocks: list) -> ThinkingResult:
        """
        Extract from Gemini native format.
        
        Gemini response format when thinking is enabled:
        [
            {'type': 'thinking', 'thinking': '...'},  # Reasoning trace
            {'type': 'text', 'text': '...'}           # Final answer
        ]
        
        NOTE: This format often outputs in English regardless of prompt.
        We check for <thinking> tags in the combined text first.
        """
        text_parts = []
        native_thinking_parts = []
        
        for block in blocks:
            if isinstance(block, dict):
                block_type = block.get('type', '')
                
                if block_type == 'thinking':
                    native_thinking = block.get('thinking', '')
                    if native_thinking:
                        native_thinking_parts.append(native_thinking)
                        
                elif block_type == 'text':
                    text_content = block.get('text', '')
                    if text_content:
                        text_parts.append(text_content)
                        
            elif isinstance(block, str):
                # Plain string in list
                text_parts.append(block)
        
        combined_text = '\n'.join(text_parts)
        
        # PRIORITY: Check for <thinking> tags in text first (Vietnamese)
        text_result = self._extract_from_text(combined_text)
        if text_result.thinking:
            return text_result
        
        # FALLBACK: Use Gemini native thinking (may be English)
        if native_thinking_parts:
            native_thinking = '\n'.join(native_thinking_parts)
            return ThinkingResult(
                text=combined_text,
                thinking=native_thinking,
                source='gemini_native'
            )
        
        # No thinking found
        return ThinkingResult(text=combined_text, thinking=None, source='none')


# =============================================================================
# SINGLETON PATTERN
# =============================================================================

_processor: Optional[ThinkingPostProcessor] = None


def get_thinking_processor() -> ThinkingPostProcessor:
    """
    Get singleton ThinkingPostProcessor instance.
    
    Returns:
        Shared ThinkingPostProcessor instance
    """
    global _processor
    if _processor is None:
        _processor = ThinkingPostProcessor()
        logger.info("✅ ThinkingPostProcessor initialized (CHỈ THỊ SỐ 29 v8)")
    return _processor
