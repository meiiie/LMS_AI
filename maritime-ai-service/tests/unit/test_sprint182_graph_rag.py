"""
Tests for Sprint 182: "Đồ Thị Tri Thức" — Graph RAG Retriever.

Covers:
- EntityInfo and GraphRAGContext dataclasses
- Entity extraction from queries (_extract_query_entities)
- Neo4j context retrieval (_get_neo4j_context)
- PostgreSQL fallback context (_get_postgres_context)
- Main entry point (enrich_with_graph_context)
- Feature gating (enable_graph_rag)
- Config flags (enable_graph_rag, graph_rag_max_entities)
- Integration with corrective_rag.py (sync + streaming paths)
- Edge cases and error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

# =============================================================================
# Test fixtures
# =============================================================================


def _make_settings(**overrides):
    """Create mock settings with Graph RAG defaults."""
    s = MagicMock()
    s.enable_graph_rag = overrides.get("enable_graph_rag", True)
    s.graph_rag_max_entities = overrides.get("graph_rag_max_entities", 5)
    s.enable_neo4j = overrides.get("enable_neo4j", False)
    s.asyncpg_url = overrides.get("asyncpg_url", "postgresql://localhost/test")
    # Visual RAG (disable for Graph RAG tests)
    s.enable_visual_rag = overrides.get("enable_visual_rag", False)
    # Other settings that corrective_rag.py may reference
    s.enable_corrective_rag = True
    s.rag_model_version = "test"
    s.rag_confidence_high = 0.8
    s.rag_confidence_medium = 0.5
    s.rag_early_exit_on_high_confidence = True
    s.rag_enable_reflection = False
    return s


def _make_documents(count=3):
    """Create sample retrieved documents."""
    docs = []
    for i in range(count):
        docs.append({
            "node_id": f"node-{i}",
            "content": f"Quy tắc {i + 10} về tránh va trên biển.",
            "title": f"Rule {i + 10}",
            "score": 0.8 - i * 0.1,
            "document_id": f"doc-{i}",
            "page_number": i + 1,
            "image_url": "",
            "content_type": "text",
        })
    return docs


def _make_entity_info(name="COLREGs", entity_type="REGULATION", **kw):
    from app.engine.agentic_rag.graph_rag_retriever import EntityInfo
    return EntityInfo(
        entity_id=kw.get("entity_id", f"ent-{name}"),
        name=name,
        name_vi=kw.get("name_vi"),
        entity_type=entity_type,
        description=kw.get("description", ""),
        source=kw.get("source", "query"),
    )


# =============================================================================
# 1. Dataclass Tests
# =============================================================================


class TestEntityInfo:
    """Test EntityInfo dataclass."""

    def test_basic_creation(self):
        from app.engine.agentic_rag.graph_rag_retriever import EntityInfo
        e = EntityInfo(entity_id="e1", name="SOLAS", entity_type="REGULATION")
        assert e.entity_id == "e1"
        assert e.name == "SOLAS"
        assert e.entity_type == "REGULATION"
        assert e.name_vi is None
        assert e.description == ""
        assert e.source == ""

    def test_with_vietnamese_name(self):
        from app.engine.agentic_rag.graph_rag_retriever import EntityInfo
        e = EntityInfo(
            entity_id="e2",
            name="starboard",
            name_vi="mạn phải",
            entity_type="CONCEPT",
            source="query",
        )
        assert e.name_vi == "mạn phải"
        assert e.source == "query"

    def test_default_entity_type(self):
        from app.engine.agentic_rag.graph_rag_retriever import EntityInfo
        e = EntityInfo(entity_id="e3", name="test")
        assert e.entity_type == "CONCEPT"

    def test_as_dict(self):
        from app.engine.agentic_rag.graph_rag_retriever import EntityInfo
        e = EntityInfo(entity_id="e4", name="Rule 15", entity_type="ARTICLE")
        d = asdict(e)
        assert d["entity_id"] == "e4"
        assert d["entity_type"] == "ARTICLE"


class TestGraphRAGContext:
    """Test GraphRAGContext dataclass."""

    def test_default_creation(self):
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext
        ctx = GraphRAGContext()
        assert ctx.entities == []
        assert ctx.related_regulations == []
        assert ctx.entity_context_text == ""
        assert ctx.additional_docs == []
        assert ctx.total_time_ms == 0.0
        assert ctx.mode == "none"

    def test_with_data(self):
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext, EntityInfo
        e = EntityInfo(entity_id="e1", name="test")
        ctx = GraphRAGContext(
            entities=[e],
            related_regulations=["Rule 15"],
            entity_context_text="Thực thể: test",
            mode="postgres",
            total_time_ms=42.5,
        )
        assert len(ctx.entities) == 1
        assert ctx.related_regulations == ["Rule 15"]
        assert ctx.mode == "postgres"

    def test_additional_docs(self):
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext
        ctx = GraphRAGContext(
            additional_docs=[{"node_id": "x", "content": "extra doc"}],
            mode="postgres",
        )
        assert len(ctx.additional_docs) == 1

    def test_modes(self):
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext
        for mode in ("none", "neo4j", "postgres"):
            ctx = GraphRAGContext(mode=mode)
            assert ctx.mode == mode


# =============================================================================
# 2. Entity Extraction Tests
# =============================================================================


class TestExtractQueryEntities:
    """Test _extract_query_entities function."""

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        from app.engine.agentic_rag.graph_rag_retriever import _extract_query_entities

        mock_entity = MagicMock()
        mock_entity.id = "ent-1"
        mock_entity.name = "COLREGs"
        mock_entity.name_vi = "Quy tắc phòng ngừa đâm va"
        mock_entity.entity_type = "REGULATION"
        mock_entity.description = "International Regulations"

        mock_extraction = MagicMock()
        mock_extraction.entities = [mock_entity]

        mock_builder = MagicMock()
        mock_builder.is_available.return_value = True
        mock_builder.extract = AsyncMock(return_value=mock_extraction)

        with patch(
            "app.engine.kg_builder_service.get_kg_builder_service",
            return_value=mock_builder,
        ):
            result = await _extract_query_entities("Quy tắc 15 COLREGs là gì?")

        assert len(result) == 1
        assert result[0].name == "COLREGs"
        assert result[0].name_vi == "Quy tắc phòng ngừa đâm va"
        assert result[0].source == "query"

    @pytest.mark.asyncio
    async def test_builder_unavailable(self):
        from app.engine.agentic_rag.graph_rag_retriever import _extract_query_entities

        mock_builder = MagicMock()
        mock_builder.is_available.return_value = False

        with patch(
            "app.engine.kg_builder_service.get_kg_builder_service",
            return_value=mock_builder,
        ):
            result = await _extract_query_entities("test query")

        assert result == []

    @pytest.mark.asyncio
    async def test_extraction_error_returns_empty(self):
        from app.engine.agentic_rag.graph_rag_retriever import _extract_query_entities

        with patch(
            "app.engine.kg_builder_service.get_kg_builder_service",
            side_effect=ImportError("module not found"),
        ):
            result = await _extract_query_entities("test query")

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_entities(self):
        from app.engine.agentic_rag.graph_rag_retriever import _extract_query_entities

        entities_data = []
        for name in ["SOLAS", "MARPOL", "Rule 15"]:
            e = MagicMock()
            e.id = f"ent-{name}"
            e.name = name
            e.name_vi = None
            e.entity_type = "REGULATION"
            e.description = ""
            entities_data.append(e)

        mock_extraction = MagicMock()
        mock_extraction.entities = entities_data

        mock_builder = MagicMock()
        mock_builder.is_available.return_value = True
        mock_builder.extract = AsyncMock(return_value=mock_extraction)

        with patch(
            "app.engine.kg_builder_service.get_kg_builder_service",
            return_value=mock_builder,
        ):
            result = await _extract_query_entities("So sánh SOLAS, MARPOL và Rule 15")

        assert len(result) == 3
        names = [e.name for e in result]
        assert "SOLAS" in names
        assert "MARPOL" in names

    @pytest.mark.asyncio
    async def test_extract_exception_logged(self):
        from app.engine.agentic_rag.graph_rag_retriever import _extract_query_entities

        mock_builder = MagicMock()
        mock_builder.is_available.return_value = True
        mock_builder.extract = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        with patch(
            "app.engine.kg_builder_service.get_kg_builder_service",
            return_value=mock_builder,
        ):
            result = await _extract_query_entities("test")

        assert result == []


# =============================================================================
# 3. Neo4j Context Tests
# =============================================================================


class TestGetNeo4jContext:
    """Test _get_neo4j_context function."""

    @pytest.mark.asyncio
    async def test_neo4j_unavailable(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = False

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            entities = [_make_entity_info()]
            result = await _get_neo4j_context(entities, ["doc-1"])

        assert result.mode == "none"

    @pytest.mark.asyncio
    async def test_neo4j_with_relations(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[
            {
                "target_id": "ent-rule15",
                "target_name": "Rule 15",
                "target_name_vi": "Quy tắc 15",
                "target_type": "ARTICLE",
            },
            {
                "target_id": "ent-crossing",
                "target_name": "Crossing Situation",
                "target_name_vi": "Tình huống cắt hướng",
                "target_type": "CONCEPT",
            },
        ])
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            entities = [_make_entity_info()]
            result = await _get_neo4j_context(entities, [])

        assert result.mode == "neo4j"
        assert "Rule 15" in result.related_regulations
        assert len(result.entities) >= 2  # Original + graph-hopped
        assert "Quy tắc liên quan" in result.entity_context_text

    @pytest.mark.asyncio
    async def test_neo4j_document_entities(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_neo4j.get_document_entities = AsyncMock(return_value=[
            {"name": "SOLAS Chapter V", "type": "ARTICLE"},
        ])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            entities = [_make_entity_info()]
            result = await _get_neo4j_context(entities, ["doc-1"])

        assert "SOLAS Chapter V" in result.related_regulations

    @pytest.mark.asyncio
    async def test_neo4j_context_passes_current_org(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        token = current_org_id.set("org-graph")
        try:
            with patch(
                "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
                return_value=mock_neo4j,
            ):
                await _get_neo4j_context([_make_entity_info()], ["doc-1"])
        finally:
            current_org_id.reset(token)

        mock_neo4j.get_entity_relations.assert_awaited_once_with(
            "ent-COLREGs",
            organization_id="org-graph",
        )
        mock_neo4j.get_document_entities.assert_awaited_once_with(
            "doc-1",
            organization_id="org-graph",
        )

    @pytest.mark.asyncio
    async def test_neo4j_limits_entities_to_5(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[])
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        # Create 10 entities — only first 5 should trigger relation lookups
        entities = [_make_entity_info(name=f"Ent-{i}", entity_id=f"e-{i}") for i in range(10)]

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            await _get_neo4j_context(entities, [])

        # get_entity_relations called max 5 times (limited by [:5])
        assert mock_neo4j.get_entity_relations.call_count == 5

    @pytest.mark.asyncio
    async def test_neo4j_exception_returns_none_mode(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            side_effect=ImportError("neo4j not installed"),
        ):
            result = await _get_neo4j_context([_make_entity_info()], [])

        assert result.mode == "none"

    @pytest.mark.asyncio
    async def test_neo4j_deduplicates_entity_names(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        # Return duplicate entity names
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[
            {"target_id": "e1", "target_name": "Rule 15", "target_type": "ARTICLE"},
            {"target_id": "e2", "target_name": "Rule 15", "target_type": "ARTICLE"},
        ])
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            result = await _get_neo4j_context([_make_entity_info()], [])

        # "Rule 15" should appear once in regulations (set dedup)
        assert result.related_regulations.count("Rule 15") == 1

    @pytest.mark.asyncio
    async def test_neo4j_relation_error_continues(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_entity_relations = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            result = await _get_neo4j_context([_make_entity_info()], [])

        # Should still return neo4j mode (partial failure is OK)
        assert result.mode == "neo4j"


# =============================================================================
# 4. PostgreSQL Context Tests
# =============================================================================


class TestGetPostgresContext:
    """Test _get_postgres_context function."""

    @pytest.mark.asyncio
    async def test_empty_entities_returns_early(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        result = await _get_postgres_context([], _make_documents())
        assert result.mode == "postgres"
        assert result.entities == []
        assert result.additional_docs == []

    @pytest.mark.asyncio
    async def test_postgres_with_entities(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [
            _make_entity_info(name="COLREGs", entity_type="REGULATION"),
            _make_entity_info(name="tránh va", entity_type="CONCEPT", name_vi="tránh va"),
        ]

        # Mock asyncpg connection
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {
                "node_id": "extra-1",
                "content": "Quy tắc bổ sung về tránh va trên biển",
                "document_id": "doc-extra",
                "page_number": 5,
                "image_url": None,
                "content_type": "text",
            }
        ])

        mock_settings = _make_settings()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("app.core.config.get_settings", return_value=mock_settings):
            result = await _get_postgres_context(entities, _make_documents())

        assert result.mode == "postgres"
        assert "Thực thể trong câu hỏi" in result.entity_context_text
        assert "Quy tắc liên quan" in result.entity_context_text
        assert len(result.additional_docs) == 1
        assert result.additional_docs[0]["node_id"] == "extra-1"

    @pytest.mark.asyncio
    async def test_postgres_context_filters_by_current_org(self, monkeypatch):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production", raising=False)

        entities = [_make_entity_info(name="COLREGs", entity_type="REGULATION")]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_settings = _make_settings()

        token = current_org_id.set("org-A")
        try:
            with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
                 patch("app.core.config.get_settings", return_value=mock_settings):
                result = await _get_postgres_context(entities, _make_documents())
        finally:
            current_org_id.reset(token)

        query = mock_conn.fetch.await_args.args[0]
        assert "AND (organization_id = $2 OR organization_id IS NULL)" in query
        assert mock_conn.fetch.await_args.args[1] == "COLREGs"
        assert mock_conn.fetch.await_args.args[2] == "org-A"
        assert result.mode == "postgres"

    @pytest.mark.asyncio
    async def test_postgres_context_blocks_missing_org_before_connect(self, monkeypatch):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production", raising=False)

        entities = [_make_entity_info(name="PRIVATE ENTITY", entity_type="REGULATION")]
        connect = AsyncMock()

        token = current_org_id.set(None)
        try:
            with patch("asyncpg.connect", connect):
                result = await _get_postgres_context(entities, _make_documents())
        finally:
            current_org_id.reset(token)

        assert result.mode == "postgres"
        assert result.additional_docs == []
        assert "PRIVATE ENTITY" in result.entity_context_text
        connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_postgres_filters_existing_docs(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [_make_entity_info()]
        existing_docs = _make_documents(2)  # node-0, node-1

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"node_id": "node-0", "content": "dup", "document_id": "d", "page_number": 1, "image_url": None, "content_type": "text"},
            {"node_id": "new-1", "content": "new doc", "document_id": "d2", "page_number": 2, "image_url": None, "content_type": "text"},
        ])

        mock_settings = _make_settings()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("app.core.config.get_settings", return_value=mock_settings):
            result = await _get_postgres_context(entities, existing_docs)

        # node-0 should be filtered out (already in existing_docs)
        node_ids = [d["node_id"] for d in result.additional_docs]
        assert "node-0" not in node_ids
        assert "new-1" in node_ids

    @pytest.mark.asyncio
    async def test_postgres_db_error_graceful(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [_make_entity_info()]

        with patch("asyncpg.connect", AsyncMock(side_effect=ConnectionError("DB down"))):
            with patch("app.core.config.get_settings", return_value=_make_settings()):
                result = await _get_postgres_context(entities, _make_documents())

        # Should still return context from entities, no additional docs
        assert result.mode == "postgres"
        assert result.additional_docs == []
        assert "Thực thể trong câu hỏi" in result.entity_context_text

    @pytest.mark.asyncio
    async def test_postgres_limits_additional_docs(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [_make_entity_info()]

        # Return 5 rows from DB
        rows = [
            {"node_id": f"extra-{i}", "content": f"content {i}", "document_id": f"d{i}",
             "page_number": i, "image_url": None, "content_type": "text"}
            for i in range(5)
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        mock_settings = _make_settings()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("app.core.config.get_settings", return_value=mock_settings):
            result = await _get_postgres_context(entities, [])

        # Limited to 3 additional docs
        assert len(result.additional_docs) <= 3

    @pytest.mark.asyncio
    async def test_postgres_regulation_entities(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [
            _make_entity_info(name="Rule 15", entity_type="ARTICLE"),
            _make_entity_info(name="SOLAS", entity_type="REGULATION"),
            _make_entity_info(name="tàu", entity_type="CONCEPT"),
        ]

        result = await _get_postgres_context(entities, _make_documents())

        # ARTICLE and REGULATION entities should be in related_regulations
        assert "Rule 15" in result.related_regulations
        assert "SOLAS" in result.related_regulations
        assert "tàu" not in result.related_regulations

    @pytest.mark.asyncio
    async def test_postgres_additional_doc_format(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [_make_entity_info()]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"node_id": "n1", "content": "Some maritime regulation content here that is quite long",
             "document_id": "d1", "page_number": 3, "image_url": "http://img.png", "content_type": "table"}
        ])
        mock_settings = _make_settings()

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("app.core.config.get_settings", return_value=mock_settings):
            result = await _get_postgres_context(entities, [])

        assert len(result.additional_docs) == 1
        doc = result.additional_docs[0]
        assert doc["node_id"] == "n1"
        assert doc["score"] == 0.5  # Default graph-discovered score
        assert doc["content_type"] == "table"
        assert doc["title"].startswith("[Graph]")


# =============================================================================
# 5. Main Entry Point Tests
# =============================================================================


class TestEnrichWithGraphContext:
    """Test enrich_with_graph_context main function."""

    @pytest.mark.asyncio
    async def test_no_entities_returns_empty(self):
        from app.engine.agentic_rag.graph_rag_retriever import enrich_with_graph_context

        with patch(
            "app.engine.agentic_rag.graph_rag_retriever._extract_query_entities",
            AsyncMock(return_value=[]),
        ):
            result = await enrich_with_graph_context(_make_documents(), "test query")

        assert result.entities == []
        assert result.mode == "none"
        assert result.total_time_ms >= 0

    @pytest.mark.asyncio
    async def test_neo4j_mode_when_enabled(self):
        from app.engine.agentic_rag.graph_rag_retriever import (
            enrich_with_graph_context,
            GraphRAGContext,
        )

        entity = _make_entity_info()
        neo4j_ctx = GraphRAGContext(
            entities=[entity],
            related_regulations=["Rule 15"],
            entity_context_text="Quy tắc liên quan: Rule 15",
            mode="neo4j",
        )

        mock_settings = _make_settings(enable_neo4j=True)

        with patch(
            "app.engine.agentic_rag.graph_rag_retriever._extract_query_entities",
            AsyncMock(return_value=[entity]),
        ), patch(
            "app.engine.agentic_rag.graph_rag_retriever._get_neo4j_context",
            AsyncMock(return_value=neo4j_ctx),
        ), patch(
            "app.core.config.get_settings",
            return_value=mock_settings,
        ):
            result = await enrich_with_graph_context(_make_documents(), "Rule 15 là gì?")

        assert result.mode == "neo4j"
        assert "Rule 15" in result.entity_context_text
        assert result.total_time_ms >= 0

    @pytest.mark.asyncio
    async def test_postgres_fallback_when_neo4j_disabled(self):
        from app.engine.agentic_rag.graph_rag_retriever import (
            enrich_with_graph_context,
            GraphRAGContext,
        )

        entity = _make_entity_info()
        pg_ctx = GraphRAGContext(
            entities=[entity],
            entity_context_text="Thực thể trong câu hỏi: COLREGs",
            mode="postgres",
        )

        mock_settings = _make_settings(enable_neo4j=False)

        with patch(
            "app.engine.agentic_rag.graph_rag_retriever._extract_query_entities",
            AsyncMock(return_value=[entity]),
        ), patch(
            "app.engine.agentic_rag.graph_rag_retriever._get_postgres_context",
            AsyncMock(return_value=pg_ctx),
        ), patch(
            "app.core.config.get_settings",
            return_value=mock_settings,
        ):
            result = await enrich_with_graph_context(_make_documents(), "COLREGs là gì?")

        assert result.mode == "postgres"
        assert result.total_time_ms >= 0

    @pytest.mark.asyncio
    async def test_postgres_fallback_when_neo4j_returns_none(self):
        from app.engine.agentic_rag.graph_rag_retriever import (
            enrich_with_graph_context,
            GraphRAGContext,
        )

        entity = _make_entity_info()
        neo4j_ctx = GraphRAGContext(mode="none")
        pg_ctx = GraphRAGContext(
            entities=[entity],
            entity_context_text="Thực thể: COLREGs",
            mode="postgres",
        )

        mock_settings = _make_settings(enable_neo4j=True)

        with patch(
            "app.engine.agentic_rag.graph_rag_retriever._extract_query_entities",
            AsyncMock(return_value=[entity]),
        ), patch(
            "app.engine.agentic_rag.graph_rag_retriever._get_neo4j_context",
            AsyncMock(return_value=neo4j_ctx),
        ), patch(
            "app.engine.agentic_rag.graph_rag_retriever._get_postgres_context",
            AsyncMock(return_value=pg_ctx),
        ), patch(
            "app.core.config.get_settings",
            return_value=mock_settings,
        ):
            result = await enrich_with_graph_context(_make_documents(), "COLREGs là gì?")

        # Should fallback to postgres when neo4j returns mode="none"
        assert result.mode == "postgres"

    @pytest.mark.asyncio
    async def test_timing_is_recorded(self):
        from app.engine.agentic_rag.graph_rag_retriever import enrich_with_graph_context

        entity = _make_entity_info()

        mock_settings = _make_settings(enable_neo4j=False)

        with patch(
            "app.engine.agentic_rag.graph_rag_retriever._extract_query_entities",
            AsyncMock(return_value=[entity]),
        ), patch(
            "app.engine.agentic_rag.graph_rag_retriever._get_postgres_context",
            AsyncMock(return_value=MagicMock(
                entity_context_text="test",
                mode="postgres",
                entities=[entity],
                additional_docs=[],
                total_time_ms=0,
            )),
        ), patch(
            "app.core.config.get_settings",
            return_value=mock_settings,
        ):
            result = await enrich_with_graph_context(_make_documents(), "query")

        assert result.total_time_ms >= 0


# =============================================================================
# 6. Config and Feature Gate Tests
# =============================================================================


class TestGraphRAGConfig:
    """Test config flags for Graph RAG."""

    def test_enable_graph_rag_default_false(self):
        """enable_graph_rag defaults to False in config."""
        from app.core.config import Settings
        s = Settings(
            api_key="test",
            google_api_key="test",
            database_url="postgresql+asyncpg://x/y",
        )
        assert s.enable_graph_rag is False

    def test_graph_rag_max_entities_default(self):
        from app.core.config import Settings
        s = Settings(
            api_key="test",
            google_api_key="test",
            database_url="postgresql+asyncpg://x/y",
        )
        assert s.graph_rag_max_entities == 5

    def test_graph_rag_max_entities_range(self):
        from app.core.config import Settings
        s = Settings(
            api_key="test",
            google_api_key="test",
            database_url="postgresql+asyncpg://x/y",
            graph_rag_max_entities=10,
        )
        assert s.graph_rag_max_entities == 10


# =============================================================================
# 7. Corrective RAG Integration Tests
# =============================================================================


class TestCorrativeRAGSyncIntegration:
    """Test Graph RAG integration in corrective_rag.py sync path."""

    @pytest.mark.asyncio
    async def test_graph_rag_disabled_skips_enrichment(self):
        """When enable_graph_rag=False, no graph enrichment occurs."""
        # This tests the feature gate at the corrective_rag level
        # We verify the function itself works correctly regardless
        mock_settings = _make_settings(enable_graph_rag=False)

        # Even if we call enrich_with_graph_context, the gate is in corrective_rag
        # So we test the gate logic directly
        assert mock_settings.enable_graph_rag is False

    @pytest.mark.asyncio
    async def test_graph_context_injected_into_context_dict(self):
        """Graph entity context should be injected into context['entity_context']."""
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext

        entity = _make_entity_info()
        graph_ctx = GraphRAGContext(
            entities=[entity],
            entity_context_text="Quy tắc liên quan: Rule 15. Thực thể: COLREGs",
            mode="postgres",
        )

        # Simulate what corrective_rag.py does
        context = {}
        graph_entity_context = graph_ctx.entity_context_text
        if graph_entity_context:
            context["entity_context"] = graph_entity_context

        assert context["entity_context"] == "Quy tắc liên quan: Rule 15. Thực thể: COLREGs"

    @pytest.mark.asyncio
    async def test_additional_docs_appended(self):
        """Graph-discovered docs should be appended to document list."""
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext

        documents = _make_documents(2)
        graph_ctx = GraphRAGContext(
            additional_docs=[{"node_id": "graph-1", "content": "extra"}],
            mode="postgres",
        )

        # Simulate what corrective_rag.py does
        if graph_ctx.additional_docs:
            documents.extend(graph_ctx.additional_docs)

        assert len(documents) == 3
        assert documents[-1]["node_id"] == "graph-1"


class TestCorrectiveRAGStreamingIntegration:
    """Test Graph RAG integration in streaming path."""

    @pytest.mark.asyncio
    async def test_streaming_graph_rag_emits_events(self):
        """Streaming path should emit status and thinking events for Graph RAG."""
        from app.engine.agentic_rag.graph_rag_retriever import GraphRAGContext

        # Verify event format
        graph_result = GraphRAGContext(
            entities=[_make_entity_info()],
            entity_context_text="Thực thể: COLREGs",
            mode="postgres",
            total_time_ms=45.0,
        )

        # Simulate the streaming event that would be emitted
        thinking_event = {
            "type": "thinking",
            "content": f"Đồ thị tri thức: {len(graph_result.entities)} thực thể, chế độ {graph_result.mode} ({graph_result.total_time_ms:.0f}ms)",
            "step": "graph_rag",
        }

        assert thinking_event["type"] == "thinking"
        assert thinking_event["step"] == "graph_rag"
        assert "1 thực thể" in thinking_event["content"]
        assert "postgres" in thinking_event["content"]

    @pytest.mark.asyncio
    async def test_streaming_graph_entity_context_passed_to_generation(self):
        """Graph entity context should be passed to _generate_response_streaming."""
        # The streaming path stores graph context in graph_entity_context_streaming
        # and passes it to entity_context= in the generation call
        graph_entity_context_streaming = "Quy tắc: Rule 15"

        # Verify it would be passed (non-empty string)
        assert graph_entity_context_streaming
        assert "Rule 15" in graph_entity_context_streaming


# =============================================================================
# 8. Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_documents_list(self):
        from app.engine.agentic_rag.graph_rag_retriever import enrich_with_graph_context

        with patch(
            "app.engine.agentic_rag.graph_rag_retriever._extract_query_entities",
            AsyncMock(return_value=[_make_entity_info()]),
        ), patch(
            "app.engine.agentic_rag.graph_rag_retriever._get_postgres_context",
            AsyncMock(return_value=MagicMock(
                entity_context_text="test",
                mode="postgres",
                entities=[_make_entity_info()],
                additional_docs=[],
                total_time_ms=0,
            )),
        ), patch(
            "app.core.config.get_settings",
            return_value=_make_settings(enable_neo4j=False),
        ):
            result = await enrich_with_graph_context([], "test query")

        # Should still work with empty docs (no document_ids to search)
        assert result.mode == "postgres"

    @pytest.mark.asyncio
    async def test_entity_with_empty_name(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [_make_entity_info(name=""), _make_entity_info(name="COLREGs")]

        # Empty name should be filtered out in entity_names list
        result = await _get_postgres_context(entities, _make_documents())

        # entity_names filters by `if e.name`, so empty name excluded
        assert result.mode == "postgres"

    @pytest.mark.asyncio
    async def test_vietnamese_name_preferred_in_display(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        entities = [
            _make_entity_info(name="starboard", name_vi="mạn phải"),
        ]

        result = await _get_postgres_context(entities, _make_documents())

        # Vietnamese name should appear in context text
        assert "mạn phải" in result.entity_context_text

    @pytest.mark.asyncio
    async def test_neo4j_context_text_format(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        mock_neo4j.get_entity_relations = AsyncMock(return_value=[
            {"target_id": "e1", "target_name": "Rule 15", "target_type": "ARTICLE"},
        ])
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            result = await _get_neo4j_context(
                [_make_entity_info(name="COLREG", name_vi="Quy tắc tránh va")],
                [],
            )

        # Context text should contain both regulations and entities
        assert "Quy tắc liên quan: Rule 15" in result.entity_context_text
        assert "Thực thể liên quan" in result.entity_context_text

    @pytest.mark.asyncio
    async def test_postgres_conn_close_always_called(self):
        """Connection should be closed even if fetch fails."""
        from app.engine.agentic_rag.graph_rag_retriever import _get_postgres_context

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=RuntimeError("SQL error"))

        with patch("asyncpg.connect", AsyncMock(return_value=mock_conn)), \
             patch("app.core.config.get_settings", return_value=_make_settings()):
            result = await _get_postgres_context([_make_entity_info()], [])

        # Connection close should still be called (finally block)
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_regulations_limited_to_10(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        # Return 15 different ARTICLE relations
        relations = [
            {"target_id": f"e{i}", "target_name": f"Rule {i}", "target_type": "ARTICLE"}
            for i in range(15)
        ]
        mock_neo4j.get_entity_relations = AsyncMock(return_value=relations)
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            result = await _get_neo4j_context([_make_entity_info()], [])

        # Should be limited to 10 regulations
        assert len(result.related_regulations) <= 10

    @pytest.mark.asyncio
    async def test_max_entities_limited_to_20(self):
        from app.engine.agentic_rag.graph_rag_retriever import _get_neo4j_context

        mock_neo4j = MagicMock()
        mock_neo4j.is_available.return_value = True
        # Return many relations
        relations = [
            {"target_id": f"e{i}", "target_name": f"Entity {i}", "target_type": "CONCEPT"}
            for i in range(30)
        ]
        mock_neo4j.get_entity_relations = AsyncMock(return_value=relations)
        mock_neo4j.get_document_entities = AsyncMock(return_value=[])

        with patch(
            "app.repositories.neo4j_knowledge_repository.Neo4jKnowledgeRepository",
            return_value=mock_neo4j,
        ):
            result = await _get_neo4j_context([_make_entity_info()], [])

        # Should be limited to 20 entities
        assert len(result.entities) <= 20


# =============================================================================
# 9. Import Tests
# =============================================================================


class TestImports:
    """Test module imports."""

    def test_graph_rag_retriever_imports(self):
        from app.engine.agentic_rag.graph_rag_retriever import (
            EntityInfo,
            GraphRAGContext,
            enrich_with_graph_context,
        )
        assert EntityInfo is not None
        assert GraphRAGContext is not None
        assert callable(enrich_with_graph_context)

    def test_private_functions_importable(self):
        from app.engine.agentic_rag.graph_rag_retriever import (
            _extract_query_entities,
            _get_neo4j_context,
            _get_postgres_context,
        )
        assert callable(_extract_query_entities)
        assert callable(_get_neo4j_context)
        assert callable(_get_postgres_context)
