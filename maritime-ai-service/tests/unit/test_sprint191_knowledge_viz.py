"""
Sprint 191: "Mat Tri Thuc" -- Knowledge Visualization

Tests for:
  1. TestScatter -- PCA 2D/3D, t-SNE, auto-fallback, empty state, cache, org isolation
  2. TestKnowledgeGraph -- node/edge creation, Mermaid, cross-doc similarity, empty
  3. TestRagFlow -- embed->retrieve->grade pipeline, thresholds, doc name, empty
  4. TestAPI -- feature gate, multi-tenant gate, org membership, param validation, rate limit
  5. TestCache -- TTL hit, TTL expiry, key generation
"""

import sys
import hashlib
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# =============================================================================
# Sklearn stub — inject mock sklearn modules so lazy imports inside the service
# work even when sklearn is not installed.
# =============================================================================

def _ensure_sklearn_mocks():
    """Inject minimal sklearn mocks into sys.modules if not already present."""
    if "sklearn" in sys.modules and not isinstance(sys.modules["sklearn"], ModuleType):
        return  # already mocked
    try:
        import sklearn  # noqa: F401
        return  # real sklearn available
    except ImportError:
        pass

    # Create stub modules
    sklearn_mod = ModuleType("sklearn")
    decomposition_mod = ModuleType("sklearn.decomposition")
    manifold_mod = ModuleType("sklearn.manifold")

    # PCA stub: fit_transform returns random coords with correct shape
    class _StubPCA:
        def __init__(self, n_components=2, random_state=None):
            self.n_components = n_components

        def fit_transform(self, X):
            return np.random.randn(X.shape[0], self.n_components)

    # TSNE stub
    class _StubTSNE:
        def __init__(self, n_components=2, perplexity=30, random_state=None):
            self.n_components = n_components

        def fit_transform(self, X):
            return np.random.randn(X.shape[0], self.n_components)

    decomposition_mod.PCA = _StubPCA
    manifold_mod.TSNE = _StubTSNE

    sklearn_mod.decomposition = decomposition_mod
    sklearn_mod.manifold = manifold_mod

    sys.modules["sklearn"] = sklearn_mod
    sys.modules["sklearn.decomposition"] = decomposition_mod
    sys.modules["sklearn.manifold"] = manifold_mod


_ensure_sklearn_mocks()


# =============================================================================
# Legacy embedder stub
#
# The service now resolves embeddings through get_embedding_backend(), but the
# stub remains harmless and keeps backward compatibility with older imports.
# =============================================================================

_EMBEDDER_MODULE = "app.engine.llm_providers.gemini_embedding"

# Sentinel class that tests will patch on a per-test basis
class _StubGeminiOptimizedEmbeddings:
    """Placeholder that will be replaced by patch() in each test."""
    def __init__(self, *a, **kw):
        pass

    async def aembed_query(self, text):
        return [0.1] * 768


def _ensure_embedder_mock():
    """Pre-populate sys.modules for the lazy import path used by the service."""
    if _EMBEDDER_MODULE in sys.modules:
        return
    mod = ModuleType(_EMBEDDER_MODULE)
    mod.GeminiOptimizedEmbeddings = _StubGeminiOptimizedEmbeddings
    sys.modules[_EMBEDDER_MODULE] = mod
    # Also ensure parent is importable
    parent = "app.engine.llm_providers"
    if parent in sys.modules:
        sys.modules[parent].gemini_embedding = mod


_ensure_embedder_mock()


# =============================================================================
# Helpers
# =============================================================================

