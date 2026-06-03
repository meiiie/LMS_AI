"""
Tests for Sprint 46: GraphRAGService coverage.

Tests graph-enhanced retrieval including:
- GraphEnhancedResult dataclass
- GraphRAGService init
- search (no results, with results, neo4j enrichment)
- _extract_entities_cached (cache hit, miss, expired, extraction error)
- _get_entity_context
- search_with_graph_context
- is_available, is_graph_available
- Entity cache TTL
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock


# ============================================================================
# GraphEnhancedResult
# ============================================================================


class TestGraphEnhancedResult:
    """Test GraphEnhancedResult dataclass."""

    def test_default_values(self):
        from app.services.graph_rag_service import GraphEnhancedResult
        result = GraphEnhancedResult(
            chunk_id="c1",
            content="Some content",
            score=0.85
        )
        assert result.chunk_id == "c1"
        assert result.score == 0.85
        assert result.related_entities == []
        assert result.related_regulations == []
        assert result.entity_context == ""
        assert result.search_method == "graph_enhanced"
        assert result.category == "Knowledge"

    def test_full_values(self):
        from app.services.graph_rag_service import GraphEnhancedResult
        result = GraphEnhancedResult(
            chunk_id="c1",
            content="Content",
            score=0.9,
            page_number=5,
            document_id="doc1",
            related_entities=[{"id": "e1", "name": "Rule 15"}],
            related_regulations=["Rule 15"],
            entity_context="About Rule 15",
            dense_score=0.88,
            sparse_score=0.75
        )
        assert result.page_number == 5
        assert len(result.related_entities) == 1
        assert result.dense_score == 0.88


# ============================================================================
# GraphRAGService init
# ============================================================================


class TestGraphRAGServiceInit:
    """Test GraphRAGService initialization."""

    def test_init_with_mocks(self):
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        assert svc._hybrid is mock_hybrid
        assert svc._neo4j is mock_neo4j
        assert svc._neo4j_available is True

    def test_neo4j_unavailable(self):
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        assert svc._neo4j_available is False


# ============================================================================
# search - no results
# ============================================================================


class TestSearchNoResults:
    """Test search when hybrid search returns empty."""

    @pytest.mark.asyncio
    async def test_empty_results(self):
        mock_hybrid = MagicMock()
        mock_hybrid.search = AsyncMock(return_value=[])
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        results = await svc.search("test query")
        assert results == []


# ============================================================================
# search - with results, no Neo4j
# ============================================================================


class TestSearchWithResults:
    """Test search with hybrid results."""

    @pytest.mark.asyncio
    async def test_results_without_neo4j(self):
        mock_result = MagicMock()
        mock_result.node_id = "n1"
        mock_result.content = "Rule 15 content"
        mock_result.rrf_score = 0.85
        mock_result.page_number = 5
        mock_result.document_id = "doc1"
        mock_result.image_url = None
        mock_result.bounding_boxes = None
        mock_result.category = "Knowledge"
        mock_result.search_method = "hybrid"
        mock_result.dense_score = 0.88
        mock_result.sparse_score = 0.75

        mock_hybrid = MagicMock()
        mock_hybrid.search = AsyncMock(return_value=[mock_result])
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        results = await svc.search("Rule 15")
        assert len(results) == 1
        assert results[0].chunk_id == "n1"
        assert results[0].content == "Rule 15 content"
        assert results[0].search_method == "hybrid"  # No Neo4j, keeps original


# ============================================================================
# search - with Neo4j enrichment
# ============================================================================


class TestSearchWithNeo4j:
    """Test search with Neo4j entity enrichment."""

    @pytest.mark.asyncio
    async def test_results_with_neo4j(self):
        mock_result = MagicMock()
        mock_result.node_id = "n1"
        mock_result.content = "Rule 15 content"
        mock_result.rrf_score = 0.85
        mock_result.page_number = 5
        mock_result.document_id = "doc1"
        mock_result.image_url = None
        mock_result.bounding_boxes = None
        mock_result.category = "Knowledge"
        mock_result.search_method = "hybrid"
        mock_result.dense_score = 0.88
        mock_result.sparse_score = 0.75

        mock_hybrid = MagicMock()
        mock_hybrid.search = AsyncMock(return_value=[mock_result])
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_document_entities = AsyncMock(return_value=[
            {"id": "e1", "name": "Rule 15", "type": "ARTICLE"}
        ])
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        results = await svc.search("Rule 15")
        assert len(results) == 1
        assert results[0].search_method == "graph_enhanced"
        assert len(results[0].related_entities) > 0
        assert "Rule 15" in results[0].related_regulations


# ============================================================================
# _extract_entities_cached
# ============================================================================


class TestExtractEntitiesCached:
    """Test entity extraction with caching."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear entity cache before each test."""
        import app.services.graph_rag_service as mod
        mod._entity_cache.clear()
        yield
        mod._entity_cache.clear()

    @pytest.mark.asyncio
    async def test_cache_miss_extracts(self):
        mock_extraction = MagicMock()
        mock_entity = MagicMock()
        mock_entity.id = "entity1"
        mock_extraction.entities = [mock_entity]

        mock_kg = MagicMock()
        mock_kg.is_available.return_value = True
        mock_kg.extract = AsyncMock(return_value=mock_extraction)

        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        entities = await svc._extract_entities_cached("What is Rule 15?")
        assert entities == ["entity1"]
        mock_kg.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        import app.services.graph_rag_service as mod
        mod._entity_cache["what is rule 15?"] = (["cached_entity"], time.time())

        mock_kg = MagicMock()
        mock_kg.is_available.return_value = True
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        entities = await svc._extract_entities_cached("What is Rule 15?")
        assert entities == ["cached_entity"]
        mock_kg.extract.assert_not_called()  # Should not call extract

    @pytest.mark.asyncio
    async def test_cache_expired(self):
        import app.services.graph_rag_service as mod
        # Set cache with expired timestamp (6 minutes ago)
        mod._entity_cache["what is rule 15?"] = (["old_entity"], time.time() - 360)

        mock_extraction = MagicMock()
        mock_entity = MagicMock()
        mock_entity.id = "new_entity"
        mock_extraction.entities = [mock_entity]

        mock_kg = MagicMock()
        mock_kg.is_available.return_value = True
        mock_kg.extract = AsyncMock(return_value=mock_extraction)
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        entities = await svc._extract_entities_cached("What is Rule 15?")
        assert entities == ["new_entity"]

    @pytest.mark.asyncio
    async def test_extraction_error(self):
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = True
        mock_kg.extract = AsyncMock(side_effect=Exception("LLM error"))
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        entities = await svc._extract_entities_cached("test")
        assert entities == []

    @pytest.mark.asyncio
    async def test_kg_not_available(self):
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = False
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        entities = await svc._extract_entities_cached("test")
        assert entities == []


