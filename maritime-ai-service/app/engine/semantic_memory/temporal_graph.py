"""
Temporal Knowledge Graph Memory — Zep/Graphiti-inspired memory layer.
Sprint 184-186: "Trí Nhớ Thời Gian"

Augments the existing semantic memory with entity-relation-episode subgraphs:
1. **Entities**: People, concepts, facts extracted from conversations
2. **Relations**: Connections between entities (user→fact, fact→fact)
3. **Episodes**: Time-bounded interaction contexts (sessions, events)

Key patterns:
- Bi-temporal model: event_time (when it happened) + ingestion_time (when stored)
- Fact versioning: changed_at, superseded_by for history tracking
- Hybrid retrieval: semantic + keyword + recency + graph traversal

Data storage:
- Uses existing `semantic_memories` table with `metadata.graph` JSON field
- Zero new migrations required — additive metadata only
- Feature-gated by enable_temporal_memory in config

Reference: Zep/Graphiti (2025), Microsoft GraphRAG, Mem0
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.temporal_graph_runtime import (
    build_context_text_impl,
    extract_graph_from_facts_impl,
    from_dict_impl,
    to_dict_impl,
)
from app.engine.semantic_memory.write_audit import (
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)
TEMPORAL_GRAPH_SCOPE_BLOCKED_ERROR = (
    "temporal graph memory blocked missing organization context"
)


# =============================================================================
# Data Models
# =============================================================================


class EntityType(str, Enum):
    """Types of entities in the knowledge graph."""

    PERSON = "person"          # User, teacher, family member
    CONCEPT = "concept"        # Domain concept (COLREGs, SOLAS)
    FACT = "fact"              # Atomic fact about user
    LOCATION = "location"      # Place, city, school
    EVENT = "event"            # Specific event (exam, class, meeting)
    SKILL = "skill"            # Learning skill/ability
    PREFERENCE = "preference"  # User preference


class RelationType(str, Enum):
    """Types of relations between entities."""

    HAS_FACT = "has_fact"            # user → fact
    KNOWS = "knows"                  # user → concept/person
    LOCATED_AT = "located_at"        # user/event → location
    STUDIES = "studies"              # user → concept
    WEAK_AT = "weak_at"             # user → skill
    STRONG_AT = "strong_at"         # user → skill
    PREFERS = "prefers"             # user → preference
    RELATED_TO = "related_to"       # concept → concept
    SUPERSEDES = "supersedes"       # fact_v2 → fact_v1


@dataclass
class GraphEntity:
    """An entity in the temporal knowledge graph."""

    entity_id: str
    name: str
    entity_type: EntityType
    description: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    # Bi-temporal timestamps
    event_time: Optional[datetime] = None     # When the fact/event occurred
    ingestion_time: Optional[datetime] = None  # When we stored it
    # Versioning
    version: int = 1
    superseded_by: Optional[str] = None  # entity_id of newer version
    is_current: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type.value,
            "description": self.description,
            "properties": self.properties,
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "ingestion_time": self.ingestion_time.isoformat() if self.ingestion_time else None,
            "version": self.version,
            "superseded_by": self.superseded_by,
            "is_current": self.is_current,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEntity":
        return cls(
            entity_id=data["entity_id"],
            name=data["name"],
            entity_type=EntityType(data["entity_type"]),
            description=data.get("description", ""),
            properties=data.get("properties", {}),
            event_time=datetime.fromisoformat(data["event_time"]) if data.get("event_time") else None,
            ingestion_time=datetime.fromisoformat(data["ingestion_time"]) if data.get("ingestion_time") else None,
            version=data.get("version", 1),
            superseded_by=data.get("superseded_by"),
            is_current=data.get("is_current", True),
        )


@dataclass
class GraphRelation:
    """A relation between two entities."""

    relation_id: str
    source_id: str
    target_id: str
    relation_type: RelationType
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    event_time: Optional[datetime] = None
    ingestion_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type.value,
            "properties": self.properties,
            "confidence": self.confidence,
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "ingestion_time": self.ingestion_time.isoformat() if self.ingestion_time else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphRelation":
        return cls(
            relation_id=data["relation_id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation_type=RelationType(data["relation_type"]),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            event_time=datetime.fromisoformat(data["event_time"]) if data.get("event_time") else None,
            ingestion_time=datetime.fromisoformat(data["ingestion_time"]) if data.get("ingestion_time") else None,
        )


@dataclass
class Episode:
    """A time-bounded interaction context."""

    episode_id: str
    user_id: str
    session_id: Optional[str] = None
    summary: str = ""
    entity_ids: List[str] = field(default_factory=list)
    relation_ids: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "summary": self.summary,
            "entity_ids": self.entity_ids,
            "relation_ids": self.relation_ids,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Episode":
        return cls(
            episode_id=data["episode_id"],
            user_id=data["user_id"],
            session_id=data.get("session_id"),
            summary=data.get("summary", ""),
            entity_ids=data.get("entity_ids", []),
            relation_ids=data.get("relation_ids", []),
            start_time=datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None,
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            metadata=data.get("metadata", {}),
        )


@dataclass
class TemporalGraphContext:
    """Result from temporal graph memory retrieval."""

    entities: List[GraphEntity] = field(default_factory=list)
    relations: List[GraphRelation] = field(default_factory=list)
    episodes: List[Episode] = field(default_factory=list)
    context_text: str = ""
    total_time_ms: float = 0.0


# =============================================================================
# Temporal Graph Manager
# =============================================================================


class TemporalGraphManager:
    """Manages entity-relation-episode subgraphs for a user.

    Stores graph data in semantic_memories metadata.graph JSON field.
    This avoids new database migrations while providing graph capabilities.
    """

    def __init__(self):
        self._entities: Dict[str, Dict[str, GraphEntity]] = {}  # user_id → {entity_id → entity}
        self._relations: Dict[str, Dict[str, GraphRelation]] = {}  # user_id → {relation_id → relation}
        self._episodes: Dict[str, Dict[str, Episode]] = {}  # user_id → {episode_id → episode}

    def _scope_key(self, user_id: str, *, write: bool = False) -> str | None:
        scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
        if not scope.write_allowed:
            logger.warning(
                "[TGraph] %s blocked user_hash=%s org_hash=%s org_scope=%s warnings=%s",
                "write" if write else "read",
                hash_memory_identifier(user_id),
                hash_memory_identifier(scope.org_id),
                scope.state,
                scope.warnings,
            )
            return None
        if scope.state == "single_tenant_default":
            return user_id
        return f"{scope.org_id}:{user_id}" if scope.org_id else user_id

    def _write_scope_key(self, user_id: str) -> str:
        scope_key = self._scope_key(user_id, write=True)
        if scope_key is None:
            raise ValueError(TEMPORAL_GRAPH_SCOPE_BLOCKED_ERROR)
        return scope_key

    def add_entity(
        self,
        user_id: str,
        name: str,
        entity_type: EntityType,
        description: str = "",
        properties: Optional[Dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> GraphEntity:
        """Add or update an entity in the user's graph.

        If an entity with the same name and type exists:
        - If value differs: create new version, supersede old
        - If same: update ingestion_time only
        """
        now = datetime.now(timezone.utc)
        scope_key = self._write_scope_key(user_id)

        if scope_key not in self._entities:
            self._entities[scope_key] = {}

        # Check for existing entity with same name+type
        existing = None
        for e in self._entities[scope_key].values():
            if e.name == name and e.entity_type == entity_type and e.is_current:
                existing = e
                break

        if existing:
            # Check if description (value) changed → version
            if description and description != existing.description:
                # Supersede old version
                existing.is_current = False
                existing.superseded_by = f"{name}_{entity_type.value}_v{existing.version + 1}"

                entity = GraphEntity(
                    entity_id=existing.superseded_by,
                    name=name,
                    entity_type=entity_type,
                    description=description,
                    properties=properties or existing.properties,
                    event_time=event_time or now,
                    ingestion_time=now,
                    version=existing.version + 1,
                    is_current=True,
                )
                self._entities[scope_key][entity.entity_id] = entity
                logger.info(
                    "[TGraph] Versioned entity: %s v%d → v%d",
                    name, existing.version, entity.version,
                )
                return entity
            else:
                # Same value — just update ingestion_time
                existing.ingestion_time = now
                return existing

        # New entity
        entity_id = f"{name}_{entity_type.value}_v1"
        entity = GraphEntity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            description=description,
            properties=properties or {},
            event_time=event_time or now,
            ingestion_time=now,
        )
        self._entities[scope_key][entity_id] = entity
        return entity

    def add_relation(
        self,
        user_id: str,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        confidence: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
        event_time: Optional[datetime] = None,
    ) -> GraphRelation:
        """Add a relation between two entities."""
        now = datetime.now(timezone.utc)
        scope_key = self._write_scope_key(user_id)

        if scope_key not in self._relations:
            self._relations[scope_key] = {}

        relation_id = f"{source_id}__{relation_type.value}__{target_id}"
        relation = GraphRelation(
            relation_id=relation_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=properties or {},
            confidence=confidence,
            event_time=event_time or now,
            ingestion_time=now,
        )
        self._relations[scope_key][relation_id] = relation
        return relation

    def add_episode(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        summary: str = "",
        entity_ids: Optional[List[str]] = None,
        relation_ids: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Episode:
        """Record an interaction episode."""
        now = datetime.now(timezone.utc)
        scope_key = self._write_scope_key(user_id)

        if scope_key not in self._episodes:
            self._episodes[scope_key] = {}

        episode_id = f"ep_{session_id or uuid4().hex[:8]}_{now.strftime('%Y%m%d_%H%M%S')}"
        episode = Episode(
            episode_id=episode_id,
            user_id=user_id,
            session_id=session_id,
            summary=summary,
            entity_ids=entity_ids or [],
            relation_ids=relation_ids or [],
            start_time=start_time or now,
            end_time=end_time,
        )
        self._episodes[scope_key][episode_id] = episode
        return episode

    def get_entities(
        self,
        user_id: str,
        entity_type: Optional[EntityType] = None,
        current_only: bool = True,
    ) -> List[GraphEntity]:
        """Get entities for a user, optionally filtered by type."""
        scope_key = self._scope_key(user_id)
        if scope_key is None:
            return []
        entities = list(self._entities.get(scope_key, {}).values())

        if current_only:
            entities = [e for e in entities if e.is_current]

        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]

        return entities

    def get_relations(
        self,
        user_id: str,
        entity_id: Optional[str] = None,
        relation_type: Optional[RelationType] = None,
    ) -> List[GraphRelation]:
        """Get relations for a user, optionally filtered."""
        scope_key = self._scope_key(user_id)
        if scope_key is None:
            return []
        relations = list(self._relations.get(scope_key, {}).values())

        if entity_id:
            relations = [
                r for r in relations
                if r.source_id == entity_id or r.target_id == entity_id
            ]

        if relation_type:
            relations = [r for r in relations if r.relation_type == relation_type]

        return relations

    def get_entity_neighbors(
        self,
        user_id: str,
        entity_id: str,
        max_hops: int = 1,
    ) -> List[GraphEntity]:
        """Get neighboring entities via graph traversal.

        Performs BFS up to max_hops from the source entity.
        """
        scope_key = self._scope_key(user_id)
        if scope_key is None or scope_key not in self._entities:
            return []

        visited: Set[str] = {entity_id}
        frontier: Set[str] = {entity_id}
        result: List[GraphEntity] = []

        for _hop in range(max_hops):
            next_frontier: Set[str] = set()
            relations = self._relations.get(scope_key, {})

            for rel in relations.values():
                if rel.source_id in frontier and rel.target_id not in visited:
                    next_frontier.add(rel.target_id)
                    visited.add(rel.target_id)
                if rel.target_id in frontier and rel.source_id not in visited:
                    next_frontier.add(rel.source_id)
                    visited.add(rel.source_id)

            frontier = next_frontier

        # Collect entities
        entities = self._entities.get(scope_key, {})
        for eid in visited:
            if eid != entity_id and eid in entities:
                result.append(entities[eid])

        return result

    def get_episodes(
        self,
        user_id: str,
        limit: int = 5,
        session_id: Optional[str] = None,
    ) -> List[Episode]:
        """Get recent episodes for a user."""
        scope_key = self._scope_key(user_id)
        if scope_key is None:
            return []
        episodes = list(self._episodes.get(scope_key, {}).values())

        if session_id:
            episodes = [e for e in episodes if e.session_id == session_id]

        # Sort by start_time descending
        episodes.sort(
            key=lambda e: e.start_time or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        return episodes[:limit]

    def get_entity_history(
        self,
        user_id: str,
        name: str,
        entity_type: EntityType,
    ) -> List[GraphEntity]:
        """Get version history of an entity (all versions, including superseded)."""
        scope_key = self._scope_key(user_id)
        if scope_key is None:
            return []
        entities = self._entities.get(scope_key, {})
        history = [
            e for e in entities.values()
            if e.name == name and e.entity_type == entity_type
        ]
        history.sort(key=lambda e: e.version)
        return history

    def build_context_text(
        self,
        user_id: str,
        relevant_entity_ids: Optional[List[str]] = None,
        max_entities: int = 10,
        max_relations: int = 5,
    ) -> str:
        """Build a Vietnamese-language context text for LLM injection.

        Formats entities and their relations into a natural paragraph.
        """
        scope_key = self._scope_key(user_id)
        if scope_key is None:
            return ""
        return build_context_text_impl(
            user_id=scope_key,
            entities_by_user=self._entities,
            relations_by_user=self._relations,
            relevant_entity_ids=relevant_entity_ids,
            max_entities=max_entities,
            max_relations=max_relations,
        )

    def to_dict(self, user_id: str) -> Dict[str, Any]:
        """Serialize user's graph to dict for JSON storage."""
        scope_key = self._scope_key(user_id)
        if scope_key is None:
            return {"entities": {}, "relations": {}, "episodes": {}}
        return to_dict_impl(
            user_id=scope_key,
            entities_by_user=self._entities,
            relations_by_user=self._relations,
            episodes_by_user=self._episodes,
        )

    def from_dict(self, user_id: str, data: Dict[str, Any]) -> None:
        """Load user's graph from serialized dict."""
        scope_key = self._write_scope_key(user_id)
        entities, relations, episodes = from_dict_impl(
            user_id=user_id,
            data=data,
            entity_from_dict=GraphEntity.from_dict,
            relation_from_dict=GraphRelation.from_dict,
            episode_from_dict=Episode.from_dict,
        )
        self._entities[scope_key] = entities
        self._relations[scope_key] = relations
        self._episodes[scope_key] = episodes

    def clear_user(self, user_id: str) -> None:
        """Clear all graph data for a user."""
        scope_key = self._scope_key(user_id, write=True)
        if scope_key is None:
            return
        self._entities.pop(scope_key, None)
        self._relations.pop(scope_key, None)
        self._episodes.pop(scope_key, None)


