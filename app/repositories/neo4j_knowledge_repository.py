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

See: .kiro/specs/sparse-search-migration/design.md for migration details.
"""

import asyncio
import logging
from datetime import datetime
from functools import wraps
from typing import Any, List, Optional

from app.core.config import settings
from app.models.knowledge_graph import (
    Citation,
    KnowledgeNode,
    NodeType,
    RelationType,
)

logger = logging.getLogger(__name__)


def neo4j_retry(max_attempts: int = 2, backoff: float = 1.0):
    """
    SOTA: Retry decorator for Neo4j transient failures.
    
    Handles ServiceUnavailable, SessionExpired, and OSError (defunct connection).
    Uses exponential backoff between retries.
    
    Based on: https://neo4j.com/docs/python-manual/current/transactions/
    
    Args:
        max_attempts: Maximum number of retry attempts
        backoff: Initial backoff time in seconds (doubles each retry)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(self, *args, **kwargs)
                except OSError as e:
                    # Defunct connection - needs reconnect
                    last_exception = e
                    logger.warning(
                        f"Neo4j connection error (attempt {attempt+1}/{max_attempts}): {e}"
                    )
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(backoff * (2 ** attempt))
                        # Try to reconnect
                        self._init_driver()
                except Exception as e:
                    # Check for neo4j-specific transient errors
                    error_name = type(e).__name__
                    if error_name in ('ServiceUnavailable', 'SessionExpired', 'TransientError'):
                        last_exception = e
                        logger.warning(
                            f"Neo4j transient error (attempt {attempt+1}/{max_attempts}): {e}"
                        )
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(backoff * (2 ** attempt))
                            self._init_driver()
                    else:
                        # Non-transient error, propagate immediately
                        raise
            
            logger.error(f"Neo4j operation failed after {max_attempts} attempts: {last_exception}")
            # Return appropriate default based on return type hint
            return_type = func.__annotations__.get('return')
            if return_type == bool:
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
        """
        Convert neo4j.time.DateTime to Python datetime or ISO string.
        
        Neo4j returns its own DateTime type which Pydantic cannot serialize.
        This helper converts it to a standard Python datetime.
        """
        if value is None:
            return None
        
        # Check if it's a neo4j DateTime type
        type_name = type(value).__name__
        if type_name in ('DateTime', 'Date', 'Time', 'Duration'):
            try:
                # neo4j.time.DateTime has to_native() method
                if hasattr(value, 'to_native'):
                    return value.to_native()
                # Fallback: convert to ISO string
                return str(value)
            except Exception:
                return str(value)
        
        return value
    
    def _init_driver(self):
        """
        Initialize Neo4j driver with Aura-optimized settings.
        
        SOTA Pattern (Neo4j Official Docs):
        - max_connection_lifetime < 60 min (Aura idle timeout)
        - liveness_check_timeout for connection health
        - connection_acquisition_timeout for waiting
        """
        try:
            from neo4j import GraphDatabase
            
            # Use neo4j_username_resolved to support both formats
            username = settings.neo4j_username_resolved
            
            # SOTA: Aura Free Tier connection settings
            # Based on: https://neo4j.com/docs/python-manual/current/connect-advanced/
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(username, settings.neo4j_password),
                # Retire connections before Aura's 60-min idle timeout
                max_connection_lifetime=3000,      # 50 minutes (seconds)
                # Keep-alive check interval  
                liveness_check_timeout=300,        # 5 minutes (seconds)
                # Connection pool settings
                max_connection_pool_size=10,
                connection_acquisition_timeout=60  # 1 minute
            )
            self._driver.verify_connectivity()
            self._available = True
            logger.info(f"Neo4j connected with Aura-optimized settings to {settings.neo4j_uri}")
        except Exception as e:
            logger.warning(f"Neo4j connection failed: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if Neo4j is available."""
        return self._available
    
    def _ensure_connection(self) -> bool:
        """
        Ensure Neo4j connection is alive, auto-reconnect if needed.
        
        This handles Neo4j Aura Free Tier connection timeouts and defunct connections.
        
        Returns:
            True if connection is available, False otherwise
        """
        if not self._available:
            return False
        
        try:
            # Try a lightweight query to check connection
            with self._driver.session() as session:
                session.run("RETURN 1").single()
            return True
        except Exception as e:
            logger.warning(f"Neo4j connection check failed: {e}, attempting reconnect...")
            # Try to reconnect
            try:
                if self._driver:
                    self._driver.close()
            except Exception:
                pass
            
            self._init_driver()
            return self._available
    
    def ping(self) -> bool:
        """
        Ping Neo4j with a lightweight query to keep connection alive.
        
        This is critical for Neo4j Aura Free Tier which pauses after 72 hours
        of inactivity. Running this query resets the inactivity timer.
        
        Returns:
            True if ping successful, False otherwise
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
            logger.warning(f"Neo4j ping failed: {e}")
            # Try to reconnect
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
        limit: int = 5
    ) -> List[KnowledgeNode]:
        """
        Search knowledge base using text matching with synonym expansion.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching KnowledgeNodes (deduplicated)
        """
        logger.info(f"Neo4j hybrid_search called with query: {query}")
        
        if not self._available:
            logger.warning("Neo4j not available for search")
            return []
        
        # Extract keywords from query (remove common words)
        stop_words = {
            "là", "gì", "the", "what", "is", "a", "an", "về", "cho", "tôi", 
            "me", "about", "of", "in", "on", "at", "to", "for", "and", "or",
            "how", "why", "when", "where", "which", "who", "như", "thế", "nào"
        }
        
        query_lower = query.lower()
        
        # First, check for multi-word phrase matches in synonyms
        expanded_keywords = set()
        for key, synonyms in self.SYNONYMS.items():
            # Check if key phrase is in query
            if key in query_lower:
                expanded_keywords.add(key)
                expanded_keywords.update(synonyms)
            # Check if any synonym phrase is in query
            for syn in synonyms:
                if syn in query_lower:
                    expanded_keywords.add(key)
                    expanded_keywords.update(synonyms)
        
        # Then extract individual keywords
        keywords = [w for w in query_lower.split() if w not in stop_words and len(w) > 1]
        
        if not keywords:
            keywords = [query_lower]
        
        # Expand single-word keywords with synonyms
        for kw in keywords:
            expanded_keywords.add(kw)
            # Check direct synonyms
            if kw in self.SYNONYMS:
                expanded_keywords.update(self.SYNONYMS[kw])
            # Check if keyword is in any synonym list
            for key, synonyms in self.SYNONYMS.items():
                if kw in synonyms:
                    expanded_keywords.add(key)
                    expanded_keywords.update(synonyms)
        
        keywords = list(expanded_keywords)
        logger.info(f"Search keywords (expanded): {keywords}")
        
        # Extract rule numbers from query (e.g., "Rule 5", "Quy tắc 15")
        import re
        rule_numbers = re.findall(r'\b(\d+)\b', query)
        if rule_numbers:
            # Add rule number patterns to keywords
            for num in rule_numbers:
                keywords.append(f"rule {num}")
                keywords.append(f"rule{num}")
        
        logger.info(f"Final keywords: {keywords}")
        
        try:
            with self._driver.session() as session:
                # Search with relevance scoring
                # Priority: title match > content match, exact number match gets bonus
                cypher = """
                MATCH (k:Knowledge)
                WHERE ANY(keyword IN $keywords WHERE 
                    toLower(k.title) CONTAINS keyword OR 
                    toLower(k.content) CONTAINS keyword OR
                    toLower(k.category) CONTAINS keyword
                )
                WITH DISTINCT k,
                    // Calculate relevance score - title matches worth more
                    REDUCE(score = 0, keyword IN $keywords |
                        score + 
                        CASE WHEN toLower(k.title) CONTAINS keyword THEN 15 ELSE 0 END +
                        CASE WHEN toLower(k.content) CONTAINS keyword THEN 1 ELSE 0 END
                    ) AS relevance
                RETURN k, relevance
                ORDER BY relevance DESC
                LIMIT $max_results
                """
                
                logger.info(f"Executing Neo4j query with keywords: {keywords}")
                result = session.run(cypher, keywords=keywords, max_results=limit)
                
                nodes = []
                seen_ids = set()  # Additional deduplication
                
                for record in result:
                    node_data = record["k"]
                    relevance = record["relevance"]
                    node_id = node_data.get("id", "")
                    
                    # Skip duplicates
                    if node_id in seen_ids:
                        continue
                    seen_ids.add(node_id)
                    
                    logger.info(f"Found node: {node_data.get('title', 'N/A')} (score: {relevance})")
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
                
                logger.info(f"Neo4j search returned {len(nodes)} unique nodes")
                return nodes
                
        except Exception as e:
            logger.error(f"Neo4j search failed: {e}")
            return []
    
    async def get_by_category(
        self,
        category: str,
        limit: int = 10
    ) -> List[KnowledgeNode]:
        """Get knowledge nodes by category."""
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (k:Knowledge)-[:BELONGS_TO]->(c:Category {name: $category})
                RETURN k
                LIMIT $limit
                """
                
                result = session.run(cypher, category=category, limit=limit)
                
                nodes = []
                for record in result:
                    node_data = record["k"]
                    nodes.append(KnowledgeNode(
                        id=node_data.get("id", ""),
                        node_type=NodeType.CONCEPT,
                        title=node_data.get("title", ""),
                        content=node_data.get("content", ""),
                        source=node_data.get("source", ""),
                        metadata={"category": category}
                    ))
                
                return nodes
                
        except Exception as e:
            logger.error(f"Neo4j category query failed: {e}")
            return []
    
    async def traverse_relations(
        self,
        node_id: str,
        relation_types: List[RelationType],
        depth: int = 1
    ) -> List[KnowledgeNode]:
        """Traverse relations from a node."""
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (k:Knowledge {id: $node_id})-[r]-(related:Knowledge)
                RETURN related
                LIMIT 5
                """
                
                result = session.run(cypher, node_id=node_id)
                
                nodes = []
                for record in result:
                    node_data = record["related"]
                    nodes.append(KnowledgeNode(
                        id=node_data.get("id", ""),
                        node_type=NodeType.CONCEPT,
                        title=node_data.get("title", ""),
                        content=node_data.get("content", ""),
                        source=node_data.get("source", "")
                    ))
                
                return nodes
                
        except Exception as e:
            logger.error(f"Neo4j traverse failed: {e}")
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
                source=node.source or "Maritime Knowledge Base",
                title=node.title,
                relevance_score=0.8
            ))
        
        return citations
    
    async def get_all_categories(self) -> List[str]:
        """Get all knowledge categories."""
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                cypher = "MATCH (c:Category) RETURN c.name as name"
                result = session.run(cypher)
                return [record["name"] for record in result]
        except Exception as e:
            logger.error(f"Neo4j categories query failed: {e}")
            return []
    
    async def get_stats(self) -> dict:
        """Get knowledge base statistics."""
        if not self._available:
            return {"total": 0, "categories": 0}
        
        try:
            with self._driver.session() as session:
                # Count nodes
                result = session.run("MATCH (k:Knowledge) RETURN count(k) as count")
                total = result.single()["count"]
                
                # Count categories
                result = session.run("MATCH (c:Category) RETURN count(c) as count")
                categories = result.single()["count"]
                
                return {
                    "total": total,
                    "categories": categories
                }
        except Exception as e:
            logger.error(f"Neo4j stats query failed: {e}")
            return {"total": 0, "categories": 0}
    
    # ==================== Document Management Methods ====================
    # Feature: knowledge-ingestion
    # Requirements: 4.1, 4.3, 4.4, 6.1, 6.3
    
    async def create_document(
        self,
        document_id: str,
        filename: str,
        category: str,
        content_hash: str,
        uploaded_by: str
    ) -> str:
        """
        Create a Document node to track uploaded files.
        
        **Validates: Requirements 4.1**
        """
        if not self._available:
            raise RuntimeError("Neo4j not available")
        
        try:
            with self._driver.session() as session:
                cypher = """
                MERGE (c:Category {name: $category})
                CREATE (d:Document {
                    id: $document_id,
                    filename: $filename,
                    category: $category,
                    content_hash: $content_hash,
                    uploaded_by: $uploaded_by,
                    uploaded_at: datetime(),
                    nodes_count: 0
                })
                MERGE (d)-[:IN_CATEGORY]->(c)
                RETURN d.id as id
                """
                result = session.run(
                    cypher,
                    document_id=document_id,
                    filename=filename,
                    category=category,
                    content_hash=content_hash,
                    uploaded_by=uploaded_by
                )
                record = result.single()
                logger.info(f"Created document node: {document_id}")
                return record["id"]
        except Exception as e:
            logger.error(f"Failed to create document: {e}")
            raise
    
    async def create_knowledge_node(
        self,
        node_id: str,
        title: str,
        content: str,
        category: str,
        source: str,
        document_id: str,
        chunk_index: int
    ) -> bool:
        """
        Create a Knowledge node from a document chunk.
        
        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        if not self._available:
            raise RuntimeError("Neo4j not available")
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (d:Document {id: $document_id})
                MERGE (c:Category {name: $category})
                CREATE (k:Knowledge {
                    id: $node_id,
                    title: $title,
                    content: $content,
                    category: $category,
                    source: $source,
                    document_id: $document_id,
                    chunk_index: $chunk_index
                })
                MERGE (k)-[:BELONGS_TO]->(c)
                MERGE (k)-[:FROM_DOCUMENT]->(d)
                WITH d
                SET d.nodes_count = d.nodes_count + 1
                RETURN true as success
                """
                result = session.run(
                    cypher,
                    node_id=node_id,
                    title=title,
                    content=content,
                    category=category,
                    source=source,
                    document_id=document_id,
                    chunk_index=chunk_index
                )
                result.single()
                return True
        except Exception as e:
            logger.error(f"Failed to create knowledge node: {e}")
            return False
    
    async def delete_document_nodes(self, document_id: str) -> int:
        """
        Delete a document and all its associated Knowledge nodes.
        
        **Validates: Requirements 6.3**
        """
        if not self._available:
            raise RuntimeError("Neo4j not available")
        
        try:
            with self._driver.session() as session:
                # First count nodes to delete
                count_cypher = """
                MATCH (k:Knowledge {document_id: $document_id})
                RETURN count(k) as count
                """
                result = session.run(count_cypher, document_id=document_id)
                count = result.single()["count"]
                
                # Delete knowledge nodes
                delete_knowledge = """
                MATCH (k:Knowledge {document_id: $document_id})
                DETACH DELETE k
                """
                session.run(delete_knowledge, document_id=document_id)
                
                # Delete document node
                delete_doc = """
                MATCH (d:Document {id: $document_id})
                DETACH DELETE d
                """
                session.run(delete_doc, document_id=document_id)
                
                logger.info(f"Deleted document {document_id} with {count} knowledge nodes")
                return count
        except Exception as e:
            logger.error(f"Failed to delete document nodes: {e}")
            raise
    
    async def get_document_list(
        self,
        page: int = 1,
        limit: int = 20
    ) -> List[dict]:
        """
        Get paginated list of uploaded documents.
        
        **Validates: Requirements 6.1**
        """
        if not self._available:
            return []
        
        try:
            skip = (page - 1) * limit
            with self._driver.session() as session:
                cypher = """
                MATCH (d:Document)
                RETURN d.id as id, d.filename as filename, d.category as category,
                       d.nodes_count as nodes_count, d.uploaded_by as uploaded_by,
                       d.uploaded_at as uploaded_at
                ORDER BY d.uploaded_at DESC
                SKIP $skip LIMIT $limit
                """
                result = session.run(cypher, skip=skip, limit=limit)
                
                documents = []
                for record in result:
                    # Convert neo4j.time.DateTime to Python datetime
                    uploaded_at = self._convert_neo4j_datetime(record["uploaded_at"])
                    documents.append({
                        "id": record["id"],
                        "filename": record["filename"],
                        "category": record["category"],
                        "nodes_count": record["nodes_count"],
                        "uploaded_by": record["uploaded_by"],
                        "uploaded_at": uploaded_at
                    })
                return documents
        except Exception as e:
            logger.error(f"Failed to get document list: {e}")
            return []
    
    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """
        Check if a document with the same content hash already exists.
        
        **Validates: Requirements 4.4**
        """
        if not self._available:
            return None
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (d:Document {content_hash: $content_hash})
                RETURN d.id as id
                LIMIT 1
                """
                result = session.run(cypher, content_hash=content_hash)
                record = result.single()
                if record:
                    return record["id"]
                return None
        except Exception as e:
            logger.error(f"Failed to check duplicate: {e}")
            return None
    
    async def get_extended_stats(self) -> dict:
        """
        Get extended knowledge base statistics including documents.
        
        **Validates: Requirements 6.2**
        """
        if not self._available:
            return {"total_documents": 0, "total_nodes": 0, "categories": {}}
        
        try:
            with self._driver.session() as session:
                # Count documents
                doc_result = session.run("MATCH (d:Document) RETURN count(d) as count")
                total_documents = doc_result.single()["count"]
                
                # Count nodes
                node_result = session.run("MATCH (k:Knowledge) RETURN count(k) as count")
                total_nodes = node_result.single()["count"]
                
                # Category breakdown
                cat_cypher = """
                MATCH (k:Knowledge)
                RETURN k.category as category, count(k) as count
                ORDER BY count DESC
                """
                cat_result = session.run(cat_cypher)
                categories = {r["category"]: r["count"] for r in cat_result}
                
                # Recent uploads
                recent_cypher = """
                MATCH (d:Document)
                RETURN d.id as id, d.filename as filename, d.category as category,
                       d.nodes_count as nodes_count, d.uploaded_at as uploaded_at
                ORDER BY d.uploaded_at DESC
                LIMIT 5
                """
                recent_result = session.run(recent_cypher)
                
                # Convert neo4j.time.DateTime to Python datetime for each record
                recent_uploads = []
                for r in recent_result:
                    doc = dict(r)
                    doc["uploaded_at"] = self._convert_neo4j_datetime(doc.get("uploaded_at"))
                    recent_uploads.append(doc)
                
                return {
                    "total_documents": total_documents,
                    "total_nodes": total_nodes,
                    "categories": categories,
                    "recent_uploads": recent_uploads
                }
        except Exception as e:
            logger.error(f"Failed to get extended stats: {e}")
            return {"total_documents": 0, "total_nodes": 0, "categories": {}}
    
    def get_all_knowledge_nodes(self) -> List[dict]:
        """
        Get all Knowledge nodes for embedding generation.
        
        Returns list of dicts with id, title, content.
        
        **Feature: hybrid-search**
        **Validates: Requirements 2.1, 6.1**
        """
        if not self._available:
            logger.warning("Neo4j not available")
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (k:Knowledge)
                RETURN k.id as id, k.title as title, k.content as content
                """
                result = session.run(cypher)
                
                nodes = []
                for record in result:
                    nodes.append({
                        "id": record["id"],
                        "title": record["title"] or "",
                        "content": record["content"] or ""
                    })
                
                logger.info(f"Retrieved {len(nodes)} Knowledge nodes")
                return nodes
                
        except Exception as e:
            logger.error(f"Failed to get all knowledge nodes: {e}")
            return []
    
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
        chunk_id: Optional[str] = None
    ) -> bool:
        """
        Create an Entity node extracted from document.
        
        **Feature: document-kg**
        **CHỈ THỊ KỸ THUẬT SỐ 29: Automated Knowledge Graph Construction**
        
        Args:
            entity_id: Unique entity ID (snake_case)
            entity_type: Type (ARTICLE, REGULATION, VESSEL_TYPE, etc.)
            name: English name
            name_vi: Vietnamese name
            description: Brief description
            document_id: Source document ID
            chunk_id: Source chunk ID
            
        Returns:
            True if created successfully
        """
        if not self._available:
            logger.warning("Neo4j not available for entity creation")
            return False
        
        try:
            with self._driver.session() as session:
                cypher = """
                MERGE (e:Entity {id: $entity_id})
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
                result = session.run(
                    cypher,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    name=name,
                    name_vi=name_vi,
                    description=description,
                    document_id=document_id,
                    chunk_id=chunk_id
                )
                record = result.single()
                logger.debug(f"Created/merged entity: {entity_id} ({entity_type})")
                return record is not None
                
        except Exception as e:
            logger.error(f"Failed to create entity {entity_id}: {e}")
            return False
    
    async def create_entity_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str = ""
    ) -> bool:
        """
        Create a relation between two entities.
        
        **Feature: document-kg**
        
        Args:
            source_id: Source entity ID
            target_id: Target entity ID
            relation_type: Type (REFERENCES, APPLIES_TO, etc.)
            description: Relation description
            
        Returns:
            True if created successfully
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                # Use dynamic relationship type
                cypher = f"""
                MATCH (s:Entity {{id: $source_id}})
                MATCH (t:Entity {{id: $target_id}})
                MERGE (s)-[r:{relation_type}]->(t)
                ON CREATE SET r.description = $description, r.created_at = datetime()
                RETURN type(r) as rel_type
                """
                result = session.run(
                    cypher,
                    source_id=source_id,
                    target_id=target_id,
                    description=description
                )
                record = result.single()
                if record:
                    logger.debug(f"Created relation: {source_id} -[{relation_type}]-> {target_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to create relation {source_id}->{target_id}: {e}")
            return False
    
    async def link_entity_to_chunk(
        self,
        entity_id: str,
        chunk_id: str
    ) -> bool:
        """
        Link an entity to its source chunk for provenance.
        
        **Feature: document-kg**
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (e:Entity {id: $entity_id})
                MERGE (c:Chunk {id: $chunk_id})
                MERGE (c)-[:MENTIONS]->(e)
                RETURN c.id as chunk_id
                """
                result = session.run(cypher, entity_id=entity_id, chunk_id=chunk_id)
                return result.single() is not None
                
        except Exception as e:
            logger.error(f"Failed to link entity {entity_id} to chunk {chunk_id}: {e}")
            return False
    
    async def get_entities_by_type(self, entity_type: str, limit: int = 50) -> List[dict]:
        """
        Get entities by type.
        
        **Feature: document-kg**
        """
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (e:Entity {type: $entity_type})
                RETURN e.id as id, e.name as name, e.name_vi as name_vi, 
                       e.description as description, e.type as type
                LIMIT $limit
                """
                result = session.run(cypher, entity_type=entity_type, limit=limit)
                return [dict(record) for record in result]
                
        except Exception as e:
            logger.error(f"Failed to get entities by type {entity_type}: {e}")
            return []
    
    async def get_entity_relations(self, entity_id: str) -> List[dict]:
        """
        Get all relations for an entity.
        
        **Feature: document-kg**
        """
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (e:Entity {id: $entity_id})-[r]->(t:Entity)
                RETURN type(r) as relation_type, t.id as target_id, 
                       t.name as target_name, t.type as target_type
                """
                result = session.run(cypher, entity_id=entity_id)
                return [dict(record) for record in result]
                
        except Exception as e:
            logger.error(f"Failed to get relations for {entity_id}: {e}")
            return []
    
    @neo4j_retry(max_attempts=2, backoff=1.0)
    async def get_document_entities(self, document_id: str) -> List[dict]:
        """
        Get all entities extracted from a document.
        
        SOTA: Uses retry decorator for transient failures.
        
        **Feature: document-kg**
        """
        if not self._available:
            logger.warning(f"Neo4j not available for get_document_entities({document_id})")
            return []
        
        try:
            with self._driver.session() as session:
                cypher = """
                MATCH (e:Entity {document_id: $document_id})
                RETURN e.id as id, e.name as name, e.name_vi as name_vi,
                       e.type as type, e.description as description
                """
                result = session.run(cypher, document_id=document_id)
                return [dict(record) for record in result]
                
        except Exception as e:
            logger.error(f"Failed to get entities for document {document_id}: {e}")
            raise  # Let retry decorator handle it
    
    def close(self):
        """Close Neo4j connection."""
        if self._driver:
            self._driver.close()
