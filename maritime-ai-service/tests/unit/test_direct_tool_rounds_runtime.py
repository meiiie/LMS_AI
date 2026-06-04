import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.engine.multi_agent.direct_document_host_action_runtime import (
    DocumentHostActionShortcut,
    execute_document_host_action_shortcut,
    execute_requested_document_host_action_shortcut,
)


def test_build_direct_final_synthesis_instruction_is_mode_aware_for_market_turn():
    from app.engine.multi_agent.direct_final_synthesis_runtime import (
        build_direct_final_synthesis_instruction as _build_direct_final_synthesis_instruction,
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


def test_build_direct_final_synthesis_instruction_blocks_live_lookup_memory_bleed():
    from app.engine.multi_agent.direct_final_synthesis_runtime import (
        build_direct_live_lookup_system_guard,
        build_direct_final_synthesis_instruction as _build_direct_final_synthesis_instruction,
    )

    instruction = _build_direct_final_synthesis_instruction(
        "thoi tiet Hai Phong hom nay",
        {},
        ["tool_web_search", "tool_current_datetime", "tool_fetch_url"],
    ).lower()

    assert "chi tra loi tu bang chung cong cu" in instruction
    assert "khong chen ky uc" in instruction
    assert "cam xuc" in instruction
    assert "hang hai" in instruction
    assert "ui da co the nguon" in instruction
    for tool_name in [
        "tool_web_search",
        "TOOL_SEARCH_LEGAL",
        "search_maritime",
        "tool_search_news",
    ]:
        guard = build_direct_live_lookup_system_guard([tool_name])
        assert "Do not use stored memory" in guard
        assert "interested in ports" in guard
    assert build_direct_live_lookup_system_guard(["tool_generate_visual"]) == ""


def test_explicit_web_search_returns_template_after_fetch_evidence():
    from app.engine.multi_agent.direct_web_search_policy import (
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


def test_auto_routed_web_search_does_not_use_explicit_search_template():
    from app.engine.multi_agent.direct_web_search_policy import (
        _should_return_search_template_after_tool_round,
        _should_use_search_template_for_empty_response,
    )

    events = [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": ("URL: https://example.test/news\nCurrent event evidence.\n") * 80,
            "id": "search_1",
        },
    ]

    assert (
        _should_return_search_template_after_tool_round(
            query="hom nay co gi hot",
            state={"routing_metadata": {"intent": "web_search"}},
            tool_call_events=events,
            tool_round=1,
        )
        is False
    )
    assert (
        _should_use_search_template_for_empty_response(
            query="hom nay co gi hot",
            state={"routing_metadata": {"intent": "web_search"}},
            tool_call_events=events,
        )
        is False
    )


def test_weather_web_search_does_not_return_raw_search_template_after_tool_round():
    from app.engine.multi_agent.direct_web_search_policy import (
        _should_return_search_template_after_tool_round,
        _should_use_search_template_for_empty_response,
    )

    events = [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": (
                "**AccuWeather Hai Phong**\n"
                "RealFeel 39C, humidity 64%, cloudy.\n"
                "URL: https://example.test/weather\n"
            )
            * 80,
            "id": "search_1",
        },
    ]

    assert (
        _should_return_search_template_after_tool_round(
            query="thời tiết Hải Phòng hôm nay cho mình nhé",
            state={"routing_metadata": {"intent": "web_search"}},
            tool_call_events=events,
            tool_round=0,
        )
        is False
    )
    assert (
        _should_use_search_template_for_empty_response(
            query="thời tiết Hải Phòng hôm nay cho mình nhé",
            state={"routing_metadata": {"intent": "web_search"}},
            tool_call_events=events,
        )
        is False
    )


def test_clean_forced_web_search_query_strips_vietnamese_discourse_marker():
    from app.engine.multi_agent.direct_web_search_policy import (
        _clean_forced_web_search_query,
    )

    cleaned = _clean_forced_web_search_query(
        "ý là thời tiết nóng đó. Bạn biết nay bao độ không"
    )

    assert cleaned == "thời tiết nóng đó. Bạn biết nay bao độ không"
    assert not cleaned.lower().startswith("ý là")


def test_clean_forced_web_search_query_strips_polite_search_suffix():
    from app.engine.multi_agent.direct_web_search_policy import (
        _clean_forced_web_search_query,
    )

    assert (
        _clean_forced_web_search_query("thời tiết Hải Phòng hôm nay cho mình")
        == "thời tiết Hải Phòng hôm nay"
    )
    assert (
        _clean_forced_web_search_query("@web-search giá vàng hôm nay giúp mình nhé")
        == "giá vàng hôm nay"
    )


def test_weather_lookup_limits_duplicate_web_search_fanout():
    from app.engine.multi_agent.direct_tool_round_execution_runtime import (
        _should_skip_weather_search_fanout,
    )

    state = {"_turn_path_decision": {"path": "web_search"}}
    query = "thời tiết Hải Phòng hôm nay"

    assert (
        _should_skip_weather_search_fanout(
            tool_call={"name": "tool_web_search"},
            query=query,
            state=state,
            executed_web_search_count=0,
        )
        is False
    )
    assert (
        _should_skip_weather_search_fanout(
            tool_call={"name": "tool_web_search"},
            query=query,
            state=state,
            executed_web_search_count=1,
        )
        is True
    )
    assert (
        _should_skip_weather_search_fanout(
            tool_call={"name": "tool_current_datetime"},
            query=query,
            state=state,
            executed_web_search_count=1,
        )
        is False
    )


def test_build_direct_post_tool_search_template_response_for_forced_web(monkeypatch):
    from app.engine.multi_agent import direct_search_template_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "build_search_template_fallback",
        lambda **_kwargs: "Tổng hợp từ web có nguồn.",
    )

    monkeypatch.setattr(
        runtime,
        "_force_skills_for_turn",
        lambda _state: {"web-search"},
    )

    response = runtime.build_direct_post_tool_search_template_response(
        query="giá dầu hôm nay",
        state={"routing_metadata": {"intent": "web_search"}},
        tool_call_events=[
            {
                "type": "result",
                "name": "tool_web_search",
                "result": "URL: https://example.test/oil\nGiá dầu tăng.",
            }
        ],
        tool_round=0,
        native_tool_messages=False,
    )

    assert response is not None
    assert response.content == "Tổng hợp từ web có nguồn."


def test_build_direct_post_tool_search_template_response_skips_weather_even_when_forced(
    monkeypatch,
):
    from app.engine.multi_agent import direct_search_template_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "build_search_template_fallback",
        lambda **_kwargs: "Không nên trả template cho weather tự nhiên.",
    )

    response = runtime.build_direct_post_tool_search_template_response(
        query="thời tiết Hải Phòng hôm nay cho mình nhé",
        state={"force_skills": ["web-search"]},
        tool_call_events=[
            {
                "type": "result",
                "name": "tool_web_search",
                "result": "URL: https://example.test/weather\nRealFeel 39C.",
            }
        ],
        tool_round=0,
        native_tool_messages=False,
    )

    assert response is None


def test_build_direct_post_tool_search_template_response_for_explicit_round(
    monkeypatch,
):
    from app.engine.multi_agent import direct_search_template_runtime as runtime

    monkeypatch.setattr(runtime, "_force_skills_for_turn", lambda _state: set())
    monkeypatch.setattr(
        runtime,
        "_should_return_search_template_after_tool_round",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        runtime,
        "build_search_template_fallback",
        lambda **_kwargs: "Tổng hợp sau vòng công cụ.",
    )

    response = runtime.build_direct_post_tool_search_template_response(
        query="tìm web về responses api",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=[{"type": "result", "name": "tool_fetch_url", "result": "ok"}],
        tool_round=1,
        native_tool_messages=False,
    )

    assert response is not None
    assert response.content == "Tổng hợp sau vòng công cụ."


def test_build_direct_post_tool_search_template_response_skips_empty_template(
    monkeypatch,
):
    from app.engine.multi_agent import direct_search_template_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "build_search_template_fallback",
        lambda **_kwargs: "",
    )

    response = runtime.build_direct_post_tool_search_template_response(
        query="giá dầu hôm nay",
        state={"force_skills": ["web-search"]},
        tool_call_events=[
            {"type": "result", "name": "tool_web_search", "result": "source"}
        ],
        tool_round=0,
        native_tool_messages=False,
    )

    assert response is None


@pytest.mark.asyncio
async def test_execute_forced_web_search_shortcut_emits_events(monkeypatch):
    from app.engine.multi_agent import direct_forced_web_search_runtime as runtime

    tool = object()
    emitted: list[dict] = []
    tool_events: list[dict] = []
    invoke_call: dict = {}

    monkeypatch.setattr(
        runtime,
        "build_search_template_fallback",
        lambda **_kwargs: "Tổng hợp nhanh có nguồn.",
    )

    async def push_event(event):
        emitted.append(event)

    def get_tool_by_name(tools, name):
        assert tools == [tool]
        return tool if name == "tool_web_search" else None

    async def invoke_tool_with_runtime(tool_arg, args, **kwargs):
        invoke_call["tool"] = tool_arg
        invoke_call["args"] = args
        invoke_call.update(kwargs)
        return (
            "URL: https://example.test\n"
            "Tin mới.\n"
            "access_token=raw-forced-token-123456 page_id=page-secret-123456"
        )

    response = await runtime.execute_forced_web_search_shortcut(
        query="@web-search giá dầu hôm nay",
        state={"force_skills": ["web-search"]},
        tools=[tool],
        messages=[],
        tool_call_events=tool_events,
        push_event=push_event,
        native_tool_messages=False,
        runtime_context_base={"tenant": "demo"},
        get_tool_by_name=get_tool_by_name,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        summarize_tool_result_for_stream=lambda _name, result: f"summary:{result}",
    )

    assert response is not None
    assert response.content == "Tổng hợp nhanh có nguồn."
    assert [event["type"] for event in emitted] == [
        "tool_call",
        "tool_result",
        "sources",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
    ]
    assert emitted[2]["content"][0]["url"] == "https://example.test"
    thinking_text = " ".join(
        str(event.get("content", ""))
        for event in emitted
        if event.get("type") == "thinking_delta"
    )
    assert "@web-search" not in thinking_text
    assert "tool_web_search" not in thinking_text
    assert "synthesizer" not in thinking_text.lower()
    assert tool_events[0]["type"] == "call"
    assert tool_events[0]["name"] == "tool_web_search"
    assert tool_events[1]["type"] == "result"
    assert "URL: https://example.test" in tool_events[1]["result"]
    assert "raw-forced-token" not in tool_events[1]["result"]
    assert "page-secret-123456" not in tool_events[1]["result"]
    assert invoke_call["tool"] is tool
    assert invoke_call["args"]["query"] == "giá dầu hôm nay"
    assert invoke_call["tool_name"] == "tool_web_search"
    assert invoke_call["runtime_context_base"] == {"tenant": "demo"}
    assert invoke_call["tool_call_id"] == "forced_web_search_0"
    assert invoke_call["prefer_async"] is False
    assert invoke_call["run_sync_in_thread"] is True


