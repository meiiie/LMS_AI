from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.engine.semantic_memory.privacy import (
    hash_memory_identifier,
    memory_log_reference,
)
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    build_semantic_memory_write_audit,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)
from app.engine.semantic_memory.write_doctor import (
    build_recent_semantic_memory_write_doctor_report_from_session_log,
    build_semantic_memory_write_doctor_history_from_session_log,
    build_semantic_memory_write_doctor_report,
)
from app.engine.runtime.session_event_log import InMemorySessionEventLog
from app.engine.semantic_memory.session_runtime import store_explicit_insight_impl
from app.services.memory_lifecycle import prune_stale_memories


def test_memory_log_reference_uses_hash_and_count_without_raw_text() -> None:
    raw_fact = "PRIVATE MEMORY FACT access_token=raw-secret-token-12345"

    reference = memory_log_reference(raw_fact)

    assert reference.startswith("sha256:")
    assert ";chars=" in reference
    assert "PRIVATE MEMORY FACT" not in reference
    assert "raw-secret-token" not in reference


def test_hash_memory_identifier_is_stable_without_exposing_identifier() -> None:
    identifier = "user-private-123"

    first = hash_memory_identifier(identifier)
    second = hash_memory_identifier(identifier)

    assert first == second
    assert first.startswith("sha256:")
    assert identifier not in first


def test_semantic_memory_write_audit_uses_counts_and_hashes() -> None:
    message = "PRIVATE MESSAGE access_token=raw-message-token-12345"
    response = "PRIVATE RESPONSE"
    payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-123",
        message=message,
        response=response,
        scope=MemoryWriteScope(
            org_id="org-private-123",
            state="request_scoped",
            warnings=[],
        ),
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=2,
        status="saved",
    )

    assert payload["privacy"]["raw_content_included"] is False
    assert payload["turn"] == {
        "message_char_count": len(message),
        "response_char_count": len(response),
    }
    assert payload["write"]["stored_fact_count"] == 2
    assert payload["write"]["stored_insight_count"] == 0
    assert payload["write"]["kind"] == "interaction"
    serialized = str(payload)
    assert "user-private-123" not in serialized
    assert "session-private-123" not in serialized
    assert "org-private-123" not in serialized
    assert "PRIVATE MESSAGE" not in serialized
    assert "raw-message-token" not in serialized
    assert "PRIVATE RESPONSE" not in serialized


def test_memory_write_scope_blocks_missing_multi_tenant_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.core.org_context import current_org_id

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    token = current_org_id.set(None)
    try:
        scope = resolve_memory_write_scope()
    finally:
        current_org_id.reset(token)

    assert scope.write_allowed is False
    assert scope.org_id is None
    assert scope.state == "blocked_missing_org_context"
    assert "missing_org_context" in scope.warnings


def test_memory_read_scope_blocks_missing_multi_tenant_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.core.org_context import current_org_id

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    token = current_org_id.set(None)
    try:
        scope = resolve_memory_read_scope()
    finally:
        current_org_id.reset(token)

    assert scope.write_allowed is False
    assert scope.org_id is None
    assert scope.state == "blocked_missing_org_context"


def test_semantic_memory_write_doctor_aggregates_without_raw_content() -> None:
    payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-123",
        message="PRIVATE MESSAGE",
        response="PRIVATE RESPONSE",
        scope=MemoryWriteScope(
            org_id="org-private-123",
            state="request_scoped",
            warnings=[],
        ),
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=2,
        status="saved",
    )

    report = build_semantic_memory_write_doctor_report([payload])

    assert report["status"] == "ready"
    assert report["summary"]["write_count"] == 1
    assert report["summary"]["stored_fact_total"] == 2
    assert report["summary"]["stored_insight_total"] == 0
    assert report["write_kinds"] == {"interaction": 1}
    assert report["organization_contexts"] == {"request_scoped": 1}
    serialized = str(report)
    assert "PRIVATE MESSAGE" not in serialized
    assert "PRIVATE RESPONSE" not in serialized
    assert "user-private-123" not in serialized
    assert "session-private-123" not in serialized
    assert "org-private-123" not in serialized


