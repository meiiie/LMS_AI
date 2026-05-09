import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_build_direct_final_synthesis_instruction_is_mode_aware_for_market_turn():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_direct_final_synthesis_instruction,
    )

    instruction = _build_direct_final_synthesis_instruction(
        "phan tich gia dau",
        {},
        ["tool_web_search"],
    ).lower()

    assert "khong goi them cong cu" in instruction
    assert "mot cau thesis ve mat bang thi truong hien tai" in instruction
    assert "khong dung heading markdown nhu #, ##, ###" in instruction
    assert "khong dung bullet/bold kieu ban tin tong hop" in instruction
    assert "opec+" in instruction or "ton kho" in instruction


def test_explicit_web_search_returns_template_after_fetch_evidence():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _prefer_official_query_for_known_docs,
        _should_return_search_template_after_tool_round,
        _should_use_search_template_for_empty_response,
    )

    events = [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": "**OpenAI Responses API**\nURL: https://developers.openai.com/api/reference/responses",
            "id": "search_1",
        },
        {
            "type": "result",
            "name": "tool_fetch_url",
            "result": "The Responses API exposes POST /v1/responses.",
            "id": "fetch_1",
        },
    ]

    assert _should_return_search_template_after_tool_round(
        query="Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=events,
        tool_round=1,
    ) is True
    assert _should_return_search_template_after_tool_round(
        query="Phân tích nội bộ từ dữ liệu đã có",
        state={"routing_metadata": {"intent": "general"}},
        tool_call_events=events,
        tool_round=1,
    ) is False
    assert _should_return_search_template_after_tool_round(
        query="Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=events[:1],
        tool_round=0,
    ) is False
    rich_search_events = [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": (
                "**OpenAI Responses API**\n"
                "URL: https://developers.openai.com/api/reference/responses/overview\n"
                "POST /v1/responses creates a model response. "
                "GET /v1/responses/{response_id} retrieves a response. "
            )
            * 35,
            "id": "search_1",
        },
    ]
    assert _should_return_search_template_after_tool_round(
        query="Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=rich_search_events,
        tool_round=0,
    ) is True
    assert _prefer_official_query_for_known_docs(
        {"query": "OpenAI Responses API endpoints 2025"},
        "Tìm trên web giúp mình: OpenAI Responses API hiện tại có endpoint nào?",
    ) == {
        "query": "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
    }
    assert _should_use_search_template_for_empty_response(
        query="Tìm web từ nguồn chính thức OpenAI: Responses API endpoint là gì?",
        state={"routing_metadata": {"intent": "web_search"}},
        tool_call_events=events[:1],
    ) is True
    assert _should_use_search_template_for_empty_response(
        query="Không dùng web, chỉ nhắc lại trong phiên.",
        state={"routing_metadata": {"intent": "personal"}},
        tool_call_events=events[:1],
    ) is False


def test_direct_public_thinking_dedupe_detects_identical_blocks():
    from app.engine.multi_agent.direct_public_thinking_runtime import (
        remember_direct_public_thinking_chunks,
        should_emit_direct_public_thinking_chunks,
    )

    state = {}
    opening_chunks = [
        "Cau nay can mot nhip dap cham va that hon la mot loi giai thich voi.",
        "Minh muon mo loi vua du diu de neu ban muon ke tiep thi van con cho cho nhip do di ra.",
    ]
    remember_direct_public_thinking_chunks(state, opening_chunks)

    assert should_emit_direct_public_thinking_chunks(state, list(opening_chunks)) is False


def test_direct_public_thinking_dedupe_allows_changed_blocks():
    from app.engine.multi_agent.direct_public_thinking_runtime import (
        remember_direct_public_thinking_chunks,
        should_emit_direct_public_thinking_chunks,
    )

    state = {}
    remember_direct_public_thinking_chunks(
        state,
        [
            "Cau nay can mot nhip dap cham va that hon la mot loi giai thich voi.",
            "Minh muon mo loi vua du diu de neu ban muon ke tiep thi van con cho cho nhip do di ra.",
        ],
    )

    assert should_emit_direct_public_thinking_chunks(
        state,
        [
            "Gio minh da co them du kien nen co the noi cu the hon.",
            "Minh se giu nhip diu nhung neo cau tra loi vao dieu vua kiem chung.",
        ],
    ) is True