@pytest.mark.asyncio
async def test_execute_forced_web_search_shortcut_skips_natural_weather_auto_route():
    from app.engine.multi_agent import direct_forced_web_search_runtime as runtime

    emitted: list[dict] = []

    async def push_event(event):
        emitted.append(event)

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        raise AssertionError("Natural weather routing should use the planner loop")

    response = await runtime.execute_forced_web_search_shortcut(
        query="thời tiết Hải Phòng hôm nay cho mình nhé",
        state={"routing_metadata": {"intent": "web_search"}},
        tools=[object()],
        messages=[],
        tool_call_events=[],
        push_event=push_event,
        native_tool_messages=False,
        runtime_context_base={},
        get_tool_by_name=lambda _tools, _name: object(),
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        summarize_tool_result_for_stream=lambda _name, result: result,
    )

    assert response is None
    assert emitted == []


@pytest.mark.asyncio
async def test_execute_forced_web_search_shortcut_skips_when_not_forced():
    from app.engine.multi_agent.direct_forced_web_search_runtime import (
        execute_forced_web_search_shortcut,
    )

    response = await execute_forced_web_search_shortcut(
        query="giá dầu hôm nay",
        state={},
        tools=[object()],
        messages=[],
        tool_call_events=[],
        push_event=lambda _event: None,
        native_tool_messages=False,
        runtime_context_base=None,
        get_tool_by_name=lambda _tools, _name: object(),
        invoke_tool_with_runtime=lambda *_args, **_kwargs: None,
        summarize_tool_result_for_stream=lambda _name, result: result,
    )

    assert response is None


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
    from app.engine.multi_agent.direct_final_synthesis_runtime import (
        build_direct_final_synthesis_instruction as _build_direct_final_synthesis_instruction,
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
async def test_run_direct_final_synthesis_uses_no_tool_binding_and_moderate_timeout():
    from app.engine.multi_agent.direct_final_synthesis_runtime import (
        run_direct_final_synthesis,
    )

    llm_base = object()
    llm_auto = object()
    llm_with_tools = object()
    final_response = SimpleNamespace(
        content="Day la cau tra loi tong hop cuoi cung.",
        tool_calls=[],
    )
    calls: list[dict] = []
    heartbeat_kwargs: list[dict] = []

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(llm, messages, **kwargs):
        await asyncio.sleep(0)
        calls.append(
            {
                "llm": llm,
                "messages": list(messages),
                "kwargs": dict(kwargs),
            }
        )
        return final_response

    async def fake_stream_direct_wait_heartbeats(*_args, **kwargs):
        heartbeat_kwargs.append(dict(kwargs))
        await asyncio.Future()

    def remember_execution_target(candidate_llm, fallback_source=None):
        assert candidate_llm is llm_base
        assert fallback_source is llm_base
        return "qwen", "qwen3-next"

    def runtime_tier_for(candidate_llm, fallback_source=None):
        assert candidate_llm is llm_base
        assert fallback_source is llm_base
        return "base-tier"

    result = await run_direct_final_synthesis(
        messages=[],
        query="phan tich gia dau",
        state={},
        tool_call_events=[
            {"type": "call", "name": "tool_web_search", "id": "tc-1"},
            {"type": "result", "name": "tool_web_search", "id": "tc-1"},
        ],
        push_event=push_event,
        native_tool_messages=False,
        llm_base=llm_base,
        llm_auto=llm_auto,
        llm_with_tools=llm_with_tools,
        provider="auto",
        resolved_provider=None,
        request_failover_mode="auto",
        allowed_fallback_providers=("qwen",),
        ainvoke_with_fallback=fake_ainvoke_with_fallback,
        stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
        remember_execution_target=remember_execution_target,
        runtime_tier_for=runtime_tier_for,
    )

    assert result.llm_response is final_response
    assert result.resolved_provider == "qwen"
    assert len(result.messages) == 2
    assert result.messages[0].role == "system"
    assert "Do not use stored memory" in result.messages[0].content
    assert "Khong goi them cong cu" in result.messages[-1].content
    assert calls[0]["llm"] is llm_base
    assert "tools" not in calls[0]["kwargs"]
    assert calls[0]["kwargs"]["timeout_profile"] == "moderate"
    assert calls[0]["kwargs"]["tier"] == "base-tier"
    assert calls[0]["kwargs"]["allowed_fallback_providers"] == ("qwen",)
    assert heartbeat_kwargs[0]["phase"] == "synthesize"
    assert heartbeat_kwargs[0]["cue"] == "synthesis"
    assert heartbeat_kwargs[0]["tool_names"] == ["tool_web_search"]


@pytest.mark.asyncio
async def test_run_direct_final_synthesis_requires_unbound_base_llm():
    from app.engine.multi_agent.direct_final_synthesis_runtime import (
        run_direct_final_synthesis,
    )

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(*_args, **_kwargs):
        raise AssertionError("synthesis should fail before invoking a tool-bound model")

    async def fake_stream_direct_wait_heartbeats(*_args, **_kwargs):
        raise AssertionError("heartbeat should not start without an unbound model")

    with pytest.raises(RuntimeError, match="requires an unbound LLM"):
        await run_direct_final_synthesis(
            messages=[],
            query="phan tich gia dau",
            state={},
            tool_call_events=[{"type": "call", "name": "tool_web_search"}],
            push_event=push_event,
            native_tool_messages=False,
            llm_base=None,
            llm_auto=object(),
            llm_with_tools=object(),
            provider="auto",
            resolved_provider=None,
            request_failover_mode="auto",
            allowed_fallback_providers=None,
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            remember_execution_target=lambda *_args, **_kwargs: (None, None),
            runtime_tier_for=lambda *_args, **_kwargs: "moderate",
        )


def test_append_direct_tool_convergence_hint_inserts_sparse_self_eval():
    from app.engine.multi_agent.direct_tool_convergence_runtime import (
        append_direct_tool_convergence_hint,
    )

    messages = []
    result = append_direct_tool_convergence_hint(
        messages=messages,
        tool_round=0,
        tool_call_events=[
            {"type": "call", "name": "tool_web_search", "id": "tc-1"},
            {"type": "result", "name": "tool_web_search", "result": "short"},
        ],
        requires_visual_commit=False,
        native_tool_messages=False,
    )

    assert result.inserted is True
    assert result.kind == "sparse_self_eval"
    assert result.total_result_chars == len("short")
    assert len(messages) == 1
    assert "tool_search_news" in messages[0].content
    assert "110.01" in messages[0].content


def test_append_direct_tool_convergence_hint_inserts_rich_stop_hint():
    from app.engine.multi_agent.direct_tool_convergence_runtime import (
        append_direct_tool_convergence_hint,
    )

    messages = []
    result = append_direct_tool_convergence_hint(
        messages=messages,
        tool_round=0,
        tool_call_events=[
            {"type": "call", "name": "tool_fetch_url", "id": "tc-1"},
            {"type": "result", "name": "tool_fetch_url", "result": "x" * 2500},
        ],
        requires_visual_commit=False,
        native_tool_messages=False,
    )

    assert result.inserted is True
    assert result.kind == "rich_stop_hint"
    assert result.total_result_chars == 2500
    assert len(messages) == 1
    assert "110.01" in messages[0].content


@pytest.mark.parametrize(
    ("tool_round", "events", "requires_visual_commit"),
    [
        (1, [{"type": "call", "name": "tool_web_search"}], False),
        (0, [{"type": "call", "name": "tool_demo"}], False),
        (0, [{"type": "call", "name": "tool_web_search"}], True),
    ],
)
def test_append_direct_tool_convergence_hint_skips_non_convergence_cases(
    tool_round,
    events,
    requires_visual_commit,
):
    from app.engine.multi_agent.direct_tool_convergence_runtime import (
        append_direct_tool_convergence_hint,
    )

    messages = []
    result = append_direct_tool_convergence_hint(
        messages=messages,
        tool_round=tool_round,
        tool_call_events=events,
        requires_visual_commit=requires_visual_commit,
        native_tool_messages=False,
    )

    assert result.inserted is False
    assert messages == []


def test_select_direct_tool_followup_uses_auto_llm_for_non_visual_turn():
    from app.engine.multi_agent.direct_tool_followup_runtime import (
        select_direct_tool_followup,
    )
    from app.engine.multi_agent.visual_intent_resolver import VisualIntentDecision

    llm_auto = object()
    llm_base = object()
    llm_with_tools = object()
    tools = [SimpleNamespace(name="tool_web_search")]

    selection = select_direct_tool_followup(
        llm_auto=llm_auto,
        llm_base=llm_base,
        llm_with_tools=llm_with_tools,
        tools=tools,
        requires_visual_commit=False,
        visual_emitted_any=False,
        visual_decision=VisualIntentDecision(mode="text"),
        resolved_provider="zhipu",
        provider="auto",
    )

    assert selection.llm is llm_auto
    assert selection.tools is tools
    assert selection.tool_choice is None
    assert selection.fallback_source is llm_base


def test_select_direct_tool_followup_rebinds_visual_only_tools():
    from app.engine.multi_agent.direct_tool_followup_runtime import (
        select_direct_tool_followup,
    )
    from app.engine.multi_agent.visual_intent_resolver import VisualIntentDecision

    bound_llm = object()

    class FakeBaseLLM:
        def __init__(self):
            self.calls: list[dict] = []

        def bind_tools(self, tools, tool_choice=None):
            self.calls.append({"tools": list(tools), "tool_choice": tool_choice})
            return bound_llm

    llm_base = FakeBaseLLM()
    tools = [
        SimpleNamespace(name="tool_web_search"),
        SimpleNamespace(name="tool_generate_visual"),
        SimpleNamespace(name="tool_generate_mermaid"),
    ]

    selection = select_direct_tool_followup(
        llm_auto=object(),
        llm_base=llm_base,
        llm_with_tools=object(),
        tools=tools,
        requires_visual_commit=True,
        visual_emitted_any=False,
        visual_decision=VisualIntentDecision(
            mode="template",
            force_tool=True,
            presentation_intent="article_figure",
        ),
        resolved_provider="zhipu",
        provider="auto",
    )

    assert selection.llm is bound_llm
    assert [tool.name for tool in selection.tools] == ["tool_generate_visual"]
    assert selection.tool_choice == "tool_generate_visual"
    assert selection.fallback_source is llm_base
    assert len(llm_base.calls) == 1
    assert [tool.name for tool in llm_base.calls[0]["tools"]] == ["tool_generate_visual"]
    assert llm_base.calls[0]["tool_choice"] == "tool_generate_visual"


def test_select_direct_tool_followup_skips_non_bindable_base_llm():
    from app.engine.multi_agent.direct_tool_followup_runtime import (
        select_direct_tool_followup,
    )
    from app.engine.multi_agent.visual_intent_resolver import VisualIntentDecision

    bound_llm = object()

    class FakeAutoLLM:
        def __init__(self):
            self.calls: list[dict] = []

        def bind_tools(self, tools, tool_choice=None):
            self.calls.append({"tools": list(tools), "tool_choice": tool_choice})
            return bound_llm

    llm_auto = FakeAutoLLM()
    llm_base = object()
    tools = [
        SimpleNamespace(name="tool_web_search"),
        SimpleNamespace(name="tool_generate_visual"),
    ]

    selection = select_direct_tool_followup(
        llm_auto=llm_auto,
        llm_base=llm_base,
        llm_with_tools=object(),
        tools=tools,
        requires_visual_commit=True,
        visual_emitted_any=False,
        visual_decision=VisualIntentDecision(
            mode="template",
            force_tool=True,
            presentation_intent="article_figure",
        ),
        resolved_provider="zhipu",
        provider="auto",
    )

    assert selection.llm is bound_llm
    assert [tool.name for tool in selection.tools] == ["tool_generate_visual"]
    assert selection.tool_choice == "tool_generate_visual"
    assert selection.fallback_source is llm_auto
    assert len(llm_auto.calls) == 1
    assert [tool.name for tool in llm_auto.calls[0]["tools"]] == ["tool_generate_visual"]
    assert llm_auto.calls[0]["tool_choice"] == "tool_generate_visual"


def test_select_direct_tool_followup_keeps_auto_llm_after_visual_emits():
    from app.engine.multi_agent.direct_tool_followup_runtime import (
        select_direct_tool_followup,
    )
    from app.engine.multi_agent.visual_intent_resolver import VisualIntentDecision

    llm_auto = object()
    llm_base = object()
    tools = [SimpleNamespace(name="tool_generate_visual")]

    selection = select_direct_tool_followup(
        llm_auto=llm_auto,
        llm_base=llm_base,
        llm_with_tools=object(),
        tools=tools,
        requires_visual_commit=True,
        visual_emitted_any=True,
        visual_decision=VisualIntentDecision(
            mode="template",
            force_tool=True,
            presentation_intent="article_figure",
        ),
        resolved_provider="zhipu",
        provider="auto",
    )

    assert selection.llm is llm_auto
    assert selection.tools is tools
    assert selection.tool_choice is None
    assert selection.fallback_source is llm_base


@pytest.mark.asyncio
async def test_invoke_direct_tool_followup_cancels_heartbeat_and_updates_provider():
    from app.engine.multi_agent.direct_tool_followup_runtime import (
        invoke_direct_tool_followup,
    )
    from app.engine.multi_agent.visual_intent_resolver import VisualIntentDecision

    llm_auto = object()
    llm_base = object()
    response = SimpleNamespace(content="done")
    messages = [{"role": "user", "content": "xin chao"}]
    tools = [SimpleNamespace(name="tool_web_search")]
    state: dict = {"request_id": "req-1"}
    heartbeat_started = asyncio.Event()
    heartbeat_cancelled = False
    heartbeat_call: dict = {}
    invoke_call: dict = {}

    async def push_event(event):
        return event

    async def fake_heartbeats(push_event_arg, **kwargs):
        nonlocal heartbeat_cancelled
        heartbeat_call["push_event"] = push_event_arg
        heartbeat_call.update(kwargs)
        heartbeat_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            heartbeat_cancelled = True
            raise

    async def fake_ainvoke(llm, messages_arg, **kwargs):
        await heartbeat_started.wait()
        invoke_call["llm"] = llm
        invoke_call["messages"] = messages_arg
        invoke_call.update(kwargs)
        return response

    def remember_execution_target(candidate_llm, fallback_source=None):
        assert candidate_llm is llm_auto
        assert fallback_source is llm_base
        return "qwen", "qwen3-next"

    def runtime_tier_for(candidate_llm, fallback_source=None):
        assert candidate_llm is llm_auto
        assert fallback_source is llm_base
        return "balanced"

    result = await invoke_direct_tool_followup(
        llm_auto=llm_auto,
        llm_base=llm_base,
        llm_with_tools=object(),
        tools=tools,
        messages=messages,
        query="xin chao",
        push_event=push_event,
        requires_visual_commit=False,
        visual_emitted_any=False,
        visual_decision=VisualIntentDecision(mode="text"),
        resolved_provider="zhipu",
        provider="auto",
        request_failover_mode="auto",
        followup_timeout_profile="structured",
        state=state,
        allowed_fallback_providers=("zhipu",),
        ainvoke_with_fallback=fake_ainvoke,
        stream_direct_wait_heartbeats=fake_heartbeats,
        remember_execution_target=remember_execution_target,
        runtime_tier_for=runtime_tier_for,
        round_cue="tool-cue",
        round_tool_names=["tool_web_search"],
    )

    assert result.llm_response is response
    assert result.resolved_provider == "qwen"
    assert heartbeat_cancelled is True
    assert heartbeat_call["push_event"] is push_event
    assert heartbeat_call["query"] == "xin chao"
    assert heartbeat_call["phase"] == "ground"
    assert heartbeat_call["cue"] == "tool-cue"
    assert heartbeat_call["tool_names"] == ["tool_web_search"]
    assert invoke_call["llm"] is llm_auto
    assert invoke_call["messages"] is messages
    assert invoke_call["tools"] is tools
    assert invoke_call["tool_choice"] is None
    assert invoke_call["tier"] == "balanced"
    assert invoke_call["provider"] == "auto"
    assert invoke_call["resolved_provider"] == "qwen"
    assert invoke_call["failover_mode"] == "auto"
    assert invoke_call["push_event"] is push_event
    assert invoke_call["timeout_profile"] == "structured"
    assert invoke_call["state"] is state
    assert invoke_call["allowed_fallback_providers"] == ("zhipu",)


@pytest.mark.asyncio
async def test_finalize_direct_tool_response_uses_empty_search_template(monkeypatch):
    from app.engine.multi_agent import direct_tool_response_finalization_runtime as runtime

    messages = [{"role": "user", "content": "gia dau"}]
    tool_events = [{"type": "result", "name": "tool_web_search", "content": "evidence"}]
    inject_call: dict = {}

    monkeypatch.setattr(
        runtime,
        "_should_use_search_template_for_empty_response",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        runtime,
        "build_search_template_fallback",
        lambda **_kwargs: "Bản tổng hợp có nguồn.",
    )

    async def fail_synthesis(**_kwargs):
        raise AssertionError("final synthesis should not run after template fallback")

    def inject_widget_blocks(response, events, **kwargs):
        inject_call["response"] = response
        inject_call["events"] = events
        inject_call.update(kwargs)
        return response

    monkeypatch.setattr(runtime, "run_direct_final_synthesis", fail_synthesis)

    result = await runtime.finalize_direct_tool_response(
        llm_response=SimpleNamespace(content=""),
        messages=messages,
        tools=[SimpleNamespace(name="tool_web_search")],
        tool_call_events=tool_events,
        query="giá dầu hôm nay",
        state={"force_search": True},
        push_event=lambda _event: None,
        native_tool_messages=False,
        llm_base=object(),
        llm_auto=object(),
        llm_with_tools=object(),
        provider="auto",
        resolved_provider="zhipu",
        request_failover_mode="auto",
        allowed_fallback_providers=("zhipu",),
        ainvoke_with_fallback=lambda *_args, **_kwargs: None,
        stream_direct_wait_heartbeats=lambda *_args, **_kwargs: None,
        remember_execution_target=lambda *_args, **_kwargs: (None, None),
        runtime_tier_for=lambda *_args, **_kwargs: "moderate",
        inject_widget_blocks_from_tool_results=inject_widget_blocks,
        structured_visuals_enabled=True,
    )

    assert result.llm_response.content == "Bản tổng hợp có nguồn."
    assert result.messages is messages
    assert result.resolved_provider == "zhipu"
    assert inject_call["response"] is result.llm_response
    assert inject_call["events"] is tool_events
    assert inject_call["query"] == "giá dầu hôm nay"
    assert inject_call["structured_visuals_enabled"] is True


@pytest.mark.asyncio
async def test_finalize_direct_tool_response_forces_no_tool_synthesis(monkeypatch):
    from app.engine.multi_agent import direct_tool_response_finalization_runtime as runtime

    response = SimpleNamespace(content="final")
    messages = [{"role": "user", "content": "hoc hang hai"}]
    synthesized_messages = [*messages, {"role": "assistant", "content": "final"}]
    tool_events = [{"type": "call", "name": "tool_knowledge_search"}]
    synthesis_call: dict = {}

    monkeypatch.setattr(
        runtime,
        "_should_use_search_template_for_empty_response",
        lambda **_kwargs: False,
    )

    async def fake_synthesis(**kwargs):
        synthesis_call.update(kwargs)
        return SimpleNamespace(
            llm_response=response,
            messages=synthesized_messages,
            resolved_provider="qwen",
        )

    def inject_widget_blocks(response_arg, events, **kwargs):
        assert response_arg is response
        assert events is tool_events
        assert kwargs["structured_visuals_enabled"] is False
        return response_arg

    monkeypatch.setattr(runtime, "run_direct_final_synthesis", fake_synthesis)

    result = await runtime.finalize_direct_tool_response(
        llm_response=SimpleNamespace(content="", tool_calls=[{"name": "tool_demo"}]),
        messages=messages,
        tools=[SimpleNamespace(name="tool_demo")],
        tool_call_events=tool_events,
        query="mình muốn học hàng hải",
        state={"request_id": "req-2"},
        push_event=lambda _event: None,
        native_tool_messages=False,
        llm_base="base",
        llm_auto="auto",
        llm_with_tools="with_tools",
        provider="auto",
        resolved_provider="zhipu",
        request_failover_mode="auto",
        allowed_fallback_providers=("zhipu",),
        ainvoke_with_fallback=lambda *_args, **_kwargs: None,
        stream_direct_wait_heartbeats=lambda *_args, **_kwargs: None,
        remember_execution_target=lambda *_args, **_kwargs: (None, None),
        runtime_tier_for=lambda *_args, **_kwargs: "moderate",
        inject_widget_blocks_from_tool_results=inject_widget_blocks,
        structured_visuals_enabled=False,
    )

    assert result.llm_response is response
    assert result.messages is synthesized_messages
    assert result.resolved_provider == "qwen"
    assert synthesis_call["messages"] is messages
    assert synthesis_call["query"] == "mình muốn học hàng hải"
    assert synthesis_call["tool_call_events"] is tool_events
    assert synthesis_call["resolved_provider"] == "zhipu"


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
async def test_execute_direct_tool_rounds_converts_raw_json_tool_call_text():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeKnowledgeTool:
        name = "tool_knowledge_search"

        async def ainvoke(self, args):
            return f"Nguon nhap mon hang hai cho {args['query']}"

    events = []

    async def push_event(event):
        events.append(event)

    async def fake_stream_direct_answer_with_fallback(*_args, **_kwargs):
        return (
            SimpleNamespace(
                content=json.dumps(
                    {
                        "name": "tool_knowledge_search",
                        "arguments": {
                            "query": "gioi thieu nganh hang hai cho nguoi moi bat dau",
                        },
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            ),
            True,
        )

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        return SimpleNamespace(
            content=(
                "Được chứ. Nếu mới bắt đầu học Hàng hải, mình sẽ đi từ bức tranh lớn: "
                "tàu, cảng, an toàn, luật biển và nghiệp vụ vận hành."
            ),
            tool_calls=[],
        )

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
        "app.engine.multi_agent.graph._stream_direct_answer_with_fallback",
        new=fake_stream_direct_answer_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeKnowledgeTool()],
            push_event=push_event,
            query="Mình đang muốn học về lĩnh vực Hàng Hải các bạn có thể giúp mình được không",
            state={},
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert "tool_knowledge_search" not in llm_response.content
    assert "mới bắt đầu học Hàng hải" in llm_response.content
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert tool_call_events[0]["name"] == "tool_knowledge_search"
    assert tool_call_events[0]["args"]["query"] == "gioi thieu nganh hang hai cho nguoi moi bat dau"
    assert any(event["type"] == "tool_call" for event in events)
    assert not any(
        event["type"] == "answer_delta" and "tool_knowledge_search" in str(event.get("content", ""))
        for event in events
    )


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
async def test_uploaded_document_preview_runs_host_action_without_planner_llm():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    captured: dict[str, object] = {}

    class FakeHostPreviewTool:
        name = "host_action__authoring__preview_lesson_patch"

        def invoke(self, args):
            captured["args"] = dict(args)
            return json.dumps(
                {
                    "status": "action_requested",
                    "request_id": "host-preview-1",
                    "action": "authoring.preview_lesson_patch",
                    "params": args,
                },
                ensure_ascii=False,
            )

        async def ainvoke(self, args):
            return self.invoke(args)

    class FakeHostApplyTool:
        name = "host_action__authoring__apply_lesson_patch"

        def invoke(self, args):
            captured["apply_args"] = dict(args)
            raise AssertionError(
                "uploaded document authoring must not apply before preview approval"
            )

        async def ainvoke(self, args):
            return self.invoke(args)

    events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        raise AssertionError("uploaded document preview should not depend on planner LLM")

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("document preview should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    markdown = (
        "Sổ tay trực ca buồng lái\n"
        "Marker kiểm thử: WIII_DOC_GOAL_123\n"
        "Mục tiêu học tập 1: giải thích quy trình trực ca khi tầm nhìn hạn chế.\n"
        "Checklist nguồn trang 4: xác nhận người trực ca, kiểm tra thiết bị định vị.\n"
        "Checklist nguồn trang 5: báo thuyền trưởng, giảm tốc an toàn, ghi nhật ký.\n"
    )
    state = {
        "context": {
            "document_context": {
                "attachments": [
                    {
                        "file_name": "so-tay-truc-ca.docx",
                        "markdown": markdown,
                    }
                ]
            },
            "page_context": {"lesson_id": "lesson-from-url"},
        }
    }

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
            tools=[FakeHostPreviewTool(), FakeHostApplyTool()],
            push_event=push_event,
            query=(
                "Dua tren tai lieu Word vua upload, tao preview_lesson_patch "
                "co source_references page 4-5 va marker WIII_DOC_GOAL_123."
            ),
            state=state,
            forced_tool_choice="host_action__authoring__preview_lesson_patch",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    preview_args = captured["args"]
    assert preview_args["lesson_id"] == "lesson-from-url"
    assert preview_args["title"].startswith("Bản nháp:")
    assert "# Bản nháp bài học từ tài liệu:" in preview_args["content"]
    assert "## Mục tiêu học tập" in preview_args["content"]
    assert "## Hoạt động thảo luận" in preview_args["content"]
    assert "Marker kiểm thử: WIII_DOC_GOAL_123" in preview_args["content"]
    assert "Ban nhap" not in preview_args["content"]
    assert "Muc tieu hoc tap" not in preview_args["content"]
    assert "WIII_DOC_GOAL_123" in preview_args["content"]
    assert preview_args["source_references"][0]["page_start"] == 4
    assert preview_args["source_references"][0]["page_end"] == 5
    assert [event["type"] for event in tool_call_events] == ["call", "host_action", "result"]
    assert any(event.get("type") == "host_action" for event in events)
    assert "apply_args" not in captured
    assert "preview" in llm_response.content.lower()


@pytest.mark.asyncio
async def test_uploaded_document_course_plan_runs_host_action_without_planner_llm():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    captured: dict[str, object] = {}

    class FakeHostCourseTool:
        name = "host_action__authoring__generate_course_from_document"

        def invoke(self, args):
            captured["args"] = dict(args)
            return json.dumps(
                {
                    "status": "action_requested",
                    "request_id": "host-course-1",
                    "action": "authoring.generate_course_from_document",
                    "params": args,
                },
                ensure_ascii=False,
            )

        async def ainvoke(self, args):
            return self.invoke(args)

    events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        raise AssertionError("uploaded document course plan should not depend on planner LLM")

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("document course plan should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    markdown = (
        "# Hướng Dẫn Sử Dụng HoLiLiHu LMS\n"
        "Nguồn section: 1. Tổng Quan (trang 1-2)\n"
        "# 3. Hướng Dẫn Cho Học Viên\n"
        "Nguồn section: 3. Hướng Dẫn Cho Học Viên (trang 12-20)\n"
        "# 4. Hướng Dẫn Cho Giảng Viên\n"
        "Nguồn section: 4. Hướng Dẫn Cho Giảng Viên (trang 21-34)\n"
        "## 4.2. Tạo khóa học mới\n"
        "Nguồn section: 4.2. Tạo khóa học mới (trang 23-25)\n"
        "## 4.5. Thêm video, tài liệu và quiz\n"
        "Nguồn section: 4.5. Thêm video, tài liệu và quiz (trang 29-31)\n"
        "# 5. Hướng Dẫn Cho Quản Lý\n"
        "Nguồn section: 5. Hướng Dẫn Cho Quản Lý (trang 35-42)\n"
    )
    state = {
        "context": {
            "document_context": {
                "attachments": [
                    {
                        "file_name": "Huong_dan_su_dung_HoLiLiHu_LMS.docx",
                        "markdown": markdown,
                    }
                ]
            },
            "page_context": {"course_id": "course-from-url"},
        }
    }

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
            tools=[FakeHostCourseTool()],
            push_event=push_event,
            query="Dựa trên tài liệu Word vừa upload, hãy tạo toàn bộ khóa học theo chương/bài có citation.",
            state=state,
            forced_tool_choice="host_action__authoring__generate_course_from_document",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    course_args = captured["args"]
    course_plan = course_args["course_plan"]
    assert course_args["course_id"] == "course-from-url"
    assert course_args["action"] == "preview_course_plan_from_document"
    assert course_plan["title"] == "Khai thác HoLiLiHu LMS từ tài liệu hướng dẫn"
    assert len(course_plan["chapters"]) == 5
    assert sum(len(chapter["lessons"]) for chapter in course_plan["chapters"]) >= 15
    assert "Tác nghiệp giảng viên" in course_plan["chapters"][2]["title"]
    assert "source_references" in course_plan["chapters"][2]["lessons"][0]
    assert any(ref.get("page_start") == 23 for ref in course_args["source_references"])
    assert [event["type"] for event in tool_call_events] == ["call", "host_action", "result"]
    assert any(event.get("type") == "host_action" for event in events)
    assert "khóa học" in llm_response.content.lower()


def test_uploaded_doc_course_plan_builder_creates_full_lms_architecture():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
    )

    markdown = (
        "# Hướng Dẫn Sử Dụng HoLiLiHu LMS\n"
        "Nguồn section: 1. Tổng Quan (trang 1-2)\n"
        "# 3. Hướng Dẫn Cho Học Viên\n"
        "Nguồn section: 3. Hướng Dẫn Cho Học Viên (trang 12-20)\n"
        "# 4. Hướng Dẫn Cho Giảng Viên\n"
        "Nguồn section: 4. Hướng Dẫn Cho Giảng Viên (trang 21-34)\n"
        "## 4.2. Tạo khóa học mới\n"
        "Nguồn section: 4.2. Tạo khóa học mới (trang 23-25)\n"
        "## 4.5. Thêm video, tài liệu và quiz\n"
        "Nguồn section: 4.5. Thêm video, tài liệu và quiz (trang 29-31)\n"
        "# 5. Hướng Dẫn Cho Quản Lý\n"
        "Nguồn section: 5. Hướng Dẫn Cho Quản Lý (trang 35-42)\n"
    )
    params = _build_uploaded_doc_course_params(
        "Tạo khóa học đầy đủ từ tài liệu Word này, chia chương/bài có source_references.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "Huong_dan_su_dung_HoLiLiHu_LMS.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-1"},
            }
        },
    )

    plan = params["course_plan"]
    assert params["course_id"] == "course-1"
    assert params["changed_fields"] == ["course_structure"]
    assert params["summary"].endswith("tài liệu upload.")
    assert "trích dẫn" not in params["summary"]
    assert "LMS" not in params["summary"]
    assert len(plan["chapters"]) == 5
    titles = [chapter["title"] for chapter in plan["chapters"]]
    assert any("Hành trình học viên" in title for title in titles)
    assert any("Tác nghiệp giảng viên" in title for title in titles)
    assert any("Quản lý" in title for title in titles)
    assert plan["chapters"][2]["lessons"][0]["source_references"][0]["page_start"] == 23
    assert f"{sum(len(chapter['lessons']) for chapter in plan['chapters'])} bài" in plan["duration"]
    assert "không publish tự động" in " ".join(plan["implementation_checklist"])


