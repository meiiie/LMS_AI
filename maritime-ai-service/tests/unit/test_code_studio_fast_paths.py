from types import SimpleNamespace
import json

import pytest

from app.engine.multi_agent import code_studio_fast_paths
from app.engine.multi_agent.code_studio_fast_paths import (
    CodeStudioFastPathRecipe,
    CodeStudioFastPathResult,
    _COLREG_RULE15_FAST_PATH_HTML,
    _PENDULUM_FAST_PATH_HTML,
    _build_recipe,
    _contains_visual_payload_result,
)
from app.engine.multi_agent.tool_collection import _build_visual_tool_runtime_metadata
from app.engine.tools.runtime_context import ToolRuntimeContext, tool_runtime_scope
from app.engine.tools.visual_tools import parse_visual_payloads, tool_create_visual_code


def _create_payloads(query: str, code_html: str):
    metadata = _build_visual_tool_runtime_metadata({"context": {}}, query) or {}
    with tool_runtime_scope(ToolRuntimeContext(metadata=metadata)):
        result = tool_create_visual_code.invoke({
            "code_html": code_html,
            "title": "Fast path smoke",
        })
    return result, parse_visual_payloads(result)


def test_colreg_fast_path_html_satisfies_visual_payload_contract() -> None:
    result, payloads = _create_payloads(
        "Mô phỏng Quy tắc 15 COLREGs",
        _COLREG_RULE15_FAST_PATH_HTML,
    )

    assert _contains_visual_payload_result(result)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.type == "simulation"
    assert payload.renderer_kind == "app"
    assert payload.metadata["app_category"] == "simulation"
    assert "<canvas" in (payload.fallback_html or "").lower()
    assert "window.WiiiVisualBridge.reportResult" in (payload.fallback_html or "")


def test_pendulum_fast_path_html_satisfies_visual_payload_contract() -> None:
    result, payloads = _create_payloads(
        "Hãy mô phỏng vật lý con lắc có kéo thả chuột",
        _PENDULUM_FAST_PATH_HTML,
    )

    assert _contains_visual_payload_result(result)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.type == "simulation"
    assert payload.renderer_kind == "app"
    assert "<canvas" in (payload.fallback_html or "").lower()
    assert "requestAnimationFrame" in (payload.fallback_html or "")


def test_fast_path_recipe_contract_builds_tool_args() -> None:
    recipe = _build_recipe("simulate COLREG rule 15 crossing situation", {"context": {}})

    assert isinstance(recipe, CodeStudioFastPathRecipe)
    assert recipe.call_id_prefix == "fast_colreg15"
    assert recipe.tool_args() == {
        "code_html": _COLREG_RULE15_FAST_PATH_HTML,
        "title": "COLREGs Rule 15 Simulation",
    }


@pytest.mark.asyncio
async def test_recipe_fast_path_returns_typed_result(monkeypatch) -> None:
    invoked_args = {}

    async def fake_invoke_tool_with_runtime(*_args, **_kwargs):
        invoked_args.update(_args[1])
        return (
            '{"visual_session_id":"vs-fast","fallback_html":'
            '"<canvas>raw-code-token-123456</canvas>",'
            '"provider_payload":{"access_token":"raw-provider-token-123456"}}'
        )

    async def fake_maybe_emit_visual_event(**_kwargs):
        return ["vs-fast"], []

    async def fake_emit_visual_commit_events(**_kwargs):
        return None

    monkeypatch.setattr(
        code_studio_fast_paths,
        "invoke_tool_with_runtime",
        fake_invoke_tool_with_runtime,
    )
    monkeypatch.setattr(
        code_studio_fast_paths,
        "_maybe_emit_visual_event",
        fake_maybe_emit_visual_event,
    )
    monkeypatch.setattr(
        code_studio_fast_paths,
        "_emit_visual_commit_events",
        fake_emit_visual_commit_events,
    )

    pushed_events = []

    async def push_event(event):
        pushed_events.append(event)

    result = await code_studio_fast_paths.execute_code_studio_fast_path(
        state={"context": {}},
        query="simulate COLREG rule 15 crossing situation",
        tools=[SimpleNamespace(name="tool_create_visual_code")],
        push_event=push_event,
        runtime_context_base=None,
        derive_code_stream_session_id=lambda **_kwargs: "vs-test",
        sanitize_code_studio_response=lambda text, *_args: text,
    )

    assert isinstance(result, CodeStudioFastPathResult)
    assert result.fast_path == "fast_colreg15"
    assert result.tools_used == [{"name": "tool_create_visual_code"}]
    assert result.tool_call_events[0]["type"] == "call"
    assert result.tool_call_events[0]["args"]["code_html"]["redacted"] is True
    assert _COLREG_RULE15_FAST_PATH_HTML not in str(result.tool_call_events[0]["args"])
    public_result = json.loads(result.tool_call_events[1]["result"])
    assert public_result["fallback_html"]["redacted"] is True
    serialized_result = json.dumps(public_result, ensure_ascii=False)
    assert "provider_payload" not in serialized_result
    assert "access_token" not in serialized_result
    assert "raw-code-token" not in serialized_result
    assert "raw-provider-token" not in serialized_result
    assert invoked_args["code_html"] == _COLREG_RULE15_FAST_PATH_HTML
    tool_call_event = next(event for event in pushed_events if event["type"] == "tool_call")
    public_args = tool_call_event["content"]["args"]
    assert public_args["code_html"]["redacted"] is True
    assert _COLREG_RULE15_FAST_PATH_HTML not in str(public_args)


@pytest.mark.asyncio
async def test_recipe_fast_path_rejects_non_payload_tool_result(monkeypatch) -> None:
    async def fake_invoke_tool_with_runtime(*_args, **_kwargs):
        return "Quality score 4/10 - chua dat"

    monkeypatch.setattr(
        code_studio_fast_paths,
        "invoke_tool_with_runtime",
        fake_invoke_tool_with_runtime,
    )

    pushed_events = []

    async def push_event(event):
        pushed_events.append(event)

    result = await code_studio_fast_paths.execute_code_studio_fast_path(
        state={"context": {}},
        query="Mô phỏng Quy tắc 15 COLREGs",
        tools=[SimpleNamespace(name="tool_create_visual_code")],
        push_event=push_event,
        runtime_context_base=None,
        derive_code_stream_session_id=lambda **_kwargs: "vs-test",
        sanitize_code_studio_response=lambda text, *_args: text,
    )

    assert result is None
    assert pushed_events == []
