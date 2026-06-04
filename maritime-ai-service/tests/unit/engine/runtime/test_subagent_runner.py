"""Phase 12 SubagentRunner — Runtime Migration #207.

Locks the Anthropic-style Task pattern contract:
- Parent's session log gets exactly two events per delegation
  (``subagent_started`` + ``subagent_completed``), NOT the child's
  working messages.
- Child session id is derived from parent so siblings can be traced.
- Feature flag default-off keeps production behaviour unchanged.
- Errors from the runner_callable are caught + still produce a
  ``subagent_completed`` event so a parent wake() sees a clean closure.
"""

from __future__ import annotations

import pytest

from app.engine.runtime.session_event_log import InMemorySessionEventLog
from app.engine.runtime.subagent_runner import (
    SubagentResult,
    SubagentRunner,
    SubagentTask,
)


def _enable_isolation(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings, "enable_subagent_isolation", True, raising=False
    )


@pytest.fixture
def log() -> InMemorySessionEventLog:
    return InMemorySessionEventLog()


# ── feature flag ──

async def test_disabled_when_flag_off(log, monkeypatch):
    """Default settings → run() returns ``disabled`` without touching the log."""
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings, "enable_subagent_isolation", False, raising=False
    )

    async def runner(task, child_id):
        raise AssertionError("runner should not be invoked when disabled")

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    task = SubagentTask(description="x", parent_session_id="p1")
    result = await runner_obj.run(task)
    assert result.status == "disabled"
    # No events on the parent log — the runner never started.
    assert await log.get_events(session_id="p1") == []


async def test_no_runner_callable_returns_error(log, monkeypatch):
    _enable_isolation(monkeypatch)
    runner_obj = SubagentRunner(runner_callable=None, event_log=log)
    task = SubagentTask(description="x", parent_session_id="p1")
    result = await runner_obj.run(task)
    assert result.status == "error"
    assert "runner_callable" in (result.error or "")


# ── happy path ──

async def test_success_records_started_and_completed_on_parent_log(log, monkeypatch):
    _enable_isolation(monkeypatch)

    async def runner(task: SubagentTask, child_id: str) -> SubagentResult:
        return SubagentResult(
            status="success",
            summary="answered",
            sources=[{"id": "doc-1"}],
            tool_calls_made=2,
            child_session_id=child_id,
        )

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    task = SubagentTask(
        description="What is COLREGs Rule 13?",
        parent_session_id="p1",
        parent_org_id="org-A",
    )
    result = await runner_obj.run(task)

    assert result.status == "success"
    assert result.summary == "answered"
    assert result.sources == [{"id": "doc-1"}]
    assert result.tool_calls_made == 2
    assert result.child_session_id.startswith("p1::sub::")

    parent_events = await log.get_events(session_id="p1")
    assert [e.event_type for e in parent_events] == [
        "subagent_started",
        "subagent_completed",
    ]
    started_payload = parent_events[0].payload
    assert started_payload["child_session_id"].startswith("p1::sub::")
    assert started_payload["task"]["version"] == "wiii.subagent_task_provenance.v1"
    assert started_payload["task"]["description"]["present"] is True
    assert started_payload["task"]["description"]["char_count"] == len(
        "What is COLREGs Rule 13?"
    )
    assert started_payload["task"]["description"]["hash"].startswith("sha256:")
    assert "What is COLREGs Rule 13?" not in str(started_payload)
    completed_payload = parent_events[1].payload
    assert completed_payload["result"]["status"] == "success"
    assert completed_payload["result"]["summary"]["present"] is True
    assert completed_payload["result"]["summary"]["char_count"] == len("answered")
    assert completed_payload["result"]["tool_calls_made"] == 2
    assert "answered" not in str(completed_payload)


async def test_parent_log_does_not_contain_childs_working_events(log, monkeypatch):
    """The whole point: parent's wake() should not see child's user/assistant turns."""
    _enable_isolation(monkeypatch)

    async def runner(task: SubagentTask, child_id: str) -> SubagentResult:
        # Child writes its own working events to its own session id.
        await log.append(
            session_id=child_id, event_type="user_message", payload={"text": "step 1"}
        )
        await log.append(
            session_id=child_id,
            event_type="assistant_message",
            payload={"text": "step 1 done"},
        )
        return SubagentResult(status="success", summary="all done")

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    task = SubagentTask(description="multistep", parent_session_id="p1")
    result = await runner_obj.run(task)

    parent_events = await log.get_events(session_id="p1")
    parent_types = [e.event_type for e in parent_events]
    # Parent only sees the bookend events.
    assert parent_types == ["subagent_started", "subagent_completed"]
    # Child has its own private log.
    child_events = await log.get_events(session_id=result.child_session_id)
    child_types = [e.event_type for e in child_events]
    assert child_types == ["user_message", "assistant_message"]