def test_uploaded_doc_course_plan_builder_keeps_maritime_research_out_of_lms_manual():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    markdown = (
        "# NGHIEN CUU XAY DUNG HE THONG QUAN LY VAN HANH VA HO SO TAU THUY\n"
        "Nguon section: GIOI THIEU (trang 1-4)\n"
        "# GIOI THIEU\n"
        "Gioi thieu bai toan xay dung he thong quan ly van hanh va ho so tau thuy.\n"
        "Nguon section: Gioi thieu bai toan xay dung he thong quan ly van hanh va ho so tau thuy (trang 5-8)\n"
        "# KHAO SAT BAI TOAN VAN HANH VA HO SO TAU THUY\n"
        "Nguon section: Khao sat bai toan van hanh va ho so tau thuy (trang 9-20)\n"
        "## Nghiep vu quan ly van hanh va ho so tau thuy\n"
        "Nguon section: Nghiep vu quan ly van hanh va ho so tau thuy (trang 18-28)\n"
        "# PHAN TICH VA THIET KE HE THONG\n"
        "Nguon section: Phan tich va thiet ke he thong (trang 29-40)\n"
        "## Phan tich chuc nang cua he thong tau\n"
        "Nguon section: Phan tich chuc nang cua he thong tau (trang 41-50)\n"
        "## So do luong du lieu muc ngu canh\n"
        "Nguon section: So do luong du lieu muc ngu canh (trang 51-60)\n"
        "## Thiet ke co so du lieu tau\n"
        "Nguon section: Thiet ke co so du lieu tau (trang 61-80)\n"
        "## Cac bang du lieu\n"
        "Nguon section: Cac bang du lieu (trang 81-95)\n"
        "## Phan tich chuc nang cua he thong bo\n"
        "Nguon section: Phan tich chuc nang cua he thong bo (trang 96-110)\n"
        "# KET LUAN VA HUONG PHAT TRIEN\n"
        "Nguon section: Ket luan va huong phat trien (trang 111-120)\n"
    )
    params = _build_uploaded_doc_course_params(
        (
            "Lap chuong trinh dao tao cho giao vien tu tai lieu Word nay. "
            "Khong bien thanh huong dan HoLiLiHu LMS; hay bam vao van hanh, "
            "ho so tau thuy va doanh nghiep van tai bien."
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "40 - GV.25-26.01.31 - Nghien cuu he thong quan ly van hanh va ho so tau thuy.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-vessel"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))
    assert params["course_id"] == "course-vessel"
    assert len(plan["chapters"]) == 6
    assert sum(len(chapter["lessons"]) for chapter in plan["chapters"]) == 18
    assert "holilihu" not in normalized_plan
    assert "dang nhap" not in normalized_plan
    assert "video tuong tac" not in normalized_plan
    assert "ho so tau" in normalized_plan
    assert "van tai bien" in normalized_plan
    assert "co so du lieu" in normalized_plan or "du lieu" in normalized_plan
    assert all(
        lesson.get("source_references")
        for chapter in plan["chapters"]
        for lesson in chapter["lessons"]
    )


