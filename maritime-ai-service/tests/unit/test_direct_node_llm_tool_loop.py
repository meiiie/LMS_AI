from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.multi_agent.direct_node_llm_tool_loop import (
    execute_direct_node_llm_tool_loop,
)


@pytest.mark.asyncio
async def test_execute_direct_node_llm_tool_loop_returns_typed_execution_state():
    calls: dict[str, object] = {}
    tracer = MagicMock()
    llm = object()
    state = {"query": "kiem tra tool loop"}
    tools = [SimpleNamespace(name="tool_a"), SimpleNamespace(name="tool_b")]

    def prepare_tool_execution_fn(**kwargs):
        calls["prepare"] = kwargs
        return SimpleNamespace(
            force_tools=True,
            direct_answer_timeout_profile={"primary": 3},
            direct_answer_primary_timeout=3,
            direct_allowed_fallback_providers=["qwen"],
            llm_with_tools="llm-with-tools",
            llm_auto="llm-auto",
            forced_tool_choice={"type": "any"},
            native_direct_messages=True,
            messages=["system-message"],
            runtime_context_base={"request_id": "req-1"},
        )

    def execute_direct_tool_rounds(*args, **kwargs):
        calls["tool_round_args"] = args
        calls["tool_round_kwargs"] = kwargs
        return "direct-execution"

    async def run_with_host_timeout_fn(**kwargs):
        calls["host_timeout"] = kwargs
        return (
            SimpleNamespace(content="raw response"),
            ["system-message", "tool-message"],
            [{"name": "tool_a", "status": "ok"}],
        )

    async def finalize_llm_execution_fn(**kwargs):
        calls["finalize"] = kwargs
        return SimpleNamespace(response="Da xu ly xong.")

    async def push_event(_event):
        calls["event_pushed"] = True

    result = await execute_direct_node_llm_tool_loop(
        llm=llm,
        query="kiem tra tool loop",
        state=state,
        ctx={"request_id": "req-1"},
        bus_id="bus-1",
        domain_name_vi="Hang hai",
        role_name="direct_agent",
        tools=tools,
        force_tools=False,
        tools_context_override=None,
        visual_decision=SimpleNamespace(force_tool=False),
        history_limit=10,
        routing_intent="learning",
        response_language="vi",
        is_identity_turn=False,
        is_short_house_chatter=False,
        use_house_voice_direct=False,
        direct_provider_override=None,
        preferred_provider="qwen",
        explicit_user_provider=None,
        explicit_web_search_turn=False,
        push_event=push_event,
        needs_web_search=lambda _query: False,
        needs_datetime=lambda _query: False,
        resolve_direct_answer_timeout_profile=lambda **_kwargs: {"primary": 3},
        bind_direct_tools=lambda *_args, **_kwargs: (None, None, None),
        build_direct_system_messages=lambda *_args, **_kwargs: [],
        build_visual_tool_runtime_metadata=lambda *_args, **_kwargs: {},
        execute_direct_tool_rounds=execute_direct_tool_rounds,
        extract_direct_response=lambda *_args, **_kwargs: "",
        sanitize_structured_visual_answer_text=lambda text, *_args, **_kwargs: text,
        sanitize_wiii_house_text=lambda text, *_args, **_kwargs: text,
        build_direct_reasoning_summary=lambda *_args, **_kwargs: "",
        tracer=tracer,
        logger_obj=MagicMock(),
        direct_max_rounds=7,
        host_ui_total_timeout_seconds=45.0,
        prepare_tool_execution_fn=prepare_tool_execution_fn,
        run_with_host_timeout_fn=run_with_host_timeout_fn,
        finalize_llm_execution_fn=finalize_llm_execution_fn,
    )

    assert result.response == "Da xu ly xong."
    assert result.messages == ["system-message", "tool-message"]
    assert result.tool_call_events == [{"name": "tool_a", "status": "ok"}]
    assert result.force_tools is True

    assert calls["prepare"]["role_name"] == "direct_agent"
    assert calls["tool_round_args"][:5] == (
        "llm-with-tools",
        "llm-auto",
        ["system-message"],
        tools,
        push_event,
    )
    assert calls["tool_round_kwargs"]["max_rounds"] == 7
    assert calls["tool_round_kwargs"]["allowed_fallback_providers"] == ["qwen"]
    assert calls["tool_round_kwargs"]["native_tool_messages"] is True
    assert calls["host_timeout"]["direct_execution"] == "direct-execution"
    assert calls["host_timeout"]["timeout_seconds"] == 45.0
    assert calls["finalize"]["response_language"] == "vi"
    assert calls["finalize"]["explicit_web_search_turn"] is False
    tracer.end_step.assert_called_once_with(
        result="Phan hoi LLM: 14 chars",
        confidence=0.85,
        details={
            "response_type": "llm_generated",
            "tools_bound": 2,
            "force_tools": True,
        },
    )


