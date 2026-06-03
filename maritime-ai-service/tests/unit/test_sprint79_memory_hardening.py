"""
Tests for Sprint 79: Memory System Hardening — Persistent Summaries & Cross-Session Continuity

Part 1: Running Summary Persistence (9 tests)
Part 2: Session Summary Milestones (5 tests)
Part 3: Integration (6 tests)
Part 4: Debug Logging Cleanup (1 test)
Part 5: Auto-Summarize Previous Session (4 tests)
Part 6: Pronoun Style Persistence (8 tests)
Part 7: Repository Running Summary Methods (5 tests)

Total: 38 tests
"""

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Pre-populate to break circular import chain:
# app.services.__init__ → chat_service → multi_agent.graph → agents → tutor_node
# → services.__init__ (circular)
# Only set mock if module not already loaded (avoid polluting real modules)
if "app.services.chat_service" not in sys.modules:
    _mock_chat_svc = types.ModuleType("app.services.chat_service")
    _mock_chat_svc.ChatService = MagicMock  # noqa: F811
    _mock_chat_svc.get_chat_service = MagicMock
    _mock_chat_svc.reset_chat_service = MagicMock
    sys.modules["app.services.chat_service"] = _mock_chat_svc

from app.engine.messages import Message


# =============================================================================
# Helpers
# =============================================================================


def _make_history(n: int, content_len: int = 100) -> list:
    """Create n history entries."""
    history = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Message {i}: " + "x" * content_len
        history.append({"role": role, "content": content})
    return history