def _make_settings(**overrides):
    """Create a Settings mock with defaults + overrides."""
    defaults = {
        "enable_knowledge_visualization": True,
        "enable_multi_tenant": True,
        "enable_org_admin": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_auth(user_id="user-1", role="student", org_id=None):
    """Create an AuthenticatedUser for testing (Sprint 217: require_auth migration)."""
    from app.core.security import AuthenticatedUser
    return AuthenticatedUser(
        user_id=user_id,
        auth_method="api_key",
        role=role,
        organization_id=org_id,
    )


def _make_request(user_id="user-1", role="student", org_id=None):
    """Create a mock Request for rate limiter (still needed by endpoints)."""
    headers = {
        "x-user-id": user_id,
        "x-role": role,
    }
    if org_id:
        headers["x-organization-id"] = org_id

    req = MagicMock()
    req.headers = MagicMock()
    req.headers.get = lambda key, default=None: headers.get(key, default)
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.state = MagicMock()
    return req


def _make_pool():
    """Create mock asyncpg pool with async context manager acquire()."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock()
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    return pool, conn


def _make_embedding_row(
    row_id="chunk-1",
    document_id="doc-1",
    content="Sample content for testing",
    page_number=1,
    content_type="text",
    document_name="test.pdf",
    embedding=None,
):
    """Create a dict mimicking a knowledge_embeddings JOIN row."""
    if embedding is None:
        embedding = "[" + ",".join(str(x) for x in np.random.randn(128).tolist()) + "]"
    return {
        "id": row_id,
        "document_id": document_id,
        "content": content,
        "page_number": page_number,
        "content_type": content_type,
        "document_name": document_name,
        "embedding": embedding,
    }


def _make_doc_row(document_id="doc-1", filename="test.pdf"):
    """Mimics organization_documents row."""
    return {"document_id": document_id, "filename": filename}


def _make_rag_row(
    row_id="chunk-1",
    document_id="doc-1",
    content="Maritime safety regulations",
    page_number=1,
    content_type="text",
    document_name="colregs.pdf",
    similarity=0.85,
):
    """Create a dict mimicking a RAG retrieval result row."""
    return {
        "id": row_id,
        "document_id": document_id,
        "content": content,
        "page_number": page_number,
        "content_type": content_type,
        "document_name": document_name,
        "similarity": similarity,
    }


def _mock_embedder(return_value=None, side_effect=None):
    """Create a mock embedder that replaces GeminiOptimizedEmbeddings."""
    embedder = MagicMock()
    if side_effect:
        embedder.aembed_query = AsyncMock(side_effect=side_effect)
    else:
        embedder.aembed_query = AsyncMock(return_value=return_value or [0.1] * 768)
    return embedder


# =============================================================================
# Fixture: clear service cache between tests
# =============================================================================

@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the in-memory cache before every test."""
    from app.services.knowledge_visualization_service import _CACHE
    _CACHE.clear()
    yield
    _CACHE.clear()


# =============================================================================
# 1. TestScatter -- PCA/t-SNE scatter computation
# =============================================================================

class TestScatter:
    """Test compute_scatter for PCA/t-SNE dimensionality reduction."""

    @pytest.mark.asyncio
    async def test_pca_2d_returns_points(self):
        """PCA 2D on 10 embeddings returns 10 points with x, y."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id=f"c-{i}", document_id=f"doc-{i % 3}") for i in range(10)]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1", method="pca", dimensions=2, limit=500)

        assert result.method == "pca"
        assert result.dimensions == 2
        assert len(result.points) == 10
        for pt in result.points:
            assert pt.x is not None
            assert pt.y is not None
            assert pt.z is None  # 2D -> no z

    @pytest.mark.asyncio
    async def test_pca_3d_returns_z_coordinate(self):
        """PCA 3D on embeddings returns points with z coordinate."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id=f"c-{i}", document_id="doc-1") for i in range(10)]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1", method="pca", dimensions=3, limit=500)

        assert result.dimensions == 3
        assert len(result.points) == 10
        for pt in result.points:
            assert pt.z is not None

    @pytest.mark.asyncio
    async def test_tsne_small_dataset(self):
        """t-SNE on a small dataset (< 500 points, >= 5) uses t-SNE method."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id=f"c-{i}", document_id=f"doc-{i % 2}") for i in range(20)]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1", method="tsne", dimensions=2, limit=500)

        assert result.method == "tsne"
        assert len(result.points) == 20

    @pytest.mark.asyncio
    async def test_tsne_auto_fallback_to_pca_over_500(self):
        """t-SNE auto-falls back to PCA when point count exceeds 500."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id=f"c-{i}", document_id=f"doc-{i % 5}") for i in range(501)]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1", method="tsne", dimensions=2, limit=600)

        # Should fall back to PCA
        assert result.method == "pca"
        assert len(result.points) == 501

    @pytest.mark.asyncio
    async def test_tsne_fallback_pca_when_too_few_points(self):
        """t-SNE falls back to PCA when fewer than 5 points."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id=f"c-{i}", document_id="doc-1") for i in range(3)]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1", method="tsne", dimensions=2, limit=500)

        assert result.method == "pca"  # Fell back
        assert len(result.points) == 3

    @pytest.mark.asyncio
    async def test_scatter_empty_state(self):
        """Empty embeddings table returns empty result."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1")

        assert result.points == []
        assert result.documents == []
        assert result.computation_ms == 0

    @pytest.mark.asyncio
    async def test_scatter_cache_hit(self):
        """Second call with same params returns cached result (no DB hit)."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id="c-1", document_id="doc-1")]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result1 = await compute_scatter("org-1", method="pca", dimensions=2, limit=500)
            result2 = await compute_scatter("org-1", method="pca", dimensions=2, limit=500)

        # DB should only be called once (second call uses cache)
        assert conn.fetch.call_count == 1
        assert result1.method == result2.method
        assert len(result1.points) == len(result2.points)

    @pytest.mark.asyncio
    async def test_scatter_org_isolation(self):
        """Different org IDs produce different cache keys and results."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        rows_a = [_make_embedding_row(row_id="c-a1", document_id="doc-a1")]
        rows_b = [_make_embedding_row(row_id="c-b1", document_id="doc-b1"),
                   _make_embedding_row(row_id="c-b2", document_id="doc-b2")]
        conn.fetch = AsyncMock(side_effect=[rows_a, rows_b])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result_a = await compute_scatter("org-A", method="pca", dimensions=2, limit=500)
            result_b = await compute_scatter("org-B", method="pca", dimensions=2, limit=500)

        assert len(result_a.points) == 1
        assert len(result_b.points) == 2
        assert conn.fetch.call_count == 2  # Both hit DB (different orgs)

    @pytest.mark.asyncio
    async def test_scatter_document_colors_assigned(self):
        """Each document gets a unique color from the palette."""
        from app.services.knowledge_visualization_service import compute_scatter, DOC_COLORS

        pool, conn = _make_pool()
        rows = [
            _make_embedding_row(row_id="c-1", document_id="doc-1", document_name="a.pdf"),
            _make_embedding_row(row_id="c-2", document_id="doc-2", document_name="b.pdf"),
            _make_embedding_row(row_id="c-3", document_id="doc-1", document_name="a.pdf"),
        ]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1", method="pca", dimensions=2, limit=500)

        assert len(result.documents) == 2
        assert result.documents[0].color == DOC_COLORS[0]
        assert result.documents[1].color == DOC_COLORS[1]

    @pytest.mark.asyncio
    async def test_scatter_content_preview_truncation(self):
        """Content preview is truncated to 150 chars with ellipsis."""
        from app.services.knowledge_visualization_service import compute_scatter

        pool, conn = _make_pool()
        long_content = "A" * 300
        rows = [_make_embedding_row(row_id="c-1", content=long_content)]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_scatter("org-1")

        assert len(result.points[0].content_preview) == 153  # 150 + "..."


