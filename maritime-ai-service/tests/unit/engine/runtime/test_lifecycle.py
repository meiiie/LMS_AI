"""Phase 27 lifecycle hooks — Runtime Migration #207.

Locks the contract:
- register/unregister are idempotent.
- fire passes the payload dict to every hook at that point.
- Hook exception is logged + does not break dispatcher / other hooks.
- Hooks fire in registration order.
- Empty bucket fires no-op.
- Reset clears every hook on the singleton.
"""

from __future__ import annotations

import logging

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.engine.runtime.lifecycle import (
    HookPoint,
    HookRegistration,
    LIFECYCLE_REGISTRATION_REPORT_VERSION,
    Lifecycle,
    build_lifecycle_registration_report,
    get_lifecycle,
    register_default_lifecycle_hooks,
)


@pytest.fixture(autouse=True)
def reset_runtime_metrics():
    rm._reset_for_tests()
    yield
    rm._reset_for_tests()


@pytest.fixture
def lifecycle():
    return Lifecycle()


# ── register / unregister ──

async def test_register_records_hook(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    assert lifecycle.hooks_at(HookPoint.ON_RUN_START) == [hook]


async def test_register_records_explicit_owner_metadata(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(
        HookPoint.ON_RUN_END,
        hook,
        owner="engine.semantic_memory",
    )

    registrations = lifecycle.registrations_at(HookPoint.ON_RUN_END)
    assert registrations == [
        HookRegistration(
            hook=hook,
            owner="engine.semantic_memory",
            name="hook",
            module=hook.__module__,
        )
    ]
    assert lifecycle.hooks_at(HookPoint.ON_RUN_END) == [hook]


async def test_register_is_idempotent(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    lifecycle.register(HookPoint.ON_RUN_START, hook)
    assert lifecycle.hooks_at(HookPoint.ON_RUN_START) == [hook]


async def test_register_idempotency_preserves_original_owner(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(HookPoint.ON_RUN_START, hook, owner="engine.runtime")
    lifecycle.register(HookPoint.ON_RUN_START, hook, owner="engine.semantic_memory")

    registrations = lifecycle.registrations_at(HookPoint.ON_RUN_START)
    assert [registration.owner for registration in registrations] == ["engine.runtime"]


async def test_register_default_lifecycle_hooks_installs_runtime_owned_hooks(lifecycle):
    registrations = register_default_lifecycle_hooks(lifecycle)
    register_default_lifecycle_hooks(lifecycle)

    assert {
        (registration.owner, registration.name)
        for registration in registrations
    } == {
        ("engine.runtime", "_record_run_end_hook"),
        ("engine.runtime", "_record_run_error_hook"),
    }
    assert [
        registration.name
        for registration in lifecycle.registrations_at(HookPoint.ON_RUN_END)
    ] == ["_record_run_end_hook"]
    assert [
        registration.name
        for registration in lifecycle.registrations_at(HookPoint.ON_RUN_ERROR)
    ] == ["_record_run_error_hook"]
    assert len(lifecycle.hooks_at(HookPoint.ON_RUN_END)) == 1
    assert len(lifecycle.hooks_at(HookPoint.ON_RUN_ERROR)) == 1

    await lifecycle.fire(HookPoint.ON_RUN_END, {"status": "success"})
    await lifecycle.fire(HookPoint.ON_RUN_ERROR, {"error": "provider down"})

    snap = rm.snapshot()
    assert snap["counters"]["runtime.lifecycle.hook_runs"][
        (
            ("owner", "engine.runtime"),
            ("point", "on_run_end"),
            ("status", "success"),
        )
    ] == 1
    assert snap["counters"]["runtime.lifecycle.hook_runs"][
        (
            ("owner", "engine.runtime"),
            ("point", "on_run_error"),
            ("status", "error"),
        )
    ] == 1


async def test_lifecycle_registration_report_summarizes_owners_and_runtime_defaults(
    lifecycle,
):
    async def memory_hook(payload):
        pass

    lifecycle.register(
        HookPoint.ON_RUN_END,
        memory_hook,
        owner="engine.semantic_memory",
    )
    register_default_lifecycle_hooks(lifecycle)

    report = build_lifecycle_registration_report(lifecycle)

    assert report["version"] == LIFECYCLE_REGISTRATION_REPORT_VERSION
    assert report["registration_count"] == 3
    assert report["owner_counts"] == {
        "engine.runtime": 2,
        "engine.semantic_memory": 1,
    }
    assert report["point_counts"]["on_run_end"] == 2
    assert report["point_counts"]["on_run_error"] == 1
    assert report["default_runtime_hooks"]["installed"] is True
    assert report["default_runtime_hooks"]["registered_count"] == 2
    assert {
        (registration["point"], registration["owner"], registration["name"])
        for registration in report["registrations"]
    } == {
        ("on_run_end", "engine.semantic_memory", "memory_hook"),
        ("on_run_end", "engine.runtime", "_record_run_end_hook"),
        ("on_run_error", "engine.runtime", "_record_run_error_hook"),
    }
    assert report["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "code_metadata_only",
    }


def test_startup_registration_installs_default_lifecycle_hooks():
    from app.engine.runtime import lifecycle as lc_mod
    from app.main_startup_runtime import _register_runtime_lifecycle_hooks

    lc_mod._reset_for_tests()
    try:
        _register_runtime_lifecycle_hooks(logging.getLogger("test"))
        lc = lc_mod.get_lifecycle()

        assert [
            registration.owner
            for registration in lc.registrations_at(HookPoint.ON_RUN_END)
        ] == ["engine.runtime", "engine.semantic_memory"]
        assert [
            registration.owner
            for registration in lc.registrations_at(HookPoint.ON_RUN_ERROR)
        ] == ["engine.runtime", "engine.semantic_memory"]
    finally:
        lc_mod._reset_for_tests()


async def test_bound_method_registration_is_idempotent(lifecycle):
    class Hooks:
        async def hook(self, payload):
            pass

    hooks = Hooks()

    lifecycle.register(HookPoint.ON_RUN_START, hooks.hook, owner="engine.runtime")
    lifecycle.register(HookPoint.ON_RUN_START, hooks.hook, owner="engine.runtime")

    assert len(lifecycle.hooks_at(HookPoint.ON_RUN_START)) == 1
    assert lifecycle.unregister(HookPoint.ON_RUN_START, hooks.hook) is True
    assert lifecycle.hooks_at(HookPoint.ON_RUN_START) == []


async def test_unregister_returns_true_when_present(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    assert lifecycle.unregister(HookPoint.ON_RUN_START, hook) is True
    assert lifecycle.hooks_at(HookPoint.ON_RUN_START) == []


async def test_unregister_returns_false_when_absent(lifecycle):
    async def hook(payload):
        pass

    assert lifecycle.unregister(HookPoint.ON_RUN_START, hook) is False


async def test_hooks_at_returns_independent_copy(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    snapshot = lifecycle.hooks_at(HookPoint.ON_RUN_START)
    snapshot.clear()
    # Internal bucket unaffected.
    assert lifecycle.hooks_at(HookPoint.ON_RUN_START) == [hook]


# ── fire ──

async def test_fire_with_no_hooks_is_noop(lifecycle):
    # No hooks registered → no exception.
    await lifecycle.fire(HookPoint.ON_RUN_START, {"x": 1})


async def test_fire_passes_payload_to_each_hook(lifecycle):
    received: list[dict] = []

    async def hook_a(payload):
        received.append({"label": "a", **payload})

    async def hook_b(payload):
        received.append({"label": "b", **payload})

    lifecycle.register(HookPoint.ON_RUN_END, hook_a)
    lifecycle.register(HookPoint.ON_RUN_END, hook_b)
    await lifecycle.fire(HookPoint.ON_RUN_END, {"session_id": "s1"})

    assert received == [
        {"label": "a", "session_id": "s1"},
        {"label": "b", "session_id": "s1"},
    ]


async def test_fire_sanitizes_payload_before_hooks(lifecycle):
    received: list[dict] = []

    async def hook(payload):
        received.append(dict(payload))

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    await lifecycle.fire(
        HookPoint.ON_RUN_START,
        {
            "session_id": "s1",
            "user_id": "raw-user-id",
            "access_token": "raw-access-token",
            "error": (
                "provider failed with Bearer raw-bearer-token-123 "
                "client_secret=raw-client-secret-inline"
            ),
            "host": {
                "safe_id": "page-1",
                "provider_payload": {"id": "raw-provider"},
            },
        },
    )

    payload = received[0]
    assert payload["session_id"] == "s1"
    assert payload["user_id_hash"].startswith("sha256:")
    assert payload["host"]["safe_id"] == "page-1"
    assert "<redacted-secret>" in payload["error"]
    serialized = str(payload)
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "raw-client-secret-inline" not in serialized
    assert "raw-provider" not in serialized
    assert "provider_payload" not in serialized


async def test_fire_preserves_registration_order(lifecycle):
    received: list[str] = []

    async def make(label):
        async def hook(payload):
            received.append(label)

        return hook

    h1 = await make("first")
    h2 = await make("second")
    h3 = await make("third")
    lifecycle.register(HookPoint.ON_TOOL_END, h1)
    lifecycle.register(HookPoint.ON_TOOL_END, h2)
    lifecycle.register(HookPoint.ON_TOOL_END, h3)

    await lifecycle.fire(HookPoint.ON_TOOL_END, {})
    assert received == ["first", "second", "third"]


async def test_faulty_hook_does_not_break_chain(lifecycle, caplog):
    received: list[str] = []

    async def boom(payload):
        raise RuntimeError("boom")

    async def good(payload):
        received.append("good ran")

    boom.__module__ = "app.engine.semantic_memory.write_audit"
    lifecycle.register(HookPoint.ON_RUN_START, boom)
    lifecycle.register(HookPoint.ON_RUN_START, good)

    with caplog.at_level(logging.DEBUG, logger="app.engine.runtime.lifecycle"):
        await lifecycle.fire(HookPoint.ON_RUN_START, {})

    # Good hook still ran.
    assert received == ["good ran"]
    snap = rm.snapshot()
    labels = (
        ("owner", "engine.semantic_memory"),
        ("point", "on_run_start"),
    )
    assert snap["counters"]["runtime.lifecycle.hook_failures"][labels] == 1


async def test_faulty_hook_metric_uses_explicit_registration_owner(lifecycle):
    async def boom(payload):
        raise RuntimeError("boom")

    boom.__module__ = "app.engine.semantic_memory.write_audit"
    lifecycle.register(HookPoint.ON_RUN_END, boom, owner="engine.runtime")

    await lifecycle.fire(HookPoint.ON_RUN_END, {})

    snap = rm.snapshot()
    labels = (
        ("owner", "engine.runtime"),
        ("point", "on_run_end"),
    )
    assert snap["counters"]["runtime.lifecycle.hook_failures"][labels] == 1
    inferred_labels = (
        ("owner", "engine.semantic_memory"),
        ("point", "on_run_end"),
    )
    assert inferred_labels not in snap["counters"]["runtime.lifecycle.hook_failures"]


async def test_invalid_explicit_owner_falls_back_to_inferred_owner(lifecycle):
    async def boom(payload):
        raise RuntimeError("boom")

    boom.__module__ = "app.engine.semantic_memory.write_audit"
    lifecycle.register(HookPoint.ON_RUN_END, boom, owner="unsafe owner value")

    registration = lifecycle.registrations_at(HookPoint.ON_RUN_END)[0]
    assert registration.owner == "engine.semantic_memory"

    await lifecycle.fire(HookPoint.ON_RUN_END, {})
    snap = rm.snapshot()
    labels = (
        ("owner", "engine.semantic_memory"),
        ("point", "on_run_end"),
    )
    assert snap["counters"]["runtime.lifecycle.hook_failures"][labels] == 1


async def test_fire_uses_empty_dict_when_payload_omitted(lifecycle):
    seen: list[dict] = []

    async def hook(payload):
        seen.append(payload)

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    await lifecycle.fire(HookPoint.ON_RUN_START)
    assert seen == [{}]


async def test_unregister_during_fire_does_not_skip_others(lifecycle):
    """fire iterates over a SNAPSHOT of the bucket; mid-fire registry
    mutations don't affect the in-flight invocation."""
    received: list[str] = []

    async def remove_self(payload):
        received.append("remove_self")
        # Note: lifecycle.unregister of self after running should not
        # affect subsequent hooks during this fire.
        lifecycle.unregister(HookPoint.ON_RUN_START, remove_self)

    async def runs_after(payload):
        received.append("runs_after")

    lifecycle.register(HookPoint.ON_RUN_START, remove_self)
    lifecycle.register(HookPoint.ON_RUN_START, runs_after)
    await lifecycle.fire(HookPoint.ON_RUN_START, {})

    assert received == ["remove_self", "runs_after"]


# ── reset ──

def test_reset_clears_all_buckets(lifecycle):
    async def hook(payload):
        pass

    lifecycle.register(HookPoint.ON_RUN_START, hook)
    lifecycle.register(HookPoint.ON_TOOL_END, hook)
    lifecycle.reset()
    assert lifecycle.hooks_at(HookPoint.ON_RUN_START) == []
    assert lifecycle.hooks_at(HookPoint.ON_TOOL_END) == []


# ── singleton ──

def test_get_lifecycle_returns_same_instance():
    a = get_lifecycle()
    b = get_lifecycle()
    assert a is b


# ── integration with native_dispatch ──

async def test_lifecycle_fires_around_native_dispatch():
    """Phase 27 wiring: ON_RUN_START + ON_RUN_END fire on success path."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.engine.runtime import lifecycle as lc_mod
    from app.engine.runtime.native_dispatch import native_chat_dispatch
    from app.engine.runtime.session_event_log import InMemorySessionEventLog

    lc_mod._reset_for_tests()
    lc = lc_mod.get_lifecycle()
    events: list[tuple[HookPoint, dict]] = []

    async def record_start(payload):
        events.append((HookPoint.ON_RUN_START, dict(payload)))

    async def record_end(payload):
        events.append((HookPoint.ON_RUN_END, dict(payload)))

    lc.register(HookPoint.ON_RUN_START, record_start)
    lc.register(HookPoint.ON_RUN_END, record_end)

    fake_response = SimpleNamespace(
        message="hi",
        metadata={"latency_ms": 50},
        agent_type=SimpleNamespace(value="rag"),
    )
    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=fake_response)
    )
    request = SimpleNamespace(
        user_id="u1",
        session_id="s1",
        message="ping",
        organization_id="org-A",
        role=SimpleNamespace(value="student"),
        domain_id="maritime",
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        await native_chat_dispatch(request, event_log=InMemorySessionEventLog())

    # Ordered: start, then end. Both carry session_id.
    assert [point for point, _ in events] == [
        HookPoint.ON_RUN_START,
        HookPoint.ON_RUN_END,
    ]
    assert events[0][1]["session_id"] == "s1"
    assert events[0][1]["user_message"] == "ping"
    assert events[0][1]["user_id_hash"].startswith("sha256:")
    assert "user_id" not in events[0][1]
    assert events[1][1]["status"] == "success"
    lc_mod._reset_for_tests()


async def test_lifecycle_fires_run_error_then_run_end_on_failure():
    """Exception path: ON_RUN_ERROR before ON_RUN_END(status=error)."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.engine.runtime import lifecycle as lc_mod
    from app.engine.runtime.native_dispatch import native_chat_dispatch
    from app.engine.runtime.session_event_log import InMemorySessionEventLog

    lc_mod._reset_for_tests()
    lc = lc_mod.get_lifecycle()
    events: list[HookPoint] = []

    async def record(payload, *, point):
        events.append(point)

    lc.register(
        HookPoint.ON_RUN_START,
        lambda p: record(p, point=HookPoint.ON_RUN_START),
    )
    lc.register(
        HookPoint.ON_RUN_ERROR,
        lambda p: record(p, point=HookPoint.ON_RUN_ERROR),
    )
    lc.register(
        HookPoint.ON_RUN_END,
        lambda p: record(p, point=HookPoint.ON_RUN_END),
    )

    fake_service = SimpleNamespace(
        process_message=AsyncMock(side_effect=RuntimeError("provider down"))
    )
    request = SimpleNamespace(
        user_id="u1",
        session_id="s2",
        message="ping",
        organization_id="org-A",
        role=SimpleNamespace(value="student"),
        domain_id="maritime",
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        with pytest.raises(RuntimeError):
            await native_chat_dispatch(
                request, event_log=InMemorySessionEventLog()
            )

    assert events == [
        HookPoint.ON_RUN_START,
        HookPoint.ON_RUN_ERROR,
        HookPoint.ON_RUN_END,
    ]
    lc_mod._reset_for_tests()
