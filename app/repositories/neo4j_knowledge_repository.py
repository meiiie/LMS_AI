"""
Neo4j Knowledge Graph Repository.

Connects to Neo4j database for knowledge retrieval.
"""

import logging
from typing import List, Optional

from app.core.config import settings
from app.models.knowledge_graph import (
    Citation,
    KnowledgeNode,
    NodeType,
    RelationType,
)

logger = logging.getLogger(__name__)


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
    
    def _init_driver(self):
        """Initialize Neo4j driver (supports both local Docker and Neo4j Aura)."""
        try:
            from neo4j import GraphDatabase
            
            # Use neo4j_username_resolved to support both formats
            username = settings.neo4j_username_resolved
            
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(username, settings.neo4j_password)
            )
            self._driver.verify_connectivity()
            self._available = True
            logger.info(f"Neo4j connection established to {settings.neo4j_uri}")
        except Exception as e:
            logger.warning(f"Neo4j connection failed: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if Neo4j is available."""
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
    
    def close(self):
        """Close Neo4j connection."""
        if self._driver:
            self._driver.close()
