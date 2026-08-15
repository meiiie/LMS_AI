"""
Tests for Sprint 27: per-request token tracking core.

The LangChain-era ``TokenTrackingCallback`` and ``LLMPool._attach_tracking_callback``
were deleted with epic #207 — nothing fired LangChain-style callbacks after
``BaseChatModel`` was removed. Native recording now lives in ``WiiiChatModel``
(see ``test_wiii_chat_model_usage_tracking.py``); this file keeps coverage for
the tracker primitives themselves.
"""

from app.core.token_tracker import (
    TokenTracker,
    start_tracking,
    get_tracker,
    record_llm_call,
    _current_tracker,
)


class TestTrackerCore:
    """ContextVar lifecycle for the per-request tracker."""

    def test_start_tracking_sets_context_tracker(self):
        tracker = start_tracking("req-core")
        assert get_tracker() is tracker
        assert isinstance(tracker, TokenTracker)
        _current_tracker.set(None)

    def test_record_llm_call_without_tracker_is_noop(self):
        _current_tracker.set(None)
        record_llm_call(
            model="gemini-3.1-flash-lite-preview",
            tier="moderate",
            input_tokens=10,
            output_tokens=5,
        )
        assert get_tracker() is None


class TestTokenTrackerSummary:
    """Tracker aggregation over recorded calls."""

    def test_summary_after_multiple_calls(self):
        """Summary should aggregate all recorded calls."""
        tracker = start_tracking("req-summary")

        record_llm_call(
            model="gemini-3.1-flash-lite-preview",
            tier="moderate",
            input_tokens=100,
            output_tokens=50,
        )
        record_llm_call(
            model="gemini-3.1-flash-lite-preview",
            tier="light",
            input_tokens=30,
            output_tokens=15,
        )

        summary = tracker.summary()

        assert summary["total_calls"] == 2
        assert summary["total_input_tokens"] == 130
        assert summary["total_output_tokens"] == 65
        assert summary["total_tokens"] == 195
        assert "estimated_cost_usd" in summary
        assert "duration_ms" in summary

        _current_tracker.set(None)
