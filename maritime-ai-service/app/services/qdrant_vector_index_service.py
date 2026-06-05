"""Qdrant sidecar index for active embedding shadow vectors.

PostgreSQL remains the source of truth. Qdrant stores only vectors and minimal
payload needed for ANN filtering; callers must fetch full records back from
Postgres before returning anything user-visible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import logging
import math
import re
import time
from typing import Any, Iterable, Literal, Mapping, Sequence

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_shared_session_factory
from app.services.embedding_space_registry_service import (
    EmbeddingEntityType,
    EmbeddingSpaceRegistryEntry,
    get_active_embedding_read_space,
)

logger = logging.getLogger(__name__)

QdrantEntityType = EmbeddingEntityType
QdrantDistance = Literal["Cosine"]

_COLLECTION_CACHE: set[tuple[str, str, int]] = set()
_DEGRADED_UNTIL = 0.0
_SUPPORTED_ENTITY_TYPES: tuple[QdrantEntityType, ...] = (
    "semantic_memories",
    "knowledge_embeddings",
)


@dataclass(frozen=True)
class QdrantSearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QdrantIndexRebuildResult:
    entity_type: str
    collection_name: str | None
    space_fingerprint: str | None
    indexed_points: int
    failed_points: int
    status: str
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_qdrant_enabled() -> bool:
    return (
        str(getattr(settings, "vector_index_backend", "postgres") or "postgres")
        .strip()
        .lower()
        == "qdrant"
        and bool(str(getattr(settings, "qdrant_url", "") or "").strip())
        and time.monotonic() >= _DEGRADED_UNTIL
    )


def _mark_qdrant_degraded(exc: Exception | str) -> None:
    global _DEGRADED_UNTIL
    cooldown = float(getattr(settings, "qdrant_failure_cooldown_seconds", 30.0) or 0.0)
    if cooldown <= 0:
        return
    _DEGRADED_UNTIL = time.monotonic() + cooldown
    logger.warning(
        "[QDRANT] Temporarily degraded for %.1fs; falling back to Postgres. reason=%s",
        cooldown,
        exc,
    )


def qdrant_headers() -> dict[str, str]:
    api_key = getattr(settings, "qdrant_api_key", None)
    return {"api-key": api_key} if api_key else {}


def qdrant_base_url() -> str:
    return str(getattr(settings, "qdrant_url", "http://localhost:6333")).rstrip("/")


def qdrant_timeout() -> float:
    return float(getattr(settings, "qdrant_timeout_seconds", 5.0) or 5.0)


def qdrant_search_oversample() -> int:
    return max(1, int(getattr(settings, "qdrant_search_oversample", 5) or 5))


def _normalize_entity_type(entity_type: str) -> QdrantEntityType:
    normalized = (entity_type or "").strip().lower()
    if normalized not in _SUPPORTED_ENTITY_TYPES:
        raise ValueError(f"Unsupported Qdrant entity_type: {entity_type}")
    return normalized  # type: ignore[return-value]


def _clean_collection_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value or "").strip("_")
    return cleaned or "wiii"


def build_qdrant_collection_name(
    entity_type: QdrantEntityType,
    space_fingerprint: str,
) -> str:
    entity = "semantic" if entity_type == "semantic_memories" else "knowledge"
    prefix = _clean_collection_component(str(getattr(settings, "qdrant_collection_prefix", "wiii")))
    digest = hashlib.sha1(space_fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{entity}_{digest}"


def _collection_cache_key(collection_name: str, dimensions: int) -> tuple[str, str, int]:
    return (qdrant_base_url(), collection_name, int(dimensions))


def _extract_collection_vector_size(payload: Mapping[str, Any]) -> int | None:
    try:
        vectors = payload["result"]["config"]["params"]["vectors"]
        if isinstance(vectors, Mapping):
            if "size" in vectors:
                return int(vectors["size"])
            default_vector = vectors.get("")
            if isinstance(default_vector, Mapping) and "size" in default_vector:
                return int(default_vector["size"])
    except Exception:
        return None
    return None


def ensure_qdrant_collection_sync(
    entity_type: QdrantEntityType,
    space: EmbeddingSpaceRegistryEntry,
    *,
    distance: QdrantDistance = "Cosine",
) -> str | None:
    if not is_qdrant_enabled():
        return None
    collection_name = build_qdrant_collection_name(entity_type, space.space_fingerprint)
    cache_key = _collection_cache_key(collection_name, space.dimensions)
    if cache_key in _COLLECTION_CACHE:
        return collection_name

    url = f"{qdrant_base_url()}/collections/{collection_name}"
    headers = qdrant_headers()
    timeout = qdrant_timeout()
    try:
        response = httpx.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            vector_size = _extract_collection_vector_size(response.json())
            if vector_size is not None and vector_size != int(space.dimensions):
                logger.warning(
                    "[QDRANT] Collection %s has %sd vectors, expected %sd",
                    collection_name,
                    vector_size,
                    space.dimensions,
                )
                return None
            _COLLECTION_CACHE.add(cache_key)
            return collection_name
        if response.status_code != 404:
            logger.warning(
                "[QDRANT] Collection probe failed: collection=%s status=%s body=%s",
                collection_name,
                response.status_code,
                response.text[:300],
            )
            _mark_qdrant_degraded(f"collection probe status {response.status_code}")
            return None

        create_response = httpx.put(
            url,
            headers=headers,
            timeout=timeout,
            json={"vectors": {"size": int(space.dimensions), "distance": distance}},
        )
        create_response.raise_for_status()
        _COLLECTION_CACHE.add(cache_key)
        logger.info(
            "[QDRANT] Created collection %s for %s %s",
            collection_name,
            entity_type,
            space.space_fingerprint,
        )
        return collection_name
    except Exception as exc:
        logger.warning("[QDRANT] Collection ensure failed for %s: %s", collection_name, exc)
        _mark_qdrant_degraded(exc)
        return None


async def ensure_qdrant_collection_async(
    entity_type: QdrantEntityType,
    space: EmbeddingSpaceRegistryEntry,
    *,
    distance: QdrantDistance = "Cosine",
) -> str | None:
    if not is_qdrant_enabled():
        return None
    collection_name = build_qdrant_collection_name(entity_type, space.space_fingerprint)
    cache_key = _collection_cache_key(collection_name, space.dimensions)
    if cache_key in _COLLECTION_CACHE:
        return collection_name

    url = f"{qdrant_base_url()}/collections/{collection_name}"
    headers = qdrant_headers()
    timeout = qdrant_timeout()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                vector_size = _extract_collection_vector_size(response.json())
                if vector_size is not None and vector_size != int(space.dimensions):
                    logger.warning(
                        "[QDRANT] Collection %s has %sd vectors, expected %sd",
                        collection_name,
                        vector_size,
                        space.dimensions,
                    )
                    return None
                _COLLECTION_CACHE.add(cache_key)
                return collection_name
            if response.status_code != 404:
                logger.warning(
                    "[QDRANT] Collection probe failed: collection=%s status=%s body=%s",
                    collection_name,
                    response.status_code,
                    response.text[:300],
                )
                _mark_qdrant_degraded(f"collection probe status {response.status_code}")
                return None

            create_response = await client.put(
                url,
                headers=headers,
                json={"vectors": {"size": int(space.dimensions), "distance": distance}},
            )
            create_response.raise_for_status()
        _COLLECTION_CACHE.add(cache_key)
        logger.info(
            "[QDRANT] Created collection %s for %s %s",
            collection_name,
            entity_type,
            space.space_fingerprint,
        )
        return collection_name
    except Exception as exc:
        logger.warning("[QDRANT] Collection ensure failed for %s: %s", collection_name, exc)
        _mark_qdrant_degraded(exc)
        return None


def _strip_none(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value is not None}


def build_qdrant_payload(
    *,
    entity_type: QdrantEntityType,
    point_id: str,
    space: EmbeddingSpaceRegistryEntry,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entity_key = "memory_id" if entity_type == "semantic_memories" else "knowledge_embedding_id"
    base_payload = {
        "entity_type": entity_type,
        entity_key: point_id,
        "space_fingerprint": space.space_fingerprint,
        "provider": space.provider,
        "model": space.model,
        "dimensions": int(space.dimensions),
    }
    base_payload.update(dict(payload or {}))
    return _strip_none(base_payload)


def _coerce_vector(embedding: Sequence[float] | str | None) -> list[float]:
    if embedding is None:
        return []
    if isinstance(embedding, str):
        raw = embedding.strip().strip("{}[]")
        if not raw:
            return []
        return [float(value) for value in raw.split(",") if value.strip()]
    return [float(value) for value in embedding]


def _valid_vector(embedding: Sequence[float], dimensions: int) -> bool:
    if len(embedding) != int(dimensions):
        return False
    return not any(math.isnan(float(value)) or math.isinf(float(value)) for value in embedding)


def upsert_qdrant_points_sync(
    *,
    entity_type: QdrantEntityType,
    space: EmbeddingSpaceRegistryEntry,
    points: Sequence[tuple[str, Sequence[float], Mapping[str, Any] | None]],
) -> bool:
    normalized = _normalize_entity_type(entity_type)
    if not points or not is_qdrant_enabled():
        return False
    collection_name = ensure_qdrant_collection_sync(normalized, space)
    if not collection_name:
        return False

    qdrant_points: list[dict[str, Any]] = []
    for point_id, embedding, payload in points:
        vector = list(embedding)
        if not _valid_vector(vector, space.dimensions):
            logger.warning(
                "[QDRANT] Skipping invalid vector for %s point %s",
                normalized,
                point_id,
            )
            continue
        qdrant_points.append(
            {
                "id": str(point_id),
                "vector": vector,
                "payload": build_qdrant_payload(
                    entity_type=normalized,
                    point_id=str(point_id),
                    space=space,
                    payload=payload,
                ),
            }
        )
    if not qdrant_points:
        return False

    try:
        response = httpx.put(
            f"{qdrant_base_url()}/collections/{collection_name}/points",
            params={"wait": "true"},
            headers=qdrant_headers(),
            timeout=qdrant_timeout(),
            json={"points": qdrant_points},
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("[QDRANT] Upsert failed for %s: %s", collection_name, exc)
        _mark_qdrant_degraded(exc)
        return False


async def upsert_qdrant_points_async(
    *,
    entity_type: QdrantEntityType,
    space: EmbeddingSpaceRegistryEntry,
    points: Sequence[tuple[str, Sequence[float], Mapping[str, Any] | None]],
) -> bool:
    normalized = _normalize_entity_type(entity_type)
    if not points or not is_qdrant_enabled():
        return False
    collection_name = await ensure_qdrant_collection_async(normalized, space)
    if not collection_name:
        return False

    qdrant_points: list[dict[str, Any]] = []
    for point_id, embedding, payload in points:
        vector = list(embedding)
        if not _valid_vector(vector, space.dimensions):
            logger.warning(
                "[QDRANT] Skipping invalid vector for %s point %s",
                normalized,
                point_id,
            )
            continue
        qdrant_points.append(
            {
                "id": str(point_id),
                "vector": vector,
                "payload": build_qdrant_payload(
                    entity_type=normalized,
                    point_id=str(point_id),
                    space=space,
                    payload=payload,
                ),
            }
        )
    if not qdrant_points:
        return False

    try:
        async with httpx.AsyncClient(timeout=qdrant_timeout()) as client:
            response = await client.put(
                f"{qdrant_base_url()}/collections/{collection_name}/points",
                params={"wait": "true"},
                headers=qdrant_headers(),
                json={"points": qdrant_points},
            )
            response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("[QDRANT] Upsert failed for %s: %s", collection_name, exc)
        _mark_qdrant_degraded(exc)
        return False


def _qdrant_condition(key: str, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if "gte" in value or "lte" in value or "gt" in value or "lt" in value:
            return {"key": key, "range": dict(value)}
        return None
    if isinstance(value, (list, tuple, set)):
        values = [item for item in value if item is not None]
        if not values:
            return None
        return {"key": key, "match": {"any": values}}
    return {"key": key, "match": {"value": value}}


def build_qdrant_filter(filters: Mapping[str, Any] | None) -> dict[str, Any] | None:
    must = [
        condition
        for key, value in dict(filters or {}).items()
        if (condition := _qdrant_condition(key, value)) is not None
    ]
    return {"must": must} if must else None


def _parse_qdrant_hits(payload: Mapping[str, Any]) -> list[QdrantSearchHit]:
    hits: list[QdrantSearchHit] = []
    for item in payload.get("result") or []:
        try:
            point_id = str(item.get("id"))
            if not point_id:
                continue
            score = float(item.get("score") or 0.0)
            if math.isnan(score) or math.isinf(score):
                score = 0.0
            hits.append(
                QdrantSearchHit(
                    point_id=point_id,
                    score=max(0.0, min(1.0, score)),
                    payload=dict(item.get("payload") or {}),
                )
            )
        except Exception:
            continue
    return hits


def search_qdrant_sync(
    *,
    entity_type: QdrantEntityType,
    space: EmbeddingSpaceRegistryEntry,
    query_embedding: Sequence[float],
    limit: int,
    score_threshold: float | None = None,
    filters: Mapping[str, Any] | None = None,
    oversample: int | None = None,
) -> list[QdrantSearchHit]:
    normalized = _normalize_entity_type(entity_type)
    if not is_qdrant_enabled() or space.storage_kind != "shadow":
        return []
    query_vector = list(query_embedding)
    if not _valid_vector(query_vector, space.dimensions):
        return []
    collection_name = ensure_qdrant_collection_sync(normalized, space)
    if not collection_name:
        return []

    qdrant_filter = build_qdrant_filter(
        {
            "space_fingerprint": space.space_fingerprint,
            "dimensions": int(space.dimensions),
            **dict(filters or {}),
        }
    )
    body: dict[str, Any] = {
        "vector": query_vector,
        "limit": max(1, int(limit)) * max(1, int(oversample or qdrant_search_oversample())),
        "with_payload": True,
        "with_vector": False,
    }
    if score_threshold is not None:
        body["score_threshold"] = float(score_threshold)
    if qdrant_filter:
        body["filter"] = qdrant_filter

    try:
        response = httpx.post(
            f"{qdrant_base_url()}/collections/{collection_name}/points/search",
            headers=qdrant_headers(),
            timeout=qdrant_timeout(),
            json=body,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return _parse_qdrant_hits(response.json())
    except Exception as exc:
        logger.warning("[QDRANT] Search failed for %s: %s", collection_name, exc)
        _mark_qdrant_degraded(exc)
        return []


async def search_qdrant_async(
    *,
    entity_type: QdrantEntityType,
    space: EmbeddingSpaceRegistryEntry,
    query_embedding: Sequence[float],
    limit: int,
    score_threshold: float | None = None,
    filters: Mapping[str, Any] | None = None,
    oversample: int | None = None,
) -> list[QdrantSearchHit]:
    normalized = _normalize_entity_type(entity_type)
    if not is_qdrant_enabled() or space.storage_kind != "shadow":
        return []
    query_vector = list(query_embedding)
    if not _valid_vector(query_vector, space.dimensions):
        return []
    collection_name = await ensure_qdrant_collection_async(normalized, space)
    if not collection_name:
        return []

    qdrant_filter = build_qdrant_filter(
        {
            "space_fingerprint": space.space_fingerprint,
            "dimensions": int(space.dimensions),
            **dict(filters or {}),
        }
    )
    body: dict[str, Any] = {
        "vector": query_vector,
        "limit": max(1, int(limit)) * max(1, int(oversample or qdrant_search_oversample())),
        "with_payload": True,
        "with_vector": False,
    }
    if score_threshold is not None:
        body["score_threshold"] = float(score_threshold)
    if qdrant_filter:
        body["filter"] = qdrant_filter

    try:
        async with httpx.AsyncClient(timeout=qdrant_timeout()) as client:
            response = await client.post(
                f"{qdrant_base_url()}/collections/{collection_name}/points/search",
                headers=qdrant_headers(),
                json=body,
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return _parse_qdrant_hits(response.json())
    except Exception as exc:
        logger.warning("[QDRANT] Search failed for %s: %s", collection_name, exc)
        _mark_qdrant_degraded(exc)
        return []


def _semantic_rebuild_rows_sql() -> str:
    return """
        SELECT
            sm.id::text AS point_id,
            sm.user_id,
            sm.organization_id,
            sm.memory_type,
            smv.embedding
        FROM semantic_memory_vectors smv
        JOIN semantic_memories sm ON sm.id = smv.memory_id
        WHERE smv.space_fingerprint = :space_fingerprint
          AND smv.dimensions = :dimensions
        ORDER BY smv.updated_at ASC NULLS LAST, smv.created_at ASC NULLS LAST, smv.memory_id ASC
    """


def _knowledge_rebuild_rows_sql(*, has_domain_id: bool) -> str:
    domain_expr = "ke.domain_id" if has_domain_id else "NULL AS domain_id"
    return f"""
        SELECT
            ke.id::text AS point_id,
            ke.organization_id,
            ke.content_type,
            ke.confidence_score,
            {domain_expr},
            kev.embedding
        FROM knowledge_embedding_vectors kev
        JOIN knowledge_embeddings ke ON ke.id = kev.knowledge_embedding_id
        WHERE kev.space_fingerprint = :space_fingerprint
          AND kev.dimensions = :dimensions
        ORDER BY kev.updated_at ASC NULLS LAST, kev.created_at ASC NULLS LAST, kev.knowledge_embedding_id ASC
    """


def _table_has_column(session, table_name: str, column_name: str) -> bool:
    return bool(
        session.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                      AND column_name = :column_name
                )
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar()
    )


def _row_payload(entity_type: QdrantEntityType, row) -> dict[str, Any]:
    if entity_type == "semantic_memories":
        return _strip_none(
            {
                "user_id": row.user_id,
                "organization_id": row.organization_id,
                "memory_type": row.memory_type,
            }
        )
    return _strip_none(
        {
            "organization_id": row.organization_id,
            "content_type": row.content_type,
            "confidence_score": float(row.confidence_score) if row.confidence_score is not None else None,
            "domain_id": getattr(row, "domain_id", None),
        }
    )


def rebuild_qdrant_index_for_active_spaces(
    *,
    entity_types: Iterable[str] | None = None,
    batch_size: int | None = None,
) -> tuple[QdrantIndexRebuildResult, ...]:
    """Rebuild Qdrant from active shadow-vector rows.

    This is idempotent. It never mutates Postgres data.
    """
    targets = tuple(_normalize_entity_type(item) for item in (entity_types or _SUPPORTED_ENTITY_TYPES))
    resolved_batch_size = max(
        1,
        int(batch_size or getattr(settings, "qdrant_upsert_batch_size", 64) or 64),
    )
    results: list[QdrantIndexRebuildResult] = []

    if not is_qdrant_enabled():
        return tuple(
            QdrantIndexRebuildResult(
                entity_type=entity_type,
                collection_name=None,
                space_fingerprint=None,
                indexed_points=0,
                failed_points=0,
                status="skipped",
                detail="vector_index_backend is not qdrant",
            )
            for entity_type in targets
        )

    session_factory = get_shared_session_factory()
    for entity_type in targets:
        space = get_active_embedding_read_space(entity_type, force_refresh=True)
        if space is None or space.storage_kind != "shadow":
            results.append(
                QdrantIndexRebuildResult(
                    entity_type=entity_type,
                    collection_name=None,
                    space_fingerprint=space.space_fingerprint if space else None,
                    indexed_points=0,
                    failed_points=0,
                    status="skipped",
                    detail="active embedding space is not a shadow-vector space",
                )
            )
            continue

        collection_name = ensure_qdrant_collection_sync(entity_type, space)
        if not collection_name:
            results.append(
                QdrantIndexRebuildResult(
                    entity_type=entity_type,
                    collection_name=None,
                    space_fingerprint=space.space_fingerprint,
                    indexed_points=0,
                    failed_points=0,
                    status="error",
                    detail="could not create or verify Qdrant collection",
                )
            )
            continue

        indexed_points = 0
        failed_points = 0
        try:
            with session_factory() as session:
                if entity_type == "semantic_memories":
                    rows = session.execute(
                        text(_semantic_rebuild_rows_sql()),
                        {
                            "space_fingerprint": space.space_fingerprint,
                            "dimensions": space.dimensions,
                        },
                    ).fetchall()
                else:
                    rows = session.execute(
                        text(
                            _knowledge_rebuild_rows_sql(
                                has_domain_id=_table_has_column(
                                    session,
                                    "knowledge_embeddings",
                                    "domain_id",
                                )
                            )
                        ),
                        {
                            "space_fingerprint": space.space_fingerprint,
                            "dimensions": space.dimensions,
                        },
                    ).fetchall()
        except Exception as exc:
            results.append(
                QdrantIndexRebuildResult(
                    entity_type=entity_type,
                    collection_name=collection_name,
                    space_fingerprint=space.space_fingerprint,
                    indexed_points=0,
                    failed_points=0,
                    status="error",
                    detail=f"failed to read shadow vectors: {exc}",
                )
            )
            continue

        for start in range(0, len(rows), resolved_batch_size):
            batch = rows[start : start + resolved_batch_size]
            points: list[tuple[str, Sequence[float], Mapping[str, Any] | None]] = []
            for row in batch:
                vector = _coerce_vector(row.embedding)
                if not _valid_vector(vector, space.dimensions):
                    failed_points += 1
                    continue
                points.append((str(row.point_id), vector, _row_payload(entity_type, row)))
            if not points:
                continue
            if upsert_qdrant_points_sync(entity_type=entity_type, space=space, points=points):
                indexed_points += len(points)
            else:
                failed_points += len(points)

        results.append(
            QdrantIndexRebuildResult(
                entity_type=entity_type,
                collection_name=collection_name,
                space_fingerprint=space.space_fingerprint,
                indexed_points=indexed_points,
                failed_points=failed_points,
                status="ok" if failed_points == 0 else "partial",
            )
        )

    return tuple(results)
