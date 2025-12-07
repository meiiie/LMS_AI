"""
Semantic Memory Module
CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

This module provides semantic memory capabilities for the Maritime AI Service.
Refactored from monolithic semantic_memory.py into modular components:

- core.py: SemanticMemoryEngine (Facade)
- context.py: ContextRetriever (context/insights retrieval)
- extraction.py: FactExtractor (fact extraction/storage)

Usage:
    from app.engine.semantic_memory import SemanticMemoryEngine
    engine = SemanticMemoryEngine()
"""

from .core import SemanticMemoryEngine, get_semantic_memory_engine
from .context import ContextRetriever
from .extraction import FactExtractor

__all__ = [
    "SemanticMemoryEngine",
    "get_semantic_memory_engine",
    "ContextRetriever",
    "FactExtractor",
]
