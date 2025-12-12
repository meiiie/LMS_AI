"""
User Graph Repository - Neo4j
Knowledge Graph Implementation Phase 2

Manages User ↔ Module ↔ Topic relationships for:
- Learning paths (STUDIED, COMPLETED)
- Knowledge gaps (WEAK_AT)
- Prerequisites (PREREQUISITE)

Pattern: MemoriLabs Mem0 Graph Storage Layer
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.config import settings

logger = logging.getLogger(__name__)


class UserGraphRepository:
    """
    User Graph repository using Neo4j.
    
    Manages learning relationships separate from RAG (which uses PostgreSQL).
    This is the "Relationship Layer" in the hybrid architecture.
    
    Nodes:
    - User: Learning user from LMS
    - Module: Course modules (synced from documents)
    - Topic: Knowledge topics (extracted from documents)
    
    Relationships:
    - STUDIED: User studied a module
    - COMPLETED: User completed a module
    - WEAK_AT: User is weak at a topic
    - PREREQUISITE: Module requires another module
    """
    
    def __init__(self):
        """Initialize Neo4j connection for User Graph."""
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
            logger.info(f"[USER GRAPH] Neo4j connected: {settings.neo4j_uri}")
        except Exception as e:
            logger.warning(f"[USER GRAPH] Neo4j unavailable: {e}")
            self._available = False
    
    def is_available(self) -> bool:
        """Check if Neo4j is available."""
        return self._available
    
    # =========================================================================
    # USER NODE OPERATIONS
    # =========================================================================
    
    def ensure_user_node(self, user_id: str, display_name: Optional[str] = None) -> bool:
        """
        Create or update User node.
        
        Called on first interaction to ensure user exists in graph.
        
        Args:
            user_id: User ID from LMS
            display_name: Optional display name
            
        Returns:
            True if successful
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MERGE (u:User {id: $user_id})
                    SET u.display_name = COALESCE($display_name, u.display_name),
                        u.last_seen = datetime()
                """, user_id=user_id, display_name=display_name)
            
            logger.debug(f"[USER GRAPH] User node ensured: {user_id}")
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to create user node: {e}")
            return False
    
    def get_user_node(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user node data."""
        if not self._available:
            return None
        
        try:
            with self._driver.session() as session:
                result = session.run("""
                    MATCH (u:User {id: $user_id})
                    RETURN u.id as id, u.display_name as display_name, 
                           u.last_seen as last_seen
                """, user_id=user_id)
                record = result.single()
                if record:
                    return dict(record)
            return None
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to get user: {e}")
            return None
    
    # =========================================================================
    # MODULE NODE OPERATIONS
    # =========================================================================
    
    def ensure_module_node(
        self, 
        module_id: str, 
        title: str,
        document_id: Optional[str] = None
    ) -> bool:
        """
        Create or update Module node.
        
        Args:
            module_id: Module identifier
            title: Module title
            document_id: Associated document ID in Neon
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MERGE (m:Module {id: $module_id})
                    SET m.title = $title,
                        m.document_id = COALESCE($document_id, m.document_id),
                        m.updated_at = datetime()
                """, module_id=module_id, title=title, document_id=document_id)
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to create module: {e}")
            return False
    
    # =========================================================================
    # TOPIC NODE OPERATIONS
    # =========================================================================
    
    def ensure_topic_node(self, topic_id: str, name: str) -> bool:
        """Create or update Topic node."""
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MERGE (t:Topic {id: $topic_id})
                    SET t.name = $name,
                        t.updated_at = datetime()
                """, topic_id=topic_id, name=name)
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to create topic: {e}")
            return False
    
    # =========================================================================
    # RELATIONSHIP OPERATIONS
    # =========================================================================
    
    def mark_studied(
        self, 
        user_id: str, 
        module_id: str,
        progress: float = 0.0
    ) -> bool:
        """
        Mark that user studied a module.
        
        Creates STUDIED relationship with progress tracking.
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MATCH (u:User {id: $user_id})
                    MATCH (m:Module {id: $module_id})
                    MERGE (u)-[r:STUDIED]->(m)
                    SET r.progress = $progress,
                        r.last_studied = datetime()
                """, user_id=user_id, module_id=module_id, progress=progress)
            
            logger.info(f"[USER GRAPH] {user_id} STUDIED {module_id} ({progress*100:.0f}%)")
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to mark studied: {e}")
            return False
    
    def mark_completed(self, user_id: str, module_id: str) -> bool:
        """Mark that user completed a module."""
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MATCH (u:User {id: $user_id})
                    MATCH (m:Module {id: $module_id})
                    MERGE (u)-[r:COMPLETED]->(m)
                    SET r.completed_at = datetime()
                """, user_id=user_id, module_id=module_id)
            
            logger.info(f"[USER GRAPH] {user_id} COMPLETED {module_id}")
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to mark completed: {e}")
            return False
    
    def mark_weak_at(
        self, 
        user_id: str, 
        topic_id: str,
        confidence: float = 0.0
    ) -> bool:
        """
        Mark that user is weak at a topic.
        
        Used for knowledge gap detection.
        """
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MATCH (u:User {id: $user_id})
                    MATCH (t:Topic {id: $topic_id})
                    MERGE (u)-[r:WEAK_AT]->(t)
                    SET r.confidence = $confidence,
                        r.detected_at = datetime()
                """, user_id=user_id, topic_id=topic_id, confidence=confidence)
            
            logger.info(f"[USER GRAPH] {user_id} WEAK_AT {topic_id}")
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to mark weak_at: {e}")
            return False
    
    def add_prerequisite(self, module_id: str, requires_module_id: str) -> bool:
        """Add prerequisite relationship between modules."""
        if not self._available:
            return False
        
        try:
            with self._driver.session() as session:
                session.run("""
                    MATCH (m:Module {id: $module_id})
                    MATCH (req:Module {id: $requires_module_id})
                    MERGE (m)-[:PREREQUISITE]->(req)
                """, module_id=module_id, requires_module_id=requires_module_id)
            return True
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to add prerequisite: {e}")
            return False
    
    # =========================================================================
    # QUERY OPERATIONS
    # =========================================================================
    
    def get_learning_path(
        self, 
        user_id: str, 
        depth: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get user's learning path (modules studied).
        
        Returns chronologically ordered list of studied modules.
        """
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                result = session.run("""
                    MATCH (u:User {id: $user_id})-[r:STUDIED|COMPLETED]->(m:Module)
                    RETURN m.id as module_id, m.title as title,
                           r.progress as progress, type(r) as status,
                           r.last_studied as last_studied
                    ORDER BY r.last_studied DESC
                    LIMIT $depth
                """, user_id=user_id, depth=depth)
                
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to get learning path: {e}")
            return []
    
    def get_knowledge_gaps(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get topics user is weak at.
        
        Returns list of topics with weakness confidence.
        """
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                result = session.run("""
                    MATCH (u:User {id: $user_id})-[r:WEAK_AT]->(t:Topic)
                    RETURN t.id as topic_id, t.name as topic_name,
                           r.confidence as confidence
                    ORDER BY r.confidence DESC
                """, user_id=user_id)
                
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to get knowledge gaps: {e}")
            return []
    
    def get_prerequisites(self, module_id: str) -> List[Dict[str, Any]]:
        """Get prerequisite modules for a module."""
        if not self._available:
            return []
        
        try:
            with self._driver.session() as session:
                result = session.run("""
                    MATCH (m:Module {id: $module_id})-[:PREREQUISITE*1..3]->(req:Module)
                    RETURN DISTINCT req.id as module_id, req.title as title
                """, module_id=module_id)
                
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[USER GRAPH] Failed to get prerequisites: {e}")
            return []
    
    def close(self):
        """Close Neo4j driver."""
        if self._driver:
            self._driver.close()
            logger.info("[USER GRAPH] Neo4j connection closed")


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_user_graph_repo: Optional[UserGraphRepository] = None


def get_user_graph_repository() -> UserGraphRepository:
    """Get or create singleton UserGraphRepository instance."""
    global _user_graph_repo
    
    if _user_graph_repo is None:
        _user_graph_repo = UserGraphRepository()
    
    return _user_graph_repo
