from __future__ import annotations

import json
from types import SimpleNamespace

from app.engine.native_chat_runtime import (
    NativeAssistantMessage,
    NativeChatModelHandle,
    flatten_message_content,
    make_assistant_message,
    make_system_message,
    make_tool_message,
    make_user_message,
    message_to_openai_payload,
    normalize_tool_choice,
    openai_response_to_assistant_message,
    tool_to_openai_schema,
)


def test_flatten_message_content_keeps_text_blocks_in_order():
    assert flatten_message_content([
        {"text": "Xin chao"},
        {"content": "Wiii"},
        {"value": "native"},
        {"image_url": "ignored"},
    ]) == "Xin chao\nWiii\nnative"


def test_message_to_openai_payload_accepts_langchain_like_human_message():
    message = SimpleNamespace(
        type="human",
        content=[
            {"text": "Xin chao"},
            {"content": "Wiii"},
        ],
    )

    assert message_to_openai_payload(message) == {
        "role": "user",
        "content": "Xin chao\nWiii",
    }


def test_message_to_openai_payload_accepts_native_dict_tool_message():
    assert message_to_openai_payload({
        "role": "tool",
        "tool_call_id": "call_123",
        "content": "tool result",
    }) == {
        "role": "tool",
        "tool_call_id": "call_123",
        "content": "tool result",
    }


def test_message_to_openai_payload_accepts_native_message_objects():
    assert message_to_openai_payload(make_system_message("System prompt")) == {
        "role": "system",
        "content": "System prompt",
    }
    assert message_to_openai_payload(make_user_message("Hi Wiii")) == {
        "role": "user",
        "content": "Hi Wiii",
    }
    assert message_to_openai_payload(
        make_tool_message("tool result", tool_call_id="call_123")
    ) == {
        "role": "tool",
        "tool_call_id": "call_123",
        "content": "tool result",
    }


def test_message_to_openai_payload_normalizes_assistant_tool_calls():
    payload = message_to_openai_payload(SimpleNamespace(
        type="ai",
        content="",
        tool_calls=[
            {
                "id": "call_weather",
                "name": "weather.lookup",
                "args": {"city": "Da Nang"},
            }
        ],
    ))

    assert payload["role"] == "assistant"
    assert payload["tool_calls"][0]["id"] == "call_weather"
    assert payload["tool_calls"][0]["function"]["name"] == "weather.lookup"
    assert json.loads(payload["tool_calls"][0]["function"]["arguments"]) == {
        "city": "Da Nang",
    }


def test_tool_to_openai_schema_accepts_simple_tool_object():
    tool = SimpleNamespace(
        name="ui.highlight",
        description="Highlight one host element",
        parameters={
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    )

    schema = tool_to_openai_schema(tool)

    assert schema == {
        "type": "function",
        "function": {
            "name": "ui.highlight",
            "description": "Highlight one host element",
            "parameters": {
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
            },
        },
    }


def test_native_handle_bind_tools_stores_openai_schema_and_normalized_choice():
    tool = SimpleNamespace(
        name="tool_current_datetime",
        description="Get current date and time",
        parameters={"type": "object", "properties": {}},
    )
    handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
    )

    bound = handle.bind_tools([tool], tool_choice="tool_current_datetime")

    assert bound is not handle
    assert bound._wiii_bound_tools[0]["function"]["name"] == "tool_current_datetime"
    assert bound._wiii_tool_choice == {
        "type": "function",
        "function": {"name": "tool_current_datetime"},
    }
    assert handle._wiii_bound_tools == []


def test_normalize_tool_choice_maps_force_any_to_required():
    assert normalize_tool_choice("any") == "required"
    assert normalize_tool_choice("required") == "required"
    assert normalize_tool_choice("tool_demo") == {
        "type": "function",
        "function": {"name": "tool_demo"},
    }


def test_openai_response_to_assistant_message_extracts_tool_calls():
    response = SimpleNamespace(
        model="deepseek-ai/deepseek-v4-flash",
        usage={"total_tokens": 42},
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="ui.highlight",
                                arguments='{"selector":"[data-wiii-id=\\"browse-courses\\"]"}',
                            ),
                        )
                    ],
                ),
            )
        ],
    )

    message = openai_response_to_assistant_message(response)

    assert message.content == ""
    assert message.response_metadata == {
        "model": "deepseek-ai/deepseek-v4-flash",
        "finish_reason": "tool_calls",
    }
    assert message.usage_metadata == {"total_tokens": 42}
    assert message.tool_calls == [
        {
            "id": "call_1",
            "name": "ui.highlight",
            "args": {"selector": '[data-wiii-id="browse-courses"]'},
        }
    ]


def test_make_assistant_message_preserves_langchain_like_surface_without_langchain():
    message = make_assistant_message(
        "Native answer",
        response_metadata={"model": "deepseek-ai/deepseek-v4-flash"},
        additional_kwargs={"thinking": "short plan"},
    )

    assert isinstance(message, NativeAssistantMessage)
    assert message.type == "ai"
    assert message.content == "Native answer"
    assert message.response_metadata["model"] == "deepseek-ai/deepseek-v4-flash"
    assert message.additional_kwargs["thinking"] == "short plan"


def test_agent_config_can_resolve_native_nvidia_handle(monkeypatch):
    from app.core.config import settings
    from app.engine.openai_compatible_credentials import resolve_nvidia_model
    from app.engine.multi_agent.agent_config import AgentConfigRegistry, AgentNodeConfig

    def _fake_runtime(cls, node_id, *, provider_override=None):
        return (
            AgentNodeConfig(node_id, provider="nvidia", tier="light", temperature=0.25),
            {},
            "nvidia",
            "light",
            None,
        )

    monkeypatch.setattr(
        AgentConfigRegistry,
        "_resolve_effective_runtime",
        classmethod(_fake_runtime),
    )

    handle = AgentConfigRegistry.get_native_llm(
        "direct",
        provider_override="nvidia",
    )

    assert handle is not None
    assert handle._wiii_native_route is True
    assert handle._wiii_provider_name == "nvidia"
    assert handle._wiii_model_name == resolve_nvidia_model(settings)
    assert handle._wiii_tier_key == "light"
    assert handle.temperature == 0.25


def test_agent_config_native_nvidia_handle_skips_degraded_primary(monkeypatch):
    from app.engine.llm_model_health import record_model_failure, reset_model_health_state
    from app.core.config import settings
    from app.engine.openai_compatible_credentials import (
        resolve_nvidia_model,
        resolve_nvidia_model_advanced,
    )
    from app.engine.multi_agent.agent_config import AgentConfigRegistry, AgentNodeConfig

    reset_model_health_state()

    def _fake_runtime(cls, node_id, *, provider_override=None):
        return (
            AgentNodeConfig(node_id, provider="nvidia", tier="light", temperature=0.25),
            {},
            "nvidia",
            "light",
            None,
        )

    monkeypatch.setattr(
        AgentConfigRegistry,
        "_resolve_effective_runtime",
        classmethod(_fake_runtime),
    )
    flash_model = resolve_nvidia_model(settings)
    pro_model = resolve_nvidia_model_advanced(settings)
    record_model_failure(
        "nvidia",
        flash_model,
        reason_code="timeout",
        degraded_for_seconds=60,
    )

    try:
        handle = AgentConfigRegistry.get_native_llm("direct")

        assert handle is not None
        assert handle._wiii_model_name == pro_model
    finally:
        reset_model_health_state()
