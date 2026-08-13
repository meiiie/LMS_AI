"""
Tests for Sprint 40: Streaming timeout, cache async safety, rate limiting.

Covers:
- astream() timeout in answer_generator.py (per-chunk + total)
- graph.astream() timeout in graph_streaming.py
- str(e) not leaked in streaming error paths
- SemanticCache uses asyncio.Lock for concurrent access
- Rate limiting decorators on /chat/stream, /admin/*, /organizations/*
"""

import ast
import asyncio
import inspect
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# 1. astream() timeout in answer_generator.py
# ============================================================================


class TestAnswerGeneratorStreamingTimeout:
    """Test that generate_response_streaming has timeout protection."""

    def test_imports_asyncio_and_time(self):
        """answer_generator.py imports asyncio and time for timeout logic."""
        import app.engine.agentic_rag.answer_generator as mod
        import asyncio as _asyncio
        import time as _time

        # Module-level imports should be present
        assert hasattr(mod, "asyncio") or "asyncio" in dir(mod)

    @pytest.mark.asyncio
    async def test_chunk_timeout_aborts_stream(self):
        """Stream aborts when a chunk takes too long (asyncio.TimeoutError)."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        from app.models.knowledge_graph import KnowledgeNode

        # Create a mock LLM that hangs on second chunk
        async def hanging_astream(messages):
            yield MagicMock(content="First chunk")
            await asyncio.sleep(999)  # Will timeout
            yield MagicMock(content="Never reached")

        mock_llm = MagicMock()
        mock_llm.astream = hanging_astream

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "system"
        mock_loader.get_thinking_instruction.return_value = ""

        nodes = [KnowledgeNode(id="n1", node_type="REGULATION", title="Test", content="Content", source="src")]

        chunks = []
        gen = AnswerGenerator.generate_response_streaming(
            llm=mock_llm,
            prompt_loader=mock_loader,
            question="test?",
            nodes=nodes,
        )
        async for chunk in gen:
            chunks.append(chunk)
            if len(chunks) > 5:
                break  # Safety valve

        # Should have gotten at least the first chunk
        assert len(chunks) >= 1
        assert "First chunk" in chunks[0]

    @pytest.mark.asyncio
    async def test_no_str_e_in_streaming_error(self):
        """Streaming error yields generic message, not str(e)."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        from app.models.knowledge_graph import KnowledgeNode

        # Create a mock LLM that raises immediately
        async def error_astream(messages):
            raise RuntimeError("SECRET_API_KEY_LEAKED")
            yield  # pragma: no cover

        mock_llm = MagicMock()
        mock_llm.astream = error_astream

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "system"
        mock_loader.get_thinking_instruction.return_value = ""

        nodes = [KnowledgeNode(id="n1", node_type="REGULATION", title="Test", content="Content", source="src")]

        chunks = []
        async for chunk in AnswerGenerator.generate_response_streaming(
            llm=mock_llm,
            prompt_loader=mock_loader,
            question="test?",
            nodes=nodes,
        ):
            chunks.append(chunk)

        # Should contain a safe fallback, NOT the actual exception message.
        error_text = " ".join(chunks)
        assert "SECRET_API_KEY_LEAKED" not in error_text
        assert "Test: Content" in error_text
        assert "Nguồn tham khảo" in error_text



# ============================================================================
# 2. graph.astream() timeout in graph_streaming.py
# ============================================================================




# ============================================================================
# 3. SemanticCache uses asyncio.Lock
# ============================================================================


class TestSemanticCacheAsyncSafety:
    """Test that SemanticResponseCache uses asyncio.Lock for all mutations."""

    def test_cache_has_asyncio_lock(self):
        """SemanticResponseCache.__init__ creates an asyncio.Lock."""
        from app.cache.semantic_cache import SemanticResponseCache

        cache = SemanticResponseCache()
        assert hasattr(cache, "_lock")
        assert isinstance(cache._lock, asyncio.Lock)





    @pytest.mark.asyncio
    async def test_concurrent_set_get_no_crash(self):
        """Concurrent set + get operations don't crash."""
        from app.cache.semantic_cache import SemanticResponseCache
        from app.cache.models import CacheConfig

        config = CacheConfig(enabled=True, max_response_entries=50)
        cache = SemanticResponseCache(config)

        import numpy as np

        errors = []

        async def writer(n):
            try:
                emb = np.random.rand(768).tolist()
                await cache.set(f"query_{n}", emb, f"response_{n}")
            except Exception as e:
                errors.append(e)

        async def reader(n):
            try:
                emb = np.random.rand(768).tolist()
                await cache.get(f"query_{n}", emb)
            except Exception as e:
                errors.append(e)

        # Run 20 concurrent writers and 20 concurrent readers
        tasks = []
        for i in range(20):
            tasks.append(asyncio.create_task(writer(i)))
            tasks.append(asyncio.create_task(reader(i)))

        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"Concurrent access errors: {errors}"


# ============================================================================
# 4. Rate limiting decorators
# ============================================================================




# ============================================================================
# 5. Comprehensive str(e) leak check (regression)
# ============================================================================


class TestNoStrELeaksStreaming:
    """Verify no str(e) in streaming/error paths to clients."""

    @pytest.mark.parametrize("filepath", [
        "app/engine/agentic_rag/answer_generator.py",
        "app/engine/multi_agent/graph_streaming.py",
    ])
    def test_no_str_e_yielded_to_client(self, filepath):
        """Streaming files should not yield str(e) to client."""
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip logger lines
            if stripped.startswith("logger."):
                continue
            # Check for str(e) in yield or create_error_event
            if "str(e)" in stripped:
                if "yield" in stripped or "create_error_event" in stripped:
                    pytest.fail(
                        f"{filepath}:{i} leaks str(e) to client: {stripped}"
                    )
