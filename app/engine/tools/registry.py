"""
Tool Registry - Centralized Tool Management for Maritime AI Tutor

SOTA 2025 Pattern: Tool Registry with Categories
- Modular tool organization
- Category-based loading
- Read/Write separation
- Role-based access (future)
"""

import logging
from typing import Dict, List, Optional, Callable
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories for organization and filtering."""
    RAG = "rag"              # Knowledge retrieval
    MEMORY = "memory"        # User memory management
    MEMORY_CONTROL = "memory_control"  # Phase 10: Explicit control
    LEARNING = "learning"    # Future: Lesson, Quiz
    ASSESSMENT = "assessment"  # Future: Exam, Certificate
    SCHEDULE = "schedule"    # Future: Phase 12


class ToolAccess(Enum):
    """Tool access types for safety."""
    READ = "read"      # Read-only, safe
    WRITE = "write"    # Mutating, needs care


@dataclass
class ToolInfo:
    """Metadata about a registered tool."""
    name: str
    tool: Callable
    category: ToolCategory
    access: ToolAccess
    description: str = ""
    roles: List[str] = field(default_factory=lambda: ["student", "teacher", "admin"])


class ToolRegistry:
    """
    Centralized registry for all AI agent tools.
    
    Benefits:
    - Modular organization
    - Category-based filtering
    - Read/Write separation
    - Role-based access control
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolInfo] = {}
        self._categories: Dict[ToolCategory, List[str]] = {}
        self._initialized = False
    
    def register(
        self,
        tool: Callable,
        category: ToolCategory,
        access: ToolAccess = ToolAccess.READ,
        description: str = "",
        roles: Optional[List[str]] = None
    ) -> None:
        """
        Register a tool with metadata.
        
        Args:
            tool: The LangChain tool function
            category: Tool category for organization
            access: READ or WRITE access type
            description: Human-readable description
            roles: Allowed user roles (default: all)
        """
        name = tool.name if hasattr(tool, 'name') else tool.__name__
        
        info = ToolInfo(
            name=name,
            tool=tool,
            category=category,
            access=access,
            description=description or (tool.description if hasattr(tool, 'description') else ""),
            roles=roles or ["student", "teacher", "admin"]
        )
        
        self._tools[name] = info
        
        # Track by category
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(name)
        
        logger.debug(f"Registered tool: {name} [{category.value}/{access.value}]")
    
    def get_all(self) -> List[Callable]:
        """Get all registered tools as a list."""
        return [info.tool for info in self._tools.values()]
    
    def get_all_names(self) -> List[str]:
        """Get names of all registered tools."""
        return list(self._tools.keys())
    
    def get_by_category(self, category: ToolCategory) -> List[Callable]:
        """Get tools by category."""
        names = self._categories.get(category, [])
        return [self._tools[name].tool for name in names]
    
    def get_read_only(self) -> List[Callable]:
        """Get only read-only (safe) tools."""
        return [
            info.tool for info in self._tools.values()
            if info.access == ToolAccess.READ
        ]
    
    def get_mutating(self) -> List[Callable]:
        """Get only mutating (write) tools."""
        return [
            info.tool for info in self._tools.values()
            if info.access == ToolAccess.WRITE
        ]
    
    def get_for_role(self, role: str) -> List[Callable]:
        """Get tools available for a specific user role."""
        return [
            info.tool for info in self._tools.values()
            if role in info.roles
        ]
    
    def get_info(self, name: str) -> Optional[ToolInfo]:
        """Get metadata for a specific tool."""
        return self._tools.get(name)
    
    def count(self) -> int:
        """Get total number of registered tools."""
        return len(self._tools)
    
    def summary(self) -> Dict:
        """Get summary of registered tools."""
        return {
            "total": len(self._tools),
            "categories": {
                cat.value: len(names) 
                for cat, names in self._categories.items()
            },
            "read_only": len([t for t in self._tools.values() if t.access == ToolAccess.READ]),
            "mutating": len([t for t in self._tools.values() if t.access == ToolAccess.WRITE])
        }


# =============================================================================
# Singleton Pattern
# =============================================================================

_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(
    category: ToolCategory,
    access: ToolAccess = ToolAccess.READ,
    description: str = "",
    roles: Optional[List[str]] = None
):
    """
    Decorator to register a tool with the global registry.
    
    Usage:
        @register_tool(ToolCategory.RAG, ToolAccess.READ)
        @tool
        async def my_tool(query: str) -> str:
            ...
    """
    def decorator(func):
        # Will be registered when module is imported
        get_tool_registry().register(
            tool=func,
            category=category,
            access=access,
            description=description,
            roles=roles
        )
        return func
    return decorator
