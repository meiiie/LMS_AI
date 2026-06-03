"""
Tests for ScheduledTaskExecutor — Periodic poll loop for proactive agent tasks.

Sprint 20: Proactive Agent Activation.

Verifies:
- Poll loop starts and stops
- Executes due tasks (notification mode)
- Executes due tasks (agent mode with mock)
- Handles execution errors gracefully
- Respects max_concurrent limit
- Calculates next_run for recurring tasks
- Graceful shutdown with timeout
- Interval parsing (_parse_interval)
"""

import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.runtime import runtime_metrics as rm
from app.engine.multi_agent.runtime_contracts import WiiiTurnRequest, WiiiTurnResult
from app.services.scheduled_task_executor import (
    ScheduledTaskExecutor,
    _parse_interval,
    get_scheduled_task_executor,
)


# =============================================================================
# Fixtures
# =============================================================================

def _counter_value(name: str, labels: dict[str, str] | None = None) -> int:
    key = tuple(sorted((k, v) for k, v in (labels or {}).items()))
    return rm.snapshot()["counters"].get(name, {}).get(key, 0)


def _histogram_values(name: str, labels: dict[str, str]) -> list[float]:
    key = tuple(sorted(labels.items()))
    return rm.snapshot()["histograms"].get(name, {}).get(key, [])


@pytest.fixture(autouse=True)
def reset_runtime_metrics():
    rm._reset_for_tests()
    yield
    rm._reset_for_tests()


@pytest.fixture
def executor():
    """Fresh ScheduledTaskExecutor instance."""
    return ScheduledTaskExecutor()


@pytest.fixture
def sample_task_once():
    """Sample one-time scheduled task."""
    return {
        "id": "task-once-12345678",
        "user_id": "user-1",
        "domain_id": "maritime",
        "description": "Nhắc ôn tập COLREGs Rule 13",
        "schedule_type": "once",
        "schedule_expr": "",
        "next_run": str(datetime.now(timezone.utc) - timedelta(minutes=1)),
        "last_run": None,
        "run_count": 0,
        "max_runs": None,
        "status": "active",
        "channel": "websocket",
        "created_at": str(datetime.now(timezone.utc)),
        "extra_data": {},
        "organization_id": "org-1",
    }


@pytest.fixture
def sample_task_agent():
    """Sample agent-invoke scheduled task."""
    return {
        "id": "task-agent-87654321",
        "user_id": "user-2",
        "domain_id": "maritime",
        "description": "Quiz 5 câu hỏi về MARPOL Annex I",
        "schedule_type": "once",
        "schedule_expr": "",
        "next_run": str(datetime.now(timezone.utc) - timedelta(minutes=1)),
        "last_run": None,
        "run_count": 0,
        "max_runs": None,
        "status": "active",
        "channel": "websocket",
        "created_at": str(datetime.now(timezone.utc)),
        "extra_data": {"agent_invoke": True},
        "organization_id": "org-2",
    }


@pytest.fixture
def sample_task_recurring():
    """Sample recurring scheduled task."""
    return {
        "id": "task-recur-11223344",
        "user_id": "user-1",
        "domain_id": "maritime",
        "description": "Nhắc ôn tập hàng ngày",
        "schedule_type": "recurring",
        "schedule_expr": "1d",
        "next_run": str(datetime.now(timezone.utc) - timedelta(minutes=1)),
        "last_run": None,
        "run_count": 0,
        "max_runs": 7,
        "status": "active",
        "channel": "websocket",
        "created_at": str(datetime.now(timezone.utc)),
        "extra_data": {},
        "organization_id": "org-1",
    }


# =============================================================================
# _parse_interval
# =============================================================================

class TestParseInterval:

    def test_parse_seconds(self):
        assert _parse_interval("30s") == timedelta(seconds=30)

    def test_parse_minutes(self):
        assert _parse_interval("15m") == timedelta(minutes=15)

    def test_parse_hours(self):
        assert _parse_interval("2h") == timedelta(hours=2)

    def test_parse_days(self):
        assert _parse_interval("1d") == timedelta(days=1)

    def test_parse_combined(self):
        assert _parse_interval("1h30m") == timedelta(hours=1, minutes=30)

    def test_parse_invalid(self):
        assert _parse_interval("invalid") is None

    def test_parse_empty(self):
        assert _parse_interval("") is None

    def test_parse_zero(self):
        """Zero values return None (no timedelta)."""
        assert _parse_interval("0m") is None