# =============================================================================
# 2. TestKnowledgeGraph -- node/edge creation, Mermaid, cross-doc similarity
# =============================================================================

class TestKnowledgeGraph:
    """Test compute_knowledge_graph for document/chunk graphs."""

    @pytest.mark.asyncio
    async def test_creates_document_and_chunk_nodes(self):
        """Graph has document nodes and chunk nodes connected by 'contains' edges."""
        from app.services.knowledge_visualization_service import compute_knowledge_graph

        pool, conn = _make_pool()
        doc_rows = [_make_doc_row("doc-1", "test.pdf")]
        emb = "[" + ",".join(str(x) for x in np.random.randn(128).tolist()) + "]"
        chunk_rows = [
            {"id": "c-1", "document_id": "doc-1", "content": "Chunk 1 content", "page_number": 1, "embedding": emb},
            {"id": "c-2", "document_id": "doc-1", "content": "Chunk 2 content", "page_number": 2, "embedding": emb},
        ]
        conn.fetch = AsyncMock(side_effect=[doc_rows, chunk_rows])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_knowledge_graph("org-1", max_nodes=50)

        doc_nodes = [n for n in result.nodes if n.node_type == "document"]
        chunk_nodes = [n for n in result.nodes if n.node_type == "chunk"]
        contains_edges = [e for e in result.edges if e.edge_type == "contains"]

        assert len(doc_nodes) == 1
        assert len(chunk_nodes) == 2
        assert len(contains_edges) == 2

    @pytest.mark.asyncio
    async def test_mermaid_generation(self):
        """Mermaid code is generated with graph LR header and class definitions."""
        from app.services.knowledge_visualization_service import compute_knowledge_graph

        pool, conn = _make_pool()
        doc_rows = [_make_doc_row("doc-1", "test.pdf")]
        emb = "[" + ",".join(str(x) for x in np.random.randn(128).tolist()) + "]"
        chunk_rows = [
            {"id": "c-1", "document_id": "doc-1", "content": "Hello world", "page_number": 1, "embedding": emb},
        ]
        conn.fetch = AsyncMock(side_effect=[doc_rows, chunk_rows])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_knowledge_graph("org-1")

        assert result.mermaid_code.startswith("graph LR")
        assert "classDef doc" in result.mermaid_code
        assert "classDef chunk" in result.mermaid_code
        assert ":::" in result.mermaid_code

    @pytest.mark.asyncio
    async def test_cross_doc_similarity_edges(self):
        """Chunks from different docs with cosine > 0.85 get 'similar_to' edges."""
        from app.services.knowledge_visualization_service import compute_knowledge_graph

        pool, conn = _make_pool()
        doc_rows = [
            _make_doc_row("doc-1", "a.pdf"),
            _make_doc_row("doc-2", "b.pdf"),
        ]
        # Two very similar embeddings from different docs
        base_vec = np.ones(128)
        vec_a = base_vec + np.random.randn(128) * 0.01
        vec_b = base_vec + np.random.randn(128) * 0.01

        emb_a = "[" + ",".join(str(x) for x in vec_a.tolist()) + "]"
        emb_b = "[" + ",".join(str(x) for x in vec_b.tolist()) + "]"

        chunk_rows = [
            {"id": "c-1", "document_id": "doc-1", "content": "Similar A", "page_number": 1, "embedding": emb_a},
            {"id": "c-2", "document_id": "doc-2", "content": "Similar B", "page_number": 1, "embedding": emb_b},
        ]
        conn.fetch = AsyncMock(side_effect=[doc_rows, chunk_rows])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_knowledge_graph("org-1")

        similar_edges = [e for e in result.edges if e.edge_type == "similar_to"]
        assert len(similar_edges) >= 1
        assert similar_edges[0].weight is not None
        assert similar_edges[0].weight > 0.85

    @pytest.mark.asyncio
    async def test_no_similarity_edges_within_same_doc(self):
        """Chunks from the SAME doc should not get similarity edges."""
        from app.services.knowledge_visualization_service import compute_knowledge_graph

        pool, conn = _make_pool()
        doc_rows = [_make_doc_row("doc-1", "only.pdf")]
        vec = np.ones(128)
        emb = "[" + ",".join(str(x) for x in vec.tolist()) + "]"
        chunk_rows = [
            {"id": "c-1", "document_id": "doc-1", "content": "Same doc A", "page_number": 1, "embedding": emb},
            {"id": "c-2", "document_id": "doc-1", "content": "Same doc B", "page_number": 2, "embedding": emb},
        ]
        conn.fetch = AsyncMock(side_effect=[doc_rows, chunk_rows])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_knowledge_graph("org-1")

        similar_edges = [e for e in result.edges if e.edge_type == "similar_to"]
        assert len(similar_edges) == 0

    @pytest.mark.asyncio
    async def test_knowledge_graph_empty_state(self):
        """No documents returns empty graph with placeholder Mermaid."""
        from app.services.knowledge_visualization_service import compute_knowledge_graph

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_knowledge_graph("org-1")

        assert result.nodes == []
        assert result.edges == []
        assert "empty" in result.mermaid_code or "Chua co" in result.mermaid_code
        assert result.computation_ms == 0

    @pytest.mark.asyncio
    async def test_graph_node_labels_truncated(self):
        """Document node labels are truncated to 40 chars."""
        from app.services.knowledge_visualization_service import compute_knowledge_graph

        pool, conn = _make_pool()
        long_name = "A" * 60 + ".pdf"
        doc_rows = [_make_doc_row("doc-1", long_name)]
        conn.fetch = AsyncMock(side_effect=[doc_rows, []])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            result = await compute_knowledge_graph("org-1")

        doc_node = [n for n in result.nodes if n.node_type == "document"][0]
        assert len(doc_node.label) <= 40


