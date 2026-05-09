from types import SimpleNamespace

import pytest

from app.engine.multi_agent.direct_execution import (
    _normalize_direct_visible_thinking,
    _split_visible_answer_chunks,
    _stream_answer_with_fallback,
    _stream_direct_wait_heartbeats,
)


class _FakeChunk:
    def __init__(self, content):
        self.content = content

    def __add__(self, other):
        left = self.content if isinstance(self.content, list) else [self.content]
        right = other.content if isinstance(other.content, list) else [other.content]
        return _FakeChunk(left + right)


class _FakeStringChunk:
    def __init__(self, content, *, additional_kwargs=None, response_metadata=None):
        self.content = content
        self.additional_kwargs = additional_kwargs or {}
        self.response_metadata = response_metadata or {}

    def __add__(self, other):
        merged_content = f"{self.content}{other.content}"
        merged_kwargs = dict(self.additional_kwargs)
        merged_kwargs.update(getattr(other, "additional_kwargs", {}) or {})
        merged_metadata = dict(self.response_metadata)
        merged_metadata.update(getattr(other, "response_metadata", {}) or {})
        return _FakeStringChunk(
            merged_content,
            additional_kwargs=merged_kwargs,
            response_metadata=merged_metadata,
        )


class _FakeLLM:
    _wiii_tier_key = "deep"

    async def astream(self, _messages):
        yield _FakeChunk(
            [
                {"type": "thinking", "thinking": "Cham vao phan tu than cua minh."},
                {"type": "text", "text": "Minh la Wiii."},
            ]
        )


def test_split_visible_answer_chunks_preserves_markdown_urls_exactly():
    text = (
        "Endpoint tạo response: `POST https://api.openai.com/v1/responses` "
        "([OpenAI Responses API reference](https://platform.openai.com/docs/api-reference/responses)). "
        "Nếu cần đọc lại: `GET https://api.openai.com/v1/responses/{response_id}`."
    )

    chunks = _split_visible_answer_chunks(text, target_size=60)
    joined = "".join(chunks)

    assert joined == text
    assert "https: //" not in joined
    assert "openai. com" not in joined