def _mock_db_factory(rows=None, side_effect=None):
    """Create a mock session factory that returns configurable results."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    if side_effect:
        mock_session.execute.side_effect = side_effect
    else:
        mock_result.fetchone.return_value = rows
        mock_session.execute.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    factory = MagicMock(return_value=mock_session)
    return factory, mock_session


def _close_background_coro(coro):
    """Close mocked background coroutines so tests do not leak warnings."""
    coro.close()
    return MagicMock()


# =============================================================================
# Part 1: Running Summary Persistence
# =============================================================================


class TestRunningSummaryPersistence:
    """Sprint 79 Gap 1: Running summary persisted to DB."""

    def test_get_running_summary_cache_hit(self):
        """Cache hit returns in-memory summary without DB call."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()
        # Sprint 125: composite cache key is "user1::s1"
        compactor._running_summaries["user1::s1"] = "Cached summary"

        result = compactor.get_running_summary("s1", user_id="user1")
        assert result == "Cached summary"

    def test_get_running_summary_db_fallback(self):
        """Cache miss with user_id loads from DB."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        factory, mock_session = _mock_db_factory(rows=("DB summary",))

        with patch("app.core.database.get_shared_session_factory", return_value=factory):
            result = compactor.get_running_summary("s1", user_id="user1")

        assert result == "DB summary"
        # Sprint 125: composite cache key
        assert compactor._running_summaries["user1::s1"] == "DB summary"

    def test_get_running_summary_db_empty(self):
        """Cache miss + empty DB returns empty string."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        factory, _ = _mock_db_factory(rows=None)

        with patch("app.core.database.get_shared_session_factory", return_value=factory):
            result = compactor.get_running_summary("s1", user_id="user1")

        assert result == ""
        assert "s1" not in compactor._running_summaries

    def test_set_running_summary_persists_to_db(self):
        """set_running_summary writes to DB when user_id provided."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        factory, mock_session = _mock_db_factory()

        with patch("app.core.database.get_shared_session_factory", return_value=factory), \
             patch.object(compactor, "_persist_session_summary"):
            compactor.set_running_summary("s1", "New summary", user_id="user1")

        # Sprint 125: composite cache key
        assert compactor._running_summaries["user1::s1"] == "New summary"
        # DB write happened (DELETE + INSERT = 2 execute calls)
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    def test_set_running_summary_empty_clears_both(self):
        """Empty summary clears both cache and DB."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()
        # Sprint 125: composite cache key
        compactor._running_summaries["user1::s1"] = "Old summary"

        factory, mock_session = _mock_db_factory()

        with patch("app.core.database.get_shared_session_factory", return_value=factory):
            compactor.set_running_summary("s1", "", user_id="user1")

        assert "user1::s1" not in compactor._running_summaries
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_clear_session_deletes_from_db(self):
        """clear_session removes from DB when user_id provided."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()
        # Sprint 125: composite cache key
        compactor._running_summaries["user1::s1"] = "Summary"

        factory, mock_session = _mock_db_factory()

        with patch("app.core.database.get_shared_session_factory", return_value=factory):
            compactor.clear_session("s1", user_id="user1")

        assert "user1::s1" not in compactor._running_summaries
        mock_session.execute.assert_called_once()

    def test_persist_graceful_on_db_error(self):
        """DB error during persist doesn't crash — logged and swallowed."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        with patch(
            "app.core.database.get_shared_session_factory",
            side_effect=Exception("DB down"),
        ):
            compactor.set_running_summary("s1", "Summary", user_id="user1")

        # In-memory still updated (Sprint 125: composite cache key)
        assert compactor._running_summaries["user1::s1"] == "Summary"

    def test_load_graceful_on_db_error(self):
        """DB unavailable during load returns empty string."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        with patch(
            "app.core.database.get_shared_session_factory",
            side_effect=Exception("DB down"),
        ):
            result = compactor.get_running_summary("s1", user_id="user1")

        assert result == ""

    def test_backward_compat_no_user_id(self):
        """Omitting user_id = in-memory only, no DB calls."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        with patch("app.core.database.get_shared_session_factory") as mock_factory:
            compactor.set_running_summary("s1", "Summary")
            result = compactor.get_running_summary("s1")

        assert result == "Summary"
        mock_factory.assert_not_called()

    def test_running_summary_blocks_missing_org_context_before_cache_or_db(
        self,
        monkeypatch,
    ):
        """Multi-tenant production without org must not read cache or DB."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()
        compactor._running_summaries["user1::s1"] = "Legacy unscoped summary"
        compactor._running_summaries["org-A::user1::s1"] = "Org A summary"

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                result = compactor.get_running_summary("s1", user_id="user1")
                compactor.set_running_summary("s1", "Blocked summary", user_id="user1")
                compactor.clear_session("s1", user_id="user1")
        finally:
            current_org_id.reset(token)

        assert result == ""
        assert "Blocked summary" not in compactor._running_summaries.values()
        assert compactor._running_summaries["user1::s1"] == "Legacy unscoped summary"
        assert compactor._running_summaries["org-A::user1::s1"] == "Org A summary"
        mock_factory.assert_not_called()

    def test_running_summary_cache_is_scoped_per_org(self, monkeypatch):
        """Same user/session pair keeps separate cached summaries per org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        factory, _ = _mock_db_factory()

        with patch("app.core.database.get_shared_session_factory", return_value=factory), \
             patch.object(compactor, "_persist_session_summary"):
            token = current_org_id.set("org-A")
            try:
                compactor.set_running_summary("s1", "Org A summary", user_id="user1")
            finally:
                current_org_id.reset(token)

            token = current_org_id.set("org-B")
            try:
                compactor.set_running_summary("s1", "Org B summary", user_id="user1")
            finally:
                current_org_id.reset(token)

        token = current_org_id.set("org-A")
        try:
            assert compactor.get_running_summary("s1", user_id="user1") == "Org A summary"
        finally:
            current_org_id.reset(token)

        token = current_org_id.set("org-B")
        try:
            assert compactor.get_running_summary("s1", user_id="user1") == "Org B summary"
        finally:
            current_org_id.reset(token)

        assert compactor._running_summaries["org-A::user1::s1"] == "Org A summary"
        assert compactor._running_summaries["org-B::user1::s1"] == "Org B summary"

    def test_running_summary_db_read_filters_by_current_org(self, monkeypatch):
        """DB fallback reads only the request-scoped organization."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        factory, mock_session = _mock_db_factory(rows=("DB summary",))

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=factory):
                result = compactor.get_running_summary("s2", user_id="user1")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert result == "DB summary"
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert compactor._running_summaries["org-A::user1::s2"] == "DB summary"


# =============================================================================
# Part 2: Session Summary Milestones
# =============================================================================


class TestSessionSummaryMilestones:
    """Sprint 79 Gap 2: Auto-generate session summaries at message milestones."""

    def test_upsert_thread_returns_message_count_update(self):
        """upsert_thread return dict includes message_count (update path)."""
        from app.repositories.thread_repository import ThreadRepository

        repo = ThreadRepository()

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("tid", 5, {})
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        repo._session_factory = MagicMock(return_value=mock_session)
        repo._initialized = True

        result = repo.upsert_thread(
            thread_id="tid", user_id="u1", domain_id="maritime"
        )

        assert result is not None
        assert result["message_count"] == 6  # 5 + 1

    def test_upsert_thread_returns_message_count_insert(self):
        """upsert_thread return dict includes message_count (insert path)."""
        from app.repositories.thread_repository import ThreadRepository

        repo = ThreadRepository()

        mock_session = MagicMock()
        mock_select = MagicMock()
        mock_select.fetchone.return_value = None
        mock_insert = MagicMock()
        mock_session.execute.side_effect = [mock_select, mock_insert]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        repo._session_factory = MagicMock(return_value=mock_session)
        repo._initialized = True

        result = repo.upsert_thread(
            thread_id="tid", user_id="u1", domain_id="maritime"
        )

        assert result is not None
        assert result["message_count"] == 1

    @pytest.mark.asyncio
    async def test_summary_triggered_at_milestone_6(self):
        """asyncio.create_task called when message_count hits milestone 6."""
        from app.engine.multi_agent import graph as graph_mod

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "final_response": "test",
            "sources": [],
            "agent_outputs": {},
        })

        mock_repo = MagicMock()
        mock_repo.upsert_thread.return_value = {
            "thread_id": "tid", "user_id": "u1",
            "domain_id": "maritime", "title": "Test",
            "message_count": 6,
        }

        with patch("app.engine.multi_agent.runner.get_wiii_runner", return_value=mock_runner), \
             patch("app.engine.agents.get_agent_registry") as mock_reg, \
             patch.object(graph_mod, "_build_domain_config", return_value={}), \
             patch.object(graph_mod, "_build_turn_local_state_defaults", return_value={}), \
             patch.object(graph_mod, "_inject_host_context", return_value=None), \
             patch("app.repositories.thread_repository.get_thread_repository", return_value=mock_repo), \
             patch("app.core.token_tracker.start_tracking"), \
             patch("app.core.token_tracker.get_tracker", return_value=None), \
             patch("asyncio.create_task", side_effect=_close_background_coro) as mock_create_task:

            mock_reg.return_value.start_request_trace.return_value = "t1"
            mock_reg.return_value.end_request_trace.return_value = {"span_count": 0, "total_duration_ms": 0}

            await graph_mod.process_with_multi_agent(
                query="Test", user_id="u1", session_id="s1"
            )

            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_summary_trigger_passes_org_scope(self):
        """Milestone summary jobs inherit the thread org scope."""
        from app.engine.multi_agent.graph_process import _upsert_thread_view

        mock_repo = MagicMock()
        mock_repo.upsert_thread.return_value = {
            "thread_id": "tid",
            "message_count": 6,
        }

        summary_calls = []

        def _fake_summary(thread_id, user_id, organization_id=None):
            summary_calls.append((thread_id, user_id, organization_id))

            async def _noop():
                return None

            return _noop()

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ), patch(
            "app.core.thread_utils.build_thread_id",
            return_value="thread-org",
        ), patch(
            "asyncio.create_task",
            side_effect=_close_background_coro,
        ) as mock_create_task:
            await _upsert_thread_view(
                query="Test",
                user_id="u1",
                session_id="s1",
                domain_id="maritime",
                context={"organization_id": "org-active"},
                summary_milestones={6},
                generate_session_summary_bg=_fake_summary,
            )

        mock_repo.upsert_thread.assert_called_once_with(
            thread_id="thread-org",
            user_id="u1",
            domain_id="maritime",
            title="Test",
            organization_id="org-active",
        )
        mock_create_task.assert_called_once()
        assert summary_calls == [("thread-org", "u1", "org-active")]

    @pytest.mark.asyncio
    async def test_summary_not_triggered_below_threshold(self):
        """No trigger when message_count is not a milestone."""
        from app.engine.multi_agent import graph as graph_mod

        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "final_response": "test",
            "sources": [],
            "agent_outputs": {},
        })

        mock_repo = MagicMock()
        mock_repo.upsert_thread.return_value = {
            "thread_id": "tid", "user_id": "u1",
            "domain_id": "maritime", "title": "Test",
            "message_count": 5,  # NOT a milestone
        }

        with patch("app.engine.multi_agent.runner.get_wiii_runner", return_value=mock_runner), \
             patch("app.engine.agents.get_agent_registry") as mock_reg, \
             patch.object(graph_mod, "_build_domain_config", return_value={}), \
             patch.object(graph_mod, "_build_turn_local_state_defaults", return_value={}), \
             patch.object(graph_mod, "_inject_host_context", return_value=None), \
             patch("app.repositories.thread_repository.get_thread_repository", return_value=mock_repo), \
             patch("app.core.token_tracker.start_tracking"), \
             patch("app.core.token_tracker.get_tracker", return_value=None), \
             patch("asyncio.create_task") as mock_create_task:

            mock_reg.return_value.start_request_trace.return_value = "t1"
            mock_reg.return_value.end_request_trace.return_value = {"span_count": 0, "total_duration_ms": 0}

            await graph_mod.process_with_multi_agent(
                query="Test", user_id="u1", session_id="s1"
            )

            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_summary_failure_non_blocking(self):
        """Exception in _generate_session_summary_bg doesn't propagate."""
        from app.engine.multi_agent.graph import _generate_session_summary_bg

        with patch(
            "app.services.session_summarizer.get_session_summarizer",
            side_effect=Exception("Summarizer unavailable"),
        ):
            await _generate_session_summary_bg("tid", "u1")


