"""Append-only durable event log per chat session.

Phase 5 of the runtime migration epic (issue #207). Borrows the
Anthropic Managed Agents pattern: harness (stateless control loop) +
session (this module — append-only log outside the context window) +
sandbox (pluggable execution).

Two backends share a single interface so call sites stay agnostic:

- ``InMemorySessionEventLog`` — feature flag off (default) or test mode.
  Per-session deque guarded by a process-local lock. Loses data on
  restart; fine while ``enable_session_event_log = False``.
- ``PostgresSessionEventLog`` — feature flag on. Writes through the
  existing async SQLAlchemy session. Enforces monotonic ``seq`` per
  session and surfaces ``org_id`` for multi-tenant filtering.

Event types are not enumerated as an enum on purpose — phases 5/6 will
add new ones (``tool_call``, ``tool_result``, ``assistant_chunk``, ...)
and a closed enum would force migration churn. Keep them as opaque
strings; observers filter by type.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional, Protocol

from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload

logger = logging.getLogger(__name__)
_DEFAULT_RECENT_EVENT_LIMIT = 50
_MAX_RECENT_EVENT_LIMIT = 500


def _safe_payload_dict(payload: object) -> dict:
    safe_payload = sanitize_runtime_payload(payload)
    return copy.deepcopy(safe_payload) if isinstance(safe_payload, dict) else {}


def _bounded_recent_limit(limit: int | None) -> int:
    if type(limit) is not int:
        return _DEFAULT_RECENT_EVENT_LIMIT
    return min(max(limit, 1), _MAX_RECENT_EVENT_LIMIT)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event_created_before(event: "SessionEvent", cutoff: datetime) -> bool:
    raw_value = event.created_at
    if not raw_value:
        return False
    try:
        value = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return _utc_datetime(value) < _utc_datetime(cutoff)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One immutable entry in a session's event log."""

    session_id: str
    event_type: str
    payload: dict
    seq: int
    org_id: Optional[str] = None
    created_at: Optional[str] = None


class SessionEventLog(Protocol):
    """Backend-agnostic interface every consumer depends on."""

    async def append(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict,
        org_id: Optional[str] = None,
    ) -> SessionEvent:
        ...

    async def get_events(
        self,
        *,
        session_id: str,
        org_id: Optional[str] = None,
        since_seq: Optional[int] = None,
    ) -> list[SessionEvent]:
        ...

    async def latest_seq(
        self, *, session_id: str, org_id: Optional[str] = None
    ) -> int:
        ...

    async def get_recent_events(
        self,
        *,
        org_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = _DEFAULT_RECENT_EVENT_LIMIT,
    ) -> list[SessionEvent]:
        ...

    async def prune_older_than(
        self,
        *,
        cutoff: datetime,
        org_id: Optional[str] = None,
        event_type: Optional[str] = None,
        dry_run: bool = True,
    ) -> int:
        ...


@dataclass
class _SessionState:
    seq: int = 0
    events: list[SessionEvent] = field(default_factory=list)


def _copy_event(event: SessionEvent) -> SessionEvent:
    return SessionEvent(
        session_id=event.session_id,
        event_type=event.event_type,
        payload=copy.deepcopy(event.payload),
        seq=event.seq,
        org_id=event.org_id,
        created_at=event.created_at,
    )


