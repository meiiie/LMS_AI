"""
Prompt Loader - Load persona configuration from YAML files.

CHỈ THỊ KỸ THUẬT SỐ 16: HUMANIZATION
- Tách biệt persona ra file YAML
- Few-shot prompting để dạy AI nói chuyện tự nhiên
- Hỗ trợ role-based prompting (student vs teacher/admin)

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 16**
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

logger = logging.getLogger(__name__)


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
        user_facts: Optional[List[str]] = None
    ) -> str:
        """
        Build system prompt from persona configuration.
        
        Supports both tutor.yaml and assistant.yaml formats with full YAML structure.
        
        Args:
            role: User role (student, teacher, admin)
            user_name: User's name if known (from Memory)
            conversation_summary: Summary of previous conversation
            user_facts: List of known facts about user
            
        Returns:
            Complete system prompt string with template variables replaced
        """
        persona = self.get_persona(role)
        
        # Build prompt sections
        sections = []
        
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
