import json
from types import SimpleNamespace

import pytest

from app.engine.multi_agent.code_studio_scaffold_fallback_policy import (
    CodeStudioScaffoldFallbackIntent,
    resolve_code_studio_scaffold_fallback,
)
from app.engine.multi_agent import code_studio_tool_rounds


def _visual_decision(**overrides):
    data = {
        "mode": "app",
        "force_tool": True,
        "presentation_intent": "code_studio_app",
        "preferred_tool": "tool_create_visual_code",
        "studio_lane": "app",
        "artifact_kind": "html_app",
        "visual_type": "simulation",
        "app_category": "simulation",
        "quality_profile": "premium",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_suppresses_generic_simulation_scaffold_fallback() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo mô phỏng hảo hán đối ẩm",
        reason="llm_prose_no_tool_call",
        resolve_visual_intent_fn=lambda _query: _visual_decision(),
        build_caption_fn=lambda _query: "caption should not be used",
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "app_requires_tool_generated_preview"
    assert decision.response_type == "code_studio_scaffold_suppressed"
    assert "template chung chung" in decision.response
    assert decision.app_category == "simulation"
    assert decision.metric_labels()["app_category"] == "simulation"
    assert decision.metric_labels()["reason"] == "llm_prose_no_tool_call"


def test_suppresses_non_code_studio_visual_lane() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Vẽ biểu đồ giá dầu hôm nay",
        reason="stream_empty",
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            mode="inline_html",
            force_tool=True,
            presentation_intent="chart_runtime",
            preferred_tool="tool_generate_visual",
            studio_lane=None,
            visual_type="chart",
        ),
        build_caption_fn=lambda _query: "caption should not be used",
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "not_code_studio_tool_contract"
    assert decision.presentation_intent == "chart_runtime"
    assert decision.preferred_tool == "tool_generate_visual"


def test_suppresses_plain_text_misroute_without_sanitizing_to_app() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Chào Wiii",
        reason="node_outer_RuntimeError",
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            mode="text",
            force_tool=False,
            presentation_intent="text",
            preferred_tool=None,
            studio_lane=None,
            visual_type=None,
        ),
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "not_code_studio_tool_contract"
    assert decision.presentation_intent == "text"
    assert decision.preferred_tool == "none"
    assert decision.studio_lane == "none"
    assert decision.visual_type == "none"


def test_fallback_intent_contract_does_not_invent_missing_visual_metadata() -> None:
    intent = CodeStudioScaffoldFallbackIntent.from_visual_decision(
        _visual_decision(
            force_tool=False,
            preferred_tool=None,
            studio_lane=None,
            visual_type=None,
            app_category=None,
            quality_profile=None,
        )
    )

    assert intent.is_code_studio_tool_contract is False
    assert intent.decision_fields() == {
        "presentation_intent": "code_studio_app",
        "preferred_tool": "none",
        "studio_lane": "none",
        "artifact_kind": "html_app",
        "visual_type": "none",
        "app_category": "none",
        "quality_profile": "standard",
    }


def test_allows_artifact_scaffold_fallback_with_contract_metadata() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo một mini app HTML để nhúng LMS",
        reason="ainvoke_exception",
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            presentation_intent="artifact",
            studio_lane="artifact",
            visual_type=None,
            quality_profile="premium",
        ),
        build_caption_fn=lambda _query: "artifact caption",
        detect_kind_fn=lambda _query: "default",
    )

    assert decision.engage_scaffold is True
    assert decision.response == "artifact caption"
    assert decision.policy_reason == "artifact_contract_allows_scaffold"
    assert decision.response_type == "code_studio_contract_scaffold_fallback"
    assert decision.presentation_intent == "artifact"
    assert decision.studio_lane == "artifact"
    assert decision.metric_labels()["kind"] == "default"


