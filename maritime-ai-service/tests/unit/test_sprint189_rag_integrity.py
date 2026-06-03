"""
Sprint 189: "Nạp Đúng — Trả Đúng" — RAG Ingestion Org Isolation + Source Accuracy

Tests:
1. TestIngestionOrgId — API endpoint accepts org_id, passes through pipeline
2. TestVisionProcessorOrgId — store_chunk_in_database includes organization_id in SQL
3. TestTextIngestionOrgId — TextIngestionRequest has org_id, passed to dense_repo
4. TestCitationContentType — Citation model has content_type, populated from HybridSearchResult
5. TestSourceDedup — generate_hybrid_citations deduplicates by (document_id, page_number)
6. TestOrgIdFallback — When no explicit org_id, uses get_effective_org_id()
7. TestRegressionNoOrg — When enable_multi_tenant=False, behavior unchanged
"""

import json
import pytest
from dataclasses import dataclass
from typing import Optional, List
from unittest.mock import AsyncMock, MagicMock, patch, call


# ═══════════════════════════════════════════════════════════════════
# 1. TestIngestionOrgId — API endpoint accepts org_id
# ═══════════════════════════════════════════════════════════════════

class TestIngestionOrgId:
    """Verify knowledge.py API endpoints accept and propagate organization_id."""

    def test_multimodal_endpoint_has_organization_id_param(self):
        """ingest_multimodal_document should accept organization_id Form param."""
        from app.api.v1.knowledge import ingest_multimodal_document
        import inspect

        sig = inspect.signature(ingest_multimodal_document)
        assert "organization_id" in sig.parameters, (
            "ingest_multimodal_document must accept organization_id parameter"
        )
        param = sig.parameters["organization_id"]
        assert param.default is not inspect.Parameter.empty, (
            "organization_id should have a default value (None)"
        )

    def test_text_ingestion_request_has_organization_id(self):
        """TextIngestionRequest model should have organization_id field."""
        from app.api.v1.knowledge import TextIngestionRequest

        req = TextIngestionRequest(
            content="test content",
            document_id="doc1",
            organization_id="org-123"
        )
        assert req.organization_id == "org-123"

    def test_text_ingestion_request_org_id_optional(self):
        """TextIngestionRequest.organization_id should default to None."""
        from app.api.v1.knowledge import TextIngestionRequest

        req = TextIngestionRequest(content="test", document_id="doc1")
        assert req.organization_id is None

    @pytest.mark.asyncio
    async def test_multimodal_passes_org_id_to_service(self):
        """ingest_multimodal_document should pass organization_id to service.ingest_pdf()."""
        from app.api.v1.knowledge import ingest_multimodal_document

        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.successful_pages = 1
        mock_result.total_pages = 1
        mock_result.failed_pages = 0
        mock_result.success_rate = 100.0
        mock_result.errors = []
        mock_result.document_id = "doc1"
        mock_result.vision_pages = 0
        mock_result.direct_pages = 1
        mock_result.fallback_pages = 0
        mock_result.api_savings_percent = 100.0
        mock_service.ingest_pdf = AsyncMock(return_value=mock_result)

        mock_file = MagicMock()
        mock_file.content_type = "application/pdf"
        mock_file.filename = "test.pdf"
        mock_file.read = AsyncMock(return_value=b"fake-pdf-content")

        mock_request = MagicMock()

        import tempfile
        import os

        with patch("app.api.v1.knowledge.get_ingestion_service", return_value=mock_service), \
             patch("app.api.v1.knowledge.validate_file"), \
             patch("tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):
            mock_tmp_instance = MagicMock()
            mock_tmp_instance.__enter__ = MagicMock(return_value=mock_tmp_instance)
            mock_tmp_instance.__exit__ = MagicMock(return_value=False)
            mock_tmp_instance.name = "/tmp/test.pdf"
            mock_tmp.return_value = mock_tmp_instance

            result = await ingest_multimodal_document(
                request=mock_request,
                auth=MagicMock(),
                background_tasks=MagicMock(),
                file=mock_file,
                document_id="doc1",
                organization_id="org-abc",
                resume=True,
                max_pages=None,
                start_page=None,
                end_page=None,
            )

            mock_service.ingest_pdf.assert_called_once()
            call_kwargs = mock_service.ingest_pdf.call_args[1]
            assert call_kwargs["organization_id"] == "org-abc"

    def test_multimodal_org_id_default_is_none(self):
        """organization_id parameter should have default=None in signature."""
        from app.api.v1.knowledge import ingest_multimodal_document
        import inspect

        sig = inspect.signature(ingest_multimodal_document)
        param = sig.parameters["organization_id"]
        # FastAPI Form(default=None) — the default.default is None
        default = param.default
        # At HTTP runtime, FastAPI resolves Form(None) → None
        # Just verify the parameter exists and has a None-ish default
        assert default is not inspect.Parameter.empty
        assert getattr(default, "default", None) is None or default is None


# ═══════════════════════════════════════════════════════════════════
# 2. TestVisionProcessorOrgId — store_chunk includes organization_id
# ═══════════════════════════════════════════════════════════════════

class TestVisionProcessorOrgId:
    """Verify VisionProcessor.store_chunk_in_database includes organization_id."""

    @pytest.mark.asyncio
    async def test_store_chunk_insert_includes_org_id(self):
        """INSERT SQL should include organization_id column."""
        from app.services.vision_processor import VisionProcessor

        processor = VisionProcessor.__new__(VisionProcessor)

        mock_session = MagicMock()
        mock_session.execute = MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        mock_session.commit = MagicMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.vision_processor.get_shared_session_factory", return_value=mock_factory), \
             patch("app.services.vision_processor.settings") as mock_settings:
            mock_settings.default_domain = "maritime"

            await processor.store_chunk_in_database(
                document_id="doc1",
                page_number=1,
                chunk_index=0,
                content="test content",
                contextual_content=None,
                embedding=[0.1] * 768,
                image_url="http://example.com/img.png",
                organization_id="org-test-123"
            )

            # Verify INSERT was called (2nd execute call, first is SELECT)
            calls = mock_session.execute.call_args_list
            assert len(calls) >= 2, "Expected at least 2 SQL executions (SELECT + INSERT)"

            select_call = calls[0]
            select_sql = str(select_call[0][0].text)
            assert "AND organization_id = :org_id" in select_sql

            insert_call = calls[1]
            sql_str = str(insert_call[0][0].text)
            assert "organization_id" in sql_str, "INSERT SQL must include organization_id column"

            params = insert_call[0][1]
            assert params["org_id"] == "org-test-123", "org_id param must be passed"

    @pytest.mark.asyncio
    async def test_store_chunk_update_includes_org_id(self):
        """UPDATE SQL should include organization_id = :org_id."""
        from app.services.vision_processor import VisionProcessor

        processor = VisionProcessor.__new__(VisionProcessor)

        mock_session = MagicMock()
        # First execute returns existing record
        mock_session.execute = MagicMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=("existing-id",)))
        )
        mock_session.commit = MagicMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.vision_processor.get_shared_session_factory", return_value=mock_factory), \
             patch("app.services.vision_processor.settings") as mock_settings:
            mock_settings.default_domain = "maritime"

            await processor.store_chunk_in_database(
                document_id="doc1",
                page_number=1,
                chunk_index=0,
                content="updated content",
                contextual_content=None,
                embedding=[0.2] * 768,
                image_url="http://example.com/img.png",
                organization_id="org-update-456"
            )

            calls = mock_session.execute.call_args_list
            assert len(calls) >= 2, "Expected at least 2 SQL executions (SELECT + UPDATE)"

            update_call = calls[1]
            sql_str = str(update_call[0][0].text)
            assert "AND organization_id = :org_id" in sql_str, "UPDATE SQL must filter organization_id"

            params = update_call[0][1]
            assert params["org_id"] == "org-update-456"

    @pytest.mark.asyncio
    async def test_process_page_passes_org_id(self):
        """process_page should pass organization_id to store_chunk_in_database."""
        from app.services.vision_processor import VisionProcessor

        processor = VisionProcessor.__new__(VisionProcessor)
        processor.hybrid_detection_enabled = False
        processor.force_vision_mode = False
        processor.entity_extraction_enabled = False

        # Mock storage
        mock_upload = MagicMock()
        mock_upload.success = True
        mock_upload.public_url = "http://example.com/img.png"
        processor.storage = MagicMock()
        processor.storage.upload_pil_image = AsyncMock(return_value=mock_upload)

        # Mock vision
        mock_extraction = MagicMock()
        mock_extraction.success = True
        mock_extraction.text = "Test text content"
        processor.vision = MagicMock()
        processor.vision.extract_from_image = AsyncMock(return_value=mock_extraction)
        processor.vision.validate_extraction = MagicMock(return_value=True)

        # Mock chunker
        mock_chunk = MagicMock()
        mock_chunk.chunk_index = 0
        mock_chunk.content = "Test text content"
        mock_chunk.content_type = "text"
        mock_chunk.confidence_score = 1.0
        mock_chunk.metadata = {}
        mock_chunk.contextual_content = None
        processor.chunker = MagicMock()
        processor.chunker.chunk_page_content = AsyncMock(return_value=[mock_chunk])

        # Mock embeddings
        processor.embeddings = MagicMock()
        processor.embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)

        # Mock bbox
        processor.bbox_extractor = MagicMock()

        # Mock context_enricher — not needed since contextual_rag_enabled is patched off

        # Mock store_chunk_in_database
        processor.store_chunk_in_database = AsyncMock()

        mock_image = MagicMock()

        with patch("app.services.vision_processor.settings") as mock_settings:
            mock_settings.default_domain = "maritime"
            mock_settings.contextual_rag_enabled = False
            mock_settings.enable_visual_rag = False

            await processor.process_page(
                image=mock_image,
                document_id="doc1",
                page_number=1,
                organization_id="org-page-789"
            )

            processor.store_chunk_in_database.assert_called_once()
            call_kwargs = processor.store_chunk_in_database.call_args[1]
            assert call_kwargs["organization_id"] == "org-page-789"