# =============================================================================
# Start / Stop
# =============================================================================

class TestStartStop:

    @pytest.mark.asyncio
    async def test_start_sets_running(self, executor):
        """start() sets is_running and creates background task."""
        mock_settings = MagicMock()
        mock_settings.scheduler_poll_interval = 1

        with patch("app.core.config.settings", mock_settings):
            await executor.start()
            assert executor.is_running is True

            await executor.shutdown(timeout=2)
            assert executor.is_running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, executor):
        """Calling start() twice doesn't create duplicate tasks."""
        mock_settings = MagicMock()
        mock_settings.scheduler_poll_interval = 1

        with patch("app.core.config.settings", mock_settings):
            await executor.start()
            task1 = executor._task

            await executor.start()  # Should be a no-op
            task2 = executor._task

            assert task1 is task2
            await executor.shutdown(timeout=2)

    @pytest.mark.asyncio
    async def test_shutdown_when_not_running(self, executor):
        """Shutdown on non-running executor is a no-op."""
        await executor.shutdown()
        assert executor.is_running is False


# =============================================================================
# Execute notification mode
# =============================================================================

class TestExecuteNotificationMode:

    @pytest.mark.asyncio
    async def test_execute_notification_task(self, executor, sample_task_once):
        """Notification mode returns description as response."""
        result = await executor._execute_single_task(sample_task_once)

        assert result["mode"] == "notification"
        assert result["response"] == sample_task_once["description"]

    @pytest.mark.asyncio
    async def test_execute_due_tasks_notification(self, executor, sample_task_once):
        """Full pipeline: fetch → execute → notify → mark."""
        mock_repo = MagicMock()
        mock_repo.get_due_tasks.return_value = [sample_task_once]
        mock_repo.mark_executed.return_value = True

        mock_dispatcher = MagicMock()
        mock_dispatcher.notify_task_result = AsyncMock(
            return_value={"delivered": True, "channel": "websocket", "detail": "ok"}
        )

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo), \
             patch("app.services.notification_dispatcher.get_notification_dispatcher", return_value=mock_dispatcher):
            await executor._execute_due_tasks()

        mock_repo.get_due_tasks.assert_called_once_with(
            limit=5,
            allow_all_orgs=True,
        )
        assert _counter_value(
            "runtime.scheduled_tasks.polls", {"status": "success"}
        ) == 1
        assert _counter_value("runtime.scheduled_tasks.due") == 1
        assert _counter_value(
            "runtime.scheduled_tasks.delivery",
            {"mode": "notification", "status": "delivered"},
        ) == 1
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "notification", "status": "success"},
        ) == 1
        assert _histogram_values(
            "runtime.scheduled_tasks.duration_ms",
            {"mode": "notification", "status": "success"},
        )
        mock_dispatcher.notify_task_result.assert_called_once()
        # "once" task → next_run=None
        mock_repo.mark_executed.assert_called_once_with(
            sample_task_once["id"],
            next_run=None,
            organization_id="org-1",
        )


# =============================================================================
# Execute agent mode
# =============================================================================

