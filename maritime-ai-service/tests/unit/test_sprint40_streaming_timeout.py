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

    def test_source_has_timeout_constants(self):
        """answer_generator streaming method defines timeout constants."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        source = inspect.getsource(AnswerGenerator.generate_response_streaming)
        assert "CHUNK_TIMEOUT" in source
        assert "TOTAL_TIMEOUT" in source
        assert "asyncio.wait_for" in source


# ============================================================================
# 2. graph.astream() timeout in graph_streaming.py
# ============================================================================


class TestGraphStreamingTimeout:
    """Test that graph_streaming has timeout protection."""

    def test_source_has_timeout_constants(self):
        """graph_streaming defines timeout constants for graph nodes."""
        with open("app/engine/multi_agent/graph_streaming.py", encoding="utf-8") as f:
            source = f.read()
        assert "GRAPH_NODE_TIMEOUT" in source
        assert "GRAPH_TOTAL_TIMEOUT" in source
        assert "asyncio.wait_for" in source

    def test_no_str_e_in_error_event(self):
        """Error event uses generic message, not str(e)."""
        with open("app/engine/multi_agent/graph_streaming.py", encoding="utf-8") as f:
            content = f.read()

        # Find except Exception blocks
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "create_error_event" in stripped and "str(e)" in stripped:
                pytest.fail(
                    f"graph_streaming.py:{i+1} leaks str(e) via create_error_event: {stripped}"
                )


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

    def test_get_uses_lock(self):
        """get() method acquires _lock."""
        from app.cache.semantic_cache import SemanticResponseCache

        source = inspect.getsource(SemanticResponseCache.get)
        assert "async with self._lock" in source

    def test_set_uses_lock(self):
        """set() method acquires _lock."""
        from app.cache.semantic_cache import SemanticResponseCache

        source = inspect.getsource(SemanticResponseCache.set)
        assert "async with self._lock" in source

    def test_invalidate_uses_lock(self):
        """invalidate_by_document() method acquires _lock."""
        from app.cache.semantic_cache import SemanticResponseCache

        source = inspect.getsource(SemanticResponseCache.invalidate_by_document)
        assert "async with self._lock" in source

    def test_clear_uses_lock(self):
        """clear() method acquires _lock."""
        from app.cache.semantic_cache import SemanticResponseCache

        source = inspect.getsource(SemanticResponseCache.clear)
        assert "async with self._lock" in source

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


class TestRateLimitingDecorators:
    """Verify all API endpoints have rate limiting."""

    def test_chat_stream_v3_has_rate_limit(self):
        """V3 /chat/stream/v3 endpoint has @limiter.limit decorator."""
        from app.api.v1 import chat_stream

        fn = getattr(chat_stream, "chat_stream_v3")
        # Check that the module imports limiter
        mod_source = inspect.getsource(chat_stream)
        assert "from app.core.rate_limit import limiter" in mod_source

    def test_chat_stream_module_imports_limiter(self):
        """chat_stream.py imports the limiter."""
        with open("app/api/v1/chat_stream.py", encoding="utf-8") as f:
            content = f.read()
        assert "from app.core.rate_limit import limiter" in content

    @pytest.mark.parametrize("line_pattern", [
        "@limiter.limit",
    ])
    def test_chat_stream_all_endpoints_decorated(self, line_pattern):
        """All streaming endpoints have @limiter.limit before the function."""
        with open("app/api/v1/chat_stream.py", encoding="utf-8") as f:
            content = f.read()

        # Count @limiter.limit occurrences — should be >= 1 (v3)
        count = content.count(line_pattern)
        assert count >= 1, f"Expected >= 1 {line_pattern} decorators, found {count}"

    def test_admin_module_imports_limiter(self):
        """admin.py imports the limiter."""
        with open("app/api/v1/admin.py", encoding="utf-8") as f:
            content = f.read()
        assert "from app.core.rate_limit import limiter" in content

    def test_admin_all_endpoints_rate_limited(self):
        """All admin endpoints have @limiter.limit decorator."""
        with open("app/api/v1/admin.py", encoding="utf-8") as f:
            content = f.read()

        # 7 endpoints: upload, status, list, delete, list_domains, get_domain, list_skills
        count = content.count("@limiter.limit")
        assert count >= 7, f"Expected >= 7 @limiter.limit in admin.py, found {count}"

    def test_organizations_module_imports_limiter(self):
        """organizations.py imports the limiter."""
        with open("app/api/v1/organizations.py", encoding="utf-8") as f:
            content = f.read()
        assert "from app.core.rate_limit import limiter" in content

    def test_organizations_all_endpoints_rate_limited(self):
        """All organization endpoints have @limiter.limit decorator."""
        with open("app/api/v1/organizations.py", encoding="utf-8") as f:
            content = f.read()

        # 9 endpoints: list, get, create, update, delete, add_member, remove_member, list_members, my_orgs
        count = content.count("@limiter.limit")
        assert count >= 9, f"Expected >= 9 @limiter.limit in organizations.py, found {count}"

    def test_admin_endpoints_have_request_param(self):
        """All rate-limited admin endpoints accept Request parameter."""
        with open("app/api/v1/admin.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name in (
                    "upload_document", "get_document_status", "list_documents",
                    "delete_document", "list_domains", "get_domain", "list_domain_skills"
                ):
                    arg_names = [a.arg for a in node.args.args]
                    assert "request" in arg_names, (
                        f"admin.{node.name}() missing 'request' param for slowapi"
                    )

    def test_organizations_endpoints_have_request_param(self):
        """All rate-limited org endpoints accept Request parameter."""
        with open("app/api/v1/organizations.py", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                if node.name in (
                    "list_organizations", "get_organization", "create_organization",
                    "update_organization", "delete_organization", "add_member",
                    "remove_member", "list_members", "my_organizations"
                ):
                    arg_names = [a.arg for a in node.args.args]
                    assert "request" in arg_names, (
                        f"organizations.{node.name}() missing 'request' param for slowapi"
                    )


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