# =============================================================================
# Part 3: Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for Sprint 79 changes."""

    @pytest.mark.asyncio
    async def test_compact_persists_session_summary(self):
        """Compaction saves summary to thread_views via _persist_session_summary."""
        from app.engine.context_manager import ConversationCompactor

        compactor = ConversationCompactor()

        with patch.object(compactor, "_persist_summary_to_db"), \
             patch.object(compactor, "_persist_session_summary") as mock_persist:
            compactor.set_running_summary("s1", "Compacted summary", user_id="u1")

        mock_persist.assert_called_once_with("s1", "u1", "Compacted summary")

    def test_persist_session_summary_calls_thread_repo(self):
        """_persist_session_summary calls thread_repository.update_extra_data."""
        from app.engine.context_manager import ConversationCompactor
        from app.engine.semantic_memory.write_audit import MemoryWriteScope

        compactor = ConversationCompactor()

        mock_repo = MagicMock()
        mock_repo.update_extra_data.return_value = True

        with patch("app.core.thread_utils.build_thread_id", return_value="user_u1__session_s1"), \
             patch("app.repositories.thread_repository.get_thread_repository", return_value=mock_repo):
            compactor._persist_session_summary(
                "s1",
                "u1",
                "Summary text",
                scope=MemoryWriteScope(
                    org_id="org-active",
                    state="request_scoped",
                    warnings=[],
                    write_allowed=True,
                ),
            )

        mock_repo.update_extra_data.assert_called_once_with(
            "user_u1__session_s1",
            "u1",
            {"summary": "Summary text"},
            organization_id="org-active",
        )

    @pytest.mark.asyncio
    async def test_input_processor_passes_user_id(self):
        """input_processor.build_context passes user_id to compactor.maybe_compact."""
        from app.services.input_processor import InputProcessor
        from app.models.schemas import ChatRequest, UserRole

        processor = InputProcessor()

        request = MagicMock(spec=ChatRequest)
        request.user_id = "test_user"
        request.message = "Hello"
        request.role = UserRole.STUDENT
        request.user_context = None

        session_id = uuid4()

        with patch("app.engine.context_manager.get_compactor") as mock_get:
            mock_compactor = MagicMock()
            mock_compactor.maybe_compact = AsyncMock(return_value=(
                "", [Message(role="user", content="hi")],
                MagicMock(
                    total_used=50, total_budget=20000, utilization=0.002,
                    messages_included=1, messages_dropped=0, has_summary=False,
                ),
            ))
            mock_get.return_value = mock_compactor

            await processor.build_context(request, session_id)

        # Verify user_id was passed
        call_kwargs = mock_compactor.maybe_compact.call_args
        assert call_kwargs.kwargs.get("user_id") == "test_user"

    @pytest.mark.asyncio
    async def test_context_api_compact_passes_user_id(self):
        """POST /context/compact passes user_id to force_compact."""
        from app.api.v1.chat import compact_context

        mock_request = MagicMock()
        mock_request.headers = {"X-Session-ID": "test-session"}
        mock_auth = MagicMock()
        mock_auth.user_id = "test_user"

        with patch("app.engine.context_manager.get_compactor") as mock_get, \
             patch("app.repositories.chat_history_repository.get_chat_history_repository") as mock_hist:

            mock_compactor = MagicMock()
            mock_compactor.force_compact = AsyncMock(return_value="Summary")
            mock_get.return_value = mock_compactor

            mock_history = MagicMock()
            mock_history.is_available.return_value = False
            mock_hist.return_value = mock_history

            result = await compact_context(mock_request, mock_auth)

        assert result.status_code == 200
        call_kwargs = mock_compactor.force_compact.call_args
        assert call_kwargs.kwargs.get("user_id") == "test_user"

    @pytest.mark.asyncio
    async def test_context_api_clear_passes_user_id(self):
        """POST /context/clear passes user_id to clear_session."""
        from app.api.v1.chat import clear_context

        mock_request = MagicMock()
        mock_request.headers = {"X-Session-ID": "test-session"}
        mock_auth = MagicMock()
        mock_auth.user_id = "test_user"

        with patch("app.engine.context_manager.get_compactor") as mock_get, \
             patch("app.engine.memory_summarizer.get_memory_summarizer") as mock_summ:

            mock_compactor = MagicMock()
            mock_get.return_value = mock_compactor
            mock_summarizer = MagicMock()
            mock_summ.return_value = mock_summarizer

            result = await clear_context(mock_request, mock_auth)

        assert result.status_code == 200
        mock_compactor.clear_session.assert_called_once_with(
            "test-session", user_id="test_user"
        )

    @pytest.mark.asyncio
    async def test_maybe_compact_passes_user_id_through(self):
        """maybe_compact passes user_id to get_running_summary."""
        from app.engine.context_manager import ConversationCompactor, TokenBudgetManager

        mgr = TokenBudgetManager(effective_window=100_000)
        compactor = ConversationCompactor(budget_manager=mgr)

        with patch.object(compactor, "get_running_summary", wraps=compactor.get_running_summary) as spy_get:
            history = _make_history(3, content_len=20)
            await compactor.maybe_compact("s1", history, user_id="u1")

        spy_get.assert_called_with("s1", user_id="u1")


