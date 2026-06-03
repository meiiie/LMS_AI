import time
from typing import Any, Callable, Optional

from app.engine.semantic_memory.privacy import hash_memory_identifier


def build_context_text_impl(
    *,
    user_id: str,
    entities_by_user,
    relations_by_user,
    relevant_entity_ids: Optional[list[str]] = None,
    max_entities: int = 10,
    max_relations: int = 5,
) -> str:
    parts = []
    entities = entities_by_user.get(user_id, {})
    relations = relations_by_user.get(user_id, {})

    if relevant_entity_ids:
        entity_list = [
            entities[eid]
            for eid in relevant_entity_ids
            if eid in entities and entities[eid].is_current
        ]
    else:
        entity_list = [e for e in entities.values() if e.is_current]

    entity_list = entity_list[:max_entities]

    if entity_list:
        entity_strs = []
        for entity in entity_list:
            desc = f"{entity.name}"
            if entity.description:
                desc += f" ({entity.description})"
            entity_strs.append(desc)
        parts.append(f"Thông tin liên quan: {', '.join(entity_strs)}")

    rel_strs = []
    for rel in list(relations.values())[:max_relations]:
        source = entities.get(rel.source_id)
        target = entities.get(rel.target_id)
        if source and target:
            rel_strs.append(
                f"{source.name} → {rel.relation_type.value} → {target.name}"
            )
    if rel_strs:
        parts.append(f"Quan hệ: {'; '.join(rel_strs)}")

    return ". ".join(parts)


def to_dict_impl(
    *,
    user_id: str,
    entities_by_user,
    relations_by_user,
    episodes_by_user,
) -> dict[str, Any]:
    return {
        "entities": {
            eid: entity.to_dict()
            for eid, entity in entities_by_user.get(user_id, {}).items()
        },
        "relations": {
            rid: relation.to_dict()
            for rid, relation in relations_by_user.get(user_id, {}).items()
        },
        "episodes": {
            epid: episode.to_dict()
            for epid, episode in episodes_by_user.get(user_id, {}).items()
        },
    }


def from_dict_impl(
    *,
    user_id: str,
    data: dict[str, Any],
    entity_from_dict: Callable[[dict[str, Any]], Any],
    relation_from_dict: Callable[[dict[str, Any]], Any],
    episode_from_dict: Callable[[dict[str, Any]], Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    entities = {
        eid: entity_from_dict(e_data)
        for eid, e_data in data.get("entities", {}).items()
    }
    relations = {
        rid: relation_from_dict(r_data)
        for rid, r_data in data.get("relations", {}).items()
    }
    episodes = {
        epid: episode_from_dict(ep_data)
        for epid, ep_data in data.get("episodes", {}).items()
    }
    return entities, relations, episodes


async def extract_graph_from_facts_impl(
    *,
    user_id: str,
    facts: list[dict[str, Any]],
    session_id: Optional[str],
    get_temporal_graph_manager_fn: Callable[[], Any],
    temporal_graph_context_cls,
    entity_type_cls,
    relation_type_cls,
    logger_obj,
):
    start = time.time()
    manager = get_temporal_graph_manager_fn()

    entities = []
    relations = []

    fact_to_entity_type = {
        "name": entity_type_cls.PERSON,
        "age": entity_type_cls.FACT,
        "hometown": entity_type_cls.LOCATION,
        "role": entity_type_cls.FACT,
        "level": entity_type_cls.FACT,
        "location": entity_type_cls.LOCATION,
        "organization": entity_type_cls.FACT,
        "goal": entity_type_cls.PREFERENCE,
        "preference": entity_type_cls.PREFERENCE,
        "weakness": entity_type_cls.SKILL,
        "strength": entity_type_cls.SKILL,
        "learning_style": entity_type_cls.PREFERENCE,
        "hobby": entity_type_cls.PREFERENCE,
        "interest": entity_type_cls.CONCEPT,
        "emotion": entity_type_cls.FACT,
        "recent_topic": entity_type_cls.CONCEPT,
    }

    fact_to_relation_type = {
        "name": relation_type_cls.HAS_FACT,
        "goal": relation_type_cls.PREFERS,
        "preference": relation_type_cls.PREFERS,
        "weakness": relation_type_cls.WEAK_AT,
        "strength": relation_type_cls.STRONG_AT,
        "interest": relation_type_cls.STUDIES,
        "hometown": relation_type_cls.LOCATED_AT,
        "location": relation_type_cls.LOCATED_AT,
    }

    user_entity = manager.add_entity(
        user_id=user_id,
        name=user_id,
        entity_type=entity_type_cls.PERSON,
        description="User",
    )

    entity_ids = [user_entity.entity_id]
    relation_ids = []

    for fact in facts:
        fact_type = fact.get("fact_type", "")
        value = fact.get("value", "")
        confidence = fact.get("confidence", 0.8)

        if not value:
            continue

        entity_type = fact_to_entity_type.get(fact_type, entity_type_cls.FACT)
        relation_type = fact_to_relation_type.get(fact_type, relation_type_cls.HAS_FACT)

        entity = manager.add_entity(
            user_id=user_id,
            name=value,
            entity_type=entity_type,
            description=f"{fact_type}: {value}",
        )
        entities.append(entity)
        entity_ids.append(entity.entity_id)

        relation = manager.add_relation(
            user_id=user_id,
            source_id=user_entity.entity_id,
            target_id=entity.entity_id,
            relation_type=relation_type,
            confidence=confidence,
        )
        relations.append(relation)
        relation_ids.append(relation.relation_id)

    episode = manager.add_episode(
        user_id=user_id,
        session_id=session_id,
        summary=f"Extracted {len(facts)} facts from conversation",
        entity_ids=entity_ids,
        relation_ids=relation_ids,
    )

    total_time = (time.time() - start) * 1000
    context_text = manager.build_context_text(user_id, entity_ids)

    logger_obj.info(
        "[TGraph] Extracted %d entities, %d relations, 1 episode for user_hash=%s (%.0fms)",
        len(entities),
        len(relations),
        hash_memory_identifier(user_id),
        total_time,
    )

    return temporal_graph_context_cls(
        entities=entities,
        relations=relations,
        episodes=[episode],
        context_text=context_text,
        total_time_ms=total_time,
    )