# ═══════════════════════════════════════════════════════════════════
# 3. TestTextIngestionOrgId
# ═══════════════════════════════════════════════════════════════════

class TestTextIngestionOrgId:
    """Verify text ingestion endpoint propagates organization_id."""

    def test_text_request_model_org_id_field(self):
        """TextIngestionRequest should have organization_id field."""
        from app.api.v1.knowledge import TextIngestionRequest

        schema = TextIngestionRequest.model_json_schema()
        assert "organization_id" in schema["properties"], (
            "TextIngestionRequest must have organization_id in schema"
        )

    def test_text_request_serializes_org_id(self):
        """TextIngestionRequest.organization_id should serialize correctly."""
        from app.api.v1.knowledge import TextIngestionRequest

        req = TextIngestionRequest(
            content="some content",
            document_id="doc1",
            organization_id="lms-hang-hai"
        )
        data = req.model_dump()
        assert data["organization_id"] == "lms-hang-hai"

    def test_text_request_org_id_in_json_schema(self):
        """TextIngestionRequest JSON schema should show organization_id as optional."""
        from app.api.v1.knowledge import TextIngestionRequest

        schema = TextIngestionRequest.model_json_schema()
        org_field = schema["properties"]["organization_id"]
        # Should accept null/None
        assert org_field.get("default") is None or "anyOf" in org_field or org_field.get("type") in ("string", None)


