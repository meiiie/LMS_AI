"""
Tests for Scheduler Tools — LangChain tools for proactive agent scheduling (Sprint 19).

Verifies:
- tool_schedule_reminder: success, past time, missing user_id, invalid datetime
- tool_list_scheduled_tasks: with tasks, empty list, missing user_id
- tool_cancel_scheduled_task: success, not found, short ID resolution
- User context via set_scheduler_user / init_scheduler_tools
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import app.engine.tools.scheduler_tools as scheduler_tools_module
from app.engine.tools.scheduler_tools import (
    set_scheduler_user,
    tool_schedule_reminder,
    tool_list_scheduled_tasks,
    tool_cancel_scheduled_task,
    get_scheduler_tools,
    init_scheduler_tools,
)


@pytest.fixture(autouse=True)
def reset_user_context():
    """Reset per-request contextvar state before each test."""
    # Sprint 26: contextvars — reset by setting a fresh empty state
    scheduler_tools_module._scheduler_tool_state.set(None)
    yield
    scheduler_tools_module._scheduler_tool_state.set(None)


@pytest.fixture
def mock_repo():
    """Create a mock scheduler repository."""
    repo = MagicMock()
    # Lazy import inside tool functions → patch at SOURCE module
    with patch(
        "app.repositories.scheduler_repository.get_scheduler_repository",
        return_value=repo,
    ):
        yield repo


@pytest.fixture
def set_user():
    """Set the scheduler user context for tests."""
    set_scheduler_user("test-user", "maritime")


# =============================================================================
# tool_schedule_reminder
# =============================================================================

class TestToolScheduleReminder:
    """Tests for tool_schedule_reminder."""

    def test_success(self, mock_repo, set_user):
        """Successfully schedule a reminder in the future."""
        mock_repo.create_task.return_value = "abc-123-def-456"

        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        result = tool_schedule_reminder.invoke(
            {"description": "Ôn tập COLREGs Rule 13", "when": future}
        )

        assert "Đã lên lịch thành công" in result
        assert "abc-123-def-456" in result
        assert "Ôn tập COLREGs Rule 13" in result
        mock_repo.create_task.assert_called_once()
        call_kwargs = mock_repo.create_task.call_args
        assert call_kwargs.kwargs["user_id"] == "test-user"
        assert call_kwargs.kwargs["schedule_type"] == "once"

    def test_past_time_rejected(self, mock_repo, set_user):
        """Scheduling in the past should be rejected."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = tool_schedule_reminder.invoke(
            {"description": "Past reminder", "when": past}
        )

        assert "tương lai" in result
        mock_repo.create_task.assert_not_called()

    def test_no_user_id(self, mock_repo):
        """Without user_id set, should return error message."""
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        result = tool_schedule_reminder.invoke(
            {"description": "Test", "when": future}
        )

        assert "chưa xác định user_id" in result
        mock_repo.create_task.assert_not_called()

    def test_invalid_datetime_format(self, mock_repo, set_user):
        """Invalid datetime string should return format error."""
        result = tool_schedule_reminder.invoke(
            {"description": "Test", "when": "not-a-date"}
        )

        assert "Định dạng thời gian không hợp lệ" in result

    def test_repo_returns_none(self, mock_repo, set_user):
        """When repo.create_task returns None, should return failure message."""
        mock_repo.create_task.return_value = None

        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        result = tool_schedule_reminder.invoke(
            {"description": "Test", "when": future}
        )

        assert "Không thể tạo lịch nhắc nhở" in result


# =============================================================================
# tool_list_scheduled_tasks
# =============================================================================

class TestToolListScheduledTasks:
    """Tests for tool_list_scheduled_tasks."""

    def test_with_tasks(self, mock_repo, set_user):
        """Should format tasks into a readable list."""
        mock_repo.list_tasks.return_value = [
            {
                "id": "aaaa1111-bbbb-cccc-dddd-eeeeffffggg1",
                "description": "Ôn tập Rule 13",
                "next_run": "2026-02-15T09:00:00+07:00",
                "schedule_type": "once",
            },
            {
                "id": "aaaa1111-bbbb-cccc-dddd-eeeeffffggg2",
                "description": "Quiz hàng hải",
                "next_run": "2026-02-16T10:00:00+07:00",
                "schedule_type": "recurring",
            },
        ]

        result = tool_list_scheduled_tasks.invoke({})

        assert "2 tác vụ" in result
        assert "Ôn tập Rule 13" in result
        assert "Quiz hàng hải" in result
        assert "aaaa1111" in result  # Short ID prefix
        mock_repo.list_tasks.assert_called_once_with(user_id="test-user")

    def test_empty_list(self, mock_repo, set_user):
        """When no tasks exist, should show empty message."""
        mock_repo.list_tasks.return_value = []

        result = tool_list_scheduled_tasks.invoke({})

        assert "chưa có tác vụ nào" in result

    def test_no_user_id(self, mock_repo):
        """Without user_id set, should return error message."""
        result = tool_list_scheduled_tasks.invoke({})

        assert "chưa xác định user_id" in result
        mock_repo.list_tasks.assert_not_called()


# =============================================================================
# tool_cancel_scheduled_task
# =============================================================================