@pytest.mark.asyncio
async def test_execute_direct_node_llm_tool_loop_preserves_partial_state_on_finalize_error():
    async def run_with_host_timeout_fn(**_kwargs):
        return (
            SimpleNamespace(content="salvage me"),
            ["message-before-cleanup"],
            [{"name": "tool_a"}],
        )

    async def finalize_llm_execution_fn(**_kwargs):
        raise RuntimeError("cleanup boom")

    with pytest.raises(RuntimeError) as exc_info:
        await execute_direct_node_llm_tool_loop(
            llm=object(),
            query="kiem tra salvage",
            state={},
            ctx={},
            bus_id=None,
            domain_name_vi="Hang hai",
            role_name="direct_agent",
            tools=[],
            force_tools=False,
            tools_context_override=None,
            visual_decision=SimpleNamespace(force_tool=False),
            history_limit=10,
            routing_intent="learning",
            response_language="vi",
            is_identity_turn=False,
            is_short_house_chatter=False,
            use_house_voice_direct=False,
            direct_provider_override=None,
            preferred_provider=None,
            explicit_user_provider=None,
            explicit_web_search_turn=False,
            push_event=lambda *_args, **_kwargs: None,
            needs_web_search=lambda _query: False,
            needs_datetime=lambda _query: False,
            resolve_direct_answer_timeout_profile=lambda **_kwargs: None,
            bind_direct_tools=lambda *_args, **_kwargs: (None, None, None),
            build_direct_system_messages=lambda *_args, **_kwargs: [],
            build_visual_tool_runtime_metadata=lambda *_args, **_kwargs: {},
            execute_direct_tool_rounds=lambda *_args, **_kwargs: "direct-execution",
            extract_direct_response=lambda *_args, **_kwargs: "",
            sanitize_structured_visual_answer_text=lambda text, *_args, **_kwargs: text,
            sanitize_wiii_house_text=lambda text, *_args, **_kwargs: text,
            build_direct_reasoning_summary=lambda *_args, **_kwargs: "",
            tracer=MagicMock(),
            logger_obj=MagicMock(),
            direct_max_rounds=1,
            host_ui_total_timeout_seconds=45.0,
            prepare_tool_execution_fn=lambda **_kwargs: SimpleNamespace(
                force_tools=False,
                direct_answer_timeout_profile=None,
                direct_answer_primary_timeout=None,
                direct_allowed_fallback_providers=None,
                llm_with_tools="llm-with-tools",
                llm_auto="llm-auto",
                forced_tool_choice=None,
                native_direct_messages=False,
                messages=["message-before-cleanup"],
                runtime_context_base=None,
            ),
            run_with_host_timeout_fn=run_with_host_timeout_fn,
            finalize_llm_execution_fn=finalize_llm_execution_fn,
        )

    exc = exc_info.value
    assert getattr(exc, "_direct_node_llm_response").content == "salvage me"
    assert getattr(exc, "_direct_node_messages") == ["message-before-cleanup"]
    assert getattr(exc, "_direct_node_tool_call_events") == [{"name": "tool_a"}]
