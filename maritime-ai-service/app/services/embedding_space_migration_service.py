"""Planning and controlled execution for full embedding-space migrations."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text

from app.cache.invalidation import get_invalidation_manager
from app.core.database import get_shared_session_factory
from app.engine.embedding_runtime import (
    build_embedding_backend_for_provider_model,
    reset_embedding_backend,
)
from app.services.embedding_selectability_service import invalidate_embedding_selectability_cache
from app.services.embedding_shadow_vector_service import format_pg_array_literal
from app.services.embedding_shadow_index_service import ensure_shadow_vector_indexes
from app.services.embedding_space_guard import (
    EmbeddingSpaceAudit,
    EmbeddingSpaceContract,
    EmbeddingSpaceTableAudit,
    build_embedding_space_contract,
    get_active_embedding_space_contract,
    get_runtime_embedding_space_contract,
    inspect_embedding_space_usage,
    stamp_embedding_metadata,
    validate_embedding_space_transition_with_audit,
)
from app.services.embedding_space_registry_service import (
    prepare_shadow_embedding_space,
    promote_shadow_embedding_space,
)
from app.services.llm_runtime_policy_service import (
    apply_llm_runtime_policy_snapshot,
    persist_current_llm_runtime_policy,
    snapshot_current_llm_runtime_policy,
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
class EmbeddingSpaceMigrationTablePlan:
    table_name: str
    candidate_rows: int
    embedded_rows: int
    tracked_rows: int
    untracked_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmbeddingSpaceMigrationPlan:
    current_contract_fingerprint: str | None
    target_contract_fingerprint: str | None
    current_contract_label: str | None
    target_contract_label: str | None
    same_space: bool
    transition_allowed: bool
    target_backend_constructible: bool
    maintenance_required: bool
    total_candidate_rows: int
    total_embedded_rows: int
    tables: tuple[EmbeddingSpaceMigrationTablePlan, ...]
    warnings: tuple[str, ...] = ()
    detail: str | None = None
    recommended_steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tables"] = [item.to_dict() for item in self.tables]
        return payload


@dataclass(frozen=True)
class EmbeddingSpaceMigrationTableResult:
    table_name: str
    candidate_rows: int
    updated_rows: int
    skipped_rows: int
    failed_rows: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmbeddingSpaceMigrationResult:
    dry_run: bool
    maintenance_acknowledged: bool
    current_contract_fingerprint: str | None
    target_contract_fingerprint: str | None
    target_backend_constructible: bool
    tables: tuple[EmbeddingSpaceMigrationTableResult, ...]
    warnings: tuple[str, ...] = ()
    detail: str | None = None
    recommended_next_steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tables"] = [item.to_dict() for item in self.tables]
        return payload


@dataclass(frozen=True)
class _MigrationRow:
    table_name: str
    row_id: str
    text_to_embed: str
    metadata: dict[str, Any]


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


def _count_candidate_rows(session, *, table_name: str, fingerprint: str | None) -> int:
    if not fingerprint:
        return 0
    if table_name == "semantic_memories":
        sql = text(
            f"""
            SELECT COUNT(*)
            FROM semantic_memories
            WHERE embedding IS NOT NULL
              AND {_TRACKED_FINGERPRINT_SQL} = :fingerprint
              AND NULLIF(TRIM(COALESCE(content, '')), '') IS NOT NULL
            """
        )
    elif table_name == "knowledge_embeddings":
        sql = text(
            f"""
            SELECT COUNT(*)
            FROM knowledge_embeddings
            WHERE embedding IS NOT NULL
              AND {_TRACKED_FINGERPRINT_SQL} = :fingerprint
              AND COALESCE(NULLIF(TRIM(contextual_content), ''), NULLIF(TRIM(content), '')) IS NOT NULL
            """
        )
    else:
        return 0
    return int(session.execute(sql, {"fingerprint": fingerprint}).scalar() or 0)


def _fetch_candidate_rows(
    session,
    *,
    table_name: str,
    fingerprint: str | None,
    limit: int | None,
) -> list[_MigrationRow]:
    if not fingerprint:
        return []
    if table_name == "semantic_memories":
        sql = text(
            f"""
            SELECT id::text AS row_id, content AS text_to_embed, metadata
            FROM semantic_memories
            WHERE embedding IS NOT NULL
              AND {_TRACKED_FINGERPRINT_SQL} = :fingerprint
              AND NULLIF(TRIM(COALESCE(content, '')), '') IS NOT NULL
            ORDER BY updated_at ASC NULLS LAST, created_at ASC NULLS LAST, id ASC
            {f"LIMIT {int(limit)}" if limit else ""}
            """
        )
    elif table_name == "knowledge_embeddings":
        sql = text(
            f"""
            SELECT
                id::text AS row_id,
                COALESCE(NULLIF(TRIM(contextual_content), ''), NULLIF(TRIM(content), '')) AS text_to_embed,
                metadata
            FROM knowledge_embeddings
            WHERE embedding IS NOT NULL
              AND {_TRACKED_FINGERPRINT_SQL} = :fingerprint
              AND COALESCE(NULLIF(TRIM(contextual_content), ''), NULLIF(TRIM(content), '')) IS NOT NULL
            ORDER BY updated_at ASC NULLS LAST, created_at ASC NULLS LAST, id ASC
            {f"LIMIT {int(limit)}" if limit else ""}
            """
        )
    else:
        return []

    rows = session.execute(sql, {"fingerprint": fingerprint}).fetchall()
    return [
        _MigrationRow(
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
    row: _MigrationRow,
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


def _shadow_vector_table(table_name: str) -> tuple[str, str]:
    if table_name == "semantic_memories":
        return "semantic_memory_vectors", "memory_id"
    if table_name == "knowledge_embeddings":
        return "knowledge_embedding_vectors", "knowledge_embedding_id"
    raise ValueError(f"Unsupported shadow vector table for {table_name}")


def _upsert_shadow_row_embedding(
    session,
    *,
    row: _MigrationRow,
    target_contract: EmbeddingSpaceContract,
    embedding: Sequence[float],
    metadata: Mapping[str, Any],
) -> None:
    vector_table, fk_column = _shadow_vector_table(row.table_name)
    session.execute(
        text(
            f"""
            INSERT INTO {vector_table} (
                {fk_column},
                space_fingerprint,
                provider,
                model,
                dimensions,
                embedding,
                metadata,
                updated_at
            )
            VALUES (
                CAST(:row_id AS uuid),
                :space_fingerprint,
                :provider,
                :model,
                :dimensions,
                CAST(:embedding AS double precision[]),
                CAST(:metadata AS jsonb),
                NOW()
            )
            ON CONFLICT ({fk_column}, space_fingerprint)
            DO UPDATE SET
                provider = EXCLUDED.provider,
                model = EXCLUDED.model,
                dimensions = EXCLUDED.dimensions,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """
        ),
        {
            "row_id": row.row_id,
            "space_fingerprint": target_contract.fingerprint,
            "provider": target_contract.provider,
            "model": target_contract.model,
            "dimensions": target_contract.dimensions,
            "embedding": format_pg_array_literal(embedding),
            "metadata": json.dumps(metadata, ensure_ascii=False),
        },
    )


def _flush_embedding_version(version: str | None) -> None:
    if not version:
        return
    try:
        coroutine = get_invalidation_manager().on_embeddings_refreshed(version, None)
        try:
            asyncio.run(coroutine)
        except RuntimeError:
            logger.debug("Embedding invalidation skipped because an event loop is already running")
    except Exception as exc:
        logger.warning("Failed to broadcast embedding refresh for %s: %s", version, exc)


def _current_contract() -> EmbeddingSpaceContract | None:
    return get_active_embedding_space_contract() or get_runtime_embedding_space_contract()


def _build_plan_tables(
    *,
    audit: EmbeddingSpaceAudit | None,
    fingerprint: str | None,
    tables: tuple[str, ...],
) -> tuple[EmbeddingSpaceMigrationTablePlan, ...]:
    audit_by_name = {table.table_name: table for table in (audit.tables if audit else ())}
    if not fingerprint:
        return tuple(
            EmbeddingSpaceMigrationTablePlan(
                table_name=table_name,
                candidate_rows=0,
                embedded_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).embedded_row_count,
                tracked_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).tracked_row_count,
                untracked_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).untracked_row_count,
            )
            for table_name in tables
        )
    if audit is not None and not audit.audit_available:
        return tuple(
            EmbeddingSpaceMigrationTablePlan(
                table_name=table_name,
                candidate_rows=0,
                embedded_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).embedded_row_count,
                tracked_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).tracked_row_count,
                untracked_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).untracked_row_count,
            )
            for table_name in tables
        )
    session_factory = get_shared_session_factory()
    plans: list[EmbeddingSpaceMigrationTablePlan] = []
    with session_factory() as session:
        for table_name in tables:
            audit_table = audit_by_name.get(
                table_name,
                EmbeddingSpaceTableAudit(
                    table_name=table_name,
                    embedded_row_count=0,
                    tracked_row_count=0,
                    untracked_row_count=0,
                    fingerprints={},
                ),
            )
            candidate_rows = _count_candidate_rows(
                session,
                table_name=table_name,
                fingerprint=fingerprint,
            )
            plans.append(
                EmbeddingSpaceMigrationTablePlan(
                    table_name=table_name,
                    candidate_rows=candidate_rows,
                    embedded_rows=audit_table.embedded_row_count,
                    tracked_rows=audit_table.tracked_row_count,
                    untracked_rows=audit_table.untracked_row_count,
                )
            )
    return tuple(plans)


def plan_embedding_space_migration(
    *,
    target_model: str,
    target_dimensions: int | None = None,
    tables: Iterable[str] | None = None,
) -> EmbeddingSpaceMigrationPlan:
    current_contract = _current_contract()
    target_contract = build_embedding_space_contract(target_model, target_dimensions)
    if target_contract is None:
        raise RuntimeError("Target embedding model khong hop le cho migration plan.")

    audit = (
        inspect_embedding_space_usage(
            current_model=current_contract.model,
            current_dimensions=current_contract.dimensions,
        )
        if current_contract is not None
        else None
    )
    transition = validate_embedding_space_transition_with_audit(
        current_contract=current_contract,
        target_contract=target_contract,
        audit=audit,
    )
    normalized_tables = _normalize_tables(tables)
    audit_available = bool(audit is None or audit.audit_available)
    table_probe_error: str | None = None
    try:
        plan_tables = _build_plan_tables(
            audit=audit,
            fingerprint=current_contract.fingerprint if current_contract else None,
            tables=normalized_tables,
        )
    except Exception as exc:
        logger.warning("Embedding-space migration planner could not inspect candidate rows: %s", exc)
        table_probe_error = str(exc)
        audit_by_name = {table.table_name: table for table in (audit.tables if audit else ())}
        plan_tables = tuple(
            EmbeddingSpaceMigrationTablePlan(
                table_name=table_name,
                candidate_rows=0,
                embedded_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).embedded_row_count,
                tracked_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).tracked_row_count,
                untracked_rows=audit_by_name.get(
                    table_name,
                    EmbeddingSpaceTableAudit(
                        table_name=table_name,
                        embedded_row_count=0,
                        tracked_row_count=0,
                        untracked_row_count=0,
                        fingerprints={},
                    ),
                ).untracked_row_count,
            )
            for table_name in normalized_tables
        )
        audit_available = False
    total_candidate_rows = sum(item.candidate_rows for item in plan_tables)
    total_embedded_rows = audit.total_embedded_rows if audit else 0
    target_backend_constructible = (
        build_embedding_backend_for_provider_model(
            target_contract.provider,
            target_contract.model,
            dimensions=target_contract.dimensions,
        )
        is not None
    )
    zero_downtime_shadow_supported = (
        current_contract is None
        or current_contract.fingerprint == target_contract.fingerprint
        or target_backend_constructible
    )
    transition_allowed = transition.allowed
    if current_contract is not None and current_contract.fingerprint != target_contract.fingerprint:
        transition_allowed = bool(audit_available and zero_downtime_shadow_supported)
    maintenance_required = False
    warnings = list(transition.warnings)
    if not audit_available:
        warnings.append(
            "Khong the xac nhan day du candidate rows tu database; migration preview dang fail-closed."
        )
    if table_probe_error:
        warnings.append(f"Khong the dem candidate rows chi tiet: {table_probe_error}")
    if audit is not None:
        for table in audit.tables:
            if table.untracked_row_count > 0:
                warnings.append(
                    f"{table.table_name} con row untracked; hay chay legacy re-embed truoc migration full-space."
                )
            if len(table.fingerprints) > 1:
                warnings.append(
                    f"{table.table_name} dang mixed-space; nen lam sach index truoc khi migration."
                )
    if not target_backend_constructible:
        warnings.append("Target backend chua du dieu kien cau hinh de thuc hien re-embed.")

    recommended_steps: list[str] = []
    if transition.same_space:
        recommended_steps.append("Khong can migration full-space vi target dang cung vector-space hien tai.")
    else:
        if not audit_available:
            recommended_steps.append("Khoi phuc database audit/candidate scan truoc khi thuc hien migration full-space.")
        if not target_backend_constructible:
            recommended_steps.append("Cau hinh backend/credential cho target embedding model truoc.")
        if total_candidate_rows > 0 and audit_available and target_backend_constructible:
            recommended_steps.append("Prepare shadow space cho target model de bat dual-write ma khong dong retrieval.")
            recommended_steps.append("Backfill vector side-table tu current space sang target space bang run migration apply.")
            recommended_steps.append("Sau khi backfill xong, moi promote target space de doi read authority va runtime policy.")
        elif total_candidate_rows == 0 and target_backend_constructible:
            recommended_steps.append("Không có row cần backfill; có thể prepare và promote target space sau khi xác nhận backend sẵn sàng.")
        else:
            recommended_steps.append("Giu nguyen current space cho den khi planner co du du lieu va target backend san sang.")

    detail = transition.detail
    if current_contract is not None and current_contract.fingerprint != target_contract.fingerprint and not audit_available:
        if detail:
            detail += " Hiện không thể xác nhận trạng thái row/vector trong database, nên preview đang fail-closed."
        else:
            detail = (
                "Hiện không thể xác nhận trạng thái row/vector trong database, "
                "nên embedding-space migration preview đang fail-closed."
            )
    elif current_contract is not None and current_contract.fingerprint != target_contract.fingerprint and target_backend_constructible:
        zero_downtime_note = (
            "Wiii da co shadow-index path cho embeddings: prepare -> backfill -> promote."
        )
        detail = f"{detail} {zero_downtime_note}".strip() if detail else zero_downtime_note

    return EmbeddingSpaceMigrationPlan(
        current_contract_fingerprint=current_contract.fingerprint if current_contract else None,
        target_contract_fingerprint=target_contract.fingerprint,
        current_contract_label=current_contract.label if current_contract else None,
        target_contract_label=target_contract.label,
        same_space=transition.same_space,
        transition_allowed=transition_allowed,
        target_backend_constructible=target_backend_constructible,
        maintenance_required=maintenance_required,
        total_candidate_rows=total_candidate_rows,
        total_embedded_rows=total_embedded_rows,
        tables=plan_tables,
        warnings=tuple(dict.fromkeys(warnings)),
        detail=detail,
        recommended_steps=tuple(recommended_steps),
    )


def migrate_embedding_space_rows(
    *,
    target_model: str,
    target_dimensions: int | None = None,
    dry_run: bool = True,
    batch_size: int = 16,
    limit_per_table: int | None = None,
    tables: Iterable[str] | None = None,
    acknowledge_maintenance_window: bool = False,
) -> EmbeddingSpaceMigrationResult:
    plan = plan_embedding_space_migration(
        target_model=target_model,
        target_dimensions=target_dimensions,
        tables=tables,
    )
    if plan.same_space:
        return EmbeddingSpaceMigrationResult(
            dry_run=dry_run,
            maintenance_acknowledged=acknowledge_maintenance_window,
            current_contract_fingerprint=plan.current_contract_fingerprint,
            target_contract_fingerprint=plan.target_contract_fingerprint,
            target_backend_constructible=plan.target_backend_constructible,
            tables=tuple(
                EmbeddingSpaceMigrationTableResult(
                    table_name=item.table_name,
                    candidate_rows=item.candidate_rows,
                    updated_rows=0,
                    skipped_rows=item.candidate_rows,
                    failed_rows=0,
                )
                for item in plan.tables
            ),
            warnings=tuple(plan.warnings),
            detail="Target model dang cung vector-space hien tai; khong can migration full-space.",
            recommended_next_steps=("Giu nguyen policy hoac switch model trong cung space neu can.",),
        )
    if not dry_run and not acknowledge_maintenance_window:
        raise RuntimeError(
            "Maintenance window acknowledgement is required before applying embedding-space migration."
        )
    if not plan.target_backend_constructible:
        raise RuntimeError("Target backend chua san sang; khong the chay embedding-space migration.")

    current_contract = _current_contract()
    target_contract = build_embedding_space_contract(target_model, target_dimensions)
    if current_contract is None or target_contract is None:
        raise RuntimeError("Khong the xac dinh current/target embedding contract cho migration.")

    backend = build_embedding_backend_for_provider_model(
        target_contract.provider,
        target_contract.model,
        dimensions=target_contract.dimensions,
    )
    if backend is None:
        raise RuntimeError("Target backend khong the khoi tao duoi runtime config hien tai.")

    normalized_tables = _normalize_tables(tables)
    session_factory = get_shared_session_factory()
    table_results: list[EmbeddingSpaceMigrationTableResult] = []
    warnings = list(plan.warnings)

    if not dry_run:
        prepare_shadow_embedding_space(
            entity_types=normalized_tables,
            target_contract=target_contract,
            index_ready=False,
            metadata={
                "prepared_by": "embedding_space_migration_service",
                "current_contract_fingerprint": current_contract.fingerprint,
            },
        )
        try:
            ensure_shadow_vector_indexes(
                target_contract=target_contract,
                tables=normalized_tables,
            )
        except Exception as exc:
            warnings.append(f"Khong tao duoc shadow vector indexes ngay luc apply: {exc}")

    for table_name in normalized_tables:
        with session_factory() as session:
            rows = _fetch_candidate_rows(
                session,
                table_name=table_name,
                fingerprint=current_contract.fingerprint,
                limit=limit_per_table,
            )

        candidate_rows = len(rows)
        updated_rows = 0
        skipped_rows = 0
        failed_rows = 0
        if candidate_rows == 0:
            table_results.append(
                EmbeddingSpaceMigrationTableResult(
                    table_name=table_name,
                    candidate_rows=0,
                    updated_rows=0,
                    skipped_rows=0,
                    failed_rows=0,
                )
            )
            continue

        for start in range(0, candidate_rows, max(1, batch_size)):
            batch = rows[start : start + max(1, batch_size)]
            texts = [row.text_to_embed for row in batch]
            if dry_run:
                skipped_rows += len(batch)
                continue
            try:
                embeddings = backend.embed_documents(texts)
            except Exception as exc:
                logger.warning(
                    "Embedding-space migration batch failed: table=%s offset=%s error=%s",
                    table_name,
                    start,
                    exc,
                )
                failed_rows += len(batch)
                continue
            if len(embeddings) != len(batch):
                failed_rows += len(batch)
                warnings.append(
                    f"Batch migration {table_name} bat dau tu offset {start} tra ve so embedding khong khop."
                )
                continue
            with session_factory() as session:
                for row, embedding in zip(batch, embeddings, strict=False):
                    if not embedding:
                        failed_rows += 1
                        continue
                    stamped = stamp_embedding_metadata(
                        row.metadata,
                        model_name=target_contract.model,
                        dimensions=target_contract.dimensions,
                    )
                    try:
                        _upsert_shadow_row_embedding(
                            session,
                            row=row,
                            target_contract=target_contract,
                            embedding=embedding,
                            metadata=stamped,
                        )
                        updated_rows += 1
                    except Exception as exc:
                        logger.warning(
                            "Embedding-space migration row failed: table=%s row=%s error=%s",
                            table_name,
                            row.row_id,
                            exc,
                        )
                        failed_rows += 1
                session.commit()

        table_results.append(
            EmbeddingSpaceMigrationTableResult(
                table_name=table_name,
                candidate_rows=candidate_rows,
                updated_rows=updated_rows,
                skipped_rows=skipped_rows,
                failed_rows=failed_rows,
            )
            )

    if not dry_run:
        _flush_embedding_version(target_contract.fingerprint)
        warnings.append(
            "Da prepare/backfill shadow vectors cho target space. Buoc tiep theo: promote target space de doi runtime policy + read authority."
        )

    return EmbeddingSpaceMigrationResult(
        dry_run=dry_run,
        maintenance_acknowledged=acknowledge_maintenance_window,
        current_contract_fingerprint=current_contract.fingerprint,
        target_contract_fingerprint=target_contract.fingerprint,
        target_backend_constructible=True,
        tables=tuple(table_results),
        warnings=tuple(dict.fromkeys(warnings)),
        detail=plan.detail,
        recommended_next_steps=tuple(plan.recommended_steps),
    )


def promote_embedding_space_shadow(
    *,
    target_model: str,
    target_dimensions: int | None = None,
    tables: Iterable[str] | None = None,
    acknowledge_maintenance_window: bool = False,
) -> EmbeddingSpaceMigrationResult:
    plan = plan_embedding_space_migration(
        target_model=target_model,
        target_dimensions=target_dimensions,
        tables=tables,
    )
    if plan.same_space:
        return EmbeddingSpaceMigrationResult(
            dry_run=False,
            maintenance_acknowledged=acknowledge_maintenance_window,
            current_contract_fingerprint=plan.current_contract_fingerprint,
            target_contract_fingerprint=plan.target_contract_fingerprint,
            target_backend_constructible=plan.target_backend_constructible,
            tables=(),
            warnings=tuple(plan.warnings),
            detail="Target embedding space da la active space hien tai.",
            recommended_next_steps=("Khong can promote them.",),
        )

    if not plan.transition_allowed:
        raise RuntimeError(
            "Target embedding space chua san sang de promote. Hay chay plan/apply shadow truoc."
        )
    if not acknowledge_maintenance_window:
        raise RuntimeError(
            "Maintenance window acknowledgement is required before promoting embedding-space shadow."
        )

    target_contract = build_embedding_space_contract(target_model, target_dimensions)
    if target_contract is None:
        raise RuntimeError("Target embedding model khong hop le cho promote.")

    snapshot = snapshot_current_llm_runtime_policy()
    failover_chain = list(snapshot.get("embedding_failover_chain") or [])
    if target_contract.provider in failover_chain:
        failover_chain = [target_contract.provider] + [
            provider
            for provider in failover_chain
            if provider != target_contract.provider
        ]
    elif target_contract.provider:
        failover_chain = [target_contract.provider, *failover_chain]

    snapshot.update(
        {
            "embedding_provider": "auto",
            "embedding_model": target_contract.model,
            "embedding_dimensions": target_contract.dimensions,
            "embedding_failover_chain": failover_chain or [target_contract.provider],
        }
    )
    apply_llm_runtime_policy_snapshot(snapshot)
    persist_current_llm_runtime_policy()
    reset_embedding_backend()
    invalidate_embedding_selectability_cache()
    promote_shadow_embedding_space(
        entity_types=_normalize_tables(tables),
        target_contract=target_contract,
    )
    _flush_embedding_version(target_contract.fingerprint)

    return EmbeddingSpaceMigrationResult(
        dry_run=False,
        maintenance_acknowledged=acknowledge_maintenance_window,
        current_contract_fingerprint=plan.current_contract_fingerprint,
        target_contract_fingerprint=target_contract.fingerprint,
        target_backend_constructible=True,
        tables=(),
        warnings=("Da promote target shadow space thanh active embedding space.",),
        detail="Runtime policy va read authority da duoc chuyen sang target shadow space.",
        recommended_next_steps=(
            "Theo doi retrieval smoke tests va admin runtime snapshot de xac nhan active contract moi.",
        ),
    )