# =============================================================================
# Module-level singleton
# =============================================================================

_manager: Optional[TemporalGraphManager] = None


def get_temporal_graph_manager() -> TemporalGraphManager:
    """Get or create the singleton TemporalGraphManager."""
    global _manager
    if _manager is None:
        _manager = TemporalGraphManager()
    return _manager


# =============================================================================
# Integration helper: extract graph from conversation
# =============================================================================


async def extract_graph_from_facts(
    user_id: str,
    facts: List[Dict[str, Any]],
    session_id: Optional[str] = None,
) -> TemporalGraphContext:
    """Convert extracted user facts into temporal graph entities and relations.

    Called after FactExtractor produces facts. Maps fact_types to graph entities.

    Args:
        user_id: User identifier.
        facts: List of extracted facts (from FactExtractor).
        session_id: Optional session ID for episode tracking.

    Returns:
        TemporalGraphContext with created entities, relations, and episode.
    """
    return await extract_graph_from_facts_impl(
        user_id=user_id,
        facts=facts,
        session_id=session_id,
        get_temporal_graph_manager_fn=get_temporal_graph_manager,
        temporal_graph_context_cls=TemporalGraphContext,
        entity_type_cls=EntityType,
        relation_type_cls=RelationType,
        logger_obj=logger,
    )