# =============================================================================
# Part 4: Debug Logging Cleanup
# =============================================================================


class TestDebugLogging:
    """Sprint 79 Gap 3: Verify verbose info logs replaced with concise debug."""

    @pytest.mark.asyncio
    async def test_build_context_uses_debug_not_info(self):
        """build_context should use logger.debug for context summary, not info."""
        from app.services.input_processor import InputProcessor
        from app.models.schemas import ChatRequest, UserRole

        processor = InputProcessor()
        request = MagicMock(spec=ChatRequest)
        request.user_id = "u1"
        request.message = "Hello"
        request.role = UserRole.STUDENT
        request.user_context = None

        session_id = uuid4()

        with patch("app.engine.context_manager.get_compactor") as mock_get:
            mock_compactor = MagicMock()
            mock_compactor.maybe_compact = AsyncMock(return_value=(
                "", [], MagicMock(
                    total_used=0, total_budget=20000, utilization=0.0,
                    messages_included=0, messages_dropped=0, has_summary=False,
                ),
            ))
            mock_get.return_value = mock_compactor

            with patch("app.services.input_processor.logger") as mock_logger:
                await processor.build_context(request, session_id)

        # Check consolidated debug log exists
        debug_calls = [c for c in mock_logger.debug.call_args_list if "[CONTEXT]" in str(c)]
        assert len(debug_calls) >= 1, "Expected consolidated [CONTEXT] debug log"

        # Old verbose info logs should NOT exist
        info_calls = [c for c in mock_logger.info.call_args_list if "CONTEXT BUILT" in str(c)]
        assert len(info_calls) == 0, "Old verbose 'CONTEXT BUILT' info logs should be removed"


