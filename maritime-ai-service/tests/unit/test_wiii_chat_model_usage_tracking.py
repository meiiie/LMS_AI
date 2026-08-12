"""Issue #882: native usage recording feeds the per-request TokenTracker.

The LangChain callback path (``TokenTrackingCallback.on_llm_end``) stopped
firing when ``BaseChatModel`` was removed (Phase 9a of epic #207), which left
``llm_usage_log`` silently empty. ``WiiiChatModel`` now records usage from the
native SDK response directly.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from app.core.token_tracker import start_tracking
from app.engine.llm_providers.wiii_chat_model import WiiiChatModel


def _build_model() -> WiiiChatModel:
    model = WiiiChatModel(
        model="test-model",
        api_key="test-key",
        base_url="https://example.test/v1",
    )
    # The LLM pool tags instances this way (llm_pool_support.py).
    setattr(model, "_wiii_provider_name", "google")
    setattr(model, "_wiii_tier_key", "google:moderate")
    return model


def _response(prompt_tokens: int = 11, completion_tokens: int = 7) -> Any:
    message = SimpleNamespace(content="hi", tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


def _stream_chunk(content: str = "", usage: Any = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=None)
    choices = [SimpleNamespace(delta=delta, finish_reason=None)] if content else []
    return SimpleNamespace(choices=choices, usage=usage)


class _FakeStream:
    def __init__(self, chunks: list) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._chunks)
        except StopIteration as exc:  # pragma: no cover - protocol shim
            raise StopAsyncIteration from exc


def _client_returning(value: Any) -> Any:
    client = SimpleNamespace()
    client.chat = SimpleNamespace()
    client.chat.completions = SimpleNamespace()
    client.chat.completions.create = AsyncMock(return_value=value)
    return client


async def test_ainvoke_records_usage_on_tracker():
    model = _build_model()
    tracker = start_tracking("req-1")

    with patch.object(WiiiChatModel, "_get_client", return_value=_client_returning(_response())):
        result = await model.ainvoke([{"role": "user", "content": "x"}])

    assert result.content == "hi"
    assert tracker.total_calls == 1
    assert tracker.total_input_tokens == 11
    assert tracker.total_output_tokens == 7
    call = tracker.calls[0]
    assert call.model == "test-model"
    assert call.provider == "google"
    assert call.component == "WiiiChatModel.ainvoke"


async def test_ainvoke_without_tracker_is_noop():
    model = _build_model()
    # No start_tracking() in this context: recording must silently no-op.
    with patch.object(WiiiChatModel, "_get_client", return_value=_client_returning(_response())):
        result = await model.ainvoke([{"role": "user", "content": "x"}])
    assert result.content == "hi"


async def test_astream_records_final_chunk_usage():
    model = _build_model()
    tracker = start_tracking("req-2")
    chunks = [
        _stream_chunk("Hel"),
        _stream_chunk("lo"),
        _stream_chunk(  # final usage-bearing chunk, no choices (OpenAI shape)
            "",
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
        ),
    ]

    with patch.object(WiiiChatModel, "_get_client", return_value=_client_returning(_FakeStream(chunks))):
        collected = [sc.content async for sc in model.astream([{"role": "user", "content": "x"}])]

    assert "".join(collected) == "Hello"
    assert tracker.total_calls == 1
    assert tracker.total_input_tokens == 5
    assert tracker.total_output_tokens == 3
    assert tracker.calls[0].component == "WiiiChatModel.astream"


async def test_astream_without_usage_records_nothing():
    model = _build_model()
    tracker = start_tracking("req-3")
    chunks = [_stream_chunk("Hi")]

    with patch.object(WiiiChatModel, "_get_client", return_value=_client_returning(_FakeStream(chunks))):
        _ = [sc async for sc in model.astream([{"role": "user", "content": "x"}])]

    assert tracker.total_calls == 0