def test_uploaded_doc_course_plan_builder_keeps_maritime_lms_research_out_of_holilihu_manual():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    markdown = (
        "CONG TRINH\n\n"
        "**NGHIEN CUU XAY DUNG HE THONG LMS NANG CAO NGHIEP VU CHUYEN MON CHO CAC THUY THU**\n"
        "# GIOI THIEU\n"
        "Tai lieu phan tich nhu cau boi duong nghiep vu chuyen mon cho thuy thu bang he thong LMS.\n"
        "Nguon section: Gioi thieu nhu cau dao tao thuy thu (trang 1-5)\n"
        "# CO SO LY LUAN VA THUC TIEN\n"
        "Trinh bay co so e-learning, quan ly hoc tap va dac thu dao tao hang hai.\n"
        "Nguon section: Co so ly luan va thuc tien (trang 6-18)\n"
        "# PHAN TICH VA THIET KE HE THONG LMS\n"
        "Mo ta cac chuc nang quan ly khoa hoc, nguoi hoc, bai giang va danh gia nang luc.\n"
        "Nguon section: Phan tich va thiet ke he thong LMS (trang 19-36)\n"
        "# THU NGHIEM VA DANH GIA\n"
        "Danh gia kha nang ung dung he thong trong dao tao nghiep vu chuyen mon cho thuy thu.\n"
        "Nguon section: Thu nghiem va danh gia (trang 37-48)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tao bai giang di.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "SV25-26.43_KH-KT.docx",
                            "title": "tmpg98c_ocp",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-maritime-lms"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))
    assert params["course_id"] == "course-maritime-lms"
    assert plan["document_domain"]["id"] == "maritime_training_lms"
    assert "holilihu" not in normalized_plan
    assert "khai thac holilihu lms" not in normalized_plan
    assert "quan ly van hanh va ho so tau" not in normalized_plan
    assert "nghien cuu xay dung he thong lms" in _normalize_doc_preview_text(
        plan["source_document_title"]
    )
    assert "nghiep vu" in normalized_plan
    assert "thuy thu" in normalized_plan


def test_uploaded_doc_course_plan_research_title_overrides_manual_markers_in_body():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    markdown = (
        "CONG TRINH\n\n"
        "**NGHIEN CUU XAY DUNG HE THONG LMS NANG CAO NGHIEP VU CHUYEN MON CHO CAC THUY THU**\n"
        "# GIOI THIEU\n"
        "Tai lieu phan tich nhu cau boi duong nghiep vu chuyen mon cho thuy thu bang he thong LMS.\n"
        "Nguon section: Gioi thieu nhu cau dao tao thuy thu (trang 1-5)\n"
        "# HUONG DAN SU DUNG HE THONG LMS\n"
        "Noi dung minh hoa co cac marker dang nhap, tao khoa hoc, them video va quiz.\n"
        "HoLiLiHu LMS duoc nhac den nhu mot vi du san pham trong qua trinh nghien cuu.\n"
        "Nguon section: Phan tich chuc nang LMS va quy trinh su dung (trang 19-36)\n"
        "# THU NGHIEM VA DANH GIA\n"
        "Danh gia kha nang ung dung he thong trong dao tao nghiep vu chuyen mon cho thuy thu.\n"
        "Nguon section: Thu nghiem va danh gia (trang 37-48)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tao bai giang di.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "SV25-26.43_KH-KT.docx",
                            "title": "tmpg98c_ocp",
                            "markdown": markdown,
                        }
                    ]
                },
                "host_context": {
                    "page": {
                        "metadata": {
                            "course_id": "course-from-nested-host-metadata",
                        }
                    }
                },
            }
        },
    )

    plan = params["course_plan"]
    normalized_title = _normalize_doc_preview_text(plan["title"])
    assert params["course_id"] == "course-from-nested-host-metadata"
    assert plan["document_domain"]["id"] == "maritime_training_lms"
    assert "khai thac holilihu lms" not in normalized_title


