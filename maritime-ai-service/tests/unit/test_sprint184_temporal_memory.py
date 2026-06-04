"""
Tests for Sprint 184: "Trí Nhớ Thời Gian" — Temporal Knowledge Graph Memory.

Covers:
- Data models (GraphEntity, GraphRelation, Episode, TemporalGraphContext)
- TemporalGraphManager CRUD operations
- Entity versioning (supersede pattern)
- Graph traversal (get_entity_neighbors)
- Episode management
- Context text building
- Serialization/deserialization
- extract_graph_from_facts integration
- Config flags
"""

import pytest
from datetime import datetime, timezone, timedelta


# =============================================================================
# 1. Enum Tests
# =============================================================================


class TestEntityType:
    def test_all_types(self):
        from app.engine.semantic_memory.temporal_graph import EntityType
        assert EntityType.PERSON == "person"
        assert EntityType.CONCEPT == "concept"
        assert EntityType.FACT == "fact"
        assert EntityType.LOCATION == "location"
        assert EntityType.SKILL == "skill"
        assert EntityType.PREFERENCE == "preference"


class TestRelationType:
    def test_all_types(self):
        from app.engine.semantic_memory.temporal_graph import RelationType
        assert RelationType.HAS_FACT == "has_fact"
        assert RelationType.KNOWS == "knows"
        assert RelationType.WEAK_AT == "weak_at"
        assert RelationType.SUPERSEDES == "supersedes"


# =============================================================================
# 2. GraphEntity Tests
# =============================================================================


class TestGraphEntity:
    def test_basic_creation(self):
        from app.engine.semantic_memory.temporal_graph import GraphEntity, EntityType
        e = GraphEntity(entity_id="e1", name="Hùng", entity_type=EntityType.PERSON)
        assert e.entity_id == "e1"
        assert e.name == "Hùng"
        assert e.version == 1
        assert e.is_current is True
        assert e.superseded_by is None

    def test_to_dict(self):
        from app.engine.semantic_memory.temporal_graph import GraphEntity, EntityType
        now = datetime.now(timezone.utc)
        e = GraphEntity(
            entity_id="e1",
            name="COLREGs",
            entity_type=EntityType.CONCEPT,
            description="International Regulations",
            event_time=now,
            ingestion_time=now,
        )
        d = e.to_dict()
        assert d["entity_id"] == "e1"
        assert d["entity_type"] == "concept"
        assert d["event_time"] is not None

    def test_from_dict(self):
        from app.engine.semantic_memory.temporal_graph import GraphEntity, EntityType
        data = {
            "entity_id": "e2",
            "name": "SOLAS",
            "entity_type": "concept",
            "description": "Safety of Life at Sea",
            "version": 2,
            "is_current": True,
        }
        e = GraphEntity.from_dict(data)
        assert e.entity_id == "e2"
        assert e.entity_type == EntityType.CONCEPT
        assert e.version == 2

    def test_roundtrip_serialization(self):
        from app.engine.semantic_memory.temporal_graph import GraphEntity, EntityType
        now = datetime.now(timezone.utc)
        original = GraphEntity(
            entity_id="e3",
            name="test",
            entity_type=EntityType.FACT,
            description="desc",
            properties={"key": "val"},
            event_time=now,
            ingestion_time=now,
            version=3,
            superseded_by="e4",
            is_current=False,
        )
        restored = GraphEntity.from_dict(original.to_dict())
        assert restored.entity_id == original.entity_id
        assert restored.version == 3
        assert restored.is_current is False
        assert restored.superseded_by == "e4"


# =============================================================================
# 3. GraphRelation Tests
# =============================================================================


class TestGraphRelation:
    def test_basic_creation(self):
        from app.engine.semantic_memory.temporal_graph import GraphRelation, RelationType
        r = GraphRelation(
            relation_id="r1",
            source_id="e1",
            target_id="e2",
            relation_type=RelationType.KNOWS,
        )
        assert r.confidence == 1.0

    def test_to_dict_and_from_dict(self):
        from app.engine.semantic_memory.temporal_graph import GraphRelation, RelationType
        now = datetime.now(timezone.utc)
        original = GraphRelation(
            relation_id="r2",
            source_id="s1",
            target_id="t1",
            relation_type=RelationType.WEAK_AT,
            confidence=0.85,
            event_time=now,
        )
        restored = GraphRelation.from_dict(original.to_dict())
        assert restored.relation_id == "r2"
        assert restored.relation_type == RelationType.WEAK_AT
        assert restored.confidence == 0.85


