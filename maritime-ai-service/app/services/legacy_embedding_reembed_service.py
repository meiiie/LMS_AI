"""Batch re-embedding for legacy rows that predate embedding-space metadata."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text

from app.cache.invalidation import get_invalidation_manager
from app.core.database import get_shared_session_factory
from app.engine.embedding_runtime import get_embedding_backend
from app.services.embedding_space_guard import (
    build_embedding_space_contract,
    inspect_embedding_space_usage,
    stamp_embedding_metadata,
)

logger = logging.getLogger(__name__)

_TRACKED_FINGERPRINT_SQL = (
    "COALESCE("
    "metadata -> '_embedding_space' ->> 'fingerprint', "
    "metadata ->> 'embedding_space_fingerprint'"
    ")"
)
_SUPPORTED_TABLES = ("semantic_memories", "knowledge_embeddings")


@dataclass(frozen=True)
class LegacyEmbeddingRow:
    table_name: str
    row_id: str
    text_to_embed: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class LegacyEmbeddingTableResult:
    table_name: str
    scanned_rows: int
    updated_rows: int
    skipped_rows: int
    failed_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyEmbeddingReembedResult:
    dry_run: bool
    batch_size: int
    contract_fingerprint: str | None
    active_provider: str | None
    active_model: str | None
    tables: tuple[LegacyEmbeddingTableResult, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tables"] = [item.to_dict() for item in self.tables]
        return payload


def _format_pgvector(embedding: Sequence[float]) -> str:
    return "[" + ",".join(str(value) for value in embedding) + "]"


def _normalize_tables(tables: Iterable[str] | None) -> tuple[str, ...]:
    if tables is None:
        return _SUPPORTED_TABLES
    normalized: list[str] = []
    for table_name in tables:
        clean = (table_name or "").strip().lower()
        if clean in _SUPPORTED_TABLES and clean not in normalized:
            normalized.append(clean)
    return tuple(normalized)


def _fetch_legacy_rows(
    session,
    *,
    table_name: str,
    limit: int | None,
) -> list[LegacyEmbeddingRow]:
    if table_name == "semantic_memories":
        rows = session.execute(
            text(
                f"""
                SELECT id::text AS row_id, content AS text_to_embed, metadata
                FROM semantic_memories
                WHERE embedding IS NOT NULL
                  AND {_TRACKED_FINGERPRINT_SQL} IS NULL
                  AND NULLIF(TRIM(COALESCE(content, '')), '') IS NOT NULL
                ORDER BY updated_at ASC NULLS LAST, created_at ASC NULLS LAST, id ASC
                {f"LIMIT {int(limit)}" if limit else ""}
                """
            )
        ).fetchall()
    elif table_name == "knowledge_embeddings":
        rows = session.execute(
            text(
                f"""
                SELECT
                    id::text AS row_id,
                    COALESCE(NULLIF(TRIM(contextual_content), ''), NULLIF(TRIM(content), '')) AS text_to_embed,
                    metadata
                FROM knowledge_embeddings
                WHERE embedding IS NOT NULL
                  AND {_TRACKED_FINGERPRINT_SQL} IS NULL
                  AND COALESCE(NULLIF(TRIM(contextual_content), ''), NULLIF(TRIM(content), '')) IS NOT NULL
                ORDER BY updated_at ASC NULLS LAST, created_at ASC NULLS LAST, id ASC
                {f"LIMIT {int(limit)}" if limit else ""}
                """
            )
        ).fetchall()
    else:
        return []

    return [
        LegacyEmbeddingRow(
            table_name=table_name,
            row_id=str(row.row_id),
            text_to_embed=str(row.text_to_embed or ""),
            metadata=dict(row.metadata or {}),
        )
        for row in rows
        if row.text_to_embed
    ]


def _update_row_embedding(
    session,
    *,
    row: LegacyEmbeddingRow,
    embedding: Sequence[float],
    metadata: Mapping[str, Any],
) -> None:
    params = {
        "row_id": row.row_id,
        "embedding": _format_pgvector(embedding),
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }
    session.execute(
        text(
            f"""
            UPDATE {row.table_name}
            SET embedding = CAST(:embedding AS vector),
                metadata = CAST(:metadata AS jsonb),
                updated_at = NOW()
            WHERE id = CAST(:row_id AS uuid)
            """
        ),
        params,
    )


def _flush_embedding_version(version: str) -> None:
    try:
        coroutine = get_invalidation_manager().on_embeddings_refreshed(version, None)
        try:
            asyncio.run(coroutine)
        except RuntimeError:
            logger.debug("Embedding invalidation skipped because an event loop is already running")
    except Exception as exc:
        logger.warning("Failed to broadcast embedding refresh for %s: %s", version, exc)


def reembed_legacy_embedding_rows(
    *,
    dry_run: bool = True,
    batch_size: int = 16,
    limit_per_table: int | None = None,
    tables: Iterable[str] | None = None,
    acknowledge_maintenance_window: bool = False,
) -> LegacyEmbeddingReembedResult:
    if not dry_run and not acknowledge_maintenance_window:
        raise RuntimeError(
            "Maintenance window acknowledgement is required before applying legacy embedding re-embed."
        )

    backend = get_embedding_backend()
    active_backend = backend.active_backend if backend is not None else None
    contract = (
        build_embedding_space_contract(
            getattr(active_backend, "model_name", None),
            getattr(active_backend, "dimensions", None),
        )
        if active_backend is not None
        else None
    )
    if contract is None or active_backend is None:
        raise RuntimeError("Embedding backend hien tai chua san sang cho re-embed legacy rows.")

    session_factory = get_shared_session_factory()
    table_results: list[LegacyEmbeddingTableResult] = []
    warnings: list[str] = []

    normalized_tables = _normalize_tables(tables)
    if not normalized_tables:
        warnings.append("Khong co bang nao duoc chon cho re-embed.")

    for table_name in normalized_tables:
        scanned_rows = 0
        updated_rows = 0
        skipped_rows = 0
        failed_rows = 0

        with session_factory() as session:
            legacy_rows = _fetch_legacy_rows(
                session,
                table_name=table_name,
                limit=limit_per_table,
            )

        scanned_rows = len(legacy_rows)
        if scanned_rows == 0:
            table_results.append(
                LegacyEmbeddingTableResult(
                    table_name=table_name,
                    scanned_rows=0,
                    updated_rows=0,
                    skipped_rows=0,
                    failed_rows=0,
                )
            )
            continue

        for start in range(0, scanned_rows, max(1, batch_size)):
            batch = legacy_rows[start : start + max(1, batch_size)]
            texts = [row.text_to_embed for row in batch]
            try:
                embeddings = active_backend.embed_documents(texts)
            except Exception as exc:
                logger.warning(
                    "Legacy re-embed batch failed: table=%s offset=%s error=%s",
                    table_name,
                    start,
                    exc,
                )
                failed_rows += len(batch)
                continue
            if len(embeddings) != len(batch):
                failed_rows += len(batch)
                warnings.append(
                    f"Batch re-embed {table_name} bat dau tu offset {start} tra ve so embedding khong khop."
                )
                continue

            with session_factory() as session:
                for row, embedding in zip(batch, embeddings, strict=False):
                    if not embedding:
                        failed_rows += 1
                        continue
                    stamped_metadata = stamp_embedding_metadata(
                        row.metadata,
                        model_name=contract.model,
                        dimensions=contract.dimensions,
                    )
                    if dry_run:
                        skipped_rows += 1
                        continue
                    try:
                        _update_row_embedding(
                            session,
                            row=row,
                            embedding=embedding,
                            metadata=stamped_metadata,
                        )
                        updated_rows += 1
                    except Exception as exc:
                        logger.warning(
                            "Legacy re-embed failed: table=%s row_id=%s error=%s",
                            table_name,
                            row.row_id,
                            exc,
                        )
                        failed_rows += 1
                if not dry_run:
                    session.commit()

        table_results.append(
            LegacyEmbeddingTableResult(
                table_name=table_name,
                scanned_rows=scanned_rows,
                updated_rows=updated_rows,
                skipped_rows=skipped_rows,
                failed_rows=failed_rows,
            )
        )

    if not dry_run and contract is not None:
        _flush_embedding_version(contract.fingerprint)

    audit = inspect_embedding_space_usage(
        current_model=contract.model if contract else None,
        current_dimensions=contract.dimensions if contract else None,
    )
    warnings.extend(audit.warnings)
    return LegacyEmbeddingReembedResult(
        dry_run=dry_run,
        batch_size=batch_size,
        contract_fingerprint=contract.fingerprint if contract else None,
        active_provider=getattr(active_backend, "provider", None),
        active_model=getattr(active_backend, "model_name", None),
        tables=tuple(table_results),
        warnings=tuple(dict.fromkeys(warnings)),
    )
