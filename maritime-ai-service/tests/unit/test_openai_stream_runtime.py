import asyncio
from types import SimpleNamespace

import pytest

from app.core.exceptions import ProviderStreamInterruptedError
from app.engine.multi_agent.openai_stream_runtime import (
    _ainvoke_openai_compatible_chat_impl,
    _stream_openai_compatible_answer_with_route_impl,
    _supports_native_answer_streaming_impl,
)


def test_supports_native_answer_streaming_now_includes_google():
    assert _supports_native_answer_streaming_impl("google") is True


@pytest.mark.asyncio
async def test_native_openai_compatible_ainvoke_sends_tools_and_choice(monkeypatch):
    from app.engine.native_chat_runtime import NativeChatModelHandle

    captured: dict = {}

    class _FakeChatCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model=kwargs["model"],
                usage={"total_tokens": 12},
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="tool_current_datetime",
                                        arguments="{}",
                                    ),
                                )
                            ],
                        ),
                    )
                ],
            )

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(
        "app.engine.multi_agent.openai_stream_runtime._create_openai_compatible_stream_client_impl",
        lambda _provider: _FakeClient(),
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.openai_stream_runtime._resolve_openai_stream_model_name_impl",
        lambda *_args: "deepseek-ai/deepseek-v4-flash",
    )

    handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
    ).bind_tools(
        [
            SimpleNamespace(
                name="tool_current_datetime",
                description="Get current date and time",
                parameters={"type": "object", "properties": {}},
            )
        ],
        tool_choice="tool_current_datetime",
    )

    response = await _ainvoke_openai_compatible_chat_impl(
        handle,
        [{"role": "user", "content": "May gio roi?"}],
    )

    assert captured["model"] == "deepseek-ai/deepseek-v4-flash"
    assert captured["messages"] == [{"role": "user", "content": "May gio roi?"}]
    assert captured["tools"][0]["function"]["name"] == "tool_current_datetime"
    assert captured["tool_choice"] == {
        "type": "function",
        "function": {"name": "tool_current_datetime"},
    }
    assert response.tool_calls == [
        {"id": "call_1", "name": "tool_current_datetime", "args": {}}
    ]


@pytest.mark.asyncio
async def test_google_direct_stream_emits_visible_reasoning_before_answer():
    events = []

    async def _push_event(event):
        events.append(event)

    class _FakeStream:
        def __aiter__(self):
            async def _gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="<thinking>Cham vao phan tu than cua minh.</thinking>Minh la Wiii.",
                            )
                        )
                    ]
                )
            return _gen()

    class _FakeChatCompletions:
        async def create(self, **_kwargs):
            return _FakeStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    route = SimpleNamespace(
        provider="google",
        llm=SimpleNamespace(
            _wiii_tier_key="deep",
            temperature=0.2,
        ),
    )

    response, streamed = await _stream_openai_compatible_answer_with_route_impl(
        route,
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        node="direct",
        thinking_stop_signal=None,
        supports_native_answer_streaming=lambda provider: provider == "google",
        create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
        resolve_openai_stream_model_name=lambda *_args: "gemini-3.1-pro-preview",
        langchain_message_to_openai_payload=lambda message: {"role": "user", "content": message.content},
        extract_openai_delta_text=lambda delta: ("", str(getattr(delta, "content", "") or "")),
    )

    assert streamed is True
    assert str(getattr(response, "content", "")) == "Minh la Wiii."
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert events[1]["content"] == "Cham vao phan tu than cua minh."
    assert events[3]["content"] == "Minh la Wiii."


@pytest.mark.asyncio
async def test_native_direct_stream_returns_tool_call_chunks_with_bound_tools():
    from app.engine.native_chat_runtime import NativeChatModelHandle

    captured: dict = {}
    events = []

    async def _push_event(event):
        events.append(event)

    class _FakeStream:
        def __aiter__(self):
            async def _gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call_1",
                                        function=SimpleNamespace(
                                            name="tool_current_datetime",
                                            arguments="",
                                        ),
                                    )
                                ]
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        function=SimpleNamespace(
                                            name="",
                                            arguments='{"timezone":"Asia/Saigon"}',
                                        ),
                                    )
                                ]
                            )
                        )
                    ]
                )

            return _gen()

    class _FakeChatCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    llm = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
    ).bind_tools(
        [
            SimpleNamespace(
                name="tool_current_datetime",
                description="Get current date and time",
                parameters={
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                },
            )
        ]
    )

    response, streamed = await _stream_openai_compatible_answer_with_route_impl(
        SimpleNamespace(provider="nvidia", llm=llm),
        messages=[{"role": "user", "content": "May gio roi?"}],
        push_event=_push_event,
        node="direct",
        thinking_stop_signal=None,
        supports_native_answer_streaming=lambda provider: provider == "nvidia",
        create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
        resolve_openai_stream_model_name=lambda *_args: "deepseek-ai/deepseek-v4-flash",
        langchain_message_to_openai_payload=lambda message: message,
        extract_openai_delta_text=lambda delta: ("", str(getattr(delta, "content", "") or "")),
    )

    assert streamed is False
    assert captured["tools"][0]["function"]["name"] == "tool_current_datetime"
    assert response.content == ""
    assert response.tool_calls == [
        {
            "id": "call_1",
            "name": "tool_current_datetime",
            "args": {"timezone": "Asia/Saigon"},
        }
    ]
    assert events == []


