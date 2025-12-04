"""
Sparse Search Repository for Hybrid Search.

Uses Neo4j Full-text Index for keyword-based search with BM25-style scoring.

Feature: hybrid-search
Requirements: 3.1, 3.2, 3.3, 3.4
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SparseSearchResult:
    """Result from sparse (keyword) search."""
    node_id: str
    title: str
    content: str
    source: str
    category: str
    score: float  # BM25-style relevance score
    
    def __post_init__(self):
        # Ensure score is non-negative
        self.score = max(0.0, self.score)


class SparseSearchRepository:
    """
    Repository for keyword-based search using Neo4j Full-text Index.
    
    Provides BM25-style scoring with number boosting for rule numbers.
    
    Feature: hybrid-search
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    
    # Full-text index name
    INDEX_NAME = "knowledge_fulltext"
    
    # Number boost factor for rule numbers in titles
    NUMBER_BOOST_FACTOR = 5.0
    
    def __init__(self):
        """Initialize repository with Neo4j connection."""
        self._driver = None
        self._available = False
        self._init_driver()
    
    def _init_driver(self):
        """Initialize Neo4j driver."""
        try:
            from neo4j import GraphDatabase
            
            username = settings.neo4j_username_resolved
            
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(username, settings.neo4j_password)
            )
            self._driver.verify_connectivity()
            self._available = True
            logger.info(f"SparseSearchRepository connected to {settings.neo4j_uri}")
        except Exception as e:
            logger.warning(f"Neo4j connection failed for sparse search: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if sparse search is available."""
        return self._available
    
    def _extract_numbers(self, query: str) -> List[str]:
        """
        Extract numbers from query for rule number boosting.
        
        Args:
            query: Search query
            
        Returns:
            List of number strings found in query
        """
        return re.findall(r'\b(\d+)\b', query)
    
    def _build_search_query(self, query: str) -> str:
        """
        Build Lucene query string for full-text search.
        
        Handles Vietnamese and English queries with fuzzy matching.
        
        Args:
            query: User search query
            
        Returns:
            Lucene query string
        """
        # Clean and tokenize query
        words = query.lower().split()
        
        # Remove common stop words
        stop_words = {
            "là", "gì", "the", "what", "is", "a", "an", "về", "cho", "tôi",
            "me", "about", "of", "in", "on", "at", "to", "for", "and", "or",
            "how", "why", "when", "where", "which", "who", "như", "thế", "nào"
        }
        
        words = [w for w in words if w not in stop_words and len(w) > 1]
        
        if not words:
            return query
        
        # Build query with OR between terms
        # Use wildcards for partial matching
        query_parts = []
        for word in words:
            # Exact match gets higher priority
            query_parts.append(word)
            # Wildcard for partial match
            if len(word) > 2:
                query_parts.append(f"{word}*")
        
        return " OR ".join(query_parts)
    
    async def search(
        self,
        query: str,
        limit: int = 10
    ) -> List[SparseSearchResult]:
        """
        Search using Neo4j full-text index.
        
        Args:
            query: Search query (supports natural language)
            limit: Maximum results to return
            
        Returns:
            List of SparseSearchResult sorted by score (descending)
            
        Requirements: 3.2, 3.3, 3.4
        """
        if not self._available:
            logger.warning("Sparse search not available")
            return []
        
        try:
            # Extract numbers for boosting
            numbers = self._extract_numbers(query)
            
            # Build search query
            search_query = self._build_search_query(query)
            
            logger.info(f"Sparse search query: {search_query}, numbers: {numbers}")
            
            with self._driver.session() as session:
                # Use full-text index search
                cypher = """
                CALL db.index.fulltext.queryNodes($index_name, $search_query)
                YIELD node, score
                WITH node as k, score
                RETURN 
                    k.id as node_id,
                    k.title as title,
                    k.content as content,
                    k.source as source,
                    k.category as category,
                    score
                ORDER BY score DESC
                LIMIT $limit
                """
                
                result = session.run(
                    cypher,
                    index_name=self.INDEX_NAME,
                    search_query=search_query,
                    limit=limit * 2  # Get more for boosting
                )
                
                results = []
                for record in result:
                    node_id = record["node_id"] or ""
                    title = record["title"] or ""
                    content = record["content"] or ""
                    source = record["source"] or ""
                    category = record["category"] or ""
                    base_score = float(record["score"])
                    
                    # Apply number boosting
                    final_score = base_score
                    if numbers:
                        for num in numbers:
                            # Boost if number appears in title
                            if num in title:
                                final_score += self.NUMBER_BOOST_FACTOR
                                logger.debug(f"Boosted '{title}' for number {num}")
                    
                    results.append(SparseSearchResult(
                        node_id=node_id,
                        title=title,
                        content=content,
                        source=source,
                        category=category,
                        score=final_score
                    ))
                
                # Re-sort by boosted score and limit
                results.sort(key=lambda x: x.score, reverse=True)
                results = results[:limit]
                
                logger.info(f"Sparse search returned {len(results)} results")
                return results
                
        except Exception as e:
            logger.error(f"Sparse search failed: {e}")
            return []
    
    async def create_fulltext_index(self) -> bool:
        """
        Create full-text index on Knowledge nodes.
        
        Should be called once during setup.
        
        Returns:
            True if index created/exists, False on error
            
        Requirements: 3.1
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                # Create index if not exists
                cypher = """
                CREATE FULLTEXT INDEX knowledge_fulltext IF NOT EXISTS
                FOR (k:Knowledge) ON EACH [k.title, k.content]
                """
                session.run(cypher)
                logger.info("Created/verified full-text index: knowledge_fulltext")
                return True
                
        except Exception as e:
            logger.error(f"Failed to create full-text index: {e}")
            return False
    
    async def check_index_exists(self) -> bool:
        """Check if full-text index exists."""
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                result = session.run(
                    "SHOW INDEXES WHERE name = $name",
                    name=self.INDEX_NAME
                )
                return result.single() is not None
                
        except Exception as e:
            logger.error(f"Failed to check index: {e}")
            return False
    
    def close(self):
        """Close Neo4j connection."""
        if self._driver:
            self._driver.close()
            logger.info("Closed SparseSearchRepository connection")