# ═══════════════════════════════════════════════════════════════════
# 4. TestCitationContentType
# ═══════════════════════════════════════════════════════════════════

class TestCitationContentType:
    """Verify Citation model includes content_type field."""

    def test_citation_has_content_type_field(self):
        """Citation model should have content_type field."""
        from app.models.knowledge_graph import Citation

        citation = Citation(
            node_id="n1",
            title="Test",
            source="KB",
            content_type="table"
        )
        assert citation.content_type == "table"

    def test_citation_content_type_defaults_none(self):
        """Citation.content_type should default to None."""
        from app.models.knowledge_graph import Citation

        citation = Citation(node_id="n1", title="Test", source="KB")
        assert citation.content_type is None

    def test_citation_content_type_in_schema(self):
        """Citation JSON schema should include content_type."""
        from app.models.knowledge_graph import Citation

        schema = Citation.model_json_schema()
        assert "content_type" in schema["properties"]

    def test_citation_serializes_content_type(self):
        """Citation should serialize content_type in model_dump."""
        from app.models.knowledge_graph import Citation

        citation = Citation(
            node_id="n1",
            title="Test Table",
            source="COLREGS",
            content_type="table"
        )
        data = citation.model_dump()
        assert data["content_type"] == "table"

    def test_citation_content_type_all_values(self):
        """Citation should accept all valid content_type values."""
        from app.models.knowledge_graph import Citation

        for ct in ["text", "table", "heading", "diagram_reference", "formula", "visual_description"]:
            c = Citation(node_id="n1", title="T", source="S", content_type=ct)
            assert c.content_type == ct

    def test_generate_hybrid_citations_includes_content_type(self):
        """generate_hybrid_citations should populate content_type from HybridSearchResult."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="n1",
                title="Table of Contents",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.9,
                content_type="table",
                page_number=5,
                document_id="doc1",
            ),
            HybridSearchResult(
                node_id="n2",
                title="Section Header",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.8,
                content_type="heading",
                page_number=6,
                document_id="doc1",
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        assert len(citations) == 2
        assert citations[0].content_type == "table"
        assert citations[1].content_type == "heading"

    def test_documents_to_citations_includes_content_type(self):
        """documents_to_citations should propagate content_type from doc dict."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever

        docs = [
            {
                "node_id": "n1",
                "title": "Test",
                "document_id": "doc1",
                "score": 0.9,
                "content_type": "formula",
            }
        ]

        citations = DocumentRetriever.documents_to_citations(docs)
        assert len(citations) == 1
        assert citations[0].content_type == "formula"

    def test_documents_to_citations_content_type_none(self):
        """documents_to_citations should handle missing content_type gracefully."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever

        docs = [{"node_id": "n1", "title": "Test", "document_id": "doc1"}]
        citations = DocumentRetriever.documents_to_citations(docs)
        assert citations[0].content_type is None


# ═══════════════════════════════════════════════════════════════════
# 5. TestSourceDedup
# ═══════════════════════════════════════════════════════════════════

class TestSourceDedup:
    """Verify source deduplication by (document_id, page_number)."""

    def test_dedup_same_page_different_chunks(self):
        """Multiple chunks from same page should produce only one citation."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="n1",
                title="Rule 5 - Lookout",
                content="Content chunk 1...",
                source="KB",
                category="regulation",
                rrf_score=0.95,
                page_number=15,
                document_id="colregs",
                chunk_index=0,
            ),
            HybridSearchResult(
                node_id="n2",
                title="Rule 5 - Lookout (cont)",
                content="Content chunk 2...",
                source="KB",
                category="regulation",
                rrf_score=0.90,
                page_number=15,
                document_id="colregs",
                chunk_index=1,
            ),
            HybridSearchResult(
                node_id="n3",
                title="Rule 5 - Lookout (more)",
                content="Content chunk 3...",
                source="KB",
                category="regulation",
                rrf_score=0.85,
                page_number=15,
                document_id="colregs",
                chunk_index=2,
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        assert len(citations) == 1, (
            f"Expected 1 citation for same page, got {len(citations)}"
        )
        assert citations[0].node_id == "n1"  # First (highest score) is kept

    def test_dedup_different_pages_kept(self):
        """Chunks from different pages should all be kept."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="n1",
                title="Page 10 content",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.9,
                page_number=10,
                document_id="colregs",
            ),
            HybridSearchResult(
                node_id="n2",
                title="Page 11 content",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.85,
                page_number=11,
                document_id="colregs",
            ),
            HybridSearchResult(
                node_id="n3",
                title="Page 12 content",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.8,
                page_number=12,
                document_id="colregs",
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        assert len(citations) == 3

    def test_dedup_different_documents_same_page(self):
        """Same page number from different documents should both be kept."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="n1",
                title="COLREGS Page 5",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.9,
                page_number=5,
                document_id="colregs",
            ),
            HybridSearchResult(
                node_id="n2",
                title="SOLAS Page 5",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.85,
                page_number=5,
                document_id="solas",
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        assert len(citations) == 2

    def test_dedup_no_document_id_not_deduped(self):
        """Results without document_id should not be deduped."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="n1",
                title="Result 1",
                content="...",
                source="KB",
                category="knowledge",
                rrf_score=0.9,
                document_id="",
            ),
            HybridSearchResult(
                node_id="n2",
                title="Result 2",
                content="...",
                source="KB",
                category="knowledge",
                rrf_score=0.85,
                document_id="",
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        assert len(citations) == 2

    def test_dedup_preserves_first_highest_score(self):
        """Dedup should keep the first result (highest RRF score) for each page."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="high_score",
                title="Best chunk",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.95,
                page_number=1,
                document_id="doc1",
            ),
            HybridSearchResult(
                node_id="low_score",
                title="Worse chunk",
                content="...",
                source="KB",
                category="regulation",
                rrf_score=0.50,
                page_number=1,
                document_id="doc1",
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        assert len(citations) == 1
        assert citations[0].node_id == "high_score"

    def test_dedup_mixed_with_and_without_doc_id(self):
        """Mix of results with/without document_id should work correctly."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever
        from app.engine.rrf_reranker import HybridSearchResult

        results = [
            HybridSearchResult(
                node_id="n1", title="Doc chunk", content="...",
                source="KB", category="r", rrf_score=0.9,
                page_number=5, document_id="colregs",
            ),
            HybridSearchResult(
                node_id="n2", title="No doc chunk", content="...",
                source="KB", category="r", rrf_score=0.85,
                document_id="",
            ),
            HybridSearchResult(
                node_id="n3", title="Same page chunk", content="...",
                source="KB", category="r", rrf_score=0.80,
                page_number=5, document_id="colregs",
            ),
        ]

        citations = DocumentRetriever.generate_hybrid_citations(results)
        # n1 (page 5, colregs), n2 (no doc_id), n3 (duplicate of n1)
        assert len(citations) == 2
        node_ids = [c.node_id for c in citations]
        assert "n1" in node_ids
        assert "n2" in node_ids
        assert "n3" not in node_ids

    def test_dedup_empty_results(self):
        """Empty results should return empty citations."""
        from app.engine.agentic_rag.document_retriever import DocumentRetriever

        citations = DocumentRetriever.generate_hybrid_citations([])
        assert citations == []


# ═══════════════════════════════════════════════════════════════════
# 6. TestOrgIdFallback
# ═══════════════════════════════════════════════════════════════════

class TestOrgIdFallback:
    """Verify knowledge ingestion resolves tenant scope without unsafe fallback."""

    @pytest.mark.asyncio
    async def test_vision_processor_uses_current_org_scope_when_none(self, monkeypatch):
        """When organization_id=None, store_chunk should use request org context."""
        from app.services.vision_processor import VisionProcessor
        from app.core.config import settings
        from app.core.org_context import current_org_id

        processor = VisionProcessor.__new__(VisionProcessor)

        mock_session = MagicMock()
        mock_session.execute = MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        mock_session.commit = MagicMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(settings, "default_domain", "maritime")
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production", raising=False)

        token = current_org_id.set("fallback-org")
        try:
            with patch(
                "app.services.vision_processor.get_shared_session_factory",
                return_value=mock_factory,
            ):
                await processor.store_chunk_in_database(
                    document_id="doc1",
                    page_number=1,
                    chunk_index=0,
                    content="content",
                    contextual_content=None,
                    embedding=[0.1] * 768,
                    image_url="",
                    organization_id=None  # No explicit org_id
                )
        finally:
            current_org_id.reset(token)

        insert_call = mock_session.execute.call_args_list[1]
        params = insert_call[0][1]
        assert params["org_id"] == "fallback-org"

    @pytest.mark.asyncio
    async def test_vision_processor_blocks_missing_org_context_before_db(self, monkeypatch):
        """Production multi-tenant ingestion must not default missing org scope."""
        from app.services.vision_processor import VisionProcessor
        from app.core.config import settings
        from app.core.org_context import current_org_id

        processor = VisionProcessor.__new__(VisionProcessor)
        get_factory = MagicMock()

        monkeypatch.setattr(settings, "default_domain", "maritime")
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production", raising=False)

        token = current_org_id.set(None)
        try:
            with patch("app.services.vision_processor.get_shared_session_factory", get_factory):
                with pytest.raises(RuntimeError, match="Organization context required"):
                    await processor.store_chunk_in_database(
                        document_id="PRIVATE-DOC",
                        page_number=1,
                        chunk_index=0,
                        content="PRIVATE CONTENT",
                        contextual_content=None,
                        embedding=[0.1] * 768,
                        image_url="",
                        organization_id=None,
                    )
        finally:
            current_org_id.reset(token)

        get_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_org_id_overrides_current_scope(self):
        """When organization_id is provided, it should be used instead of context."""
        from app.services.vision_processor import VisionProcessor

        processor = VisionProcessor.__new__(VisionProcessor)

        mock_session = MagicMock()
        mock_session.execute = MagicMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))
        mock_session.commit = MagicMock()

        mock_factory = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        with patch("app.services.vision_processor.get_shared_session_factory", return_value=mock_factory), \
             patch("app.services.vision_processor.settings") as mock_settings:
            mock_settings.default_domain = "maritime"

            await processor.store_chunk_in_database(
                document_id="doc1",
                page_number=1,
                chunk_index=0,
                content="content",
                contextual_content=None,
                embedding=[0.1] * 768,
                image_url="",
                organization_id="explicit-org"
            )

            insert_call = mock_session.execute.call_args_list[1]
            params = insert_call[0][1]
            assert params["org_id"] == "explicit-org"

    def test_get_effective_org_id_single_tenant(self):
        """When multi-tenant disabled, get_effective_org_id returns default."""
        # org_filter lazy-imports settings inside function body
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_multi_tenant = False
            mock_settings.default_organization_id = "default"

            from app.core.org_filter import get_effective_org_id
            result = get_effective_org_id()
            assert result == "default"

    def test_get_effective_org_id_multi_tenant_context(self):
        """When multi-tenant enabled, uses ContextVar."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_multi_tenant = True
            mock_settings.default_organization_id = "default"

            with patch("app.core.org_context.get_current_org_id", return_value="ctx-org"):
                from app.core.org_filter import get_effective_org_id
                result = get_effective_org_id()
                assert result == "ctx-org"


# ═══════════════════════════════════════════════════════════════════
# 7. TestRegressionNoOrg
# ═══════════════════════════════════════════════════════════════════

class TestRegressionNoOrg:
    """Verify backward compatibility when no org_id is provided."""

    def test_text_ingestion_backward_compat(self):
        """TextIngestionRequest without organization_id should still work."""
        from app.api.v1.knowledge import TextIngestionRequest

        # Old-style request without organization_id
        req = TextIngestionRequest(
            content="test content",
            document_id="doc1",
            domain_id="maritime",
            title="Test"
        )
        assert req.organization_id is None
        assert req.content == "test content"

    def test_citation_backward_compat(self):
        """Citation without content_type should still work."""
        from app.models.knowledge_graph import Citation

        citation = Citation(
            node_id="n1",
            title="Test",
            source="KB",
            relevance_score=0.9,
        )
        assert citation.content_type is None
        assert citation.relevance_score == 0.9

    def test_citation_dict_backward_compat(self):
        """Citation model_dump should not break existing consumers."""
        from app.models.knowledge_graph import Citation

        citation = Citation(node_id="n1", title="T", source="S")
        data = citation.model_dump()

        # All existing fields should be present
        assert "node_id" in data
        assert "title" in data
        assert "source" in data
        assert "relevance_score" in data
        assert "image_url" in data
        assert "page_number" in data
        assert "document_id" in data
        assert "bounding_boxes" in data
        # New field should be present too
        assert "content_type" in data

    def test_ingest_pdf_backward_compat(self):
        """ingest_pdf should work without organization_id parameter."""
        from app.services.multimodal_ingestion_service import MultimodalIngestionService
        import inspect

        sig = inspect.signature(MultimodalIngestionService.ingest_pdf)
        params = sig.parameters

        assert "organization_id" in params
        assert params["organization_id"].default is None, (
            "organization_id should default to None for backward compatibility"
        )

    def test_process_page_backward_compat(self):
        """VisionProcessor.process_page should work without organization_id."""
        from app.services.vision_processor import VisionProcessor
        import inspect

        sig = inspect.signature(VisionProcessor.process_page)
        params = sig.parameters

        assert "organization_id" in params
        assert params["organization_id"].default is None

    def test_store_chunk_backward_compat(self):
        """VisionProcessor.store_chunk_in_database should work without organization_id."""
        from app.services.vision_processor import VisionProcessor
        import inspect

        sig = inspect.signature(VisionProcessor.store_chunk_in_database)
        params = sig.parameters

        assert "organization_id" in params
        assert params["organization_id"].default is None


# ═══════════════════════════════════════════════════════════════════
# 8. TestIngestionServiceOrgIdPropagation
# ═══════════════════════════════════════════════════════════════════

class TestIngestionServiceOrgIdPropagation:
    """Verify MultimodalIngestionService threads org_id through to VisionProcessor."""

    def test_ingest_pdf_has_organization_id_param(self):
        """ingest_pdf method signature should include organization_id."""
        from app.services.multimodal_ingestion_service import MultimodalIngestionService
        import inspect

        sig = inspect.signature(MultimodalIngestionService.ingest_pdf)
        assert "organization_id" in sig.parameters

    def test_process_page_wrapper_has_organization_id(self):
        """_process_page wrapper should accept organization_id."""
        from app.services.multimodal_ingestion_service import MultimodalIngestionService
        import inspect

        sig = inspect.signature(MultimodalIngestionService._process_page)
        assert "organization_id" in sig.parameters

    @pytest.mark.asyncio
    async def test_ingest_pdf_passes_org_id_to_process_page(self):
        """ingest_pdf should pass organization_id to _process_page for each page."""
        from app.services.multimodal_ingestion_service import MultimodalIngestionService, PageResult

        service = MultimodalIngestionService.__new__(MultimodalIngestionService)
        service.hybrid_detection_enabled = False
        service._pdf_processor = MagicMock()
        service._vision_processor = MagicMock()

        # Mock PDF page count + conversion
        mock_image = MagicMock()
        mock_image.close = MagicMock()
        service._pdf_processor.get_pdf_page_count = MagicMock(return_value=1)
        service._pdf_processor.convert_pdf_to_images = MagicMock(
            return_value=([mock_image], 1)
        )

        # Mock page result
        mock_page_result = PageResult(
            page_number=1,
            success=True,
            text_length=100,
            total_chunks=2,
            extraction_method="direct"
        )

        service._process_page = AsyncMock(return_value=mock_page_result)
        service._load_progress = MagicMock(return_value=0)
        service._save_progress = MagicMock()
        service._clear_progress = MagicMock()

        with patch("app.services.multimodal_ingestion_service.settings") as mock_settings:
            mock_settings.default_domain = "maritime"

            result = await service.ingest_pdf(
                pdf_path="/tmp/test.pdf",
                document_id="doc1",
                organization_id="org-propagate-test"
            )

            service._process_page.assert_called_once()
            call_kwargs = service._process_page.call_args[1]
            assert call_kwargs["organization_id"] == "org-propagate-test"

    @pytest.mark.asyncio
    async def test_process_page_wrapper_passes_to_vision_processor(self):
        """_process_page wrapper should pass organization_id to VisionProcessor."""
        from app.services.multimodal_ingestion_service import MultimodalIngestionService, PageResult

        service = MultimodalIngestionService.__new__(MultimodalIngestionService)

        mock_result = PageResult(page_number=1, success=True)
        service._vision_processor = MagicMock()
        service._vision_processor.process_page = AsyncMock(return_value=mock_result)

        with patch("app.services.multimodal_ingestion_service.settings") as mock_settings:
            mock_settings.default_domain = "maritime"

            await service._process_page(
                image=MagicMock(),
                document_id="doc1",
                page_number=1,
                organization_id="org-wrapper-test"
            )

            service._vision_processor.process_page.assert_called_once()
            call_kwargs = service._vision_processor.process_page.call_args[1]
            assert call_kwargs["organization_id"] == "org-wrapper-test"
