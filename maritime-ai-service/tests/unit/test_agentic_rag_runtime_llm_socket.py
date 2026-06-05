from unittest.mock import AsyncMock, patch

import pytest

from app.engine.agentic_rag.runtime_llm_socket import (
    agentic_rag_runtime_target,
    ainvoke_agentic_rag_llm,
    make_agentic_rag_messages,
    resolve_agentic_rag_llm,
)
from app.engine.llm_factory import ThinkingTier
from app.engine.native_chat_runtime import NativeChatModelHandle


def test_make_agentic_rag_messages_uses_native_message_surface():
    messages = make_agentic_rag_messages(
        system="system prompt",
        user="user prompt",
        assistant_prefill="<thinking>",
    )

    assert [message.type for message in messages] == ["system", "human", "ai"]
    assert [message.content for message in messages] == [
        "system prompt",
        "user prompt",
        "<thinking>",
    ]


def test_resolve_agentic_rag_llm_prefers_native_handle_when_client_exists():
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            return_value=native_handle,
        ),
        patch(
            "app.engine.multi_agent.openai_stream_runtime."
            "_create_openai_compatible_stream_client_impl",
            return_value=object(),
        ),
        patch("app.engine.agentic_rag.runtime_llm_socket.get_llm_for_provider") as fallback,
    ):
        llm = resolve_agentic_rag_llm(
            tier=ThinkingTier.LIGHT,
            component="RuntimeSocketTest",
        )

    assert llm is native_handle
    fallback.assert_not_called()


def test_resolve_agentic_rag_llm_forwards_request_scoped_model_to_native_registry():
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="nvidia/nemotron-3-ultra-550b-a55b",
        _wiii_tier_key="moderate",
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            return_value=native_handle,
        ) as get_native_llm,
        patch(
            "app.engine.multi_agent.openai_stream_runtime."
            "_create_openai_compatible_stream_client_impl",
            return_value=object(),
        ),
        patch("app.engine.agentic_rag.runtime_llm_socket.get_llm_for_provider") as fallback,
        agentic_rag_runtime_target(
            provider="nvidia",
            model="nvidia/nemotron-3-ultra-550b-a55b",
        ),
    ):
        llm = resolve_agentic_rag_llm(
            tier=ThinkingTier.MODERATE,
            component="RuntimeSocketTest",
        )

    assert llm is native_handle
    assert get_native_llm.call_args.kwargs["provider_override"] == "nvidia"
    assert get_native_llm.call_args.kwargs["requested_model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    fallback.assert_not_called()


def test_resolve_agentic_rag_llm_uses_request_scoped_custom_model_when_native_missing():
    custom_llm = object()

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            return_value=NativeChatModelHandle(
                _wiii_provider_name="nvidia",
                _wiii_model_name="nvidia/nemotron-3-ultra-550b-a55b",
                _wiii_tier_key="moderate",
            ),
        ),
        patch(
            "app.engine.multi_agent.openai_stream_runtime."
            "_create_openai_compatible_stream_client_impl",
            return_value=None,
        ),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=custom_llm,
        ) as get_llm,
        patch("app.engine.agentic_rag.runtime_llm_socket.get_llm_for_provider") as fallback,
        agentic_rag_runtime_target(
            provider="nvidia",
            model="nvidia/nemotron-3-ultra-550b-a55b",
        ),
    ):
        llm = resolve_agentic_rag_llm(
            tier=ThinkingTier.MODERATE,
            component="RuntimeSocketTest",
        )

    assert llm is custom_llm
    assert get_llm.call_args.args[0] == "rag_agent"
    assert get_llm.call_args.kwargs["provider_override"] == "nvidia"
    assert get_llm.call_args.kwargs["requested_model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert get_llm.call_args.kwargs["strict_provider_pin"] is True
    fallback.assert_not_called()


def test_resolve_agentic_rag_llm_falls_back_when_native_client_missing():
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )
    fallback_llm = object()

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            return_value=native_handle,
        ),
        patch(
            "app.engine.multi_agent.openai_stream_runtime."
            "_create_openai_compatible_stream_client_impl",
            return_value=None,
        ),
        patch(
            "app.engine.agentic_rag.runtime_llm_socket.get_llm_for_provider",
            return_value=fallback_llm,
        ),
    ):
        llm = resolve_agentic_rag_llm(
            tier=ThinkingTier.LIGHT,
            component="RuntimeSocketTest",
        )

    assert llm is fallback_llm


@pytest.mark.asyncio
async def test_ainvoke_agentic_rag_llm_pins_native_provider_to_failover_socket():
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )

    with patch(
        "app.engine.agentic_rag.runtime_llm_socket.ainvoke_with_failover",
        new=AsyncMock(return_value="ok"),
    ) as invoke:
        result = await ainvoke_agentic_rag_llm(
            llm=native_handle,
            messages=make_agentic_rag_messages(user="hello"),
            tier=ThinkingTier.LIGHT,
            component="RuntimeSocketTest",
        )

    assert result == "ok"
    assert invoke.await_args.kwargs["provider"] == "nvidia"
    assert invoke.await_args.kwargs["prefer_selectable_fallback"] is False