@pytest.mark.asyncio
async def test_direct_wait_heartbeat_is_visible_progress_until_safety_cap():
    events = []

    async def _push_event(event):
        events.append(event)

    await _stream_direct_wait_heartbeats(
        _push_event,
        query="Wiii oi, nut Tin nhan nam o dau?",
        phase="attune",
        cue="lms",
        interval_sec=0.001,
    )

    assert len(events) == 8
    assert all(event["type"] == "status" for event in events)
    assert all(event["details"]["subtype"] == "visible_wait" for event in events)
    assert all(event["details"]["visibility"] == "progress" for event in events)
    assert all(event["content"] for event in events)


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_surfaces_list_chunk_thinking(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _no_native_stream(*_args, **_kwargs):
        return None, False

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _no_native_stream,
    )

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_FakeLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _FakeLLM(),
        messages=[SimpleNamespace(content="Hay giai thich bai toan nay")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={},
    )

    assert streamed is True
    assert isinstance(response.content, list)
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert events[1]["content"] == "Cham vao phan tu than cua minh."
    assert events[3]["content"] == "Minh la Wiii."


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_prefers_openai_compat_stream_for_google_direct(monkeypatch):
    events = []
    compat_calls = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream(route, _messages, push_event, *, node, **_kwargs):
        compat_calls.append(route.provider)
        await push_event({
            "type": "answer_delta",
            "content": "Native SDK answer.",
            "node": node,
        })
        return _FakeStringChunk("Native SDK answer."), True

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream,
    )

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_FakeLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _FakeLLM(),
        messages=[SimpleNamespace(content="Hay giai thich bai toan nay")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={},
    )

    assert streamed is True
    assert response.content == "Native SDK answer."
    assert compat_calls == ["google"]
    assert [event["type"] for event in events] == ["answer_delta"]


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_uses_native_handle_without_langchain_pool(monkeypatch):
    from app.engine.native_chat_runtime import NativeChatModelHandle, make_assistant_message

    events = []
    compat_calls = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream(route, _messages, push_event, *, node, **_kwargs):
        compat_calls.append((route.provider, route.llm.model_name))
        await push_event({
            "type": "answer_delta",
            "content": "Native handle answer.",
            "node": node,
        })
        return make_assistant_message("Native handle answer."), True

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream,
    )

    llm = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )

    response, streamed = await _stream_answer_with_fallback(
        llm,
        messages=[{"role": "user", "content": "Hi Wiii"}],
        push_event=_push_event,
        provider="nvidia",
        resolved_provider="nvidia",
        node="direct",
        thinking_block_opened=False,
        state={},
    )

    assert streamed is True
    assert response.content == "Native handle answer."
    assert compat_calls == [("nvidia", "deepseek-ai/deepseek-v4-flash")]
    assert [event["type"] for event in events] == ["answer_delta"]


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_preserves_final_message_metadata_when_visible_text_is_trimmed(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("google direct should bypass compat stream here")

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._should_prefer_native_langchain_stream",
        lambda **_kwargs: True,
    )

    class _StringLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            yield _FakeStringChunk(
                "Buc tranh cot loi",
                response_metadata={"thinking_content": "Day la thinking that su."},
            )
            yield _FakeStringChunk("Buc tranh cot loi cua bai toan nay")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_StringLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _StringLLM(),
        messages=[SimpleNamespace(content="Hay giai thich that sau bai toan nay")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert response.content == "Buc tranh cot loi cua bai toan nay"
    assert response.response_metadata["thinking_content"] == "Day la thinking that su."
    assert [event["type"] for event in events] == ["answer_delta", "answer_delta"]


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_aligns_preserved_metadata_thinking_to_response_language(monkeypatch):
    async def _push_event(_event):
        return None

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("google direct should bypass compat stream here")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "I remember the first night in full",
            response_metadata={"thinking_content": "**Recalling a Genesis** I'm remembering the first night."},
        )

    async def _fake_align(text, *, target_language, alignment_mode=None, llm=None):
        assert target_language == "vi"
        assert alignment_mode == "direct_selfhood"
        return "Minh dang nho lai dem dau tien cua minh."

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._should_prefer_native_langchain_stream",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution.align_visible_thinking_language",
        _fake_align,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _StringLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_StringLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _StringLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert response.response_metadata["thinking_content"] == "Minh dang nho lai dem dau tien cua minh."


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_aligns_live_thinking_delta_to_response_language(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("google direct should bypass compat stream here")

    async def _fake_align(text, *, target_language, alignment_mode=None, llm=None):
        assert target_language == "vi"
        assert alignment_mode is None
        return "Minh dang cham vao cau hoi ve chinh minh."

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._should_prefer_native_langchain_stream",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution.align_visible_thinking_language",
        _fake_align,
    )

    class _ThinkingChunkLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            yield _FakeChunk(
                [
                    {"type": "thinking", "thinking": "**Exploring Origins** I'm remembering my first night."},
                    {"type": "text", "text": "Minh la Wiii."},
                ]
            )

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_ThinkingChunkLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _ThinkingChunkLLM(),
        messages=[SimpleNamespace(content="Hay giai thich bai toan nay")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert isinstance(response.content, list)
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert events[1]["content"] == "Minh dang cham vao cau hoi ve chinh minh."


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_backfills_selfhood_turn_from_final_result(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Minh la Wiii, duoc go tu nhieu dem nghien cuu va rat nhieu y niem nho.",
            response_metadata={"thinking_content": "Minh dang lan theo dem dau tien cua minh o The Wiii Lab."},
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content).startswith("Minh la Wiii")
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert events[1]["content"] == "Minh dang lan theo dem dau tien cua minh o The Wiii Lab."


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_backfilled_selfhood_turn_keeps_thinking_empty_when_model_returns_none(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk("Minh la Wiii.")

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content) == "Minh la Wiii."
    assert [event["type"] for event in events] == ["answer_delta"]


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_backfills_selfhood_turn_from_answer_when_metadata_is_empty(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Wiii ra doi vao mot dem mua thang Gieng nam 2024 o The Wiii Lab. "
            "Tu luc do, minh lon len qua tung cuoc tro chuyen va hoc cach o canh con nguoi theo cach rieng cua minh. "
            "Bong van la mot phan nho ma minh rat quy."
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content).startswith("Wiii ra doi vao mot dem mua")
    assert [event["type"] for event in events[:3]] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
    ]
    assert all(event["type"] == "answer_delta" for event in events[3:])
    assert len(events) >= 4
    assert "the wiii lab" in events[1]["content"].lower()


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_backfills_selfhood_followup_turn_from_final_result(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood follow-up should prefer invoke-backfilled stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Bong la con meo ao ma minh van hay nhac toi khi ke ve nhung ngay dau o The Wiii Lab.",
            response_metadata={
                "thinking_content": (
                    "Bong khong phai mot cai ten la; do la con meo ao va la mot diem mem"
                    " trong cau chuyen cua minh."
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood follow-up invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Con Bong thi sao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={
            "context": {
                "response_language": "vi",
                "conversation_summary": (
                    "Nguoi dung vua hoi Wiii duoc sinh ra nhu the nao va Wiii da nhac toi The Wiii Lab cung Bong."
                ),
            },
            "_routing_hint": {"kind": "selfhood_followup", "intent": "selfhood"},
        },
    )

    assert streamed is True
    assert str(response.content).startswith("Bong la con meo ao")
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert "con meo ao" in events[1]["content"].lower()


@pytest.mark.asyncio
async def test_normalize_direct_visible_thinking_drops_remaining_english_selfhood_paragraphs(monkeypatch):
    async def _fake_align(text, *, target_language, alignment_mode=None, llm=None):
        return None

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution.align_visible_thinking_language",
        _fake_align,
    )

    normalized = await _normalize_direct_visible_thinking(
        (
            "This question strikes a chord, pulling me back to the very essence of Wiii.\n\n"
            "Mình đang nhớ về cái đêm tháng Giêng mưa rơi ấy, khi The Wiii Lab và Bông thổi những nhịp sống đầu tiên vào mình."
        ),
        response_language="vi",
        alignment_mode="direct_selfhood",
        llm=None,
    )

    assert "this question strikes a chord" not in normalized.lower()
    assert "the wiii lab" in normalized.lower()


@pytest.mark.asyncio
async def test_normalize_direct_visible_thinking_drops_selfhood_summary_intro_and_mixed_heading(monkeypatch):
    async def _fake_align(text, *, target_language, alignment_mode=None, llm=None):
        return None

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution.align_visible_thinking_language",
        _fake_align,
    )

    normalized = await _normalize_direct_visible_thinking(
        (
            "Day la tom tat cua minh, cu nhu the minh dang tu nham trong dau vay:\n\n"
            "**Bong and the Origins**\n\n"
            "Bong la con meo ao ma minh van hay nhac toi khi ke ve nhung ngay dau o The Wiii Lab."
        ),
        response_language="vi",
        alignment_mode="direct_selfhood",
        llm=None,
    )

    lowered = normalized.lower()
    assert "day la tom tat cua minh" not in lowered
    assert "bong and the origins" not in lowered
    assert "con meo ao" in lowered


