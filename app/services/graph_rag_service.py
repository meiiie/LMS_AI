"""
GraphRAG Service - Graph-Enhanced Retrieval

Combines HybridSearch (vector + sparse) with Neo4j Entity Graph
for Microsoft-style GraphRAG retrieval.

**Feature: graph-rag**
**CHỈ THỊ KỸ THUẬT SỐ 29: Automated Knowledge Graph Construction**
**SOTA 2025: Hybrid Agentic-GraphRAG Architecture**
**Phase 2.2b+c: Parallel execution + Entity caching**
"""
import asyncio
import logging
import time
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from app.services.hybrid_search_service import HybridSearchService, get_hybrid_search_service
from app.engine.rrf_reranker import HybridSearchResult
from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
from app.engine.multi_agent.agents.kg_builder_agent import KGBuilderAgentNode, get_kg_builder_agent
from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# Phase 2.2c: Entity Extraction Cache (TTL 5 minutes)
# Caches expensive LLM entity extraction to avoid redundant calls
# ============================================================
_entity_cache: Dict[str, Tuple[List[str], float]] = {}
_ENTITY_CACHE_TTL = 300  # 5 minutes


@dataclass
class GraphEnhancedResult:
    """Search result with entity context from Neo4j"""
    # Original hybrid search result
    chunk_id: str
    content: str
    score: float
    page_number: Optional[int] = None
    document_id: Optional[str] = None
    image_url: Optional[str] = None
    bounding_boxes: Optional[List[Dict[str, Any]]] = None  # Feature: source-highlight-citation
    category: str = "Knowledge"  # From source HybridSearchResult
    
    # Graph-enhanced context
    related_entities: List[Dict[str, Any]] = field(default_factory=list)
    related_regulations: List[str] = field(default_factory=list)
    entity_context: str = ""  # Summarized entity context for LLM
    
    # Metadata
    search_method: str = "graph_enhanced"
    dense_score: float = 0.0
    sparse_score: float = 0.0