def test_semantic_memory_write_doctor_counts_blocked_writes() -> None:
    payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-123",
        message="PRIVATE MESSAGE",
        response="PRIVATE RESPONSE",
        scope=MemoryWriteScope(
            org_id=None,
            state="blocked_missing_org_context",
            warnings=["missing_org_context"],
            write_allowed=False,
        ),
        message_saved=False,
        response_saved=False,
        extract_facts=True,
        stored_fact_count=0,
        status="blocked",
    )

    report = build_semantic_memory_write_doctor_report([payload])

    assert report["status"] == "degraded"
    assert report["summary"]["blocked_count"] == 1
    assert report["organization_contexts"] == {"blocked_missing_org_context": 1}
    assert report["warnings"] == {"missing_org_context": 1}


@pytest.mark.asyncio
async def test_recent_semantic_memory_write_doctor_reads_session_log() -> None:
    log = InMemorySessionEventLog()
    payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-123",
        message="PRIVATE MESSAGE",
        response="PRIVATE RESPONSE",
        scope=MemoryWriteScope(
            org_id="org-A",
            state="request_scoped",
            warnings=[],
        ),
        message_saved=True,
        response_saved=False,
        extract_facts=True,
        stored_fact_count=1,
        status="degraded",
    )
    await log.append(
        session_id="session-private-123",
        org_id="org-A",
        event_type="semantic_memory_write",
        payload=payload,
    )
    await log.append(
        session_id="session-private-456",
        org_id="org-B",
        event_type="semantic_memory_write",
        payload=payload,
    )

    report = await build_recent_semantic_memory_write_doctor_report_from_session_log(
        log,
        org_id="org-A",
        limit=20,
    )

    assert report["status"] == "degraded"
    assert report["summary"]["write_count"] == 1
    assert report["summary"]["degraded_count"] == 1
    assert report["source"] == {
        "session_event_count": 1,
        "semantic_memory_write_event_count": 1,
        "limit": 20,
        "org_scoped": True,
        "window": "recent_semantic_memory_write_events",
    }
    serialized = str(report)
    assert "session-private-123" not in serialized
    assert "PRIVATE MESSAGE" not in serialized


@pytest.mark.asyncio
async def test_semantic_memory_write_doctor_history_is_aggregate_only() -> None:
    log = InMemorySessionEventLog()
    org_a_payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-123",
        message="PRIVATE HISTORY MESSAGE",
        response="PRIVATE HISTORY RESPONSE",
        scope=MemoryWriteScope(
            org_id="org-A",
            state="request_scoped",
            warnings=[],
        ),
        write_kind="interaction",
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=2,
        status="saved",
    )
    org_a_degraded_payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-123",
        message="PRIVATE HISTORY MESSAGE",
        response="PRIVATE HISTORY RESPONSE",
        scope=MemoryWriteScope(
            org_id="org-A",
            state="request_scoped",
            warnings=[],
        ),
        write_kind="insight_store",
        message_saved=False,
        response_saved=False,
        extract_facts=False,
        stored_fact_count=0,
        stored_insight_count=1,
        status="degraded",
        warnings=["insight_store_degraded"],
    )
    org_b_payload = build_semantic_memory_write_audit(
        user_id="user-private-456",
        session_id="session-private-456",
        message="PRIVATE OTHER ORG",
        response="PRIVATE OTHER ORG",
        scope=MemoryWriteScope(
            org_id="org-B",
            state="request_scoped",
            warnings=[],
        ),
        write_kind="interaction",
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=4,
        status="saved",
    )
    await log.append(
        session_id="session-private-123",
        org_id="org-A",
        event_type="semantic_memory_write",
        payload=org_a_payload,
    )
    await log.append(
        session_id="session-private-123",
        org_id="org-A",
        event_type="semantic_memory_write",
        payload=org_a_degraded_payload,
    )
    await log.append(
        session_id="session-private-456",
        org_id="org-B",
        event_type="semantic_memory_write",
        payload=org_b_payload,
    )

    history = await build_semantic_memory_write_doctor_history_from_session_log(
        log,
        org_id="org-A",
        limit=20,
        bucket_limit=12,
    )

    assert history["version"] == "wiii.semantic_memory_write_doctor_history.v1"
    assert history["bucket_strategy"] == "event_created_at_hour"
    assert history["identifier_strategy"] == "aggregate_counts_only"
    assert history["source"]["semantic_memory_write_event_count"] == 2
    assert history["source"]["org_scoped"] is True
    assert history["source"]["bucket_limit"] == 12
    assert history["buckets"][0]["status"] == "degraded"
    assert history["buckets"][0]["summary"]["write_count"] == 2
    assert history["buckets"][0]["summary"]["stored_fact_total"] == 2
    assert history["buckets"][0]["summary"]["stored_insight_total"] == 1
    assert history["buckets"][0]["warnings"] == {"insight_store_degraded": 1}
    assert history["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "aggregate_counts_only",
    }
    serialized = str(history)
    assert "session-private-123" not in serialized
    assert "session-private-456" not in serialized
    assert "PRIVATE HISTORY MESSAGE" not in serialized
    assert "PRIVATE OTHER ORG" not in serialized


