"""
Tests for Web Search circuit breaker and timeout (Sprint 9).

Verifies:
- Circuit breaker opens after threshold failures
- Circuit breaker recovers after timeout
- Timeout handling for slow searches
- Success resets failure count

Sprint 198: Serper is now primary, DuckDuckGo is fallback.
Tests must disable Serper to exercise the DuckDuckGo/_search_sync path.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

import app.engine.tools.web_search_tools as ws


@pytest.fixture(autouse=True)
def disable_serper():
    """Force DuckDuckGo path by disabling Serper (Sprint 198).

    Without this, tool_web_search calls real Serper API if SERPER_API_KEY is set,
    bypassing any _search_sync patches.
    """
    with patch(
        "app.engine.tools.serper_web_search.is_serper_available",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def disable_layered_live_backends():
    """Keep resilience unit tests on the mocked DDG path only."""
    with patch(
        "app.engine.tools.web_search_tools._searxng_search_sync",
        return_value=[],
    ), patch(
        "app.engine.tools.web_search_tools._brave_search_sync",
        return_value=[],
    ), patch(
        "app.engine.tools.web_search_tools._augment_top_result_with_deep_fetch",
        side_effect=lambda results, _query: results,
    ), patch(
        "app.engine.tools.web_search_tools._merge_news_into_search",
        side_effect=lambda results, _query: results,
    ):
        yield


def _reset_cb():
    """Reset circuit breaker state."""
    with ws._cb_lock:
        ws._cb_states.clear()


class TestCircuitBreaker:
    """Test web search circuit breaker logic."""

    def setup_method(self):
        _reset_cb()

    def teardown_method(self):
        _reset_cb()

    def test_cb_initially_closed(self):
        """Circuit breaker starts closed (no failures)."""
        assert ws._cb_is_open() is False

    def test_cb_opens_after_threshold(self):
        """Circuit breaker opens after 3 consecutive failures."""
        for _ in range(ws._CB_THRESHOLD):
            ws._cb_record_failure()
        assert ws._cb_is_open() is True

    def test_cb_stays_closed_below_threshold(self):
        """Circuit breaker stays closed below threshold."""
        for _ in range(ws._CB_THRESHOLD - 1):
            ws._cb_record_failure()
        assert ws._cb_is_open() is False

    def test_cb_recovers_after_timeout(self):
        """Circuit breaker resets after recovery period."""
        for _ in range(ws._CB_THRESHOLD):
            ws._cb_record_failure()
        assert ws._cb_is_open() is True

        # Simulate time passing beyond recovery window
        with ws._cb_lock:
            ws._cb_states["default"]["last_failure"] = time.time() - ws._CB_RECOVERY_SECONDS - 1
        assert ws._cb_is_open() is False

    def test_success_resets_counter(self):
        """Successful search resets failure count."""
        ws._cb_record_failure()
        ws._cb_record_failure()
        with ws._cb_lock:
            assert ws._cb_states["default"]["failures"] == 2

        ws._cb_record_success()
        with ws._cb_lock:
            assert ws._cb_states["default"]["failures"] == 0

    def test_cb_open_returns_error_message(self):
        """When CB open, tool_web_search returns Vietnamese error."""
        for _ in range(ws._CB_THRESHOLD):
            ws._cb_record_failure("web_search")

        result = ws.tool_web_search.invoke("test query")
        assert "không khả dụng" in result

    def test_search_failure_increments_counter(self):
        """Search failure increments the failure counter."""
        with patch.object(ws, "_search_sync", side_effect=Exception("Network error")):
            ws.tool_web_search.invoke("test query")

        with ws._cb_lock:
            assert ws._cb_states["web_search"]["failures"] == 1

    def test_search_timeout_increments_counter(self):
        """Search timeout increments the failure counter."""
        import concurrent.futures

        def slow_search(*args, **kwargs):
            time.sleep(100)

        with patch.object(ws, "_search_sync", side_effect=slow_search):
            # Use a very short timeout for test
            original_timeout = ws.WEB_SEARCH_TIMEOUT
            ws.WEB_SEARCH_TIMEOUT = 0.01
            try:
                result = ws.tool_web_search.invoke("test query")
                with ws._cb_lock:
                    assert ws._cb_states["web_search"]["failures"] == 1
                assert "thời gian chờ" in result
            finally:
                ws.WEB_SEARCH_TIMEOUT = original_timeout


class TestSearchExecution:
    """Test web search execution paths."""

    def setup_method(self):
        _reset_cb()

    def teardown_method(self):
        _reset_cb()

    def test_successful_search(self):
        """Successful search returns formatted results."""
        mock_results = [
            {"title": "Test", "body": "Result body", "href": "https://example.com"}
        ]

        with patch.object(ws, "_search_sync", return_value=mock_results):
            result = ws.tool_web_search.invoke("test query")

        assert "Test" in result
        assert "example.com" in result
        with ws._cb_lock:
            state = ws._cb_states.get("web_search", {"failures": 0})
            assert state["failures"] == 0

    def test_empty_results(self):
        """Empty results return Vietnamese no-results message."""
        with patch.object(ws, "_search_sync", return_value=[]):
            result = ws.tool_web_search.invoke("test query")

        assert "Không tìm thấy" in result

    def test_import_error(self):
        """ImportError returns install instructions."""
        with patch.object(ws, "_search_sync", side_effect=ImportError("no module")):
            result = ws.tool_web_search.invoke("test query")

        assert "duckduckgo-search" in result


class TestConstants:
    """Test web search configuration constants."""

    def test_timeout_value(self):
        """Timeout should be reasonable (5-30 seconds)."""
        assert 5.0 <= ws.WEB_SEARCH_TIMEOUT <= 30.0

    def test_cb_threshold(self):
        """CB threshold should be 2-5 failures."""
        assert 2 <= ws._CB_THRESHOLD <= 5

    def test_cb_recovery_seconds(self):
        """CB recovery should be 60-300 seconds."""
        assert 60 <= ws._CB_RECOVERY_SECONDS <= 300