class InMemorySessionEventLog:
    """Process-local fallback used when the DB-backed log is disabled.

    Not durable across restarts. Suitable for tests and the default
    feature-flag-off path so consumers can call into the same interface
    without branching.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}
        self._events: list[SessionEvent] = []
        self._lock = asyncio.Lock()

    async def append(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict,
        org_id: Optional[str] = None,
    ) -> SessionEvent:
        async with self._lock:
            state = self._sessions.setdefault(session_id, _SessionState())
            state.seq += 1
            safe_payload = _safe_payload_dict(payload)
            event = SessionEvent(
                session_id=session_id,
                event_type=event_type,
                payload=safe_payload,
                seq=state.seq,
                org_id=org_id,
                created_at=datetime.now(UTC).isoformat(),
            )
            state.events.append(event)
            self._events.append(event)
            return _copy_event(event)

    async def get_events(
        self,
        *,
        session_id: str,
        org_id: Optional[str] = None,
        since_seq: Optional[int] = None,
    ) -> list[SessionEvent]:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return []
            events = state.events
            if org_id is not None:
                events = [e for e in events if e.org_id == org_id]
            if since_seq is not None:
                events = [e for e in events if e.seq > since_seq]
            return [_copy_event(e) for e in events]

    async def latest_seq(
        self, *, session_id: str, org_id: Optional[str] = None
    ) -> int:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return 0
            if org_id is None:
                return state.seq
            # When filtering by org, return the highest matching seq.
            for event in reversed(state.events):
                if event.org_id == org_id:
                    return event.seq
            return 0

    async def get_recent_events(
        self,
        *,
        org_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = _DEFAULT_RECENT_EVENT_LIMIT,
    ) -> list[SessionEvent]:
        async with self._lock:
            bounded_limit = _bounded_recent_limit(limit)
            events: list[SessionEvent] = []
            for event in reversed(self._events):
                if org_id is not None and event.org_id != org_id:
                    continue
                if event_type is not None and event.event_type != event_type:
                    continue
                events.append(event)
                if len(events) >= bounded_limit:
                    break
            return [_copy_event(e) for e in events]

    async def prune_older_than(
        self,
        *,
        cutoff: datetime,
        org_id: Optional[str] = None,
        event_type: Optional[str] = None,
        dry_run: bool = True,
    ) -> int:
        async with self._lock:
            def _matches(event: SessionEvent) -> bool:
                if org_id is not None and event.org_id != org_id:
                    return False
                if event_type is not None and event.event_type != event_type:
                    return False
                return _event_created_before(event, cutoff)

            removed_count = sum(1 for event in self._events if _matches(event))
            if dry_run or removed_count == 0:
                return removed_count

            self._events = [event for event in self._events if not _matches(event)]
            for session_id in list(self._sessions):
                state = self._sessions[session_id]
                state.events = [event for event in state.events if not _matches(event)]
                if not state.events:
                    del self._sessions[session_id]
            return removed_count


class PostgresSessionEventLog:
    """Durable Postgres backend for the append-only session event log.

    Phase 10 of the runtime migration epic (issue #207). Promotes
    ``InMemorySessionEventLog`` to a real Postgres-backed implementation
    using the existing ``asyncpg`` pool (``app.core.database``).

    Concurrency: append computes ``seq = COALESCE(MAX(seq), 0) + 1`` in
    the same statement and relies on the ``session_events_seq_unique``
    constraint shipped by Alembic 047. If two concurrent writers pick the
    same ``seq``, the second one hits the unique violation; we retry up
    to ``MAX_APPEND_RETRIES`` times. In practice the contention window is
    < 1ms so 3 retries is plenty.

    Multi-tenant: ``org_id`` is recorded and used as a filter on read.
    Callers responsible for not leaking session_id across tenants — the
    backend itself does not enforce a session-to-org binding because a
    session may be personal (NULL org) and migrate to an org later.
    """

    MAX_APPEND_RETRIES = 3

    async def _pool(self):
        from app.core.database import get_asyncpg_pool

        return await get_asyncpg_pool()

    async def append(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict,
        org_id: Optional[str] = None,
    ) -> SessionEvent:
        import asyncpg
        import json

        pool = await self._pool()
        safe_payload = _safe_payload_dict(payload)
        payload_json = json.dumps(safe_payload, ensure_ascii=False)

        last_exc: Optional[Exception] = None
        for _ in range(self.MAX_APPEND_RETRIES):
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO session_events
                            (session_id, org_id, event_type, payload, seq)
                        VALUES (
                            $1, $2, $3, $4::jsonb,
                            (SELECT COALESCE(MAX(seq), 0) + 1
                             FROM session_events
                             WHERE session_id = $1)
                        )
                        RETURNING id, session_id, org_id, event_type,
                                  payload, seq, created_at
                        """,
                        session_id,
                        org_id,
                        event_type,
                        payload_json,
                    )
                return _row_to_event(row)
            except asyncpg.UniqueViolationError as exc:  # contention retry
                last_exc = exc
                continue
        raise RuntimeError(
            "PostgresSessionEventLog.append exceeded retries"
        ) from last_exc

    async def get_events(
        self,
        *,
        session_id: str,
        org_id: Optional[str] = None,
        since_seq: Optional[int] = None,
    ) -> list[SessionEvent]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            params: list = [session_id]
            where = ["session_id = $1"]
            if org_id is not None:
                params.append(org_id)
                where.append(f"org_id = ${len(params)}")
            if since_seq is not None:
                params.append(since_seq)
                where.append(f"seq > ${len(params)}")

            sql = (
                "SELECT id, session_id, org_id, event_type, payload, seq, "
                "       created_at "
                "FROM session_events "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY seq ASC"
            )
            rows = await conn.fetch(sql, *params)
        return [_row_to_event(r) for r in rows]

    async def latest_seq(
        self, *, session_id: str, org_id: Optional[str] = None
    ) -> int:
        pool = await self._pool()
        async with pool.acquire() as conn:
            if org_id is None:
                seq = await conn.fetchval(
                    "SELECT COALESCE(MAX(seq), 0) "
                    "FROM session_events WHERE session_id = $1",
                    session_id,
                )
            else:
                seq = await conn.fetchval(
                    "SELECT COALESCE(MAX(seq), 0) "
                    "FROM session_events "
                    "WHERE session_id = $1 AND org_id = $2",
                    session_id,
                    org_id,
                )
        return int(seq or 0)

    async def get_recent_events(
        self,
        *,
        org_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = _DEFAULT_RECENT_EVENT_LIMIT,
    ) -> list[SessionEvent]:
        pool = await self._pool()
        bounded_limit = _bounded_recent_limit(limit)
        async with pool.acquire() as conn:
            params: list = []
            where: list[str] = []
            if org_id is not None:
                params.append(org_id)
                where.append(f"org_id = ${len(params)}")
            if event_type is not None:
                params.append(event_type)
                where.append(f"event_type = ${len(params)}")
            params.append(bounded_limit)
            limit_param = len(params)

            where_clause = f"WHERE {' AND '.join(where)} " if where else ""
            sql = (
                "SELECT id, session_id, org_id, event_type, payload, seq, "
                "       created_at "
                "FROM session_events "
                f"{where_clause}"
                "ORDER BY created_at DESC, id DESC "
                f"LIMIT ${limit_param}"
            )
            rows = await conn.fetch(sql, *params)
        return [_row_to_event(r) for r in rows]

    async def prune_older_than(
        self,
        *,
        cutoff: datetime,
        org_id: Optional[str] = None,
        event_type: Optional[str] = None,
        dry_run: bool = True,
    ) -> int:
        pool = await self._pool()
        cutoff_utc = _utc_datetime(cutoff)
        async with pool.acquire() as conn:
            params: list = [cutoff_utc]
            where = ["created_at < $1"]
            if org_id is not None:
                params.append(org_id)
                where.append(f"org_id = ${len(params)}")
            if event_type is not None:
                params.append(event_type)
                where.append(f"event_type = ${len(params)}")
            where_clause = " AND ".join(where)
            if dry_run:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM session_events WHERE {where_clause}",
                    *params,
                )
            else:
                count = await conn.fetchval(
                    "WITH deleted AS ("
                    f"DELETE FROM session_events WHERE {where_clause} "
                    "RETURNING 1"
                    ") SELECT COUNT(*) FROM deleted",
                    *params,
                )
        return int(count or 0)