# =============================================================================
# 3. TestRagFlow -- embed -> retrieve -> grade pipeline
# =============================================================================

_EMBEDDER_PATCH = "app.services.knowledge_visualization_service.get_embedding_backend"


class TestRagFlow:
    """Test simulate_rag_flow for RAG retrieval simulation."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_results(self):
        """Full embed->retrieve->grade pipeline produces steps and graded chunks."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        rag_rows = [
            _make_rag_row(row_id="c-1", similarity=0.90, content="High relevance"),
            _make_rag_row(row_id="c-2", similarity=0.65, content="Medium relevance"),
            _make_rag_row(row_id="c-3", similarity=0.40, content="Low relevance"),
        ]
        conn.fetch = AsyncMock(return_value=rag_rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="maritime safety", top_k=10)

        assert result.query == "maritime safety"
        assert len(result.steps) == 3
        assert result.steps[0].name == "Embedding"
        assert result.steps[1].name == "Retrieval"
        assert result.steps[2].name == "Grading"
        assert len(result.chunks) == 3

    @pytest.mark.asyncio
    async def test_grade_threshold_relevant(self):
        """Similarity >= 0.75 is graded as 'relevant'."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(similarity=0.75)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="test", top_k=5)

        assert result.chunks[0].grade == "relevant"

    @pytest.mark.asyncio
    async def test_grade_threshold_partial(self):
        """Similarity >= 0.60 and < 0.75 is graded as 'partial'."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(similarity=0.65)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="test", top_k=5)

        assert result.chunks[0].grade == "partial"

    @pytest.mark.asyncio
    async def test_grade_threshold_irrelevant(self):
        """Similarity < 0.60 is graded as 'irrelevant'."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(similarity=0.50)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="test", top_k=5)

        assert result.chunks[0].grade == "irrelevant"

    @pytest.mark.asyncio
    async def test_grade_boundary_075(self):
        """Exactly 0.75 is 'relevant' (boundary test)."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(similarity=0.75)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="boundary", top_k=5)

        assert result.chunks[0].grade == "relevant"

    @pytest.mark.asyncio
    async def test_grade_boundary_060(self):
        """Exactly 0.60 is 'partial' (boundary test)."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(similarity=0.60)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="boundary", top_k=5)

        assert result.chunks[0].grade == "partial"

    @pytest.mark.asyncio
    async def test_doc_name_resolution_from_join(self):
        """Document name is resolved via JOIN with organization_documents."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(document_name="colregs.pdf")])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="test", top_k=5)

        assert result.chunks[0].document_name == "colregs.pdf"

    @pytest.mark.asyncio
    async def test_rag_flow_empty_results(self):
        """No chunks retrieved returns empty chunks list but still has steps."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="nothing", top_k=5)

        assert result.chunks == []
        assert len(result.steps) == 3  # Embedding, Retrieval, Grading still logged

    @pytest.mark.asyncio
    async def test_rag_flow_embedding_error_returns_early(self):
        """Embedding failure returns early with error step."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        with patch(_EMBEDDER_PATCH,
                   return_value=_mock_embedder(side_effect=RuntimeError("API key expired"))):
            result = await simulate_rag_flow("org-1", query="fail", top_k=5)

        assert len(result.steps) == 1
        assert result.steps[0].name == "Embedding"
        assert "Error" in result.steps[0].detail
        assert result.chunks == []

    @pytest.mark.asyncio
    async def test_rag_flow_content_preview_truncation(self):
        """Content preview is truncated to 200 chars."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        long_content = "B" * 400
        conn.fetch = AsyncMock(return_value=[_make_rag_row(content=long_content, similarity=0.80)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="test", top_k=5)

        assert len(result.chunks[0].content_preview) == 203  # 200 + "..."

    @pytest.mark.asyncio
    async def test_rag_flow_null_similarity(self):
        """Null similarity from DB is treated as 0.0 -> irrelevant."""
        from app.services.knowledge_visualization_service import simulate_rag_flow

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[_make_rag_row(similarity=None)])

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            with patch(_EMBEDDER_PATCH, return_value=_mock_embedder()):
                result = await simulate_rag_flow("org-1", query="null sim", top_k=5)

        assert result.chunks[0].grade == "irrelevant"
        assert result.chunks[0].similarity == 0.0


# =============================================================================
# 4. TestAPI -- feature gate, multi-tenant gate, org membership, param validation
# =============================================================================

class TestAPI:
    """Test API endpoint handler logic (called directly, not via TestClient)."""

    @pytest.mark.asyncio
    async def test_feature_gate_returns_403(self):
        """Endpoints return 403 when enable_knowledge_visualization=False."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        auth = _make_auth(role="student")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings(enable_knowledge_visualization=False)):
            with pytest.raises(Exception) as exc_info:
                await _require_org_member_viz(auth, "org-1")
            assert exc_info.value.status_code == 403
            assert "disabled" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_multi_tenant_gate_returns_403(self):
        """Endpoints return 403 when enable_multi_tenant=False."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        auth = _make_auth(role="student")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings(enable_multi_tenant=False)):
            with pytest.raises(Exception) as exc_info:
                await _require_org_member_viz(auth, "org-1")
            assert exc_info.value.status_code == 403
            assert "multi-tenant" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_admin_bypasses_membership_check(self):
        """Platform admin (role=admin) bypasses org membership check."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            user_id = await _require_org_member_viz(auth, "any-org")
            assert user_id == "admin-1"

    @pytest.mark.asyncio
    async def test_non_member_rejected(self):
        """Non-member of org gets 403."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        mock_repo = MagicMock()
        mock_repo.is_user_in_org = MagicMock(return_value=False)

        auth = _make_auth(user_id="outsider", role="student", org_id="private-org")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository",
                       return_value=mock_repo):
                with pytest.raises(Exception) as exc_info:
                    await _require_org_member_viz(auth, "private-org")
                assert exc_info.value.status_code == 403
                assert "member" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_member_passes_check(self):
        """Org member passes membership check."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        mock_repo = MagicMock()
        mock_repo.is_user_in_org = MagicMock(return_value=True)

        auth = _make_auth(user_id="member-1", role="student", org_id="my-org")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository",
                       return_value=mock_repo):
                user_id = await _require_org_member_viz(auth, "my-org")
                assert user_id == "member-1"

    @pytest.mark.asyncio
    async def test_missing_active_org_rejected_before_membership_lookup(self):
        """Non-admin calls need an active org before route org data is exposed."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        auth = _make_auth(user_id="member-1", role="student", org_id=None)
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository") as repo_factory:
                with pytest.raises(Exception) as exc_info:
                    await _require_org_member_viz(auth, "my-org")
                assert exc_info.value.status_code == 403
                assert exc_info.value.detail == "Organization context required for knowledge visualization"
                repo_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_org_mismatch_rejected_before_membership_lookup(self):
        """Route org must match active org for non-admin knowledge visualization."""
        from app.api.v1.knowledge_visualization import _require_org_member_viz

        auth = _make_auth(user_id="member-1", role="student", org_id="org-A")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository") as repo_factory:
                with pytest.raises(Exception) as exc_info:
                    await _require_org_member_viz(auth, "org-B")
                assert exc_info.value.status_code == 403
                assert exc_info.value.detail == "Active organization does not match route organization"
                repo_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_scatter_bad_method_returns_400(self):
        """Invalid method param (not pca/tsne) returns 400."""
        from app.api.v1.knowledge_visualization import get_knowledge_scatter

        request = _make_request(user_id="admin-1", role="admin")
        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with pytest.raises(Exception) as exc_info:
                await get_knowledge_scatter(request, "org-1", method="umap", dimensions=2, limit=500, auth=auth)
            assert exc_info.value.status_code == 400
            assert "method" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_scatter_bad_dimensions_returns_400(self):
        """Invalid dimensions param (not 2 or 3) returns 400."""
        from app.api.v1.knowledge_visualization import get_knowledge_scatter

        request = _make_request(user_id="admin-1", role="admin")
        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with pytest.raises(Exception) as exc_info:
                await get_knowledge_scatter(request, "org-1", method="pca", dimensions=4, limit=500, auth=auth)
            assert exc_info.value.status_code == 400
            assert "dimensions" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_scatter_bad_limit_too_low(self):
        """Limit < 10 returns 400."""
        from app.api.v1.knowledge_visualization import get_knowledge_scatter

        request = _make_request(user_id="admin-1", role="admin")
        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with pytest.raises(Exception) as exc_info:
                await get_knowledge_scatter(request, "org-1", method="pca", dimensions=2, limit=5, auth=auth)
            assert exc_info.value.status_code == 400
            assert "limit" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_scatter_bad_limit_too_high(self):
        """Limit > 2000 returns 400."""
        from app.api.v1.knowledge_visualization import get_knowledge_scatter

        request = _make_request(user_id="admin-1", role="admin")
        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with pytest.raises(Exception) as exc_info:
                await get_knowledge_scatter(request, "org-1", method="pca", dimensions=2, limit=3000, auth=auth)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_graph_bad_max_nodes_too_low(self):
        """max_nodes < 5 returns 400."""
        from app.api.v1.knowledge_visualization import get_knowledge_graph

        request = _make_request(user_id="admin-1", role="admin")
        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with pytest.raises(Exception) as exc_info:
                await get_knowledge_graph(request, "org-1", max_nodes=2, auth=auth)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_graph_bad_max_nodes_too_high(self):
        """max_nodes > 200 returns 400."""
        from app.api.v1.knowledge_visualization import get_knowledge_graph

        request = _make_request(user_id="admin-1", role="admin")
        auth = _make_auth(user_id="admin-1", role="admin")
        with patch("app.api.v1.knowledge_visualization.get_settings",
                    return_value=_make_settings()):
            with pytest.raises(Exception) as exc_info:
                await get_knowledge_graph(request, "org-1", max_nodes=300, auth=auth)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rag_flow_request_validation(self):
        """RagFlowRequest validates query and top_k fields."""
        from app.api.v1.knowledge_visualization import RagFlowRequest

        body = RagFlowRequest(query="test query", top_k=10)
        assert body.query == "test query"
        assert body.top_k == 10

        body2 = RagFlowRequest(query="minimal")
        assert body2.top_k == 10

    def test_rag_flow_request_rejects_empty_query(self):
        """RagFlowRequest rejects empty query string."""
        from app.api.v1.knowledge_visualization import RagFlowRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RagFlowRequest(query="")

    def test_rag_flow_request_rejects_too_high_top_k(self):
        """RagFlowRequest rejects top_k > 50."""
        from app.api.v1.knowledge_visualization import RagFlowRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RagFlowRequest(query="test", top_k=100)

    def test_rag_flow_request_rejects_zero_top_k(self):
        """RagFlowRequest rejects top_k = 0."""
        from app.api.v1.knowledge_visualization import RagFlowRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RagFlowRequest(query="test", top_k=0)

    def test_router_exists_with_correct_prefix(self):
        """Router is importable with /organizations prefix."""
        from app.api.v1.knowledge_visualization import router
        assert router is not None
        assert router.prefix == "/organizations"


# =============================================================================
# 5. TestCache -- TTL hit, TTL expiry, key generation
# =============================================================================

class TestCache:
    """Test in-memory TTL cache behavior."""

    def test_cache_set_and_get(self):
        """Value stored via _cache_set is retrievable via _cache_get."""
        from app.services.knowledge_visualization_service import _cache_set, _cache_get

        _cache_set("test-key", {"data": 42})
        result = _cache_get("test-key")
        assert result == {"data": 42}

    def test_cache_miss_returns_none(self):
        """Missing key returns None."""
        from app.services.knowledge_visualization_service import _cache_get

        result = _cache_get("nonexistent-key")
        assert result is None

    def test_cache_ttl_expiry(self):
        """Expired entry returns None and is evicted."""
        from app.services.knowledge_visualization_service import (
            _CACHE, _cache_set, _cache_get, _CACHE_TTL,
        )

        _cache_set("expiring-key", {"data": "old"})

        # Manually set the timestamp to the past (beyond TTL)
        _CACHE["expiring-key"] = (time.time() - _CACHE_TTL - 1, {"data": "old"})

        result = _cache_get("expiring-key")
        assert result is None
        assert "expiring-key" not in _CACHE

    def test_cache_key_generation_deterministic(self):
        """Same inputs produce the same cache key."""
        from app.services.knowledge_visualization_service import _cache_key

        key1 = _cache_key("org-1", "scatter", {"method": "pca", "dimensions": 2})
        key2 = _cache_key("org-1", "scatter", {"method": "pca", "dimensions": 2})
        assert key1 == key2

    def test_cache_key_different_orgs(self):
        """Different org_ids produce different keys."""
        from app.services.knowledge_visualization_service import _cache_key

        key_a = _cache_key("org-A", "scatter", {"method": "pca"})
        key_b = _cache_key("org-B", "scatter", {"method": "pca"})
        assert key_a != key_b

    def test_cache_key_different_functions(self):
        """Different function names produce different keys."""
        from app.services.knowledge_visualization_service import _cache_key

        key1 = _cache_key("org-1", "scatter", {"method": "pca"})
        key2 = _cache_key("org-1", "graph", {"method": "pca"})
        assert key1 != key2

    def test_cache_key_different_params(self):
        """Different params produce different keys."""
        from app.services.knowledge_visualization_service import _cache_key

        key1 = _cache_key("org-1", "scatter", {"method": "pca", "dimensions": 2})
        key2 = _cache_key("org-1", "scatter", {"method": "pca", "dimensions": 3})
        assert key1 != key2

    def test_cache_key_is_md5_hex(self):
        """Cache key is a valid MD5 hex digest."""
        from app.services.knowledge_visualization_service import _cache_key

        key = _cache_key("org-1", "scatter", {"method": "pca"})
        assert len(key) == 32
        int(key, 16)  # Valid hex

    def test_cache_eviction_on_large_size(self):
        """Cache evicts expired entries when exceeding 200 entries."""
        from app.services.knowledge_visualization_service import (
            _CACHE, _cache_set, _CACHE_TTL,
        )

        # Fill cache with expired entries
        expired_time = time.time() - _CACHE_TTL - 10
        for i in range(205):
            _CACHE[f"old-{i}"] = (expired_time, "stale")

        # New set should trigger eviction
        _cache_set("fresh-key", "new-value")

        # Expired entries should be cleaned
        remaining_old = sum(1 for k in _CACHE if k.startswith("old-"))
        assert remaining_old == 0
        assert _CACHE["fresh-key"][1] == "new-value"

    @pytest.mark.asyncio
    async def test_scatter_uses_cached_result(self):
        """compute_scatter returns cached result without DB call on second invocation."""
        from app.services.knowledge_visualization_service import compute_scatter, _CACHE

        pool, conn = _make_pool()
        rows = [_make_embedding_row(row_id="c-1")]
        conn.fetch = AsyncMock(return_value=rows)

        with patch("app.services.knowledge_visualization_service._get_pool", return_value=pool):
            r1 = await compute_scatter("org-1", method="pca", dimensions=2, limit=500)
            assert len(_CACHE) == 1
            r2 = await compute_scatter("org-1", method="pca", dimensions=2, limit=500)

        # Only 1 DB call (first time)
        assert conn.fetch.call_count == 1
        assert r1.method == r2.method


# =============================================================================
# 6. TestResponseModels -- Pydantic model validation
# =============================================================================

class TestResponseModels:
    """Test response model schemas are correct."""

    def test_scatter_point_2d(self):
        from app.services.knowledge_visualization_service import ScatterPoint
        pt = ScatterPoint(x=1.0, y=2.0, document_id="d1", document_name="a.pdf", content_preview="test")
        assert pt.z is None

    def test_scatter_point_3d(self):
        from app.services.knowledge_visualization_service import ScatterPoint
        pt = ScatterPoint(x=1.0, y=2.0, z=3.0, document_id="d1", document_name="a.pdf", content_preview="test")
        assert pt.z == 3.0

    def test_scatter_response_model(self):
        from app.services.knowledge_visualization_service import ScatterResponse
        resp = ScatterResponse(points=[], documents=[], method="pca", dimensions=2, computation_ms=100)
        assert resp.method == "pca"
        assert resp.computation_ms == 100

    def test_knowledge_graph_response_model(self):
        from app.services.knowledge_visualization_service import KnowledgeGraphResponse
        resp = KnowledgeGraphResponse(nodes=[], edges=[], mermaid_code="graph LR", computation_ms=50)
        assert resp.mermaid_code == "graph LR"

    def test_rag_flow_response_model(self):
        from app.services.knowledge_visualization_service import RagFlowResponse
        resp = RagFlowResponse(query="test", steps=[], chunks=[], computation_ms=200)
        assert resp.query == "test"

    def test_rag_flow_chunk_model(self):
        from app.services.knowledge_visualization_service import RagFlowChunk
        chunk = RagFlowChunk(
            chunk_id="c-1", document_id="d-1", document_name="test.pdf",
            content_preview="preview", similarity=0.85, grade="relevant",
        )
        assert chunk.grade == "relevant"
        assert chunk.page_number is None  # Optional

    def test_doc_colors_has_10_entries(self):
        from app.services.knowledge_visualization_service import DOC_COLORS
        assert len(DOC_COLORS) == 10
        for c in DOC_COLORS:
            assert c.startswith("#")
            assert len(c) == 7

    def test_cache_ttl_is_1800(self):
        from app.services.knowledge_visualization_service import _CACHE_TTL
        assert _CACHE_TTL == 1800
