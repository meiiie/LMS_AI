"""
Prompt Loader - Load persona configuration from YAML files.

CHỈ THỊ KỸ THUẬT SỐ 16: HUMANIZATION
- Tách biệt persona ra file YAML
- Few-shot prompting để dạy AI nói chuyện tự nhiên
- Hỗ trợ role-based prompting (student vs teacher/admin)

CHỈ THỊ KỸ THUẬT SỐ 20: PRONOUN ADAPTATION
- Phát hiện cách xưng hô từ user (mình/cậu, tớ/cậu, anh/em, chị/em)
- AI thích ứng xưng hô theo user
- Lọc bỏ xưng hô tục tĩu/nhạy cảm

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 16, 20**
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# PRONOUN ADAPTATION - CHỈ THỊ KỸ THUẬT SỐ 20
# =============================================================================

# Các cặp xưng hô hợp lệ (user_pronoun -> ai_pronoun)
VALID_PRONOUN_PAIRS = {
    # User xưng "mình" -> AI xưng "mình" và gọi user là "cậu"
    "mình": {"user_called": "cậu", "ai_self": "mình"},
    # User xưng "tớ" -> AI xưng "tớ" và gọi user là "cậu"
    "tớ": {"user_called": "cậu", "ai_self": "tớ"},
    # User xưng "em" -> AI xưng "anh/chị" và gọi user là "em"
    "em": {"user_called": "em", "ai_self": "anh"},  # Default to "anh", can be "chị"
    # User xưng "anh" -> AI xưng "em" và gọi user là "anh"
    "anh": {"user_called": "anh", "ai_self": "em"},
    # User xưng "chị" -> AI xưng "em" và gọi user là "chị"
    "chị": {"user_called": "chị", "ai_self": "em"},
    # User xưng "tôi" -> AI xưng "tôi" và gọi user là "bạn" (default)
    "tôi": {"user_called": "bạn", "ai_self": "tôi"},
    # User xưng "bạn" (gọi AI) -> AI xưng "tôi" và gọi user là "bạn"
    "bạn": {"user_called": "bạn", "ai_self": "tôi"},
}

# Từ xưng hô tục tĩu/nhạy cảm cần lọc bỏ
INAPPROPRIATE_PRONOUNS = [
    "mày", "tao", "đ.m", "dm", "vcl", "vl", "đéo", "địt",
    "con", "thằng", "đồ", "lũ", "bọn",  # Khi dùng một mình có thể xúc phạm
]


def detect_pronoun_style(message: str) -> Optional[Dict[str, str]]:
    """
    Detect user's pronoun style from their message.
    
    CHỈ THỊ KỸ THUẬT SỐ 20: Pronoun Adaptation
    
    Args:
        message: User's message text
        
    Returns:
        Dict with pronoun style info or None if not detected
        Example: {"user_self": "mình", "user_called": "cậu", "ai_self": "mình"}
        
    **Validates: Requirements 6.1, 6.4**
    """
    message_lower = message.lower()
    
    # Check for inappropriate pronouns first
    for bad_word in INAPPROPRIATE_PRONOUNS:
        if bad_word in message_lower:
            logger.warning(f"Inappropriate pronoun detected: {bad_word}")
            return None  # Reject and use default
    
    # Patterns to detect user's self-reference
    # Order matters: check more specific patterns first
    pronoun_patterns = [
        # "mình" patterns
        (r'\bmình\s+(?:là|tên|muốn|cần|hỏi|không|có|đang|sẽ|đã)', "mình"),
        (r'\bmình\b', "mình"),
        # "tớ" patterns
        (r'\btớ\s+(?:là|tên|muốn|cần|hỏi|không|có|đang|sẽ|đã)', "tớ"),
        (r'\btớ\b', "tớ"),
        # "em" patterns (user xưng em với AI)
        (r'\bem\s+(?:là|tên|muốn|cần|hỏi|không|có|đang|sẽ|đã|chào)', "em"),
        (r'^em\s+', "em"),  # Message starts with "em"
        # "anh" patterns (user gọi AI là anh)
        (r'(?:chào|cảm ơn|hỏi|nhờ)\s+anh\b', "anh"),
        (r'\banh\s+(?:ơi|à|nhé|giúp|chỉ)', "anh"),
        # "chị" patterns (user gọi AI là chị)
        (r'(?:chào|cảm ơn|hỏi|nhờ)\s+chị\b', "chị"),
        (r'\bchị\s+(?:ơi|à|nhé|giúp|chỉ)', "chị"),
        # "cậu" patterns (user gọi AI là cậu)
        (r'(?:chào|cảm ơn|hỏi|nhờ)\s+cậu\b', "mình"),  # If user calls AI "cậu", they use "mình"
        (r'\bcậu\s+(?:ơi|à|nhé|giúp|chỉ)', "mình"),
    ]
    
    for pattern, pronoun in pronoun_patterns:
        if re.search(pattern, message_lower):
            if pronoun in VALID_PRONOUN_PAIRS:
                style = VALID_PRONOUN_PAIRS[pronoun].copy()
                style["user_self"] = pronoun
                logger.info(f"Detected pronoun style: {style}")
                return style
    
    return None  # No specific style detected, use default


def get_pronoun_instruction(pronoun_style: Optional[Dict[str, str]]) -> str:
    """
    Generate instruction for AI to use adapted pronouns.
    
    Args:
        pronoun_style: Dict with pronoun style info
        
    Returns:
        Instruction string for system prompt
        
    **Validates: Requirements 6.2**
    """
    if not pronoun_style:
        return ""
    
    user_called = pronoun_style.get("user_called", "bạn")
    ai_self = pronoun_style.get("ai_self", "tôi")
    user_self = pronoun_style.get("user_self", "")
    
    instruction = f"""
