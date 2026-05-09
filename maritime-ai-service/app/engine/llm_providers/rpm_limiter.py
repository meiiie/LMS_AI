"""Sliding-window rate limiter for outbound LLM API calls.

Pattern: client-side proactive throttle. Cap requests-per-minute (RPM) before
the upstream provider (NVIDIA NIM, Google Gemini, ...) starts returning 429.

Why client-side > server-side retry:
- 429 retry adds latency for the user (extra round-trip + backoff sleep)
- Some providers ban for sustained overage instead of just throttling
- Reservoir of in-flight requests is invisible to caller without RPM cap

Pattern (Anthropic best-practice 2026):
- Sliding 60s window
- asyncio.Lock around deque mutation (single-process safe)
- Per-provider instance (NVIDIA limit ≠ Google limit)
- Off by default (rpm=0) — opt-in via env var
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class SlidingWindowRpmLimiter:
    """Cap calls to N per 60 seconds. Sleeps caller when cap exceeded."""

    def __init__(self, rpm: int, *, name: str = "llm"):
        self._cap = max(int(rpm), 0)
        self._window = 60.0
        self._calls: deque = deque()
        self._lock = asyncio.Lock()
        self._name = name
        self._waited_count = 0
        self._waited_total_ms = 0.0

    @property
    def enabled(self) -> bool:
        return self._cap > 0

    async def acquire(self) -> None:
        """Block until acquiring a slot. No-op when limiter disabled."""
        if not self.enabled:
            return

        async with self._lock:
            now = time.monotonic()
            # Evict expired calls outside the 60s window.
            while self._calls and now - self._calls[0] >= self._window:
                self._calls.popleft()

            if len(self._calls) >= self._cap:
                # Wait for oldest call to roll out of window.
                wait_s = self._window - (now - self._calls[0]) + 0.05
                if wait_s > 0:
                    self._waited_count += 1
                    self._waited_total_ms += wait_s * 1000.0
                    if self._waited_count <= 3 or self._waited_count % 50 == 0:
                        logger.info(
                            "[RPM_LIMITER] %s cap=%d hit; sleeping %.2fs (total waits=%d)",
                            self._name, self._cap, wait_s, self._waited_count,
                        )
                    # Release lock during sleep — let other waiters retry.
                    self._lock.release()
                    try:
                        await asyncio.sleep(wait_s)
                    finally:
                        await self._lock.acquire()
                # Re-check window after sleep (concurrent acquires may have eaten capacity).
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self._window:
                    self._calls.popleft()

            self._calls.append(time.monotonic())

    def stats(self) -> dict:
        return {
            "name": self._name,
            "rpm_cap": self._cap,
            "in_flight_window": len(self._calls),
            "wait_count": self._waited_count,
            "wait_total_ms": int(self._waited_total_ms),
        }


_PROVIDER_LIMITERS: dict[str, SlidingWindowRpmLimiter] = {}


def get_provider_rpm_limiter(provider: str) -> Optional[SlidingWindowRpmLimiter]:
    """Return (cached) limiter for a provider, or None when no cap configured.

    Env var convention: ``{PROVIDER_UPPER}_RPM_LIMIT`` (e.g. NVIDIA_RPM_LIMIT=30).
    Cached at first access — restart container to change the value.
    """
    key = (provider or "").strip().lower()
    if not key:
        return None

    if key in _PROVIDER_LIMITERS:
        existing = _PROVIDER_LIMITERS[key]
        return existing if existing.enabled else None

    try:
        from app.core.config import settings
        rpm = int(getattr(settings, f"{key}_rpm_limit", 0) or 0)
    except Exception:  # noqa: BLE001
        rpm = 0

    limiter = SlidingWindowRpmLimiter(rpm, name=key)
    _PROVIDER_LIMITERS[key] = limiter
    if limiter.enabled:
        logger.info("[RPM_LIMITER] enabled for %s @ %d req/min", key, rpm)
    return limiter if limiter.enabled else None