# =============================================================================
# 4. Episode Tests
# =============================================================================


class TestEpisode:
    def test_basic_creation(self):
        from app.engine.semantic_memory.temporal_graph import Episode
        ep = Episode(
            episode_id="ep1",
            user_id="user-1",
            summary="Test session",
        )
        assert ep.episode_id == "ep1"
        assert ep.entity_ids == []

    def test_to_dict_and_from_dict(self):
        from app.engine.semantic_memory.temporal_graph import Episode
        now = datetime.now(timezone.utc)
        original = Episode(
            episode_id="ep2",
            user_id="user-2",
            session_id="sess-1",
            summary="Learning about COLREGs",
            entity_ids=["e1", "e2"],
            relation_ids=["r1"],
            start_time=now,
        )
        restored = Episode.from_dict(original.to_dict())
        assert restored.episode_id == "ep2"
        assert len(restored.entity_ids) == 2
        assert restored.summary == "Learning about COLREGs"


# =============================================================================
# 5. TemporalGraphManager Tests
# =============================================================================


class TestTemporalGraphManagerEntities:
    def test_add_entity(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        e = m.add_entity("u1", "Hùng", EntityType.PERSON, description="Student")
        assert e.name == "Hùng"
        assert e.entity_type == EntityType.PERSON
        assert e.is_current is True
        assert e.version == 1

    def test_add_duplicate_same_value(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        e1 = m.add_entity("u1", "Hùng", EntityType.PERSON, description="Student")
        e2 = m.add_entity("u1", "Hùng", EntityType.PERSON, description="Student")
        # Same value — should return same entity, just updated ingestion_time
        assert e1.entity_id == e2.entity_id
        assert len(m.get_entities("u1")) == 1

    def test_entity_versioning(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        e1 = m.add_entity("u1", "role", EntityType.FACT, description="sinh viên năm 2")
        e2 = m.add_entity("u1", "role", EntityType.FACT, description="sinh viên năm 3")

        # e1 should be superseded
        assert e1.is_current is False
        assert e1.superseded_by is not None
        assert e2.is_current is True
        assert e2.version == 2

        # get_entities should return only current
        current = m.get_entities("u1", current_only=True)
        assert len(current) == 1
        assert current[0].version == 2

    def test_get_entities_all_versions(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        m.add_entity("u1", "role", EntityType.FACT, description="v1")
        m.add_entity("u1", "role", EntityType.FACT, description="v2")

        all_entities = m.get_entities("u1", current_only=False)
        assert len(all_entities) == 2

    def test_get_entities_by_type(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        m.add_entity("u1", "Hùng", EntityType.PERSON)
        m.add_entity("u1", "COLREGs", EntityType.CONCEPT)
        m.add_entity("u1", "Hải Phòng", EntityType.LOCATION)

        persons = m.get_entities("u1", entity_type=EntityType.PERSON)
        assert len(persons) == 1
        assert persons[0].name == "Hùng"

    def test_get_entity_history(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        m.add_entity("u1", "goal", EntityType.PREFERENCE, description="Pass COLREGs exam")
        m.add_entity("u1", "goal", EntityType.PREFERENCE, description="Master COLREGs")

        history = m.get_entity_history("u1", "goal", EntityType.PREFERENCE)
        assert len(history) == 2
        assert history[0].version == 1
        assert history[1].version == 2


class TestTemporalGraphManagerRelations:
    def test_add_relation(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "Hùng", EntityType.PERSON)
        m.add_entity("u1", "COLREGs", EntityType.CONCEPT)

        r = m.add_relation("u1", "Hùng_person_v1", "COLREGs_concept_v1", RelationType.STUDIES)
        assert r.relation_type == RelationType.STUDIES
        assert r.source_id == "Hùng_person_v1"

    def test_get_relations_by_entity(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "Hùng", EntityType.PERSON)
        m.add_entity("u1", "COLREGs", EntityType.CONCEPT)
        m.add_entity("u1", "SOLAS", EntityType.CONCEPT)

        m.add_relation("u1", "Hùng_person_v1", "COLREGs_concept_v1", RelationType.STUDIES)
        m.add_relation("u1", "Hùng_person_v1", "SOLAS_concept_v1", RelationType.STUDIES)

        rels = m.get_relations("u1", entity_id="Hùng_person_v1")
        assert len(rels) == 2

    def test_get_relations_by_type(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, RelationType
        m = TemporalGraphManager()
        m.add_relation("u1", "e1", "e2", RelationType.STUDIES)
        m.add_relation("u1", "e1", "e3", RelationType.WEAK_AT)

        studies = m.get_relations("u1", relation_type=RelationType.STUDIES)
        assert len(studies) == 1


class TestTemporalGraphManagerEpisodes:
    def test_add_episode(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager
        m = TemporalGraphManager()
        ep = m.add_episode("u1", session_id="sess-1", summary="Learning COLREGs")
        assert "sess-1" in ep.episode_id
        assert ep.user_id == "u1"

    def test_get_episodes_sorted(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager
        m = TemporalGraphManager()
        now = datetime.now(timezone.utc)

        m.add_episode("u1", summary="old", start_time=now - timedelta(hours=2))
        m.add_episode("u1", summary="new", start_time=now)

        episodes = m.get_episodes("u1", limit=2)
        assert episodes[0].summary == "new"  # Most recent first

    def test_get_episodes_by_session(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager
        m = TemporalGraphManager()
        m.add_episode("u1", session_id="s1", summary="session 1")
        m.add_episode("u1", session_id="s2", summary="session 2")

        eps = m.get_episodes("u1", session_id="s1")
        assert len(eps) == 1
        assert eps[0].summary == "session 1"


class TestTemporalGraphManagerTraversal:
    def test_get_entity_neighbors_1_hop(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "A", EntityType.PERSON)
        m.add_entity("u1", "B", EntityType.CONCEPT)
        m.add_entity("u1", "C", EntityType.CONCEPT)
        m.add_relation("u1", "A_person_v1", "B_concept_v1", RelationType.STUDIES)
        m.add_relation("u1", "B_concept_v1", "C_concept_v1", RelationType.RELATED_TO)

        neighbors = m.get_entity_neighbors("u1", "A_person_v1", max_hops=1)
        assert len(neighbors) == 1  # Only B (1 hop)
        assert neighbors[0].name == "B"

    def test_get_entity_neighbors_2_hops(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "A", EntityType.PERSON)
        m.add_entity("u1", "B", EntityType.CONCEPT)
        m.add_entity("u1", "C", EntityType.CONCEPT)
        m.add_relation("u1", "A_person_v1", "B_concept_v1", RelationType.STUDIES)
        m.add_relation("u1", "B_concept_v1", "C_concept_v1", RelationType.RELATED_TO)

        neighbors = m.get_entity_neighbors("u1", "A_person_v1", max_hops=2)
        assert len(neighbors) == 2  # B + C

    def test_get_entity_neighbors_empty(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager
        m = TemporalGraphManager()
        neighbors = m.get_entity_neighbors("u1", "nonexistent", max_hops=1)
        assert neighbors == []


# =============================================================================
# 6. Serialization Tests
# =============================================================================


class TestSerialization:
    def test_to_dict(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "test", EntityType.FACT, description="testing")
        m.add_relation("u1", "test_fact_v1", "other", RelationType.RELATED_TO)

        data = m.to_dict("u1")
        assert "entities" in data
        assert "relations" in data
        assert "episodes" in data
        assert len(data["entities"]) == 1

    def test_from_dict(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "A", EntityType.PERSON)
        m.add_entity("u1", "B", EntityType.CONCEPT)
        m.add_relation("u1", "A_person_v1", "B_concept_v1", RelationType.KNOWS)
        m.add_episode("u1", summary="test episode")

        data = m.to_dict("u1")

        m2 = TemporalGraphManager()
        m2.from_dict("u1", data)

        assert len(m2.get_entities("u1")) == 2
        assert len(m2.get_relations("u1")) == 1
        assert len(m2.get_episodes("u1")) == 1

    def test_clear_user(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        m.add_entity("u1", "test", EntityType.FACT)
        m.add_episode("u1", summary="ep")

        m.clear_user("u1")
        assert m.get_entities("u1") == []
        assert m.get_episodes("u1") == []


# =============================================================================
# 6b. Organization Scope Tests
# =============================================================================


class TestTemporalGraphOrgScope:
    def test_same_user_graph_isolated_by_current_org(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.semantic_memory.temporal_graph import (
            EntityType,
            TemporalGraphManager,
        )

        m = TemporalGraphManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            m.add_entity("same-user", "Org A fact", EntityType.FACT)
            assert [e.name for e in m.get_entities("same-user")] == ["Org A fact"]
        finally:
            current_org_id.reset(token)

        token = current_org_id.set("org-B")
        try:
            m.add_entity("same-user", "Org B fact", EntityType.FACT)
            assert [e.name for e in m.get_entities("same-user")] == ["Org B fact"]
            data = m.to_dict("same-user")
        finally:
            current_org_id.reset(token)

        assert list(data["entities"]) == ["Org B fact_fact_v1"]

        token = current_org_id.set("org-A")
        try:
            assert [e.name for e in m.get_entities("same-user")] == ["Org A fact"]
        finally:
            current_org_id.reset(token)

    def test_write_blocks_without_org_context_in_production(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.semantic_memory.temporal_graph import (
            EntityType,
            TEMPORAL_GRAPH_SCOPE_BLOCKED_ERROR,
            TemporalGraphManager,
        )

        m = TemporalGraphManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            with pytest.raises(ValueError, match=TEMPORAL_GRAPH_SCOPE_BLOCKED_ERROR):
                m.add_entity("raw-temporal-user", "Private fact", EntityType.FACT)
            assert m.get_entities("raw-temporal-user") == []
            assert m.to_dict("raw-temporal-user") == {
                "entities": {},
                "relations": {},
                "episodes": {},
            }
        finally:
            current_org_id.reset(token)


# =============================================================================
# 7. Context Text Tests
# =============================================================================


class TestBuildContextText:
    def test_basic_context(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        m.add_entity("u1", "Hùng", EntityType.PERSON, description="Sinh viên")
        m.add_entity("u1", "COLREGs", EntityType.CONCEPT, description="Quy tắc tránh va")

        text = m.build_context_text("u1")
        assert "Hùng" in text
        assert "COLREGs" in text
        assert "Thông tin liên quan" in text

    def test_context_with_relations(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType, RelationType
        m = TemporalGraphManager()
        m.add_entity("u1", "user", EntityType.PERSON)
        m.add_entity("u1", "navigation", EntityType.SKILL)
        m.add_relation("u1", "user_person_v1", "navigation_skill_v1", RelationType.WEAK_AT)

        text = m.build_context_text("u1")
        assert "Quan hệ" in text
        assert "weak_at" in text

    def test_empty_graph(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager
        m = TemporalGraphManager()
        text = m.build_context_text("u1")
        assert text == ""

    def test_filtered_by_entity_ids(self):
        from app.engine.semantic_memory.temporal_graph import TemporalGraphManager, EntityType
        m = TemporalGraphManager()
        m.add_entity("u1", "A", EntityType.FACT, description="fact A")
        m.add_entity("u1", "B", EntityType.FACT, description="fact B")

        text = m.build_context_text("u1", relevant_entity_ids=["A_fact_v1"])
        assert "A" in text


# =============================================================================
# 8. extract_graph_from_facts Tests
# =============================================================================


class TestExtractGraphFromFacts:
    @pytest.mark.asyncio
    async def test_extract_basic_facts(self):
        from app.engine.semantic_memory.temporal_graph import (
            extract_graph_from_facts,
        )

        # Reset singleton
        import app.engine.semantic_memory.temporal_graph as mod
        mod._manager = None

        facts = [
            {"fact_type": "name", "value": "Hùng", "confidence": 0.95},
            {"fact_type": "hometown", "value": "Hải Phòng", "confidence": 0.9},
            {"fact_type": "weakness", "value": "Rule 15", "confidence": 0.8},
        ]

        result = await extract_graph_from_facts("user-1", facts, session_id="sess-1")

        assert len(result.entities) == 3
        assert len(result.relations) == 3
        assert len(result.episodes) == 1
        assert result.total_time_ms >= 0
        assert result.context_text  # Non-empty

    @pytest.mark.asyncio
    async def test_extract_empty_facts(self):
        from app.engine.semantic_memory.temporal_graph import extract_graph_from_facts
        import app.engine.semantic_memory.temporal_graph as mod
        mod._manager = None

        result = await extract_graph_from_facts("user-2", [])
        assert len(result.entities) == 0
        assert len(result.episodes) == 1  # Episode still created

    @pytest.mark.asyncio
    async def test_extract_skips_empty_values(self):
        from app.engine.semantic_memory.temporal_graph import extract_graph_from_facts
        import app.engine.semantic_memory.temporal_graph as mod
        mod._manager = None

        facts = [
            {"fact_type": "name", "value": "", "confidence": 0.9},
            {"fact_type": "role", "value": "student", "confidence": 0.85},
        ]

        result = await extract_graph_from_facts("user-3", facts)
        assert len(result.entities) == 1  # Only "student", not empty name

    @pytest.mark.asyncio
    async def test_extract_maps_fact_types(self):
        from app.engine.semantic_memory.temporal_graph import (
            extract_graph_from_facts,
            EntityType,
        )
        import app.engine.semantic_memory.temporal_graph as mod
        mod._manager = None

        facts = [
            {"fact_type": "hometown", "value": "Hà Nội", "confidence": 0.9},
            {"fact_type": "weakness", "value": "navigation", "confidence": 0.7},
            {"fact_type": "interest", "value": "COLREGs", "confidence": 0.8},
        ]

        result = await extract_graph_from_facts("user-4", facts)

        entity_types = [e.entity_type for e in result.entities]
        assert EntityType.LOCATION in entity_types
        assert EntityType.SKILL in entity_types
        assert EntityType.CONCEPT in entity_types

    @pytest.mark.asyncio
    async def test_extract_blocks_without_org_context_in_production(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.semantic_memory.temporal_graph import (
            TEMPORAL_GRAPH_SCOPE_BLOCKED_ERROR,
            extract_graph_from_facts,
            get_temporal_graph_manager,
        )
        import app.engine.semantic_memory.temporal_graph as mod
        mod._manager = None

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            with pytest.raises(ValueError, match=TEMPORAL_GRAPH_SCOPE_BLOCKED_ERROR):
                await extract_graph_from_facts(
                    "raw-temporal-user",
                    [{"fact_type": "goal", "value": "PRIVATE TEMPORAL FACT"}],
                    session_id="raw-temporal-session",
                )
            manager = get_temporal_graph_manager()
            assert manager.to_dict("raw-temporal-user") == {
                "entities": {},
                "relations": {},
                "episodes": {},
            }
        finally:
            current_org_id.reset(token)


# =============================================================================
# 9. Singleton Tests
# =============================================================================


class TestSingleton:
    def test_get_temporal_graph_manager(self):
        import app.engine.semantic_memory.temporal_graph as mod
        mod._manager = None

        from app.engine.semantic_memory.temporal_graph import get_temporal_graph_manager
        m1 = get_temporal_graph_manager()
        m2 = get_temporal_graph_manager()
        assert m1 is m2


# =============================================================================
# 10. Config Tests
# =============================================================================


class TestConfig:
    def test_enable_temporal_memory_default_false(self):
        from app.core.config import Settings
        s = Settings(
            api_key="test",
            google_api_key="test",
            database_url="postgresql+asyncpg://x/y",
        )
        assert s.enable_temporal_memory is False


# =============================================================================
# 11. Import Tests
# =============================================================================


class TestImports:
    def test_module_imports(self):
        from app.engine.semantic_memory.temporal_graph import (
            EntityType,
            RelationType,
            GraphEntity,
            GraphRelation,
            Episode,
            TemporalGraphContext,
            TemporalGraphManager,
            get_temporal_graph_manager,
            extract_graph_from_facts,
        )
        assert all(
            item is not None
            for item in (
                EntityType,
                RelationType,
                GraphEntity,
                GraphRelation,
                Episode,
                TemporalGraphContext,
                TemporalGraphManager,
            )
        )
        assert callable(get_temporal_graph_manager)
        assert callable(extract_graph_from_facts)