class TestToolCancelScheduledTask:
    """Tests for tool_cancel_scheduled_task."""

    def test_cancel_success_full_id(self, mock_repo, set_user):
        """Cancel with full UUID should call repo.cancel_task directly."""
        full_id = "aaaa1111-bbbb-cccc-dddd-eeeeffffggg1"
        mock_repo.cancel_task.return_value = True

        result = tool_cancel_scheduled_task.invoke({"task_id": full_id})

        assert "Đã hủy tác vụ" in result
        assert "aaaa1111" in result
        mock_repo.cancel_task.assert_called_once_with(
            task_id=full_id, user_id="test-user"
        )

    def test_cancel_not_found(self, mock_repo, set_user):
        """When cancel returns False, should show failure message."""
        full_id = "aaaa1111-bbbb-cccc-dddd-eeeeffffggg1"
        mock_repo.cancel_task.return_value = False

        result = tool_cancel_scheduled_task.invoke({"task_id": full_id})

        assert "Không thể hủy" in result

    def test_cancel_short_id_single_match(self, mock_repo, set_user):
        """Short ID matching a single task should resolve and cancel."""
        full_id = "aaaa1111-bbbb-cccc-dddd-eeeeffffggg1"
        mock_repo.list_tasks.return_value = [
            {"id": full_id, "description": "Test"},
        ]
        mock_repo.cancel_task.return_value = True

        result = tool_cancel_scheduled_task.invoke({"task_id": "aaaa1111"})

        assert "Đã hủy tác vụ" in result
        mock_repo.cancel_task.assert_called_once_with(
            task_id=full_id, user_id="test-user"
        )

    def test_cancel_short_id_multiple_matches(self, mock_repo, set_user):
        """Short ID matching multiple tasks should ask for full ID."""
        mock_repo.list_tasks.return_value = [
            {"id": "aaaa1111-bbbb-cccc-dddd-eeeeffffggg1", "description": "Task 1"},
            {"id": "aaaa1111-bbbb-cccc-dddd-eeeeffffggg2", "description": "Task 2"},
        ]

        result = tool_cancel_scheduled_task.invoke({"task_id": "aaaa1111"})

        assert "2 tác vụ khớp" in result
        assert "ID đầy đủ" in result
        mock_repo.cancel_task.assert_not_called()

    def test_cancel_short_id_no_match(self, mock_repo, set_user):
        """Short ID with no matches should show not found."""
        mock_repo.list_tasks.return_value = []

        result = tool_cancel_scheduled_task.invoke({"task_id": "zzzz9999"})

        assert "Không tìm thấy" in result
        mock_repo.cancel_task.assert_not_called()

    def test_cancel_no_user_id(self, mock_repo):
        """Without user_id set, should return error message."""
        result = tool_cancel_scheduled_task.invoke({"task_id": "any-id"})

        assert "chưa xác định user_id" in result


# =============================================================================
# Helper functions
# =============================================================================

class TestHelperFunctions:
    """Tests for set_scheduler_user, get_scheduler_tools, init_scheduler_tools."""

    def test_set_scheduler_user(self):
        """set_scheduler_user should update contextvar state."""
        set_scheduler_user("user-42", "traffic_law")

        state = scheduler_tools_module._get_scheduler_state()
        assert state.user_id == "user-42"
        assert state.domain_id == "traffic_law"
        assert "user=user-42" in (state.identity_key or "")
        assert "domain=traffic_law" in (state.identity_key or "")

    def test_set_scheduler_user_replaces_previous_identity(self):
        """Changing user context should replace the scheduler tool identity."""
        set_scheduler_user("user-a", "maritime")
        first_state = scheduler_tools_module._get_scheduler_state()

        set_scheduler_user("user-b", "traffic_law")
        second_state = scheduler_tools_module._get_scheduler_state()

        assert second_state is not first_state
        assert second_state.user_id == "user-b"
        assert second_state.domain_id == "traffic_law"
        assert "user=user-b" in (second_state.identity_key or "")
        assert "domain=traffic_law" in (second_state.identity_key or "")

    def test_runtime_context_identity_isolates_scheduler_state(self):
        """Runtime org/session identity should prevent scheduler state reuse."""
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        ctx_a = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-a",
            session_id="session-a",
        )
        ctx_b = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-b",
            session_id="session-a",
        )

        with tool_runtime_scope(ctx_a):
            set_scheduler_user("user-a", "maritime")
            state_a = scheduler_tools_module._get_scheduler_state()
            assert state_a.user_id == "user-a"
            assert "org=org-a" in (state_a.identity_key or "")

        with tool_runtime_scope(ctx_b):
            state_b = scheduler_tools_module._get_scheduler_state()
            assert state_b is not state_a
            assert state_b.user_id == "user-a"
            assert "org=org-b" in (state_b.identity_key or "")

    def test_set_scheduler_user_default_domain(self):
        """set_scheduler_user with default domain_id."""
        set_scheduler_user("user-99")

        state = scheduler_tools_module._get_scheduler_state()
        assert state.user_id == "user-99"
        assert state.domain_id == "maritime"

    def test_get_scheduler_tools_returns_three_tools(self):
        """get_scheduler_tools should return a list of 3 tools."""
        tools = get_scheduler_tools()

        assert len(tools) == 3
        tool_names = [t.name for t in tools]
        assert "tool_schedule_reminder" in tool_names
        assert "tool_list_scheduled_tasks" in tool_names
        assert "tool_cancel_scheduled_task" in tool_names

    def test_init_scheduler_tools_sets_context(self):
        """init_scheduler_tools should call set_scheduler_user."""
        init_scheduler_tools("init-user", "traffic_law")

        state = scheduler_tools_module._get_scheduler_state()
        assert state.user_id == "init-user"
        assert state.domain_id == "traffic_law"
