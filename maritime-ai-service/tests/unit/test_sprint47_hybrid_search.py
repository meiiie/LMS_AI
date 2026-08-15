"""
Tests for Sprint 47: HybridSearchService coverage.

Tests hybrid search combining dense + sparse with RRF reranking:
- Init (weights, components)
- Properties (dense_weight, sparse_weight)
- _extract_rule_numbers (Rule N, Quy tắc N, Điều N, bare numbers)
- search (hybrid, dense fallback, sparse fallback, both fail, neither enabled)
- search_dense_only, search_sparse_only
- is_available
- store_embedding, delete_embedding
- close
- Singleton (get_hybrid_search_service)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_service(dense_weight=0.5, sparse_weight=0.5, rrf_k=60):
    """Create HybridSearchService with mocked dependencies."""
    with patch("app.services.hybrid_search_service.get_embedding_backend") as mock_backend_fn, \
         patch("app.services.hybrid_search_service.get_dense_search_repository") as mock_dense_fn, \
         patch("app.repositories.sparse_search_repository.get_sparse_search_repository") as mock_sparse_fn:
        mock_emb = MagicMock()
        mock_backend_fn.return_value = mock_emb
        mock_dense = MagicMock()
        mock_dense_fn.return_value = mock_dense
        mock_sparse = MagicMock()
        mock_sparse_fn.return_value = mock_sparse

        from app.services.hybrid_search_service import HybridSearchService
        svc = HybridSearchService(
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
            rrf_k=rrf_k,
        )
    return svc, mock_emb, mock_dense, mock_sparse


# ============================================================================
# Init and properties
# ============================================================================


class TestHybridSearchServiceInit:
    """Test HybridSearchService initialization and properties."""

    def test_default_weights(self):
        svc, _, _, _ = _make_service()
        assert svc.dense_weight == 0.5
        assert svc.sparse_weight == 0.5

    def test_custom_weights(self):
        svc, _, _, _ = _make_service(dense_weight=0.7, sparse_weight=0.3)
        assert svc.dense_weight == 0.7
        assert svc.sparse_weight == 0.3

    def test_reranker_created(self):
        svc, _, _, _ = _make_service(rrf_k=30)
        assert svc._reranker.k == 30


# ============================================================================
# _extract_rule_numbers
# ============================================================================


class TestExtractRuleNumbers:
    """Test rule number extraction from queries."""

    def test_english_rule(self):
        svc, _, _, _ = _make_service()
        nums = svc._extract_rule_numbers("What is Rule 15?")
        assert "15" in nums

    def test_vietnamese_quy_tac(self):
        svc, _, _, _ = _make_service()
        nums = svc._extract_rule_numbers("Quy tắc 19 là gì?")
        assert "19" in nums

    def test_vietnamese_dieu(self):
        svc, _, _, _ = _make_service()
        nums = svc._extract_rule_numbers("Điều 23 quy định gì?")
        assert "23" in nums

    def test_bare_number(self):
        svc, _, _, _ = _make_service()
        nums = svc._extract_rule_numbers("Tell me about 15")
        assert "15" in nums

    def test_multiple_numbers(self):
        svc, _, _, _ = _make_service()
        nums = svc._extract_rule_numbers("Compare Rule 15 and Rule 19")
        assert "15" in nums
        assert "19" in nums

    def test_no_numbers(self):
        svc, _, _, _ = _make_service()
        nums = svc._extract_rule_numbers("What are navigation lights?")
        assert nums == []


# ============================================================================
# search - hybrid mode
# ============================================================================


class TestSearchHybrid:
    """Test hybrid search (both dense + sparse)."""

    @pytest.mark.asyncio
    async def test_parallel_search(self):
        svc, mock_emb, mock_dense, mock_sparse = _make_service()

        # Mock embedding generation
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)

        # Mock dense results
        dense_r = MagicMock()
        dense_r.node_id = "n1"
        dense_r.content = "Dense content"
        dense_r.similarity = 0.9
        dense_r.content_type = "text"
        dense_r.confidence_score = 1.0
        dense_r.page_number = 0
        dense_r.chunk_index = 0
        dense_r.image_url = ""
        dense_r.document_id = ""
        dense_r.section_hierarchy = {}
        dense_r.bounding_boxes = None
        mock_dense.search = AsyncMock(return_value=[dense_r])

        # Mock sparse results
        sparse_r = MagicMock()
        sparse_r.node_id = "n2"
        sparse_r.title = "Sparse title"
        sparse_r.content = "Sparse content"
        sparse_r.source = "KB"
        sparse_r.category = "Knowledge"
        sparse_r.score = 5.0
        sparse_r.image_url = ""
        sparse_r.page_number = 0
        sparse_r.document_id = ""
        sparse_r.bounding_boxes = None
        mock_sparse.search = AsyncMock(return_value=[sparse_r])

        results = await svc.search("Rule 15", limit=5)
        assert len(results) == 2
        mock_dense.search.assert_called_once()
        mock_sparse.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_dense_fails_fallback_sparse(self):
        svc, mock_emb, mock_dense, mock_sparse = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)
        mock_dense.search = AsyncMock(side_effect=Exception("Dense error"))

        sparse_r = MagicMock()
        sparse_r.node_id = "n1"
        sparse_r.title = "Title"
        sparse_r.content = "Content"
        sparse_r.source = "KB"
        sparse_r.category = "Knowledge"
        sparse_r.score = 5.0
        sparse_r.image_url = ""
        sparse_r.page_number = 0
        sparse_r.document_id = ""
        sparse_r.bounding_boxes = None
        mock_sparse.search = AsyncMock(return_value=[sparse_r])

        results = await svc.search("Rule 15", limit=5)
        assert len(results) == 1
        assert results[0].search_method == "sparse_only"

    @pytest.mark.asyncio
    async def test_sparse_fails_fallback_dense(self):
        svc, mock_emb, mock_dense, mock_sparse = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)
        mock_sparse.search = AsyncMock(side_effect=Exception("Sparse error"))

        dense_r = MagicMock()
        dense_r.node_id = "n1"
        dense_r.content = "Content"
        dense_r.similarity = 0.9
        dense_r.content_type = "text"
        dense_r.confidence_score = 1.0
        dense_r.page_number = 0
        dense_r.chunk_index = 0
        dense_r.image_url = ""
        dense_r.document_id = ""
        dense_r.section_hierarchy = {}
        dense_r.bounding_boxes = None
        mock_dense.search = AsyncMock(return_value=[dense_r])

        results = await svc.search("Rule 15", limit=5)
        assert len(results) == 1
        assert results[0].search_method == "dense_only"

    @pytest.mark.asyncio
    async def test_both_fail_returns_empty(self):
        svc, mock_emb, mock_dense, mock_sparse = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)
        mock_dense.search = AsyncMock(side_effect=Exception("Dense error"))
        mock_sparse.search = AsyncMock(side_effect=Exception("Sparse error"))

        results = await svc.search("Rule 15", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_strict_mode_surfaces_total_retrieval_failure(self):
        from app.services.hybrid_search_service import HybridSearchUnavailableError

        svc, mock_emb, mock_dense, mock_sparse = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)
        mock_dense.search = AsyncMock(side_effect=Exception("Dense error"))
        mock_sparse.search = AsyncMock(side_effect=Exception("Sparse error"))

        with pytest.raises(HybridSearchUnavailableError):
            await svc.search(
                "Rule 15",
                limit=5,
                raise_on_total_failure=True,
            )

    @pytest.mark.asyncio
    async def test_embedding_fails_returns_empty(self):
        svc, mock_emb, mock_dense, mock_sparse = _make_service()
        mock_emb.aembed_query = AsyncMock(side_effect=Exception("Embedding error"))

        results = await svc.search("Rule 15", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_query_embedding_falls_back_to_sparse(self):
        svc, mock_emb, mock_dense, mock_sparse = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[])

        sparse_r = MagicMock()
        sparse_r.node_id = "n1"
        sparse_r.title = "Title"
        sparse_r.content = "Content"
        sparse_r.source = "KB"
        sparse_r.category = "Knowledge"
        sparse_r.score = 5.0
        sparse_r.image_url = ""
        sparse_r.page_number = 0
        sparse_r.document_id = ""
        sparse_r.bounding_boxes = None
        mock_sparse.search = AsyncMock(return_value=[sparse_r])

        results = await svc.search("Rule 15", limit=5)
        assert len(results) == 1
        assert results[0].search_method == "sparse_only"
        mock_dense.search.assert_not_called()
        mock_sparse.search.assert_called_once()


# ============================================================================
# search - single mode
# ============================================================================


class TestSearchSingleMode:
    """Test dense-only and sparse-only search modes."""

    @pytest.mark.asyncio
    async def test_dense_only_mode(self):
        svc, mock_emb, mock_dense, _ = _make_service(dense_weight=1.0, sparse_weight=0.0)
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)

        dense_r = MagicMock()
        dense_r.node_id = "n1"
        dense_r.content = "Content"
        dense_r.similarity = 0.9
        dense_r.content_type = "text"
        dense_r.confidence_score = 1.0
        dense_r.page_number = 0
        dense_r.chunk_index = 0
        dense_r.image_url = ""
        dense_r.document_id = ""
        dense_r.section_hierarchy = {}
        dense_r.bounding_boxes = None
        mock_dense.search = AsyncMock(return_value=[dense_r])

        results = await svc.search("test", limit=5)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_sparse_only_mode(self):
        svc, _, _, mock_sparse = _make_service(dense_weight=0.0, sparse_weight=1.0)

        sparse_r = MagicMock()
        sparse_r.node_id = "n1"
        sparse_r.title = "Title"
        sparse_r.content = "Content"
        sparse_r.source = "KB"
        sparse_r.category = "Knowledge"
        sparse_r.score = 5.0
        sparse_r.image_url = ""
        sparse_r.page_number = 0
        sparse_r.document_id = ""
        sparse_r.bounding_boxes = None
        mock_sparse.search = AsyncMock(return_value=[sparse_r])

        results = await svc.search("test", limit=5)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_neither_enabled(self):
        svc, _, _, _ = _make_service(dense_weight=0.0, sparse_weight=0.0)
        results = await svc.search("test", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_dense_only_error(self):
        svc, mock_emb, mock_dense, _ = _make_service(dense_weight=1.0, sparse_weight=0.0)
        mock_emb.aembed_query = AsyncMock(side_effect=Exception("error"))
        results = await svc.search("test", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_dense_only_mode_empty_embedding_returns_empty(self):
        svc, mock_emb, mock_dense, _ = _make_service(dense_weight=1.0, sparse_weight=0.0)
        mock_emb.aembed_query = AsyncMock(return_value=[])

        results = await svc.search("test", limit=5)
        assert results == []
        mock_dense.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_sparse_only_error(self):
        svc, _, _, mock_sparse = _make_service(dense_weight=0.0, sparse_weight=1.0)
        mock_sparse.search = AsyncMock(side_effect=Exception("error"))
        results = await svc.search("test", limit=5)
        assert results == []


# ============================================================================
# search_dense_only / search_sparse_only methods
# ============================================================================


class TestDirectSearchMethods:
    """Test search_dense_only and search_sparse_only convenience methods."""

    @pytest.mark.asyncio
    async def test_search_dense_only(self):
        svc, mock_emb, mock_dense, _ = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[0.1] * 768)

        dense_r = MagicMock()
        dense_r.node_id = "n1"
        dense_r.content = "Content"
        dense_r.similarity = 0.9
        dense_r.content_type = "text"
        dense_r.confidence_score = 1.0
        dense_r.page_number = 0
        dense_r.chunk_index = 0
        dense_r.image_url = ""
        dense_r.document_id = ""
        dense_r.section_hierarchy = {}
        dense_r.bounding_boxes = None
        mock_dense.search = AsyncMock(return_value=[dense_r])

        results = await svc.search_dense_only("test", limit=3)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_dense_only_error(self):
        svc, mock_emb, _, _ = _make_service()
        mock_emb.aembed_query = AsyncMock(side_effect=Exception("error"))
        results = await svc.search_dense_only("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_dense_only_empty_embedding_returns_empty(self):
        svc, mock_emb, mock_dense, _ = _make_service()
        mock_emb.aembed_query = AsyncMock(return_value=[])

        results = await svc.search_dense_only("test")
        assert results == []
        mock_dense.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_sparse_only(self):
        svc, _, _, mock_sparse = _make_service()

        sparse_r = MagicMock()
        sparse_r.node_id = "n1"
        sparse_r.title = "Title"
        sparse_r.content = "Content"
        sparse_r.source = "KB"
        sparse_r.category = "Knowledge"
        sparse_r.score = 5.0
        sparse_r.image_url = ""
        sparse_r.page_number = 0
        sparse_r.document_id = ""
        sparse_r.bounding_boxes = None
        mock_sparse.search = AsyncMock(return_value=[sparse_r])

        results = await svc.search_sparse_only("test", limit=3)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_sparse_only_error(self):
        svc, _, _, mock_sparse = _make_service()
        mock_sparse.search = AsyncMock(side_effect=Exception("error"))
        results = await svc.search_sparse_only("test")
        assert results == []


# ============================================================================
# is_available
# ============================================================================


class TestIsAvailable:
    """Test is_available."""

    def test_both_available(self):
        svc, _, mock_dense, mock_sparse = _make_service()
        mock_dense.is_available.return_value = True
        mock_sparse.is_available.return_value = True
        assert svc.is_available() is True

    def test_dense_only_available(self):
        svc, _, mock_dense, mock_sparse = _make_service()
        mock_dense.is_available.return_value = True
        mock_sparse.is_available.return_value = False
        assert svc.is_available() is True

    def test_sparse_only_available(self):
        svc, _, mock_dense, mock_sparse = _make_service()
        mock_dense.is_available.return_value = False
        mock_sparse.is_available.return_value = True
        assert svc.is_available() is True

    def test_neither_available(self):
        svc, _, mock_dense, mock_sparse = _make_service()
        mock_dense.is_available.return_value = False
        mock_sparse.is_available.return_value = False
        assert svc.is_available() is False


# ============================================================================
# store_embedding / delete_embedding
# ============================================================================


class TestEmbeddingOperations:
    """Test store and delete embedding."""

    @pytest.mark.asyncio
    async def test_store_embedding_success(self):
        svc, mock_emb, mock_dense, _ = _make_service()
        mock_emb.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_dense.store_embedding = AsyncMock(return_value=True)

        result = await svc.store_embedding("node1", "Some content")
        assert result is True
        mock_dense.store_embedding.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_embedding_error(self):
        svc, mock_emb, _, _ = _make_service()
        mock_emb.aembed_documents = AsyncMock(side_effect=Exception("error"))

        result = await svc.store_embedding("node1", "Some content")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_embedding(self):
        svc, _, mock_dense, _ = _make_service()
        mock_dense.delete_embedding = AsyncMock(return_value=True)

        result = await svc.delete_embedding("node1")
        assert result is True
        mock_dense.delete_embedding.assert_called_once_with("node1")


# ============================================================================
# close
# ============================================================================


class TestClose:
    """Test close."""

    @pytest.mark.asyncio
    async def test_close(self):
        svc, _, mock_dense, mock_sparse = _make_service()
        mock_dense.close = AsyncMock()
        mock_sparse.close = AsyncMock()

        await svc.close()
        mock_dense.close.assert_called_once()
        mock_sparse.close.assert_called_once()


# ============================================================================
# Singleton
# ============================================================================


class TestSingleton:
    """Test singleton pattern."""

    def test_get_hybrid_search_service(self):
        with patch("app.services.hybrid_search_service.get_embedding_backend"), \
             patch("app.services.hybrid_search_service.get_dense_search_repository"), \
             patch("app.repositories.sparse_search_repository.get_sparse_search_repository"):
            import app.services.hybrid_search_service as mod
            mod._hybrid_search_service = None
            svc1 = mod.get_hybrid_search_service()
            svc2 = mod.get_hybrid_search_service()
            assert svc1 is svc2
            mod._hybrid_search_service = None  # Cleanup