def test_suppresses_artifact_scaffold_when_callsite_cannot_deliver_preview() -> None:
    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo một mini app HTML để nhúng LMS",
        reason="node_outer_RuntimeError",
        allow_scaffold_delivery=False,
        resolve_visual_intent_fn=lambda _query: _visual_decision(
            presentation_intent="artifact",
            studio_lane="artifact",
            visual_type=None,
            quality_profile="premium",
        ),
        build_caption_fn=lambda _query: "caption should not be shown",
        detect_kind_fn=lambda _query: "default",
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "scaffold_delivery_unavailable"
    assert decision.response_type == "code_studio_scaffold_suppressed"
    assert decision.presentation_intent == "artifact"
    assert decision.studio_lane == "artifact"
    assert "preview thật" in decision.response
    assert "caption should not be shown" not in decision.response


def test_resolution_failure_suppresses_scaffold() -> None:
    def broken_resolver(_query: str):
        raise RuntimeError("resolver unavailable")

    decision = resolve_code_studio_scaffold_fallback(
        query="Tạo mô phỏng bất kỳ",
        reason="node_outer_RuntimeError",
        resolve_visual_intent_fn=broken_resolver,
    )

    assert decision.engage_scaffold is False
    assert decision.policy_reason == "visual_contract_resolution_failed"
    assert decision.presentation_intent == "unknown"


def test_manual_scaffold_helper_does_not_inject_tool_call_for_simulation() -> None:
    manual_tc, visible_caption, decision = code_studio_tool_rounds._build_scaffold_manual_tool_call(
        "Hay mo phong vat ly con lac co the keo tha",
        reason="stream_empty",
        state={},
    )

    assert manual_tc is None
    assert decision.engage_scaffold is False
    assert decision.policy_reason == "app_requires_tool_generated_preview"
    assert "template chung chung" in visible_caption


def test_tool_round_outcome_safe_stops_simulation_scaffold() -> None:
    outcome = code_studio_tool_rounds.resolve_code_studio_scaffold_tool_round_outcome(
        "Hay mo phong vat ly con lac co the keo tha",
        trigger=code_studio_tool_rounds.CodeStudioToolRoundTrigger.STREAM_EMPTY,
        state={},
    )

    assert (
        outcome.kind
        == code_studio_tool_rounds.CodeStudioToolRoundOutcomeKind.SAFE_STOP_RESPONSE
    )
    assert outcome.first_tool_call is None
    assert outcome.trigger == "stream_empty"
    assert outcome.scaffold_decision is not None
    assert (
        outcome.scaffold_decision.policy_reason
        == "app_requires_tool_generated_preview"
    )
    assert outcome.scaffold_decision.metric_labels()["reason"] == "stream_empty"


def test_manual_scaffold_helper_keeps_artifact_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        code_studio_tool_rounds,
        "build_code_studio_scaffold",
        lambda _query: "<html><body>artifact scaffold</body></html>",
    )

    manual_tc, visible_caption, decision = code_studio_tool_rounds._build_scaffold_manual_tool_call(
        "Tao mot mini app HTML de nhung vao LMS",
        reason="ainvoke_exception",
        state={},
    )

    assert decision.engage_scaffold is True
    assert manual_tc is not None
    assert manual_tc["name"] == "tool_create_visual_code"
    assert manual_tc["args"]["code_html"] == "<html><body>artifact scaffold</body></html>"
    assert visible_caption


def test_tool_round_outcome_keeps_artifact_scaffold_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        code_studio_tool_rounds,
        "build_code_studio_scaffold",
        lambda _query: "<html><body>artifact scaffold</body></html>",
    )

    outcome = code_studio_tool_rounds.resolve_code_studio_scaffold_tool_round_outcome(
        "Tao mot mini app HTML de nhung vao LMS",
        trigger=code_studio_tool_rounds.CodeStudioToolRoundTrigger.AINVOKE_EXCEPTION,
        state={},
    )

    assert (
        outcome.kind
        == code_studio_tool_rounds.CodeStudioToolRoundOutcomeKind.SCAFFOLD_TOOL_CALL
    )
    assert outcome.first_tool_call is not None
    assert outcome.first_tool_call["name"] == "tool_create_visual_code"
    assert (
        outcome.first_tool_call["args"]["code_html"]
        == "<html><body>artifact scaffold</body></html>"
    )
    assert outcome.trigger == "ainvoke_exception"
    assert outcome.scaffold_decision is not None
    assert (
        outcome.scaffold_decision.policy_reason
        == "artifact_contract_allows_scaffold"
    )


