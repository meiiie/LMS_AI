from __future__ import annotations

from types import SimpleNamespace

import pytest


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None


def _session_factory():
    return _DummySession()


def test_plan_embedding_space_migration_marks_shadow_path_available(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    current_contract = SimpleNamespace(
        provider="ollama",
        model="embeddinggemma",
        dimensions=768,
        fingerprint="ollama:embeddinggemma:768",
        label="embeddinggemma [ollama, 768d]",
    )
    target_contract = SimpleNamespace(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1536,
        fingerprint="openai:text-embedding-3-small:1536",
        label="text-embedding-3-small [openai, 1536d]",
    )
    audit = SimpleNamespace(
        audit_available=True,
        total_embedded_rows=5,
        tables=(
            SimpleNamespace(
                table_name="semantic_memories",
                embedded_row_count=3,
                tracked_row_count=3,
                untracked_row_count=0,
                fingerprints={"ollama:embeddinggemma:768": 3},
            ),
            SimpleNamespace(
                table_name="knowledge_embeddings",
                embedded_row_count=2,
                tracked_row_count=2,
                untracked_row_count=0,
                fingerprints={"ollama:embeddinggemma:768": 2},
            ),
        ),
        warnings=(),
        error=None,
    )

    monkeypatch.setattr(mod, "_current_contract", lambda: current_contract)
    monkeypatch.setattr(mod, "build_embedding_space_contract", lambda *_args, **_kwargs: target_contract)
    monkeypatch.setattr(mod, "inspect_embedding_space_usage", lambda **_kwargs: audit)
    monkeypatch.setattr(
        mod,
        "validate_embedding_space_transition_with_audit",
        lambda **_kwargs: SimpleNamespace(
            same_space=False,
            allowed=False,
            requires_reembed=True,
            warnings=(),
            detail="blocked until re-embed",
        ),
    )
    monkeypatch.setattr(
        mod,
        "_build_plan_tables",
        lambda **_kwargs: (
            mod.EmbeddingSpaceMigrationTablePlan(
                table_name="semantic_memories",
                candidate_rows=3,
                embedded_rows=3,
                tracked_rows=3,
                untracked_rows=0,
            ),
            mod.EmbeddingSpaceMigrationTablePlan(
                table_name="knowledge_embeddings",
                candidate_rows=2,
                embedded_rows=2,
                tracked_rows=2,
                untracked_rows=0,
            ),
        ),
    )
    monkeypatch.setattr(mod, "build_embedding_backend_for_provider_model", lambda *_args, **_kwargs: object())

    plan = mod.plan_embedding_space_migration(target_model="text-embedding-3-small")

    assert plan.same_space is False
    assert plan.transition_allowed is True
    assert plan.maintenance_required is False
    assert plan.total_candidate_rows == 5
    assert plan.target_backend_constructible is True
    assert any("shadow" in step.lower() for step in plan.recommended_steps)


def test_plan_embedding_space_migration_fail_closed_when_audit_unavailable(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    current_contract = SimpleNamespace(
        provider="ollama",
        model="embeddinggemma",
        dimensions=768,
        fingerprint="ollama:embeddinggemma:768",
        label="embeddinggemma [ollama, 768d]",
    )
    target_contract = SimpleNamespace(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1536,
        fingerprint="openai:text-embedding-3-small:1536",
        label="text-embedding-3-small [openai, 1536d]",
    )
    audit = SimpleNamespace(
        audit_available=False,
        total_embedded_rows=0,
        tables=(),
        warnings=("db unavailable",),
        error="No DB in unit tests",
    )

    monkeypatch.setattr(mod, "_current_contract", lambda: current_contract)
    monkeypatch.setattr(mod, "build_embedding_space_contract", lambda *_args, **_kwargs: target_contract)
    monkeypatch.setattr(mod, "inspect_embedding_space_usage", lambda **_kwargs: audit)
    monkeypatch.setattr(
        mod,
        "validate_embedding_space_transition_with_audit",
        lambda **_kwargs: SimpleNamespace(
            same_space=False,
            allowed=True,
            requires_reembed=False,
            warnings=("db unavailable",),
            detail=None,
        ),
    )
    monkeypatch.setattr(mod, "build_embedding_backend_for_provider_model", lambda *_args, **_kwargs: object())

    plan = mod.plan_embedding_space_migration(target_model="text-embedding-3-small")

    assert plan.same_space is False
    assert plan.transition_allowed is False
    assert plan.maintenance_required is False
    assert any("fail-closed" in warning.lower() for warning in plan.warnings)
    assert any("database audit" in step.lower() for step in plan.recommended_steps)


def test_migrate_embedding_space_rows_same_space_short_circuits(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    monkeypatch.setattr(
        mod,
        "plan_embedding_space_migration",
        lambda **_kwargs: mod.EmbeddingSpaceMigrationPlan(
            current_contract_fingerprint="ollama:embeddinggemma:768",
            target_contract_fingerprint="ollama:embeddinggemma:768",
            current_contract_label="embeddinggemma [ollama, 768d]",
            target_contract_label="embeddinggemma [ollama, 768d]",
            same_space=True,
            transition_allowed=True,
            target_backend_constructible=True,
            maintenance_required=False,
            total_candidate_rows=0,
            total_embedded_rows=0,
            tables=(),
            warnings=(),
            detail="noop",
            recommended_steps=(),
        ),
    )

    result = mod.migrate_embedding_space_rows(
        target_model="embeddinggemma",
        dry_run=True,
    )

    assert result.detail is not None
    assert "khong can migration" in result.detail.lower()


def test_migrate_embedding_space_rows_dry_run_counts_candidates(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    current_contract = SimpleNamespace(
        provider="ollama",
        model="embeddinggemma",
        dimensions=768,
        fingerprint="ollama:embeddinggemma:768",
        label="embeddinggemma [ollama, 768d]",
    )
    target_contract = SimpleNamespace(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1536,
        fingerprint="openai:text-embedding-3-small:1536",
        label="text-embedding-3-small [openai, 1536d]",
    )
    monkeypatch.setattr(
        mod,
        "plan_embedding_space_migration",
        lambda **_kwargs: mod.EmbeddingSpaceMigrationPlan(
            current_contract_fingerprint=current_contract.fingerprint,
            target_contract_fingerprint=target_contract.fingerprint,
            current_contract_label=current_contract.label,
            target_contract_label=target_contract.label,
            same_space=False,
            transition_allowed=True,
            target_backend_constructible=True,
            maintenance_required=False,
            total_candidate_rows=2,
            total_embedded_rows=2,
            tables=(
                mod.EmbeddingSpaceMigrationTablePlan(
                    table_name="semantic_memories",
                    candidate_rows=2,
                    embedded_rows=2,
                    tracked_rows=2,
                    untracked_rows=0,
                ),
            ),
            warnings=(),
            detail="shadow path",
            recommended_steps=("prepare shadow",),
        ),
    )
    monkeypatch.setattr(mod, "_current_contract", lambda: current_contract)
    monkeypatch.setattr(mod, "build_embedding_space_contract", lambda *_args, **_kwargs: target_contract)
    monkeypatch.setattr(mod, "build_embedding_backend_for_provider_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(mod, "get_shared_session_factory", lambda: _session_factory)
    monkeypatch.setattr(
        mod,
        "_fetch_candidate_rows",
        lambda *_args, table_name, fingerprint, limit: [
            mod._MigrationRow(
                table_name=table_name,
                row_id="row-1",
                text_to_embed="hello",
                metadata={"source": "test"},
            ),
            mod._MigrationRow(
                table_name=table_name,
                row_id="row-2",
                text_to_embed="world",
                metadata={"source": "test"},
            ),
        ],
    )

    result = mod.migrate_embedding_space_rows(
        target_model="text-embedding-3-small",
        dry_run=True,
        acknowledge_maintenance_window=True,
    )

    assert result.dry_run is True
    assert result.tables[0].candidate_rows == 2
    assert result.tables[0].updated_rows == 0
    assert result.tables[0].skipped_rows == 2


def test_migrate_embedding_space_rows_apply_requires_maintenance_ack(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    monkeypatch.setattr(
        mod,
        "plan_embedding_space_migration",
        lambda **_kwargs: mod.EmbeddingSpaceMigrationPlan(
            current_contract_fingerprint="ollama:embeddinggemma:768",
            target_contract_fingerprint="openai:text-embedding-3-small:1536",
            current_contract_label="embeddinggemma [ollama, 768d]",
            target_contract_label="text-embedding-3-small [openai, 1536d]",
            same_space=False,
            transition_allowed=True,
            target_backend_constructible=True,
            maintenance_required=False,
            total_candidate_rows=1,
            total_embedded_rows=1,
            tables=(),
            warnings=(),
            detail="shadow path",
            recommended_steps=("prepare shadow",),
        ),
    )

    with pytest.raises(RuntimeError, match="Maintenance window acknowledgement"):
        mod.migrate_embedding_space_rows(
            target_model="text-embedding-3-small",
            dry_run=False,
            acknowledge_maintenance_window=False,
        )


def test_migrate_embedding_space_rows_apply_updates_and_stamps_target_metadata(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    current_contract = SimpleNamespace(
        provider="ollama",
        model="embeddinggemma",
        dimensions=768,
        fingerprint="ollama:embeddinggemma:768",
        label="embeddinggemma [ollama, 768d]",
    )
    target_contract = SimpleNamespace(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1536,
        fingerprint="openai:text-embedding-3-small:1536",
        label="text-embedding-3-small [openai, 1536d]",
    )
    backend = SimpleNamespace(
        embed_documents=lambda texts: [[0.1] * 1536 for _ in texts],
    )

    monkeypatch.setattr(
        mod,
        "plan_embedding_space_migration",
        lambda **_kwargs: mod.EmbeddingSpaceMigrationPlan(
            current_contract_fingerprint=current_contract.fingerprint,
            target_contract_fingerprint=target_contract.fingerprint,
            current_contract_label=current_contract.label,
            target_contract_label=target_contract.label,
            same_space=False,
            transition_allowed=True,
            target_backend_constructible=True,
            maintenance_required=False,
            total_candidate_rows=1,
            total_embedded_rows=1,
            tables=(
                mod.EmbeddingSpaceMigrationTablePlan(
                    table_name="semantic_memories",
                    candidate_rows=1,
                    embedded_rows=1,
                    tracked_rows=1,
                    untracked_rows=0,
                ),
            ),
            warnings=(),
            detail="shadow path",
            recommended_steps=("promote later",),
        ),
    )
    monkeypatch.setattr(mod, "_current_contract", lambda: current_contract)
    monkeypatch.setattr(mod, "build_embedding_space_contract", lambda *_args, **_kwargs: target_contract)
    monkeypatch.setattr(mod, "build_embedding_backend_for_provider_model", lambda *_args, **_kwargs: backend)
    monkeypatch.setattr(mod, "get_shared_session_factory", lambda: _session_factory)
    monkeypatch.setattr(
        mod,
        "_fetch_candidate_rows",
        lambda *_args, table_name, fingerprint, limit: [
            mod._MigrationRow(
                table_name=table_name,
                row_id="row-1",
                text_to_embed="hello",
                metadata={"source": "test"},
            )
        ],
    )
    monkeypatch.setattr(mod, "_flush_embedding_version", lambda _version: None)
    monkeypatch.setattr(mod, "prepare_shadow_embedding_space", lambda **_kwargs: ())
    monkeypatch.setattr(mod, "ensure_shadow_vector_indexes", lambda **_kwargs: ())

    writes: list[dict] = []

    def _capture(_session, *, row, target_contract, embedding, metadata):
        writes.append({"row_id": row.row_id, "embedding_len": len(embedding), "metadata": metadata})

    monkeypatch.setattr(mod, "_upsert_shadow_row_embedding", _capture)

    result = mod.migrate_embedding_space_rows(
        target_model="text-embedding-3-small",
        dry_run=False,
        acknowledge_maintenance_window=True,
    )

    assert result.tables[0].updated_rows == 1
    assert writes[0]["embedding_len"] == 1536
    assert writes[0]["metadata"]["embedding_space_fingerprint"] == "openai:text-embedding-3-small:1536"


def test_promote_embedding_space_shadow_updates_policy_and_registry(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    monkeypatch.setattr(
        mod,
        "plan_embedding_space_migration",
        lambda **_kwargs: mod.EmbeddingSpaceMigrationPlan(
            current_contract_fingerprint="ollama:embeddinggemma:768",
            target_contract_fingerprint="openai:text-embedding-3-small:1536",
            current_contract_label="embeddinggemma [ollama, 768d]",
            target_contract_label="text-embedding-3-small [openai, 1536d]",
            same_space=False,
            transition_allowed=True,
            target_backend_constructible=True,
            maintenance_required=False,
            total_candidate_rows=1,
            total_embedded_rows=1,
            tables=(),
            warnings=(),
            detail="shadow ready",
            recommended_steps=("promote",),
        ),
    )
    target_contract = SimpleNamespace(
        provider="openai",
        model="text-embedding-3-small",
        dimensions=1536,
        fingerprint="openai:text-embedding-3-small:1536",
        label="text-embedding-3-small [openai, 1536d]",
    )
    applied_snapshots: list[dict] = []
    monkeypatch.setattr(mod, "build_embedding_space_contract", lambda *_args, **_kwargs: target_contract)
    monkeypatch.setattr(
        mod,
        "snapshot_current_llm_runtime_policy",
        lambda: {
            "embedding_provider": "auto",
            "embedding_model": "embeddinggemma",
            "embedding_dimensions": 768,
            "embedding_failover_chain": ["ollama", "openai", "google"],
        },
    )
    monkeypatch.setattr(mod, "apply_llm_runtime_policy_snapshot", lambda snapshot: applied_snapshots.append(snapshot) or snapshot)
    monkeypatch.setattr(mod, "persist_current_llm_runtime_policy", lambda: None)
    monkeypatch.setattr(mod, "reset_embedding_backend", lambda: None)
    monkeypatch.setattr(mod, "invalidate_embedding_selectability_cache", lambda: None)
    promoted: list[tuple] = []
    monkeypatch.setattr(mod, "promote_shadow_embedding_space", lambda **kwargs: promoted.append(tuple(kwargs["entity_types"])) or ())
    monkeypatch.setattr(mod, "_flush_embedding_version", lambda _version: None)

    result = mod.promote_embedding_space_shadow(
        target_model="text-embedding-3-small",
        acknowledge_maintenance_window=True,
    )

    assert result.target_contract_fingerprint == "openai:text-embedding-3-small:1536"
    assert applied_snapshots[0]["embedding_model"] == "text-embedding-3-small"
    assert applied_snapshots[0]["embedding_dimensions"] == 1536
    assert applied_snapshots[0]["embedding_failover_chain"][0] == "openai"
    assert promoted[0] == ("semantic_memories", "knowledge_embeddings")


def test_promote_embedding_space_shadow_requires_maintenance_ack(monkeypatch):
    from app.services import embedding_space_migration_service as mod

    monkeypatch.setattr(
        mod,
        "plan_embedding_space_migration",
        lambda **_kwargs: mod.EmbeddingSpaceMigrationPlan(
            current_contract_fingerprint="ollama:embeddinggemma:768",
            target_contract_fingerprint="openai:text-embedding-3-small:1536",
            current_contract_label="embeddinggemma [ollama, 768d]",
            target_contract_label="text-embedding-3-small [openai, 1536d]",
            same_space=False,
            transition_allowed=True,
            target_backend_constructible=True,
            maintenance_required=False,
            total_candidate_rows=1,
            total_embedded_rows=1,
            tables=(),
            warnings=(),
            detail="shadow ready",
            recommended_steps=("promote",),
        ),
    )

    with pytest.raises(RuntimeError, match="Maintenance window acknowledgement"):
        mod.promote_embedding_space_shadow(
            target_model="text-embedding-3-small",
            acknowledge_maintenance_window=False,
        )