# ============================================================================
# _get_entity_context
# ============================================================================


class TestGetEntityContext:
    """Test _get_entity_context."""

    @pytest.mark.asyncio
    async def test_with_document_entities(self):
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_document_entities = AsyncMock(return_value=[
            {"id": "e1", "name": "Rule 15", "type": "ARTICLE"},
            {"id": "e2", "name": "Crossing", "type": "CONCEPT"}
        ])
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_hybrid = MagicMock()
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        context = await svc._get_entity_context("doc1", [])
        assert len(context["entities"]) == 2
        assert "Rule 15" in context["regulations"]
        assert "Rule 15" in context["summary"]

    @pytest.mark.asyncio
    async def test_passes_current_org_to_neo4j(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_result = MagicMock()
        mock_result.node_id = "n1"
        mock_result.content = "Rule 15 content"
        mock_result.rrf_score = 0.85
        mock_result.page_number = 5
        mock_result.document_id = "doc1"
        mock_result.image_url = None
        mock_result.bounding_boxes = None
        mock_result.category = "Knowledge"
        mock_result.search_method = "hybrid"
        mock_result.dense_score = 0.88
        mock_result.sparse_score = 0.75

        mock_hybrid = MagicMock()
        mock_hybrid.search = AsyncMock(return_value=[mock_result])
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = True
        mock_entity = MagicMock()
        mock_entity.id = "entity1"
        mock_kg.extract = AsyncMock(return_value=MagicMock(entities=[mock_entity]))

        from app.services.graph_rag_service import GraphRAGService
        import app.services.graph_rag_service as mod
        mod._entity_cache.clear()

        token = current_org_id.set("org-service")
        try:
            svc = GraphRAGService(
                hybrid_service=mock_hybrid,
                neo4j_repo=mock_neo4j,
                kg_builder=mock_kg,
            )
            await svc.search("Rule 15")
        finally:
            current_org_id.reset(token)
            mod._entity_cache.clear()

        mock_neo4j.get_document_entities.assert_awaited_once_with(
            "doc1",
            organization_id="org-service",
        )
        mock_neo4j.get_entity_relations.assert_awaited_once_with(
            "entity1",
            organization_id="org-service",
        )

    @pytest.mark.asyncio
    async def test_with_query_entities(self):
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[
            {"target_type": "ARTICLE", "target_name": "Rule 17"}
        ])
        mock_hybrid = MagicMock()
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        context = await svc._get_entity_context(None, ["entity1"])
        assert "Rule 17" in context["regulations"]

    @pytest.mark.asyncio
    async def test_no_document_no_entities(self):
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_hybrid = MagicMock()
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        context = await svc._get_entity_context(None, [])
        assert context["entities"] == []
        assert context["regulations"] == []
        assert context["summary"] == ""


