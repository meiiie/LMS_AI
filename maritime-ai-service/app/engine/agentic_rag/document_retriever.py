"""
Document Retriever for RAG Agent.

Handles document retrieval, conversion between search result formats,
citation generation, and evidence image collection.

Extracted from rag_agent.py as part of modular refactoring.

**Feature: hybrid-search, semantic-chunking, document-kg, multimodal-rag-vision**
"""

import logging
from typing import Any, Dict, List

from app.models.knowledge_graph import (
    Citation,
    KnowledgeNode,
)
from app.engine.agentic_rag.rag_agent_contracts import EvidenceImage
from app.engine.rrf_reranker import HybridSearchResult

logger = logging.getLogger(__name__)


class DocumentRetriever:
    """
    Handles document retrieval conversion, citation generation,
    and evidence image collection for the RAG pipeline.

    Methods are designed to be called by RAGAgent as delegation targets.
    """

    @staticmethod
    def graph_to_hybrid_results(graph_results) -> List[HybridSearchResult]:
        """Convert GraphEnhancedResult to HybridSearchResult for compatibility."""
        hybrid_results = []
        for gr in graph_results:
            hybrid_results.append(HybridSearchResult(
                node_id=gr.chunk_id,
                content=gr.content,
                title=gr.content[:50] + "..." if len(gr.content) > 50 else gr.content,
                source=gr.document_id or "Knowledge Base",
                category=getattr(gr, 'category', 'Knowledge'),  # SOTA: graceful fallback
                rrf_score=gr.score,
                dense_score=gr.dense_score,
                sparse_score=gr.sparse_score,
                search_method=gr.search_method,
                page_number=gr.page_number,
                document_id=gr.document_id,
                image_url=gr.image_url
            ))
        return hybrid_results

    @staticmethod
    def hybrid_results_to_nodes(results: List[HybridSearchResult]) -> List[KnowledgeNode]:
        """Convert HybridSearchResult to KnowledgeNode for compatibility with chunking metadata."""
        from app.models.knowledge_graph import NodeType

        nodes = []
        for r in results:
            # Skip results with empty title or content
            title = r.title or ""
            content = r.content or ""

            if not title.strip() or not content.strip():
                logger.warning("Skipping result with empty title/content: %s", r.node_id)
                continue

            # Build enhanced title with document hierarchy
            enhanced_title = DocumentRetriever.format_title_with_hierarchy(title, r)

            nodes.append(KnowledgeNode(
                id=r.node_id,
                node_type=NodeType.CONCEPT,
                title=enhanced_title,
                content=content,
                source=r.source or "Knowledge Base",
                metadata={
                    "category": r.category,
                    "rrf_score": r.rrf_score,
                    "dense_score": r.dense_score,
                    "sparse_score": r.sparse_score,
                    "search_method": r.search_method,
                    # Semantic chunking metadata
                    "content_type": r.content_type,
                    "confidence_score": r.confidence_score,
                    "page_number": r.page_number,
                    "chunk_index": r.chunk_index,
                    "image_url": r.image_url,
                    "document_id": r.document_id,
                    "section_hierarchy": r.section_hierarchy
                }
            ))
        return nodes

    @staticmethod
    def format_title_with_hierarchy(title: str, result: HybridSearchResult) -> str:
        """
        Format title with document hierarchy (\u0110i\u1ec1u, Kho\u1ea3n, etc.).

        **Feature: semantic-chunking**
        **Validates: Requirements 8.4**
        """
        hierarchy = result.section_hierarchy or {}
        if not hierarchy:
            return title

        # Build hierarchy prefix
        parts = []
        if 'article' in hierarchy:
            parts.append(f"\u0110i\u1ec1u {hierarchy['article']}")
        if 'clause' in hierarchy:
            parts.append(f"Kho\u1ea3n {hierarchy['clause']}")
        if 'point' in hierarchy:
            parts.append(f"\u0110i\u1ec3m {hierarchy['point']}")
        if 'rule' in hierarchy:
            parts.append(f"Rule {hierarchy['rule']}")

        if parts:
            hierarchy_prefix = " - ".join(parts)
            # Avoid duplicate if title already contains hierarchy
            if hierarchy_prefix.lower() not in title.lower():
                return f"[{hierarchy_prefix}] {title}"

        return title

    @staticmethod
    def generate_hybrid_citations(results: List[HybridSearchResult]) -> List[Citation]:
        """
        Generate citations from hybrid search results with relevance scores and chunking metadata.

        **Feature: semantic-chunking, source-highlight-citation**
        **Validates: Requirements 8.4, 8.5, 2.1, 2.3**
        """
        citations = []
        seen_pages = set()  # (document_id, page_number) dedup
        for r in results:
            # Deduplicate by (document_id, page_number) — Sprint 189
            if r.document_id:
                dedup_key = (r.document_id, r.page_number)
                if dedup_key in seen_pages:
                    continue
                seen_pages.add(dedup_key)

            # Format title with hierarchy
            enhanced_title = DocumentRetriever.format_title_with_hierarchy(r.title, r)

            # Add content type indicator for special types
            if r.content_type == "table":
                enhanced_title = f"\U0001F4CA {enhanced_title}"
            elif r.content_type == "heading":
                enhanced_title = f"\U0001F4D1 {enhanced_title}"
            elif r.content_type == "diagram_reference":
                enhanced_title = f"\U0001F4C8 {enhanced_title}"

            citations.append(Citation(
                node_id=r.node_id,
                source=r.source or "Knowledge Base",
                title=enhanced_title,
                relevance_score=r.rrf_score,
                image_url=r.image_url,
                page_number=r.page_number,
                document_id=r.document_id,
                bounding_boxes=r.bounding_boxes,
                content_type=r.content_type,
            ))
        return citations

    @staticmethod
    async def collect_evidence_images(
        node_ids: List[str],
        max_images: int = 3
    ) -> List:
        """
        Collect evidence images from database for given node IDs.

        CHI THI KY THUAT SO 26: Evidence Images

        **Property 3: Search Results Include Image URL**
        **Property 11: Response Metadata Contains Evidence Images**
        **Property 12: Maximum Evidence Images Per Response**

        Args:
            node_ids: List of node IDs to get images for
            max_images: Maximum number of images to return (default 3)

        Returns:
            List of EvidenceImage objects
        """
        from app.repositories.dense_search_repository import get_dense_search_repository
        from app.repositories.knowledge_search_org_scope import (
            log_knowledge_search_scope_blocked,
            resolve_knowledge_search_org_scope,
        )

        evidence_images = []
        seen_urls = set()

        try:
            scope = resolve_knowledge_search_org_scope()
            if not scope.write_allowed or not scope.org_id:
                log_knowledge_search_scope_blocked(
                    logger,
                    "collect_evidence_images",
                    scope,
                    node_id=node_ids[0] if node_ids else None,
                )
                return evidence_images

            repo = get_dense_search_repository()
            pool = await repo._get_pool()

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id::text as node_id, image_url, page_number, document_id
                    FROM knowledge_embeddings
                    WHERE id::text = ANY($1)
                    AND image_url IS NOT NULL
                    AND (organization_id = $2 OR organization_id IS NULL)
                    ORDER BY page_number
                    """,
                    node_ids,
                    scope.org_id,
                )

                for row in rows:
                    image_url = row['image_url']

                    # Skip duplicates or empty URLs
                    if not image_url or image_url in seen_urls:
                        continue

                    seen_urls.add(image_url)
                    evidence_images.append(EvidenceImage(
                        url=image_url,
                        page_number=row['page_number'] or 0,
                        document_id=row['document_id'] or ""
                    ))

                    # Limit to max_images
                    if len(evidence_images) >= max_images:
                        break

        except Exception as e:
            logger.warning("Failed to collect evidence images: %s", e)

        return evidence_images

    @staticmethod
    def documents_to_nodes(documents: List[Dict[str, Any]]) -> List[KnowledgeNode]:
        """Convert document dicts to KnowledgeNodes for generation."""
        from app.models.knowledge_graph import NodeType

        nodes = []
        for i, doc in enumerate(documents):
            # Use 'or' operator to handle empty strings (not just None)
            node = KnowledgeNode(
                id=doc.get("node_id") or f"doc_{i}",
                node_type=NodeType.REGULATION,
                title=doc.get("title") or f"Document {i+1}",
                content=doc.get("content") or "No content",
                source=doc.get("document_id") or "",
                metadata={
                    "score": doc.get("score", 0),
                    "page_number": doc.get("page_number"),
                    "image_url": doc.get("image_url")
                }
            )
            nodes.append(node)

        return nodes

    @staticmethod
    def documents_to_citations(documents: List[Dict[str, Any]]) -> List[Citation]:
        """Convert document dicts to Citations for response."""
        citations = []
        for doc in documents:
            citations.append(Citation(
                node_id=doc.get("node_id", ""),
                source=doc.get("document_id") or "Knowledge Base",
                title=doc.get("title") or "Unknown",
                relevance_score=doc.get("score", 0),
                image_url=doc.get("image_url"),
                page_number=doc.get("page_number"),
                document_id=doc.get("document_id"),
                bounding_boxes=doc.get("bounding_boxes"),
                content_type=doc.get("content_type"),
            ))
        return citations
