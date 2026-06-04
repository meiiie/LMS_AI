"""Runtime helpers for DenseSearchRepository CRUD operations."""

from __future__ import annotations

import json
import logging
from typing import List, Optional
from uuid import NAMESPACE_URL, uuid5

from app.services.embedding_shadow_vector_service import (
    build_shadow_embedding_async,
    build_shadow_metadata,
    filter_shadow_spaces,
)
from app.services.embedding_space_guard import get_active_embedding_space_contract
from app.services.embedding_space_registry_service import get_embedding_write_spaces
from app.repositories.knowledge_search_org_scope import (
    log_knowledge_search_scope_blocked,
    resolve_knowledge_search_org_scope,
)

logger = logging.getLogger(__name__)


def _embedding_to_pgvector(embedding: List[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


def _has_valid_embedding(embedding: List[float]) -> bool:
    return bool(embedding)


def _resolve_effective_org_id(
    organization_id: Optional[str],
    *,
    write: bool = False,
):
    return resolve_knowledge_search_org_scope(organization_id, write=write)


def _derive_storage_uuid(node_id: str) -> str:
    """Map legacy string node ids onto the current UUID-backed schema."""
    return str(uuid5(NAMESPACE_URL, f"knowledge-embedding:{node_id}"))


async def _resolve_storage_identity(repo, conn, node_id: str) -> tuple[str, str]:
    """Return the storage key column/value pair for current schema."""
    if await repo._has_column(conn, "knowledge_embeddings", "node_id"):
        return "node_id", node_id
    return "id", _derive_storage_uuid(node_id)


def _inject_legacy_node_id(metadata: dict | None, *, node_id: str, storage_key: str) -> str:
    from app.services.embedding_space_guard import stamp_embedding_metadata

    payload = stamp_embedding_metadata(metadata)
    if storage_key != "node_id" and node_id:
        payload.setdefault("legacy_node_id", node_id)
    return json.dumps(payload, ensure_ascii=False)


async def _resolve_inline_embedding_async(
    *,
    text_to_embed: str,
    embedding: List[float],
    write_spaces: tuple,
) -> tuple[List[float] | None, object | None]:
    inline_space = next(
        (space for space in write_spaces if space.storage_kind == "inline"),
        None,
    )
    if inline_space is None:
        return None, None

    source_contract = get_active_embedding_space_contract()
    try:
        resolved = await build_shadow_embedding_async(
            text_to_embed=text_to_embed,
            space=inline_space,
            source_embedding=embedding,
            source_contract=source_contract,
        )
        return resolved, inline_space
    except Exception as exc:
        logger.warning(
            "Inline knowledge embedding degraded to base-row-only for %s: %s",
            inline_space.space_fingerprint,
            exc,
        )
        return None, inline_space


async def _upsert_shadow_vector_async(
    conn,
    *,
    knowledge_embedding_id: str,
    text_to_embed: str,
    metadata: dict | None,
    source_embedding: List[float],
    space,
    precomputed_embedding: List[float] | None = None,
) -> None:
    if precomputed_embedding:
        shadow_embedding = precomputed_embedding
    else:
        source_contract = get_active_embedding_space_contract()
        shadow_embedding = await build_shadow_embedding_async(
            text_to_embed=text_to_embed,
            space=space,
            source_embedding=source_embedding,
            source_contract=source_contract,
        )
    await conn.execute(
        """
        INSERT INTO knowledge_embedding_vectors (
            knowledge_embedding_id,
            space_fingerprint,
            provider,
            model,
            dimensions,
            embedding,
            metadata,
            updated_at
        )
        VALUES ($1::uuid, $2, $3, $4, $5, $6::double precision[], $7::jsonb, NOW())
        ON CONFLICT (knowledge_embedding_id, space_fingerprint)
        DO UPDATE SET
            provider = EXCLUDED.provider,
            model = EXCLUDED.model,
            dimensions = EXCLUDED.dimensions,
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
        """,
        knowledge_embedding_id,
        space.space_fingerprint,
        space.provider,
        space.model,
        space.dimensions,
        shadow_embedding,
        build_shadow_metadata(metadata, contract=space),
    )


async def _write_shadow_vectors_async(
    conn,
    *,
    knowledge_embedding_id: str,
    text_to_embed: str,
    metadata: dict | None,
    source_embedding: List[float],
    write_spaces: tuple,
) -> None:
    for shadow_space in filter_shadow_spaces(write_spaces):
        try:
            await _upsert_shadow_vector_async(
                conn,
                knowledge_embedding_id=knowledge_embedding_id,
                text_to_embed=text_to_embed,
                metadata=metadata,
                source_embedding=source_embedding,
                space=shadow_space,
            )
        except Exception as exc:
            logger.warning(
                "Shadow knowledge embedding skipped for %s [%s]: %s",
                knowledge_embedding_id,
                shadow_space.space_fingerprint,
                exc,
            )


async def store_embedding_impl(repo, *, node_id: str, embedding: List[float], organization_id: Optional[str]) -> bool:
    if not repo._available:
        logger.warning("Dense search not available for storing")
        return False

    if not _has_valid_embedding(embedding):
        logger.error("Invalid embedding payload for node %s", node_id)
        return False

    scope = _resolve_effective_org_id(organization_id, write=True)
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(
            logger,
            "store_embedding",
            scope,
            node_id=node_id,
        )
        return False

    try:
        pool = await repo._get_pool()
        eff_org_id = scope.org_id
        write_spaces = get_embedding_write_spaces("knowledge_embeddings")
        source_contract = get_active_embedding_space_contract()

        async with pool.acquire() as conn:
            key_column, key_value = await _resolve_storage_identity(repo, conn, node_id)
            metadata_json = _inject_legacy_node_id(
                None,
                node_id=node_id,
                storage_key=key_column,
            )
            inline_space = next((space for space in write_spaces if space.storage_kind == "inline"), None)
            inline_embedding_str: str | None = None
            if (
                inline_space is not None
                and source_contract is not None
                and source_contract.fingerprint == inline_space.space_fingerprint
                and len(embedding) == inline_space.dimensions
            ):
                inline_embedding_str = _embedding_to_pgvector(embedding)
            if eff_org_id and await repo._has_column(conn, "knowledge_embeddings", "organization_id"):
                storage_id = await conn.fetchval(
                    f"""
                    INSERT INTO knowledge_embeddings ({key_column}, embedding, metadata, organization_id)
                    VALUES ($1, {('$2::vector' if inline_embedding_str else 'NULL')}, ${3 if inline_embedding_str else 2}::jsonb, ${4 if inline_embedding_str else 3})
                    ON CONFLICT ({key_column})
                    DO UPDATE SET
                        embedding = COALESCE(EXCLUDED.embedding, knowledge_embeddings.embedding),
                        metadata = EXCLUDED.metadata,
                        organization_id = COALESCE(EXCLUDED.organization_id, knowledge_embeddings.organization_id),
                        updated_at = NOW()
                    RETURNING id::text
                    """,
                    key_value,
                    *(
                        (inline_embedding_str, metadata_json, eff_org_id)
                        if inline_embedding_str
                        else (metadata_json, eff_org_id)
                    ),
                )
            else:
                storage_id = await conn.fetchval(
                    f"""
                    INSERT INTO knowledge_embeddings ({key_column}, embedding, metadata)
                    VALUES ($1, {('$2::vector' if inline_embedding_str else 'NULL')}, ${3 if inline_embedding_str else 2}::jsonb)
                    ON CONFLICT ({key_column})
                    DO UPDATE SET
                        embedding = COALESCE(EXCLUDED.embedding, knowledge_embeddings.embedding),
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    RETURNING id::text
                    """,
                    key_value,
                    *(
                        (inline_embedding_str, metadata_json)
                        if inline_embedding_str
                        else (metadata_json,)
                    ),
                )

            if storage_id:
                for shadow_space in filter_shadow_spaces(write_spaces):
                    if (
                        source_contract is None
                        or source_contract.fingerprint != shadow_space.space_fingerprint
                        or len(embedding) != shadow_space.dimensions
                    ):
                        logger.debug(
                            "Shadow write skipped for %s because content-free path cannot mint %s",
                            node_id,
                            shadow_space.space_fingerprint,
                        )
                        continue
                    await _upsert_shadow_vector_async(
                        conn,
                        knowledge_embedding_id=str(storage_id),
                        text_to_embed="",
                        metadata=None,
                        source_embedding=embedding,
                        space=shadow_space,
                        precomputed_embedding=list(embedding),
                    )

            logger.debug("Stored embedding for node: %s", node_id)
            return True
    except Exception as exc:
        logger.error("Failed to store embedding for %s: %s", node_id, exc)
        return False


async def upsert_embedding_impl(
    repo,
    *,
    node_id: str,
    content: str,
    embedding: List[float],
    organization_id: Optional[str],
) -> bool:
    if not repo._available:
        logger.warning("Dense search not available for storing")
        return False

    if not _has_valid_embedding(embedding):
        logger.error("Invalid embedding payload for node %s", node_id)
        return False

    scope = _resolve_effective_org_id(organization_id, write=True)
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(
            logger,
            "upsert_embedding",
            scope,
            node_id=node_id,
        )
        return False

    try:
        pool = await repo._get_pool()
        eff_org_id = scope.org_id
        write_spaces = get_embedding_write_spaces("knowledge_embeddings")

        async with pool.acquire() as conn:
            key_column, key_value = await _resolve_storage_identity(repo, conn, node_id)
            metadata_json = _inject_legacy_node_id(
                None,
                node_id=node_id,
                storage_key=key_column,
            )
            inline_embedding, _inline_space = await _resolve_inline_embedding_async(
                text_to_embed=content,
                embedding=embedding,
                write_spaces=write_spaces,
            )
            inline_embedding_str = (
                _embedding_to_pgvector(inline_embedding) if inline_embedding else None
            )
            if eff_org_id and await repo._has_column(conn, "knowledge_embeddings", "organization_id"):
                storage_id = await conn.fetchval(
                    f"""
                    INSERT INTO knowledge_embeddings ({key_column}, content, embedding, metadata, organization_id)
                    VALUES ($1, $2, {('$3::vector' if inline_embedding_str else 'NULL')}, ${4 if inline_embedding_str else 3}::jsonb, ${5 if inline_embedding_str else 4})
                    ON CONFLICT ({key_column})
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = COALESCE(EXCLUDED.embedding, knowledge_embeddings.embedding),
                        metadata = EXCLUDED.metadata,
                        organization_id = COALESCE(EXCLUDED.organization_id, knowledge_embeddings.organization_id),
                        updated_at = NOW()
                    RETURNING id::text
                    """,
                    key_value,
                    content[:500],
                    *(
                        (inline_embedding_str, metadata_json, eff_org_id)
                        if inline_embedding_str
                        else (metadata_json, eff_org_id)
                    ),
                )
            else:
                storage_id = await conn.fetchval(
                    f"""
                    INSERT INTO knowledge_embeddings ({key_column}, content, embedding, metadata)
                    VALUES ($1, $2, {('$3::vector' if inline_embedding_str else 'NULL')}, ${4 if inline_embedding_str else 3}::jsonb)
                    ON CONFLICT ({key_column})
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = COALESCE(EXCLUDED.embedding, knowledge_embeddings.embedding),
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    RETURNING id::text
                    """,
                    key_value,
                    content[:500],
                    *(
                        (inline_embedding_str, metadata_json)
                        if inline_embedding_str
                        else (metadata_json,)
                    ),
                )

            if storage_id:
                await _write_shadow_vectors_async(
                    conn,
                    knowledge_embedding_id=str(storage_id),
                    text_to_embed=content,
                    metadata=None,
                    source_embedding=embedding,
                    write_spaces=write_spaces,
                )

            logger.debug("Upserted embedding for node: %s", node_id)
            return True
    except Exception as exc:
        logger.error("Failed to upsert embedding for %s: %s", node_id, exc)
        return False


async def store_document_chunk_impl(
    repo,
    *,
    node_id: str,
    content: str,
    embedding: List[float],
    document_id: str,
    page_number: int,
    chunk_index: int,
    content_type: str,
    confidence_score: float,
    image_url: str,
    metadata: dict | None,
    organization_id: Optional[str],
    bounding_boxes: Optional[list],
) -> bool:
    if not repo._available:
        logger.warning("Dense search not available for storing")
        return False

    if not _has_valid_embedding(embedding):
        logger.error("Invalid embedding payload for node %s", node_id)
        return False

    scope = _resolve_effective_org_id(organization_id, write=True)
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(
            logger,
            "store_document_chunk",
            scope,
            node_id=node_id,
        )
        return False

    try:
        pool = await repo._get_pool()
        bounding_boxes_json = (
            json.dumps(bounding_boxes, ensure_ascii=False)
            if bounding_boxes
            else None
        )
        eff_org_id = scope.org_id
        write_spaces = get_embedding_write_spaces("knowledge_embeddings")

        async with pool.acquire() as conn:
            key_column, key_value = await _resolve_storage_identity(repo, conn, node_id)
            metadata_json = _inject_legacy_node_id(
                metadata,
                node_id=node_id,
                storage_key=key_column,
            )
            inline_embedding, _inline_space = await _resolve_inline_embedding_async(
                text_to_embed=content,
                embedding=embedding,
                write_spaces=write_spaces,
            )
            inline_embedding_str = (
                _embedding_to_pgvector(inline_embedding) if inline_embedding else None
            )
            has_org_column = bool(
                eff_org_id
                and await repo._has_column(conn, "knowledge_embeddings", "organization_id")
            )
            has_domain_column = await repo._has_column(
                conn,
                "knowledge_embeddings",
                "domain_id",
            )
            domain_id = metadata.get("domain_id") if isinstance(metadata, dict) else None

            columns = [
                key_column,
                "content",
                "embedding",
                "document_id",
                "page_number",
                "chunk_index",
                "content_type",
                "confidence_score",
                "image_url",
                "metadata",
            ]
            params: list[object] = [key_value, content[:2000]]
            values = ["$1", "$2"]
            if inline_embedding_str:
                params.append(inline_embedding_str)
                values.append("$3::vector")
            else:
                values.append("NULL")

            for value, cast_jsonb in (
                (document_id, False),
                (page_number, False),
                (chunk_index, False),
                (content_type, False),
                (confidence_score, False),
                (image_url, False),
                (metadata_json, True),
            ):
                params.append(value)
                placeholder = f"${len(params)}"
                if cast_jsonb:
                    placeholder += "::jsonb"
                values.append(placeholder)

            if has_org_column:
                columns.append("organization_id")
                params.append(eff_org_id)
                values.append(f"${len(params)}")

            if has_domain_column:
                columns.append("domain_id")
                params.append(domain_id)
                values.append(f"${len(params)}")

            columns.append("bounding_boxes")
            params.append(bounding_boxes_json)
            values.append(f"${len(params)}::jsonb")

            update_lines = [
                "content = EXCLUDED.content",
                "embedding = COALESCE(EXCLUDED.embedding, knowledge_embeddings.embedding)",
                "document_id = EXCLUDED.document_id",
                "page_number = EXCLUDED.page_number",
                "chunk_index = EXCLUDED.chunk_index",
                "content_type = EXCLUDED.content_type",
                "confidence_score = EXCLUDED.confidence_score",
                "image_url = EXCLUDED.image_url",
                "metadata = EXCLUDED.metadata",
            ]
            if has_org_column:
                update_lines.append(
                    "organization_id = COALESCE(EXCLUDED.organization_id, knowledge_embeddings.organization_id)"
                )
            if has_domain_column:
                update_lines.append(
                    "domain_id = COALESCE(EXCLUDED.domain_id, knowledge_embeddings.domain_id)"
                )
            update_lines.extend(
                [
                    "bounding_boxes = EXCLUDED.bounding_boxes",
                    "updated_at = NOW()",
                ]
            )

            storage_id = await conn.fetchval(
                f"""
                INSERT INTO knowledge_embeddings (
                    {", ".join(columns)}
                )
                VALUES ({", ".join(values)})
                ON CONFLICT ({key_column})
                DO UPDATE SET
                    {", ".join(update_lines)}
                RETURNING id::text
                """,
                *params,
            )

            if storage_id:
                await _write_shadow_vectors_async(
                    conn,
                    knowledge_embedding_id=str(storage_id),
                    text_to_embed=content,
                    metadata=metadata,
                    source_embedding=embedding,
                    write_spaces=write_spaces,
                )

            logger.debug(
                "Stored chunk: %s, type=%s, confidence=%s, page=%d",
                node_id,
                content_type,
                confidence_score,
                page_number,
            )
            return True
    except Exception as exc:
        logger.error("Failed to store chunk %s: %s", node_id, exc)
        return False


async def delete_embedding_impl(repo, *, node_id: str, organization_id: Optional[str]) -> bool:
    if not repo._available:
        logger.warning("Dense search not available for deletion")
        return False

    scope = _resolve_effective_org_id(organization_id, write=True)
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(
            logger,
            "delete_embedding",
            scope,
            node_id=node_id,
        )
        return False

    try:
        pool = await repo._get_pool()
        from app.core.org_filter import org_where_positional

        eff_org_id = scope.org_id
        async with pool.acquire() as conn:
            key_column, key_value = await _resolve_storage_identity(repo, conn, node_id)
            query = f"DELETE FROM knowledge_embeddings WHERE {key_column} = $1"
            params = [key_value]
            query += org_where_positional(eff_org_id, params, allow_null=True)
            result = await conn.execute(query, *params)
            deleted = int(result.split()[-1]) if result else 0
            logger.debug("Deleted %d embedding(s) for node: %s", deleted, node_id)
            return True
    except Exception as exc:
        logger.error("Failed to delete embedding for %s: %s", node_id, exc)
        return False


async def get_embedding_impl(repo, *, node_id: str, organization_id: Optional[str]) -> Optional[List[float]]:
    if not repo._available:
        return None

    scope = _resolve_effective_org_id(organization_id)
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(
            logger,
            "get_embedding",
            scope,
            node_id=node_id,
        )
        return None

    try:
        pool = await repo._get_pool()
        from app.core.org_filter import org_where_positional

        eff_org_id = scope.org_id
        active_space = get_embedding_write_spaces("knowledge_embeddings")[0] if get_embedding_write_spaces("knowledge_embeddings") else None
        async with pool.acquire() as conn:
            key_column, key_value = await _resolve_storage_identity(repo, conn, node_id)
            if active_space is not None and active_space.storage_kind == "shadow":
                query = f"""
                    SELECT kev.embedding
                    FROM knowledge_embeddings ke
                    JOIN knowledge_embedding_vectors kev
                      ON kev.knowledge_embedding_id = ke.id
                     AND kev.space_fingerprint = $2
                    WHERE ke.{key_column} = $1
                """
                params = [key_value, active_space.space_fingerprint]
                query += org_where_positional(eff_org_id, params, allow_null=True).replace(
                    "organization_id",
                    "ke.organization_id",
                )
            else:
                query = f"SELECT embedding FROM knowledge_embeddings WHERE {key_column} = $1"
                params = [key_value]
                query += org_where_positional(eff_org_id, params, allow_null=True)
            row = await conn.fetchrow(query, *params)
            if row and row["embedding"]:
                embedding_str = str(row["embedding"])
                values = embedding_str.strip("[]").split(",")
                return [float(value) for value in values]
            return None
    except Exception as exc:
        logger.error("Failed to get embedding for %s: %s", node_id, exc)
        return None


async def count_embeddings_impl(repo, *, organization_id: Optional[str]) -> int:
    if not repo._available:
        return 0

    scope = _resolve_effective_org_id(organization_id)
    if not scope.write_allowed or not scope.org_id:
        log_knowledge_search_scope_blocked(
            logger,
            "count_embeddings",
            scope,
        )
        return 0

    try:
        pool = await repo._get_pool()
        from app.core.org_filter import org_where_positional

        eff_org_id = scope.org_id
        async with pool.acquire() as conn:
            query = "SELECT COUNT(*) as count FROM knowledge_embeddings WHERE 1=1"
            params = []
            query += org_where_positional(eff_org_id, params, allow_null=True)
            row = await conn.fetchrow(query, *params)
            return row["count"] if row else 0
    except Exception as exc:
        logger.error("Failed to count embeddings: %s", exc)
        return 0


async def close_pool_impl(repo) -> None:
    if repo._pool:
        await repo._pool.close()
        repo._pool = None
        logger.info("Closed DenseSearchRepository connection pool")