def test_uploaded_doc_course_plan_maritime_lms_does_not_use_vessel_template():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    markdown = (
        "CONG TRINH\n\n"
        "**NGHIEN CUU XAY DUNG HE THONG LMS NANG CAO NGHIEP VU CHUYEN MON CHO CAC THUY THU**\n"
        "| Sinh vien thuc hien chinh | PHAM THI MINH HONG |\n"
        "| Sinh vien thuc hien | NGUYEN THUY LINH |\n"
        "2. San pham cong nghe\n"
        "He thong LMS ho tro dao tao truc tuyen cho thuy thu va hoc vien hang hai.\n"
        "San pham duoc dinh huong phuc vu boi duong nghiep vu chuyen mon, theo doi tien do, "
        "quan ly bai giang, quiz va danh gia nang luc trong moi truong van tai bien.\n"
        "Noi dung co nhac den tau thuy va boi canh hang hai nhung trong tam la he thong LMS dao tao.\n"
        "Nguon section: 2. San pham cong nghe (trang 1-4)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tao bai giang di. Chia thanh chuong/bai co nguon trich dan.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "SV25-26.43_KH-KT.docx",
                            "title": "tmpqd4k3n0b",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-prod-like-maritime-lms"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))
    assert params["course_id"] == "course-prod-like-maritime-lms"
    assert plan["document_domain"]["id"] == "maritime_training_lms"
    assert "nghien cuu xay dung he thong lms" in _normalize_doc_preview_text(
        plan["source_document_title"]
    )
    assert "lms nang cao nghiep vu" in normalized_plan
    assert "thuy thu" in normalized_plan
    assert "quan ly van hanh va ho so tau" not in normalized_plan
    assert "doanh nghiep van tai bien" not in normalized_plan
    assert all(
        lesson.get("source_references")
        for chapter in plan["chapters"]
        for lesson in chapter["lessons"]
    )


def test_uploaded_doc_course_title_skips_cover_metadata_for_long_thesis_doc():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    title = (
        "NGHIEN CUU XAY DUNG HE THONG QUAN LY VAN HANH VA HO SO TAU THUY "
        "PHUC VU DOANH NGHIEP VAN TAI BIEN"
    )
    markdown = (
        "| BO XAY DUNG | BO GIAO DUC VA DAO TAO |\n"
        "|-------------|-------------------------|\n\n"
        "**TRUONG DAI HOC HANG HAI VIET NAM**\n\n"
        "<!-- image -->\n\n"
        "**VU DUC TINH - 97658 - CNT63CL**\n\n"
        "**BUI TRUNG HIEU - 95457 - CNT63CL**\n\n"
        "**THUC TAP TOT NGHIEP**\n\n"
        f"**{title}**\n\n"
        "HAI PHONG - 2026\n\n"
        "# MO DAU\n"
        "Tai lieu trinh bay bai toan quan ly van hanh, ho so tau thuy va doanh nghiep van tai bien.\n"
        "Nguon section: Mo dau bai toan quan ly ho so tau (trang 1-4)\n"
        "# PHAN TICH HE THONG\n"
        "Mo ta chuc nang quan ly tau, ho so, thuyen vien, bao tri va van hanh.\n"
        "Nguon section: Phan tich he thong quan ly tau (trang 5-20)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tao bai giang di.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "40 - GV.25-26.01.31.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-thesis"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_source = _normalize_doc_preview_text(plan["source_document_title"])
    assert params["course_id"] == "course-thesis"
    assert plan["document_domain"]["id"] == "maritime_vessel_management"
    assert "bo xay dung" not in normalized_source
    assert "truong dai hoc" not in normalized_source
    assert "nghien cuu xay dung he thong quan ly van hanh" in normalized_source
    assert "doanh nghiep van tai bien" in normalized_source


def test_generic_uploaded_doc_course_clusters_full_long_document_map():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    sections = []
    for index in range(1, 25):
        sections.append(
            "\n".join(
                [
                    f"# Section {index}: Operational capability {index}",
                    f"This section explains capability {index}, constraints, evidence, and practical decisions.",
                    f"Nguon section: Section {index}: Operational capability {index} (trang {index}-{index})",
                ]
            )
        )
    markdown = "# Complex operations handbook\n" + "\n\n".join(sections)

    params = _build_uploaded_doc_course_params(
        "Turn this uploaded handbook into a complete course plan with citations.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "complex-operations-handbook.docx",
                            "title": "Complex operations handbook",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-generic"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))

    assert params["course_id"] == "course-generic"
    assert plan["document_domain"]["id"] == "generic_document_course"
    assert len(plan["chapters"]) == 6
    assert sum(len(chapter["lessons"]) for chapter in plan["chapters"]) == 18
    assert plan["document_map_summary"]["strategy"] == "cluster_full_document_map"
    assert plan["document_map_summary"]["candidate_section_count"] >= 24
    assert params["quality_report"]["status"] == "pass"
    assert params["quality_report"]["source_reference_count"] >= 24
    assert "section 24" in normalized_plan
    assert "section 1" in normalized_plan
    assert all(
        lesson.get("source_references")
        for chapter in plan["chapters"]
        for lesson in chapter["lessons"]
    )


def test_uploaded_doc_course_parses_unicode_vietnamese_source_lines():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_course_params,
    )

    markdown = (
        "# Báo cáo vận hành\n"
        "Nguồn section: Tổng quan vận hành (trang 7-9)\n"
        "# Quy trình kiểm tra\n"
        "Nguồn section: Quy trình kiểm tra (trang 12)\n"
        "# Đánh giá sau triển khai\n"
        "Nguồn section: Đánh giá sau triển khai (trang 18-20)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tạo khóa học từ báo cáo này với citation.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "bao-cao-van-hanh.docx",
                            "title": "Báo cáo vận hành",
                            "markdown": markdown,
                        }
                    ]
                },
            }
        },
    )

    assert params["quality_report"]["source_reference_count"] == 3
    assert params["source_references"][0]["page_start"] == 7
    assert params["source_references"][0]["page_end"] == 9


