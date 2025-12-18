"""
Adaptive Pipeline Router - SOTA 2025 Query Routing.

Routes queries through optimal pipeline paths based on:
- Cache hit status
- Similarity score
- Query complexity
- Context requirements

Pattern References:
- Microsoft Foundry IQ - Intelligent Query Planning
- Anthropic Constitutional AI - Layered Evaluation

Feature: semantic-cache-phase2
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.cache.models import CacheLookupResult

logger = logging.getLogger(__name__)


class PipelinePath(str, Enum):
    """Pipeline execution paths."""
    
    # Cache hit paths
    CACHED_FAST = "cached_fast"          # ~3s: similarity >= 0.99, skip grader
    CACHED_STANDARD = "cached_standard"  # ~10s: similarity >= 0.95, light verify
    
    # Cache miss paths
    STANDARD = "standard"                # ~60s: good retrieval, skip rewrite
    FULL = "full"                        # ~100s: full pipeline with correction


@dataclass
class RouterConfig:
    """Configuration for pipeline routing."""
    
    # Cache thresholds
    cached_fast_threshold: float = 0.99    # Near identical
    cached_standard_threshold: float = 0.95  # Similar
    
    # Grading thresholds (for cache miss)
    fast_path_grading: float = 9.0         # Skip correction if score >= 9.0
    standard_path_grading: float = 7.0     # Standard path if score >= 7.0
    
    # Feature flags
    enable_cached_fast: bool = True
    enable_cached_standard: bool = True
    enable_adaptive_routing: bool = True


@dataclass
class RoutingDecision:
    """Result of routing decision."""
    path: PipelinePath
    reason: str
    skip_grader: bool = False
    skip_verifier: bool = False
    use_thinking_adapter: bool = False
    estimated_time_ms: int = 100000


class AdaptivePipelineRouter:
    """
    SOTA 2025: Route queries through optimal pipeline paths.
    
    Determines the best execution path based on:
    - Cache lookup result (hit/miss, similarity)
    - Query analysis (complexity, type)
    - Context requirements
    
    **Feature: semantic-cache-phase2**
    
    Paths:
        CACHED_FAST (~3s):
            - similarity >= 0.99
            - Use ThinkingAdapter only
            - Skip grader, verifier
            
        CACHED_STANDARD (~10s):
            - similarity >= 0.95
            - Use ThinkingAdapter
            - Light verification
            
        STANDARD (~60s):
            - Cache miss, good retrieval
            - Skip query rewriting
            
        FULL (~100s):
            - Cache miss, needs correction
            - Full pipeline
    
    Usage:
        router = AdaptivePipelineRouter()
        
        decision = router.route(cache_result, context)
        
        if decision.use_thinking_adapter:
            # Use ThinkingAdapter for cache hits
            adapted = await thinking_adapter.adapt(...)
        elif decision.path == PipelinePath.STANDARD:
            # Skip correction step
            ...
    """
    
    def __init__(self, config: Optional[RouterConfig] = None):
        """Initialize adaptive router."""
        self._config = config or RouterConfig()
        
        # Decision logging
        self._total_decisions = 0
        self._path_counts = {path: 0 for path in PipelinePath}
        
        logger.info(
            f"[Router] Initialized with thresholds: "
            f"cached_fast={self._config.cached_fast_threshold}, "
            f"cached_standard={self._config.cached_standard_threshold}"
        )
    
    def route(
        self,
        cache_result: Optional[CacheLookupResult] = None,
        grading_score: Optional[float] = None,
        query_complexity: str = "medium"
    ) -> RoutingDecision:
        """
        Determine optimal pipeline path.
        
        Args:
            cache_result: Result from semantic cache lookup
            grading_score: Average grading score (if available)
            query_complexity: "simple", "medium", or "complex"
            
        Returns:
            RoutingDecision with path and flags
        """
        self._total_decisions += 1
        
        # Check cache hit paths first
        if cache_result and cache_result.hit:
            decision = self._route_cache_hit(cache_result)
            self._path_counts[decision.path] += 1
            return decision
        
        # Cache miss - use grading-based routing
        decision = self._route_cache_miss(grading_score, query_complexity)
        self._path_counts[decision.path] += 1
        return decision
    
    def _route_cache_hit(self, cache_result: CacheLookupResult) -> RoutingDecision:
        """Route when cache hit occurs."""
        similarity = cache_result.similarity
        
        # CACHED_FAST: Near identical query
        if (self._config.enable_cached_fast and 
            similarity >= self._config.cached_fast_threshold):
            
            logger.info(
                f"[Router] CACHED_FAST: similarity={similarity:.3f} "
                f">= {self._config.cached_fast_threshold}"
            )
            
            return RoutingDecision(
                path=PipelinePath.CACHED_FAST,
                reason=f"Near identical query (similarity={similarity:.3f})",
                skip_grader=True,
                skip_verifier=True,
                use_thinking_adapter=True,
                estimated_time_ms=3000
            )
        
        # CACHED_STANDARD: Similar query
        if (self._config.enable_cached_standard and 
            similarity >= self._config.cached_standard_threshold):
            
            logger.info(
                f"[Router] CACHED_STANDARD: similarity={similarity:.3f} "
                f">= {self._config.cached_standard_threshold}"
            )
            
            return RoutingDecision(
                path=PipelinePath.CACHED_STANDARD,
                reason=f"Similar query (similarity={similarity:.3f})",
                skip_grader=True,
                skip_verifier=False,  # Keep light verification
                use_thinking_adapter=True,
                estimated_time_ms=10000
            )
        
        # Shouldn't reach here for hits, but fallback to FULL
        logger.warning(
            f"[Router] Cache hit but low similarity={similarity:.3f}, "
            f"falling back to FULL path"
        )
        return RoutingDecision(
            path=PipelinePath.FULL,
            reason=f"Cache hit but low similarity={similarity:.3f}",
            skip_grader=False,
            skip_verifier=False,
            use_thinking_adapter=False,
            estimated_time_ms=100000
        )
    
    def _route_cache_miss(
        self, 
        grading_score: Optional[float],
        query_complexity: str
    ) -> RoutingDecision:
        """Route when cache miss occurs."""
        
        if not self._config.enable_adaptive_routing:
            # Disabled, always use full path
            return RoutingDecision(
                path=PipelinePath.FULL,
                reason="Adaptive routing disabled",
                estimated_time_ms=100000
            )
        
        # No grading score yet - can't make adaptive decision
        if grading_score is None:
            return RoutingDecision(
                path=PipelinePath.FULL,
                reason="No grading score available yet",
                estimated_time_ms=100000
            )
        
        # High quality retrieval + simple query = fast standard path
        if (grading_score >= self._config.fast_path_grading and 
            query_complexity == "simple"):
            
            logger.info(
                f"[Router] STANDARD: score={grading_score:.1f} >= "
                f"{self._config.fast_path_grading}, complexity=simple"
            )
            
            return RoutingDecision(
                path=PipelinePath.STANDARD,
                reason=f"High quality retrieval (score={grading_score:.1f})",
                skip_grader=False,
                skip_verifier=True,  # Skip verification for simple + high score
                estimated_time_ms=60000
            )
        
        # Good retrieval = standard path
        if grading_score >= self._config.standard_path_grading:
            
            logger.info(
                f"[Router] STANDARD: score={grading_score:.1f} >= "
                f"{self._config.standard_path_grading}"
            )
            
            return RoutingDecision(
                path=PipelinePath.STANDARD,
                reason=f"Good retrieval (score={grading_score:.1f})",
                skip_grader=False,
                skip_verifier=False,
                estimated_time_ms=70000
            )
        
        # Default: full path
        logger.info(
            f"[Router] FULL: score={grading_score:.1f} < "
            f"{self._config.standard_path_grading}"
        )
        
        return RoutingDecision(
            path=PipelinePath.FULL,
            reason=f"Low retrieval score ({grading_score:.1f}), needs correction",
            estimated_time_ms=100000
        )
    
    def get_stats(self) -> dict:
        """Get routing statistics."""
        return {
            "total_decisions": self._total_decisions,
            "path_distribution": {
                path.value: count for path, count in self._path_counts.items()
            },
            "config": {
                "cached_fast_threshold": self._config.cached_fast_threshold,
                "cached_standard_threshold": self._config.cached_standard_threshold,
                "fast_path_grading": self._config.fast_path_grading,
                "standard_path_grading": self._config.standard_path_grading
            }
        }


# Singleton
_router: Optional[AdaptivePipelineRouter] = None


def get_adaptive_router(config: Optional[RouterConfig] = None) -> AdaptivePipelineRouter:
    """Get or create AdaptivePipelineRouter singleton."""
    global _router
    if _router is None:
        _router = AdaptivePipelineRouter(config)
    return _router
