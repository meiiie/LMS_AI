import logging

import pytest

from app.engine.multi_agent.direct_tool_post_dispatch_runtime import (
    process_direct_tool_post_dispatch,
)
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
)


@pytest.mark.asyncio
async def test_process_direct_tool_post_dispatch_appends_events_and_reflection() -> None:
    pushed_events: list[dict] = []
    messages: list[dict] = []
    tool_call_events: list[dict] = []
    visual_session_ids: list[str] = []

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    async def maybe_emit_host_action_event(**kwargs) -> None:
        pushed_events.append({"type": "host_action_checked", "tool": kwargs["tool_name"]})

    async def maybe_emit_visual_event(**kwargs) -> tuple[list[str], list[str]]:
        pushed_events.append({"type": "visual_checked", "tool": kwargs["tool_name"]})
        return ["vs-1"], []

    async def build_reflection(state, tool_name, result) -> str:
        return f"{tool_name}: reflected {result}"

    async def push_status_only_progress(push_event, **kwargs) -> None:
        await push_event({"type": "status", "content": kwargs["content"]})

    state = await process_direct_tool_post_dispatch(
        tool_name="tool_web_search",
        tool_args={"query": "maritime"},
        tool_call_id="call-1",
        result="search result",
        state={},
        messages=messages,
        tool_call_events=tool_call_events,
        push_event=push_event,
        native_tool_messages=False,
        active_visual_session_ids=[],
        visual_session_ids=visual_session_ids,
        visual_emitted_any=False,
        handoffs_enabled=True,
        maybe_emit_host_action_event=maybe_emit_host_action_event,
        maybe_emit_visual_event=maybe_emit_visual_event,
        build_direct_tool_reflection=build_reflection,
        push_status_only_progress=push_status_only_progress,
        build_tool_result_message=lambda content, **kwargs: {
            "content": content,
            "tool_call_id": kwargs["tool_call_id"],
        },
        logger_obj=logging.getLogger(__name__),
    )

    assert state.result == "search result"
    assert state.active_visual_session_ids == ["vs-1"]
    assert state.visual_emitted_any is True
    assert visual_session_ids == ["vs-1"]
    assert tool_call_events == [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": "search result",
            "id": "call-1",
        }
    ]
    assert messages == [{"content": "search result", "tool_call_id": "call-1"}]
    assert pushed_events == [
        {"type": "host_action_checked", "tool": "tool_web_search"},
        {"type": "visual_checked", "tool": "tool_web_search"},
        {"type": "status", "content": "tool_web_search: reflected search result"},
    ]


@pytest.mark.asyncio
async def test_process_direct_tool_post_dispatch_updates_visual_disposals() -> None:
    async def noop_push_event(event: dict) -> None:
        return None

    async def noop_host_action(**kwargs) -> None:
        return None

    async def dispose_visual(**kwargs) -> tuple[list[str], list[str]]:
        return [], ["drop-me"]

    async def no_reflection(state, tool_name, result) -> str:
        return ""

    async def noop_progress(*args, **kwargs) -> None:
        return None

    state = await process_direct_tool_post_dispatch(
        tool_name="tool_visual_dispose",
        tool_args={},
        tool_call_id="call-2",
        result="disposed",
        state={},
        messages=[],
        tool_call_events=[],
        push_event=noop_push_event,
        native_tool_messages=False,
        active_visual_session_ids=["keep-me", "drop-me"],
        visual_session_ids=[],
        visual_emitted_any=False,
        handoffs_enabled=True,
        maybe_emit_host_action_event=noop_host_action,
        maybe_emit_visual_event=dispose_visual,
        build_direct_tool_reflection=no_reflection,
        push_status_only_progress=noop_progress,
        build_tool_result_message=lambda content, **kwargs: content,
        logger_obj=logging.getLogger(__name__),
    )

    assert state.active_visual_session_ids == ["keep-me"]
    assert state.visual_emitted_any is False


