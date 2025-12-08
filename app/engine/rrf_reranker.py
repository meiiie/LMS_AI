"""
Reciprocal Rank Fusion (RRF) Reranker for Hybrid Search.

Merges results from Dense and Sparse search using RRF algorithm.
Includes Title Match Boosting for improved citation accuracy.

Feature: hybrid-search
Requirements: 4.1, 4.2, 4.3, 4.4
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """
    Result from hybrid search with combined scoring and semantic chunking metadata.
    
    Feature: hybrid-search, semantic-chunking
    """
    node_id: str
    title: str
    content: str
    source: str
    category: str
    
    # Scoring from individual searches
    dense_score: Optional[float] = None  # Cosine similarity (0-1)
    sparse_score: Optional[float] = None  # BM25-style score
    
    # Combined RRF score
    rrf_score: float = 0.0
    
    # Metadata
    search_method: str = "hybrid"  # "hybrid", "dense_only", "sparse_only"
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    
    # Semantic chunking metadata
    content_type: str = "text"  # text, table, heading, diagram_reference, formula
    confidence_score: float = 1.0  # 0.0-1.0
    page_number: int = 0
    chunk_index: int = 0
    image_url: str = ""
    document_id: str = ""
    section_hierarchy: dict = field(default_factory=dict)  # article, clause, point, rule
    
    def appears_in_both(self) -> bool:
        """Check if result appeared in both dense and sparse searches."""
        return self.dense_score is not None and self.sparse_score is not None
    
    def has_document_hierarchy(self) -> bool:
        """Check if result has document hierarchy (Điều, Khoản, etc.)."""
        return bool(self.section_hierarchy)


@dataclass
class RankedItem:
    """Internal item for RRF calculation with chunking metadata."""
    node_id: str
    title: str
    content: str
    source: str
    category: str
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    # Semantic chunking metadata
    content_type: str = "text"
    confidence_score: float = 1.0
    page_number: int = 0
    chunk_index: int = 0
    image_url: str = ""
    document_id: str = ""
    section_hierarchy: dict = field(default_factory=dict)


class RRFReranker:
    """
    Reciprocal Rank Fusion reranker for merging search results.
    
    RRF Formula: score(d) = Σ(weight_i / (k + rank_i(d)))
    
    Where:
    - k is a constant (default 60, standard value from literature)
    - rank_i(d) is the rank of document d in result list i
    - weight_i is the weight for result list i
    
    Includes Title Match Boosting for improved citation accuracy.
    
    Feature: hybrid-search
    Requirements: 4.1, 4.2, 4.3, 4.4
    """
    
    # Default RRF constant (from original RRF paper)
    DEFAULT_K = 60
    
    # Title match boost multipliers (Chỉ thị Cố vấn Kiến trúc)
    # - Boost mạnh cho số hiệu (digits) và tên riêng (proper nouns): x3.0
    # - Boost nhẹ cho từ phổ thông: x1.1
    TITLE_MATCH_BOOST_STRONG = 3.0  # For digits, proper nouns (Rule 15, COLREGs, SOLAS)
    TITLE_MATCH_BOOST_WEAK = 1.1    # For common words (tàu, biển, đi)
    TITLE_MATCH_BOOST_MEDIUM = 1.5  # For 1 keyword match
    
    # Sparse score threshold for priority boost
    SPARSE_PRIORITY_THRESHOLD = 15.0
    SPARSE_PRIORITY_BOOST = 1.5
    
    # Proper nouns that should trigger strong boost
    PROPER_NOUNS = {
        'colregs', 'solas', 'marpol', 'stcw', 'imdg', 'imsbc',
        'imo', 'isps', 'ism', 'msc', 'mepc'
    }
    
    def __init__(self, k: int = DEFAULT_K):
        """
        Initialize RRF reranker.
        
        Args:
            k: RRF constant (default 60)
        """
        self.k = k
        logger.info(f"RRFReranker initialized with k={k}")
    
    def _calculate_rrf_score(
        self,
        dense_rank: Optional[int],
        sparse_rank: Optional[int],
        dense_weight: float,
        sparse_weight: float
    ) -> float:
        """
        Calculate RRF score for a document.
        
        Formula: score = Σ(weight_i / (k + rank_i))
        
        Args:
            dense_rank: Rank in dense results (1-indexed), None if not present
            sparse_rank: Rank in sparse results (1-indexed), None if not present
            dense_weight: Weight for dense results
            sparse_weight: Weight for sparse results
            
        Returns:
            Combined RRF score
            
        Requirements: 4.1
        """
        score = 0.0
        
        if dense_rank is not None:
            score += dense_weight / (self.k + dense_rank)
        
        if sparse_rank is not None:
            score += sparse_weight / (self.k + sparse_rank)
        
        return score
    
    def _extract_query_keywords(self, query: str) -> Set[str]:
        """
        Extract important keywords from query for title matching.
        
        Extracts:
        - Rule numbers (e.g., "rule 15", "quy tắc 15")
        - Chapter references (e.g., "chapter ii-1")
        - Topic keywords (e.g., "crossing", "visibility")
        
        Args:
            query: User query string
            
        Returns:
            Set of lowercase keywords
        """
        keywords = set()
        query_lower = query.lower()
        
        # Extract rule/chapter numbers with context
        rule_patterns = [
            r'rule\s*(\d+)',
            r'quy\s*tắc\s*(\d+)',
            r'chapter\s*([\w-]+)',
            r'chương\s*([\w-]+)',
        ]
        
        for pattern in rule_patterns:
            matches = re.findall(pattern, query_lower)
            for match in matches:
                # Add both the number and full reference
                keywords.add(match)
                if 'rule' in pattern or 'quy' in pattern:
                    keywords.add(f"rule {match}")
                    keywords.add(f"rule{match}")
        
        # Extract topic keywords
        topic_keywords = [
            'crossing', 'cắt hướng',
            'visibility', 'tầm nhìn', 'restricted',
            'overtaking', 'vượt',
            'head-on', 'đối đầu', 'meeting',
            'safe speed', 'tốc độ an toàn',
            'look-out', 'cảnh giới',
            'collision', 'va chạm',
        ]
        
        for kw in topic_keywords:
            if kw in query_lower:
                keywords.add(kw)
        
        return keywords
    
    def _calculate_title_match_boost(
        self, 
        title: str, 
        query_keywords: Set[str]
    ) -> float:
        """
        Calculate boost multiplier based on title-query keyword match.
        
        Chỉ thị Cố vấn Kiến trúc:
        - Boost mạnh (x3.0) cho số hiệu (digits) và tên riêng (proper nouns)
        - Boost nhẹ (x1.1) cho từ phổ thông
        
        Args:
            title: Document title
            query_keywords: Keywords extracted from query
            
        Returns:
            Boost multiplier (1.0 = no boost, 3.0 = triple score for exact match)
        """
        if not query_keywords or not title:
            return 1.0
        
        title_lower = title.lower()
        
        # Count matches and categorize them
        strong_matches = 0  # Digits, proper nouns
        weak_matches = 0    # Common words
        
        for kw in query_keywords:
            if kw in title_lower:
                # Check if keyword is a digit (rule number) or proper noun
                if kw.isdigit() or kw in self.PROPER_NOUNS:
                    strong_matches += 1
                else:
                    weak_matches += 1
        
        total_matches = strong_matches + weak_matches
        
        # Apply boost based on match type
        if strong_matches >= 1:
            # Strong boost for digits/proper nouns (Rule 15, COLREGs, SOLAS)
            if total_matches >= 2:
                return self.TITLE_MATCH_BOOST_STRONG  # 3.0x
            else:
                return self.TITLE_MATCH_BOOST_MEDIUM  # 1.5x
        elif weak_matches >= 2:
            # Medium boost for multiple common word matches
            return self.TITLE_MATCH_BOOST_WEAK  # 1.1x
        elif weak_matches == 1:
            # Minimal boost for single common word
            return 1.05
        
        return 1.0
    
    def merge(
        self,
        dense_results: List,  # List of DenseSearchResult
        sparse_results: List,  # List of SparseSearchResult
        dense_weight: float = 0.5,
        sparse_weight: float = 0.5,
        limit: int = 5,
        query: str = ""  # Query for title match boosting
    ) -> List[HybridSearchResult]:
        """
        Merge results using Reciprocal Rank Fusion with Title Match Boosting.
        
        Documents appearing in both lists get boosted because they
        contribute scores from both rankings.
        
        Title Match Boosting: Documents with titles matching query keywords
        get additional score boost for improved citation accuracy.
        
        Args:
            dense_results: Results from dense search (ranked by similarity)
            sparse_results: Results from sparse search (ranked by BM25 score)
            dense_weight: Weight for dense results (0.0-1.0)
            sparse_weight: Weight for sparse results (0.0-1.0)
            limit: Maximum results to return
            query: Original query for title match boosting
            
        Returns:
            Merged and deduplicated results sorted by RRF score
            
        Requirements: 4.1, 4.2, 4.3, 4.4
        """
        # Extract keywords from query for title matching
        query_keywords = self._extract_query_keywords(query) if query else set()
        # Dictionary to accumulate scores by node_id
        items: Dict[str, RankedItem] = {}
        
        # Process dense results (1-indexed ranks)
        for rank, result in enumerate(dense_results, start=1):
            node_id = result.node_id
            
            if node_id not in items:
                # Get content from dense result
                content = getattr(result, 'content', '') or ''
                title = content.split('\n')[0][:100] if content else node_id
                
                # Extract chunking metadata from dense result
                content_type = getattr(result, 'content_type', 'text') or 'text'
                confidence_score = getattr(result, 'confidence_score', 1.0) or 1.0
                page_number = getattr(result, 'page_number', 0) or 0
                chunk_index = getattr(result, 'chunk_index', 0) or 0
                image_url = getattr(result, 'image_url', '') or ''
                document_id = getattr(result, 'document_id', '') or ''
                section_hierarchy = getattr(result, 'section_hierarchy', {}) or {}
                
                items[node_id] = RankedItem(
                    node_id=node_id,
                    title=title,
                    content=content,
                    source="Maritime Knowledge Base",
                    category="Knowledge",
                    content_type=content_type,
                    confidence_score=confidence_score,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    image_url=image_url,
                    document_id=document_id,
                    section_hierarchy=section_hierarchy
                )
            
            items[node_id].dense_score = result.similarity
            items[node_id].dense_rank = rank
        
        # Process sparse results (1-indexed ranks)
        for rank, result in enumerate(sparse_results, start=1):
            node_id = result.node_id
            
            if node_id not in items:
                items[node_id] = RankedItem(
                    node_id=node_id,
                    title=result.title,
                    content=result.content,
                    source=result.source,
                    category=result.category
                )
            else:
                # Update with sparse result info (may have better metadata)
                if result.title:
                    items[node_id].title = result.title
                if result.content:
                    items[node_id].content = result.content
                if result.source:
                    items[node_id].source = result.source
                if result.category:
                    items[node_id].category = result.category
            
            items[node_id].sparse_score = result.score
            items[node_id].sparse_rank = rank
        
        # Calculate RRF scores and create results
        results = []
        for node_id, item in items.items():
            rrf_score = self._calculate_rrf_score(
                item.dense_rank,
                item.sparse_rank,
                dense_weight,
                sparse_weight
            )
            
            # Apply Title Match Boosting
            title_boost = self._calculate_title_match_boost(item.title, query_keywords)
            if title_boost > 1.0:
                logger.debug(f"Title boost {title_boost}x for: {item.title[:50]}")
            
            # Apply Sparse Priority Boost (for high exact-match scores)
            sparse_boost = 1.0
            if item.sparse_score and item.sparse_score > self.SPARSE_PRIORITY_THRESHOLD:
                sparse_boost = self.SPARSE_PRIORITY_BOOST
                logger.debug(f"Sparse priority boost for: {item.title[:50]} (score={item.sparse_score})")
            
            # Apply all boosts
            final_rrf_score = rrf_score * title_boost * sparse_boost
            
            results.append(HybridSearchResult(
                node_id=item.node_id,
                title=item.title,
                content=item.content,
                source=item.source,
                category=item.category,
                dense_score=item.dense_score,
                sparse_score=item.sparse_score,
                rrf_score=final_rrf_score,
                search_method="hybrid",
                dense_rank=item.dense_rank,
                sparse_rank=item.sparse_rank,
                # Semantic chunking metadata
                content_type=item.content_type,
                confidence_score=item.confidence_score,
                page_number=item.page_number,
                chunk_index=item.chunk_index,
                image_url=item.image_url,
                document_id=item.document_id,
                section_hierarchy=item.section_hierarchy
            ))
        
        # Sort by RRF score (descending) and limit
        results.sort(key=lambda x: x.rrf_score, reverse=True)
        results = results[:limit]
        
        # Log merge statistics
        both_count = sum(1 for r in results if r.appears_in_both())
        boosted_count = sum(1 for r in results if self._calculate_title_match_boost(r.title, query_keywords) > 1.0)
        logger.info(
            f"RRF merged {len(dense_results)} dense + {len(sparse_results)} sparse "
            f"-> {len(results)} results ({both_count} in both, {boosted_count} title-boosted)"
        )
        
        return results
    
    def merge_single_source(
        self,
        results: List,
        source: str,  # "dense" or "sparse"
        limit: int = 5
    ) -> List[HybridSearchResult]:
        """
        Convert single-source results to HybridSearchResult format.
        
        Used for fallback when one search method fails.
        
        Args:
            results: Results from single search
            source: "dense" or "sparse"
            limit: Maximum results
            
        Returns:
            List of HybridSearchResult with appropriate method flag
        """
        hybrid_results = []
        
        for rank, result in enumerate(results[:limit], start=1):
            if source == "dense":
                # Extract title from content (first line or node_id)
                content = getattr(result, 'content', '') or ''
                title = content.split('\n')[0][:100] if content else result.node_id
                
                # Extract chunking metadata
                content_type = getattr(result, 'content_type', 'text') or 'text'
                confidence_score = getattr(result, 'confidence_score', 1.0) or 1.0
                page_number = getattr(result, 'page_number', 0) or 0
                chunk_index = getattr(result, 'chunk_index', 0) or 0
                image_url = getattr(result, 'image_url', '') or ''
                document_id = getattr(result, 'document_id', '') or ''
                section_hierarchy = getattr(result, 'section_hierarchy', {}) or {}
                
                hybrid_results.append(HybridSearchResult(
                    node_id=result.node_id,
                    title=title,
                    content=content,
                    source="Maritime Knowledge Base",
                    category="Knowledge",
                    dense_score=result.similarity,
                    sparse_score=None,
                    rrf_score=result.similarity,  # Use similarity as score
                    search_method="dense_only",
                    dense_rank=rank,
                    sparse_rank=None,
                    # Semantic chunking metadata
                    content_type=content_type,
                    confidence_score=confidence_score,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    image_url=image_url,
                    document_id=document_id,
                    section_hierarchy=section_hierarchy
                ))
            else:  # sparse
                hybrid_results.append(HybridSearchResult(
                    node_id=result.node_id,
                    title=result.title,
                    content=result.content,
                    source=result.source,
                    category=result.category,
                    dense_score=None,
                    sparse_score=result.score,
                    rrf_score=result.score / 10.0,  # Normalize to similar range
                    search_method="sparse_only",
                    dense_rank=None,
                    sparse_rank=rank
                ))
        
        return hybrid_results
