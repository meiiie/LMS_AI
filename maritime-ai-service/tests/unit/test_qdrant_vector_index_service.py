from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.embedding_space_registry_service import EmbeddingSpaceRegistryEntry
from app.services import qdrant_vector_index_service as qdrant


def _space(dimensions: int = 4096) -> EmbeddingSpaceRegistryEntry:
    return EmbeddingSpaceRegistryEntry(
        entity_type="semantic_memories",
        space_fingerprint="nvidia:nvidia/nv-embed-v1:4096",
        provider="nvidia",
        model="nvidia/nv-embed-v1",
        dimensions=dimensions,
        storage_kind="shadow",
        state="active",
        reads_enabled=True,
        writes_enabled=True,
        index_ready=False,
        metadata={},
    )


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def reset_qdrant_settings(monkeypatch):
    qdrant._COLLECTION_CACHE.clear()
    qdrant._DEGRADED_UNTIL = 0.0
    monkeypatch.setattr(qdrant.settings, "vector_index_backend", "qdrant")
    monkeypatch.setattr(qdrant.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(qdrant.settings, "qdrant_api_key", None)
    monkeypatch.setattr(qdrant.settings, "qdrant_collection_prefix", "wiii_test")
    monkeypatch.setattr(qdrant.settings, "qdrant_timeout_seconds", 1.0)
    monkeypatch.setattr(qdrant.settings, "qdrant_search_oversample", 2)
    monkeypatch.setattr(qdrant.settings, "qdrant_failure_cooldown_seconds", 30.0)
    yield
    qdrant._COLLECTION_CACHE.clear()
    qdrant._DEGRADED_UNTIL = 0.0


def test_collection_name_is_stable_and_sanitized():
    first = qdrant.build_qdrant_collection_name(
        "semantic_memories",
        "nvidia:nvidia/nv-embed-v1:4096",
    )
    second = qdrant.build_qdrant_collection_name(
        "semantic_memories",
        "nvidia:nvidia/nv-embed-v1:4096",
    )
    assert first == second
    assert first.startswith("wiii_test_semantic_")
    assert "/" not in first
    assert ":" not in first


def test_filter_supports_exact_any_and_range():
    payload = qdrant.build_qdrant_filter(
        {
            "organization_id": "org-1",
            "memory_type": ["fact", "preference"],
            "confidence_score": {"gte": 0.7},
        }
    )
    assert payload == {
        "must": [
            {"key": "organization_id", "match": {"value": "org-1"}},
            {"key": "memory_type", "match": {"any": ["fact", "preference"]}},
            {"key": "confidence_score", "range": {"gte": 0.7}},
        ]
    }


def test_ensure_collection_creates_missing_collection(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        return FakeResponse(404)

    def fake_put(*args, **kwargs):
        calls.append(SimpleNamespace(args=args, kwargs=kwargs))
        return FakeResponse(200, {"result": True})

    monkeypatch.setattr(qdrant.httpx, "get", fake_get)
    monkeypatch.setattr(qdrant.httpx, "put", fake_put)

    collection_name = qdrant.ensure_qdrant_collection_sync("semantic_memories", _space())

    assert collection_name is not None
    assert calls
    assert calls[0].kwargs["json"] == {"vectors": {"size": 4096, "distance": "Cosine"}}


def test_search_posts_vector_and_filters(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        qdrant,
        "ensure_qdrant_collection_sync",
        lambda entity_type, space: "wiii_test_semantic_collection",
    )

    def fake_post(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeResponse(
            200,
            {
                "result": [
                    {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "score": 0.91,
                        "payload": {"user_id": "user-1"},
                    }
                ]
            },
        )

    monkeypatch.setattr(qdrant.httpx, "post", fake_post)

    hits = qdrant.search_qdrant_sync(
        entity_type="semantic_memories",
        space=_space(dimensions=3),
        query_embedding=[0.1, 0.2, 0.3],
        limit=5,
        score_threshold=0.7,
        filters={"user_id": "user-1"},
    )

    body = captured["kwargs"]["json"]
    assert body["limit"] == 10
    assert body["score_threshold"] == 0.7
    assert {"key": "user_id", "match": {"value": "user-1"}} in body["filter"]["must"]
    assert hits[0].point_id == "11111111-1111-1111-1111-111111111111"
    assert hits[0].score == 0.91


def test_rebuild_skips_when_backend_is_not_qdrant(monkeypatch):
    monkeypatch.setattr(qdrant.settings, "vector_index_backend", "postgres")

    results = qdrant.rebuild_qdrant_index_for_active_spaces(
        entity_types=["semantic_memories"],
    )

    assert results[0].status == "skipped"
    assert results[0].detail == "vector_index_backend is not qdrant"


def test_failed_operation_marks_qdrant_temporarily_disabled(monkeypatch):
    monkeypatch.setattr(
        qdrant,
        "ensure_qdrant_collection_sync",
        lambda entity_type, space: "wiii_test_semantic_collection",
    )

    def fake_post(*args, **kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(qdrant.httpx, "post", fake_post)

    hits = qdrant.search_qdrant_sync(
        entity_type="semantic_memories",
        space=_space(dimensions=3),
        query_embedding=[0.1, 0.2, 0.3],
        limit=3,
    )

    assert hits == []
    assert not qdrant.is_qdrant_enabled()
