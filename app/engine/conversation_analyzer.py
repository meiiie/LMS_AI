"""
Conversation Analyzer - Deep Reasoning Support.

This module analyzes conversation history to detect incomplete explanations
and provide proactive continuation suggestions.

**CHỈ THỊ KỸ THUẬT SỐ 21: Deep Reasoning & Smart Context Engine**
**Validates: Requirements 3.1, 3.4, 3.5**
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """
    Context analysis for proactive AI behavior.
    
    **CHỈ THỊ SỐ 21: Deep Reasoning - Proactive Behavior**
    """
    incomplete_explanations: List[str] = field(default_factory=list)
    last_explanation_topic: Optional[str] = None
    user_interrupted: bool = False
    should_offer_continuation: bool = False
    current_topic: Optional[str] = None
    user_facts: Dict[str, Any] = field(default_factory=dict)


class ConversationAnalyzer:
    """
    Analyzes conversation for incomplete topics and context.
    
    **CHỈ THỊ KỸ THUẬT SỐ 21: Deep Reasoning & Smart Context Engine**
    **Validates: Requirements 3.1, 3.4, 3.5**
    """
    
    # Maritime-specific topic patterns
    MARITIME_PATTERNS = [
        r"Rule\s+(\d+)",  # "Rule 5", "Rule 15"
        r"Quy tắc\s+(\d+)",  # "Quy tắc 5"
        r"(COLREGs?)",  # COLREGs
        r"(SOLAS)",  # SOLAS
        r"(MARPOL)",  # MARPOL
        r"(STCW)",  # STCW
        r"(ISM\s*Code)",  # ISM Code
        r"(MLC)",  # Maritime Labour Convention
        r"Điều\s+(\d+)",  # "Điều 15"
        r"Chương\s+(\d+)",  # "Chương 5"
    ]
    
    # Indicators of incomplete explanations
    INCOMPLETE_INDICATORS = [
        "tiếp tục", "phần tiếp theo", "sẽ giải thích thêm", "còn nữa",
        "đang nói về", "như tôi đã đề cập", "sẽ nói thêm về",
        "ngoài ra", "bên cạnh đó", "thêm vào đó", "hơn nữa",
        "đầu tiên", "thứ nhất", "một là", "trước hết",
        "...", "v.v.", "etc."
    ]
    
    # Continuation request phrases
    CONTINUATION_PHRASES = [
        "tiếp tục", "nói tiếp", "giải thích thêm", "còn gì nữa",
        "và sau đó", "rồi sao", "thế còn", "vậy thì",
        "tiếp đi", "kể tiếp", "nói thêm", "chi tiết hơn"
    ]
    
    def analyze(self, messages: List[Any]) -> ConversationContext:
        """
        Analyze conversation history for incomplete explanations and context.
        
        Args:
            messages: List of ChatMessage objects
            
        Returns:
            ConversationContext with analysis results
        """
        context = ConversationContext()
        
        if not messages:
            return context
        
        try:
            # Analyze messages for incomplete explanations
            for i, msg in enumerate(messages):
                if not hasattr(msg, 'role') or not hasattr(msg, 'content'):
                    continue
                    
                if msg.role == "assistant":
                    content = msg.content
                    
                    # Check if explanation was incomplete
                    if self.detect_incomplete_explanation(content):
                        topic = self.extract_topic(content)
                        if topic:
                            context.incomplete_explanations.append(topic)
                            context.last_explanation_topic = topic
                            
                            # Check if user interrupted with new question
                            if i + 1 < len(messages):
                                next_msg = messages[i + 1]
                                if hasattr(next_msg, 'role') and next_msg.role == "user":
                                    if not self.is_continuation_request(next_msg.content, topic):
                                        context.user_interrupted = True
            
            # Determine if we should offer continuation
            context.should_offer_continuation = bool(
                context.last_explanation_topic and context.user_interrupted
            )
            
            # Extract current topic from last user message
            if messages:
                last_user_msg = None
                for msg in reversed(messages):
                    if hasattr(msg, 'role') and msg.role == "user":
                        last_user_msg = msg
                        break
                
                if last_user_msg:
                    context.current_topic = self.extract_topic(last_user_msg.content)
            
            logger.debug(f"Conversation analysis: incomplete={len(context.incomplete_explanations)}, "
                        f"should_continue={context.should_offer_continuation}")
            
        except Exception as e:
            logger.error(f"Error analyzing conversation: {e}")
        
        return context
    
    def detect_incomplete_explanation(self, content: str) -> bool:
        """
        Check if an AI response contains an incomplete explanation.
        
        **CHỈ THỊ 21: Detect when AI was explaining something but didn't finish.**
        
        Args:
            content: AI response content
            
        Returns:
            True if explanation appears incomplete
        """
        if not content:
            return False
        
        content_lower = content.lower()
        
        # Check for incomplete indicators
        for indicator in self.INCOMPLETE_INDICATORS:
            if indicator.lower() in content_lower:
                return True
        
        # Check if content ends abruptly
        if len(content) > 100:
            # Ends with ellipsis
            if content.rstrip().endswith("..."):
                return True
            
            # Ends without proper punctuation
            last_char = content.rstrip()[-1] if content.rstrip() else ""
            if last_char not in ".!?:;)]}\"'":
                return True
        
        # Check for numbered lists that might be incomplete
        # e.g., "1. First point" without "2. Second point"
        numbered_pattern = r"^\s*(\d+)\.\s+"
        matches = re.findall(numbered_pattern, content, re.MULTILINE)
        if matches:
            numbers = [int(m) for m in matches]
            if numbers and max(numbers) == 1:
                # Only has "1." - might be incomplete
                return True
        
        return False
    
    def extract_topic(self, content: str) -> Optional[str]:
        """
        Extract the main topic being discussed from content.
        
        **CHỈ THỊ 21: Identify what topic the AI was explaining.**
        
        Args:
            content: Message content
            
        Returns:
            Extracted topic or None
        """
        if not content:
            return None
        
        # Try maritime-specific patterns first
        for pattern in self.MARITIME_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                # Return the full match or first group
                return match.group(0)
        
        # Fallback: extract first significant phrase
        # Look for quoted terms or bold terms
        quoted = re.search(r'"([^"]+)"', content)
        if quoted:
            return quoted.group(1)
        
        bold = re.search(r'\*\*([^*]+)\*\*', content)
        if bold:
            return bold.group(1)
        
        # Last resort: first few words
        words = content.split()
        if len(words) >= 3:
            return " ".join(words[:3])
        
        return None
    
    def is_continuation_request(self, user_message: str, topic: str) -> bool:
        """
        Check if user's message is asking to continue the previous topic.
        
        **CHỈ THỊ 21: Detect if user wants to continue vs asking new question.**
        
        Args:
            user_message: User's message
            topic: Previous topic being discussed
            
        Returns:
            True if user is asking to continue
        """
        if not user_message:
            return False
        
        user_lower = user_message.lower()
        
        # Check for direct continuation phrases
        for phrase in self.CONTINUATION_PHRASES:
            if phrase in user_lower:
                return True
        
        # Check if user mentions the same topic
        if topic:
            topic_lower = topic.lower()
            if topic_lower in user_lower:
                return True
            
            # Check for partial topic match (e.g., "Rule 15" -> "15")
            topic_numbers = re.findall(r'\d+', topic)
            for num in topic_numbers:
                if num in user_message:
                    return True
        
        return False
    
    def build_proactive_context(self, context: ConversationContext) -> str:
        """
        Build proactive context string for injection into AI prompt.
        
        Args:
            context: ConversationContext from analysis
            
        Returns:
            Proactive context string for <thinking> section
        """
        if not context.should_offer_continuation:
            return ""
        
        topic = context.last_explanation_topic
        return (
            f"\n<thinking>\n"
            f"User asked a new question, but I was previously explaining '{topic}' "
            f"and didn't finish. After answering their current question, "
            f"I should ask if they want me to continue explaining '{topic}'.\n"
            f"</thinking>\n"
        )


# Singleton instance
_conversation_analyzer: Optional[ConversationAnalyzer] = None


def get_conversation_analyzer() -> ConversationAnalyzer:
    """Get or create ConversationAnalyzer singleton."""
    global _conversation_analyzer
    if _conversation_analyzer is None:
        _conversation_analyzer = ConversationAnalyzer()
    return _conversation_analyzer