# =============================================================================
# Part 5: Auto-Summarize Previous Session (Sprint 79 Gap 2 - orchestrator)
# =============================================================================


class TestAutoSessionSummarization:
    """Sprint 79: Auto-summarize previous session on new session start."""

    def test_first_message_triggers_previous_session_summary(self):
        """When is_first_message=True, trigger summarize of previous session."""
        from app.services.chat_orchestrator import ChatOrchestrator

        orch = ChatOrchestrator()
        background_save = MagicMock()

        mock_repo = MagicMock()
        mock_repo.list_threads.return_value = [
            {"thread_id": "current", "extra_data": {}},
            {"thread_id": "previous", "extra_data": {}},  # No summary yet
        ]

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            orch._maybe_summarize_previous_session(
                background_save,
                "user1",
                "org-active",
            )

        background_save.assert_called_once()
        mock_repo.list_threads.assert_called_once_with(
            user_id="user1",
            limit=2,
            organization_id="org-active",
        )
        # Verify the function and args passed
        args = background_save.call_args[0]
        assert args[1] == "previous"  # thread_id
        assert args[2] == "user1"     # user_id
        assert args[3] == "org-active"

    def test_already_summarized_session_skips(self):
        """Previous session with existing summary is not re-summarized."""
        from app.services.chat_orchestrator import ChatOrchestrator

        orch = ChatOrchestrator()
        background_save = MagicMock()

        mock_repo = MagicMock()
        mock_repo.list_threads.return_value = [
            {"thread_id": "current", "extra_data": {}},
            {"thread_id": "previous", "extra_data": {"summary": "Already done"}},
        ]

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            orch._maybe_summarize_previous_session(background_save, "user1")

        background_save.assert_not_called()

    def test_no_previous_session_skips(self):
        """Only one thread (current) — nothing to summarize."""
        from app.services.chat_orchestrator import ChatOrchestrator

        orch = ChatOrchestrator()
        background_save = MagicMock()

        mock_repo = MagicMock()
        mock_repo.list_threads.return_value = [
            {"thread_id": "current", "extra_data": {}},
        ]

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            orch._maybe_summarize_previous_session(background_save, "user1")

        background_save.assert_not_called()

    def test_repo_failure_doesnt_crash(self):
        """Exception in thread_repository doesn't propagate."""
        from app.services.chat_orchestrator import ChatOrchestrator

        orch = ChatOrchestrator()
        background_save = MagicMock()

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            side_effect=Exception("DB down"),
        ):
            # Should not raise
            orch._maybe_summarize_previous_session(background_save, "user1")

        background_save.assert_not_called()