@pytest.mark.asyncio
async def test_native_direct_stream_buffers_raw_json_tool_call_text():
    events = []

    async def _push_event(event):
        events.append(event)

    class _FakeStream:
        def __aiter__(self):
            async def _gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content='{"name":"tool_knowledge_search",',
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content='"arguments":{"query":"gioi thieu hang hai"}}',
                            )
                        )
                    ]
                )

            return _gen()

    class _FakeChatCompletions:
        async def create(self, **_kwargs):
            return _FakeStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    route = SimpleNamespace(
        provider="nvidia",
        llm=SimpleNamespace(
            _wiii_tier_key="light",
            _wiii_model_name="qwen/qwen3-next-80b-a3b-thinking",
            _wiii_bound_tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "tool_knowledge_search",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        ),
    )

    response, streamed = await _stream_openai_compatible_answer_with_route_impl(
        route,
        messages=[{"role": "user", "content": "Hoc hang hai duoc khong?"}],
        push_event=_push_event,
        node="direct",
        thinking_stop_signal=None,
        supports_native_answer_streaming=lambda provider: provider == "nvidia",
        create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
        resolve_openai_stream_model_name=lambda *_args: "qwen/qwen3-next-80b-a3b-thinking",
        langchain_message_to_openai_payload=lambda message: message,
        extract_openai_delta_text=lambda delta: ("", str(getattr(delta, "content", "") or "")),
    )

    assert streamed is False
    assert response.content == ""
    assert response.tool_calls == [
        {
            "id": "raw_tool_call_0",
            "name": "tool_knowledge_search",
            "args": {"query": "gioi thieu hang hai"},
        }
    ]
    assert events == []


@pytest.mark.asyncio
async def test_native_direct_stream_timeout_marks_model_degraded():
    from app.engine.llm_model_health import is_model_degraded, reset_model_health_state

    reset_model_health_state()
    events = []

    async def _push_event(event):
        events.append(event)

    class _SlowStream:
        def __aiter__(self):
            async def _gen():
                import asyncio

                await asyncio.sleep(0.05)
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="Too late"),
                        )
                    ]
                )

            return _gen()

    class _FakeChatCompletions:
        async def create(self, **_kwargs):
            return _SlowStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    route = SimpleNamespace(
        provider="nvidia",
        llm=SimpleNamespace(
            _wiii_tier_key="light",
            _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        ),
    )

    try:
        response, streamed = await _stream_openai_compatible_answer_with_route_impl(
            route,
            messages=[{"role": "user", "content": "Hi Wiii"}],
            push_event=_push_event,
            node="direct",
            thinking_stop_signal=None,
            primary_timeout=0.001,
            supports_native_answer_streaming=lambda provider: provider == "nvidia",
            create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
            resolve_openai_stream_model_name=lambda *_args: "deepseek-ai/deepseek-v4-flash",
            langchain_message_to_openai_payload=lambda message: message,
            extract_openai_delta_text=lambda delta: ("", str(getattr(delta, "content", "") or "")),
        )

        assert response is None
        assert streamed is False
        assert is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-flash") is True
        assert events == []
    finally:
        reset_model_health_state()