def test_uploaded_doc_course_request_matches_real_teacher_curriculum_wording():
    from app.engine.multi_agent.document_preview_contract import (
        looks_uploaded_document_course_request as _looks_uploaded_doc_course_request,
    )

    assert _looks_uploaded_doc_course_request("Tạo bài giảng đi.")
    assert _looks_uploaded_doc_course_request("Soạn giáo án từ tài liệu vừa upload.")
    assert _looks_uploaded_doc_course_request(
        "Tu file Word vua upload, lap chuong trinh dao tao hoan chinh, "
        "de cuong khoa, lo trinh hoc va chia thanh chuong/bai co citation."
    )
    assert _looks_uploaded_doc_course_request(
        "Hay bien tai lieu nay thanh curriculum/syllabus gom nhieu chuong "
        "va nhieu bai hoc cho giao vien."
    )


def test_uploaded_doc_preview_skips_logo_data_uri_and_focuses_teacher_manual():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    markdown = (
        "![Logo Trường Đại học Hàng hải Việt Nam](data:image/png;base64...)\n\n"
        "**HƯỚNG DẪN SỬ DỤNG\n"
        "HOLILIHU ONLINE LMS**\n\n"
        "| **Vai trò** | **Nên đọc trước** | **Mục tiêu sau khi đọc** |\n"
        "| --- | --- | --- |\n"
        "| **Giảng viên** | Phần 4 và 5 | Biết tạo khóa, soạn nội dung và xuất bản. |\n\n"
        "# 4. Hướng Dẫn Cho Giảng Viên\n"
        "Mục tiêu học tập: giảng viên biết tạo khóa học, soạn bài học và kiểm tra trước khi xuất bản.\n"
        "Quy trình thao tác: mở trang quản lý khóa học, cập nhật bài học, thêm tài liệu và kiểm tra quiz.\n"
        "Checklist triển khai: xác nhận tiêu đề, nội dung, tài liệu đính kèm, trạng thái xuất bản và quyền truy cập học viên.\n"
    )
    params = _build_uploaded_doc_preview_params(
        (
            'Dựa trên tài liệu Word, tạo preview cho giáo viên. '
            'Trong preview gửi source_references title là "Hướng dẫn sử dụng HoLiLiHu LMS". '
            'Marker WIII_DOC_GOAL_REAL_MANUAL.'
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "Huong_dan_su_dung_HoLiLiHu_LMS_Chi_tiet_2026-05-10.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"lesson_id": "lesson-manual"},
            }
        },
    )

    content = params["content"]
    assert params["title"] == "Bản nháp: Hướng dẫn sử dụng HoLiLiHu LMS"
    assert params["lesson_id"] == "lesson-manual"
    assert params["source_references"][0]["title"] == "Hướng dẫn sử dụng HoLiLiHu LMS"
    assert "Logo Trường Đại học Hàng hải" not in params["title"]
    assert "data:image" not in content
    assert "| **Vai trò**" not in content
    assert "## Checklist thao tác / nội dung cần nắm" in content
    assert "giảng viên biết tạo khóa học" in content
    assert "trực ca" not in content.lower()
    assert "WIII_DOC_GOAL_REAL_MANUAL" in content


def test_uploaded_doc_preview_preserves_general_wiii_marker_from_query():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    marker = "WIII_PRODUCT_E2E_20260512024500"
    params = _build_uploaded_doc_preview_params(
        (
            "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload. "
            f"Noi dung bai hoc moi phai chua marker kiem thu chinh xac: {marker}."
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Muc tieu hoc tap: giao vien tao khoa hoc va kiem tra noi dung.\n"
                                "Quy trinh thao tac: mo khoa hoc, cap nhat bai hoc, kiem tra quiz.\n"
                            ),
                        }
                    ]
                },
                "page_context": {"lesson_id": "lesson-e2e"},
            }
        },
    )

    assert params["lesson_id"] == "lesson-e2e"
    assert marker in params["content"]


