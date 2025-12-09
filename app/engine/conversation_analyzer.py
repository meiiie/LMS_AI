"""
Conversation Analyzer - Deep Reasoning & Context Understanding

CHỈ THỊ KỸ THUẬT SỐ 21: DEEP REASONING & SMART CONTEXT ENGINE

Phân tích ngữ cảnh hội thoại để:
1. Nhận diện câu hỏi mơ hồ (ambiguous questions)
2. Liên kết với chủ đề đang thảo luận
3. Phát hiện giải thích dở dang (incomplete explanations)
4. Gợi ý proactive behavior cho AI

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 21**
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class QuestionType(str, Enum):
    """Types of questions based on context dependency."""
    STANDALONE = "standalone"  # Câu hỏi độc lập, đủ ngữ cảnh
    FOLLOW_UP = "follow_up"    # Câu hỏi nối tiếp, cần ngữ cảnh trước
    AMBIGUOUS = "ambiguous"    # Câu hỏi mơ hồ, cần suy luận ngữ cảnh
    CLARIFICATION = "clarification"  # Yêu cầu làm rõ


@dataclass
class ConversationContext:
    """
    Context extracted from conversation history.
    
    Provides hints for AI to understand ambiguous questions.
    """
    # Current topic being discussed
    current_topic: Optional[str] = None
    
    # Last explanation topic (for proactive behavior)
    last_explanation_topic: Optional[str] = None
    
    # Whether AI was explaining something and got interrupted
    should_offer_continuation: bool = False
    
    # Keywords from recent messages
    recent_keywords: List[str] = field(default_factory=list)
    
    # Question type detected
    question_type: QuestionType = QuestionType.STANDALONE
    
    # Inferred context for ambiguous questions
    inferred_context: Optional[str] = None
    
    # Confidence in context inference (0-1)
    confidence: float = 0.0
    
    # Proactive hints for AI
    proactive_hints: List[str] = field(default_factory=list)


class ConversationAnalyzer:
    """
    Analyzes conversation history to provide context for ambiguous questions.
    
    CHỈ THỊ KỸ THUẬT SỐ 21: Deep Reasoning Support
    
    Key features:
    1. Detect ambiguous/follow-up questions
    2. Extract current topic from conversation
    3. Provide context hints for AI reasoning
    4. Detect incomplete explanations for proactive behavior
    """
    
    # Patterns indicating follow-up/ambiguous questions
    FOLLOW_UP_PATTERNS = [
        r"^còn\s+",           # "Còn X thì sao?"
        r"^thế\s+",           # "Thế X thì sao?"
        r"^vậy\s+",           # "Vậy X thì sao?"
        r"^rồi\s+",           # "Rồi X thì sao?"
        r"\s+thì sao\??$",    # "X thì sao?"
        r"\s+thì thế nào\??$", # "X thì thế nào?"
        r"^cần\s+",           # "Cần gì?" (ambiguous)
        r"^phí\s+",           # "Phí bao nhiêu?" (ambiguous)
        r"^bao nhiêu\??$",    # "Bao nhiêu?"
        r"^những gì\??$",     # "Những gì?"
        r"^gì\??$",           # "Gì?"
        r"^sao\??$",          # "Sao?"
    ]
    
    # Patterns indicating standalone questions
    STANDALONE_PATTERNS = [
        r"quy tắc\s+\d+",     # "Quy tắc 15"
        r"rule\s+\d+",        # "Rule 15"
        r"điều\s+\d+",        # "Điều 15"
        r"colregs",           # COLREGs
        r"solas",             # SOLAS
        r"marpol",            # MARPOL
        r"là gì\??$",         # "X là gì?"
        r"giải thích",        # "Giải thích X"
        r"cho biết",          # "Cho biết X"
    ]
    
    # Maritime topic keywords
    MARITIME_TOPICS = {
        "navigation_lights": ["đèn", "đèn đỏ", "đèn xanh", "đèn trắng", "đèn vàng", "tín hiệu", "mạn"],
        "ship_registration": ["đăng ký", "tàu biển", "giấy tờ", "hồ sơ", "thủ tục", "phí", "lệ phí"],
        "colregs_rules": ["quy tắc", "rule", "colregs", "tránh va", "nhường đường"],
        "safety": ["an toàn", "solas", "cứu sinh", "cứu hỏa", "phòng cháy"],
        "pollution": ["ô nhiễm", "marpol", "dầu", "rác thải", "nước thải"],
        "navigation": ["hành trình", "hải đồ", "định vị", "gps", "radar"],
    }
    
    def __init__(self):
        """Initialize analyzer."""
        self._compiled_follow_up = [re.compile(p, re.IGNORECASE) for p in self.FOLLOW_UP_PATTERNS]
        self._compiled_standalone = [re.compile(p, re.IGNORECASE) for p in self.STANDALONE_PATTERNS]
        logger.info("ConversationAnalyzer initialized")
    
    def analyze(self, messages: List[Any]) -> ConversationContext:
        """
        Analyze conversation history and extract context.
        
        Args:
            messages: List of message objects with 'role' and 'content' attributes
            
        Returns:
            ConversationContext with extracted information
        """
        context = ConversationContext()
        
        if not messages:
            return context
        
        # Get last user message
        last_user_msg = None
        for msg in reversed(messages):
            role = getattr(msg, 'role', msg.get('role', '')) if isinstance(msg, dict) else msg.role
            if role == "user":
                last_user_msg = getattr(msg, 'content', msg.get('content', '')) if isinstance(msg, dict) else msg.content
                break
        
        if not last_user_msg:
            return context
        
        # Detect question type
        context.question_type = self._detect_question_type(last_user_msg)
        
        # Extract current topic from conversation
        context.current_topic = self._extract_current_topic(messages)
        
        # Extract keywords from recent messages
        context.recent_keywords = self._extract_keywords(messages[-6:])  # Last 3 exchanges
        
        # If ambiguous, try to infer context
        if context.question_type in [QuestionType.AMBIGUOUS, QuestionType.FOLLOW_UP]:
            context.inferred_context = self._infer_context(last_user_msg, messages)
            context.confidence = self._calculate_confidence(context)
            
            # Add proactive hints
            if context.current_topic:
                context.proactive_hints.append(
                    f"Câu hỏi này có thể liên quan đến chủ đề '{context.current_topic}' đang thảo luận."
                )
        
        # Check for incomplete explanations
        context.should_offer_continuation, context.last_explanation_topic = \
            self._detect_incomplete_explanation(messages)
        
        logger.info(f"[ANALYZER] Question type: {context.question_type.value}, "
                   f"Topic: {context.current_topic}, "
                   f"Confidence: {context.confidence:.2f}")
        
        return context
    
    def _detect_question_type(self, message: str) -> QuestionType:
        """Detect the type of question based on patterns."""
        message_lower = message.lower().strip()
        
        # Check for follow-up/ambiguous patterns FIRST (higher priority)
        # These patterns indicate the question depends on previous context
        for pattern in self._compiled_follow_up:
            if pattern.search(message_lower):
                # Short messages are more likely ambiguous
                if len(message_lower.split()) <= 6:
                    return QuestionType.AMBIGUOUS
                return QuestionType.FOLLOW_UP
        
        # Check for standalone patterns
        for pattern in self._compiled_standalone:
            if pattern.search(message_lower):
                return QuestionType.STANDALONE
        
        # Very short messages are likely ambiguous
        if len(message_lower.split()) <= 3:
            return QuestionType.AMBIGUOUS
        
        return QuestionType.STANDALONE
    
    def _extract_current_topic(self, messages: List[Any]) -> Optional[str]:
        """Extract the current topic being discussed."""
        # Look at recent messages for topic keywords
        recent_text = ""
        for msg in messages[-6:]:  # Last 3 exchanges
            content = getattr(msg, 'content', msg.get('content', '')) if isinstance(msg, dict) else msg.content
            recent_text += " " + content.lower()
        
        # Find matching topics
        topic_scores = {}
        for topic, keywords in self.MARITIME_TOPICS.items():
            score = sum(1 for kw in keywords if kw in recent_text)
            if score > 0:
                topic_scores[topic] = score
        
        if topic_scores:
            # Return topic with highest score
            best_topic = max(topic_scores, key=topic_scores.get)
            return best_topic
        
        return None
    
    def _extract_keywords(self, messages: List[Any]) -> List[str]:
        """Extract important keywords from recent messages."""
        keywords = []
        
        for msg in messages:
            content = getattr(msg, 'content', msg.get('content', '')) if isinstance(msg, dict) else msg.content
            content_lower = content.lower()
            
            # Extract maritime keywords
            for topic_keywords in self.MARITIME_TOPICS.values():
                for kw in topic_keywords:
                    if kw in content_lower and kw not in keywords:
                        keywords.append(kw)
        
        return keywords[:10]  # Limit to 10 keywords
    
    def _infer_context(self, current_message: str, messages: List[Any]) -> Optional[str]:
        """
        Infer context for ambiguous questions.
        
        This is the key function for understanding follow-up questions.
        """
        if len(messages) < 2:
            return None
        
        # Get the previous user message and AI response
        prev_user_msg = None
        prev_ai_msg = None
        
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            role = getattr(msg, 'role', msg.get('role', '')) if isinstance(msg, dict) else msg.role
            content = getattr(msg, 'content', msg.get('content', '')) if isinstance(msg, dict) else msg.content
            
            if role == "assistant" and prev_ai_msg is None:
                prev_ai_msg = content
            elif role == "user" and prev_user_msg is None and content.lower() != current_message.lower():
                prev_user_msg = content
                break
        
        if not prev_user_msg:
            return None
        
        # Build inferred context
        current_lower = current_message.lower()
        
        # Pattern: "Còn X thì sao?" -> X is related to previous topic
        if any(p.search(current_lower) for p in self._compiled_follow_up):
            # Extract what user is asking about
            # E.g., "Còn đèn xanh thì sao?" -> "đèn xanh"
            # E.g., "Cần những giấy tờ gì?" -> "giấy tờ" related to previous topic
            
            inferred = f"Câu hỏi này nối tiếp từ câu hỏi trước: '{prev_user_msg[:100]}'. "
            
            # Add topic context
            topic = self._extract_current_topic(messages)
            if topic:
                topic_name = {
                    "navigation_lights": "đèn tín hiệu hàng hải",
                    "ship_registration": "đăng ký tàu biển",
                    "colregs_rules": "quy tắc COLREGs",
                    "safety": "an toàn hàng hải",
                    "pollution": "phòng chống ô nhiễm",
                    "navigation": "hành trình",
                }.get(topic, topic)
                
                inferred += f"Chủ đề đang thảo luận: {topic_name}."
            
            return inferred
        
        return None
    
    def _calculate_confidence(self, context: ConversationContext) -> float:
        """Calculate confidence in context inference."""
        confidence = 0.0
        
        # Has current topic
        if context.current_topic:
            confidence += 0.4
        
        # Has inferred context
        if context.inferred_context:
            confidence += 0.3
        
        # Has recent keywords
        if len(context.recent_keywords) >= 3:
            confidence += 0.2
        elif len(context.recent_keywords) >= 1:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _detect_incomplete_explanation(self, messages: List[Any]) -> tuple[bool, Optional[str]]:
        """
        Detect if AI was explaining something and got interrupted.
        
        Returns:
            (should_offer_continuation, last_explanation_topic)
        """
        if len(messages) < 3:
            return False, None
        
        # Look for patterns indicating incomplete explanation
        # E.g., AI was explaining Rule 15, user asked about something else
        
        last_ai_msg = None
        for msg in reversed(messages[:-1]):  # Exclude current message
            role = getattr(msg, 'role', msg.get('role', '')) if isinstance(msg, dict) else msg.role
            if role == "assistant":
                last_ai_msg = getattr(msg, 'content', msg.get('content', '')) if isinstance(msg, dict) else msg.content
                break
        
        if not last_ai_msg:
            return False, None
        
        # Check if AI was explaining something
        explanation_patterns = [
            r"quy tắc\s+(\d+)",
            r"rule\s+(\d+)",
            r"điều\s+(\d+)",
            r"về\s+(.+?)(?:\.|,|:)",
        ]
        
        for pattern in explanation_patterns:
            match = re.search(pattern, last_ai_msg.lower())
            if match:
                topic = match.group(1) if match.lastindex else match.group(0)
                # Check if current question is about a different topic
                # (This is a simplified check)
                return True, topic
        
        return False, None
    
    def build_context_prompt(self, context: ConversationContext) -> str:
        """
        Build a context prompt to inject into AI's thinking.
        
        This helps AI understand ambiguous questions.
        """
        if context.question_type == QuestionType.STANDALONE:
            return ""
        
        prompt_parts = []
        
        prompt_parts.append("[CONTEXT ANALYSIS]")
        
        if context.question_type == QuestionType.AMBIGUOUS:
            prompt_parts.append("⚠️ Đây là câu hỏi MƠ HỒ, cần suy luận từ ngữ cảnh hội thoại.")
        elif context.question_type == QuestionType.FOLLOW_UP:
            prompt_parts.append("📎 Đây là câu hỏi NỐI TIẾP từ chủ đề trước.")
        
        if context.inferred_context:
            prompt_parts.append(f"💡 Suy luận: {context.inferred_context}")
        
        if context.current_topic:
            prompt_parts.append(f"📌 Chủ đề hiện tại: {context.current_topic}")
        
        if context.recent_keywords:
            prompt_parts.append(f"🔑 Từ khóa gần đây: {', '.join(context.recent_keywords[:5])}")
        
        if context.proactive_hints:
            for hint in context.proactive_hints:
                prompt_parts.append(f"💬 {hint}")
        
        prompt_parts.append("[/CONTEXT ANALYSIS]")
        
        return "\n".join(prompt_parts)


# Singleton
_conversation_analyzer: Optional[ConversationAnalyzer] = None


def get_conversation_analyzer() -> ConversationAnalyzer:
    """Get or create ConversationAnalyzer singleton."""
    global _conversation_analyzer
    if _conversation_analyzer is None:
        _conversation_analyzer = ConversationAnalyzer()
    return _conversation_analyzer