@pytest.mark.asyncio
async def test_process_direct_tool_post_dispatch_records_handoff_target() -> None:
    async def noop_push_event(event: dict) -> None:
        return None

    async def noop_host_action(**kwargs) -> None:
        return None

    async def no_visual(**kwargs) -> tuple[list[str], list[str]]:
        return [], []

    async def no_reflection(state, tool_name, result) -> str:
        return ""

    async def noop_progress(*args, **kwargs) -> None:
        return None

    graph_state: dict = {}
    await process_direct_tool_post_dispatch(
        tool_name="handoff_to_agent",
        tool_args={"target_agent": "rag_agent"},
        tool_call_id="call-3",
        result="handoff requested",
        state=graph_state,
        messages=[],
        tool_call_events=[],
        push_event=noop_push_event,
        native_tool_messages=False,
        active_visual_session_ids=[],
        visual_session_ids=[],
        visual_emitted_any=False,
        handoffs_enabled=True,
        maybe_emit_host_action_event=noop_host_action,
        maybe_emit_visual_event=no_visual,
        build_direct_tool_reflection=no_reflection,
        push_status_only_progress=noop_progress,
        build_tool_result_message=lambda content, **kwargs: content,
        logger_obj=logging.getLogger(__name__),
    )

    assert graph_state["_handoff_target"] == "rag_agent"


@pytest.mark.asyncio
async def test_process_direct_tool_post_dispatch_resumes_host_action_result() -> None:
    import json

    from app.engine.context.host_action_result_bridge import publish_host_action_result
    from app.engine.multi_agent.visual_events import _maybe_emit_host_action_event

    pushed_events: list[dict] = []
    messages: list[dict] = []
    tool_call_events: list[dict] = []

    async def push_event(event: dict) -> None:
        pushed_events.append(event)
        if event.get("type") == "host_action":
            content = event.get("content") or {}
            publish_host_action_result(
                request_id=content["id"],
                action=content["action"],
                success=True,
                summary="Da dang bai Facebook.",
                data={"provider_post_id": "post-1"},
                user_id="teacher-1",
                organization_id="org-1",
            )

    async def no_visual(**kwargs) -> tuple[list[str], list[str]]:
        return [], []

    async def no_reflection(state, tool_name, result) -> str:
        return ""

    async def noop_progress(*args, **kwargs) -> None:
        return None

    initial_result = json.dumps(
        {
            "status": "action_requested",
            "request_id": "req-facebook-direct-result-1",
            "action": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
            "params": {"message": "Xin chao"},
        },
        ensure_ascii=False,
    )

    state = await process_direct_tool_post_dispatch(
        tool_name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        tool_args={"message": "Xin chao"},
        tool_call_id="call-facebook-1",
        result=initial_result,
        state={"user_id": "teacher-1", "organization_id": "org-1"},
        messages=messages,
        tool_call_events=tool_call_events,
        push_event=push_event,
        native_tool_messages=False,
        active_visual_session_ids=[],
        visual_session_ids=[],
        visual_emitted_any=False,
        handoffs_enabled=False,
        maybe_emit_host_action_event=_maybe_emit_host_action_event,
        maybe_emit_visual_event=no_visual,
        build_direct_tool_reflection=no_reflection,
        push_status_only_progress=noop_progress,
        build_tool_result_message=lambda content, **kwargs: {
            "content": content,
            "tool_call_id": kwargs["tool_call_id"],
        },
        logger_obj=logging.getLogger(__name__),
    )

    final_payload = json.loads(state.result)

    assert pushed_events[0]["type"] == "host_action"
    assert final_payload["status"] == "action_completed"
    assert final_payload["summary"] == "Da dang bai Facebook."
    assert [event["type"] for event in tool_call_events] == [
        "host_action",
        "host_action_result",
        "result",
    ]
    assert messages[0]["content"] == state.result