# ============================================================================
# search_with_graph_context
# ============================================================================


class TestSearchWithGraphContext:
    """Test search_with_graph_context."""

    @pytest.mark.asyncio
    async def test_returns_results_and_context(self):
        mock_result = MagicMock()
        mock_result.node_id = "n1"
        mock_result.content = "Content"
        mock_result.rrf_score = 0.9
        mock_result.page_number = 1
        mock_result.document_id = "doc1"
        mock_result.image_url = None
        mock_result.bounding_boxes = None
        mock_result.category = "Knowledge"
        mock_result.search_method = "hybrid"
        mock_result.dense_score = 0.9
        mock_result.sparse_score = 0.8

        mock_hybrid = MagicMock()
        mock_hybrid.search = AsyncMock(return_value=[mock_result])
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_document_entities = AsyncMock(return_value=[
            {"id": "e1", "name": "Rule 15", "type": "ARTICLE"}
        ])
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_kg = MagicMock()
        mock_kg.is_available.return_value = False

        from app.services.graph_rag_service import GraphRAGService
        # Clear entity cache
        import app.services.graph_rag_service as mod
        mod._entity_cache.clear()

        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        results, context_str = await svc.search_with_graph_context("Rule 15")
        assert len(results) == 1
        assert "Rule 15" in context_str


# ============================================================================
# is_available, is_graph_available
# ============================================================================


class TestAvailability:
    """Test availability checks."""

    def test_is_available(self):
        mock_hybrid = MagicMock()
        mock_hybrid.is_available.return_value = True
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        assert svc.is_available() is True

    def test_is_graph_available(self):
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        assert svc.is_graph_available() is True

    def test_is_graph_unavailable(self):
        mock_hybrid = MagicMock()
        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False
        mock_kg = MagicMock()

        from app.services.graph_rag_service import GraphRAGService
        svc = GraphRAGService(
            hybrid_service=mock_hybrid,
            neo4j_repo=mock_neo4j,
            kg_builder=mock_kg
        )
        assert svc.is_graph_available() is False