class TestExecuteAgentMode:

    @pytest.mark.asyncio
    async def test_execute_agent_task(self, executor, sample_task_agent):
        """Agent mode calls the native Wiii runtime."""
        mock_settings = MagicMock()
        mock_settings.scheduler_agent_timeout = 30

        mock_result = WiiiTurnResult.from_payload(
            {"response": "Đây là 5 câu hỏi MARPOL..."}
        )

        with patch("app.core.config.settings", mock_settings), \
             patch(
                 "app.engine.multi_agent.runtime.run_wiii_turn",
                 new_callable=AsyncMock,
                 return_value=mock_result,
             ):
            result = await executor._execute_single_task(sample_task_agent)

        assert result["mode"] == "agent"
        assert "MARPOL" in result["response"]

    @pytest.mark.asyncio
    async def test_execute_agent_task_uses_wiii_turn_request(
        self,
        executor,
        sample_task_agent,
    ):
        """Agent mode passes a native Wiii turn request to the runtime."""
        mock_settings = MagicMock()
        mock_settings.scheduler_agent_timeout = 30
        mock_result = WiiiTurnResult.from_payload({"response": "Scheduled native ok"})

        with patch("app.core.config.settings", mock_settings), \
             patch(
                 "app.engine.multi_agent.runtime.run_wiii_turn",
                 new_callable=AsyncMock,
                 return_value=mock_result,
             ) as mock_run_turn:
            result = await executor._execute_single_task(sample_task_agent)

        turn_request = mock_run_turn.await_args.args[0]
        assert isinstance(turn_request, WiiiTurnRequest)
        assert turn_request.query == sample_task_agent["description"]
        assert turn_request.run_context.user_id == sample_task_agent["user_id"]
        assert turn_request.run_context.session_id == "scheduled_task-age"
        assert turn_request.run_context.domain_id == "maritime"
        assert turn_request.run_context.organization_id == "org-2"
        assert result == {"mode": "agent", "response": "Scheduled native ok"}

    @pytest.mark.asyncio
    async def test_agent_task_timeout(self, executor, sample_task_agent):
        """Agent invocation timeout raises TimeoutError."""
        mock_settings = MagicMock()
        mock_settings.scheduler_agent_timeout = 0.01  # Very short

        async def slow_process(_request):
            await asyncio.sleep(10)
            return {}

        with patch("app.core.config.settings", mock_settings), \
             patch(
                 "app.engine.multi_agent.runtime.run_wiii_turn",
                 side_effect=slow_process,
             ):
            with pytest.raises(asyncio.TimeoutError):
                await executor._execute_single_task(sample_task_agent)


# =============================================================================
# Product acceptance: reminder + agent-invoke delivery
# =============================================================================

