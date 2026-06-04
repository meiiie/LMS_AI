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
from app.repositories.knowledge_search_org_scope import (
    log_knowledge_search_scope_blocked,
    resolve_knowledge_search_org_scope,
)

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
    domain_id: str = ""  # Sprint 136: Cross-domain search
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
        self._pool = None
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
            logger.error("Failed to initialize PostgreSQL sparse search: %s", e)
            self._available = False
    
    def _get_asyncpg_url(self) -> str:
        """Get database URL in asyncpg format (without +asyncpg suffix)."""
        return settings.asyncpg_url

    async def _get_pool(self):
        """Get or create connection pool with configurable size."""
        if self._pool is None:
            try:
                db_url = self._get_asyncpg_url()
                self._pool = await asyncpg.create_pool(
                    db_url,
                    min_size=settings.async_pool_min_size,
                    max_size=settings.async_pool_max_size
                )
                logger.info("Created asyncpg connection pool for sparse search (min=%d, max=%d)", settings.async_pool_min_size, settings.async_pool_max_size)
            except Exception as e:
                logger.error("Failed to create connection pool: %s", e)
                self._available = False
                raise
        return self._pool

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
        - Special character sanitization for tsquery
        
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
        
        # First, remove special characters that break tsquery syntax
        # Keep only alphanumeric, Vietnamese chars, and spaces
        sanitized_query = re.sub(r"[().,?!;:\"'\[\]{}|&<>@#$%^*+=~/\\]", " ", query)
        
        # Extract meaningful words using regex (handles punctuation better)
        words = [
            w.strip().lower() for w in sanitized_query.split() 
            if w.strip() and w.strip().lower() not in stop_words and len(w.strip()) > 1
        ]
        
        if not words:
            # Fallback: return generic search term
            return ""
        
        # Add synonyms for maritime terms
        enhanced_words = []
        for word in words:
            # Skip words that are just numbers (they'll be handled separately)
            enhanced_words.append(word)
            synonyms = self._get_synonyms(word)
            enhanced_words.extend(synonyms)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_words = []
        for w in enhanced_words:
            # Final sanitization: only keep alphanumeric and Vietnamese chars
            sanitized_word = re.sub(r"[^a-zA-Z0-9àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]", "", w)
            if sanitized_word and sanitized_word not in seen and len(sanitized_word) > 1:
                seen.add(sanitized_word)
                unique_words.append(sanitized_word)
        
        if not unique_words:
            return ""
        
        # Build OR query: word1 | word2 | word3
        return " | ".join(unique_words)
    
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
                    logger.debug("Applied number boost for '%s' to result %s", num, result.node_id)
        
        # Re-sort by score
        return sorted(results, key=lambda x: x.score, reverse=True)

    
    async def search(
        self,
        query: str,
        limit: int = 10,
        domain_id: Optional[str] = None,
        org_id: Optional[str] = None
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

        scope = resolve_knowledge_search_org_scope(org_id)
        if not scope.write_allowed or not scope.org_id:
            log_knowledge_search_scope_blocked(
                logger,
                "sparse_search",
                scope,
            )
            return []
        
        try:
            # Build tsquery from natural language query
            tsquery = self._build_tsquery(query)
            
            logger.info("Sparse search tsquery: %s", tsquery)

            # Get connection from pool
            pool = await self._get_pool()

            async with pool.acquire() as conn:
                # Execute PostgreSQL full-text search
                # CHỈ THỊ 26: Include image_url for evidence images
                # Feature: source-highlight-citation - Include bounding_boxes
                # Build query with optional domain filter
                params = [tsquery]
                param_idx = 2

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
                        COALESCE(domain_id, '') as domain_id,
                        bounding_boxes
                    FROM knowledge_embeddings
                    WHERE search_vector @@ to_tsquery('simple', $1)
                """

                # Sprint 136: Cross-domain search — soft boost instead of hard filter
                from app.core.config import settings as _settings
                if domain_id and not _settings.cross_domain_search:
                    sql += f" AND domain_id = ${param_idx}"
                    params.append(domain_id)
                    param_idx += 1

                # Sprint 160: Org-scoped filtering (NULL-aware for shared KB)
                from app.core.org_filter import org_where_positional
                sql += org_where_positional(scope.org_id, params, allow_null=True)
                param_idx = len(params) + 1

                sql += f"""
                    ORDER BY score DESC
                    LIMIT ${param_idx}
                """
                params.append(limit * 2)

                rows = await conn.fetch(sql, *params)  # Get more for boosting
                
                results = []
                for row in rows:
                    # Parse bounding_boxes from JSONB
                    bounding_boxes = row.get("bounding_boxes")
                    if isinstance(bounding_boxes, str):
                        import json
                        try:
                            bounding_boxes = json.loads(bounding_boxes)
                        except Exception as e:
                            logger.warning("Failed to parse bounding_boxes JSON: %s", e)
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
                        domain_id=row["domain_id"],
                        bounding_boxes=bounding_boxes
                    ))
                
                # Apply number boosting
                results = self._apply_number_boost(results, query)
                
                # Limit results
                results = results[:limit]

                logger.info("PostgreSQL sparse search returned %d results for query: %s", len(results), query)
                return results

        except Exception as e:
            logger.error("PostgreSQL sparse search failed: %s", e)
            return []
    
    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Closed SparseSearchRepository connection pool")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================
_sparse_search_instance: Optional["SparseSearchRepository"] = None


def get_sparse_search_repository() -> "SparseSearchRepository":
    """
    Get singleton SparseSearchRepository instance.

    Ensures only ONE asyncpg connection pool is created,
    matching DenseSearchRepository singleton pattern.
    """
    global _sparse_search_instance

    if _sparse_search_instance is None:
        _sparse_search_instance = SparseSearchRepository()
        logger.info("Created singleton SparseSearchRepository instance")

    return _sparse_search_instance
