"""Phase 4 edge protocol adapters — Runtime Migration #207.

Locks in the wire-shape → ``TurnRequest`` contract for both adapters
shipped in this phase.
"""

from __future__ import annotations

import json

from app.engine.messages import Message
from app.engine.runtime.adapters import (
    anthropic_messages_to_turn_request,
    openai_chat_completions_to_turn_request,
    wiii_chat_request_to_turn_request,
)


# ── Wiii native adapter ──

def test_wiii_native_minimum_request():
    req = wiii_chat_request_to_turn_request(
        message="Hi",
        user_id="u1",
        session_id="s1",
    )
    assert req.user_id == "u1"
    assert req.session_id == "s1"
    assert req.role == "student"
    assert len(req.messages) == 1
    assert req.messages[0].role == "user"
    assert req.messages[0].content == "Hi"
    assert req.requested_streaming is False


def test_wiii_native_appends_message_after_history():
    history = [Message(role="user", content="prev"), Message(role="assistant", content="ack")]
    req = wiii_chat_request_to_turn_request(
        message="next", user_id="u1", session_id="s1", history=history
    )
    assert [m.content for m in req.messages] == ["prev", "ack", "next"]


def test_wiii_native_passes_streaming_and_capabilities():
    req = wiii_chat_request_to_turn_request(
        message="Hi",
        user_id="u1",
        session_id="s1",
        requested_streaming=True,
        requested_capabilities=["tools"],
        metadata={"preferred_provider": "google"},
    )
    assert req.requested_streaming is True
    assert "tools" in req.requested_capabilities
    assert req.metadata["preferred_provider"] == "google"


def test_wiii_native_sanitizes_metadata():
    req = wiii_chat_request_to_turn_request(
        message="Hi",
        user_id="u1",
        session_id="s1",
        metadata={
            "preferred_provider": "openai",
            "user_id": "raw-user-id",
            "access_token": "raw-access-token",
            "error": "Bearer raw-bearer-token-123",
        },
    )
    serialized = json.dumps(req.metadata, ensure_ascii=False)

    assert req.metadata["preferred_provider"] == "openai"
    assert req.metadata["user_id_hash"].startswith("sha256:")
    assert "<redacted-secret>" in req.metadata["error"]
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "access_token" not in serialized


# ── OpenAI Chat Completions adapter ──

def test_openai_compat_basic_text_request():
    body = {
        "model": "wiii-default",
        "messages": [
            {"role": "system", "content": "You are Wiii."},
            {"role": "user", "content": "Hi"},
        ],
    }
    req = openai_chat_completions_to_turn_request(
        body, user_id="u1", session_id="s1"
    )
    assert [m.role for m in req.messages] == ["system", "user"]
    assert req.metadata["openai_model"] == "wiii-default"
    assert req.requested_streaming is False
    assert req.requested_capabilities == []


def test_openai_compat_streaming_flag():
    body = {"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": True}
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert req.requested_streaming is True


def test_openai_compat_tools_capability():
    body = {
        "model": "x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "search"}}],
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert "tools" in req.requested_capabilities


def test_openai_compat_structured_output_via_response_format():
    body = {
        "model": "x",
        "messages": [{"role": "user", "content": "hi"}],
        "response_format": {"type": "json_object"},
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert "structured_output" in req.requested_capabilities


def test_openai_compat_vision_block_detection():
    body = {
        "model": "x",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": "data:..."}},
                ],
            }
        ],
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert "vision" in req.requested_capabilities
    # Multimodal content collapses to text for the canonical Message; raw
    # provider body is summarized for observability without raw image data.
    assert req.messages[0].content == "what is this?"
    summary = req.metadata["original_messages_summary"][0]["content"]
    assert summary["kind"] == "blocks"
    assert summary["blocks"][0]["text"]["present"] is True
    assert summary["blocks"][1]["image_url"]["is_data_url"] is True
    assert "original_messages" not in req.metadata
    assert "data:..." not in json.dumps(summary)


def test_openai_compat_metadata_summary_omits_raw_secrets():
    body = {
        "model": "x",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Bearer raw-bearer-token-123",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,raw-image-data"
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "publish",
                            "arguments": (
                                '{"message":"ok",'
                                '"access_token":"raw-access-token"}'
                            ),
                        },
                    }
                ],
            },
        ],
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    serialized = json.dumps(req.metadata, ensure_ascii=False)

    assert "raw-bearer-token-123" not in serialized
    assert "raw-image-data" not in serialized
    assert "raw-access-token" not in serialized
    assert "access_token" not in serialized
    assert req.metadata["original_messages_summary"][1]["tool_calls"][0][
        "argument_keys"
    ] == ["message"]


