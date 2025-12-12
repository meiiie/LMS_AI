"""
Learning Graph Service
Knowledge Graph Implementation Phase 3

Manages learning relationships between Users, Modules, and Topics.
Orchestrates between Neon (facts) and Neo4j (relationships).

Pattern: MemoriLabs Hybrid Retrieval
"""

import logging
from typing import List, Optional, Dict, Any

from app.repositories.user_graph_repository import (
    UserGraphRepository,
    get_user_graph_repository
)
from app.repositories.semantic_memory_repository import (
    SemanticMemoryRepository,
    get_semantic_memory_repository
)
from app.models.semantic_memory import Predicate, FactType

logger = logging.getLogger(__name__)


class LearningGraphService:
    """
    Service for managing learning graph relationships.
    
    Bridges Neon (semantic facts) and Neo4j (relationships).
    
    Use Cases:
    - Track what user has studied (STUDIED)
    - Detect knowledge gaps (WEAK_AT)
    - Map module prerequisites (PREREQUISITE)
    """
    
    def __init__(
        self,
        user_graph: Optional[UserGraphRepository] = None,
        semantic_repo: Optional[SemanticMemoryRepository] = None
    ):
        """Initialize with repositories."""
        self._user_graph = user_graph or get_user_graph_repository()
        self._semantic_repo = semantic_repo or get_semantic_memory_repository()
    
    def is_available(self) -> bool:
        """Check if both Neon and Neo4j are available."""
        return self._user_graph.is_available()
    
    # =========================================================================
    # STUDIED RELATIONSHIP
    # =========================================================================
    
    async def record_study_session(
        self,
        user_id: str,
        module_id: str,
        module_title: str,
        progress: float = 0.0
    ) -> bool:
        """
        Record that user studied a module.
        
        Called when user:
        - Asks questions about a module
        - Completes exercises
        - Views module content
        
        Args:
            user_id: User ID from LMS
            module_id: Module identifier
            module_title: Module title
            progress: Progress percentage (0.0 - 1.0)
        """
        if not self._user_graph.is_available():
            logger.warning("[LEARNING GRAPH] Neo4j unavailable, skipping study record")
            return False
        
        try:
            # Ensure module node exists
            self._user_graph.ensure_module_node(
                module_id=module_id,
                title=module_title
            )
            
            # Create/update STUDIED relationship
            success = self._user_graph.mark_studied(
                user_id=user_id,
                module_id=module_id,
                progress=progress
            )
            
            if success:
                logger.info(f"[LEARNING GRAPH] Recorded: {user_id} studied {module_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"[LEARNING GRAPH] Failed to record study: {e}")
            return False
    
    async def mark_module_completed(
        self,
        user_id: str,
        module_id: str
    ) -> bool:
        """Mark module as completed by user."""
        if not self._user_graph.is_available():
            return False
        
        return self._user_graph.mark_completed(user_id, module_id)
    
    # =========================================================================
    # WEAK_AT RELATIONSHIP (Knowledge Gaps)
    # =========================================================================
    
    async def detect_and_record_weakness(
        self,
        user_id: str,
        topic_id: str,
        topic_name: str,
        confidence: float = 0.5
    ) -> bool:
        """
        Record a detected knowledge gap.
        
        Called when:
        - User answers incorrectly multiple times
        - User explicitly says they don't understand
        - AI detects confusion in conversation
        
        Args:
            user_id: User ID
            topic_id: Topic identifier (e.g., "colregs_rule_15")
            topic_name: Human-readable topic name
            confidence: How confident we are about the weakness (0-1)
        """
        if not self._user_graph.is_available():
            logger.warning("[LEARNING GRAPH] Neo4j unavailable, skipping weakness record")
            return False
        
        try:
            # Ensure topic node exists
            self._user_graph.ensure_topic_node(
                topic_id=topic_id,
                name=topic_name
            )
            
            # Create/update WEAK_AT relationship
            success = self._user_graph.mark_weak_at(
                user_id=user_id,
                topic_id=topic_id,
                confidence=confidence
            )
            
            if success:
                logger.info(
                    f"[LEARNING GRAPH] Knowledge gap: {user_id} weak at {topic_name} "
                    f"(confidence: {confidence:.0%})"
                )
            
            return success
            
        except Exception as e:
            logger.error(f"[LEARNING GRAPH] Failed to record weakness: {e}")
            return False
    
    async def sync_weakness_from_facts(self, user_id: str) -> int:
        """
        Sync WEAK_AT relationships from Neon semantic facts.
        
        Reads user_facts with predicate=WEAK_AT and creates Neo4j relationships.
        
        Returns:
            Number of weaknesses synced
        """
        if not self._user_graph.is_available():
            return 0
        
        try:
            # Get weakness predicates from Neon
            weaknesses = self._semantic_repo.find_by_predicate(
                user_id=user_id,
                predicate=Predicate.WEAK_AT
            )
            
            synced = 0
            for weakness in weaknesses:
                topic_value = weakness.get("object", weakness.get("content", ""))
                if topic_value:
                    # Create topic_id from the value
                    topic_id = topic_value.lower().replace(" ", "_")[:50]
                    
                    success = await self.detect_and_record_weakness(
                        user_id=user_id,
                        topic_id=topic_id,
                        topic_name=topic_value,
                        confidence=weakness.get("confidence", 0.5)
                    )
                    if success:
                        synced += 1
            
            logger.info(f"[LEARNING GRAPH] Synced {synced} weaknesses for {user_id}")
            return synced
            
        except Exception as e:
            logger.error(f"[LEARNING GRAPH] Failed to sync weaknesses: {e}")
            return 0
    
    # =========================================================================
    # PREREQUISITE RELATIONSHIP
    # =========================================================================
    
    async def add_module_prerequisite(
        self,
        module_id: str,
        requires_module_id: str
    ) -> bool:
        """
        Add prerequisite relationship between modules.
        
        Example: "Navigation Rules" requires "Basic Seamanship"
        """
        if not self._user_graph.is_available():
            return False
        
        return self._user_graph.add_prerequisite(module_id, requires_module_id)
    
    # =========================================================================
    # QUERY OPERATIONS (Hybrid Retrieval)
    # =========================================================================
    
    async def get_user_learning_context(self, user_id: str) -> Dict[str, Any]:
        """
        Get full learning context for user.
        
        Combines:
        - Learning path from Neo4j
        - Knowledge gaps from Neo4j
        - User facts from Neon
        
        Returns:
            {
                "learning_path": [...],
                "knowledge_gaps": [...],
                "recommendations": [...]
            }
        """
        context = {
            "learning_path": [],
            "knowledge_gaps": [],
            "recommendations": []
        }
        
        if not self._user_graph.is_available():
            return context
        
        try:
            # Get from Neo4j
            context["learning_path"] = self._user_graph.get_learning_path(user_id)
            context["knowledge_gaps"] = self._user_graph.get_knowledge_gaps(user_id)
            
            # Generate recommendations based on gaps
            for gap in context["knowledge_gaps"]:
                context["recommendations"].append(
                    f"Cần ôn tập: {gap.get('topic_name', 'Unknown')}"
                )
            
            logger.debug(
                f"[LEARNING GRAPH] Context for {user_id}: "
                f"{len(context['learning_path'])} modules, "
                f"{len(context['knowledge_gaps'])} gaps"
            )
            
        except Exception as e:
            logger.error(f"[LEARNING GRAPH] Failed to get context: {e}")
        
        return context


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_learning_graph_service: Optional[LearningGraphService] = None


def get_learning_graph_service() -> LearningGraphService:
    """Get or create singleton LearningGraphService instance."""
    global _learning_graph_service
    
    if _learning_graph_service is None:
        _learning_graph_service = LearningGraphService()
    
    return _learning_graph_service