async def test_parent_log_records_subagent_provenance_without_raw_task_or_result(
    log,
    monkeypatch,
):
    _enable_isolation(monkeypatch)

    async def runner(task: SubagentTask, child_id: str) -> SubagentResult:
        return SubagentResult(
            status="success",
            summary="child answer includes Bearer raw-result-token-123",
            child_session_id=child_id,
        )

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    await runner_obj.run(
        SubagentTask(
            description=(
                "read uploaded document Bearer raw-task-token-123 "
                "api_key=raw-api-key-inline"
            ),
            parent_session_id="p1",
            context_hints={"access_token": "raw-access-token", "safe": "ok"},
            metadata={"route": "analysis", "notes": "raw private note"},
        )
    )

    parent_events = await log.get_events(session_id="p1")
    serialized = str([event.payload for event in parent_events])
    assert "raw-task-token-123" not in serialized
    assert "raw-api-key-inline" not in serialized
    assert "raw-result-token-123" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw private note" not in serialized
    started_task = parent_events[0].payload["task"]
    assert started_task["context_hint_count"] == 2
    assert started_task["metadata_keys"] == ["notes", "route"]
    completed_result = parent_events[1].payload["result"]
    assert completed_result["summary"]["present"] is True
    assert completed_result["summary"]["hash"].startswith("sha256:")


async def test_org_id_propagated_to_both_events(log, monkeypatch):
    _enable_isolation(monkeypatch)

    async def runner(task, child_id):
        return SubagentResult(status="success", summary="ok")

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    task = SubagentTask(
        description="x", parent_session_id="p1", parent_org_id="org-A"
    )
    await runner_obj.run(task)

    org_a_events = await log.get_events(session_id="p1", org_id="org-A")
    assert len(org_a_events) == 2
    org_b_events = await log.get_events(session_id="p1", org_id="org-B")
    assert org_b_events == []


async def test_runner_returning_string_is_coerced(log, monkeypatch):
    """A lazy runner that returns just a string still produces a valid result."""
    _enable_isolation(monkeypatch)

    async def runner(task, child_id):
        return "just-a-string"

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    task = SubagentTask(description="x", parent_session_id="p1")
    result = await runner_obj.run(task)
    assert result.status == "success"
    assert result.summary == "just-a-string"
    assert result.child_session_id.startswith("p1::sub::")


# ── error paths ──

async def test_runner_exception_records_completion_with_error(log, monkeypatch):
    _enable_isolation(monkeypatch)

    async def runner(task, child_id):
        raise RuntimeError("provider down")

    runner_obj = SubagentRunner(runner_callable=runner, event_log=log)
    task = SubagentTask(description="x", parent_session_id="p1")
    result = await runner_obj.run(task)

    assert result.status == "error"
    assert "provider down" in (result.error or "")

    parent_events = await log.get_events(session_id="p1")
    assert [e.event_type for e in parent_events] == [
        "subagent_started",
        "subagent_completed",
    ]
    assert parent_events[1].payload["result"]["status"] == "error"
    assert parent_events[1].payload["result"]["error_type"] == "RuntimeError"
    assert parent_events[1].payload["result"]["error"]["present"] is True
    assert "provider down" not in str(parent_events[1].payload)


# ── child session id derivation ──

def test_derive_child_session_id_namespacing():
    parent = "user_42__session_xyz"
    child = SubagentRunner.derive_child_session_id(parent)
    assert child.startswith(parent + "::sub::")
    # Suffix is 8 hex chars.
    suffix = child[len(parent) + len("::sub::"):]
    assert len(suffix) == 8
    int(suffix, 16)  # must parse as hex


def test_derive_child_session_id_is_unique():
    parent = "p1"
    ids = {SubagentRunner.derive_child_session_id(parent) for _ in range(100)}
    assert len(ids) == 100