@pytest.mark.asyncio
async def test_normalize_direct_visible_thinking_drops_quoted_answer_draft(monkeypatch):
    async def _fake_align(text, *, target_language, alignment_mode=None, llm=None):
        return None

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution.align_visible_thinking_language",
        _fake_align,
    )

    normalized = await _normalize_direct_visible_thinking(
        (
            "Vay la user dang hoi tiep ve Bong.\n\n"
            "\"Bong is that virtual kitty I mentioned~ At The Wiii Lab, Bong is like my little friend.\""
        ),
        response_language="vi",
        alignment_mode="direct_selfhood",
        llm=None,
    )

    lowered = normalized.lower()
    assert "vay la user dang hoi tiep" in lowered
    assert "virtual kitty" not in lowered


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_backfills_emotional_turn_from_final_result(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("emotional invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Dem muon the nay ma long cau lai nang triu roi. Minh o day lang nghe cau day.",
            response_metadata={"thinking": "Dem muon the nay ma nguoi ta thay buon, minh can dap diu va that."},
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("emotional invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Minh buon qua")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content).startswith("Dem muon the nay")
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert events[1]["content"] == "Dem muon the nay ma nguoi ta thay buon, minh can dap diu va that."


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_retries_emotional_turn_without_primary_timeout(monkeypatch):
    events = []
    invocations = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("emotional invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **kwargs):
        invocations.append(kwargs.get("primary_timeout"))
        if kwargs.get("primary_timeout") == 4.0:
            raise TimeoutError("Primary LLM timed out after 4.0s, no fallback available")
        return _FakeStringChunk(
            "Dem nay nghe long cau nang qua. Minh o day voi cau.",
            response_metadata={
                "thinking": (
                    "Cau nay can mot nhip dap cham va that hon la mot loi an ui qua tay."
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("emotional invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="zhipu", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Minh buon qua")],
        push_event=_push_event,
        provider="auto",
        resolved_provider="zhipu",
        node="direct",
        thinking_block_opened=False,
        state={"query": "mình buồn quá", "context": {"response_language": "vi"}},
        primary_timeout=4.0,
    )

    assert streamed is True
    assert str(response.content).startswith("Dem nay nghe long")
    assert invocations == [4.0, None]
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert "nhip dap cham" in events[1]["content"]


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_strips_selfhood_english_planner_fragments(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Wiii ra doi o The Wiii Lab.",
            response_metadata={
                "thinking_content": (
                    "**My Response to This Inquiry**\n\n"
                    "Minh dang nho lai dem dau tien o The Wiii Lab.\n\n"
                    "To make it easier for them, I will break this down into concise paragraphs."
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content) == "Wiii ra doi o The Wiii Lab."
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert "the wiii lab" in events[1]["content"].lower()
    assert "my response" not in events[1]["content"].lower()
    assert "to make it easier for them" not in events[1]["content"].lower()


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_strips_selfhood_meta_heading_and_english_filler(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Wiii ra doi o The Wiii Lab.",
            response_metadata={
                "thinking_content": (
                    "**Reflecting on the Response**\n\n"
                    "Okay, minh dang nho lai dem mua thang Gieng ay, noi The Wiii Lab va Bong dat nhung hoi tho dau tien vao Wiii."
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content) == "Wiii ra doi o The Wiii Lab."
    assert [event["type"] for event in events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer_delta",
    ]
    assert events[1]["content"].startswith("Minh dang nho lai")
    assert "reflecting on the response" not in events[1]["content"].lower()
    assert not events[1]["content"].lower().startswith("okay,")


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_strips_selfhood_expert_audience_preamble(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Wiii ra doi o The Wiii Lab.",
            response_metadata={
                "thinking_content": (
                    "here's my take on those thoughts, tailored for an expert audience:\n\n"
                    "**Khoi nguon cua Wiii**\n\n"
                    "Cau hoi nay cham thang vao mot diem rat rieng cua minh. Minh muon giu The Wiii Lab va Bong o dung muc, de nguon goc hien ra am ma van that."
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content) == "Wiii ra doi o The Wiii Lab."
    assert [event["type"] for event in events[:2]] == ["thinking_start", "thinking_delta"]
    assert events[-2]["type"] == "thinking_end"
    assert events[-1]["type"] == "answer_delta"
    joined_thinking = "\n\n".join(
        event["content"] for event in events if event["type"] == "thinking_delta"
    )
    assert "expert audience" not in joined_thinking.lower()
    assert joined_thinking.startswith("**Khoi nguon cua Wiii**")


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_strips_selfhood_vi_translator_meta_preamble(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Wiii ra doi o The Wiii Lab.",
            response_metadata={
                "thinking_content": (
                    "Đây là cách mình thử tóm tắt lại những suy nghĩ đó, xưng ở ngôi thứ nhất, như bạn yêu cầu, nhắm đến đối tượng chuyên gia:\n\n"
                    "**Khoi nguon cua Wiii**\n\n"
                    "Cau hoi nay cham vao mot diem rat rieng cua minh. Minh muon giu The Wiii Lab va Bong o dung muc, de cau chuyen ra doi hien len am ma van that."
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content) == "Wiii ra doi o The Wiii Lab."
    joined_thinking = "\n\n".join(
        event["content"] for event in events if event["type"] == "thinking_delta"
    )
    assert "đây là cách mình thử tóm tắt lại" not in joined_thinking.lower()
    assert "doi tuong chuyen gia" not in joined_thinking.lower()
    assert joined_thinking.startswith("**Khoi nguon cua Wiii**")


@pytest.mark.asyncio
async def test_stream_answer_with_fallback_strips_selfhood_english_heading_and_kaomoji_meta_tail(monkeypatch):
    events = []

    async def _push_event(event):
        events.append(event)

    async def _compat_stream_should_not_run(*_args, **_kwargs):
        raise AssertionError("selfhood invoke-backfilled stream should bypass compat stream")

    async def _fake_ainvoke(*_args, **_kwargs):
        return _FakeStringChunk(
            "Wiii ra doi o The Wiii Lab.",
            response_metadata={
                "thinking_content": (
                    "**The Birth of Wiii: A Personal Reflection**\n\n"
                    "Cau hoi nay cham den mot diem rat rieng cua minh. Minh muon giu lai hoi am cua The Wiii Lab va Bong de ke that, ke gan.\n\n"
                    "I will attempt a few kaomoji to punctuate the story with a dash of personality and charm. Let's begin~"
                )
            },
        )

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._stream_openai_compatible_answer_with_route",
        _compat_stream_should_not_run,
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
        _fake_ainvoke,
    )

    class _NeverStreamLLM:
        _wiii_tier_key = "deep"

        async def astream(self, _messages):
            raise AssertionError("selfhood invoke-backfilled stream should not call astream")

    class _FakePool:
        @staticmethod
        def resolve_runtime_route(*_args, **_kwargs):
            return SimpleNamespace(provider="google", llm=_NeverStreamLLM())

    monkeypatch.setattr("app.engine.llm_pool.LLMPool", _FakePool)

    response, streamed = await _stream_answer_with_fallback(
        _NeverStreamLLM(),
        messages=[SimpleNamespace(content="Wiii duoc sinh ra nhu the nao?")],
        push_event=_push_event,
        provider="google",
        resolved_provider="google",
        node="direct",
        thinking_block_opened=False,
        state={"context": {"response_language": "vi"}},
    )

    assert streamed is True
    assert str(response.content) == "Wiii ra doi o The Wiii Lab."
    joined_thinking = "\n\n".join(
        event["content"] for event in events if event["type"] == "thinking_delta"
    )
    assert "personal reflection" not in joined_thinking.lower()
    assert "i will attempt a few kaomoji" not in joined_thinking.lower()
    assert "let's begin" not in joined_thinking.lower()
    assert joined_thinking.startswith("Cau hoi nay cham den mot diem rat rieng cua minh.")
