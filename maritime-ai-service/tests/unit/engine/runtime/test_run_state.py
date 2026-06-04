"""Phase 25 run-state machine — Runtime Migration #207.

Locks the contract:
- Legal transitions follow the documented graph.
- Illegal transitions raise IllegalTransitionError + don't mutate state.
- RETRYING bumps attempt count and clears prior error.
- Terminal states cannot transition.
- Listeners receive (prev, next, machine) and exceptions don't block.
- Retry policy backoff grows exponentially.
"""

from __future__ import annotations

import pytest

from app.engine.runtime.run_state import (
    IllegalTransitionError,
    RunRetryPolicy,
    RunState,
    RunStateMachine,
)


# ── transition graph ──

@pytest.mark.parametrize(
    "src,target",
    [
        (RunState.PENDING, RunState.DISPATCHING),
        (RunState.PENDING, RunState.FAILED),
        (RunState.DISPATCHING, RunState.RUNNING),
        (RunState.DISPATCHING, RunState.RETRYING),
        (RunState.DISPATCHING, RunState.FAILED),
        (RunState.RUNNING, RunState.COMPLETING),
        (RunState.RUNNING, RunState.RETRYING),
        (RunState.RUNNING, RunState.FAILED),
        (RunState.COMPLETING, RunState.SUCCEEDED),
        (RunState.COMPLETING, RunState.FAILED),
        (RunState.RETRYING, RunState.DISPATCHING),
        (RunState.RETRYING, RunState.FAILED),
    ],
)
async def test_legal_transitions(src, target):
    sm = RunStateMachine()
    # Walk to ``src`` first via legal hops.
    await _walk_to(sm, src)
    await sm.transition_to(target)
    assert sm.state == target


@pytest.mark.parametrize(
    "src,target",
    [
        (RunState.PENDING, RunState.RUNNING),
        (RunState.PENDING, RunState.SUCCEEDED),
        (RunState.DISPATCHING, RunState.SUCCEEDED),
        (RunState.RUNNING, RunState.PENDING),
        (RunState.SUCCEEDED, RunState.RUNNING),
        (RunState.FAILED, RunState.RUNNING),
    ],
)
async def test_illegal_transitions_raise(src, target):
    sm = RunStateMachine()
    await _walk_to(sm, src)
    with pytest.raises(IllegalTransitionError):
        await sm.transition_to(target)
    # State unchanged.
    assert sm.state == src


async def _walk_to(sm: RunStateMachine, target: RunState) -> None:
    """Drive sm to ``target`` via legal hops."""
    paths = {
        RunState.PENDING: [],
        RunState.DISPATCHING: [RunState.DISPATCHING],
        RunState.RUNNING: [RunState.DISPATCHING, RunState.RUNNING],
        RunState.COMPLETING: [
            RunState.DISPATCHING,
            RunState.RUNNING,
            RunState.COMPLETING,
        ],
        RunState.RETRYING: [RunState.DISPATCHING, RunState.RETRYING],
        RunState.SUCCEEDED: [
            RunState.DISPATCHING,
            RunState.RUNNING,
            RunState.COMPLETING,
            RunState.SUCCEEDED,
        ],
        RunState.FAILED: [RunState.FAILED],
    }
    for hop in paths[target]:
        await sm.transition_to(hop)


# ── attempt counter ──

async def test_attempt_starts_at_one():
    sm = RunStateMachine()
    assert sm.attempt == 1


async def test_retrying_increments_attempt():
    sm = RunStateMachine()
    await sm.transition_to(RunState.DISPATCHING)
    await sm.transition_to(RunState.RETRYING)
    assert sm.attempt == 2


async def test_multiple_retries_bump_attempt_each_time():
    sm = RunStateMachine(retry_policy=RunRetryPolicy(max_attempts=5))
    for _ in range(3):
        await sm.transition_to(RunState.DISPATCHING)
        await sm.transition_to(RunState.RETRYING)
    assert sm.attempt == 4


async def test_retrying_clears_prior_error():
    sm = RunStateMachine()
    await sm.transition_to(RunState.DISPATCHING)
    await sm.transition_to(RunState.RUNNING)
    await sm.transition_to(RunState.RETRYING, error="ignored")
    assert sm.snapshot().error is None


# ── terminal states ──

async def test_succeeded_is_terminal():
    sm = RunStateMachine()
    await _walk_to(sm, RunState.SUCCEEDED)
    assert sm.is_terminal is True
    with pytest.raises(IllegalTransitionError):
        await sm.transition_to(RunState.RUNNING)