@pytest.mark.asyncio
async def test_native_direct_stream_closes_reasoning_when_no_answer_emitted():
    events = []
    thinking_stop_signal = asyncio.Event()

    async def _push_event(event):
        events.append(event)

    class _ReasoningOnlyStream:
        def __aiter__(self):
            async def _gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="Still thinking"),
                        )
                    ]
                )

            return _gen()

    class _FakeChatCompletions:
        async def create(self, **_kwargs):
            return _ReasoningOnlyStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    response, streamed = await _stream_openai_compatible_answer_with_route_impl(
        SimpleNamespace(
            provider="nvidia",
            llm=SimpleNamespace(_wiii_tier_key="light", _wiii_model_name="deepseek-ai/deepseek-v4-flash"),
        ),
        messages=[{"role": "user", "content": "Hi Wiii"}],
        push_event=_push_event,
        node="direct",
        thinking_stop_signal=thinking_stop_signal,
        supports_native_answer_streaming=lambda provider: provider == "nvidia",
        create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
        resolve_openai_stream_model_name=lambda *_args: "deepseek-ai/deepseek-v4-flash",
        langchain_message_to_openai_payload=lambda message: message,
        extract_openai_delta_text=lambda delta: (str(getattr(delta, "reasoning_content", "") or ""), ""),
    )

    assert response is None
    assert streamed is False
    assert thinking_stop_signal.is_set() is True
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
    ]


@pytest.mark.asyncio
async def test_native_direct_stream_partial_exception_does_not_mark_model_healthy():
    from app.engine.llm_model_health import is_model_degraded, reset_model_health_state

    reset_model_health_state()
    events = []

    async def _push_event(event):
        events.append(event)

    class _PartialThenFailStream:
        def __aiter__(self):
            async def _gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="Xin chao"))
                    ]
                )
                raise RuntimeError(
                    "peer closed connection without sending complete message body "
                    "(incomplete chunked read)"
                )

            return _gen()

    class _FakeChatCompletions:
        async def create(self, **_kwargs):
            return _PartialThenFailStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    try:
        with pytest.raises(ProviderStreamInterruptedError) as exc_info:
            await _stream_openai_compatible_answer_with_route_impl(
                SimpleNamespace(
                    provider="nvidia",
                    llm=SimpleNamespace(_wiii_tier_key="light", _wiii_model_name="deepseek-ai/deepseek-v4-flash"),
                ),
                messages=[{"role": "user", "content": "Hi Wiii"}],
                push_event=_push_event,
                node="direct",
                thinking_stop_signal=None,
                supports_native_answer_streaming=lambda provider: provider == "nvidia",
                create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
                resolve_openai_stream_model_name=lambda *_args: "deepseek-ai/deepseek-v4-flash",
                langchain_message_to_openai_payload=lambda message: message,
                extract_openai_delta_text=lambda delta: ("", str(getattr(delta, "content", "") or "")),
            )

        assert exc_info.value.provider == "nvidia"
        assert exc_info.value.model == "deepseek-ai/deepseek-v4-flash"
        assert exc_info.value.partial_chars == len("Xin chao")
        assert exc_info.value.reason_code == "provider_stream_interrupted"
        assert events == [{"type": "answer_delta", "content": "Xin chao", "node": "direct"}]
        assert is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-flash") is True
    finally:
        reset_model_health_state()


@pytest.mark.asyncio
async def test_native_direct_stream_partial_internal_exception_is_not_reclassified():
    events = []

    async def _push_event(event):
        events.append(event)

    class _PartialThenInternalFailStream:
        def __aiter__(self):
            async def _gen():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="Xin chao"))
                    ]
                )
                raise ValueError("local stream parser bug")

            return _gen()

    class _FakeChatCompletions:
        async def create(self, **_kwargs):
            return _PartialThenInternalFailStream()

    class _FakeChat:
        completions = _FakeChatCompletions()

    class _FakeClient:
        chat = _FakeChat()

    with pytest.raises(ValueError, match="local stream parser bug"):
        await _stream_openai_compatible_answer_with_route_impl(
            SimpleNamespace(
                provider="nvidia",
                llm=SimpleNamespace(_wiii_tier_key="light", _wiii_model_name="deepseek-ai/deepseek-v4-flash"),
            ),
            messages=[{"role": "user", "content": "Hi Wiii"}],
            push_event=_push_event,
            node="direct",
            thinking_stop_signal=None,
            supports_native_answer_streaming=lambda provider: provider == "nvidia",
            create_openai_compatible_stream_client=lambda _provider: _FakeClient(),
            resolve_openai_stream_model_name=lambda *_args: "deepseek-ai/deepseek-v4-flash",
            langchain_message_to_openai_payload=lambda message: message,
            extract_openai_delta_text=lambda delta: ("", str(getattr(delta, "content", "") or "")),
        )

    assert events == [{"type": "answer_delta", "content": "Xin chao", "node": "direct"}]