# =============================================================================
# Part 6: Pronoun Style Persistence (Sprint 79 Gap 3)
# =============================================================================


class TestPronounStylePersistence:
    """Sprint 79: Persist pronoun style as FactType for cross-session survival."""

    def test_fact_type_enum_includes_pronoun_style(self):
        """PRONOUN_STYLE exists in FactType enum."""
        from app.models.semantic_memory import FactType, ALLOWED_FACT_TYPES

        assert hasattr(FactType, "PRONOUN_STYLE")
        assert FactType.PRONOUN_STYLE.value == "pronoun_style"
        assert "pronoun_style" in ALLOWED_FACT_TYPES

    def test_pronoun_style_in_personal_category(self):
        """pronoun_style is classified as personal fact (360h stability)."""
        from app.models.semantic_memory import PERSONAL_FACT_TYPES

        assert "pronoun_style" in PERSONAL_FACT_TYPES

    def test_pronoun_style_predicate_exists(self):
        """HAS_PRONOUN_STYLE predicate exists and is mapped."""
        from app.models.semantic_memory import (
            Predicate,
            FACT_TYPE_TO_PREDICATE,
            PREDICATE_TO_OBJECT_TYPE,
        )

        assert hasattr(Predicate, "HAS_PRONOUN_STYLE")
        assert FACT_TYPE_TO_PREDICATE["pronoun_style"] == Predicate.HAS_PRONOUN_STYLE
        assert PREDICATE_TO_OBJECT_TYPE[Predicate.HAS_PRONOUN_STYLE] == "personal"

    def test_persist_pronoun_style_calls_upsert_triple(self):
        """_persist_pronoun_style stores pronoun dict as triple."""
        from app.services.chat_orchestrator import ChatOrchestrator

        orch = ChatOrchestrator()
        orch._semantic_memory = MagicMock()
        background_save = MagicMock()

        pronoun = {"user_called": "mình", "ai_self": "tớ"}

        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True

        with patch(
            "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
            return_value=mock_repo,
        ):
            orch._persist_pronoun_style(background_save, "user1", pronoun)

        # background_save was called with a callable
        background_save.assert_called_once()
        store_fn = background_save.call_args[0][0]

        # Execute the stored function
        with patch(
            "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
            return_value=mock_repo,
        ):
            store_fn()

        mock_repo.upsert_triple.assert_called_once()
        triple = mock_repo.upsert_triple.call_args[0][0]
        assert triple.predicate.value == "has_pronoun_style"
        assert '"mình"' in triple.object  # JSON serialized

    def test_load_pronoun_style_from_facts(self):
        """_load_pronoun_style_from_facts restores pronoun dict from stored fact."""
        import json
        from app.services.chat_orchestrator import ChatOrchestrator
        from app.services.session_manager import SessionContext, SessionState

        orch = ChatOrchestrator()
        orch._semantic_memory = MagicMock()
        orch._semantic_memory.is_available.return_value = True

        session = SessionContext(
            session_id=uuid4(),
            user_id="user1",
            state=SessionState(session_id=uuid4()),
        )

        pronoun_data = {"user_called": "em", "ai_self": "mình"}
        mock_mem = MagicMock()
        mock_mem.content = f"pronoun_style: {json.dumps(pronoun_data, ensure_ascii=False)}"
        mock_mem.metadata = {"fact_type": "pronoun_style"}

        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        mock_repo.get_memories_by_type.return_value = [mock_mem]

        with patch(
            "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
            return_value=mock_repo,
        ):
            orch._load_pronoun_style_from_facts(session, "user1")

        assert session.state.pronoun_style == pronoun_data

    def test_load_pronoun_style_no_facts_no_error(self):
        """No stored pronoun_style → session.pronoun_style remains None."""
        from app.services.chat_orchestrator import ChatOrchestrator
        from app.services.session_manager import SessionContext, SessionState

        orch = ChatOrchestrator()
        orch._semantic_memory = MagicMock()
        orch._semantic_memory.is_available.return_value = True

        session = SessionContext(
            session_id=uuid4(),
            user_id="user1",
            state=SessionState(session_id=uuid4()),
        )

        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        mock_repo.get_memories_by_type.return_value = []

        with patch(
            "app.repositories.semantic_memory_repository.get_semantic_memory_repository",
            return_value=mock_repo,
        ):
            orch._load_pronoun_style_from_facts(session, "user1")

        assert session.state.pronoun_style is None

    def test_pronoun_style_in_core_memory_block(self):
        """CoreMemoryBlock._compile includes pronoun_style in output."""
        from app.engine.semantic_memory.core_memory_block import CoreMemoryBlock

        block = CoreMemoryBlock()
        facts = {
            "name": "Minh",
            "pronoun_style": '{"user_called": "em", "ai_self": "mình"}',
        }
        result = block._compile(facts)
        assert "Phong cách giao tiếp" in result

    def test_pronoun_style_decay_category(self):
        """pronoun_style decays as 'personal' (360h stability)."""
        from app.engine.semantic_memory.importance_decay import get_decay_category

        assert get_decay_category("pronoun_style") == "personal"