def test_streamed_code_html_outcome_is_not_scaffold_fallback() -> None:
    outcome = code_studio_tool_rounds._build_streamed_code_html_tool_round_outcome(
        "Build a tiny stopwatch app",
        "<html><body>stopwatch</body></html>",
        content="provider caption",
    )

    assert (
        outcome.kind
        == code_studio_tool_rounds.CodeStudioToolRoundOutcomeKind.STREAMED_CODE_HTML_TOOL_CALL
    )
    assert outcome.content == "provider caption"
    assert outcome.scaffold_decision is None
    assert outcome.trigger == "streamed_code_html"
    assert outcome.first_tool_call is not None
    assert outcome.first_tool_call["name"] == "tool_create_visual_code"
    assert (
        outcome.first_tool_call["args"]["code_html"]
        == "<html><body>stopwatch</body></html>"
    )


def test_code_studio_tool_policy_denies_stale_tool_call() -> None:
    state = {
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "code_studio",
            "reason": "code_studio_tool_setup",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "allowed_tool_names": ["tool_create_visual_code"],
            "allowed_tool_prefixes": [],
            "forbidden_tool_names": [],
            "forbidden_tool_prefixes": [],
            "candidate_tool_names": ["tool_create_visual_code", "tool_web_search"],
            "visible_tool_names": ["tool_create_visual_code"],
            "connection_status": {},
            "approval_required_tool_names": [],
        }
    }

    denial = code_studio_tool_rounds._code_studio_tool_policy_denial(
        state,
        "tool_web_search",
    )

    assert denial is not None
    decision, message = denial
    assert decision.allowed is False
    assert decision.path == "code_studio"
    assert decision.reason == "surface_scope_not_allowed"
    assert "Tool bị chặn bởi chính sách" in message


def test_code_studio_tool_policy_allows_visible_tool_call() -> None:
    state = {
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "code_studio",
            "reason": "code_studio_tool_setup",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "allowed_tool_names": ["tool_create_visual_code"],
            "allowed_tool_prefixes": [],
            "forbidden_tool_names": [],
            "forbidden_tool_prefixes": [],
            "candidate_tool_names": ["tool_create_visual_code"],
            "visible_tool_names": ["tool_create_visual_code"],
            "connection_status": {},
            "approval_required_tool_names": [],
        }
    }

    assert (
        code_studio_tool_rounds._code_studio_tool_policy_denial(
            state,
            "tool_create_visual_code",
        )
        is None
    )


