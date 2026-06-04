"""
Neo4j Knowledge Graph Repository.

LEGACY STATUS: This repository is RESERVED for future Learning Graph integration.

As of sparse-search-migration (2025-12), Neo4j has been replaced by PostgreSQL
for RAG/Knowledge search. This file is kept for:
- Future Learning Graph (LMS integration)
- Student progress tracking with graph relationships
- Knowledge dependency mapping

Current RAG search uses:
- app/repositories/dense_search_repository.py (pgvector)
- app/repositories/sparse_search_repository.py (tsvector)
- app/services/hybrid_search_service.py (RRF fusion)

Active methods: is_available, ping, hybrid_search, get_citations,
get_entity_relations, get_document_entities, close, create_entity_relation.
"""

import asyncio
import logging
from functools import wraps
from typing import Any, List, Optional

from app.core.config import settings
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)
from app.models.knowledge_graph import (
    Citation,
    KnowledgeNode,
    NodeType,
)

logger = logging.getLogger(__name__)
NEO4J_KNOWLEDGE_SCOPE_BLOCKED_WARNING = "neo4j_knowledge_blocked_missing_org_context"


# =============================================================================
# SECURITY: Allowed Neo4j Relation Types
# =============================================================================
# Allowlist to prevent Cypher injection attacks via LLM-generated relation types
# CRITICAL: Only add new types after security review
ALLOWED_RELATION_TYPES: frozenset[str] = frozenset({
    "REFERENCES",       # Entity references another entity
    "APPLIES_TO",       # Rule applies to a situation
    "REQUIRES",         # Entity requires another entity
    "DEFINES",          # Entity defines a concept
    "PART_OF",          # Entity is part of another entity
    "MENTIONS",         # Document mentions an entity
    "CONTAINS",         # Entity contains another entity
    "EXAMPLE_OF",       # Entity is example of a concept
    "CONTRADICTS",      # Entity contradicts another entity
    "SUPPORTS",         # Entity supports another entity
    "PREREQUISITE",     # Entity is prerequisite for another
    "FOLLOWS",          # Entity follows another in sequence
    "RELATED_TO",       # Generic relation between entities
})


