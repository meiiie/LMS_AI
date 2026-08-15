"""
Tests for Sprint 41: Fix blocking sync embed calls in async contexts.

Verifies that all async functions use aembed_documents()/aembed_query() instead of
embed_documents()/embed_query(), preventing event loop blocking during Gemini API calls.
"""

import ast
import pytest


# ============================================================================
# AST-based checks: ensure no sync embed calls in async functions
# ============================================================================


SYNC_EMBED_METHODS = {"embed_documents", "embed_query"}


def _find_sync_embed_in_async(filepath: str) -> list[str]:
    """
    Find sync embed_documents()/embed_query() calls inside async functions.

    Returns list of 'function_name:line_number' for each violation.
    """
    with open(filepath, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            func_name = node.name
            # Walk the function body looking for sync embed calls
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and child.attr in SYNC_EMBED_METHODS:
                    violations.append(f"{func_name}:{child.attr}:{child.lineno}")
                # Also check method calls like .embed_documents(...)
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Attribute) and func.attr in SYNC_EMBED_METHODS:
                        violations.append(f"{func_name}:{func.attr}:{func.lineno}")

    # Deduplicate
    return list(set(violations))


class TestNoSyncEmbedInAsyncFunctions:
    """Ensure embed_documents()/embed_query() are not called in async functions."""

    @pytest.mark.parametrize("filepath", [
        "app/services/hybrid_search_service.py",
        # memory_manager.py removed (Sprint 84 dead code cleanup)
        "app/engine/semantic_memory/extraction.py",
        "app/engine/agentic_rag/corrective_rag.py",
        "app/engine/agentic_rag/corrective_rag_runtime_support.py",
        "app/engine/semantic_memory/context.py",
    ])
    def test_no_sync_embed_in_async(self, filepath):
        """No async function should call sync embed methods (use aembed_* instead)."""
        violations = _find_sync_embed_in_async(filepath)
        if violations:
            pytest.fail(
                f"{filepath} has sync embed calls in async functions: {violations}\n"
                "Use await ...aembed_documents()/aembed_query() instead."
            )


# ============================================================================
# Verify async embed usage in fixed files
# ============================================================================




# ============================================================================
# Verify aembed methods exist on the embeddings class
# ============================================================================


class TestAembedMethodExists:
    """Verify the async embedding methods are available."""

    def test_gemini_embeddings_has_aembed_documents(self):
        """GeminiOptimizedEmbeddings has aembed_documents method."""
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        assert hasattr(GeminiOptimizedEmbeddings, "aembed_documents")

    def test_gemini_embeddings_has_aembed_query(self):
        """GeminiOptimizedEmbeddings has aembed_query method."""
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        assert hasattr(GeminiOptimizedEmbeddings, "aembed_query")

    def test_aembed_documents_is_coroutine(self):
        """aembed_documents should be an async method."""
        import asyncio
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        assert asyncio.iscoroutinefunction(GeminiOptimizedEmbeddings.aembed_documents)

    def test_aembed_query_is_coroutine(self):
        """aembed_query should be an async method."""
        import asyncio
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        assert asyncio.iscoroutinefunction(GeminiOptimizedEmbeddings.aembed_query)


# ============================================================================
# No sync embed_documents remaining in source (excluding docstrings/comments)
# ============================================================================


class TestNoSyncEmbedRemaining:
    """Verify no sync embed calls remain in async functions across all app files."""

    @pytest.mark.parametrize("filepath", [
        "app/services/hybrid_search_service.py",
        # memory_manager.py removed (Sprint 84 dead code cleanup)
        "app/engine/semantic_memory/extraction.py",
        "app/engine/agentic_rag/corrective_rag.py",
        "app/engine/agentic_rag/corrective_rag_runtime_support.py",
        "app/engine/semantic_memory/context.py",
    ])
    def test_no_sync_embed_documents_remain(self, filepath):
        """Verify embed_documents() not used in async functions (only aembed_documents)."""
        violations = []
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "embed_documents":
                        violations.append(f"{node.name}:{child.lineno}")
        assert not violations, f"Sync embed_documents() in async: {violations}"

    @pytest.mark.parametrize("filepath", [
        "app/services/hybrid_search_service.py",
        "app/engine/agentic_rag/corrective_rag.py",
        "app/engine/agentic_rag/corrective_rag_runtime_support.py",
        "app/engine/semantic_memory/context.py",
    ])
    def test_no_sync_embed_query_remain(self, filepath):
        """Verify embed_query() not used in async functions (only aembed_query)."""
        violations = []
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "embed_query":
                        violations.append(f"{node.name}:{child.lineno}")
        assert not violations, f"Sync embed_query() in async: {violations}"