# =============================================================================
# Part 7: Repository Running Summary Methods
# =============================================================================


class TestRepositoryRunningSummary:
    """Sprint 79: SemanticMemoryRepository upsert/get running summary."""

    def test_upsert_running_summary_insert(self):
        """upsert_running_summary inserts new record when none exists."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository()
        factory, mock_session = _mock_db_factory(rows=None)

        # First execute (UPDATE) returns no rows, second (INSERT) returns a row
        mock_update_result = MagicMock()
        mock_update_result.fetchone.return_value = None
        mock_insert_result = MagicMock()
        mock_insert_result.fetchone.return_value = ("new_id",)
        mock_session.execute.side_effect = [mock_update_result, mock_insert_result]

        repo._session_factory = factory
        repo._initialized = True

        result = repo.upsert_running_summary("s1", "Test summary")
        assert result is True
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    def test_upsert_running_summary_update(self):
        """upsert_running_summary updates existing record."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository()
        factory, mock_session = _mock_db_factory(rows=("existing_id",))

        repo._session_factory = factory
        repo._initialized = True

        result = repo.upsert_running_summary("s1", "Updated summary")
        assert result is True
        # Only 1 execute (UPDATE matched)
        assert mock_session.execute.call_count == 1
        mock_session.commit.assert_called_once()

    def test_get_running_summary_found(self):
        """get_running_summary returns content when record exists."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository()
        mock_row = MagicMock()
        mock_row.content = "Stored summary"
        factory, _ = _mock_db_factory(rows=mock_row)

        repo._session_factory = factory
        repo._initialized = True

        result = repo.get_running_summary("s1")
        assert result == "Stored summary"

    def test_get_running_summary_not_found(self):
        """get_running_summary returns None when no record."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository()
        factory, _ = _mock_db_factory(rows=None)

        repo._session_factory = factory
        repo._initialized = True

        result = repo.get_running_summary("s1")
        assert result is None

    def test_delete_running_summary(self):
        """delete_running_summary removes the record."""
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository

        repo = SemanticMemoryRepository()
        factory, mock_session = _mock_db_factory(rows=("deleted_id",))

        repo._session_factory = factory
        repo._initialized = True

        result = repo.delete_running_summary("s1")
        assert result is True
        mock_session.commit.assert_called_once()
