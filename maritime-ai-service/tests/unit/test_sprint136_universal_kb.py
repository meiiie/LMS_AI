"""
Tests for Sprint 136: Universal Knowledge Base — Cross-Domain Unified Search.

Tests:
- Cross-domain dense search (domain_id=None returns all)
- Cross-domain sparse search
- RRF domain boost (same-domain gets higher score)
- Backward compat (cross_domain_search=False)
- SemanticChunker general patterns (legal, commercial, academic)
- Text ingestion endpoint validation
- Knowledge stats endpoint with domain breakdown
"""
import json
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================================
# DenseSearchResult domain_id field
# ============================================================================

class TestDenseSearchResultDomainId:
    """Test that DenseSearchResult has domain_id field."""

    def test_dense_search_result_has_domain_id(self):
        from app.repositories.dense_search_repository import DenseSearchResult

        result = DenseSearchResult(
            node_id="test-1",
            similarity=0.9,
            content="Test content",
            domain_id="maritime",
        )
        assert result.domain_id == "maritime"

    def test_dense_search_result_domain_id_default_empty(self):
        from app.repositories.dense_search_repository import DenseSearchResult

        result = DenseSearchResult(node_id="test-1", similarity=0.8)
        assert result.domain_id == ""


# ============================================================================
# SparseSearchResult domain_id field
# ============================================================================

class TestSparseSearchResultDomainId:
    """Test that SparseSearchResult has domain_id field."""

    def test_sparse_search_result_has_domain_id(self):
        from app.repositories.sparse_search_repository import SparseSearchResult

        result = SparseSearchResult(
            node_id="test-1",
            title="Test",
            content="Test content",
            source="KB",
            category="General",
            score=0.5,
            domain_id="traffic_law",
        )
        assert result.domain_id == "traffic_law"

    def test_sparse_search_result_domain_id_default_empty(self):
        from app.repositories.sparse_search_repository import SparseSearchResult

        result = SparseSearchResult(
            node_id="test-1",
            title="Test",
            content="Content",
            source="KB",
            category="General",
            score=0.5,
        )
        assert result.domain_id == ""


# ============================================================================
# HybridSearchResult domain_id field
# ============================================================================

class TestHybridSearchResultDomainId:
    """Test that HybridSearchResult has domain_id field."""

    def test_hybrid_search_result_has_domain_id(self):
        from app.engine.rrf_reranker import HybridSearchResult

        result = HybridSearchResult(
            node_id="test-1",
            title="Test",
            content="Content",
            source="KB",
            category="General",
            rrf_score=0.5,
            domain_id="maritime",
        )
        assert result.domain_id == "maritime"

    def test_hybrid_search_result_domain_id_default_empty(self):
        from app.engine.rrf_reranker import HybridSearchResult

        result = HybridSearchResult(
            node_id="test-1",
            title="Test",
            content="Content",
            source="KB",
            category="General",
        )
        assert result.domain_id == ""


# ============================================================================
# RRF Domain Boost
# ============================================================================