def _row_to_event(row) -> SessionEvent:
    """Materialise an asyncpg row → ``SessionEvent``.

    ``payload`` arrives as a JSON string from asyncpg (jsonb column with
    no codec registered) so we json.loads it. Defensive against ``None``.
    """
    import json

    raw_payload = row["payload"] if row else None
    if isinstance(raw_payload, str):
        try:
            payload_dict = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError):
            payload_dict = {}
    elif isinstance(raw_payload, dict):
        payload_dict = raw_payload
    else:
        payload_dict = {}
    payload_dict = _safe_payload_dict(payload_dict)

    raw_created_at = None
    try:
        raw_created_at = row["created_at"] if row else None
    except (KeyError, TypeError):
        raw_created_at = None
    if hasattr(raw_created_at, "isoformat"):
        created_at = raw_created_at.isoformat()
    elif raw_created_at is not None:
        created_at = str(raw_created_at)
    else:
        created_at = None

    return SessionEvent(
        session_id=row["session_id"],
        event_type=row["event_type"],
        payload=payload_dict,
        seq=int(row["seq"]),
        org_id=row["org_id"],
        created_at=created_at,
    )


_singleton: Optional[SessionEventLog] = None


def get_session_event_log() -> SessionEventLog:
    """Return the configured event log instance.

    Routes to ``PostgresSessionEventLog`` when ``enable_session_event_log``
    is True; otherwise falls back to in-memory. The Postgres backend
    requires the asyncpg pool from ``app.core.database`` to be configured
    — when the flag is on but the pool is unreachable, callers get the
    Postgres backend object and individual ``append`` calls raise.
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    try:
        from app.core.config import settings
    except (ImportError, AttributeError):
        # Settings not importable yet (e.g. CLI tools, very early bootstrap).
        # Falling back to in-memory keeps the interface usable.
        logger.debug("[session_event_log] settings unavailable; using in-memory")
        _singleton = InMemorySessionEventLog()
        return _singleton

    if settings.enable_session_event_log:
        _singleton = PostgresSessionEventLog()
        return _singleton

    _singleton = InMemorySessionEventLog()
    return _singleton


def _reset_for_tests() -> None:
    """Clear the singleton — test fixtures only."""
    global _singleton
    _singleton = None


__all__ = [
    "SessionEvent",
    "SessionEventLog",
    "InMemorySessionEventLog",
    "PostgresSessionEventLog",
    "get_session_event_log",
]
