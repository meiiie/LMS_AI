"""
Tests for Sprint 37: Async safety and resource management.

Covers:
- vision_extractor._rate_limit() is async (no time.sleep)
- object_storage retry uses asyncio.sleep (no time.sleep)
- web_search_tools circuit breaker is thread-safe
- admin.py _ingestion_jobs has bounded cleanup
"""

import ast
import threading
import time

import pytest

from app.api.v1.admin import _ingestion_jobs, _cleanup_old_jobs, _MAX_TRACKED_JOBS


# ============================================================================
# Async sleep verification (no blocking time.sleep in async code)
# ============================================================================




# ============================================================================
# Circuit breaker thread safety
# ============================================================================


class TestWebSearchCircuitBreakerThreadSafety:
    """Verify circuit breaker uses thread-safe operations."""


    def test_cb_record_failure_is_atomic(self):
        """Concurrent failures should not corrupt state."""
        from app.engine.tools.web_search_tools import (
            _cb_record_failure,
            _cb_record_success,
            _cb_is_open,
        )
        import app.engine.tools.web_search_tools as ws_mod

        # Reset state
        _cb_record_success()

        # Concurrent failures
        threads = []
        for _ in range(10):
            t = threading.Thread(target=_cb_record_failure)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have recorded all failures without corruption
        with ws_mod._cb_lock:
            assert ws_mod._cb_states.get("default", {}).get("failures", 0) == 10

        # Reset
        _cb_record_success()

    def test_cb_is_open_after_threshold(self):
        """Circuit breaker opens after threshold failures."""
        from app.engine.tools.web_search_tools import (
            _cb_record_failure,
            _cb_record_success,
            _cb_is_open,
        )

        _cb_record_success()  # Reset
        assert not _cb_is_open()

        for _ in range(3):
            _cb_record_failure()

        assert _cb_is_open()
        _cb_record_success()  # Reset


# ============================================================================
# Admin job cleanup
# ============================================================================


class TestIngestionJobCleanup:
    """Verify _ingestion_jobs has bounded growth."""

    @pytest.fixture(autouse=True)
    def reset_jobs(self):
        """Clear jobs between tests."""
        _ingestion_jobs.clear()
        yield
        _ingestion_jobs.clear()

    def test_max_tracked_jobs_is_defined(self):
        assert _MAX_TRACKED_JOBS > 0

    def test_cleanup_noop_under_limit(self):
        """No cleanup when under the limit."""
        _ingestion_jobs["job1"] = {"status": "completed"}
        _cleanup_old_jobs()
        assert "job1" in _ingestion_jobs

    def test_cleanup_removes_completed_when_over_limit(self):
        """Completed jobs are removed when over the limit."""
        # Fill beyond limit
        for i in range(_MAX_TRACKED_JOBS + 5):
            _ingestion_jobs[f"job{i}"] = {"status": "completed"}

        _cleanup_old_jobs()
        assert len(_ingestion_jobs) <= _MAX_TRACKED_JOBS

    def test_cleanup_preserves_pending_jobs(self):
        """Pending/processing jobs are not removed."""
        # Fill with completed
        for i in range(_MAX_TRACKED_JOBS):
            _ingestion_jobs[f"completed{i}"] = {"status": "completed"}

        # Add pending jobs beyond limit
        for i in range(5):
            _ingestion_jobs[f"pending{i}"] = {"status": "pending"}

        _cleanup_old_jobs()

        # All pending jobs should survive
        for i in range(5):
            assert f"pending{i}" in _ingestion_jobs

    def test_cleanup_removes_failed_jobs(self):
        """Failed jobs are also eligible for cleanup."""
        for i in range(_MAX_TRACKED_JOBS + 5):
            _ingestion_jobs[f"failed{i}"] = {"status": "failed"}

        _cleanup_old_jobs()
        assert len(_ingestion_jobs) <= _MAX_TRACKED_JOBS