async def test_failed_is_terminal():
    sm = RunStateMachine()
    await sm.transition_to(RunState.FAILED, error="hard fail")
    assert sm.is_terminal is True
    with pytest.raises(IllegalTransitionError):
        await sm.transition_to(RunState.DISPATCHING)


async def test_failure_records_error():
    sm = RunStateMachine()
    await sm.transition_to(RunState.FAILED, error="provider down")
    assert sm.snapshot().error == "provider down"


# ── listeners ──

async def test_listener_receives_prev_next_machine():
    sm = RunStateMachine()
    received = []

    async def listener(prev, target, machine):
        received.append((prev, target, machine.run_id))

    sm.add_listener(listener)
    await sm.transition_to(RunState.DISPATCHING)
    await sm.transition_to(RunState.RUNNING)
    assert received == [
        (RunState.PENDING, RunState.DISPATCHING, sm.run_id),
        (RunState.DISPATCHING, RunState.RUNNING, sm.run_id),
    ]


async def test_listener_exception_does_not_block_transition():
    sm = RunStateMachine()

    async def boom(prev, target, machine):
        raise RuntimeError("listener exploded")

    sm.add_listener(boom)
    # Should still transition cleanly.
    await sm.transition_to(RunState.DISPATCHING)
    assert sm.state == RunState.DISPATCHING


async def test_remove_listener_stops_callbacks():
    sm = RunStateMachine()
    received = []

    async def listener(prev, target, machine):
        received.append((prev, target))

    sm.add_listener(listener)
    sm.remove_listener(listener)
    await sm.transition_to(RunState.DISPATCHING)
    assert received == []


async def test_add_listener_is_idempotent():
    sm = RunStateMachine()
    received = []

    async def listener(prev, target, machine):
        received.append(target)

    sm.add_listener(listener)
    sm.add_listener(listener)  # second call no-op
    await sm.transition_to(RunState.DISPATCHING)
    assert len(received) == 1


# ── retry policy ──

def test_retry_policy_default_max_attempts():
    p = RunRetryPolicy()
    assert p.max_attempts == 3


def test_retry_policy_should_retry_under_max():
    p = RunRetryPolicy(max_attempts=3)
    assert p.should_retry(1) is True
    assert p.should_retry(2) is True
    assert p.should_retry(3) is False  # exhausted


def test_retry_policy_max_attempts_one_disables_retry():
    p = RunRetryPolicy(max_attempts=1)
    assert p.should_retry(1) is False


def test_retry_policy_backoff_grows_exponentially():
    p = RunRetryPolicy(backoff_base_seconds=1.0)
    assert p.backoff_for(1) == 1.0
    assert p.backoff_for(2) == 2.0
    assert p.backoff_for(3) == 4.0
    assert p.backoff_for(4) == 8.0


# ── snapshot ──

async def test_snapshot_captures_state_and_metadata():
    sm = RunStateMachine(metadata={"org_id": "org-A"})
    await sm.transition_to(RunState.DISPATCHING)
    snap = sm.snapshot()
    assert snap.run_id == sm.run_id
    assert snap.state == RunState.DISPATCHING
    assert snap.attempt == 1
    assert snap.metadata == {"org_id": "org-A"}
    assert snap.last_transition_at >= snap.started_at


async def test_snapshot_sanitizes_metadata_and_error():
    sm = RunStateMachine(
        metadata={
            "org_id": "org-A",
            "user_id": "raw-user-id",
            "access_token": "raw-access-token",
        }
    )
    await sm.transition_to(
        RunState.FAILED,
        error=(
            "provider failed Bearer raw-bearer-token-123 "
            "token=raw-token-inline"
        ),
    )

    snap = sm.snapshot()

    assert snap.metadata["org_id"] == "org-A"
    assert snap.metadata["user_id_hash"].startswith("sha256:")
    assert "<redacted-secret>" in snap.error
    serialized = str(snap)
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "raw-token-inline" not in serialized
    assert "access_token" not in serialized


async def test_snapshot_is_independent_of_machine():
    sm = RunStateMachine()
    await sm.transition_to(RunState.DISPATCHING)
    snap = sm.snapshot()
    await sm.transition_to(RunState.RUNNING)
    # Old snapshot is frozen at the time of capture.
    assert snap.state == RunState.DISPATCHING
