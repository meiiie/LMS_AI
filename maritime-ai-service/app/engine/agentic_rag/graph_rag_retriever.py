"""
Graph RAG Retriever — Entity-aware knowledge graph retrieval.
Sprint 182-184: "Đồ Thị Tri Thức" — Microsoft GraphRAG pattern.

Enriches the corrective RAG pipeline with entity context:
1. Extracts entities from user query (via KG Builder Agent)
2. Finds related entities and documents (Neo4j or PostgreSQL fallback)
3. Injects entity context into generation prompt
4. Supports multi-hop: query → entities → related entities → additional docs

Works in two modes:
- Neo4j mode: Full graph traversal when enable_neo4j=True
- PostgreSQL mode: Entity keyword search in chunks when Neo4j unavailable

Feature-gated by enable_graph_rag in config.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EntityInfo:
    """Extracted entity with metadata."""

    entity_id: str
    name: str
    name_vi: Optional[str] = None
    entity_type: str = "CONCEPT"
    description: str = ""
    source: str = ""  # query / document


@dataclass
class GraphRAGContext:
    """Graph-enhanced context for RAG generation."""

    entities: List[EntityInfo] = field(default_factory=list)
    related_regulations: List[str] = field(default_factory=list)
    entity_context_text: str = ""  # Formatted text for LLM injection
    additional_docs: List[Dict[str, Any]] = field(default_factory=list)
    total_time_ms: float = 0.0
    mode: str = "none"  # "neo4j" | "postgres" | "none"


def _current_graph_org_id() -> Optional[str]:
    try:
        from app.core.org_context import get_current_org_id

        org_id = get_current_org_id()
        return org_id.strip() if isinstance(org_id, str) and org_id.strip() else None
    except Exception:
        return None


async def _extract_query_entities(query: str) -> List[EntityInfo]:
    """Extract entities from user query using KG Builder Agent.

    Uses the existing LLM-based entity extraction with structured output.

    Args:
        query: User query string.

    Returns:
        List of extracted EntityInfo objects.
    """
    try:
        from app.engine.kg_builder_service import get_kg_builder_service

        builder = get_kg_builder_service()
        if not builder.is_available():
            logger.debug("[GraphRAG-R] KG Builder unavailable, skipping entity extraction")
            return []

        extraction = await builder.extract(query, source="user_query")
        entities = []
        for e in extraction.entities:
            entities.append(EntityInfo(
                entity_id=e.id,
                name=e.name,
                name_vi=e.name_vi,
                entity_type=e.entity_type,
                description=e.description,
                source="query",
            ))

        logger.info("[GraphRAG-R] Extracted %d entities from query", len(entities))
        return entities

    except Exception as e:
        logger.warning("[GraphRAG-R] Entity extraction failed: %s", e)
        return []


async def _get_neo4j_context(
    query_entities: List[EntityInfo],
    document_ids: List[str],
    organization_id: Optional[str] = None,
) -> GraphRAGContext:
    """Get entity context from Neo4j graph.

    Traverses entity relationships in Neo4j to find:
    - Related regulations for each entity
    - Document-level entities
    - Multi-hop connections

    Args:
        query_entities: Entities extracted from user query.
        document_ids: Document IDs from retrieved chunks.

    Returns:
        GraphRAGContext with Neo4j-sourced entity information.
    """
    try:
        from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository

        neo4j = Neo4jKnowledgeRepository()
        if not neo4j.is_available():
            return GraphRAGContext(mode="none")

        all_regulations = set()
        all_entities = list(query_entities)
        effective_org_id = organization_id or _current_graph_org_id()

        # Get related entities for query entities (multi-hop)
        for entity in query_entities[:5]:  # Limit to avoid too many queries
            try:
                relations = await neo4j.get_entity_relations(
                    entity.entity_id,
                    organization_id=effective_org_id,
                )
                for rel in relations:
                    target_name = rel.get("target_name", "")
                    target_type = rel.get("target_type", "")
                    if target_type == "ARTICLE" and target_name:
                        all_regulations.add(target_name)
                    if target_name:
                        all_entities.append(EntityInfo(
                            entity_id=rel.get("target_id", ""),
                            name=target_name,
                            name_vi=rel.get("target_name_vi"),
                            entity_type=target_type,
                            source="graph_hop",
                        ))
            except Exception as e:
                logger.debug("[GraphRAG-R] Relation lookup failed for %s: %s", entity.entity_id, e)

        # Get document-level entities
        for doc_id in document_ids[:3]:
            try:
                doc_entities = await neo4j.get_document_entities(
                    doc_id,
                    organization_id=effective_org_id,
                )
                for de in doc_entities:
                    if de.get("type") == "ARTICLE":
                        all_regulations.add(de.get("name", ""))
            except Exception:
                pass

        regulations = sorted(all_regulations)[:10]

        # Build context text
        context_parts = []
        if regulations:
            context_parts.append(f"Quy tắc liên quan: {', '.join(regulations)}")

        unique_names = []
        seen = set()
        for e in all_entities:
            display = e.name_vi or e.name
            if display and display not in seen:
                seen.add(display)
                unique_names.append(display)
        if unique_names:
            context_parts.append(f"Thực thể liên quan: {', '.join(unique_names[:8])}")

        return GraphRAGContext(
            entities=all_entities[:20],
            related_regulations=regulations,
            entity_context_text=". ".join(context_parts),
            mode="neo4j",
        )

    except Exception as e:
        logger.warning("[GraphRAG-R] Neo4j context failed: %s", e)
        return GraphRAGContext(mode="none")


async def _get_postgres_context(
    query_entities: List[EntityInfo],
    documents: List[Dict[str, Any]],
) -> GraphRAGContext:
    """Get entity context using PostgreSQL keyword search.

    Fallback when Neo4j is unavailable. Uses entity names to find
    related documents via text matching in knowledge_embeddings.

    Args:
        query_entities: Entities extracted from user query.
        documents: Already-retrieved documents from hybrid search.

    Returns:
        GraphRAGContext with PostgreSQL-sourced entity information.
    """
    if not query_entities:
        return GraphRAGContext(mode="postgres")

    try:
        # Use entity names to find additional related documents
        entity_names = [e.name_vi or e.name for e in query_entities if e.name]

        additional_docs = []

        if entity_names:
            try:
                import asyncpg
                from app.core.config import get_settings
                from app.repositories.knowledge_search_org_scope import (
                    log_knowledge_search_scope_blocked,
                    resolve_knowledge_search_org_scope,
                )

                scope = resolve_knowledge_search_org_scope()
                if not scope.write_allowed or not scope.org_id:
                    log_knowledge_search_scope_blocked(
                        logger,
                        "graph_rag_postgres_context",
                        scope,
                    )
                    regulations = [
                        e.name for e in query_entities
                        if e.entity_type in ("ARTICLE", "REGULATION") and e.name
                    ]
                    return GraphRAGContext(
                        entities=query_entities,
                        related_regulations=regulations,
                        entity_context_text=_format_postgres_entity_context(query_entities),
                        additional_docs=[],
                        mode="postgres",
                    )

                settings = get_settings()
                conn = await asyncpg.connect(settings.asyncpg_url)
                try:
                    # Search for documents mentioning entity names
                    # Use plainto_tsquery for safety (no injection)
                    search_terms = " | ".join(entity_names[:5])
                    rows = await conn.fetch(
                        """
                        SELECT id::text as node_id, content, document_id, page_number,
                               image_url, content_type
                        FROM knowledge_embeddings
                        WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', $1)
                        AND (organization_id = $2 OR organization_id IS NULL)
                        ORDER BY ts_rank(to_tsvector('simple', content),
                                        plainto_tsquery('simple', $1)) DESC
                        LIMIT 5
                        """,
                        search_terms,
                        scope.org_id,
                    )

                    # Filter out already-retrieved documents
                    existing_ids = {d.get("node_id") for d in documents}
                    for row in rows:
                        if row["node_id"] not in existing_ids:
                            additional_docs.append({
                                "node_id": row["node_id"],
                                "content": row["content"],
                                "document_id": row["document_id"],
                                "page_number": row["page_number"],
                                "image_url": row["image_url"] or "",
                                "content_type": row["content_type"] or "text",
                                "score": 0.5,  # Default score for graph-discovered docs
                                "title": f"[Graph] {row['content'][:60]}...",
                            })
                finally:
                    await conn.close()
            except Exception as db_err:
                logger.debug("[GraphRAG-R] PostgreSQL entity search failed: %s", db_err)

        # Build context text from entities
        context_parts = []
        entity_names_display = [e.name_vi or e.name for e in query_entities if e.name]
        if entity_names_display:
            context_parts.append(f"Thực thể trong câu hỏi: {', '.join(entity_names_display[:8])}")

        # Extract regulation references from entity types
        regulations = [
            e.name for e in query_entities
            if e.entity_type in ("ARTICLE", "REGULATION") and e.name
        ]
        if regulations:
            context_parts.append(f"Quy tắc liên quan: {', '.join(regulations[:5])}")

        return GraphRAGContext(
            entities=query_entities,
            related_regulations=regulations,
            entity_context_text=". ".join(context_parts),
            additional_docs=additional_docs[:3],
            mode="postgres",
        )

    except Exception as e:
        logger.warning("[GraphRAG-R] PostgreSQL context failed: %s", e)
        return GraphRAGContext(mode="postgres")


def _format_postgres_entity_context(query_entities: List[EntityInfo]) -> str:
    context_parts = []
    entity_names_display = [e.name_vi or e.name for e in query_entities if e.name]
    if entity_names_display:
        context_parts.append(f"Thá»±c thá»ƒ trong cÃ¢u há»i: {', '.join(entity_names_display[:8])}")

    regulations = [
        e.name for e in query_entities
        if e.entity_type in ("ARTICLE", "REGULATION") and e.name
    ]
    if regulations:
        context_parts.append(f"Quy táº¯c liÃªn quan: {', '.join(regulations[:5])}")
    return ". ".join(context_parts)


async def enrich_with_graph_context(
    documents: List[Dict[str, Any]],
    query: str,
    organization_id: Optional[str] = None,
) -> GraphRAGContext:
    """Enrich retrieved documents with knowledge graph context.

    Main entry point for Graph RAG integration. Feature-gated by enable_graph_rag.

    Flow:
    1. Extract entities from query (LLM-based via KG Builder)
    2. Find related entities/docs (Neo4j if available, PostgreSQL fallback)
    3. Build entity context text for injection into generation prompt

    Args:
        documents: Retrieved documents from hybrid search.
        query: User query string.

    Returns:
        GraphRAGContext with entities, regulations, context text, and additional docs.
    """
    start = time.time()

    # Step 1: Extract entities from query
    query_entities = await _extract_query_entities(query)

    if not query_entities:
        logger.debug("[GraphRAG-R] No entities extracted, skipping graph enrichment")
        return GraphRAGContext(total_time_ms=(time.time() - start) * 1000)

    # Step 2: Get graph context (Neo4j or PostgreSQL fallback)
    document_ids = [
        d.get("document_id") for d in documents
        if d.get("document_id")
    ]

    # Try Neo4j first, fall back to PostgreSQL
    from app.core.config import get_settings
    settings = get_settings()

    if getattr(settings, "enable_neo4j", False):
        context = await _get_neo4j_context(
            query_entities,
            document_ids,
            organization_id=organization_id,
        )
        if context.mode == "neo4j":
            context.total_time_ms = (time.time() - start) * 1000
            logger.info(
                "[GraphRAG-R] Neo4j context: %d entities, %d regulations (%.0fms)",
                len(context.entities),
                len(context.related_regulations),
                context.total_time_ms,
            )
            return context

    # PostgreSQL fallback
    context = await _get_postgres_context(query_entities, documents)
    context.total_time_ms = (time.time() - start) * 1000
    logger.info(
        "[GraphRAG-R] PostgreSQL context: %d entities, %d additional docs (%.0fms)",
        len(context.entities),
        len(context.additional_docs),
        context.total_time_ms,
    )
    return context