class TestScheduledAutonomyAcceptance:

    @pytest.mark.asyncio
    async def test_product_acceptance_runs_reminder_and_agent_invoke_delivery(
        self,
        executor,
        sample_task_once,
        sample_task_agent,
    ):
        """Due-task poll executes reminder and agent-invoke tasks through delivery."""
        from app.services.notification_dispatcher import NotificationDispatcher
        from app.services.notifications.base import ChannelConfig, NotificationResult
        from app.services.notifications.registry import NotificationChannelRegistry

        reminder_task = {
            **sample_task_once,
            "id": "task-reminder-product",
            "description": "Review COLREG Rule 13",
            "organization_id": "org-1",
        }
        agent_task = {
            **sample_task_agent,
            "id": "task-agent-product",
            "description": "Create MARPOL quiz",
            "organization_id": "org-2",
        }
        sent_payloads: list[dict] = []

        class CapturingWebSocketAdapter:
            def get_config(self):
                return ChannelConfig(id="websocket", display_name="WebSocket")

            async def send(self, user_id: str, message: str, metadata=None):
                sent_payloads.append(
                    {
                        "user_id": user_id,
                        "message": json.loads(message),
                        "metadata": metadata or {},
                    }
                )
                return NotificationResult(
                    delivered=True,
                    channel="websocket",
                    detail="captured",
                )

        registry = NotificationChannelRegistry()
        registry.register(CapturingWebSocketAdapter())
        dispatcher = NotificationDispatcher()
        dispatcher._registry = registry

        mock_repo = MagicMock()
        mock_repo.get_due_tasks.return_value = [reminder_task, agent_task]
        mock_repo.mark_executed.return_value = True

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5
        mock_settings.scheduler_agent_timeout = 30
        mock_result = WiiiTurnResult.from_payload(
            {"response": "Scheduled MARPOL quiz ready"}
        )

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo), \
             patch("app.services.notification_dispatcher.get_notification_dispatcher", return_value=dispatcher), \
             patch(
                 "app.engine.multi_agent.runtime.run_wiii_turn",
                 new_callable=AsyncMock,
                 return_value=mock_result,
             ) as mock_run_turn:
            await executor._execute_due_tasks()

        mock_repo.get_due_tasks.assert_called_once_with(
            limit=5,
            allow_all_orgs=True,
        )
        assert mock_run_turn.await_count == 1
        turn_request = mock_run_turn.await_args.args[0]
        assert isinstance(turn_request, WiiiTurnRequest)
        assert turn_request.query == "Create MARPOL quiz"
        assert turn_request.run_context.user_id == agent_task["user_id"]
        assert turn_request.run_context.organization_id == "org-2"

        assert len(sent_payloads) == 2
        reminder_payload, agent_payload = sent_payloads
        assert reminder_payload["user_id"] == reminder_task["user_id"]
        assert reminder_payload["metadata"] == {
            "task_id": reminder_task["id"],
            "organization_id": "org-1",
        }
        assert reminder_payload["message"]["type"] == "scheduled_task"
        assert reminder_payload["message"]["mode"] == "notification"
        assert reminder_payload["message"]["content"] == "Review COLREG Rule 13"
        assert agent_payload["user_id"] == agent_task["user_id"]
        assert agent_payload["metadata"] == {
            "task_id": agent_task["id"],
            "organization_id": "org-2",
        }
        assert agent_payload["message"]["type"] == "scheduled_task"
        assert agent_payload["message"]["mode"] == "agent"
        assert agent_payload["message"]["content"] == "Scheduled MARPOL quiz ready"

        assert mock_repo.mark_executed.call_count == 2
        assert mock_repo.mark_executed.call_args_list[0].kwargs["organization_id"] == "org-1"
        assert mock_repo.mark_executed.call_args_list[1].kwargs["organization_id"] == "org-2"
        assert _counter_value("runtime.scheduled_tasks.due") == 2
        assert _counter_value(
            "runtime.scheduled_tasks.delivery",
            {"mode": "notification", "status": "delivered"},
        ) == 1
        assert _counter_value(
            "runtime.scheduled_tasks.delivery",
            {"mode": "agent", "status": "delivered"},
        ) == 1
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "notification", "status": "success"},
        ) == 1
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "agent", "status": "success"},
        ) == 1

    @pytest.mark.asyncio
    async def test_product_acceptance_tool_created_reminder_reaches_websocket_delivery(
        self,
        executor,
    ):
        """A reminder created by the scheduler tool is delivered by the worker."""
        import app.engine.tools.scheduler_tools as scheduler_tools_module
        from app.engine.tools.scheduler_tools import (
            set_scheduler_user,
            tool_schedule_reminder,
        )
        from app.api.v1.websocket import ConnectionManager
        from app.services.notification_dispatcher import NotificationDispatcher
        from app.services.notifications.adapters.websocket import WebSocketAdapter
        from app.services.notifications.registry import NotificationChannelRegistry

        class InMemorySchedulerRepository:
            def __init__(self):
                self.tasks: list[dict] = []
                self.marked: list[dict] = []

            def create_task(self, **kwargs):
                task_id = "tool-created-reminder-1"
                self.tasks.append(
                    {
                        "id": task_id,
                        "user_id": kwargs["user_id"],
                        "domain_id": kwargs["domain_id"],
                        "description": kwargs["description"],
                        "schedule_type": kwargs["schedule_type"],
                        "schedule_expr": kwargs["schedule_expr"],
                        "next_run": kwargs["next_run"],
                        "last_run": None,
                        "run_count": 0,
                        "max_runs": None,
                        "status": "active",
                        "channel": "websocket",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "extra_data": {},
                        "organization_id": "org-tool",
                    }
                )
                return task_id

            def get_due_tasks(self, *, limit: int, allow_all_orgs: bool):
                assert allow_all_orgs is True
                return self.tasks[:limit]

            def mark_executed(self, task_id: str, *, next_run, organization_id):
                self.marked.append(
                    {
                        "task_id": task_id,
                        "next_run": next_run,
                        "organization_id": organization_id,
                    }
                )
                return True

        repo = InMemorySchedulerRepository()
        registry = NotificationChannelRegistry()
        registry.register(WebSocketAdapter())
        dispatcher = NotificationDispatcher()
        dispatcher._registry = registry
        manager = ConnectionManager()
        websocket = AsyncMock()
        other_org_websocket = AsyncMock()
        await manager.connect(websocket, "tool-session")
        await manager.connect(other_org_websocket, "tool-session-other-org")
        manager.register_user("tool-session", "tool-user", "org-tool")
        manager.register_user("tool-session-other-org", "tool-user", "org-other")

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

        scheduler_tools_module._scheduler_tool_state.set(None)
        set_scheduler_user("tool-user", "maritime")
        try:
            with patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=repo):
                created = tool_schedule_reminder.invoke(
                    {
                        "description": "Review COLREG Rule 13",
                        "when": future,
                    }
                )
            assert "tool-created-reminder-1" in created
            assert repo.tasks[0]["user_id"] == "tool-user"
            assert repo.tasks[0]["domain_id"] == "maritime"

            repo.tasks[0]["next_run"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            with patch("app.core.config.settings", mock_settings), \
                 patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=repo), \
                 patch("app.services.notification_dispatcher.get_notification_dispatcher", return_value=dispatcher), \
                 patch("app.api.v1.websocket.manager", manager):
                await executor._execute_due_tasks()
        finally:
            scheduler_tools_module._scheduler_tool_state.set(None)

        assert manager.is_user_online("tool-user") is True
        websocket.send_text.assert_awaited_once()
        other_org_websocket.send_text.assert_not_awaited()
        sent_message = websocket.send_text.await_args.args[0]
        payload = json.loads(sent_message)
        assert payload["type"] == "scheduled_task"
        assert payload["task_id"] == "tool-created-reminder-1"
        assert payload["mode"] == "notification"
        assert payload["content"] == "Review COLREG Rule 13"
        assert repo.marked == [
            {
                "task_id": "tool-created-reminder-1",
                "next_run": None,
                "organization_id": "org-tool",
            }
        ]
        assert _counter_value(
            "runtime.scheduled_tasks.delivery",
            {"mode": "notification", "status": "delivered"},
        ) == 1
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "notification", "status": "success"},
        ) == 1