@pytest.mark.asyncio
async def test_code_studio_tool_round_denies_out_of_policy_call_without_invoking() -> None:
    from app.engine.messages import Message

    emitted: list[dict] = []
    invoke_called = False
    ainvoke_calls = 0
    state = {
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "code_studio",
            "reason": "code_studio_tool_setup",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "allowed_tool_names": ["tool_create_visual_code"],
            "allowed_tool_prefixes": [],
            "forbidden_tool_names": [],
            "forbidden_tool_prefixes": [],
            "candidate_tool_names": ["tool_create_visual_code", "tool_web_search"],
            "visible_tool_names": ["tool_create_visual_code"],
            "connection_status": {},
            "approval_required_tool_names": [],
        }
    }

    async def push_event(event):
        emitted.append(event)

    async def ainvoke_with_fallback(*_args, **_kwargs):
        nonlocal ainvoke_calls
        ainvoke_calls += 1
        if ainvoke_calls == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "id": "tc-stale",
                        "name": "tool_web_search",
                        "args": {
                            "query": "should not run",
                            "connection_ref": "wcn_secret_connection",
                            "code_html": "<html>private code</html>",
                        },
                    }
                ],
            )
        return Message(role="assistant", content="done")

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        nonlocal invoke_called
        invoke_called = True
        raise AssertionError("out-of-policy Code Studio tool must not invoke")

    async def render_reasoning_fast(**_kwargs):
        return SimpleNamespace(
            label="policy",
            summary="policy",
            phase="ground",
            action_text="policy",
        )

    async def stream_code_studio_wait_heartbeats(*_args, **_kwargs):
        return None

    async def noop_async(*_args, **_kwargs):
        return None

    llm_response, _messages, tool_events = await code_studio_tool_rounds.execute_code_studio_tool_rounds_impl(
        SimpleNamespace(),
        SimpleNamespace(),
        [],
        [SimpleNamespace(name="tool_create_visual_code")],
        push_event,
        query="build a simulation",
        state=state,
        should_enable_real_code_streaming=lambda *_args, **_kwargs: False,
        derive_code_stream_session_id=lambda **_kwargs: "code-session",
        ainvoke_with_fallback=ainvoke_with_fallback,
        build_code_studio_progress_messages=lambda _query, _state: ["planning"],
        render_reasoning_fast=render_reasoning_fast,
        infer_code_studio_reasoning_cue=lambda _query, _tool_names: "policy",
        thinking_start_label=lambda label: label,
        code_studio_delta_chunks=lambda _beat: [],
        stream_code_studio_wait_heartbeats=stream_code_studio_wait_heartbeats,
        format_code_studio_progress_message=lambda msg, _elapsed: msg,
        build_code_studio_retry_status=lambda *_args, **_kwargs: "retry",
        build_code_studio_missing_tool_response=lambda *_args, **_kwargs: "missing",
        requires_code_studio_visual_delivery=lambda _query, _tools: False,
        collect_active_visual_session_ids=lambda _state: [],
        get_tool_by_name=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("get_tool_by_name should not run for denied tool")
        ),
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        summarize_tool_result_for_stream=lambda _name, value: value,
        maybe_emit_visual_event=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("visual event should not run for denied tool")
        ),
        emit_visual_commit_events=noop_async,
        build_code_studio_tool_reflection=lambda *_args, **_kwargs: None,
        is_terminal_code_studio_tool_error=lambda _name, _result: False,
        build_code_studio_terminal_failure_response=lambda *_args, **_kwargs: "terminal",
        build_code_studio_synthesis_observations=lambda _events: [],
        inject_widget_blocks_from_tool_results=lambda response, *_args, **_kwargs: response,
        push_status_only_progress=noop_async,
        settings_obj=SimpleNamespace(
            code_studio_llm_hard_timeout_seconds=5,
            code_studio_post_tool_synthesis_timeout_seconds=5,
            enable_structured_visuals=True,
        ),
    )

    assert invoke_called is False
    assert getattr(llm_response, "content", "") == "done"
    assert tool_events[0]["policy"]["allowed"] is False
    assert tool_events[0]["policy"]["path"] == "code_studio"
    assert tool_events[0]["args"]["connection_ref"] == "[redacted]"
    assert tool_events[0]["args"]["code_html"]["redacted"] is True
    assert "Tool bị chặn bởi chính sách" in tool_events[1]["result"]
    tool_call_event = next(event for event in emitted if event["type"] == "tool_call")
    tool_result_event = next(event for event in emitted if event["type"] == "tool_result")
    assert tool_call_event["content"]["policy"]["allowed"] is False
    assert tool_call_event["content"]["args"] == tool_events[0]["args"]
    assert "wcn_secret_connection" not in json.dumps(emitted, ensure_ascii=False)
    assert "<html>private code</html>" not in json.dumps(tool_events, ensure_ascii=False)
    assert tool_result_event["content"]["name"] == "tool_web_search"