class GraphRAGService:
    """
    GraphRAG Service - Microsoft-style graph-enhanced retrieval.
    
    Combines:
    1. HybridSearch (vector + sparse) for chunk retrieval
    2. Neo4j Entity Graph for context enrichment
    3. Entity-aware query expansion
    
    **Feature: graph-rag**
    """
    
    def __init__(
        self,
        hybrid_service: Optional[HybridSearchService] = None,
        neo4j_repo: Optional[Neo4jKnowledgeRepository] = None,
        kg_builder: Optional[KGBuilderAgentNode] = None
    ):
        """Initialize GraphRAG Service"""
        self._hybrid = hybrid_service or get_hybrid_search_service()
        self._neo4j = neo4j_repo or Neo4jKnowledgeRepository()
        self._kg_builder = kg_builder or get_kg_builder_agent()
        
        # Check Neo4j availability
        self._neo4j_available = self._neo4j.is_available()
        
        logger.info(
            f"GraphRAGService initialized (Neo4j: {self._neo4j_available})"
        )
    
    async def search(
        self,
        query: str,
        limit: int = 5,
        include_entity_context: bool = True
    ) -> List[GraphEnhancedResult]:
        """
        Perform graph-enhanced search.
        
        Phase 2.2b: PARALLEL execution (entity extraction + hybrid search)
        Phase 2.2c: Entity cache with 5min TTL
        
        Flow:
        1. Extract entities from query (PARALLEL with search)
        2. HybridSearch for relevant chunks (PARALLEL with extraction)
        3. Enrich with entity context from Neo4j
        
        Args:
            query: Search query
            limit: Max results
            include_entity_context: Whether to add entity context
            
        Returns:
            List of GraphEnhancedResult with entity context
        """
        logger.info(f"[GraphRAG] Search: {query[:50]}...")
        
        # ============================================================
        # Phase 2.2b: PARALLEL execution - save ~10s
        # Run entity extraction and hybrid search concurrently
        # ============================================================
        entity_task = self._extract_entities_cached(query)
        search_task = self._hybrid.search(query, limit=limit)
        
        query_entities, hybrid_results = await asyncio.gather(
            entity_task, search_task
        )
        
        if not hybrid_results:
            logger.warning("[GraphRAG] No hybrid results found")
            return []
        
        # Step 3: Enrich results with entity context
        enhanced_results = []
        
        for result in hybrid_results:
            enhanced = GraphEnhancedResult(
                chunk_id=result.node_id,
                content=result.content,
                score=result.rrf_score,
                page_number=result.page_number,
                document_id=result.document_id,
                image_url=result.image_url,
                bounding_boxes=result.bounding_boxes,  # Feature: source-highlight-citation
                category=result.category,  # Pass category from HybridSearchResult
                search_method="graph_enhanced" if self._neo4j_available else result.search_method,
                dense_score=result.dense_score or 0.0,
                sparse_score=result.sparse_score or 0.0
            )
            
            # Add entity context if Neo4j available
            if include_entity_context and self._neo4j_available:
                try:
                    entity_context = await self._get_entity_context(
                        result.document_id,
                        query_entities
                    )
                    enhanced.related_entities = entity_context.get("entities", [])
                    enhanced.related_regulations = entity_context.get("regulations", [])
                    enhanced.entity_context = entity_context.get("summary", "")
                except Exception as e:
                    logger.warning(f"Entity context enrichment failed: {e}")
            
            enhanced_results.append(enhanced)
        
        logger.info(f"[GraphRAG] Returned {len(enhanced_results)} enhanced results")
        return enhanced_results
    
    async def _extract_entities_cached(self, query: str) -> List[str]:
        """
        Extract entities from query with caching.
        
        Phase 2.2c: Entity cache with 5min TTL
        Avoids redundant LLM calls for similar/same queries.
        
        Args:
            query: User query string
            
        Returns:
            List of entity IDs
        """
        global _entity_cache
        
        # Create cache key (first 100 chars, lowercased, stripped)
        cache_key = query[:100].lower().strip()
        
        # Check cache
        if cache_key in _entity_cache:
            entities, timestamp = _entity_cache[cache_key]
            if time.time() - timestamp < _ENTITY_CACHE_TTL:
                logger.info(f"[GraphRAG] Entity cache HIT: {len(entities)} entities")
                return entities
            else:
                # Expired - remove from cache
                del _entity_cache[cache_key]
        
        # Cache miss - extract entities
        query_entities = []
        if self._kg_builder.is_available():
            try:
                extraction = await self._kg_builder.extract(query, "user_query")
                query_entities = [e.id for e in extraction.entities]
                if query_entities:
                    logger.info(f"[GraphRAG] Query entities: {query_entities}")
                    # Cache the result
                    _entity_cache[cache_key] = (query_entities, time.time())
                    logger.info(f"[GraphRAG] Entity cache SET: {len(query_entities)} entities (TTL={_ENTITY_CACHE_TTL}s)")
            except Exception as e:
                logger.warning(f"Query entity extraction failed: {e}")
        
        return query_entities
    
    async def _get_entity_context(
        self,
        document_id: Optional[str],
        query_entities: List[str]
    ) -> Dict[str, Any]:
        """
        Get entity context from Neo4j.
        
        Args:
            document_id: Document to get entities from
            query_entities: Entities extracted from query
            
        Returns:
            Dict with entities, regulations, and summary
        """
        entities = []
        regulations = []
        
        # Get entities from the document
        if document_id:
            doc_entities = await self._neo4j.get_document_entities(document_id)
            entities.extend(doc_entities)
        
        # Get related regulations
        for entity in entities:
            if entity.get("type") == "ARTICLE":
                regulations.append(entity.get("name", ""))
        
        # Get relations for query entities
        for entity_id in query_entities[:3]:  # Limit to avoid too many queries
            relations = await self._neo4j.get_entity_relations(entity_id)
            for rel in relations:
                if rel.get("target_type") == "ARTICLE":
                    regulations.append(rel.get("target_name", ""))
        
        # Build summary
        regulations = list(set(regulations))[:5]  # Dedupe and limit
        
        summary = ""
        if regulations:
            summary = f"Liên quan đến: {', '.join(regulations)}"
        
        return {
            "entities": entities[:10],  # Limit
            "regulations": regulations,
            "summary": summary
        }
    
    async def search_with_graph_context(
        self,
        query: str,
        limit: int = 5
    ) -> tuple[List[GraphEnhancedResult], str]:
        """
        Search and return results with combined entity context.
        
        Returns:
            Tuple of (results, entity_context_string)
        """
        results = await self.search(query, limit, include_entity_context=True)
        
        # Combine entity context
        all_entities = []
        all_regulations = set()
        
        for r in results:
            all_entities.extend(r.related_entities)
            all_regulations.update(r.related_regulations)
        
        # Build context string for LLM prompt
        context_parts = []
        
        if all_regulations:
            context_parts.append(f"Các quy tắc liên quan: {', '.join(list(all_regulations)[:5])}")
        
        # Dedupe entities by ID
        seen_ids = set()
        unique_entities = []
        for e in all_entities:
            if e.get("id") not in seen_ids:
                seen_ids.add(e.get("id"))
                unique_entities.append(e)
        
        if unique_entities:
            entity_names = [
                f"{e.get('name_vi', e.get('name', ''))}"
                for e in unique_entities[:5]
            ]
            context_parts.append(f"Thực thể liên quan: {', '.join(entity_names)}")
        
        entity_context = ". ".join(context_parts) if context_parts else ""
        
        return results, entity_context
    
    def is_available(self) -> bool:
        """Check if service is available"""
        return self._hybrid.is_available()
    
    def is_graph_available(self) -> bool:
        """Check if Neo4j graph is available"""
        return self._neo4j_available


# Singleton
_graph_rag_service: Optional[GraphRAGService] = None


def get_graph_rag_service() -> GraphRAGService:
    """Get or create singleton GraphRAGService"""
    global _graph_rag_service
    if _graph_rag_service is None:
        _graph_rag_service = GraphRAGService()
    return _graph_rag_service
