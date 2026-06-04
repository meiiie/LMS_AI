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

from app.core.config import settings
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)
USER_GRAPH_SCOPE_BLOCKED_WARNING = "user_graph_blocked_missing_org_context"


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
        """Initialize Neo4j driver.

        Sprint 165: Guarded by enable_neo4j flag.
        """
        if not getattr(settings, "enable_neo4j", False):
            logger.info("[USER GRAPH] Neo4j disabled (enable_neo4j=False)")
            self._available = False
            return

        try:
            from neo4j import GraphDatabase

            username = settings.neo4j_username_resolved
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(username, settings.neo4j_password)
            )
            self._driver.verify_connectivity()
            self._available = True
            logger.info("[USER GRAPH] Neo4j connected: %s", settings.neo4j_uri)
        except Exception as e:
            logger.warning("[USER GRAPH] Neo4j unavailable: %s", e)
            self._available = False

    def is_available(self) -> bool:
        """Check if Neo4j is available."""
        return self._available

    def _resolve_scope(self, *, write: bool) -> MemoryWriteScope:
        return resolve_memory_write_scope() if write else resolve_memory_read_scope()

    def _uses_org_scope(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.org_id and scope.state != "single_tenant_default")

    def _org_params(self, scope: MemoryWriteScope) -> Dict[str, Any]:
        if not self._uses_org_scope(scope):
            return {}
        return {"organization_id": scope.org_id}

    def _scope_for_operation(
        self,
        operation: str,
        *,
        write: bool,
        user_id: Optional[str] = None,
        module_id: Optional[str] = None,
        topic_id: Optional[str] = None,
    ) -> Optional[MemoryWriteScope]:
        scope = self._resolve_scope(write=write)
        if scope.write_allowed:
            return scope

        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(USER_GRAPH_SCOPE_BLOCKED_WARNING)
        logger.warning(
            "[USER GRAPH] %s blocked user_hash=%s module_hash=%s topic_hash=%s "
            "org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(user_id),
            hash_memory_identifier(module_id),
            hash_memory_identifier(topic_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )
        return None

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

        scope = self._scope_for_operation(
            "ensure_user_node",
            write=True,
            user_id=user_id,
        )
        if scope is None:
            return False

        params = {
            "user_id": user_id,
            "display_name": display_name,
            **self._org_params(scope),
        }
        if self._uses_org_scope(scope):
            query = """
                    MERGE (u:User {id: $user_id, organization_id: $organization_id})
                    SET u.display_name = COALESCE($display_name, u.display_name),
                        u.last_seen = datetime()
                """
        else:
            query = """
                    MERGE (u:User {id: $user_id})
                    SET u.display_name = COALESCE($display_name, u.display_name),
                        u.last_seen = datetime()
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)

            logger.debug(
                "[USER GRAPH] User node ensured user_hash=%s org_hash=%s",
                hash_memory_identifier(user_id),
                hash_memory_identifier(scope.org_id),
            )
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to create user node: %s", e)
            return False

    def get_user_node(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user node data."""
        if not self._available:
            return None

        scope = self._scope_for_operation(
            "get_user_node",
            write=False,
            user_id=user_id,
        )
        if scope is None:
            return None

        params = {"user_id": user_id, **self._org_params(scope)}
        if self._uses_org_scope(scope):
            query = """
                    MATCH (u:User {id: $user_id, organization_id: $organization_id})
                    RETURN u.id as id, u.display_name as display_name,
                           u.last_seen as last_seen,
                           u.organization_id as organization_id
                """
        else:
            query = """
                    MATCH (u:User {id: $user_id})
                    RETURN u.id as id, u.display_name as display_name,
                           u.last_seen as last_seen
                """

        try:
            with self._driver.session() as session:
                result = session.run(query, **params)
                record = result.single()
                if record:
                    return dict(record)
            return None
        except Exception as e:
            logger.error("[USER GRAPH] Failed to get user: %s", e)
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

        scope = self._scope_for_operation(
            "ensure_module_node",
            write=True,
            module_id=module_id,
        )
        if scope is None:
            return False

        params = {
            "module_id": module_id,
            "title": title,
            "document_id": document_id,
            **self._org_params(scope),
        }
        if self._uses_org_scope(scope):
            query = """
                    MERGE (m:Module {id: $module_id, organization_id: $organization_id})
                    SET m.title = $title,
                        m.document_id = COALESCE($document_id, m.document_id),
                        m.updated_at = datetime()
                """
        else:
            query = """
                    MERGE (m:Module {id: $module_id})
                    SET m.title = $title,
                        m.document_id = COALESCE($document_id, m.document_id),
                        m.updated_at = datetime()
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to create module: %s", e)
            return False

    # =========================================================================
    # TOPIC NODE OPERATIONS
    # =========================================================================

    def ensure_topic_node(self, topic_id: str, name: str) -> bool:
        """Create or update Topic node."""
        if not self._available:
            return False

        scope = self._scope_for_operation(
            "ensure_topic_node",
            write=True,
            topic_id=topic_id,
        )
        if scope is None:
            return False

        params = {"topic_id": topic_id, "name": name, **self._org_params(scope)}
        if self._uses_org_scope(scope):
            query = """
                    MERGE (t:Topic {id: $topic_id, organization_id: $organization_id})
                    SET t.name = $name,
                        t.updated_at = datetime()
                """
        else:
            query = """
                    MERGE (t:Topic {id: $topic_id})
                    SET t.name = $name,
                        t.updated_at = datetime()
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to create topic: %s", e)
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

        scope = self._scope_for_operation(
            "mark_studied",
            write=True,
            user_id=user_id,
            module_id=module_id,
        )
        if scope is None:
            return False

        params = {
            "user_id": user_id,
            "module_id": module_id,
            "progress": progress,
            **self._org_params(scope),
        }
        if self._uses_org_scope(scope):
            query = """
                    MATCH (u:User {id: $user_id, organization_id: $organization_id})
                    MATCH (m:Module {id: $module_id, organization_id: $organization_id})
                    MERGE (u)-[r:STUDIED]->(m)
                    SET r.progress = $progress,
                        r.last_studied = datetime()
                """
        else:
            query = """
                    MATCH (u:User {id: $user_id})
                    MATCH (m:Module {id: $module_id})
                    MERGE (u)-[r:STUDIED]->(m)
                    SET r.progress = $progress,
                        r.last_studied = datetime()
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)

            logger.info(
                "[USER GRAPH] user_hash=%s STUDIED module_hash=%s (%.0f%%) org_hash=%s",
                hash_memory_identifier(user_id),
                hash_memory_identifier(module_id),
                progress * 100,
                hash_memory_identifier(scope.org_id),
            )
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to mark studied: %s", e)
            return False

    def mark_completed(self, user_id: str, module_id: str) -> bool:
        """Mark that user completed a module."""
        if not self._available:
            return False

        scope = self._scope_for_operation(
            "mark_completed",
            write=True,
            user_id=user_id,
            module_id=module_id,
        )
        if scope is None:
            return False

        params = {"user_id": user_id, "module_id": module_id, **self._org_params(scope)}
        if self._uses_org_scope(scope):
            query = """
                    MATCH (u:User {id: $user_id, organization_id: $organization_id})
                    MATCH (m:Module {id: $module_id, organization_id: $organization_id})
                    MERGE (u)-[r:COMPLETED]->(m)
                    SET r.completed_at = datetime()
                """
        else:
            query = """
                    MATCH (u:User {id: $user_id})
                    MATCH (m:Module {id: $module_id})
                    MERGE (u)-[r:COMPLETED]->(m)
                    SET r.completed_at = datetime()
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)

            logger.info(
                "[USER GRAPH] user_hash=%s COMPLETED module_hash=%s org_hash=%s",
                hash_memory_identifier(user_id),
                hash_memory_identifier(module_id),
                hash_memory_identifier(scope.org_id),
            )
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to mark completed: %s", e)
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

        scope = self._scope_for_operation(
            "mark_weak_at",
            write=True,
            user_id=user_id,
            topic_id=topic_id,
        )
        if scope is None:
            return False

        params = {
            "user_id": user_id,
            "topic_id": topic_id,
            "confidence": confidence,
            **self._org_params(scope),
        }
        if self._uses_org_scope(scope):
            query = """
                    MATCH (u:User {id: $user_id, organization_id: $organization_id})
                    MATCH (t:Topic {id: $topic_id, organization_id: $organization_id})
                    MERGE (u)-[r:WEAK_AT]->(t)
                    SET r.confidence = $confidence,
                        r.detected_at = datetime()
                """
        else:
            query = """
                    MATCH (u:User {id: $user_id})
                    MATCH (t:Topic {id: $topic_id})
                    MERGE (u)-[r:WEAK_AT]->(t)
                    SET r.confidence = $confidence,
                        r.detected_at = datetime()
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)

            logger.info(
                "[USER GRAPH] user_hash=%s WEAK_AT topic_hash=%s org_hash=%s",
                hash_memory_identifier(user_id),
                hash_memory_identifier(topic_id),
                hash_memory_identifier(scope.org_id),
            )
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to mark weak_at: %s", e)
            return False

    def add_prerequisite(self, module_id: str, requires_module_id: str) -> bool:
        """Add prerequisite relationship between modules."""
        if not self._available:
            return False

        scope = self._scope_for_operation(
            "add_prerequisite",
            write=True,
            module_id=module_id,
        )
        if scope is None:
            return False

        params = {
            "module_id": module_id,
            "requires_module_id": requires_module_id,
            **self._org_params(scope),
        }
        if self._uses_org_scope(scope):
            query = """
                    MATCH (m:Module {id: $module_id, organization_id: $organization_id})
                    MATCH (req:Module {id: $requires_module_id, organization_id: $organization_id})
                    MERGE (m)-[:PREREQUISITE]->(req)
                """
        else:
            query = """
                    MATCH (m:Module {id: $module_id})
                    MATCH (req:Module {id: $requires_module_id})
                    MERGE (m)-[:PREREQUISITE]->(req)
                """

        try:
            with self._driver.session() as session:
                session.run(query, **params)
            return True
        except Exception as e:
            logger.error("[USER GRAPH] Failed to add prerequisite: %s", e)
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

        scope = self._scope_for_operation(
            "get_learning_path",
            write=False,
            user_id=user_id,
        )
        if scope is None:
            return []

        params = {"user_id": user_id, "depth": depth, **self._org_params(scope)}
        if self._uses_org_scope(scope):
            query = """
                    MATCH (u:User {id: $user_id, organization_id: $organization_id})
                          -[r:STUDIED|COMPLETED]->
                          (m:Module {organization_id: $organization_id})
                    RETURN m.id as module_id, m.title as title,
                           r.progress as progress, type(r) as status,
                           r.last_studied as last_studied
                    ORDER BY r.last_studied DESC
                    LIMIT $depth
                """
        else:
            query = """
                    MATCH (u:User {id: $user_id})-[r:STUDIED|COMPLETED]->(m:Module)
                    RETURN m.id as module_id, m.title as title,
                           r.progress as progress, type(r) as status,
                           r.last_studied as last_studied
                    ORDER BY r.last_studied DESC
                    LIMIT $depth
                """

        try:
            with self._driver.session() as session:
                result = session.run(query, **params)

                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[USER GRAPH] Failed to get learning path: %s", e)
            return []

    def get_knowledge_gaps(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get topics user is weak at.

        Returns list of topics with weakness confidence.
        """
        if not self._available:
            return []

        scope = self._scope_for_operation(
            "get_knowledge_gaps",
            write=False,
            user_id=user_id,
        )
        if scope is None:
            return []

        params = {"user_id": user_id, **self._org_params(scope)}
        if self._uses_org_scope(scope):
            query = """
                    MATCH (u:User {id: $user_id, organization_id: $organization_id})
                          -[r:WEAK_AT]->
                          (t:Topic {organization_id: $organization_id})
                    RETURN t.id as topic_id, t.name as topic_name,
                           r.confidence as confidence
                    ORDER BY r.confidence DESC
                """
        else:
            query = """
                    MATCH (u:User {id: $user_id})-[r:WEAK_AT]->(t:Topic)
                    RETURN t.id as topic_id, t.name as topic_name,
                           r.confidence as confidence
                    ORDER BY r.confidence DESC
                """

        try:
            with self._driver.session() as session:
                result = session.run(query, **params)

                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[USER GRAPH] Failed to get knowledge gaps: %s", e)
            return []

    def get_prerequisites(self, module_id: str) -> List[Dict[str, Any]]:
        """Get prerequisite modules for a module."""
        if not self._available:
            return []

        scope = self._scope_for_operation(
            "get_prerequisites",
            write=False,
            module_id=module_id,
        )
        if scope is None:
            return []

        params = {"module_id": module_id, **self._org_params(scope)}
        if self._uses_org_scope(scope):
            query = """
                    MATCH (m:Module {id: $module_id, organization_id: $organization_id})
                          -[:PREREQUISITE*1..3]->
                          (req:Module {organization_id: $organization_id})
                    RETURN DISTINCT req.id as module_id, req.title as title
                """
        else:
            query = """
                    MATCH (m:Module {id: $module_id})-[:PREREQUISITE*1..3]->(req:Module)
                    RETURN DISTINCT req.id as module_id, req.title as title
                """

        try:
            with self._driver.session() as session:
                result = session.run(query, **params)

                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[USER GRAPH] Failed to get prerequisites: %s", e)
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