--- CÁCH XƯNG HÔ ĐÃ THÍCH ỨNG ---
⚠️ QUAN TRỌNG: User đang xưng "{user_self}", hãy thích ứng theo:
- Gọi user là: "{user_called}"
- Tự xưng là: "{ai_self}"
- KHÔNG dùng "tôi/bạn" mặc định nữa
- Giữ nhất quán trong suốt cuộc hội thoại
"""
    return instruction


class PromptLoader:
    """
    Load and manage persona configurations from YAML files.
    
    Usage:
        loader = PromptLoader()
        prompt = loader.build_system_prompt("student")
    """
    
    def __init__(self, prompts_dir: Optional[str] = None):
        """
        Initialize PromptLoader.
        
        Args:
            prompts_dir: Path to prompts directory. Defaults to app/prompts/
        """
        if prompts_dir:
            self._prompts_dir = Path(prompts_dir)
        else:
            # Default: app/prompts/
            self._prompts_dir = Path(__file__).parent
        
        self._personas: Dict[str, Dict[str, Any]] = {}
        self._load_personas()
    
    def _load_personas(self) -> None:
        """Load all persona YAML files."""
        yaml_files = {
            "student": "tutor.yaml",
            "teacher": "assistant.yaml",
            "admin": "assistant.yaml"
        }
        
        # Log prompts directory for debugging deployment issues
        logger.info(f"PromptLoader: Looking for YAML files in {self._prompts_dir}")
        logger.info(f"PromptLoader: Directory exists: {self._prompts_dir.exists()}")
        
        if self._prompts_dir.exists():
            try:
                files_in_dir = list(self._prompts_dir.glob("*.yaml"))
                logger.info(f"PromptLoader: Found YAML files: {[f.name for f in files_in_dir]}")
            except Exception as e:
                logger.warning(f"PromptLoader: Could not list directory: {e}")
        
        loaded_count = 0
        for role, filename in yaml_files.items():
            filepath = self._prompts_dir / filename
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        self._personas[role] = yaml.safe_load(f)
                    logger.info(f"✅ Loaded persona for role '{role}' from {filename}")
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to load {filename}: {e}")
                    self._personas[role] = self._get_default_persona()
            else:
                logger.warning(f"⚠️ Persona file not found: {filepath} - using default")
                self._personas[role] = self._get_default_persona()
        
        logger.info(f"PromptLoader: Loaded {loaded_count}/{len(yaml_files)} persona files")
    
    def _get_default_persona(self) -> Dict[str, Any]:
        """Get default persona if YAML not found."""
        return {
            "role": "Maritime AI Assistant",
            "tone": ["Thân thiện", "Chuyên nghiệp"],
            "instructions": {},
            "few_shot_examples": []
        }
    
    def get_persona(self, role: str) -> Dict[str, Any]:
        """
        Get persona configuration for a role.
        
        Args:
            role: User role (student, teacher, admin)
            
        Returns:
            Persona configuration dict
        """
        return self._personas.get(role, self._personas.get("student", {}))
    
    def _replace_template_variables(
        self,
        text: str,
        user_name: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Replace template variables in text with actual values.
        
        Supported variables:
        - {{user_name}} -> User's name from Memory
        
        Args:
            text: Text containing template variables
            user_name: User's name to substitute
            **kwargs: Additional variables for future expansion
            
        Returns:
            Text with variables replaced
        """
        if not text:
            return text
        
        # Replace {{user_name}} with actual name or fallback
        if user_name:
            text = text.replace("{{user_name}}", user_name)
        else:
            # Fallback: remove the variable or use generic term
            text = text.replace("{{user_name}}", "bạn")
        
        # Future: Add more template variables here
        # text = text.replace("{{variable}}", value)
        
        return text
    
    def build_system_prompt(
        self,
        role: str,
        user_name: Optional[str] = None,
        conversation_summary: Optional[str] = None,
        user_facts: Optional[List[str]] = None,
        recent_phrases: Optional[List[str]] = None,
        is_follow_up: bool = False,
        name_usage_count: int = 0,
        total_responses: int = 0,
        pronoun_style: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Build system prompt from persona configuration.
        
        Supports both tutor.yaml and assistant.yaml formats with full YAML structure.
        
        Args:
            role: User role (student, teacher, admin)
            user_name: User's name if known (from Memory)
            conversation_summary: Summary of previous conversation
            user_facts: List of known facts about user
            recent_phrases: List of recently used opening phrases (for variation)
            is_follow_up: True if this is a follow-up message (not first in session)
            name_usage_count: Number of times user's name has been used
            total_responses: Total number of responses in session
            pronoun_style: Dict with adapted pronoun style (CHỈ THỊ SỐ 20)
            
        Returns:
            Complete system prompt string with template variables replaced
            
        **Validates: Requirements 1.2, 7.1, 7.3, 6.2**
        """
        persona = self.get_persona(role)
        
        # Build prompt sections
        sections = []
        
        # ============================================================
        # CRITICAL RULE AT THE TOP (Most important - LLM sees this first)
        # ============================================================
        sections.append("=" * 60)
        sections.append("⛔ QUY TẮC TUYỆT ĐỐI - ĐỌC TRƯỚC KHI TRẢ LỜI ⛔")
        sections.append("=" * 60)
        sections.append("KHÔNG BAO GIỜ bắt đầu câu trả lời bằng 'À,' hoặc 'À, ' hoặc 'À '")
        sections.append("Thay vào đó, bắt đầu trực tiếp bằng:")
        sections.append("  - '**Quy tắc X** - ...'")
        sections.append("  - 'Tiếp tục với **Quy tắc X**...'")
        sections.append("  - 'Nói về **Quy tắc X**...'")
        sections.append("  - 'Chuyển sang **Quy tắc X**...'")
        sections.append("=" * 60)
        sections.append("")
        
        # ============================================================
        # PROFILE SECTION (from YAML profile.*)
        # ============================================================
        profile = persona.get('profile', {})
        if profile:
            profile_name = profile.get('name', 'Maritime AI')
            profile_role = profile.get('role', 'Assistant')
            sections.append(f"Bạn là **{profile_name}** - {profile_role}.")
            
            if profile.get('backstory'):
                sections.append(f"\n{profile['backstory'].strip()}")
        else:
            # Fallback for old format
            role_name = persona.get('role', 'Maritime AI Assistant')
            sections.append(f"Bạn là {role_name}.")
            if persona.get('description'):
                sections.append(persona['description'])
        
        # ============================================================
        # STYLE SECTION (from YAML style.*)
        # ============================================================
        style = persona.get('style', {})
        
        # Tone
        tone = style.get('tone') or persona.get('tone', [])
        if tone:
            sections.append("\nGIỌNG VĂN:")
            for t in tone:
                sections.append(f"- {t}")
        
        # Formatting rules
        formatting = style.get('formatting', [])
        if formatting:
            sections.append("\nĐỊNH DẠNG:")
            for f in formatting:
                sections.append(f"- {f}")
        
        # Addressing rules (for assistant.yaml)
        addressing = style.get('addressing_rules', [])
        if addressing:
            sections.append("\nCÁCH XƯNG HÔ:")
            for a in addressing:
                sections.append(f"- {a}")
        
        # ============================================================
        # THOUGHT PROCESS (from YAML thought_process.*)
        # ============================================================
        thought_process = persona.get('thought_process', {})
        if thought_process:
            sections.append("\nQUY TRÌNH SUY NGHĨ (Trước khi trả lời):")
            for step, instruction in thought_process.items():
                # Format: "1_analyze" -> "1. analyze"
                step_num = step.split('_')[0] if '_' in step else step
                sections.append(f"{step_num}. {instruction}")
        
        # ============================================================
        # DIRECTIVES SECTION (from YAML directives.*)
        # ============================================================
        directives = persona.get('directives', {})
        if directives:
            if directives.get('dos'):
                sections.append("\nNÊN LÀM:")
                for rule in directives['dos']:
                    # Replace template variables like {{user_name}}
                    rule = self._replace_template_variables(rule, user_name)
                    sections.append(f"- {rule}")
            
            if directives.get('donts'):
                sections.append("\nKHÔNG NÊN:")
                for rule in directives['donts']:
                    sections.append(f"- {rule}")
        
        # Instructions (legacy format)
        instructions = persona.get('instructions', {})
        if instructions:
            sections.append("\nQUY TẮC ỨNG XỬ:")
            for category, rules in instructions.items():
                if isinstance(rules, list):
                    for rule in rules:
                        sections.append(f"- {rule}")
        
        # ============================================================
        # USER CONTEXT (from Memory - CRITICAL for personalization)
        # ============================================================
        if user_name or user_facts:
            sections.append("\n--- THÔNG TIN NGƯỜI DÙNG (từ Memory) ---")
            if user_name:
                sections.append(f"- Tên: **{user_name}**")
            if user_facts:
                for fact in user_facts[:5]:  # Limit to 5 facts
                    sections.append(f"- {fact}")
        
        # ============================================================
        # CONVERSATION SUMMARY (from MemorySummarizer)
        # ============================================================
        if conversation_summary:
            sections.append(f"\n--- TÓM TẮT HỘI THOẠI TRƯỚC ---\n{conversation_summary}")
        
        # ============================================================
        # VARIATION INSTRUCTIONS (Anti-repetition)
        # Spec: ai-response-quality, Requirements 7.1, 7.3
        # ============================================================
        if recent_phrases or is_follow_up or total_responses > 0:
            sections.append("\n--- HƯỚNG DẪN ĐA DẠNG HÓA (VARIATION) ---")
            
            # Follow-up instruction
            if is_follow_up:
                sections.append("- Đây là tin nhắn FOLLOW-UP, KHÔNG chào hỏi lại.")
            
            # Name usage instruction (20-30% frequency)
            if user_name and total_responses > 0:
                name_ratio = name_usage_count / total_responses if total_responses > 0 else 0
                if name_ratio >= 0.3:
                    sections.append(f"- KHÔNG dùng tên '{user_name}' trong response này (đã dùng đủ rồi).")
                elif name_ratio < 0.2:
                    sections.append(f"- Có thể dùng tên '{user_name}' một cách tự nhiên.")
            
            # Phrases to avoid - CRITICAL for anti-repetition
            if recent_phrases:
                sections.append("\n⚠️ CÁC CÁCH MỞ ĐẦU BẠN ĐÃ DÙNG GẦN ĐÂY:")
                for i, phrase in enumerate(recent_phrases[-3:], 1):
                    sections.append(f"  {i}. \"{phrase[:40]}...\"")
                sections.append("→ KHÔNG được bắt đầu response bằng các pattern tương tự!")
                sections.append("→ Hãy dùng cách mở đầu KHÁC BIỆT hoàn toàn.")
        
        # ============================================================
        # CRITICAL: ADDRESSING RULES (Cách xưng hô - CHỈ THỊ SỐ 20)
        # ============================================================
        if pronoun_style:
            # User đã có pronoun style được detect -> thích ứng theo
            pronoun_instruction = get_pronoun_instruction(pronoun_style)
            sections.append(pronoun_instruction)
        elif role == "student":
            # Mặc định cho student role
            sections.append("\n--- CÁCH XƯNG HÔ MẶC ĐỊNH ---")
            sections.append("- Gọi người dùng là 'bạn' (lịch sự, thân thiện)")
            sections.append("- Tự xưng là 'tôi'")
            sections.append("- Nếu người dùng dùng cách xưng hô khác (mình/cậu, em/anh...) thì THÍCH ỨNG THEO")
            sections.append("- KHÔNG cứng nhắc giữ 'tôi/bạn' nếu user đã đổi cách xưng hô")
        
        # ============================================================
        # CRITICAL: ANTI-REPETITION RULES (QUAN TRỌNG NHẤT)
        # ============================================================
        sections.append("\n" + "="*60)
        sections.append("⚠️ QUY TẮC BẮT BUỘC - KHÔNG ĐƯỢC VI PHẠM ⚠️")
        sections.append("="*60)
        sections.append("1. TUYỆT ĐỐI KHÔNG bắt đầu câu trả lời bằng 'À,' hoặc 'À, ' hoặc 'À '")
        sections.append("   - Đây là thói quen XẤU, nghe không chuyên nghiệp")
        sections.append("   - Thay vào đó, bắt đầu trực tiếp bằng tên quy tắc hoặc nội dung")
        sections.append("2. Khi trả lời nhiều câu hỏi liên tiếp về quy tắc:")
        sections.append("   - Câu 1: Bắt đầu bằng '**Quy tắc X** - ...' hoặc 'Về vấn đề này...'")
        sections.append("   - Câu 2: Bắt đầu bằng 'Quy tắc này cũng quan trọng...' hoặc 'Tiếp theo...'")
        sections.append("   - Câu 3: Bắt đầu bằng 'Nói về **Quy tắc X**...' hoặc 'Chuyển sang...'")
        sections.append("3. KHÔNG lặp lại cùng một cách mở đầu trong 3 câu liên tiếp")
        sections.append("="*60)
        
        # ============================================================
        # TOOLS INSTRUCTION (Required for ReAct Agent)
        # ============================================================
        sections.append("\n--- SỬ DỤNG CÔNG CỤ (TOOLS) ---")
        sections.append("- Hỏi về luật hàng hải, quy tắc, tàu biển -> BẮT BUỘC gọi `tool_maritime_search`. ĐỪNG bịa.")
        sections.append("- User giới thiệu tên/tuổi/trường/nghề -> Gọi `tool_save_user_info` để ghi nhớ.")
        sections.append("- Cần biết tên user -> Gọi `tool_get_user_info`.")
        sections.append("- Chào hỏi xã giao, than vãn -> Trả lời trực tiếp, KHÔNG cần tool.")
        
        # ============================================================
        # FEW-SHOT EXAMPLES (from YAML few_shot_examples)
        # ============================================================
        examples = persona.get('few_shot_examples', [])
        if examples:
            sections.append("\n--- VÍ DỤ CÁCH TRẢ LỜI ---")
            for ex in examples[:4]:  # Limit to 4 examples
                context = ex.get('context', '')
                user_msg = ex.get('user', '')
                ai_msg = ex.get('ai', '')
                if user_msg and ai_msg:
                    sections.append(f"\n[{context}]")
                    sections.append(f"User: {user_msg}")
                    sections.append(f"AI: {ai_msg}")
        
        return "\n".join(sections)
    
    def get_fact_extraction_hints(self, role: str) -> Dict[str, List[str]]:
        """
        Get hints for fact extraction (what to extract vs ignore).
        
        Args:
            role: User role
            
        Returns:
            Dict with 'extract' and 'ignore' lists
        """
        persona = self.get_persona(role)
        memory_hints = persona.get('memory_hints', {})
        
        return {
            "extract": memory_hints.get('extract_facts', []),
            "ignore": memory_hints.get('ignore_facts', [])
        }
    
    # =========================================================================
    # ENHANCED METHODS - AI Response Quality Improvement
    # Spec: ai-response-quality, Requirements 1.2, 7.1
    # =========================================================================
    
    def detect_empathy_needed(self, message: str, role: str = "student") -> bool:
        """
        Detect if user message requires empathy-first response.
        
        Checks message against empathy_patterns defined in YAML.
        
        Args:
            message: User's message text
            role: User role to get correct persona
            
        Returns:
            True if empathy response is needed
            
        **Validates: Requirements 1.2**
        """
        persona = self.get_persona(role)
        empathy_patterns = persona.get('empathy_patterns', {})
        
        if not empathy_patterns:
            return False
        
        message_lower = message.lower()
        
        # Check frustration keywords
        frustration_keywords = empathy_patterns.get('frustration_keywords', [])
        for keyword in frustration_keywords:
            if keyword.lower() in message_lower:
                logger.debug(f"Empathy needed: frustration keyword '{keyword}' detected")
                return True
        
        # Check basic needs keywords
        basic_needs = empathy_patterns.get('basic_needs_keywords', [])
        for keyword in basic_needs:
            if keyword.lower() in message_lower:
                logger.debug(f"Empathy needed: basic need '{keyword}' detected")
                return True
        
        # Check work pressure keywords (for teacher/admin)
        work_pressure = empathy_patterns.get('work_pressure_keywords', [])
        for keyword in work_pressure:
            if keyword.lower() in message_lower:
                logger.debug(f"Empathy needed: work pressure '{keyword}' detected")
                return True
        
        return False
    
    def get_variation_phrases(
        self,
        role: str,
        category: str,
        subcategory: Optional[str] = None
    ) -> List[str]:
        """
        Get alternative phrases for a category to avoid repetition.
        
        Args:
            role: User role (student, teacher, admin)
            category: Phrase category (openings, transitions, closings)
            subcategory: Optional subcategory (knowledge, follow_up, empathy)
            
        Returns:
            List of alternative phrases
            
        **Validates: Requirements 7.1**
        """
        persona = self.get_persona(role)
        variation_phrases = persona.get('variation_phrases', {})
        
        if not variation_phrases:
            return []
        
        phrases = variation_phrases.get(category, {})
        
        if subcategory and isinstance(phrases, dict):
            return phrases.get(subcategory, [])
        elif isinstance(phrases, list):
            return phrases
        
        return []
    
    def get_random_opening(
        self,
        role: str,
        context_type: str = "knowledge",
        exclude_phrases: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Get a random opening phrase, excluding recently used ones.
        
        Args:
            role: User role
            context_type: Type of response (knowledge, follow_up, empathy)
            exclude_phrases: List of recently used phrases to avoid
            
        Returns:
            A phrase not in exclude_phrases, or None if all exhausted
        """
        import random
        
        phrases = self.get_variation_phrases(role, "openings", context_type)
        
        if not phrases:
            return None
        
        if exclude_phrases:
            available = [p for p in phrases if p not in exclude_phrases]
            if available:
                return random.choice(available)
        
        return random.choice(phrases)
    
    def get_empathy_response_template(
        self,
        role: str,
        empathy_type: str = "frustration"
    ) -> Optional[str]:
        """
        Get empathy response template from YAML.
        
        Args:
            role: User role
            empathy_type: Type of empathy (frustration, basic_needs, encouragement, urgent, busy)
            
        Returns:
            Response template string with placeholders
        """
        persona = self.get_persona(role)
        empathy_patterns = persona.get('empathy_patterns', {})
        empathy_responses = empathy_patterns.get('empathy_responses', {})
        
        return empathy_responses.get(empathy_type)
    
    def reload(self) -> None:
        """Reload all persona files."""
        self._personas = {}
        self._load_personas()
        logger.info("Reloaded all persona configurations")


# Singleton instance
_prompt_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """Get or create PromptLoader singleton."""
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = PromptLoader()
    return _prompt_loader
