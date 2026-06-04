"""
Tests for SchedulerRepository — Scheduled task CRUD operations.

Sprint 21: System Correctness & Hardening.

Verifies:
- create_task with various parameters
- list_tasks with ownership filter
- cancel_task with ownership check
- get_due_tasks (executor polling)
- mark_executed (once vs recurring)
- _row_to_dict (extra_data parsing: JSON string, dict, null, missing)
- Lazy initialization & singleton
- Error handling (DB failures)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.repositories.scheduler_repository import (
    SchedulerRepository,
    get_scheduler_repository,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def repo():
    """Fresh SchedulerRepository with mocked DB session."""
    r = SchedulerRepository()
    r._initialized = True
    r._engine = MagicMock()

    # Mock session factory: context manager returning a session mock
    mock_session = MagicMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)
    r._session_factory = mock_session_factory
    r._mock_session = mock_session  # expose for assertions
    return r


@pytest.fixture
def sample_row_14():
    """Sample database row with 14 columns (includes extra_data)."""
    return (
        "task-id-123",        # 0: id
        "user-1",             # 1: user_id
        "maritime",           # 2: domain_id
        "Ôn tập COLREGs",    # 3: description
        "once",               # 4: schedule_type
        "",                   # 5: schedule_expr
        datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc),  # 6: next_run
        None,                 # 7: last_run
        0,                    # 8: run_count
        None,                 # 9: max_runs
        "active",             # 10: status
        "websocket",          # 11: channel
        datetime(2026, 2, 9, 12, 0, tzinfo=timezone.utc),   # 12: created_at
        '{"agent_invoke": true}',  # 13: extra_data (JSON string)
    )


@pytest.fixture
def sample_row_13():
    """Sample database row with 13 columns (no extra_data — backward compat)."""
    return (
        "task-id-456",
        "user-1",
        "maritime",
        "Nhắc ôn tập",
        "recurring",
        "1d",
        datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc),
        None,
        0,
        7,
        "active",
        "websocket",
        datetime(2026, 2, 9, 12, 0, tzinfo=timezone.utc),
    )


# =============================================================================
# _row_to_dict
# =============================================================================

class TestRowToDict:

    def test_row_with_json_string_extra_data(self, sample_row_14):
        """Parses JSON string extra_data correctly."""
        result = SchedulerRepository._row_to_dict(sample_row_14)

        assert result["id"] == "task-id-123"
        assert result["user_id"] == "user-1"
        assert result["domain_id"] == "maritime"
        assert result["description"] == "Ôn tập COLREGs"
        assert result["schedule_type"] == "once"
        assert result["extra_data"] == {"agent_invoke": True}

    def test_row_with_dict_extra_data(self):
        """Handles dict extra_data (already parsed by driver)."""
        row = list(range(13)) + [{"key": "value"}]
        result = SchedulerRepository._row_to_dict(row)
        assert result["extra_data"] == {"key": "value"}

    def test_row_with_null_extra_data(self):
        """Handles None extra_data gracefully."""
        row = list(range(13)) + [None]
        result = SchedulerRepository._row_to_dict(row)
        assert result["extra_data"] == {}

    def test_row_with_empty_string_extra_data(self):
        """Handles empty string extra_data (invalid JSON)."""
        row = list(range(13)) + [""]
        result = SchedulerRepository._row_to_dict(row)
        assert result["extra_data"] == {}

    def test_row_with_invalid_json_extra_data(self):
        """Handles invalid JSON string gracefully."""
        row = list(range(13)) + ["{invalid json}"]
        result = SchedulerRepository._row_to_dict(row)
        assert result["extra_data"] == {}

    def test_row_without_extra_data_column(self, sample_row_13):
        """Backward compatible: 13-column row returns empty extra_data."""
        result = SchedulerRepository._row_to_dict(sample_row_13)

        assert result["id"] == "task-id-456"
        assert result["extra_data"] == {}
        assert result["schedule_type"] == "recurring"
        assert result["max_runs"] == 7

    def test_row_timestamps_stringified(self, sample_row_14):
        """next_run, last_run, created_at are converted to strings."""
        result = SchedulerRepository._row_to_dict(sample_row_14)

        assert isinstance(result["next_run"], str)
        assert "2026" in result["next_run"]
        assert result["last_run"] is None  # None stays None
        assert isinstance(result["created_at"], str)

    def test_row_run_count_and_max_runs(self, sample_row_14):
        """Numeric fields preserved."""
        result = SchedulerRepository._row_to_dict(sample_row_14)
        assert result["run_count"] == 0
        assert result["max_runs"] is None


# =============================================================================
# create_task
# =============================================================================

class TestCreateTask:

    def test_create_task_basic(self, repo):
        """Creates task with all defaults."""
        task_id = repo.create_task(
            user_id="user-1",
            description="Test reminder",
        )

        assert task_id is not None
        assert isinstance(task_id, str)
        assert len(task_id) == 36  # UUID format

        repo._mock_session.execute.assert_called_once()
        repo._mock_session.commit.assert_called_once()

    def test_create_task_with_schedule_expr(self, repo):
        """'once' task parses schedule_expr as next_run."""
        task_id = repo.create_task(
            user_id="user-1",
            description="Reminder at specific time",
            schedule_type="once",
            schedule_expr="2026-02-10T09:00:00+00:00",
        )

        assert task_id is not None

    def test_create_task_invalid_schedule_expr(self, repo):
        """Invalid schedule_expr for 'once' returns None."""
        task_id = repo.create_task(
            user_id="user-1",
            description="Bad time",
            schedule_type="once",
            schedule_expr="not-a-datetime",
        )

        assert task_id is None

    def test_create_task_with_extra_data(self, repo):
        """extra_data is serialized to JSON."""
        task_id = repo.create_task(
            user_id="user-1",
            description="Agent task",
            extra_data={"agent_invoke": True, "quiz_count": 5},
        )

        assert task_id is not None
        # Verify the JSON was passed in the execute call
        call_args = repo._mock_session.execute.call_args
        params = call_args[0][1]
        assert '"agent_invoke": true' in params["extra"]

    def test_create_task_recurring(self, repo):
        """Recurring task with next_run and max_runs."""
        next_run = datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc)
        task_id = repo.create_task(
            user_id="user-1",
            description="Daily quiz",
            schedule_type="recurring",
            schedule_expr="1d",
            next_run=next_run,
            max_runs=7,
            channel="telegram",
        )

        assert task_id is not None

    def test_create_task_not_initialized(self):
        """Returns None when DB is not initialized."""
        repo = SchedulerRepository()
        # _ensure_initialized will fail silently
        with patch.object(repo, "_ensure_initialized"):
            result = repo.create_task("user-1", "test")
        assert result is None

    def test_create_task_db_error(self, repo):
        """Returns None on DB exception."""
        repo._mock_session.execute.side_effect = RuntimeError("DB down")

        result = repo.create_task("user-1", "test")
        assert result is None


# =============================================================================
# list_tasks
# =============================================================================

class TestListTasks:

    def test_list_tasks_returns_dicts(self, repo, sample_row_14):
        """Returns list of task dicts."""
        repo._mock_session.execute.return_value.fetchall.return_value = [sample_row_14]

        result = repo.list_tasks("user-1")

        assert len(result) == 1
        assert result[0]["id"] == "task-id-123"
        assert result[0]["user_id"] == "user-1"

    def test_list_tasks_empty(self, repo):
        """Returns empty list when no tasks."""
        repo._mock_session.execute.return_value.fetchall.return_value = []

        result = repo.list_tasks("user-1")
        assert result == []

    def test_list_tasks_respects_status_filter(self, repo):
        """Passes status filter to query."""
        repo._mock_session.execute.return_value.fetchall.return_value = []

        repo.list_tasks("user-1", status="completed")

        call_args = repo._mock_session.execute.call_args
        params = call_args[0][1]
        assert params["status"] == "completed"

    def test_list_tasks_not_initialized(self):
        """Returns empty list when DB not initialized."""
        repo = SchedulerRepository()
        with patch.object(repo, "_ensure_initialized"):
            result = repo.list_tasks("user-1")
        assert result == []

    def test_list_tasks_db_error(self, repo):
        """Returns empty list on DB error."""
        repo._mock_session.execute.side_effect = RuntimeError("DB down")

        result = repo.list_tasks("user-1")
        assert result == []


# =============================================================================
# cancel_task
# =============================================================================

class TestCancelTask:

    def test_cancel_task_success(self, repo):
        """Returns True when task is cancelled."""
        repo._mock_session.execute.return_value.rowcount = 1

        result = repo.cancel_task("task-id-123", "user-1")
        assert result is True

    def test_cancel_task_not_found(self, repo):
        """Returns False when task not found or not owned."""
        repo._mock_session.execute.return_value.rowcount = 0

        result = repo.cancel_task("nonexistent", "user-1")
        assert result is False

    def test_cancel_task_ownership_check(self, repo):
        """Query includes user_id for ownership verification."""
        repo._mock_session.execute.return_value.rowcount = 1

        repo.cancel_task("task-id-123", "user-1")

        call_args = repo._mock_session.execute.call_args
        params = call_args[0][1]
        assert params["task_id"] == "task-id-123"
        assert params["user_id"] == "user-1"

    def test_cancel_task_not_initialized(self):
        """Returns False when DB not initialized."""
        repo = SchedulerRepository()
        with patch.object(repo, "_ensure_initialized"):
            result = repo.cancel_task("task-id", "user-1")
        assert result is False

    def test_cancel_task_db_error(self, repo):
        """Returns False on DB exception."""
        repo._mock_session.execute.side_effect = RuntimeError("DB down")

        result = repo.cancel_task("task-id", "user-1")
        assert result is False


# =============================================================================
# get_due_tasks
# =============================================================================

class TestGetDueTasks:

    def test_get_due_tasks_returns_dicts(self, repo, sample_row_14):
        """Returns list of due task dicts."""
        repo._mock_session.execute.return_value.fetchall.return_value = [sample_row_14]

        result = repo.get_due_tasks()

        assert len(result) == 1
        assert result[0]["id"] == "task-id-123"
        assert result[0]["extra_data"] == {"agent_invoke": True}

    def test_get_due_tasks_respects_limit(self, repo):
        """Passes limit to query."""
        repo._mock_session.execute.return_value.fetchall.return_value = []

        repo.get_due_tasks(limit=3)

        call_args = repo._mock_session.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 3

    def test_get_due_tasks_empty(self, repo):
        """Returns empty list when no due tasks."""
        repo._mock_session.execute.return_value.fetchall.return_value = []

        result = repo.get_due_tasks()
        assert result == []

    def test_get_due_tasks_not_initialized(self):
        """Returns empty list when DB not initialized."""
        repo = SchedulerRepository()
        with patch.object(repo, "_ensure_initialized"):
            result = repo.get_due_tasks()
        assert result == []

    def test_get_due_tasks_db_error(self, repo):
        """Returns empty list on DB error."""
        repo._mock_session.execute.side_effect = RuntimeError("DB down")

        result = repo.get_due_tasks()
        assert result == []


# =============================================================================
# mark_executed
# =============================================================================

class TestMarkExecuted:

    def test_mark_executed_once(self, repo):
        """One-time task: mark as completed (next_run=None)."""
        result = repo.mark_executed("task-id-123", next_run=None)

        assert result is True
        # Should have 2 execute calls: UPDATE status + check max_runs
        assert repo._mock_session.execute.call_count == 2
        first_call = repo._mock_session.execute.call_args_list[0]
        assert "next_run = NULL" in str(first_call[0][0])
        assert "status = 'completed'" in str(first_call[0][0])
        repo._mock_session.commit.assert_called_once()

    def test_mark_executed_recurring(self, repo):
        """Recurring task: update next_run."""
        next_run = datetime(2026, 2, 11, 9, 0, tzinfo=timezone.utc)

        result = repo.mark_executed("task-id-123", next_run=next_run)

        assert result is True
        # Should have 2 execute calls: UPDATE next_run + check max_runs
        assert repo._mock_session.execute.call_count == 2

    def test_mark_executed_checks_max_runs(self, repo):
        """Always runs max_runs check after execution."""
        repo.mark_executed("task-id-123")

        # Second execute call is the max_runs check
        second_call = repo._mock_session.execute.call_args_list[1]
        sql_text = str(second_call[0][0])
        assert "max_runs" in sql_text
        assert "next_run = NULL" in sql_text

    def test_mark_executed_not_initialized(self):
        """Returns False when DB not initialized."""
        repo = SchedulerRepository()
        with patch.object(repo, "_ensure_initialized"):
            result = repo.mark_executed("task-id")
        assert result is False

    def test_mark_executed_db_error(self, repo):
        """Returns False on DB exception."""
        repo._mock_session.execute.side_effect = RuntimeError("DB down")

        result = repo.mark_executed("task-id-123")
        assert result is False


# =============================================================================
# Lazy initialization
# =============================================================================

class TestLazyInit:

    def test_ensure_initialized_success(self):
        """Lazy init acquires engine and session factory."""
        repo = SchedulerRepository()
        mock_engine = MagicMock()
        mock_factory = MagicMock()

        with patch("app.core.database.get_shared_engine", return_value=mock_engine), \
             patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
            repo._ensure_initialized()

        assert repo._initialized is True
        assert repo._engine is mock_engine
        assert repo._session_factory is mock_factory

    def test_ensure_initialized_failure(self):
        """Lazy init handles import/connection errors gracefully."""
        repo = SchedulerRepository()

        with patch("app.core.database.get_shared_engine", side_effect=RuntimeError("No DB")):
            repo._ensure_initialized()

        assert repo._initialized is False

    def test_ensure_initialized_idempotent(self):
        """Second call skips re-initialization."""
        repo = SchedulerRepository()
        repo._initialized = True
        repo._engine = "already-set"

        repo._ensure_initialized()
        assert repo._engine == "already-set"


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    def test_get_scheduler_repository_singleton(self):
        """Singleton returns same instance."""
        import app.repositories.scheduler_repository as mod
        mod._scheduler_repo = None

        r1 = get_scheduler_repository()
        r2 = get_scheduler_repository()
        assert r1 is r2

        mod._scheduler_repo = None  # Clean up