def test_openai_compat_assistant_tool_calls_round_trip():
    body = {
        "model": "x",
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q": "x"}'},
                    }
                ],
            }
        ],
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].tool_calls is not None
    assert req.messages[0].tool_calls[0].id == "c1"
    assert req.messages[0].tool_calls[0].arguments == {"q": "x"}


def test_openai_compat_tool_role_message_carries_tool_call_id():
    body = {
        "model": "x",
        "messages": [
            {"role": "tool", "content": "result", "tool_call_id": "c1"}
        ],
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].role == "tool"
    assert req.messages[0].tool_call_id == "c1"


def test_openai_compat_unknown_role_falls_back_to_user():
    body = {"model": "x", "messages": [{"role": "function", "content": "x"}]}
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].role == "user"


def test_openai_compat_temperature_and_max_tokens_into_metadata():
    body = {
        "model": "x",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.3,
        "max_tokens": 256,
    }
    req = openai_chat_completions_to_turn_request(body, user_id="u", session_id="s")
    assert req.metadata["temperature"] == 0.3
    assert req.metadata["max_tokens"] == 256


# ── Anthropic Messages adapter ──

def test_anthropic_compat_text_only_user_message():
    body = {
        "model": "claude-foo",
        "messages": [{"role": "user", "content": "hi"}],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert [m.role for m in req.messages] == ["user"]
    assert req.messages[0].content == "hi"
    assert req.metadata["anthropic_model"] == "claude-foo"


def test_anthropic_compat_system_prompt_prepends_system_message():
    body = {
        "system": "You are Wiii.",
        "messages": [{"role": "user", "content": "hi"}],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].role == "system"
    assert req.messages[0].content == "You are Wiii."
    assert req.messages[1].role == "user"


def test_anthropic_compat_assistant_text_block():
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "ack"}],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].role == "assistant"
    assert req.messages[0].content == "ack"
    assert req.messages[0].tool_calls is None


def test_anthropic_compat_assistant_tool_use_block_round_trip():
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "calling search"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "search",
                        "input": {"q": "x"},
                    },
                ],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    msg = req.messages[0]
    assert msg.role == "assistant"
    assert msg.content == "calling search"
    assert msg.tool_calls and msg.tool_calls[0].name == "search"
    assert msg.tool_calls[0].arguments == {"q": "x"}


def test_anthropic_compat_user_tool_result_block_split_into_tool_message():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "search result",
                    }
                ],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert [m.role for m in req.messages] == ["tool"]
    assert req.messages[0].tool_call_id == "toolu_1"
    assert req.messages[0].content == "search result"


def test_anthropic_compat_user_mixed_tool_result_and_text():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "follow-up"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "result",
                    },
                ],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    roles = [m.role for m in req.messages]
    assert roles == ["user", "tool"]


def test_anthropic_compat_image_block_sets_vision_capability():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "..."},
                    },
                ],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert "vision" in req.requested_capabilities
    summary = req.metadata["original_messages_summary"][0]["content"]
    assert summary["blocks"][1]["source"]["data_present"] is True
    assert "..." not in json.dumps(summary)


def test_anthropic_compat_metadata_summary_omits_raw_secrets():
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "publish",
                        "input": {
                            "message": "ok",
                            "access_token": "raw-access-token",
                        },
                    },
                    {
                        "type": "text",
                        "text": "token=raw-inline-token",
                    },
                ],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    serialized = json.dumps(req.metadata, ensure_ascii=False)

    assert "raw-access-token" not in serialized
    assert "raw-inline-token" not in serialized
    assert "access_token" not in serialized
    tool_use = req.metadata["original_messages_summary"][0]["content"]["blocks"][0][
        "tool_use"
    ]
    assert tool_use["argument_keys"] == ["message"]


def test_anthropic_compat_tools_capability_and_streaming_flag():
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "search"}],
        "stream": True,
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert "tools" in req.requested_capabilities
    assert req.requested_streaming is True


def test_anthropic_compat_unknown_role_falls_back_to_user():
    body = {"messages": [{"role": "system_extra", "content": "x"}]}
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].role == "user"


def test_anthropic_compat_tool_result_with_typed_content_blocks():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [{"type": "text", "text": "structured result"}],
                    }
                ],
            }
        ],
    }
    req = anthropic_messages_to_turn_request(body, user_id="u", session_id="s")
    assert req.messages[0].role == "tool"
    assert req.messages[0].content == "structured result"