@pytest.mark.asyncio
async def test_memory_pruning_logs_hashes_not_raw_fact_or_user(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.core.config import settings

    raw_fact = "PRIVATE PRUNE MEMORY access_token=raw-prune-token-12345"
    fact = SimpleNamespace(
        id="fact-1",
        metadata={"fact_type": "preference", "access_count": 0},
        importance=0.1,
        created_at=datetime.now(timezone.utc),
        content=raw_fact,
    )

    class Repo:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, str]] = []

        def get_all_user_facts(self, user_id: str):
            assert user_id == "user-private-123"
            return [fact]

        def delete_memory(self, user_id: str, memory_id: str) -> bool:
            self.deleted.append((user_id, memory_id))
            return True

    repo = Repo()
    monkeypatch.setattr(settings, "enable_memory_pruning", True)
    monkeypatch.setattr(settings, "memory_prune_threshold", 0.5)
    monkeypatch.setattr(
        "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
        lambda: repo,
    )
    monkeypatch.setattr(
        "app.engine.semantic_memory.importance_decay."
        "calculate_effective_importance_from_timestamps",
        lambda **_kwargs: 0.1,
    )
    caplog.set_level(logging.INFO)

    pruned = await prune_stale_memories("user-private-123")

    assert pruned == 1
    assert repo.deleted == [("user-private-123", "fact-1")]
    assert "content_ref=sha256:" in caplog.text
    assert "user_hash=sha256:" in caplog.text
    assert raw_fact not in caplog.text
    assert "raw-prune-token" not in caplog.text
    assert "user-private-123" not in caplog.text


@pytest.mark.asyncio
async def test_memory_pruning_blocks_without_org_context_when_multi_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.core.org_context import current_org_id
    from app.engine.runtime.session_event_log import InMemorySessionEventLog

    class Repo:
        def get_all_user_facts(self, _user_id: str):
            raise AssertionError("pruning must not read facts without org context")

        def delete_memory(self, _user_id: str, _memory_id: str) -> bool:
            raise AssertionError("pruning must not delete without org context")

    log = InMemorySessionEventLog()
    monkeypatch.setattr(settings, "enable_memory_pruning", True)
    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    monkeypatch.setattr(
        "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
        lambda: Repo(),
    )
    monkeypatch.setattr(
        "app.engine.runtime.session_event_log.get_session_event_log",
        lambda: log,
    )

    token = current_org_id.set(None)
    try:
        pruned = await prune_stale_memories(
            "user-private-123",
            session_id="session-private-123",
        )
    finally:
        current_org_id.reset(token)

    assert pruned == 0
    events = await log.get_events(session_id="session-private-123")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["write"]["kind"] == "memory_pruning"
    assert payload["write"]["status"] == "blocked"
    assert payload["scope"]["write_allowed"] is False
    assert "memory_pruning_blocked_missing_org_context" in payload["warnings"]


@pytest.mark.asyncio
async def test_explicit_insight_log_uses_content_reference(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_insight = "PRIVATE INSIGHT access_token=raw-insight-token-12345"

    class Provider:
        async def _store_insight(self, _insight, _session_id):
            return True

    engine = SimpleNamespace(_insight_provider=Provider())
    logger = logging.getLogger("semantic-memory-privacy-test")
    caplog.set_level(logging.INFO, logger=logger.name)

    stored = await store_explicit_insight_impl(
        engine,
        "user-private-123",
        raw_insight,
        "preference",
        "session-1",
        logger,
    )

    assert stored is True
    assert "content_ref=sha256:" in caplog.text
    assert "user_hash=sha256:" in caplog.text
    assert raw_insight not in caplog.text
    assert "raw-insight-token" not in caplog.text
    assert "user-private-123" not in caplog.text
