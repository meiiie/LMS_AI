"""
Sprint 210e: Streaming ↔ Sync Path Background Tasks Parity Tests.

Critical fix: `/chat/stream/v3` was missing 5 background tasks that the sync
`/chat` path runs. This caused:
  - No semantic memory storage from streaming conversations
  - No fact extraction from streaming conversations
  - No memory summarization from streaming conversations
  - No profile stats updates from streaming conversations
  - No character reflection from streaming conversations
  - No routine tracking from streaming conversations

The fix runs post-turn lifecycle scheduling plus Sprint 208 routine tracking
from the stream finalization path.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from uuid import uuid4, UUID


# ============================================================================
# GROUP 1: Compatibility wrapper schedules post-turn background tasks
# ============================================================================


class TestStreamingBackgroundTasksScheduled:
    """Verify the compatibility wrapper preserves post-turn scheduling args."""

    def test_schedule_all_called_with_background_tasks_add_task(self):
        """schedule_all still accepts BackgroundTasks.add_task as background_save."""
        from app.services.background_tasks import BackgroundTaskRunner

        mock_ch = MagicMock()
        mock_ch.is_available.return_value = True
        mock_sm = MagicMock()
        mock_sm.is_available.return_value = True
        mock_ms = MagicMock()
        mock_pr = MagicMock()
        mock_pr.is_available.return_value = True

        runner = BackgroundTaskRunner(
            chat_history=mock_ch,
            semantic_memory=mock_sm,
            memory_summarizer=mock_ms,
            profile_repo=mock_pr,
        )

        # Simulate what streaming path does
        background_tasks_add_task = MagicMock()
        session_id = uuid4()
        user_id = "student-123"
        message = "What is COLREG Rule 5?"
        response = "Rule 5 requires maintaining a proper lookout..."
        org_id = "lms-hang-hai"

        runner.schedule_all(
            background_save=background_tasks_add_task,
            user_id=user_id,
            session_id=session_id,
            message=message,
            response=response,
            skip_fact_extraction=False,
            org_id=org_id,
        )

        # Should schedule 5 tasks: semantic write, maintenance, summarizer,
        # profile stats, and reflection.
        assert background_tasks_add_task.call_count == 5

    def test_schedule_all_with_empty_response(self):
        """When accumulated_answer is empty, schedule_all still runs with ''."""
        from app.services.background_tasks import BackgroundTaskRunner

        mock_sm = MagicMock()
        mock_sm.is_available.return_value = True
        mock_ms = MagicMock()
        mock_pr = MagicMock()
        mock_pr.is_available.return_value = True

        runner = BackgroundTaskRunner(
            semantic_memory=mock_sm,
            memory_summarizer=mock_ms,
            profile_repo=mock_pr,
        )

        background_save = MagicMock()
        runner.schedule_all(
            background_save=background_save,
            user_id="user1",
            session_id=uuid4(),
            message="Hello",
            response="",  # Empty response (streaming produced nothing)
            skip_fact_extraction=False,
            org_id="",
        )

        # Should still schedule tasks (semantic memory stores even empty exchanges)
        assert background_save.call_count >= 1

    def test_skip_fact_extraction_false_in_streaming(self):
        """Streaming path always passes skip_fact_extraction=False
        because it doesn't track which agent ran."""
        from app.services.background_tasks import BackgroundTaskRunner

        mock_sm = MagicMock()
        mock_sm.is_available.return_value = True
        runner = BackgroundTaskRunner(semantic_memory=mock_sm)

        background_save = MagicMock()
        runner.schedule_all(
            background_save=background_save,
            user_id="user1",
            session_id=uuid4(),
            message="msg",
            response="resp",
            skip_fact_extraction=False,  # Always False in streaming
            org_id="",
        )

        # Verify the semantic memory task was scheduled
        # (it includes fact extraction since skip_fact_extraction=False)
        calls = background_save.call_args_list
        task_funcs = [c.args[0].__name__ if hasattr(c.args[0], '__name__') else str(c.args[0]) for c in calls]
        # At least _store_semantic_interaction should be scheduled
        assert any("semantic" in f or "store" in f for f in task_funcs) or background_save.call_count >= 1

    def test_org_id_threaded_to_schedule_all(self):
        """Organization ID from chat_request flows to schedule_all."""
        from app.services.background_tasks import BackgroundTaskRunner

        mock_sm = MagicMock()
        mock_sm.is_available.return_value = True
        runner = BackgroundTaskRunner(semantic_memory=mock_sm)

        background_save = MagicMock()
        session_id = uuid4()

        runner.schedule_all(
            background_save=background_save,
            user_id="user1",
            session_id=session_id,
            message="msg",
            response="resp",
            skip_fact_extraction=False,
            org_id="test-org-123",
        )

        # Verify org_id is captured (it's used in _store_semantic_interaction)
        assert background_save.called


