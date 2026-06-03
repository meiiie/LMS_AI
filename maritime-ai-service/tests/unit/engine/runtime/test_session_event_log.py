"""Phase 5 session event log — Runtime Migration #207.

Locks in the in-memory backend contract: monotonic seq, org filtering,
dict-payload immutability, since_seq replay window.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.engine.runtime.session_event_log import (
    InMemorySessionEventLog,
    SessionEvent,
    get_session_event_log,
)


@pytest.fixture
def log() -> InMemorySessionEventLog:
    return InMemorySessionEventLog()


# ── append ──

async def test_append_assigns_monotonic_seq_per_session(log):
    e1 = await log.append(session_id="s1", event_type="user_message", payload={"text": "hi"})
    e2 = await log.append(session_id="s1", event_type="assistant_message", payload={"text": "hello"})
    e3 = await log.append(session_id="s2", event_type="user_message", payload={"text": "x"})
    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 1  # different session, fresh counter


async def test_append_returns_immutable_event(log):
    payload = {"q": "x"}
    event = await log.append(session_id="s", event_type="tool_call", payload=payload)
    assert isinstance(event, SessionEvent)
    payload["q"] = "mutated"
    assert event.payload == {"q": "x"}  # snapshot, not aliased


async def test_append_returned_event_payload_cannot_mutate_inmemory_log(log):
    event = await log.append(
        session_id="s",
        event_type="tool_call",
        payload={"nested": {"q": "x"}},
    )

    event.payload["nested"]["q"] = "mutated"

    events = await log.get_events(session_id="s")
    assert events[0].payload == {"nested": {"q": "x"}}


async def test_append_records_org_id_when_supplied(log):
    event = await log.append(
        session_id="s", event_type="user_message", payload={}, org_id="org-1"
    )
    assert event.org_id == "org-1"
    assert event.created_at is not None


async def test_append_sanitizes_payload_before_storage(log):
    event = await log.append(
        session_id="s",
        event_type="tool_result",
        payload={
            "user_id": "raw-user-id",
            "args": {
                "message": "hello",
                "access_token": "raw-access-token",
            },
            "content": (
                '{"status":"ok","approval_token":"raw-approval-token",'
                '"data":{"safe_id":"post-1","provider_payload":{"id":"raw"}}}'
            ),
            "error": (
                "provider returned Bearer raw-bearer-token-123 "
                "api_key=raw-api-key-inline"
            ),
        },
    )

    assert event.payload["user_id_hash"].startswith("sha256:")
    assert event.payload["args"]["message"] == "hello"
    assert event.payload["content"]["status"] == "ok"
    assert event.payload["content"]["data"]["safe_id"] == "post-1"
    assert "<redacted-secret>" in event.payload["error"]
    serialized = str(event.payload)
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-approval-token" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "raw-api-key-inline" not in serialized
    assert "provider_payload" not in serialized


# ── get_events ──

async def test_get_events_returns_in_append_order(log):
    await log.append(session_id="s", event_type="user_message", payload={"i": 1})
    await log.append(session_id="s", event_type="user_message", payload={"i": 2})
    await log.append(session_id="s", event_type="user_message", payload={"i": 3})
    events = await log.get_events(session_id="s")
    assert [e.payload["i"] for e in events] == [1, 2, 3]


async def test_get_events_returns_payload_snapshots(log):
    await log.append(
        session_id="s",
        event_type="tool_call",
        payload={"nested": {"q": "x"}},
    )

    events = await log.get_events(session_id="s")
    events[0].payload["nested"]["q"] = "mutated"

    fresh_events = await log.get_events(session_id="s")
    assert fresh_events[0].payload == {"nested": {"q": "x"}}


async def test_get_events_unknown_session_returns_empty(log):
    assert await log.get_events(session_id="missing") == []


async def test_get_events_since_seq_filters_window(log):
    await log.append(session_id="s", event_type="x", payload={"i": 1})
    await log.append(session_id="s", event_type="x", payload={"i": 2})
    await log.append(session_id="s", event_type="x", payload={"i": 3})
    events = await log.get_events(session_id="s", since_seq=1)
    assert [e.seq for e in events] == [2, 3]


async def test_get_events_filters_by_org(log):
    await log.append(session_id="s", event_type="x", payload={}, org_id="A")
    await log.append(session_id="s", event_type="x", payload={}, org_id="B")
    await log.append(session_id="s", event_type="x", payload={}, org_id="A")
    a_events = await log.get_events(session_id="s", org_id="A")
    assert all(e.org_id == "A" for e in a_events)
    assert len(a_events) == 2


# ── latest_seq ──

async def test_latest_seq_zero_for_unknown_session(log):
    assert await log.latest_seq(session_id="missing") == 0


async def test_latest_seq_tracks_global_seq_without_org(log):
    await log.append(session_id="s", event_type="x", payload={})
    await log.append(session_id="s", event_type="x", payload={})
    assert await log.latest_seq(session_id="s") == 2


async def test_latest_seq_respects_org_filter(log):
    await log.append(session_id="s", event_type="x", payload={}, org_id="A")
    await log.append(session_id="s", event_type="x", payload={}, org_id="B")
    await log.append(session_id="s", event_type="x", payload={}, org_id="A")
    assert await log.latest_seq(session_id="s", org_id="A") == 3
    assert await log.latest_seq(session_id="s", org_id="B") == 2
    assert await log.latest_seq(session_id="s", org_id="C") == 0


# ── singleton ──

async def test_get_recent_events_filters_across_sessions(log):
    await log.append(
        session_id="s1",
        event_type="runtime_flow_ledger",
        payload={"i": 1},
        org_id="A",
    )
    await log.append(
        session_id="s2",
        event_type="user_message",
        payload={"i": 2},
        org_id="A",
    )
    await log.append(
        session_id="s3",
        event_type="runtime_flow_ledger",
        payload={"i": 3},
        org_id="B",
    )
    await log.append(
        session_id="s4",
        event_type="runtime_flow_ledger",
        payload={"i": 4},
        org_id="A",
    )

    events = await log.get_recent_events(
        org_id="A",
        event_type="runtime_flow_ledger",
        limit=5,
    )

    assert [(event.session_id, event.payload["i"]) for event in events] == [
        ("s4", 4),
        ("s1", 1),
    ]


async def test_get_recent_events_bounds_limit(log):
    for idx in range(3):
        await log.append(
            session_id=f"s{idx}",
            event_type="runtime_flow_ledger",
            payload={"i": idx},
        )

    events = await log.get_recent_events(
        event_type="runtime_flow_ledger",
        limit=0,
    )

    assert len(events) == 1
    assert events[0].payload["i"] == 2


def _rewrite_created_at(log: InMemorySessionEventLog, event: SessionEvent, created_at: str) -> None:
    rewritten = SessionEvent(
        session_id=event.session_id,
        event_type=event.event_type,
        payload=event.payload,
        seq=event.seq,
        org_id=event.org_id,
        created_at=created_at,
    )
    state = log._sessions[event.session_id]
    state.events = [
        rewritten if item.seq == event.seq and item.session_id == event.session_id else item
        for item in state.events
    ]
    log._events = [
        rewritten if item.seq == event.seq and item.session_id == event.session_id else item
        for item in log._events
    ]


async def test_prune_older_than_dry_run_counts_without_deleting(log):
    old = await log.append(
        session_id="s-old",
        event_type="runtime_flow_ledger",
        payload={"i": 1},
        org_id="A",
    )
    kept = await log.append(
        session_id="s-new",
        event_type="runtime_flow_ledger",
        payload={"i": 2},
        org_id="A",
    )
    _rewrite_created_at(log, old, "2026-05-01T00:00:00+00:00")
    _rewrite_created_at(log, kept, "2026-05-20T00:00:00+00:00")

    count = await log.prune_older_than(
        cutoff=datetime(2026, 5, 10, tzinfo=UTC),
        org_id="A",
        event_type="runtime_flow_ledger",
        dry_run=True,
    )

    assert count == 1
    assert len(await log.get_recent_events(org_id="A", event_type="runtime_flow_ledger")) == 2


async def test_prune_older_than_removes_matching_events_only(log):
    old_a = await log.append(session_id="s-a", event_type="runtime_flow_ledger", payload={"i": 1}, org_id="A")
    old_b = await log.append(session_id="s-b", event_type="runtime_flow_ledger", payload={"i": 2}, org_id="B")
    new_a = await log.append(session_id="s-c", event_type="runtime_flow_ledger", payload={"i": 3}, org_id="A")
    _rewrite_created_at(log, old_a, "2026-05-01T00:00:00+00:00")
    _rewrite_created_at(log, old_b, "2026-05-01T00:00:00+00:00")
    _rewrite_created_at(log, new_a, "2026-05-20T00:00:00+00:00")

    count = await log.prune_older_than(
        cutoff=datetime(2026, 5, 10, tzinfo=UTC),
        org_id="A",
        event_type="runtime_flow_ledger",
        dry_run=False,
    )

    assert count == 1
    assert [event.payload["i"] for event in await log.get_recent_events(event_type="runtime_flow_ledger", limit=10)] == [3, 2]


def test_get_session_event_log_returns_singleton():
    a = get_session_event_log()
    b = get_session_event_log()
    assert a is b


# ── concurrency safety ──

async def test_concurrent_appends_preserve_monotonic_seq(log):
    import asyncio

    async def write(idx: int) -> SessionEvent:
        return await log.append(
            session_id="s", event_type="x", payload={"i": idx}
        )

    events = await asyncio.gather(*(write(i) for i in range(20)))
    seqs = sorted(e.seq for e in events)
    assert seqs == list(range(1, 21))


# ── PostgresSessionEventLog ──

class _FakeRow(dict):
    """Mimic asyncpg.Record minimal interface."""

    def __getitem__(self, key):
        return super().__getitem__(key)


class _FakeConn:
    def __init__(self, rows=None, fetchval_value=0, raise_unique_n_times: int = 0):
        self.rows = rows or []
        self.fetchval_value = fetchval_value
        self.raise_unique_n_times = raise_unique_n_times
        self.fetchrow_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []
        self.fetchval_calls: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        if self.raise_unique_n_times > 0:
            self.raise_unique_n_times -= 1
            import asyncpg
            raise asyncpg.UniqueViolationError("duplicate seq")
        if self.rows:
            return self.rows.pop(0)
        # Default: synthesise a row using args.
        session_id, org_id, event_type, payload_json = args
        return _FakeRow(
            id=1,
            session_id=session_id,
            org_id=org_id,
            event_type=event_type,
            payload=payload_json,
            seq=1,
            created_at="2026-05-03T00:00:00Z",
        )

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self.rows

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return self.fetchval_value


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    def acquire(self):
        outer = self

        class _CtxManager:
            async def __aenter__(self):
                return outer._conn

            async def __aexit__(self, *exc):
                return None

        return _CtxManager()


@pytest.fixture
def fake_conn() -> _FakeConn:
    return _FakeConn()


@pytest.fixture
def pg_log(monkeypatch, fake_conn: _FakeConn):
    """PostgresSessionEventLog with the asyncpg pool mocked out."""
    from app.engine.runtime.session_event_log import PostgresSessionEventLog

    log = PostgresSessionEventLog()
    fake_pool = _FakePool(fake_conn)

    async def _pool_stub():
        return fake_pool

    monkeypatch.setattr(log, "_pool", _pool_stub)
    return log


async def test_postgres_append_round_trips_payload(pg_log, fake_conn):
    event = await pg_log.append(
        session_id="s1", event_type="user_message", payload={"text": "hi"}, org_id="org-1"
    )
    assert event.session_id == "s1"
    assert event.event_type == "user_message"
    assert event.payload == {"text": "hi"}
    assert event.org_id == "org-1"
    assert event.seq == 1
    assert event.created_at == "2026-05-03T00:00:00Z"
    # SQL was issued with the right shape — no jsonb cast missing etc.
    sql_first, args = fake_conn.fetchrow_calls[0]
    assert "INSERT INTO session_events" in sql_first
    assert "$4::jsonb" in sql_first
    assert args[0] == "s1"
    assert args[2] == "user_message"


async def test_postgres_append_retries_on_unique_violation(pg_log, fake_conn):
    fake_conn.raise_unique_n_times = 2  # succeed on 3rd try
    event = await pg_log.append(
        session_id="s1", event_type="x", payload={}
    )
    assert event.seq == 1
    assert len(fake_conn.fetchrow_calls) == 3


async def test_postgres_append_gives_up_after_max_retries(pg_log, fake_conn):
    fake_conn.raise_unique_n_times = 99  # always fail
    with pytest.raises(RuntimeError, match="exceeded retries"):
        await pg_log.append(session_id="s1", event_type="x", payload={})


async def test_postgres_get_events_filters_by_org(pg_log, fake_conn):
    fake_conn.rows = [
        _FakeRow(
            id=1, session_id="s", org_id="A", event_type="x",
            payload='{"i": 1}', seq=1, created_at=None,
        ),
        _FakeRow(
            id=2, session_id="s", org_id="A", event_type="x",
            payload='{"i": 2}', seq=2, created_at=None,
        ),
    ]
    events = await pg_log.get_events(session_id="s", org_id="A", since_seq=0)
    sql, args = fake_conn.fetch_calls[0]
    assert "ORDER BY seq ASC" in sql
    assert "session_id = $1" in sql
    assert "org_id = $2" in sql
    assert "seq > $3" in sql
    assert args == ("s", "A", 0)
    assert len(events) == 2
    assert events[0].payload == {"i": 1}


async def test_postgres_latest_seq_with_org(pg_log, fake_conn):
    fake_conn.fetchval_value = 5
    seq = await pg_log.latest_seq(session_id="s", org_id="A")
    assert seq == 5
    sql, args = fake_conn.fetchval_calls[0]
    assert "WHERE session_id = $1 AND org_id = $2" in sql
    assert args == ("s", "A")


async def test_postgres_latest_seq_without_org(pg_log, fake_conn):
    fake_conn.fetchval_value = 0
    seq = await pg_log.latest_seq(session_id="missing")
    assert seq == 0


async def test_postgres_get_recent_events_filters_by_org_and_event_type(
    pg_log,
    fake_conn,
):
    fake_conn.rows = [
        _FakeRow(
            id=1,
            session_id="s-new",
            org_id="A",
            event_type="runtime_flow_ledger",
            payload='{"i": 2}',
            seq=1,
            created_at=None,
        ),
        _FakeRow(
            id=2,
            session_id="s-old",
            org_id="A",
            event_type="runtime_flow_ledger",
            payload='{"i": 1}',
            seq=1,
            created_at=None,
        ),
    ]

    events = await pg_log.get_recent_events(
        org_id="A",
        event_type="runtime_flow_ledger",
        limit=25,
    )

    sql, args = fake_conn.fetch_calls[0]
    assert "org_id = $1" in sql
    assert "event_type = $2" in sql
    assert "ORDER BY created_at DESC, id DESC" in sql
    assert "LIMIT $3" in sql
    assert args == ("A", "runtime_flow_ledger", 25)
    assert [event.session_id for event in events] == ["s-new", "s-old"]


async def test_postgres_prune_older_than_dry_run_counts_matching_rows(
    pg_log,
    fake_conn,
):
    fake_conn.fetchval_value = 7
    count = await pg_log.prune_older_than(
        cutoff=datetime(2026, 5, 10, tzinfo=UTC),
        org_id="A",
        event_type="runtime_flow_ledger",
        dry_run=True,
    )

    sql, args = fake_conn.fetchval_calls[0]
    assert count == 7
    assert "SELECT COUNT(*) FROM session_events" in sql
    assert "created_at < $1" in sql
    assert "org_id = $2" in sql
    assert "event_type = $3" in sql
    assert args[1:] == ("A", "runtime_flow_ledger")


async def test_postgres_prune_older_than_deletes_matching_rows(
    pg_log,
    fake_conn,
):
    fake_conn.fetchval_value = 4
    count = await pg_log.prune_older_than(
        cutoff=datetime(2026, 5, 10, tzinfo=UTC),
        org_id=None,
        event_type="runtime_flow_ledger",
        dry_run=False,
    )

    sql, args = fake_conn.fetchval_calls[0]
    assert count == 4
    assert "DELETE FROM session_events" in sql
    assert "RETURNING 1" in sql
    assert "created_at < $1" in sql
    assert "event_type = $2" in sql
    assert args[1:] == ("runtime_flow_ledger",)


async def test_postgres_payload_revives_str_jsonb(pg_log, fake_conn):
    """asyncpg returns jsonb as str; backend must json.loads."""
    fake_conn.rows = [
        _FakeRow(
            id=1, session_id="s", org_id=None, event_type="x",
            payload='{"a": 1, "b": "two"}', seq=1, created_at=None,
        ),
    ]
    events = await pg_log.get_events(session_id="s")
    assert events[0].payload == {"a": 1, "b": "two"}


# ── get_session_event_log routing ──

async def test_postgres_payload_sanitizes_legacy_rows_on_read(pg_log, fake_conn):
    fake_conn.rows = [
        _FakeRow(
            id=1,
            session_id="s",
            org_id=None,
            event_type="tool_result",
            payload=(
                '{"user_id":"raw-user-id","content":'
                '"{\\"status\\":\\"ok\\",\\"approval_token\\":\\"raw-approval-token\\"}",'
                '"error":"Authorization: Bearer raw-bearer-token-123",'
                '"access_token":"raw-access-token"}'
            ),
            seq=1,
            created_at=None,
        ),
    ]

    events = await pg_log.get_events(session_id="s")

    assert events[0].payload["user_id_hash"].startswith("sha256:")
    assert events[0].payload["content"]["status"] == "ok"
    assert events[0].payload["content"]["redacted_secret_count"] == 1
    assert "<redacted-secret>" in events[0].payload["error"]
    serialized = str(events[0].payload)
    assert "raw-user-id" not in serialized
    assert "raw-approval-token" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "raw-access-token" not in serialized


def test_get_session_event_log_returns_inmemory_when_flag_off(monkeypatch):
    from app.engine.runtime import session_event_log as mod

    mod._reset_for_tests()
    fake_settings = type("S", (), {"enable_session_event_log": False})()
    monkeypatch.setattr(
        "app.core.config.settings", fake_settings, raising=False
    )
    log = mod.get_session_event_log()
    assert isinstance(log, mod.InMemorySessionEventLog)


def test_get_session_event_log_returns_postgres_when_flag_on(monkeypatch):
    from app.engine.runtime import session_event_log as mod

    mod._reset_for_tests()
    fake_settings = type("S", (), {"enable_session_event_log": True})()
    monkeypatch.setattr(
        "app.core.config.settings", fake_settings, raising=False
    )
    log = mod.get_session_event_log()
    assert isinstance(log, mod.PostgresSessionEventLog)
    mod._reset_for_tests()