# =============================================================================
# Error handling
# =============================================================================

class TestErrorHandling:

    @pytest.mark.asyncio
    async def test_execution_error_doesnt_crash(self, executor):
        """Error in one task doesn't prevent processing others."""
        task_good = {
            "id": "good-task-00000000",
            "user_id": "user-1",
            "description": "Good task",
            "schedule_type": "once",
            "channel": "websocket",
            "extra_data": {},
            "organization_id": "org-good",
        }
        task_bad = {
            "id": "bad-task-11111111",
            "user_id": "user-2",
            "description": "Bad task",
            "schedule_type": "once",
            "channel": "websocket",
            "extra_data": {"agent_invoke": True},
            "organization_id": "org-bad",
        }

        mock_repo = MagicMock()
        mock_repo.get_due_tasks.return_value = [task_bad, task_good]
        mock_repo.mark_executed.return_value = True

        mock_dispatcher = MagicMock()
        mock_dispatcher.notify_task_result = AsyncMock(
            return_value={"delivered": True, "channel": "websocket", "detail": "ok"}
        )

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 10
        mock_settings.scheduler_agent_timeout = 1

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo), \
             patch("app.services.notification_dispatcher.get_notification_dispatcher", return_value=mock_dispatcher), \
             patch(
                 "app.engine.multi_agent.runtime.run_wiii_turn",
                 side_effect=RuntimeError("LLM unavailable"),
             ):
            # Should not raise
            await executor._execute_due_tasks()

        # Good task should still have been processed
        assert mock_repo.mark_executed.call_count == 1  # Only good task
        assert mock_repo.mark_executed.call_args.kwargs["organization_id"] == "org-good"
        assert mock_repo.mark_failed.call_args.kwargs["organization_id"] == "org-bad"
        assert mock_dispatcher.notify_task_result.call_count == 1
        assert _counter_value("runtime.scheduled_tasks.due") == 2
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "agent", "status": "error"},
        ) == 1
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "notification", "status": "success"},
        ) == 1

    @pytest.mark.asyncio
    async def test_no_due_tasks(self, executor):
        """No due tasks = no-op."""
        mock_repo = MagicMock()
        mock_repo.get_due_tasks.return_value = []

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo):
            await executor._execute_due_tasks()

        mock_repo.get_due_tasks.assert_called_once_with(
            limit=5,
            allow_all_orgs=True,
        )
        assert _counter_value(
            "runtime.scheduled_tasks.polls", {"status": "success"}
        ) == 1
        assert _counter_value("runtime.scheduled_tasks.due") == 0
        assert "runtime.scheduled_tasks.runs" not in rm.snapshot()["counters"]

    @pytest.mark.asyncio
    async def test_poll_error_records_metric(self, executor):
        """Repository polling failures are visible to runtime alerting."""
        mock_repo = MagicMock()
        mock_repo.get_due_tasks.side_effect = RuntimeError("scheduler db down")

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo):
            with pytest.raises(RuntimeError, match="scheduler db down"):
                await executor._execute_due_tasks()

        assert _counter_value(
            "runtime.scheduled_tasks.polls", {"status": "error"}
        ) == 1

    @pytest.mark.asyncio
    async def test_task_timeout_records_metric(self, executor, sample_task_agent):
        """Agent task timeouts are tagged separately from generic failures."""
        mock_repo = MagicMock()
        mock_repo.get_due_tasks.return_value = [sample_task_agent]

        mock_dispatcher = MagicMock()
        mock_dispatcher.notify_task_result = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5
        mock_settings.scheduler_agent_timeout = 0.01

        async def slow_process(_request):
            await asyncio.sleep(10)
            return {}

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo), \
             patch("app.services.notification_dispatcher.get_notification_dispatcher", return_value=mock_dispatcher), \
             patch(
                 "app.engine.multi_agent.runtime.run_wiii_turn",
                 side_effect=slow_process,
             ):
            await executor._execute_due_tasks()

        mock_repo.mark_failed.assert_called_once_with(
            sample_task_agent["id"],
            "timeout",
            organization_id="org-2",
        )
        mock_dispatcher.notify_task_result.assert_not_called()
        assert _counter_value(
            "runtime.scheduled_tasks.runs",
            {"mode": "agent", "status": "timeout"},
        ) == 1


