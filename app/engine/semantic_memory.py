"""
Semantic Memory - Backward Compatibility Wrapper
CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

This file maintains backward compatibility for existing imports.
The actual implementation has been refactored into the semantic_memory/ module.

Usage (both work):
    from app.engine.semantic_memory import SemanticMemoryEngine
    from app.engine.semantic_memory.core import SemanticMemoryEngine
"""

# Re-export from the new modular structure
from app.engine.semantic_memory.core import SemanticMemoryEngine, get_semantic_memory_engine
from app.engine.semantic_memory.context import ContextRetriever
from app.engine.semantic_memory.extraction import FactExtractor

__all__ = [
    "SemanticMemoryEngine",
    "get_semantic_memory_engine",
    "ContextRetriever",
    "FactExtractor",
]