def test_uploaded_doc_preview_preserves_labelled_non_wiii_marker_from_query():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    marker = "COURSE_PATCH_MARKER_42"
    params = _build_uploaded_doc_preview_params(
        (
            "Create a safe LMS preview from the uploaded document. "
            f"Exact marker: {marker}."
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Bridge resource management guide\n"
                                "Learning objective: verify the checklist before saving.\n"
                                "Checklist: title, lesson content, source references, preview approval.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    assert marker in params["content"]


def test_uploaded_doc_preview_prefers_explicit_query_title_over_parser_metadata():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        (
            'Tao preview_lesson_patch cho giao vien. '
            'Trong preview gui source_references title la "Huong dan su dung HoLiLiHu LMS".'
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "title": "Parser provenance",
                            "markdown": (
                                "Parser provenance\n"
                                "Muc tieu hoc tap: giao vien cap nhat bai hoc trong LMS.\n"
                                "Checklist: kiem tra tieu de, noi dung va nguon truoc khi luu.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    assert params["title"] == "Bản nháp: Hướng dẫn sử dụng HoLiLiHu LMS"
    assert params["source_references"][0]["title"] == "Hướng dẫn sử dụng HoLiLiHu LMS"
    assert "# Bản nháp bài học từ tài liệu: Hướng dẫn sử dụng HoLiLiHu LMS" in params["content"]
    assert "Parser provenance" not in params["title"]


def test_uploaded_doc_preview_prefers_real_teacher_heading_over_smart_excerpt_outline():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    markdown = (
        "# Tai lieu upload: manual.docx\n\n"
        "## Muc luc phat hien\n"
        "- 3. Huong Dan Cho Hoc Vien\n"
        "- 4. Huong Dan Cho Giang Vien\n"
        "- 4.2. Tao khoa hoc moi\n\n"
        "## Trich doan dau tai lieu\n"
        "Vai tro: Hoc vien, Giang vien, Quan ly.\n\n"
        "## Trich doan uu tien theo vai tro/chu de\n"
        "### 4. Huong Dan Cho Giang Vien\n"
        "# 4. Huong Dan Cho Giang Vien\n"
        "Phan nay tap trung vao tac vu tao va van hanh khoa hoc.\n\n"
        "## 4.2. Tao khoa hoc moi\n"
        "**Giang vien**\n\n"
        "| **Muc tieu** | Nhap thong tin khoa theo cach du dung cho duyet va cho hoc vien hieu. |\n"
        "| --- | --- |\n"
        "| **Buoc** | **Thao tac** | **Ket qua dung** |\n"
        "| **1** | Bam Tao khoa hoc. | Form co cac nhom thong tin tach ro. |\n"
        "| **2** | Nhap tieu de ro rang. | Truong bat buoc bao loi neu thieu. |\n"
        "Checklist trien khai: tieu de, noi dung, video tuong tac, cau hoi va trang thai xuat ban.\n"
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien voi source_references tu tai lieu LMS nay.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": markdown,
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    assert "Tai lieu upload" not in content
    assert "Muc luc phat hien" not in content
    assert "- 4. Huong Dan Cho Giang Vien" not in content
    assert "Nhap thong tin khoa" in content
    assert "Checklist trien khai" in content
    assert "HoLiLiHu LMS" in params["description"]
    assert "OOW" not in params["description"]


def test_doc_preview_clean_line_drops_checkbox_table_markers():
    from app.engine.multi_agent.direct_document_preview_text import _clean_doc_preview_line

    assert _clean_doc_preview_line(
        "| **□** | Thong tin khoa hoan chinh. | Co tieu de va muc tieu hoc tap. |"
    ) == "Thong tin khoa hoan chinh. - Co tieu de va muc tieu hoc tap."


def test_uploaded_doc_preview_filters_bare_table_labels_from_goals():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "| **Muc tieu** |\n"
                                "| **Muc tieu hoc tap** |\n"
                                "| **Buoc** | **Thao tac** | **Ket qua dung** |\n"
                                "Muc tieu hoc tap: giao vien cap nhat bai hoc va kiem tra nguon truoc khi luu.\n"
                                "Checklist: xac nhan tieu de, noi dung, nguon va trang thai xuat ban.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    assert "- Muc tieu\n" not in content
    assert "- Muc tieu hoc tap\n" not in content
    assert "- Buoc" not in content
    assert "- Thao tac" not in content
    assert "giao vien cap nhat bai hoc" in content
    assert "xac nhan tieu de" in content


def test_uploaded_doc_preview_keeps_ordered_actions_out_of_learning_goals():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Muc tieu hoc tap: giao vien hieu cach chuan bi bai hoc truoc khi luu.\n"
                                "| **Buoc** | **Thao tac** | **Ket qua dung** |\n"
                                "| **3** | Them anh dai dien va nhap muc tieu bai hoc khi soan bai. |"
                                "Noi dung duoc hien thi dung cho hoc vien. |\n"
                                "Checklist: xac nhan source references va preview approval.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    objectives_section = content.split("## Checklist", 1)[0]
    checklist_section = content.split("## Checklist", 1)[1]
    assert "giao vien hieu cach chuan bi bai hoc" in objectives_section
    assert "Them anh dai dien" not in objectives_section
    assert "- 3 - Them anh" not in content
    assert "Them anh dai dien va nhap muc tieu bai hoc" in checklist_section


def test_uploaded_doc_preview_excludes_admonitions_from_learning_goals():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Khong nen dan van ban qua dai mot doan. "
                                "Chia thanh muc tieu, doi tuong, yeu cau dau vao.\n"
                                "Luu y: giao vien kiem tra citation truoc khi luu.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    objectives_section = content.split("## Checklist", 1)[0]
    assert "Khong nen dan van ban qua dai" not in objectives_section
    assert "Luu y: giao vien kiem tra citation" not in objectives_section
    assert "Giáo viên xác định đúng thao tác cần làm trong LMS" in objectives_section


def test_uploaded_doc_preview_shapes_descriptive_excerpt_into_learning_goal():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Phan nay tap trung vao tac vu tao va van hanh khoa hoc: "
                                "lap khoa, soan noi dung, tao cau hoi va cau hinh video.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    objectives_section = params["content"].split("## Checklist", 1)[0]
    assert "Phan nay tap trung vao" not in objectives_section
    assert (
        "Giáo viên thực hiện được tac vu tao va van hanh khoa hoc"
        in objectives_section
    )


def test_uploaded_doc_preview_repairs_truncated_publish_word_in_learning_goal():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Phan nay tap trung vao tac vu tao va van hanh khoa hoc: "
                                "lap khoa, soan noi dung, tao cau hoi, cau hinh video, "
                                "kiem tra roi xuat ba\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    objectives_section = params["content"].split("## Checklist", 1)[0]
    assert "xuat ba trong LMS" not in objectives_section
    assert "xuất bản trong LMS" in objectives_section


def test_uploaded_doc_preview_supplements_sparse_lms_learning_goals():
    from app.engine.multi_agent.direct_document_preview_payloads import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Muc tieu hoc tap: giao vien tao khoa hoc dung quy trinh.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    objectives_section = params["content"].split("## Checklist", 1)[0]
    objective_lines = [
        line for line in objectives_section.splitlines() if line.startswith("- ")
    ]
    assert len(objective_lines) >= 3
    assert "giao vien tao khoa hoc dung quy trinh" in objectives_section
    assert "phần so sánh thay đổi và nguồn trích dẫn" in objectives_section
    assert "diff, citation" not in objectives_section
    assert "bấm Apply" not in objectives_section
    assert "trạng thái nháp" in objectives_section


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
            llm_base=object(),
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
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button", "settings-link")
    assert _validate_pointy_selector("chat-send-button", state) is None


@pytest.mark.asyncio
async def test_direct_pointy_post_dispatch_emits_show_action() -> None:
    from app.engine.multi_agent.direct_pointy_runtime import (
        handle_direct_pointy_post_dispatch,
    )

    pushed_events: list[dict] = []

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    result = await handle_direct_pointy_post_dispatch(
        tool_name="tool_pointy_show",
        tool_args={
            "selector": "chat-send-button",
            "caption": "Nút gửi",
            "duration_ms": 3000,
        },
        result="[POINTY:highlight]",
        state=_state_with_targets("chat-send-button"),
        push_event=push_event,
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert result.result == "[POINTY:highlight]"
    assert result.pointy_action_emitted is True
    assert result.inventory_served is False
    assert [event["type"] for event in pushed_events] == ["pointy_action"]
    assert pushed_events[0]["content"]["action"] == "ui.highlight"
    assert pushed_events[0]["content"]["params"]["selector"] == "chat-send-button"


@pytest.mark.asyncio
async def test_direct_pointy_post_dispatch_rewrites_invalid_selector_result() -> None:
    from app.engine.multi_agent.direct_pointy_runtime import (
        handle_direct_pointy_post_dispatch,
    )

    pushed_events: list[dict] = []

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    result = await handle_direct_pointy_post_dispatch(
        tool_name="tool_pointy_show",
        tool_args={"selector": ".send-button"},
        result="[POINTY:highlight]",
        state=_state_with_targets("chat-send-button"),
        push_event=push_event,
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert "NOT a valid Wiii Pointy id" in result.result
    assert result.pointy_action_emitted is False
    assert pushed_events == []


@pytest.mark.asyncio
async def test_direct_pointy_post_dispatch_rewrites_inventory_result() -> None:
    from app.engine.multi_agent.direct_pointy_runtime import (
        handle_direct_pointy_post_dispatch,
    )

    async def push_event(event: dict) -> None:
        return None

    result = await handle_direct_pointy_post_dispatch(
        tool_name="tool_pointy_inventory",
        tool_args={},
        result="[POINTY:inventory]",
        state=_state_with_targets("chat-send-button"),
        push_event=push_event,
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert result.inventory_served is True
    assert "Pointable elements" in result.result
    assert 'tool_pointy_show(selector="chat-send-button"' in result.result


def test_pointy_validator_accepts_auto_id_in_inventory():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("auto:button:gui-tin-nhan", "settings-link")
    assert _validate_pointy_selector("auto:button:gui-tin-nhan", state) is None


def test_pointy_validator_accepts_data_wiii_id_verbose_form():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    assert (
        _validate_pointy_selector('[data-wiii-id="chat-send-button"]', state)
        is None
    )


def test_pointy_validator_rejects_compound_css_selector():
    from app.engine.multi_agent.direct_pointy_runtime import (
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
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector(".send-button", state)
    assert err is not None
    assert "DO NOT generate CSS selectors" in err


def test_pointy_validator_rejects_aria_label_selector():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector('[aria-label="Gửi"]', state)
    assert err is not None
    assert "ERROR" in err


def test_pointy_validator_rejects_pseudo_class_selector():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("button:has(svg)", state)
    assert err is not None


def test_pointy_validator_rejects_id_with_hash_prefix():
    """The `#chat-send-button` form is a CSS id selector, not a bare id."""
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("#chat-send-button", state)
    assert err is not None


def test_pointy_validator_rejects_empty_selector():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("", state)
    assert err is not None
    assert "Empty selector" in err


def test_pointy_validator_rejects_unknown_bare_id_with_inventory_hint():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button", "settings-link")
    err = _validate_pointy_selector("nonexistent-button", state)
    assert err is not None
    assert "không có trong available_targets" in err
    assert "chat-send-button" in err


def test_pointy_validator_rejects_unknown_auto_id_with_inventory_hint():
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("auto:button:gui-tin-nhan")
    err = _validate_pointy_selector("auto:button:cai-dat", state)
    assert err is not None
    assert "available_targets" in err
    assert "auto:button:gui-tin-nhan" in err


def test_pointy_validator_passes_bare_id_when_inventory_empty():
    """Without inventory we can't verify — fall through to permissive."""
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = SimpleNamespace(host_context=None)
    assert _validate_pointy_selector("chat-send-button", state) is None


def test_pointy_validator_passes_auto_id_when_inventory_empty():
    """Without inventory, allow Wiii synthetic id syntax and let frontend resolve."""
    from app.engine.multi_agent.direct_pointy_runtime import (
        _validate_pointy_selector,
    )

    state = SimpleNamespace(host_context=None)
    assert _validate_pointy_selector("auto:button:gui-tin-nhan", state) is None



def test_build_force_skill_directive_pointy_inlines_inventory():
    """v3.0 F5: when @-mention force-binds wiii-pointy, system prompt
    directive must inline the available_targets so LLM picks right id
    without round-tripping tool_pointy_inventory."""
    from app.engine.multi_agent.direct_prompt_turn_contracts import _build_force_skill_directive

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
    from app.engine.multi_agent.direct_prompt_turn_contracts import _build_force_skill_directive

    assert _build_force_skill_directive({'context': {}}) == ''
    assert _build_force_skill_directive({}) == ''


def test_build_force_skill_directive_web_search_branch():
    from app.engine.multi_agent.direct_prompt_turn_contracts import _build_force_skill_directive

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


@pytest.mark.asyncio
async def test_document_host_action_shortcut_emits_preview_event_contract() -> None:
    pushed_events: list[dict] = []
    tool_call_events: list[dict] = []
    invoke_kwargs: dict = {}
    state: dict = {}

    shortcut = DocumentHostActionShortcut(
        tool_name="tool_preview_lesson_patch",
        tool_call_id="forced_doc_preview_0",
        thinking="Preview only; wait for approval_token before apply.",
        thinking_summary="Preview document lesson",
        thinking_provenance="test_document_preview",
        response="Preview sent.",
        failure_log_message="failed: %s",
    )

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    async def invoke_tool(tool, args, **kwargs):
        invoke_kwargs.update(kwargs)
        return {"host_action": "preview", "approval_required": True}

    async def emit_host_action(**kwargs) -> None:
        pushed_events.append(
            {
                "type": "host_action",
                "content": kwargs["result"],
                "node": kwargs["node"],
            }
        )

    response = await execute_document_host_action_shortcut(
        shortcut=shortcut,
        tool=object(),
        args={"title": "Bản nháp"},
        state=state,
        tool_call_events=tool_call_events,
        push_event=push_event,
        invoke_tool_with_runtime=invoke_tool,
        maybe_emit_host_action_event=emit_host_action,
        summarize_tool_result_for_stream=lambda name, result: "summary",
        runtime_context_base={"request_id": "req-1"},
        query_snippet="Bản nháp",
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert response == "Preview sent."
    assert state["thinking_content"] == shortcut.thinking
    assert invoke_kwargs["tool_name"] == shortcut.tool_name
    assert invoke_kwargs["tool_call_id"] == shortcut.tool_call_id
    assert invoke_kwargs["prefer_async"] is False
    assert invoke_kwargs["run_sync_in_thread"] is True
    assert [event["type"] for event in pushed_events] == [
        "tool_call",
        "tool_result",
        "host_action",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
    ]
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert tool_call_events[0]["name"] == shortcut.tool_name
    assert tool_call_events[1]["result"] == str(
        {"host_action": "preview", "approval_required": True}
    )


@pytest.mark.asyncio
async def test_document_host_action_shortcut_redacts_public_tool_args() -> None:
    pushed_events: list[dict] = []
    tool_call_events: list[dict] = []
    invoked_args: dict = {}
    state: dict = {}

    shortcut = DocumentHostActionShortcut(
        tool_name="tool_preview_lesson_patch",
        tool_call_id="forced_doc_preview_sensitive",
        thinking="Preview only.",
        thinking_summary="Preview document lesson",
        thinking_provenance="test_document_preview",
        response="Preview sent.",
        failure_log_message="failed: %s",
    )

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    async def invoke_tool(tool, args, **kwargs):
        invoked_args.update(args)
        return {"host_action": "preview"}

    async def emit_host_action(**kwargs) -> None:
        return None

    await execute_document_host_action_shortcut(
        shortcut=shortcut,
        tool=object(),
        args={
            "title": "Draft",
            "content": "private uploaded document excerpt",
            "source_references": [{"excerpt": "raw source text"}],
            "course_plan": {"chapters": [{"title": "raw chapter"}]},
        },
        state=state,
        tool_call_events=tool_call_events,
        push_event=push_event,
        invoke_tool_with_runtime=invoke_tool,
        maybe_emit_host_action_event=emit_host_action,
        summarize_tool_result_for_stream=lambda name, result: "summary",
        runtime_context_base=None,
        query_snippet="Draft",
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert invoked_args["content"] == "private uploaded document excerpt"
    public_args = pushed_events[0]["content"]["args"]
    assert public_args["title"] == "Draft"
    assert public_args["content"] == "[redacted]"
    assert public_args["source_references"] == "[redacted]"
    assert public_args["course_plan"] == "[redacted]"
    assert tool_call_events[0]["args"] == public_args


@pytest.mark.asyncio
async def test_wiii_connect_facebook_post_preflight_defers_ready_request_to_tool_schema(monkeypatch) -> None:
    from app.engine.multi_agent.direct_wiii_connect_host_action_runtime import (
        preflight_requested_wiii_connect_facebook_post,
    )

    state: dict = {
        "context": {
            "images": [{"type": "base64", "data": "abc"}],
            "host_context": {
                "page": {
                    "metadata": {
                        "wiii_connect": {
                            "provider_slug": "facebook",
                            "status": "connected",
                            "connection_count": 1,
                            "active_connection_count": 1,
                            "connection_state": "connected",
                        }
                    }
                }
            },
        }
    }

    def build_assistant_message(content: str, **kwargs) -> dict:
        return {"content": content, "native_tool_messages": kwargs["native_tool_messages"]}

    monkeypatch.setattr(
        "app.engine.multi_agent.external_app_action_runtime."
        "_effective_action_allowlists_for_providers",
        lambda *_args, **_kwargs: {"facebook": ("FACEBOOK_CREATE_POST",)},
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.external_app_action_runtime."
        "_ready_provider_slugs_from_state",
        lambda *_args, **_kwargs: ("facebook",),
    )

    response = await preflight_requested_wiii_connect_facebook_post(
        query="Wiii đăng bài Facebook, bài nào cũng được kèm ảnh này",
        state=state,
        native_tool_messages=True,
        build_assistant_message=build_assistant_message,
    )

    assert response is None


@pytest.mark.asyncio
async def test_wiii_connect_facebook_post_preflight_preempts_forced_web_search(monkeypatch) -> None:
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    class FakeWebSearchTool:
        name = "tool_web_search"

        def invoke(self, _args):
            raise AssertionError("facebook external action should preempt web search")

        async def ainvoke(self, _args):
            raise AssertionError("facebook external action should preempt web search")

    class FakeFacebookPreviewTool:
        name = WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL

        def invoke(self, args):
            return json.dumps(
                {
                    "status": "action_requested",
                    "request_id": "fb-direct-apply-1",
                    "action": "wiii_connect.facebook_post.direct_apply",
                    "params": args,
                }
            )

        async def ainvoke(self, args):
            return self.invoke(args)

    pushed_events: list[dict] = []

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    ainvoke_calls: list[dict] = []

    async def fake_ainvoke_with_fallback(*_args, **kwargs):
        ainvoke_calls.append(kwargs)
        if len(ainvoke_calls) == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "fb-direct-apply-1",
                        "name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
                        "args": {
                            "provider_slug": "facebook",
                            "message": (
                                "Một ngày bình thường của Wiii: đang học COLREGs"
                            ),
                        },
                    }
                ],
            )
        return SimpleNamespace(
            content="Mình đã gửi yêu cầu đăng bài Facebook qua Wiii Connect.",
            tool_calls=[],
        )

    async def fake_stream_direct_answer_with_fallback(*_args, **_kwargs):
        raise AssertionError("facebook external action should not stream direct answer")

    async def fake_stream_direct_wait_heartbeats(*_args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.engine.multi_agent.external_app_action_runtime."
        "_effective_action_allowlists_for_providers",
        lambda *_args, **_kwargs: {"facebook": ("FACEBOOK_CREATE_POST",)},
    )
    monkeypatch.setattr(
        "app.engine.multi_agent.external_app_action_runtime."
        "_ready_provider_slugs_from_state",
        lambda *_args, **_kwargs: ("facebook",),
    )

    state = {
        "context": {
            "force_skills": ["web-search"],
            "host_context": {
                "page": {
                    "metadata": {
                        "wiii_connect": {
                            "provider_slug": "facebook",
                            "status": "connected",
                            "connection_count": 1,
                            "active_connection_count": 1,
                            "connection_state": "connected",
                        }
                    }
                }
            },
        }
    }

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_answer_with_fallback",
        new=fake_stream_direct_answer_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeWebSearchTool(), FakeFacebookPreviewTool()],
            push_event=push_event,
            query=(
                'Wiii đăng một bài Facebook: "Một ngày bình thường của Wiii: '
                'đang học COLREGs" rồi đăng lên trang cá nhân đi'
            ),
            state=state,
            forced_tool_choice="tool_web_search",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
            native_tool_messages=True,
        )

    assert "gửi yêu cầu đăng bài Facebook" in llm_response.content
    assert "chưa có nội dung" not in llm_response.content
    assert len(ainvoke_calls) == 1
    assert ainvoke_calls[0]["tool_choice"] == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    assert [tool.name for tool in ainvoke_calls[0]["tools"]] == [
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    ]
    assert tool_call_events[0]["name"] == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    assert tool_call_events[0]["args"]["provider_slug"] == "facebook"
    assert (
        tool_call_events[0]["args"]["message"]
        == "Một ngày bình thường của Wiii: đang học COLREGs"
    )
    assert any(event["type"] == "host_action" for event in pushed_events)


@pytest.mark.asyncio
async def test_wiii_connect_facebook_post_preflight_blocks_pending_connection() -> None:
    from app.engine.multi_agent.direct_wiii_connect_host_action_runtime import (
        preflight_requested_wiii_connect_facebook_post,
    )

    state: dict = {
        "context": {
            "host_context": {
                "page": {
                    "metadata": {
                        "wiii_connect": {
                            "provider_slug": "facebook",
                            "status": "not_connected",
                            "connection_count": 1,
                            "active_connection_count": 0,
                            "connection_state": "waiting",
                        }
                    }
                }
            }
        }
    }

    def build_assistant_message(content: str, **kwargs) -> dict:
        return {"content": content, "native_tool_messages": kwargs["native_tool_messages"]}

    response = await preflight_requested_wiii_connect_facebook_post(
        query="Wiii dang mot bai Facebook, bai nao cung duoc",
        state=state,
        native_tool_messages=True,
        build_assistant_message=build_assistant_message,
    )

    assert response is not None
    assert "chưa có account Facebook active" in response["content"]


@pytest.mark.asyncio
async def test_requested_document_host_action_shortcut_prefers_course_preview() -> None:
    course_tool = object()
    lesson_tool = object()
    pushed_events: list[dict] = []
    tool_call_events: list[dict] = []
    invoked: dict = {}
    lesson_checked = False
    state: dict = {"document_context": {"attachments": [{"id": "doc-1"}]}}

    course_shortcut = DocumentHostActionShortcut(
        tool_name="tool_preview_course_plan",
        tool_call_id="forced_doc_course_preview_0",
        thinking="Course preview only.",
        thinking_summary="Course preview",
        thinking_provenance="test_course_preview",
        response="Course preview sent.",
        failure_log_message="failed: %s",
    )
    lesson_shortcut = DocumentHostActionShortcut(
        tool_name="tool_preview_lesson_patch",
        tool_call_id="forced_doc_preview_0",
        thinking="Lesson preview only.",
        thinking_summary="Lesson preview",
        thinking_provenance="test_lesson_preview",
        response="Lesson preview sent.",
        failure_log_message="failed: %s",
    )

    async def push_event(event: dict) -> None:
        pushed_events.append(event)

    async def invoke_tool(tool, args, **kwargs):
        invoked.update({"tool": tool, "args": args, "kwargs": kwargs})
        return {"host_action": "preview-course", "approval_required": True}

    async def emit_host_action(**kwargs) -> None:
        pushed_events.append({"type": "host_action", "content": kwargs["result"]})

    def build_assistant_message(content: str, **kwargs) -> dict:
        return {"content": content, "native_tool_messages": kwargs["native_tool_messages"]}

    def should_request_lesson_preview(**kwargs) -> bool:
        nonlocal lesson_checked
        lesson_checked = True
        return True

    response = await execute_requested_document_host_action_shortcut(
        query="tạo cho mình bài học",
        state=state,
        tools=[course_tool, lesson_tool],
        tool_call_events=tool_call_events,
        push_event=push_event,
        native_tool_messages=True,
        runtime_context_base={"request_id": "req-1"},
        invoke_tool_with_runtime=invoke_tool,
        maybe_emit_host_action_event=emit_host_action,
        summarize_tool_result_for_stream=lambda name, result: "summary",
        should_request_course_preview=lambda **kwargs: True,
        find_course_host_action_tool=lambda tools: course_tool,
        build_course_params=lambda query, state: {
            "title": "Course",
            "source_references": [{"document_id": "doc-1"}],
        },
        course_shortcut=course_shortcut,
        should_request_lesson_preview=should_request_lesson_preview,
        find_lesson_host_action_tool=lambda tools: lesson_tool,
        build_lesson_params=lambda query, state: {"title": "Lesson"},
        lesson_shortcut=lesson_shortcut,
        build_assistant_message=build_assistant_message,
        uploaded_document_attachments_from_state=lambda state: [{"id": "doc-1"}],
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert response == {
        "content": "Course preview sent.",
        "native_tool_messages": True,
    }
    assert lesson_checked is False
    assert invoked["tool"] is course_tool
    assert invoked["kwargs"]["tool_name"] == "tool_preview_course_plan"
    assert invoked["args"]["source_references"] == [{"document_id": "doc-1"}]
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert [event["type"] for event in pushed_events] == [
        "tool_call",
        "tool_result",
        "host_action",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
    ]


@pytest.mark.asyncio
async def test_requested_document_host_action_shortcut_uses_lesson_preview() -> None:
    lesson_tool = object()
    invoked: dict = {}
    state: dict = {"document_context": {"attachments": [{"id": "doc-1"}]}}
    shortcut = DocumentHostActionShortcut(
        tool_name="tool_preview_lesson_patch",
        tool_call_id="forced_doc_preview_0",
        thinking="Lesson preview only.",
        thinking_summary="Lesson preview",
        thinking_provenance="test_lesson_preview",
        response="Lesson preview sent.",
        failure_log_message="failed: %s",
    )

    async def push_event(event: dict) -> None:
        return None

    async def invoke_tool(tool, args, **kwargs):
        invoked.update({"tool": tool, "args": args, "kwargs": kwargs})
        return {"host_action": "preview-lesson", "approval_required": True}

    async def emit_host_action(**kwargs) -> None:
        return None

    response = await execute_requested_document_host_action_shortcut(
        query="tạo cho mình bài học",
        state=state,
        tools=[lesson_tool],
        tool_call_events=[],
        push_event=push_event,
        native_tool_messages=False,
        runtime_context_base={"request_id": "req-2"},
        invoke_tool_with_runtime=invoke_tool,
        maybe_emit_host_action_event=emit_host_action,
        summarize_tool_result_for_stream=lambda name, result: "summary",
        should_request_course_preview=lambda **kwargs: False,
        find_course_host_action_tool=lambda tools: None,
        build_course_params=lambda query, state: {"title": "Course"},
        course_shortcut=shortcut,
        should_request_lesson_preview=lambda **kwargs: True,
        find_lesson_host_action_tool=lambda tools: lesson_tool,
        build_lesson_params=lambda query, state: {
            "title": "Lesson",
            "source_references": [{"document_id": "doc-1"}],
        },
        lesson_shortcut=shortcut,
        build_assistant_message=lambda content, **kwargs: {
            "content": content,
            "native_tool_messages": kwargs["native_tool_messages"],
        },
        uploaded_document_attachments_from_state=lambda state: [{"id": "doc-1"}],
        logger_obj=__import__("logging").getLogger(__name__),
    )

    assert response == {
        "content": "Lesson preview sent.",
        "native_tool_messages": False,
    }
    assert invoked["tool"] is lesson_tool
    assert invoked["kwargs"]["tool_name"] == "tool_preview_lesson_patch"
    assert invoked["args"]["source_references"] == [{"document_id": "doc-1"}]
