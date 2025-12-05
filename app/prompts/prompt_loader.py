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
        
        for role, filename in yaml_files.items():
            filepath = self._prompts_dir / filename
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        self._personas[role] = yaml.safe_load(f)
                    logger.info(f"Loaded persona for role '{role}' from {filename}")
                except Exception as e:
                    logger.error(f"Failed to load {filename}: {e}")
                    self._personas[role] = self._get_default_persona()
            else:
                logger.warning(f"Persona file not found: {filepath}")
                self._personas[role] = self._get_default_persona()
    
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
    
    def build_system_prompt(
        self,
        role: str,
        user_name: Optional[str] = None,
        conversation_summary: Optional[str] = None,
        user_facts: Optional[List[str]] = None
    ) -> str:
        """
        Build system prompt from persona configuration.
        
        Args:
            role: User role (student, teacher, admin)
            user_name: User's name if known
            conversation_summary: Summary of previous conversation
            user_facts: List of known facts about user
            
        Returns:
            Complete system prompt string
        """
        persona = self.get_persona(role)
        
        # Build prompt sections
        sections = []
        
        # Role and description
        sections.append(f"Bạn là {persona.get('role', 'Maritime AI Assistant')}.")
        if persona.get('description'):
            sections.append(persona['description'])
        
        # Tone
        if persona.get('tone'):
            tone_text = "\n".join(f"- {t}" for t in persona['tone'])
            sections.append(f"\nGIỌNG VĂN:\n{tone_text}")
        
        # Instructions
        instructions = persona.get('instructions', {})
        if instructions:
            sections.append("\nQUY TẮC ỨNG XỬ:")
            for category, rules in instructions.items():
                if isinstance(rules, list):
                    for rule in rules:
                        sections.append(f"- {rule}")
        
        # User context
        if user_name or user_facts:
            sections.append("\nTHÔNG TIN NGƯỜI DÙNG:")
            if user_name:
                sections.append(f"- Tên: {user_name}")
            if user_facts:
                for fact in user_facts[:5]:  # Limit to 5 facts
                    sections.append(f"- {fact}")
        
        # Conversation summary
        if conversation_summary:
            sections.append(f"\nTÓM TẮT HỘI THOẠI TRƯỚC:\n{conversation_summary}")
        
        # Few-shot examples
        examples = persona.get('few_shot_examples', [])
        if examples:
            sections.append("\nVÍ DỤ CÁCH TRẢ LỜI:")
            for ex in examples[:3]:  # Limit to 3 examples
                context = ex.get('context', '')
                user_msg = ex.get('user', '')
                ai_msg = ex.get('ai', '')
                if user_msg and ai_msg:
                    sections.append(f"[{context}]")
                    sections.append(f"User: {user_msg}")
                    sections.append(f"AI: {ai_msg}")
                    sections.append("")
        
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