def neo4j_retry(max_attempts: int = 2, backoff: float = 1.0):
    """
    SOTA: Retry decorator for Neo4j transient failures.

    Handles ServiceUnavailable, SessionExpired, and OSError (defunct connection).
    Uses exponential backoff between retries.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(self, *args, **kwargs)
                except OSError as e:
                    last_exception = e
                    logger.warning(
                        "Neo4j connection error (attempt %d/%d): %s", attempt + 1, max_attempts, e
                    )
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(backoff * (2 ** attempt))
                        self._init_driver()
                except Exception as e:
                    error_name = type(e).__name__
                    if error_name in ('ServiceUnavailable', 'SessionExpired', 'TransientError'):
                        last_exception = e
                        logger.warning(
                            "Neo4j transient error (attempt %d/%d): %s", attempt + 1, max_attempts, e
                        )
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(backoff * (2 ** attempt))
                            self._init_driver()
                    else:
                        raise

            logger.error("Neo4j operation failed after %d attempts: %s", max_attempts, last_exception)
            return_type = func.__annotations__.get('return')
            if return_type is bool:
                return False
            elif return_type and 'List' in str(return_type):
                return []
            return None
        return wrapper
    return decorator


class Neo4jKnowledgeRepository:
    """
    Knowledge Graph repository using Neo4j.

    Provides real database connectivity for RAG queries.
    """

    def __init__(self):
        """Initialize Neo4j connection."""
        self._driver = None
        self._available = False
        self._init_driver()

    @staticmethod
    def _convert_neo4j_datetime(value: Any) -> Any:
        """Convert neo4j.time.DateTime to Python datetime or ISO string."""
        if value is None:
            return None

        type_name = type(value).__name__
        if type_name in ('DateTime', 'Date', 'Time', 'Duration'):
            try:
                if hasattr(value, 'to_native'):
                    return value.to_native()
                return str(value)
            except Exception as e:
                logger.debug("Neo4j value conversion failed: %s", e)
                return str(value)

        return value

    def _init_driver(self):
        """Initialize Neo4j driver with Aura-optimized settings.

        Sprint 165: Guarded by enable_neo4j flag — skips connection when disabled.
        """
        if not getattr(settings, "enable_neo4j", False):
            logger.info("Neo4j disabled (enable_neo4j=False) — Learning Graph unavailable")
            self._available = False
            return

        try:
            from neo4j import GraphDatabase

            username = settings.neo4j_username_resolved

            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(username, settings.neo4j_password),
                max_connection_lifetime=3000,
                liveness_check_timeout=300,
                max_connection_pool_size=10,
                connection_acquisition_timeout=60
            )
            self._driver.verify_connectivity()
            self._available = True
            logger.info("Neo4j connected with Aura-optimized settings to %s", settings.neo4j_uri)
        except Exception as e:
            logger.warning("Neo4j connection failed: %s", e)
            self._available = False

    def is_available(self) -> bool:
        """Check if Neo4j is available."""
        return self._available

    def _resolve_scope(
        self,
        organization_id: Optional[str] = None,
        *,
        write: bool = False,
    ) -> MemoryWriteScope:
        if isinstance(organization_id, str) and organization_id.strip():
            return MemoryWriteScope(
                org_id=organization_id.strip(),
                state="explicit",
                warnings=[],
                write_allowed=True,
            )
        return resolve_memory_write_scope() if write else resolve_memory_read_scope()

    def _uses_org_scope(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.org_id and scope.state != "single_tenant_default")

    def _org_params(self, scope: MemoryWriteScope) -> dict[str, Any]:
        if not self._uses_org_scope(scope):
            return {}
        return {"organization_id": scope.org_id}

    def _scope_for_operation(
        self,
        operation: str,
        *,
        write: bool,
        organization_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> Optional[MemoryWriteScope]:
        scope = self._resolve_scope(organization_id, write=write)
        if scope.write_allowed:
            return scope

        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(NEO4J_KNOWLEDGE_SCOPE_BLOCKED_WARNING)
        logger.warning(
            "[Neo4jKG] %s blocked entity_hash=%s document_hash=%s "
            "org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(entity_id),
            hash_memory_identifier(document_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )
        return None

    def ping(self) -> bool:
        """
        Ping Neo4j with a lightweight query to keep connection alive.

        Critical for Neo4j Aura Free Tier which pauses after 72 hours of inactivity.
        """
        if not self._driver:
            return False

        try:
            with self._driver.session() as session:
                result = session.run("RETURN 1 as ping")
                record = result.single()
                if record and record["ping"] == 1:
                    logger.debug("Neo4j ping successful")
                    return True
            return False
        except Exception as e:
            logger.warning("Neo4j ping failed: %s", e)
            self._init_driver()
            return self._available

    # Synonym mapping for better search
    SYNONYMS = {
        # Vietnamese synonyms
        "quy tắc": ["rule", "regulation", "điều"],
        "cảnh giới": ["look-out", "lookout", "watch"],
        "tốc độ": ["speed", "velocity"],
        "an toàn": ["safety", "safe"],
        "va chạm": ["collision", "crash"],
        "tàu": ["vessel", "ship", "boat"],
        "đèn": ["light", "lights", "lighting"],
        "âm hiệu": ["sound", "signal", "horn"],
        "cứu sinh": ["life-saving", "lifesaving", "lifeboat"],
        "phòng cháy": ["fire", "firefighting"],
        # Situation synonyms (Vietnamese)
        "đối hướng": ["head-on", "reciprocal", "ngược hướng", "đối đầu"],
        "cắt hướng": ["crossing", "cross"],
        "vượt": ["overtaking", "overtake"],
        "nhường đường": ["give-way", "give way", "yield"],
        "giữ hướng": ["stand-on", "stand on", "maintain course"],
        "tầm nhìn hạn chế": ["restricted visibility", "poor visibility", "sương mù"],
        "luồng hẹp": ["narrow channel", "fairway"],
        # English synonyms
        "lookout": ["look-out", "watch", "cảnh giới"],
        "rule": ["regulation", "quy tắc", "điều"],
        "vessel": ["ship", "boat", "tàu"],
        "collision": ["crash", "va chạm"],
        "navigation": ["nav", "hành hải"],
        # Situation synonyms (English)
        "head-on": ["đối hướng", "reciprocal", "meeting"],
        "crossing": ["cắt hướng", "cross"],
        "overtaking": ["vượt", "overtake", "passing"],
        "give-way": ["nhường đường", "yield"],
        "stand-on": ["giữ hướng", "maintain"],
        "restricted": ["hạn chế", "limited", "poor"],
        "visibility": ["tầm nhìn", "sight"],
    }

    async def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        organization_id: Optional[str] = None,
    ) -> List[KnowledgeNode]:
        """Search knowledge base using text matching with synonym expansion."""
        logger.info(
            "Neo4j hybrid_search called query_hash=%s query_chars=%d",
            hash_memory_identifier(query),
            len(query or ""),
        )

        if not self._available:
            logger.warning("Neo4j not available for search")
            return []

        scope = self._scope_for_operation(
            "hybrid_search",
            write=False,
            organization_id=organization_id,
        )
        if scope is None:
            return []

        stop_words = {
            "là", "gì", "the", "what", "is", "a", "an", "về", "cho", "tôi",
            "me", "about", "of", "in", "on", "at", "to", "for", "and", "or",
            "how", "why", "when", "where", "which", "who", "như", "thế", "nào"
        }

        query_lower = query.lower()

        expanded_keywords = set()
        for key, synonyms in self.SYNONYMS.items():
            if key in query_lower:
                expanded_keywords.add(key)
                expanded_keywords.update(synonyms)
            for syn in synonyms:
                if syn in query_lower:
                    expanded_keywords.add(key)
                    expanded_keywords.update(synonyms)

        keywords = [w for w in query_lower.split() if w not in stop_words and len(w) > 1]

        if not keywords:
            keywords = [query_lower]

        for kw in keywords:
            expanded_keywords.add(kw)
            if kw in self.SYNONYMS:
                expanded_keywords.update(self.SYNONYMS[kw])
            for key, synonyms in self.SYNONYMS.items():
                if kw in synonyms:
                    expanded_keywords.add(key)
                    expanded_keywords.update(synonyms)

        keywords = list(expanded_keywords)
        logger.info("Search keywords expanded_count=%d", len(keywords))

        import re
        rule_numbers = re.findall(r'\b(\d+)\b', query)
        if rule_numbers:
            for num in rule_numbers:
                keywords.append(f"rule {num}")
                keywords.append(f"rule{num}")

        logger.info("Final keyword_count=%d", len(keywords))

        try:
            with self._driver.session() as session:
                if self._uses_org_scope(scope):
                    cypher = """
                    MATCH (k:Knowledge {organization_id: $organization_id})
                    WHERE ANY(keyword IN $keywords WHERE
                        toLower(k.title) CONTAINS keyword OR
                        toLower(k.content) CONTAINS keyword OR
                        toLower(k.category) CONTAINS keyword
                    )
                    WITH DISTINCT k,
                        REDUCE(score = 0, keyword IN $keywords |
                            score +
                            CASE WHEN toLower(k.title) CONTAINS keyword THEN 15 ELSE 0 END +
                            CASE WHEN toLower(k.content) CONTAINS keyword THEN 1 ELSE 0 END
                        ) AS relevance
                    RETURN k, relevance
                    ORDER BY relevance DESC
                    LIMIT $max_results
                    """
                else:
                    cypher = """
                    MATCH (k:Knowledge)
                    WHERE ANY(keyword IN $keywords WHERE
                        toLower(k.title) CONTAINS keyword OR
                        toLower(k.content) CONTAINS keyword OR
                        toLower(k.category) CONTAINS keyword
                    )
                    WITH DISTINCT k,
                        REDUCE(score = 0, keyword IN $keywords |
                            score +
                            CASE WHEN toLower(k.title) CONTAINS keyword THEN 15 ELSE 0 END +
                            CASE WHEN toLower(k.content) CONTAINS keyword THEN 1 ELSE 0 END
                        ) AS relevance
                    RETURN k, relevance
                    ORDER BY relevance DESC
                    LIMIT $max_results
                    """

                params = {
                    "keywords": keywords,
                    "max_results": limit,
                    **self._org_params(scope),
                }

                logger.info("Executing Neo4j query keyword_count=%d", len(keywords))
                result = session.run(cypher, **params)

                nodes = []
                seen_ids = set()

                for record in result:
                    node_data = record["k"]
                    relevance = record["relevance"]
                    node_id = node_data.get("id", "")

                    if node_id in seen_ids:
                        continue
                    seen_ids.add(node_id)

                    logger.info(
                        "Found Neo4j node node_hash=%s score=%s",
                        hash_memory_identifier(node_id),
                        relevance,
                    )
                    nodes.append(KnowledgeNode(
                        id=node_id,
                        node_type=NodeType.CONCEPT,
                        title=node_data.get("title", ""),
                        content=node_data.get("content", ""),
                        source=node_data.get("source", ""),
                        metadata={
                            "category": node_data.get("category", ""),
                            "subcategory": node_data.get("subcategory", ""),
                            "relevance": relevance
                        }
                    ))

                logger.info("Neo4j search returned %d unique nodes", len(nodes))
                return nodes

        except Exception as e:
            logger.error("Neo4j search failed: %s", e)
            return []

    async def get_citations(
        self,
        nodes: List[KnowledgeNode]
    ) -> List[Citation]:
        """Generate citations for nodes."""
        citations = []

        for node in nodes:
            citations.append(Citation(
                node_id=node.id,
                source=node.source or "Knowledge Base",
                title=node.title,
                relevance_score=0.8
            ))

        return citations

    # =========================================================================
    # Document KG Entity Methods (Feature: document-kg)
    # =========================================================================

    async def create_entity(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        name_vi: Optional[str] = None,
        description: str = "",
        document_id: Optional[str] = None,
        chunk_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Create an Entity node extracted from a document."""
        if not self._available:
            logger.warning("Neo4j not available for entity creation")
            return False

        scope = self._scope_for_operation(
            "create_entity",
            write=True,
            organization_id=organization_id,
            entity_id=entity_id,
            document_id=document_id,
        )
        if scope is None:
            return False

        org_params = self._org_params(scope)
        effective_org_id = org_params.get("organization_id")

        try:
            with self._driver.session() as session:
                if self._uses_org_scope(scope):
                    cypher = """
                    MERGE (e:Entity {id: $entity_id, organization_id: $organization_id})
                    ON CREATE SET
                        e.type = $entity_type,
                        e.name = $name,
                        e.name_vi = $name_vi,
                        e.description = $description,
                        e.created_at = datetime(),
                        e.document_id = $document_id,
                        e.chunk_id = $chunk_id
                    ON MATCH SET
                        e.updated_at = datetime(),
                        e.description = CASE WHEN size($description) > size(e.description)
                                             THEN $description ELSE e.description END
                    RETURN e.id as id
                    """
                else:
                    cypher = """
                    MERGE (e:Entity {id: $entity_id})
                    ON CREATE SET
                        e.type = $entity_type,
                        e.name = $name,
                        e.name_vi = $name_vi,
                        e.description = $description,
                        e.created_at = datetime(),
                        e.document_id = $document_id,
                        e.chunk_id = $chunk_id,
                        e.organization_id = $organization_id
                    ON MATCH SET
                        e.updated_at = datetime(),
                        e.description = CASE WHEN size($description) > size(e.description)
                                             THEN $description ELSE e.description END
                    RETURN e.id as id
                    """
                result = session.run(
                    cypher,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    name=name,
                    name_vi=name_vi,
                    description=description,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    organization_id=effective_org_id,
                )
                record = result.single()
                logger.debug(
                    "Created/merged entity entity_hash=%s type=%s org_hash=%s",
                    hash_memory_identifier(entity_id),
                    entity_type,
                    hash_memory_identifier(effective_org_id),
                )
                return record is not None

        except Exception as e:
            logger.error("Failed to create entity entity_hash=%s: %s", hash_memory_identifier(entity_id), e)
            return False

    async def create_entity_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str = "",
        organization_id: Optional[str] = None,
    ) -> bool:
        """
        Create a relation between two entities with validated relation type.

        **Security:** Validates relation_type against allowlist to prevent Cypher injection.
        CRITICAL: Validation happens BEFORE Neo4j availability check.
        """
        # SECURITY CRITICAL: Validate BEFORE any other check
        if relation_type not in ALLOWED_RELATION_TYPES:
            logger.warning(
                "[SECURITY] Rejected invalid relation type: '%s' "
                "from source=%s, target=%s", relation_type, source_id, target_id
            )
            raise ValueError(
                f"Invalid relation type: '{relation_type}'. "
                f"Must be one of: {sorted(ALLOWED_RELATION_TYPES)}"
            )

        if not self._available:
            return False

        scope = self._scope_for_operation(
            "create_entity_relation",
            write=True,
            organization_id=organization_id,
            entity_id=source_id,
        )
        if scope is None:
            return False

        org_params = self._org_params(scope)
        effective_org_id = org_params.get("organization_id")

        try:
            with self._driver.session() as session:
                if self._uses_org_scope(scope):
                    cypher = f"""
                    MATCH (s:Entity {{id: $source_id, organization_id: $organization_id}})
                    MATCH (t:Entity {{id: $target_id, organization_id: $organization_id}})
                    MERGE (s)-[r:{relation_type}]->(t)
                    ON CREATE SET r.description = $description, r.created_at = datetime(),
                                  r.organization_id = $organization_id
                    RETURN type(r) as rel_type
                    """
                else:
                    cypher = f"""
                    MATCH (s:Entity {{id: $source_id}})
                    MATCH (t:Entity {{id: $target_id}})
                    MERGE (s)-[r:{relation_type}]->(t)
                    ON CREATE SET r.description = $description, r.created_at = datetime(),
                                  r.organization_id = $organization_id
                    RETURN type(r) as rel_type
                    """
                result = session.run(
                    cypher,
                    source_id=source_id,
                    target_id=target_id,
                    description=description,
                    organization_id=effective_org_id,
                )
                record = result.single()
                if record:
                    logger.debug(
                        "Created relation source_hash=%s rel_type=%s target_hash=%s org_hash=%s",
                        hash_memory_identifier(source_id),
                        relation_type,
                        hash_memory_identifier(target_id),
                        hash_memory_identifier(effective_org_id),
                    )
                    return True
                return False

        except Exception as e:
            logger.error(
                "Failed to create relation source_hash=%s target_hash=%s: %s",
                hash_memory_identifier(source_id),
                hash_memory_identifier(target_id),
                e,
            )
            return False

    async def get_entity_relations(
        self, entity_id: str, organization_id: Optional[str] = None
    ) -> List[dict]:
        """Get all relations for an entity, optionally filtered by org."""
        if not self._available:
            return []

        scope = self._scope_for_operation(
            "get_entity_relations",
            write=False,
            organization_id=organization_id,
            entity_id=entity_id,
        )
        if scope is None:
            return []

        try:
            with self._driver.session() as session:
                if self._uses_org_scope(scope):
                    cypher = """
                    MATCH (e:Entity {id: $entity_id, organization_id: $organization_id})-[r]->(t:Entity)
                    RETURN type(r) as relation_type, t.id as target_id,
                           t.name as target_name, t.type as target_type
                    """
                    result = session.run(cypher, entity_id=entity_id, **self._org_params(scope))
                else:
                    cypher = """
                    MATCH (e:Entity {id: $entity_id})-[r]->(t:Entity)
                    RETURN type(r) as relation_type, t.id as target_id,
                           t.name as target_name, t.type as target_type
                    """
                    result = session.run(cypher, entity_id=entity_id)
                return [dict(record) for record in result]

        except Exception as e:
            logger.error("Failed to get relations for entity_hash=%s: %s", hash_memory_identifier(entity_id), e)
            return []

    @neo4j_retry(max_attempts=2, backoff=1.0)
    async def get_document_entities(
        self, document_id: str, organization_id: Optional[str] = None
    ) -> List[dict]:
        """Get all entities extracted from a document, optionally filtered by org."""
        if not self._available:
            logger.warning(
                "Neo4j not available for get_document_entities document_hash=%s",
                hash_memory_identifier(document_id),
            )
            return []

        scope = self._scope_for_operation(
            "get_document_entities",
            write=False,
            organization_id=organization_id,
            document_id=document_id,
        )
        if scope is None:
            return []

        try:
            with self._driver.session() as session:
                if self._uses_org_scope(scope):
                    cypher = """
                    MATCH (e:Entity {document_id: $document_id, organization_id: $organization_id})
                    RETURN e.id as id, e.name as name, e.name_vi as name_vi,
                           e.type as type, e.description as description
                    """
                    result = session.run(cypher, document_id=document_id, **self._org_params(scope))
                else:
                    cypher = """
                    MATCH (e:Entity {document_id: $document_id})
                    RETURN e.id as id, e.name as name, e.name_vi as name_vi,
                           e.type as type, e.description as description
                    """
                    result = session.run(cypher, document_id=document_id)
                return [dict(record) for record in result]

        except Exception as e:
            logger.error(
                "Failed to get entities for document_hash=%s: %s",
                hash_memory_identifier(document_id),
                e,
            )
            raise  # Let retry decorator handle it

    def close(self):
        """Close Neo4j connection."""
        if self._driver:
            self._driver.close()
