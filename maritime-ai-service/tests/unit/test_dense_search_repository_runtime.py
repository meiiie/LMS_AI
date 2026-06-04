from __future__ import annotations

import json
import logging

import pytest

from app.repositories.dense_search_repository_runtime import (
    _derive_storage_uuid,
    delete_embedding_impl,
    store_document_chunk_impl,
)


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query, *params):
        self.calls.append((query, params))
        return "DELETE 1"

    async def fetchval(self, query, *params):
        self.calls.append((query, params))
        return "11111111-1111-1111-1111-111111111111"


class _FakeRepo:
    def __init__(self, *, has_node_id: bool, has_domain_id: bool = False):
        self._available = True
        self._pool = None
        self._has_node_id = has_node_id
        self._has_domain_id = has_domain_id
        self.conn = _FakeConn()

    async def _get_pool(self):
        self.get_pool_calls = getattr(self, "get_pool_calls", 0) + 1
        return _FakePool(self.conn)

    async def _has_column(self, conn, table: str, column: str) -> bool:
        if column == "node_id":
            return self._has_node_id
        if column == "organization_id":
            return True
        if column == "domain_id":
            return self._has_domain_id
        return False


def _metadata_payload_from_params(params: tuple[object, ...]) -> dict:
    for param in params:
        if isinstance(param, str) and param.startswith("{"):
            parsed = json.loads(param)
            if "legacy_node_id" in parsed:
                return parsed
    raise AssertionError("Metadata JSON param was not captured")


@pytest.mark.asyncio
async def test_store_document_chunk_uses_uuid_id_when_schema_lacks_node_id():
    repo = _FakeRepo(has_node_id=False)

    ok = await store_document_chunk_impl(
        repo,
        node_id="legacy-node-123",
        content="Rule 15 benchmark chunk",
        embedding=[0.1] * 768,
        document_id="doc-1",
        page_number=1,
        chunk_index=0,
        content_type="text",
        confidence_score=0.9,
        image_url="",
        metadata={"domain_id": "maritime"},
        organization_id=None,
        bounding_boxes=None,
    )

    assert ok is True
    query, params = repo.conn.calls[0]
    assert "INSERT INTO knowledge_embeddings" in query
    assert "id, content, embedding, document_id" in query
    assert "ON CONFLICT (id)" in query
    assert params[0] == _derive_storage_uuid("legacy-node-123")
    metadata_payload = _metadata_payload_from_params(params)
    assert metadata_payload["legacy_node_id"] == "legacy-node-123"
    assert (
        metadata_payload["embedding_space_fingerprint"]
        == metadata_payload["_embedding_space"]["fingerprint"]
    )


@pytest.mark.asyncio
async def test_store_document_chunk_persists_domain_column_when_available():
    repo = _FakeRepo(has_node_id=True, has_domain_id=True)

    ok = await store_document_chunk_impl(
        repo,
        node_id="domain-node-123",
        content="Rule 15 crossing situation chunk",
        embedding=[0.1] * 768,
        document_id="doc-1",
        page_number=1,
        chunk_index=0,
        content_type="text",
        confidence_score=0.9,
        image_url="",
        metadata={"domain_id": "maritime"},
        organization_id=None,
        bounding_boxes=None,
    )

    assert ok is True
    query, params = repo.conn.calls[0]
    assert "domain_id" in query
    assert "domain_id = COALESCE(EXCLUDED.domain_id, knowledge_embeddings.domain_id)" in query
    assert "maritime" in params


@pytest.mark.asyncio
async def test_delete_embedding_preserves_legacy_node_id_column_when_present():
    repo = _FakeRepo(has_node_id=True)

    ok = await delete_embedding_impl(
        repo,
        node_id="legacy-node-456",
        organization_id=None,
    )

    assert ok is True
    query, params = repo.conn.calls[0]
    assert "DELETE FROM knowledge_embeddings WHERE node_id = $1" in query
    assert params[0] == "legacy-node-456"


@pytest.mark.asyncio
async def test_store_document_chunk_dual_writes_shadow_vectors(monkeypatch):
    from app.repositories import dense_search_repository_runtime as mod

    repo = _FakeRepo(has_node_id=False)
    inline_space = type(
        "_Space",
        (),
        {
            "storage_kind": "inline",
            "provider": "google",
            "model": "models/gemini-embedding-001",
            "dimensions": 768,
            "space_fingerprint": "google:models/gemini-embedding-001:768",
        },
    )()
    shadow_space = type(
        "_Space",
        (),
        {
            "storage_kind": "shadow",
            "provider": "openai",
            "model": "text-embedding-3-small",
            "dimensions": 1536,
            "space_fingerprint": "openai:text-embedding-3-small:1536",
        },
    )()

    monkeypatch.setattr(mod, "get_embedding_write_spaces", lambda *_args, **_kwargs: (inline_space, shadow_space))

    async def _fake_build_shadow_embedding_async(*, text_to_embed, space, source_embedding, source_contract):
        if space.storage_kind == "inline":
            return list(source_embedding)
        return [0.2] * space.dimensions

    monkeypatch.setattr(mod, "build_shadow_embedding_async", _fake_build_shadow_embedding_async)
    monkeypatch.setattr(
        mod,
        "get_active_embedding_space_contract",
        lambda: type(
            "_Contract",
            (),
            {
                "fingerprint": "google:models/gemini-embedding-001:768",
                "model": "models/gemini-embedding-001",
                "dimensions": 768,
                "provider": "google",
            },
        )(),
    )

    ok = await store_document_chunk_impl(
        repo,
        node_id="shadow-node-1",
        content="Rule 15 benchmark chunk",
        embedding=[0.1] * 768,
        document_id="doc-1",
        page_number=1,
        chunk_index=0,
        content_type="text",
        confidence_score=0.9,
        image_url="",
        metadata={"domain_id": "maritime"},
        organization_id=None,
        bounding_boxes=None,
    )

    assert ok is True
    assert any("INSERT INTO knowledge_embedding_vectors" in call[0] for call in repo.conn.calls)


@pytest.mark.asyncio
async def test_store_document_chunk_blocks_missing_org_context_before_db(
    monkeypatch,
    caplog,
):
    from app.core.config import settings
    from app.core.org_context import current_org_id

    repo = _FakeRepo(has_node_id=True)
    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    caplog.set_level(logging.WARNING)

    token = current_org_id.set(None)
    try:
        ok = await store_document_chunk_impl(
            repo,
            node_id="PRIVATE-NODE",
            content="PRIVATE CONTENT",
            embedding=[0.1] * 768,
            document_id="PRIVATE-DOC",
            page_number=1,
            chunk_index=0,
            content_type="text",
            confidence_score=0.9,
            image_url="",
            metadata={"domain_id": "maritime"},
            organization_id=None,
            bounding_boxes=None,
        )
    finally:
        current_org_id.reset(token)

    assert ok is False
    assert getattr(repo, "get_pool_calls", 0) == 0
    assert repo.conn.calls == []
    assert "knowledge_search_blocked_missing_org_context" in caplog.text
    assert "PRIVATE-NODE" not in caplog.text
    assert "PRIVATE CONTENT" not in caplog.text
