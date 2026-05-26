from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.engine.llm_providers.wiii_chat_model import (
    WiiiChatModel,
    _StructuredOutputWrapper,
)


def _build_model() -> WiiiChatModel:
    return WiiiChatModel(
        model="test-model",
        api_key="test-key",
        base_url="https://example.test/v1",
    )


def test_build_api_kwargs_treats_plain_string_as_single_user_message():
    model = _build_model()

    kwargs = model._build_api_kwargs(
        "Noi chinh xac: BACKEND_OK",
        {},
        stream=False,
    )

    assert kwargs["messages"] == [
        {"role": "user", "content": "Noi chinh xac: BACKEND_OK"}
    ]


def test_build_api_kwargs_preserves_message_dict_list():
    model = _build_model()
    messages = [
        {"role": "system", "content": "You are Wiii."},
        {"role": "user", "content": "Hi"},
    ]

    kwargs = model._build_api_kwargs(messages, {}, stream=False)

    assert kwargs["messages"] == messages


class ProbeResult(BaseModel):
    status: str
    detail: str


class RecordingLlm:
    def __init__(self) -> None:
        self.messages: list[Any] | None = None
        self.kwargs: dict[str, Any] | None = None

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> SimpleNamespace:
        self.messages = messages
        self.kwargs = kwargs
        return SimpleNamespace(content='{"status":"ok","detail":"probe"}')


@pytest.mark.asyncio
async def test_structured_output_wrapper_treats_plain_string_as_user_message():
    llm = RecordingLlm()
    wrapper = _StructuredOutputWrapper(llm=llm, output_schema=ProbeResult)

    result = await wrapper.ainvoke("Tra ve status ok.", temperature=0)

    assert result.model_dump() == {"status": "ok", "detail": "probe"}
    assert llm.messages is not None
    assert llm.messages[0]["role"] == "system"
    assert llm.messages[1] == {"role": "user", "content": "Tra ve status ok."}
    assert llm.kwargs == {"temperature": 0}