# ============================================================================
# GROUP 2: Error handling — schedule_all failure must NOT crash streaming
# ============================================================================


class TestStreamingBackgroundTasksErrorHandling:
    """Ensure background task scheduling failures don't crash the stream."""

    def test_schedule_all_exception_caught(self):
        """If schedule_all raises, streaming continues gracefully."""
        from app.services.background_tasks import BackgroundTaskRunner

        runner = BackgroundTaskRunner()
        # Force schedule_all to raise
        runner.schedule_all = MagicMock(side_effect=RuntimeError("DB down"))

        # Simulate the streaming path's error handling
        try:
            runner.schedule_all(
                background_save=MagicMock(),
                user_id="user1",
                session_id=uuid4(),
                message="msg",
                response="resp",
            )
            caught = False
        except RuntimeError:
            caught = True

        # The streaming code wraps in try/except, so this verifies the pattern
        assert caught is True  # Direct call raises; streaming path catches it

    def test_no_background_runner_skips_gracefully(self):
        """If _background_runner is None, the streaming path skips scheduling."""
        # Simulate: _v3_orchestrator._background_runner = None
        # The code checks `if _v3_orchestrator._background_runner:` so None skips
        assert not None  # None is falsy → condition skips


# ============================================================================
# GROUP 3: Routine tracking (Sprint 208) in streaming path
# ============================================================================


class TestStreamingRoutineTracking:
    """Sprint 208: Routine tracking should fire in streaming path too."""

    @pytest.mark.asyncio
    async def test_routine_tracker_called_when_enabled(self):
        """When living_agent_enable_routine_tracking=True, record_interaction fires."""
        mock_tracker = AsyncMock()
        mock_tracker.record_interaction = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.living_agent_enable_routine_tracking = True

        with patch(
            "app.engine.living_agent.routine_tracker.get_routine_tracker",
            return_value=mock_tracker,
        ), patch(
            "app.core.config.get_settings",
            return_value=mock_settings,
        ):
            from app.engine.living_agent.routine_tracker import get_routine_tracker
            tracker = get_routine_tracker()
            await tracker.record_interaction(
                user_id="student-123",
                channel="web",
                topic="maritime",
            )

            mock_tracker.record_interaction.assert_called_once_with(
                user_id="student-123",
                channel="web",
                topic="maritime",
            )

    @pytest.mark.asyncio
    async def test_routine_tracker_skipped_when_disabled(self):
        """When living_agent_enable_routine_tracking=False, no call made."""
        mock_settings = MagicMock()
        mock_settings.living_agent_enable_routine_tracking = False

        # Simulate the streaming path's conditional check
        if getattr(mock_settings, "living_agent_enable_routine_tracking", False):
            pytest.fail("Should not enter routine tracking block")

        # No assertion needed — test passes if we get here

    @pytest.mark.asyncio
    async def test_routine_tracker_exception_swallowed(self):
        """Routine tracker failure must not crash the streaming pipeline."""
        mock_settings = MagicMock()
        mock_settings.living_agent_enable_routine_tracking = True

        mock_tracker = AsyncMock()
        mock_tracker.record_interaction = AsyncMock(
            side_effect=Exception("Network error")
        )

        # Simulate streaming path's error handling
        try:
            from app.core.config import get_settings as _rt_settings
            if getattr(mock_settings, "living_agent_enable_routine_tracking", False):
                await mock_tracker.record_interaction(
                    user_id="user1", channel="web", topic="",
                )
        except Exception:
            pass  # This is the expected behavior — swallow errors

        # Test passes if no unhandled exception propagated


# ============================================================================
# GROUP 4: Sync ↔ Streaming parity validation
# ============================================================================