# =============================================================================
# Recurring task — next_run calculation
# =============================================================================

class TestRecurringNextRun:

    def test_calculate_next_run_once(self, executor, sample_task_once):
        """'once' task returns None (mark as completed)."""
        result = executor._calculate_next_run(sample_task_once)
        assert result is None

    def test_calculate_next_run_recurring(self, executor, sample_task_recurring):
        """Recurring task returns now + interval."""
        before = datetime.now(timezone.utc)
        result = executor._calculate_next_run(sample_task_recurring)
        after = datetime.now(timezone.utc)

        assert result is not None
        # Should be approximately now + 1 day
        expected = before + timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 2

    def test_calculate_next_run_invalid_expr(self, executor):
        """Invalid schedule_expr returns None."""
        task = {"schedule_type": "recurring", "schedule_expr": "invalid"}
        result = executor._calculate_next_run(task)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_recurring_sets_next_run(self, executor, sample_task_recurring):
        """Recurring task's mark_executed is called with a future next_run."""
        mock_repo = MagicMock()
        mock_repo.get_due_tasks.return_value = [sample_task_recurring]
        mock_repo.mark_executed.return_value = True

        mock_dispatcher = MagicMock()
        mock_dispatcher.notify_task_result = AsyncMock(
            return_value={"delivered": True, "channel": "websocket", "detail": "ok"}
        )

        mock_settings = MagicMock()
        mock_settings.scheduler_max_concurrent = 5

        with patch("app.core.config.settings", mock_settings), \
             patch("app.repositories.scheduler_repository.get_scheduler_repository", return_value=mock_repo), \
             patch("app.services.notification_dispatcher.get_notification_dispatcher", return_value=mock_dispatcher):
            await executor._execute_due_tasks()

        # Verify mark_executed was called with a next_run datetime
        call_args = mock_repo.mark_executed.call_args
        assert call_args[0][0] == sample_task_recurring["id"]
        next_run = call_args[1]["next_run"]
        assert next_run is not None
        assert next_run > datetime.now(timezone.utc)
        assert call_args[1]["organization_id"] == "org-1"


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    def test_get_scheduled_task_executor_singleton(self):
        """Singleton returns same instance."""
        import app.services.scheduled_task_executor as mod
        mod._executor = None  # Reset

        e1 = get_scheduled_task_executor()
        e2 = get_scheduled_task_executor()
        assert e1 is e2

        mod._executor = None  # Clean up