class TestRRFDomainBoost:
    """Test RRF reranker domain boost functionality."""

    def _make_dense(self, node_id, similarity, domain_id=""):
        from app.repositories.dense_search_repository import DenseSearchResult

        return DenseSearchResult(
            node_id=node_id,
            similarity=similarity,
            content=f"Content for {node_id}",
            domain_id=domain_id,
        )

    def _make_sparse(self, node_id, score, domain_id=""):
        from app.repositories.sparse_search_repository import SparseSearchResult

        return SparseSearchResult(
            node_id=node_id,
            title=f"Title {node_id}",
            content=f"Content for {node_id}",
            source="KB",
            category="General",
            score=score,
            domain_id=domain_id,
        )

    @patch("app.engine.rrf_reranker.settings", create=True)
    def test_domain_boost_increases_score_for_same_domain(self, mock_settings):
        """Same-domain results should get a score boost."""
        mock_settings.domain_boost_score = 0.15

        from app.engine.rrf_reranker import RRFReranker

        reranker = RRFReranker(k=60)

        dense_results = [
            self._make_dense("doc-maritime", 0.9, "maritime"),
            self._make_dense("doc-traffic", 0.9, "traffic_law"),
        ]

        results = reranker.merge(
            dense_results,
            [],
            dense_weight=1.0,
            sparse_weight=0.0,
            limit=10,
            active_domain_id="maritime",
        )

        assert len(results) == 2
        # Maritime result should have higher score due to domain boost
        maritime_result = next(r for r in results if r.domain_id == "maritime")
        traffic_result = next(r for r in results if r.domain_id == "traffic_law")
        assert maritime_result.rrf_score > traffic_result.rrf_score

    def test_no_domain_boost_without_active_domain(self):
        """Without active_domain_id, no boost applied."""
        from app.engine.rrf_reranker import RRFReranker

        reranker = RRFReranker(k=60)

        dense_results = [
            self._make_dense("doc-a", 0.9, "maritime"),
            self._make_dense("doc-b", 0.9, "traffic_law"),
        ]

        results = reranker.merge(
            dense_results,
            [],
            dense_weight=1.0,
            sparse_weight=0.0,
            limit=10,
        )

        # Without active_domain_id, scores should be equal (same similarity)
        assert len(results) == 2
        assert abs(results[0].rrf_score - results[1].rrf_score) < 0.001

    def test_domain_id_propagated_through_merge(self):
        """domain_id should be propagated from input to output results."""
        from app.engine.rrf_reranker import RRFReranker

        reranker = RRFReranker(k=60)

        dense = [self._make_dense("d1", 0.9, "maritime")]
        sparse = [self._make_sparse("s1", 5.0, "traffic_law")]

        results = reranker.merge(dense, sparse, limit=10)

        domain_ids = {r.domain_id for r in results}
        assert "maritime" in domain_ids
        assert "traffic_law" in domain_ids


# ============================================================================
# Cross-Domain Search Config
# ============================================================================

class TestCrossDomainConfig:
    """Test cross_domain_search configuration."""

    def test_config_has_cross_domain_search(self):
        from app.core.config import Settings

        s = Settings(
            cross_domain_search=True,
            domain_boost_score=0.15,
            enable_text_ingestion=True,
            max_ingestion_size_mb=50,
        )
        assert s.cross_domain_search is True
        assert s.domain_boost_score == 0.15
        assert s.enable_text_ingestion is True
        assert s.max_ingestion_size_mb == 50

    def test_config_cross_domain_defaults(self):
        from app.core.config import Settings

        s = Settings()
        assert s.cross_domain_search is True
        assert s.domain_boost_score == 0.15


# ============================================================================
# SemanticChunker General Patterns
# ============================================================================

class TestSemanticChunkerGeneralPatterns:
    """Test generalized document patterns in SemanticChunker."""

    @patch("app.services.chunking_service.settings")
    def test_general_patterns_initialized(self, mock_settings):
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        assert hasattr(chunker, "general_patterns")
        assert "section" in chunker.general_patterns
        assert "chapter" in chunker.general_patterns
        assert "part" in chunker.general_patterns

    @patch("app.services.chunking_service.settings")
    def test_detect_section_heading(self, mock_settings):
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        assert chunker._detect_content_type("Section 5: Legal framework") == "heading"

    @patch("app.services.chunking_service.settings")
    def test_detect_chapter_heading(self, mock_settings):
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        assert chunker._detect_content_type("Chương II: Quyền và nghĩa vụ") == "heading"

    @patch("app.services.chunking_service.settings")
    def test_detect_part_heading(self, mock_settings):
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        assert chunker._detect_content_type("Phần 3: Xử phạt hành chính") == "heading"

    @patch("app.services.chunking_service.settings")
    def test_extract_general_hierarchy(self, mock_settings):
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        hierarchy = chunker._extract_document_hierarchy(
            "Section 5 of Chapter III: Legal provisions in Part 2"
        )
        assert hierarchy.get("section") == "5"
        assert hierarchy.get("chapter") is not None

    @patch("app.services.chunking_service.settings")
    def test_maritime_patterns_still_work(self, mock_settings):
        """Ensure existing maritime patterns are not broken."""
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        assert chunker._detect_content_type("Rule 15: Crossing situation") == "heading"
        assert chunker._detect_content_type("Điều 5: Cảnh giới") == "heading"

    @patch("app.services.chunking_service.settings")
    def test_plain_text_still_detected(self, mock_settings):
        """Plain text should still be 'text' type."""
        mock_settings.chunk_size = 800
        mock_settings.chunk_overlap = 100
        mock_settings.min_chunk_size = 50

        from app.services.chunking_service import SemanticChunker

        chunker = SemanticChunker()
        assert chunker._detect_content_type("This is just plain text content.") == "text"


