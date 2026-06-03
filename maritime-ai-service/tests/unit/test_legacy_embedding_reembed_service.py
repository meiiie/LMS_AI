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


def test_reembed_legacy_rows_dry_run_counts_rows_without_writing(monkeypatch):
    from app.services import legacy_embedding_reembed_service as mod

    backend = SimpleNamespace(
        provider="ollama",
        model_name="embeddinggemma",
        dimensions=768,
        is_available=lambda: True,
        embed_documents=lambda texts: [[0.1] * 768 for _ in texts],
    )

    monkeypatch.setattr(
        mod,
        "get_embedding_backend",
        lambda: SimpleNamespace(active_backend=backend),
    )
    monkeypatch.setattr(mod, "get_shared_session_factory", lambda: _session_factory)
    monkeypatch.setattr(
        mod,
        "_fetch_legacy_rows",
        lambda *_args, table_name, limit: [
            mod.LegacyEmbeddingRow(
                table_name=table_name,
                row_id="row-1",
                text_to_embed="hello world",
                metadata={"source": "legacy"},
            )
        ],
    )
    monkeypatch.setattr(
        mod,
        "inspect_embedding_space_usage",
        lambda **_kwargs: SimpleNamespace(warnings=(), audit_available=True),
    )

    writes: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        mod,
        "_update_row_embedding",
        lambda _session, *, row, embedding, metadata: writes.append((row.row_id, metadata)),
    )

    result = mod.reembed_legacy_embedding_rows(dry_run=True, batch_size=4)

    assert result.contract_fingerprint == "ollama:embeddinggemma:768"
    assert all(item.updated_rows == 0 for item in result.tables)
    assert all(item.skipped_rows == 1 for item in result.tables)
    assert writes == []


def test_reembed_legacy_rows_updates_and_stamps_metadata(monkeypatch):
    from app.services import legacy_embedding_reembed_service as mod

    backend = SimpleNamespace(
        provider="ollama",
        model_name="embeddinggemma",
        dimensions=768,
        is_available=lambda: True,
        embed_documents=lambda texts: [[0.2] * 768 for _ in texts],
    )

    monkeypatch.setattr(
        mod,
        "get_embedding_backend",
        lambda: SimpleNamespace(active_backend=backend),
    )
    monkeypatch.setattr(mod, "get_shared_session_factory", lambda: _session_factory)
    monkeypatch.setattr(
        mod,
        "_fetch_legacy_rows",
        lambda *_args, table_name, limit: [
            mod.LegacyEmbeddingRow(
                table_name=table_name,
                row_id=f"{table_name}-1",
                text_to_embed="hello world",
                metadata={"source": "legacy"},
            )
        ],
    )
    monkeypatch.setattr(
        mod,
        "inspect_embedding_space_usage",
        lambda **_kwargs: SimpleNamespace(
            warnings=(),
            audit_available=True,
        ),
    )
    monkeypatch.setattr(mod, "_flush_embedding_version", lambda _version: None)

    writes: list[dict] = []

    def _capture(_session, *, row, embedding, metadata):
        writes.append(
            {
                "row_id": row.row_id,
                "embedding_len": len(embedding),
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(mod, "_update_row_embedding", _capture)

    result = mod.reembed_legacy_embedding_rows(
        dry_run=False,
        batch_size=2,
        acknowledge_maintenance_window=True,
    )

    assert sum(item.updated_rows for item in result.tables) == 2
    assert len(writes) == 2
    assert all(item["embedding_len"] == 768 for item in writes)
    assert all(
        item["metadata"]["embedding_space_fingerprint"] == "ollama:embeddinggemma:768"
        for item in writes
    )


def test_reembed_legacy_rows_apply_requires_maintenance_ack(monkeypatch):
    from app.services import legacy_embedding_reembed_service as mod

    with pytest.raises(RuntimeError, match="Maintenance window acknowledgement"):
        mod.reembed_legacy_embedding_rows(
            dry_run=False,
            acknowledge_maintenance_window=False,
        )


def test_reembed_legacy_rows_requires_active_backend(monkeypatch):
    from app.services import legacy_embedding_reembed_service as mod

    monkeypatch.setattr(
        mod,
        "get_embedding_backend",
        lambda: SimpleNamespace(active_backend=None),
    )
    with pytest.raises(RuntimeError, match="Embedding backend hien tai"):
        mod.reembed_legacy_embedding_rows(dry_run=True)
