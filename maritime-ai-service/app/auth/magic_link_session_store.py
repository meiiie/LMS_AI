"""
TASK-2026-04-25-002: Distributed magic-link session store.

Two implementations of a common ``MagicLinkSessionStore`` Protocol:

* ``InMemorySessionStore`` — wraps the legacy dict logic. Single-process only.
  Used when ``enable_distributed_magic_link_sessions=False`` or Valkey is
  unreachable. Preserves bit-for-bit existing behaviour.

* ``ValkeySessionStore`` — survives FastAPI restarts and multi-worker
  deployments. Each worker keeps WebSockets it owns in a local dict;
  cross-worker handoff happens via Valkey **PUB/SUB** on
  ``magic_link_push:{session_id}`` plus a TTL-bounded cache key at
  ``magic_link_session:{session_id}`` (so a publish that beats the WS
  subscribe is not lost).

Call sites use ``register / push_tokens / remove / reap_stale / active_count`` —
identical to the original ``MagicLinkSessionManager``. The factory is exposed
as ``get_session_store()`` (sync) and ``initialize_session_store()`` (async,
called once from the FastAPI lifespan).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Protocol, runtime_checkable

from fastapi import WebSocket

from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)


logger = logging.getLogger(__name__)
_REDACTED_SECRET = "<redacted-secret>"
_MAX_DIAGNOSTIC_ERROR_LENGTH = 500


def _session_ref(session_id: str) -> str:
    return hash_runtime_identifier(session_id) or "sha256:empty"


def _iter_payload_strings(value: Any, *, _depth: int = 0) -> Iterator[str]:
    if _depth > 4:
        return
    if isinstance(value, str):
        if value:
            yield value
        return
    if isinstance(value, dict):
        for item in list(value.values())[:32]:
            yield from _iter_payload_strings(item, _depth=_depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for item in list(value)[:32]:
            yield from _iter_payload_strings(item, _depth=_depth + 1)


def _safe_magic_link_error(
    exc: Any,
    *secret_values: Any,
    payload: Any = None,
) -> str:
    text = str(exc or "")
    seen: set[str] = set()
    for raw_secret in (*secret_values, *_iter_payload_strings(payload)):
        secret = str(raw_secret or "")
        if not secret or secret in seen:
            continue
        seen.add(secret)
        text = text.replace(secret, _REDACTED_SECRET)
    return redact_runtime_secret_text(
        text,
        max_length=_MAX_DIAGNOSTIC_ERROR_LENGTH,
    )


# ---------------------------------------------------------------------------
# Protocol + shared types
# ---------------------------------------------------------------------------

@dataclass
class _SessionEntry:
    """Local-process WebSocket entry. ``created_at`` is monotonic seconds."""

    websocket: WebSocket
    created_at: float


@runtime_checkable
class MagicLinkSessionStore(Protocol):
    """Common API for in-memory and Valkey-backed implementations."""

    async def register(self, session_id: str, websocket: WebSocket) -> None: ...
    async def push_tokens(self, session_id: str, payload: dict) -> bool: ...
    def remove(self, session_id: str) -> None: ...
    def reap_stale(self, max_age_seconds: float) -> int: ...
    async def aclose(self) -> None: ...
    @property
    def active_count(self) -> int: ...


# ---------------------------------------------------------------------------
# In-memory store (legacy fallback)
# ---------------------------------------------------------------------------

class InMemorySessionStore:
    """Single-process WebSocket session map. Identical semantics to the
    original ``MagicLinkSessionManager``."""

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionEntry] = {}

    async def register(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sessions[session_id] = _SessionEntry(
            websocket=websocket, created_at=time.monotonic()
        )
        logger.info(
            "Magic link WS session registered (in-memory) session_ref=%s",
            _session_ref(session_id),
        )

    async def push_tokens(self, session_id: str, payload: dict) -> bool:
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            logger.warning(
                "Magic link WS session not found session_ref=%s",
                _session_ref(session_id),
            )
            return False
        try:
            await entry.websocket.send_json(payload)
            await entry.websocket.close()
            logger.info(
                "Magic link tokens pushed (in-memory) session_ref=%s",
                _session_ref(session_id),
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to push tokens to WS session_ref=%s: %s",
                _session_ref(session_id),
                _safe_magic_link_error(exc, session_id, payload=payload),
            )
            return False

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def reap_stale(self, max_age_seconds: float) -> int:
        if max_age_seconds <= 0:
            return 0
        now = time.monotonic()
        stale_ids = [
            sid for sid, entry in self._sessions.items()
            if (now - entry.created_at) > max_age_seconds
        ]
        for sid in stale_ids:
            self._sessions.pop(sid, None)
        if stale_ids:
            logger.info("In-memory reaper dropped %d stale session(s)", len(stale_ids))
        return len(stale_ids)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    async def aclose(self) -> None:
        """Drop all session entries. In-memory store has no other resources."""
        self._sessions.clear()


# ---------------------------------------------------------------------------
# Valkey-backed store (distributed)
# ---------------------------------------------------------------------------

_KEY_PREFIX = "magic_link_session"
_CHANNEL_PREFIX = "magic_link_push"


class ValkeySessionStore:
    """Cross-worker magic-link session store backed by Valkey PUB/SUB.

    Local state: each worker keeps a dict of WebSockets it physically owns.
    Distributed handoff: ``push_tokens`` SETs the payload at
    ``magic_link_session:{sid}`` with TTL and PUBLISHes it to
    ``magic_link_push:{sid}``. A per-session subscriber task in the WS-owning
    worker forwards the message to the WebSocket and exits.

    Race-safety: ``register`` subscribes BEFORE checking the cached key,
    so a publish that arrives during ``register`` is not lost.
    """

    def __init__(self, redis_client: Any, default_ttl_seconds: int) -> None:
        self._redis = redis_client
        self._default_ttl = max(60, int(default_ttl_seconds))
        self._sessions: Dict[str, _SessionEntry] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    # -- public API --------------------------------------------------------

    async def register(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sessions[session_id] = _SessionEntry(
            websocket=websocket, created_at=time.monotonic()
        )
        # Per-session subscriber task — auto-exits after first delivery
        self._tasks[session_id] = asyncio.create_task(self._wait_for_push(session_id))
        logger.info(
            "Magic link WS session registered (Valkey) session_ref=%s",
            _session_ref(session_id),
        )

    async def push_tokens(self, session_id: str, payload: dict) -> bool:
        # Local-first: same worker as the WS, deliver directly without Valkey hop
        if session_id in self._sessions:
            return await self._deliver_local(session_id, payload)

        # Cross-worker: persist + publish. TTL-bounded so a late WS picks it up
        # but a never-arriving WS doesn't leave junk forever.
        try:
            body = json.dumps(payload, ensure_ascii=False)
            await self._redis.set(
                f"{_KEY_PREFIX}:{session_id}", body, ex=self._default_ttl
            )
            await self._redis.publish(f"{_CHANNEL_PREFIX}:{session_id}", body)
            logger.info(
                "Magic link tokens published to Valkey session_ref=%s",
                _session_ref(session_id),
            )
            return True
        except Exception as exc:
            # Per spec: log + raise rather than silently dropping
            logger.error(
                "Valkey push_tokens failed session_ref=%s: %s",
                _session_ref(session_id),
                _safe_magic_link_error(exc, session_id, payload=payload),
            )
            raise

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        task = self._tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()

    def reap_stale(self, max_age_seconds: float) -> int:
        if max_age_seconds <= 0:
            return 0
        now = time.monotonic()
        stale_ids = [
            sid for sid, entry in self._sessions.items()
            if (now - entry.created_at) > max_age_seconds
        ]
        for sid in stale_ids:
            self.remove(sid)
        if stale_ids:
            logger.info("Valkey reaper dropped %d stale session(s)", len(stale_ids))
        return len(stale_ids)

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    async def aclose(self) -> None:
        """Cancel every in-flight subscriber task and close the Valkey client.

        Called from the FastAPI lifespan shutdown so the asyncio event loop
        does not leave dangling pubsub subscriptions when the worker exits.
        Idempotent — safe to call twice.
        """
        # Snapshot tasks before mutating maps, then cancel them all
        pending = [task for task in self._tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            # Await cancellation cleanup; never raise from shutdown
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._sessions.clear()

        close = getattr(self._redis, "aclose", None) or getattr(
            self._redis, "close", None
        )
        if close is not None:
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "Valkey client close failed during aclose: %s",
                    _safe_magic_link_error(exc),
                )

    # -- internals ---------------------------------------------------------

    async def _deliver_local(self, session_id: str, payload: dict) -> bool:
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return False
        # Cancel the subscriber task — we delivered ourselves
        task = self._tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
        try:
            await entry.websocket.send_json(payload)
            await entry.websocket.close()
            return True
        except Exception as exc:
            logger.error(
                "Local WS delivery failed session_ref=%s: %s",
                _session_ref(session_id),
                _safe_magic_link_error(exc, session_id, payload=payload),
            )
            return False

    async def _wait_for_push(self, session_id: str) -> None:
        """Subscribe → check cache → deliver on first message. Exits after one delivery."""
        pubsub = None
        try:
            pubsub = self._redis.pubsub()
            channel = f"{_CHANNEL_PREFIX}:{session_id}"
            await pubsub.subscribe(channel)

            # Race-safety: a publish may have happened between push and our subscribe.
            # The TTL'd key holds the payload, so check it after the subscribe is in place.
            cached = await self._redis.get(f"{_KEY_PREFIX}:{session_id}")
            if cached is not None:
                await self._consume_payload(session_id, cached)
                return

            # Wait for a publish. Iterate until we see a real message.
            async for msg in pubsub.listen():
                if msg.get("type") not in ("message", "pmessage"):
                    continue
                await self._consume_payload(session_id, msg.get("data"))
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Valkey subscriber failed session_ref=%s: %s",
                _session_ref(session_id),
                _safe_magic_link_error(exc, session_id),
            )
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                except Exception:
                    pass
                close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
                if close is not None:
                    try:
                        result = close()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        pass

    async def _consume_payload(self, session_id: str, raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception as exc:
            logger.error(
                "Valkey payload decode failed session_ref=%s: %s",
                _session_ref(session_id),
                _safe_magic_link_error(exc, session_id, raw),
            )
            return
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return
        try:
            await entry.websocket.send_json(payload)
            await entry.websocket.close()
            logger.info(
                "Magic link tokens delivered via Valkey session_ref=%s",
                _session_ref(session_id),
            )
        except Exception as exc:
            logger.error(
                "WS delivery after Valkey publish failed session_ref=%s: %s",
                _session_ref(session_id),
                _safe_magic_link_error(exc, session_id, payload=payload),
            )


# ---------------------------------------------------------------------------
# Factory + lifespan integration
# ---------------------------------------------------------------------------

_active_store: Optional[MagicLinkSessionStore] = None


def get_session_store() -> MagicLinkSessionStore:
    """Synchronous accessor for the active session store.

    Defaults to ``InMemorySessionStore`` until ``initialize_session_store``
    runs from the FastAPI lifespan.
    """
    global _active_store
    if _active_store is None:
        _active_store = InMemorySessionStore()
    return _active_store


async def initialize_session_store(settings_obj: Any) -> MagicLinkSessionStore:
    """Pick the session store based on settings + Valkey reachability.

    Falls back to in-memory on any error. App MUST never fail to boot
    because Valkey is down.
    """
    global _active_store

    if not getattr(settings_obj, "enable_distributed_magic_link_sessions", False):
        _active_store = InMemorySessionStore()
        logger.info("Magic link session store: in-memory (distributed gate off)")
        return _active_store

    valkey_url = getattr(settings_obj, "valkey_url", "") or ""
    if not valkey_url:
        logger.warning(
            "enable_distributed_magic_link_sessions=True but valkey_url is empty; "
            "falling back to in-memory store"
        )
        _active_store = InMemorySessionStore()
        return _active_store

    try:
        import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]
    except ImportError as exc:
        logger.warning(
            "redis.asyncio not installed (%s); falling back to in-memory store",
            _safe_magic_link_error(exc),
        )
        _active_store = InMemorySessionStore()
        return _active_store

    try:
        client = redis_asyncio.from_url(
            valkey_url,
            decode_responses=False,
            socket_connect_timeout=2.0,
        )
        await client.ping()
        ttl = int(getattr(settings_obj, "magic_link_ws_timeout_seconds", 900))
        _active_store = ValkeySessionStore(client, default_ttl_seconds=ttl)
        logger.info("Magic link session store: Valkey enabled (TTL=%ds)", ttl)
        return _active_store
    except Exception as exc:
        logger.error(
            "Valkey connection failed (%s); falling back to in-memory store",
            _safe_magic_link_error(exc, valkey_url),
        )
        _active_store = InMemorySessionStore()
        return _active_store


def reset_session_store_for_tests() -> None:
    """Clear the cached singleton — TEST-ONLY helper."""
    global _active_store
    _active_store = None
