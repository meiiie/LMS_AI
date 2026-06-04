from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.tasks import semantic_memory_tasks


@pytest.fixture(autouse=True)
def reset_task_cache():
    rm._reset_for_tests()
    semantic_memory_tasks._maintenance_task = None
    semantic_memory_tasks._maintenance_task_broker = None
    yield
    rm._reset_for_tests()
    semantic_memory_tasks._maintenance_task = None
    semantic_memory_tasks._maintenance_task_broker = None


@pytest.mark.asyncio
async def test_run_semantic_memory_maintenance_sets_and_resets_org_context(
    monkeypatch,
):
    from app.core.org_context import current_org_id

    prune = AsyncMock(return_value=2)
    monkeypatch.setattr(
        "app.services.memory_lifecycle.prune_stale_memories",
        prune,
    )
    semantic_memory = SimpleNamespace(
        is_available=lambda: True,
        check_and_summarize=AsyncMock(return_value=object()),
    )

    token = current_org_id.set(None)
    try:
        result = await semantic_memory_tasks.run_semantic_memory_maintenance(
            user_id="user1",
            session_id="session1",
            org_id="org-1",
            semantic_memory=semantic_memory,
        )
        assert current_org_id.get() is None
    finally:
        current_org_id.reset(token)

    assert result["success"] is True
    assert result["pruned_count"] == 2
    assert result["summarized"] is True
    assert "user_id" not in result
    assert "session_id" not in result
    assert "org_id" not in result
    assert result["user_id_hash"].startswith("sha256:")
    assert result["session_id_hash"].startswith("sha256:")
    assert result["organization_id_hash"].startswith("sha256:")
    prune.assert_awaited_once_with("user1", session_id="session1")
    semantic_memory.check_and_summarize.assert_awaited_once_with(
        user_id="user1",
        session_id="session1",
    )
    snap = rm.snapshot()
    run_labels = (
        ("executor", "taskiq"),
        ("status", "success"),
    )
    prune_labels = (("executor", "taskiq"),)
    assert snap["counters"]["runtime.semantic_memory.maintenance.runs"][run_labels] == 1
    assert snap["counters"]["runtime.semantic_memory.maintenance.pruned"][prune_labels] == 2
    assert (
        snap["counters"]["runtime.semantic_memory.maintenance.summarized"][
            prune_labels
        ]
        == 1
    )


@pytest.mark.asyncio
async def test_run_semantic_memory_maintenance_records_error_metric(monkeypatch):
    monkeypatch.setattr(
        "app.services.memory_lifecycle.prune_stale_memories",
        AsyncMock(return_value=0),
    )
    semantic_memory = SimpleNamespace(
        is_available=lambda: True,
        check_and_summarize=AsyncMock(side_effect=RuntimeError("summary failed")),
    )

    result = await semantic_memory_tasks.run_semantic_memory_maintenance(
        user_id="user1",
        session_id="session1",
        org_id="org-1",
        semantic_memory=semantic_memory,
        executor="local_fallback",
    )

    assert result["success"] is False
    assert result["error"] == "RuntimeError"
    snap = rm.snapshot()
    labels = (
        ("executor", "local_fallback"),
        ("status", "error"),
    )
    assert snap["counters"]["runtime.semantic_memory.maintenance.runs"][labels] == 1


@pytest.mark.asyncio
async def test_enqueue_semantic_memory_maintenance_skips_when_disabled(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_background_tasks", False)
    monkeypatch.setattr(
        semantic_memory_tasks,
        "_get_taskiq_maintenance_task",
        lambda: (_ for _ in ()).throw(AssertionError("should not touch broker")),
    )

    enqueued = await semantic_memory_tasks.enqueue_semantic_memory_maintenance(
        user_id="user1",
        session_id="session1",
        org_id="org-1",
    )

    assert enqueued is False
    snap = rm.snapshot()
    labels = (
        ("reason", "disabled"),
        ("status", "skipped"),
    )
    assert snap["counters"]["runtime.semantic_memory.maintenance.enqueue"][labels] == 1


@pytest.mark.asyncio
async def test_enqueue_semantic_memory_maintenance_calls_taskiq_kiq(
    monkeypatch,
):
    from app.core.config import settings

    enqueue = AsyncMock()
    task = SimpleNamespace(kiq=enqueue)
    monkeypatch.setattr(settings, "enable_background_tasks", True)
    monkeypatch.setattr(
        semantic_memory_tasks,
        "_get_taskiq_maintenance_task",
        lambda: task,
    )

    enqueued = await semantic_memory_tasks.enqueue_semantic_memory_maintenance(
        user_id="user1",
        session_id="session1",
        org_id="org-1",
    )

    assert enqueued is True
    enqueue.assert_awaited_once_with(
        user_id="user1",
        session_id="session1",
        org_id="org-1",
    )
    snap = rm.snapshot()
    labels = (
        ("reason", "taskiq"),
        ("status", "enqueued"),
    )
    assert snap["counters"]["runtime.semantic_memory.maintenance.enqueue"][labels] == 1


def test_get_taskiq_maintenance_task_registers_lazily(monkeypatch):
    registered = []

    class Broker:
        def task(self, **kwargs):
            registered.append(kwargs)

            def _decorate(fn):
                return SimpleNamespace(fn=fn, kiq=AsyncMock())

            return _decorate

    broker = Broker()
    monkeypatch.setattr(
        "app.core.task_broker.get_broker",
        lambda: broker,
    )

    task = semantic_memory_tasks._get_taskiq_maintenance_task()
    task_again = semantic_memory_tasks._get_taskiq_maintenance_task()

    assert task is task_again
    assert task.fn is semantic_memory_tasks.run_semantic_memory_maintenance
    assert registered == [{"task_name": "semantic_memory.maintenance"}]
