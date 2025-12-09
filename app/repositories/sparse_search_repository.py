"""
Sparse Search Repository using PostgreSQL full-text search.

Provides keyword-based search with tsvector/tsquery and ts_rank scoring.
Migrated from Neo4j to PostgreSQL for architecture simplification.

Feature: sparse-search-migration
Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SparseSearchResult:
    """Result from sparse (keyword) search - unchanged interface."""
    node_id: str
    title: str
    content: str
    source: str
    category: str
    score: float
    # CHỈ THỊ 26: Evidence images support
    image_url: str = ""
    page_number: int = 0
    document_id: str = ""
    # Feature: source-highlight-citation
    bounding_boxes: list = None  # Normalized coordinates for text highlighting
    
    def __post_init__(self):
        # Ensure score is non-negative
        self.score = max(0.0, self.score)
        if self.bounding_boxes is None:
            self.bounding_boxes = []


class SparseSearchRepository:
    """
    PostgreSQL-based sparse search using tsvector/tsquery.
    
    Replaces Neo4j full-text search with PostgreSQL native full-text search.
    Uses 'simple' configuration for language-agnostic tokenization (Vietnamese support).
    
    Feature: sparse-search-migration
    Requirements: 4.1, 4.2, 4.3, 4.4
    """
    
    # Number boost factor for rule numbers
    NUMBER_BOOST_FACTOR = 2.0
    
    def __init__(self):
        """Initialize repository."""
        self._available = False
        self._init_connection()
    
    def _init_connection(self):
        """Initialize PostgreSQL connection check."""
        try:
            if settings.database_url:
                self._available = True
                logger.info("PostgreSQL sparse search repository initialized")
            else:
                logger.warning("DATABASE_URL not configured, sparse search unavailable")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL sparse search: {e}")
            self._available = False
    
    def _get_asyncpg_url(self) -> str:
        """Get database URL in asyncpg format (without +asyncpg suffix)."""
        url = settings.database_url or ''
        # Convert SQLAlchemy format to asyncpg format
        if url.startswith('postgresql+asyncpg://'):
            url = url.replace('postgresql+asyncpg://', 'postgresql://')
        return url
    
    def is_available(self) -> bool:
        """Check if PostgreSQL sparse search is available."""
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
    
    def _get_synonyms(self, word: str) -> List[str]:
        """
        Get synonyms for maritime terms.
        
        Args:
            word: Input word
            
        Returns:
            List of synonyms
        """
        SYNONYMS = {
            "quy": ["rule", "regulation"],
            "tắc": ["rule", "regulation"],
            "rule": ["quy", "tắc", "regulation", "điều"],
            "điều": ["rule", "quy", "tắc", "regulation"],
            "cảnh": ["look", "watch"],
            "giới": ["out", "watch"],
            "look": ["cảnh", "watch"],
            "out": ["giới", "watch"],
            "lookout": ["cảnh", "giới", "watch"],
            "tàu": ["vessel", "ship"],
            "vessel": ["tàu", "ship"],
            "ship": ["tàu", "vessel"],
            "cắt": ["crossing", "cross"],
            "hướng": ["crossing", "direction"],
            "crossing": ["cắt", "hướng"],
            "tầm": ["visibility", "range"],
            "nhìn": ["visibility", "sight"],
            "visibility": ["tầm", "nhìn"],
            "đèn": ["light", "lighting"],
            "light": ["đèn", "lighting"],
            "âm": ["sound", "signal"],
            "hiệu": ["signal", "sound"],
            "sound": ["âm", "hiệu"],
            "signal": ["âm", "hiệu"],
            "neo": ["anchor", "anchoring"],
            "anchor": ["neo", "anchoring"],
        }
        return SYNONYMS.get(word, [])
    
    def _build_tsquery(self, query: str) -> str:
        """
        Build PostgreSQL tsquery from natural language query.
        
        Handles:
        - Vietnamese and English text
        - Stop word removal
        - OR between terms for broader matching
        - Synonym expansion for maritime terms
        
        Args:
            query: Original search query
            
        Returns:
            PostgreSQL tsquery string
            
        Requirements: 3.2
        """
        # Stop words (Vietnamese and English)
        stop_words = {
            "là", "gì", "về", "của", "và", "có", "được", "trong", "với", 
            "cho", "từ", "này", "đó", "như", "thế", "nào", "tôi", "me",
            "the", "what", "is", "a", "an", "and", "or", "but", "in", 
            "on", "at", "to", "for", "of", "with", "by", "how", "why",
            "when", "where", "which", "who", "about"
        }
        
        # Extract meaningful words
        words = [
            w.strip() for w in query.lower().split() 
            if w.strip() and w.strip() not in stop_words and len(w.strip()) > 1
        ]
        
        if not words:
            # Fallback to original query if no meaningful words
            return query.replace("'", "''")
        
        # Add synonyms for maritime terms
        enhanced_words = []
        for word in words:
            enhanced_words.append(word)
            synonyms = self._get_synonyms(word)
            enhanced_words.extend(synonyms)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_words = []
        for w in enhanced_words:
            if w not in seen:
                seen.add(w)
                unique_words.append(w)
        
        # Build OR query: word1 | word2 | word3
        # Escape single quotes for PostgreSQL
        escaped_words = [w.replace("'", "''") for w in unique_words]
        return " | ".join(escaped_words)
    
    def _apply_number_boost(
        self, 
        results: List[SparseSearchResult],
        query: str
    ) -> List[SparseSearchResult]:
        """
        Boost results containing rule numbers from query.
        
        E.g., "Rule 15" query boosts results with "15" in content.
        
        Args:
            results: Original search results
            query: Original search query
            
        Returns:
            Results with number boosting applied
            
        Requirements: 3.3
        """
        numbers = self._extract_numbers(query)
        
        if not numbers:
            return results
        
        # Apply boosting
        for result in results:
            for num in numbers:
                if num in result.content or num in result.title:
                    result.score *= self.NUMBER_BOOST_FACTOR
                    logger.debug(f"Applied number boost for '{num}' to result {result.node_id}")
        
        # Re-sort by score
        return sorted(results, key=lambda x: x.score, reverse=True)

    
    async def search(
        self,
        query: str,
        limit: int = 10
    ) -> List[SparseSearchResult]:
        """
        Search using PostgreSQL full-text search.
        
        Uses ts_rank for scoring with number boosting.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of sparse search results sorted by score (descending)
            
        Requirements: 3.1, 3.2, 3.3, 3.4
        """
        if not self.is_available():
            logger.warning("PostgreSQL sparse search not available")
            return []
        
        try:
            # Build tsquery from natural language query
            tsquery = self._build_tsquery(query)
            
            logger.info(f"Sparse search tsquery: {tsquery}")
            
            # Connect to database
            conn = await asyncpg.connect(self._get_asyncpg_url())
            
            try:
                # Execute PostgreSQL full-text search
                # CHỈ THỊ 26: Include image_url for evidence images
                # Feature: source-highlight-citation - Include bounding_boxes
                sql = """
                    SELECT 
                        id::text as node_id,
                        COALESCE(metadata->>'title', '') as title,
                        content,
                        COALESCE(metadata->>'source', '') as source,
                        COALESCE(metadata->>'category', '') as category,
                        ts_rank(search_vector, to_tsquery('simple', $1)) as score,
                        COALESCE(image_url, '') as image_url,
                        COALESCE(page_number, 0) as page_number,
                        COALESCE(document_id, '') as document_id,
                        bounding_boxes
                    FROM knowledge_embeddings
                    WHERE search_vector @@ to_tsquery('simple', $1)
                    ORDER BY score DESC
                    LIMIT $2
                """
                
                rows = await conn.fetch(sql, tsquery, limit * 2)  # Get more for boosting
                
                results = []
                for row in rows:
                    # Parse bounding_boxes from JSONB
                    bounding_boxes = row.get("bounding_boxes")
                    if isinstance(bounding_boxes, str):
                        import json
                        try:
                            bounding_boxes = json.loads(bounding_boxes)
                        except:
                            bounding_boxes = []
                    elif bounding_boxes is None:
                        bounding_boxes = []
                    
                    results.append(SparseSearchResult(
                        node_id=row["node_id"],
                        title=row["title"],
                        content=row["content"],
                        source=row["source"],
                        category=row["category"],
                        score=float(row["score"]),
                        image_url=row["image_url"],
                        page_number=row["page_number"],
                        document_id=row["document_id"],
                        bounding_boxes=bounding_boxes
                    ))
                
                # Apply number boosting
                results = self._apply_number_boost(results, query)
                
                # Limit results
                results = results[:limit]
                
                logger.info(f"PostgreSQL sparse search returned {len(results)} results for query: {query}")
                return results
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"PostgreSQL sparse search failed: {e}")
            return []
    
    async def close(self):
        """Close database connections (if any)."""
        # PostgreSQL connections are handled per-request
        logger.info("PostgreSQL sparse search repository closed")