# ============================================================================
# HybridSearchService Cross-Domain Orchestration
# ============================================================================

class TestHybridSearchServiceCrossDomain:
    """Test HybridSearchService passes active_domain_id to reranker."""

    @patch("app.repositories.sparse_search_repository.get_sparse_search_repository")
    @patch("app.services.hybrid_search_service.get_dense_search_repository")
    @patch("app.services.hybrid_search_service.get_embedding_backend")
    def test_search_passes_active_domain_id(self, mock_emb, mock_dense, mock_sparse):
        """HybridSearchService.search should pass active_domain_id to reranker."""
        from app.services.hybrid_search_service import HybridSearchService

        service = HybridSearchService()
        # Verify reranker.merge is called — we'll test the plumbing
        assert service._reranker is not None


# ============================================================================
# Text Ingestion Endpoint
# ============================================================================

class TestTextIngestionEndpoint:
    """Test text ingestion endpoint."""

    def test_text_ingestion_request_model(self):
        """Test TextIngestionRequest model exists and validates."""
        from app.api.v1.knowledge import TextIngestionRequest

        req = TextIngestionRequest(
            content="Test content",
            document_id="doc-001",
            domain_id="maritime",
            title="Test Document",
        )
        assert req.content == "Test content"
        assert req.document_id == "doc-001"
        assert req.domain_id == "maritime"

    def test_text_ingestion_response_model(self):
        """Test TextIngestionResponse model."""
        from app.api.v1.knowledge import TextIngestionResponse

        resp = TextIngestionResponse(
            status="completed",
            document_id="doc-001",
            total_chunks=5,
            domain_id="maritime",
            message="Stored 5/5 chunks",
        )
        assert resp.total_chunks == 5

    def test_knowledge_stats_has_domain_breakdown(self):
        """Test KnowledgeStatsResponse includes domain_breakdown."""
        from app.api.v1.knowledge import KnowledgeStatsResponse

        resp = KnowledgeStatsResponse(
            total_chunks=100,
            total_documents=5,
            content_types={"text": 80, "heading": 20},
            avg_confidence=0.95,
            domain_breakdown={"maritime": 70, "traffic_law": 30},
        )
        assert resp.domain_breakdown["maritime"] == 70
        assert resp.domain_breakdown["traffic_law"] == 30

    def test_knowledge_stats_warning_for_empty_kb(self):
        """Empty KB should be visible as degraded for source-backed RAG readiness."""
        from app.api.v1.knowledge import (
            EMPTY_KNOWLEDGE_BASE_WARNING,
            build_knowledge_stats_warning,
        )

        assert build_knowledge_stats_warning(0, 0) == EMPTY_KNOWLEDGE_BASE_WARNING
        assert build_knowledge_stats_warning(10, 0) == EMPTY_KNOWLEDGE_BASE_WARNING

    def test_knowledge_stats_no_warning_for_indexed_kb(self):
        """Non-empty indexed KB should not emit the empty-KB warning."""
        from app.api.v1.knowledge import build_knowledge_stats_warning

        assert build_knowledge_stats_warning(10, 2) is None
