"""
Semantic Memory Module
CHI THI KY THUAT SO 25 - Project Restructure

This module provides semantic memory capabilities for the Wiii.
Refactored from monolithic semantic_memory.py into modular components:

- core.py: SemanticMemoryEngine (Facade)
- context.py: ContextRetriever (context/insights retrieval)
- extraction.py: FactExtractor (fact extraction/storage)
- insight_provider.py: InsightProvider (insight extraction, validation, lifecycle)

Usage:
    from app.engine.semantic_memory import SemanticMemoryEngine
    engine = SemanticMemoryEngine()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ContextRetriever
    from .core import SemanticMemoryEngine, get_semantic_memory_engine
    from .extraction import FactExtractor
    from .insight_provider import InsightProvider

_EXPORTS = {
    "SemanticMemoryEngine": (".core", "SemanticMemoryEngine"),
    "get_semantic_memory_engine": (".core", "get_semantic_memory_engine"),
    "ContextRetriever": (".context", "ContextRetriever"),
    "FactExtractor": (".extraction", "FactExtractor"),
    "InsightProvider": (".insight_provider", "InsightProvider"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    import importlib

    module_path, attr_name = target
    module = importlib.import_module(module_path, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    "SemanticMemoryEngine",
    "get_semantic_memory_engine",
    "ContextRetriever",
    "FactExtractor",
    "InsightProvider",
]