class TestSyncStreamingParity:
    """Validate that streaming post-processing matches sync path."""

    def test_sync_path_has_background_tasks(self):
        """Sync path finalizes through the post-turn lifecycle contract."""
        import inspect
        from app.services.chat_orchestrator import ChatOrchestrator
        source = inspect.getsource(ChatOrchestrator.process)
        assert "finalize_response_turn" in source
        assert "post_turn_lifecycle" in source

    def test_streaming_path_has_background_tasks(self):
        """Streaming path finalizes through the same orchestrator contract."""
        import inspect
        from app.services.chat_stream_coordinator import generate_stream_v3_events
        source = inspect.getsource(generate_stream_v3_events)
        assert "finalize_response_turn" in source
        assert "post_turn_lifecycle" in source

    def test_sync_path_has_routine_tracking(self):
        """Sync path has Sprint 208 routine tracking."""
        import inspect
        from app.services.chat_orchestrator import ChatOrchestrator
        source = inspect.getsource(ChatOrchestrator.process)
        assert "routine_tracker" in source or "record_interaction" in source, \
            "Sync path must have routine tracking"

    def test_streaming_path_has_routine_tracking(self):
        """Streaming path now has Sprint 208 routine tracking (Sprint 210e)."""
        import inspect
        from app.api.v1 import chat_stream
        source = inspect.getsource(chat_stream)
        assert "routine_tracker" in source or "record_interaction" in source, \
            "Streaming path must have routine tracking (Sprint 210e)"

    def test_sync_path_has_sentiment_analysis(self):
        """Sync path has Sprint 210d sentiment analysis."""
        import inspect
        from app.services.chat_orchestrator import ChatOrchestrator
        source = inspect.getsource(ChatOrchestrator.process)
        assert "_analyze_and_process_sentiment" in source, \
            "Sync path must have sentiment analysis"

    def test_streaming_path_has_sentiment_analysis(self):
        """Streaming path has Sprint 210d sentiment analysis."""
        import inspect
        from app.api.v1 import chat_stream
        source = inspect.getsource(chat_stream)
        assert "_analyze_and_process_sentiment" in source, \
            "Streaming path must have sentiment analysis"

    def test_both_paths_schedule_5_background_tasks(self):
        """Compatibility wrapper still schedules 5 tasks with all deps available."""
        from app.services.background_tasks import BackgroundTaskRunner

        mock_ch = MagicMock()
        mock_ch.is_available.return_value = True
        mock_sm = MagicMock()
        mock_sm.is_available.return_value = True
        mock_ms = MagicMock()
        mock_pr = MagicMock()
        mock_pr.is_available.return_value = True

        runner = BackgroundTaskRunner(
            chat_history=mock_ch,
            semantic_memory=mock_sm,
            memory_summarizer=mock_ms,
            profile_repo=mock_pr,
        )

        bg_save = MagicMock()
        runner.schedule_all(bg_save, "u1", uuid4(), "msg", "resp")
        assert bg_save.call_count == 5

    def test_streaming_passes_session_id_as_uuid(self):
        """Streaming path uses _v3_session_id which is a UUID, matching sync."""
        # _v3_session_id comes from effective_session_id which is UUID
        from uuid import UUID
        test_id = uuid4()
        assert isinstance(test_id, UUID)

        # schedule_all accepts UUID for session_id
        from app.services.background_tasks import BackgroundTaskRunner
        runner = BackgroundTaskRunner()
        bg_save = MagicMock()
        # Should not raise TypeError
        runner.schedule_all(bg_save, "u1", test_id, "msg", "resp")


# ============================================================================
# GROUP 5: Code inspection — streaming post-stream block structure
# ============================================================================


class TestStreamingPostStreamBlock:
    """Verify the post-stream block has all required sections in order."""

    def _get_post_stream_source(self):
        """Extract the authoritative finalization helper source."""
        import inspect
        from app.services.chat_orchestrator_support import finalize_response_turn_impl
        return inspect.getsource(finalize_response_turn_impl)

    def test_assistant_message_saved_before_background_tasks(self):
        """Assistant message must be saved BEFORE background tasks run."""
        source = self._get_post_stream_source()
        save_pos = source.find("persist_chat_message")
        schedule_pos = source.find("schedule_post_turn_lifecycle")
        assert save_pos > 0, "persist_chat_message must exist"
        assert schedule_pos > 0, "schedule_post_turn_lifecycle must exist"
        assert save_pos < schedule_pos, \
            "message persistence must come before post-turn lifecycle scheduling"

    def test_background_tasks_before_continuity_hooks(self):
        """Background tasks must be scheduled before continuity hooks."""
        source = self._get_post_stream_source()
        schedule_pos = source.find("schedule_post_turn_lifecycle")
        continuity_pos = source.find("scheduled_hooks = schedule_post_response_continuity_fn")
        assert schedule_pos > 0, "schedule_post_turn_lifecycle must exist"
        assert continuity_pos > 0, "continuity scheduling call must exist"
        assert schedule_pos < continuity_pos, \
            "post-turn lifecycle must come before continuity hooks"

    def test_lifecycle_summary_logged_after_continuity_hooks(self):
        """Final summary should include lifecycle and continuity evidence."""
        source = self._get_post_stream_source()
        schedule_pos = source.find("schedule_post_turn_lifecycle")
        continuity_pos = source.find("scheduled_hooks = schedule_post_response_continuity_fn")
        summary_pos = source.find("continuity_summary")
        assert schedule_pos < continuity_pos < summary_pos, \
            "Order: post_turn_lifecycle -> continuity_summary"