def test_build_direct_final_synthesis_instruction_is_mode_aware_for_math_turn():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_direct_final_synthesis_instruction,
    )

    instruction = _build_direct_final_synthesis_instruction(
        "Phan tich ve toan hoc con lac don",
        {},
        [],
    ).lower()

    assert "khong goi them cong cu" in instruction
    assert "mot cau thesis ve mo hinh dang dung" in instruction
    assert "mo hinh/gia dinh -> phuong trinh hoac suy dan -> y nghia vat ly" in instruction
    assert "khong dung heading markdown nhu #, ##, ###" in instruction


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_does_not_emit_authored_public_thinking_for_tool_rounds():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeTool:
        name = "tool_demo"

        async def ainvoke(self, args):
            return f"ket qua cho {args['query']}"

    events = []

    async def push_event(event):
        events.append(event)

    async def fake_ainvoke_with_fallback(_llm, _messages, **kwargs):
        call_index = fake_ainvoke_with_fallback.calls
        fake_ainvoke_with_fallback.calls += 1
        if call_index == 0:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {"id": "call_1", "name": "tool_demo", "args": {"query": "abc"}}
                ],
            )
        return SimpleNamespace(content="Day la cau tra loi cuoi.", tool_calls=[])

    fake_ainvoke_with_fallback.calls = 0

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("No-tool streaming path should not be used in this test")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(push_event, node, content, subtype):
        await push_event(
            {
                "type": "status",
                "content": content,
                "node": node,
                "subtype": subtype,
            }
        )

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="Tim giup minh mot du kien roi tra loi ngan gon.",
            state={},
            forced_tool_choice="tool_demo",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert llm_response.content == "Day la cau tra loi cuoi."
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    event_types = [event["type"] for event in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "thinking_start" not in event_types
    assert "thinking_delta" not in event_types
    assert "action_text" not in event_types


@pytest.mark.asyncio
async def test_forced_web_search_runs_tool_without_planner_or_synthesis_llm():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeTool:
        name = "tool_web_search"

        def invoke(self, args):
            return (
                "**Introducing GPT-5.5 - OpenAI**\n"
                "Apr 23, 2026 · OpenAI is releasing GPT-5.5.\n"
                "URL: https://openai.com/index/introducing-gpt-5-5/"
            )

        async def ainvoke(self, args):
            return (
                "**Introducing GPT-5.5 - OpenAI**\n"
                "Apr 23, 2026 · OpenAI is releasing GPT-5.5.\n"
                "URL: https://openai.com/index/introducing-gpt-5-5/"
            )

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        fake_ainvoke_with_fallback.calls += 1
        raise AssertionError("forced @web-search should not depend on planner LLM")

    fake_ainvoke_with_fallback.calls = 0

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("tool-bound turn should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="OpenAI latest model announcement 2026",
            state={"context": {"force_skills": ["web-search"]}},
            forced_tool_choice="tool_web_search",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert fake_ainvoke_with_fallback.calls == 0
    assert "Introducing GPT-5.5" in llm_response.content
    assert "https://openai.com/index/introducing-gpt-5-5/" in llm_response.content
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert tool_call_events[0]["args"]["query"] == "OpenAI latest model announcement 2026"


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_forwards_runtime_tier_to_failover_helper():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeTool:
        name = "tool_demo"

        async def ainvoke(self, args):
            return f"ket qua cho {args['query']}"

    captured: dict[str, object] = {}

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(_llm, _messages, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content="final", tool_calls=[])

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("tool-bound turn should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    llm = SimpleNamespace(_wiii_tier_key="deep", _wiii_provider_name="google")

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        await execute_direct_tool_rounds_impl(
            llm_with_tools=llm,
            llm_auto=llm,
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="Hay giai thich spectral theorem va self-adjoint operator",
            state={},
            llm_base=llm,
            forced_tool_choice="tool_demo",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert captured["tier"] == "deep"


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_can_use_native_tool_messages():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )
    from app.engine.native_chat_runtime import NativeToolMessage, NativeUserMessage

    class FakeTool:
        name = "tool_demo"

        def invoke(self, args):
            return f"ket qua cho {args['query']}"

    captured_messages: list[list[object]] = []

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(_llm, messages, **_kwargs):
        captured_messages.append(list(messages))
        call_index = fake_ainvoke_with_fallback.calls
        fake_ainvoke_with_fallback.calls += 1
        if call_index == 0:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {"id": "call_1", "name": "tool_demo", "args": {"query": "abc"}}
                ],
            )
        if call_index == 1:
            return SimpleNamespace(content="", tool_calls=[])
        return SimpleNamespace(content="Day la cau tra loi cuoi.", tool_calls=[])

    fake_ainvoke_with_fallback.calls = 0

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("tool-bound turn should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="Tim du kien roi tong hop lai",
            state={},
            forced_tool_choice="tool_demo",
            native_tool_messages=True,
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert llm_response.content == "Day la cau tra loi cuoi."
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert any(isinstance(message, NativeToolMessage) for message in captured_messages[1])
    assert isinstance(captured_messages[2][-1], NativeUserMessage)
    assert messages == captured_messages[2]


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_forwards_primary_timeout_to_stream_path():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    captured: dict[str, object] = {}

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(*args, **kwargs):
        raise AssertionError("no-tool turn should use streaming helper first")

    async def fake_stream_direct_answer_with_fallback(_llm, _messages, _push_event, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content="xin chao", tool_calls=[]), True

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    llm = SimpleNamespace(_wiii_tier_key="deep", _wiii_provider_name="zhipu")

    with patch(
        "app.engine.multi_agent.graph._stream_direct_answer_with_fallback",
        new=fake_stream_direct_answer_with_fallback,
    ):
        await execute_direct_tool_rounds_impl(
            llm_with_tools=llm,
            llm_auto=llm,
            messages=[],
            tools=[],
            push_event=push_event,
            query="Wiii duoc sinh ra nhu the nao?",
            state={},
            llm_base=llm,
            direct_answer_timeout_profile="structured",
            direct_answer_primary_timeout=6.0,
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert captured["primary_timeout"] == pytest.approx(6.0)
    assert captured["timeout_profile"] == "structured"


# ─────────────────────────────────────────────────────────────────────────
# Wiii Pointy v3.0 — server-side selector validator (anti-hallucination).
# ─────────────────────────────────────────────────────────────────────────


def _state_with_targets(*ids: str) -> SimpleNamespace:
    """Build minimal state.host_context.page.metadata.available_targets."""
    return SimpleNamespace(
        host_context={
            "page": {
                "metadata": {
                    "available_targets": [{"id": i} for i in ids],
                }
            }
        }
    )


def test_pointy_validator_accepts_bare_id_in_inventory():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button", "settings-link")
    assert _validate_pointy_selector("chat-send-button", state) is None


def test_pointy_validator_accepts_auto_id_in_inventory():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("auto:button:gui-tin-nhan", "settings-link")
    assert _validate_pointy_selector("auto:button:gui-tin-nhan", state) is None


def test_pointy_validator_accepts_data_wiii_id_verbose_form():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    assert (
        _validate_pointy_selector('[data-wiii-id="chat-send-button"]', state)
        is None
    )


def test_pointy_validator_rejects_compound_css_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector(
        'button[type="submit"], .send-button, [aria-label="Gửi"], button:has(svg)',
        state,
    )
    assert err is not None
    assert "ERROR" in err
    assert "NOT a valid Wiii Pointy id" in err
    assert "chat-send-button" in err  # available ids surfaced for self-correction


def test_pointy_validator_rejects_class_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector(".send-button", state)
    assert err is not None
    assert "DO NOT generate CSS selectors" in err


def test_pointy_validator_rejects_aria_label_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector('[aria-label="Gửi"]', state)
    assert err is not None
    assert "ERROR" in err


def test_pointy_validator_rejects_pseudo_class_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("button:has(svg)", state)
    assert err is not None


def test_pointy_validator_rejects_id_with_hash_prefix():
    """The `#chat-send-button` form is a CSS id selector, not a bare id."""
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("#chat-send-button", state)
    assert err is not None


def test_pointy_validator_rejects_empty_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("", state)
    assert err is not None
    assert "Empty selector" in err


def test_pointy_validator_rejects_unknown_bare_id_with_inventory_hint():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button", "settings-link")
    err = _validate_pointy_selector("nonexistent-button", state)
    assert err is not None
    assert "không có trong available_targets" in err
    assert "chat-send-button" in err


def test_pointy_validator_rejects_unknown_auto_id_with_inventory_hint():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("auto:button:gui-tin-nhan")
    err = _validate_pointy_selector("auto:button:cai-dat", state)
    assert err is not None
    assert "available_targets" in err
    assert "auto:button:gui-tin-nhan" in err


def test_pointy_validator_passes_bare_id_when_inventory_empty():
    """Without inventory we can't verify — fall through to permissive."""
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = SimpleNamespace(host_context=None)
    assert _validate_pointy_selector("chat-send-button", state) is None


def test_pointy_validator_passes_auto_id_when_inventory_empty():
    """Without inventory, allow Wiii synthetic id syntax and let frontend resolve."""
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = SimpleNamespace(host_context=None)
    assert _validate_pointy_selector("auto:button:gui-tin-nhan", state) is None



def test_build_force_skill_directive_pointy_inlines_inventory():
    """v3.0 F5: when @-mention force-binds wiii-pointy, system prompt
    directive must inline the available_targets so LLM picks right id
    without round-tripping tool_pointy_inventory."""
    from app.engine.multi_agent.direct_prompts import _build_force_skill_directive

    state = {
        'context': {
            'force_skills': ['wiii-pointy'],
            'host_context': {
                'page': {
                    'metadata': {
                        'available_targets': [
                            {'id': 'chat-send-button', 'role': 'button', 'label': 'Gửi tin nhắn'},
                            {'id': 'auto:button:dinh-kem-file', 'role': 'button', 'label': 'Đính kèm file'},
                            {'id': 'settings-link', 'role': 'link', 'label': 'Cài đặt'},
                        ]
                    }
                }
            }
        }
    }
    result = _build_force_skill_directive(state)
    # Imperative phrasing — Anthropic Computer Use 2026.
    assert 'PHẢI gọi' in result
    assert 'tool_pointy_show' in result
    # Inventory inline với prescriptive directive.
    assert 'chat-send-button' in result
    assert 'Gửi tin nhắn' in result
    # Anti-hallucination — exact inventory id contract, including auto ids.
    assert 'auto:button:dinh-kem-file' in result
    assert 'Synthetic ids' in result
    assert 'KHÔNG generate CSS' in result


def test_build_force_skill_directive_empty_when_no_force_skills():
    from app.engine.multi_agent.direct_prompts import _build_force_skill_directive

    assert _build_force_skill_directive({'context': {}}) == ''
    assert _build_force_skill_directive({}) == ''


def test_build_force_skill_directive_web_search_branch():
    from app.engine.multi_agent.direct_prompts import _build_force_skill_directive

    state = {'context': {'force_skills': ['web-search']}}
    result = _build_force_skill_directive(state)
    assert 'web-search' in result.lower() or 'tool_web_search' in result
    assert 'PHẢI gọi' in result



def test_make_pointy_show_with_enum_constrains_selector():
    """v9.0 F18: enum-bound tool's selector must accept inventory ids only.

    SeeAct (ICML'24) Textual Choices grounding pattern — JSON schema
    enum constraint at OpenAI tool-call layer.
    """
    from app.engine.tools.pointy_tools import make_pointy_show_with_enum

    inventory = ["chat-send-button", "auto:button:dinh-kem-file", "domain-selector"]
    enum_tool = make_pointy_show_with_enum(inventory)
    schema = enum_tool.input_model.model_json_schema()
    selector_field = schema.get("properties", {}).get("selector", {})
    # Pydantic produces enum constraint via Literal[...].
    enum_values = selector_field.get("enum")
    assert enum_values is not None
    assert set(enum_values) == set(inventory)


def test_make_pointy_show_with_enum_empty_falls_back_to_static():
    from app.engine.tools.pointy_tools import (
        make_pointy_show_with_enum,
        tool_pointy_show,
    )

    enum_tool = make_pointy_show_with_enum([])
    # No inventory → return static unchanged.
    assert enum_tool is tool_pointy_show


def test_make_pointy_show_with_enum_caps_at_64_for_token_budget():
    from app.engine.tools.pointy_tools import make_pointy_show_with_enum

    huge_inventory = [f"item-{i:03d}" for i in range(200)]
    enum_tool = make_pointy_show_with_enum(huge_inventory)
    schema = enum_tool.input_model.model_json_schema()
    enum_values = schema["properties"]["selector"].get("enum", [])
    # Cap to 64 to avoid prompt bloat.
    assert len(enum_values) == 64
    assert enum_values[0] == "item-000"


def test_validate_pointy_target_accepts_inventory_id():
    from app.engine.tools.pointy_tools import validate_pointy_target

    inv = ["chat-send-button", "attach-file-button"]
    assert validate_pointy_target("chat-send-button", inv) is None
    err = validate_pointy_target("nonexistent", inv)
    assert err is not None
    assert "not in current inventory" in err
    err = validate_pointy_target("", inv)
    assert err is not None


def test_extract_inventory_ids_from_state_dict_form():
    from app.engine.tools.pointy_tools import extract_inventory_ids_from_state

    state = {
        "host_context": {
            "page": {
                "metadata": {
                    "available_targets": [
                        {"id": "btn-a"},
                        {"id": "btn-b"},
                        {"id": ""},  # filtered
                    ]
                }
            }
        }
    }
    ids = extract_inventory_ids_from_state(state)
    assert ids == ["btn-a", "btn-b"]


def test_extract_inventory_ids_from_state_nested_context():
    from app.engine.tools.pointy_tools import extract_inventory_ids_from_state

    # Some flows set host_context inside state["context"] not top-level.
    state = {
        "context": {
            "host_context": {
                "page": {
                    "metadata": {
                        "available_targets": [{"id": "btn-x"}]
                    }
                }
            }
        }
    }
    ids = extract_inventory_ids_from_state(state)
    assert ids == ["btn-x"]
