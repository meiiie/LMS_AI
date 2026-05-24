from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.multi_agent.code_studio_node_preflight import (
    CodeStudioNodePreflightDependencies,
    CodeStudioNodePreflightRequest,
    execute_code_studio_node_preflight,
    resolve_code_studio_domain_name_vi,
)


def _dependencies(**overrides):
    values = {
        "looks_like_ambiguous_simulation_request": lambda _query, _state: False,
        "ground_simulation_query_from_visual_context": lambda _query, _state: "",
        "last_inline_visual_title": lambda _state: "Visual hiện tại",
        "build_ambiguous_simulation_clarifier": lambda _state: "Bạn muốn mô phỏng gì?",
    }
    values.update(overrides)
    return CodeStudioNodePreflightDependencies(**values)


def test_code_studio_domain_name_prefers_domain_config() -> None:
    assert (
        resolve_code_studio_domain_name_vi(
            state={"domain_config": {"name_vi": "Hàng hải"}},
            default_domain="maritime",
        )
        == "Hàng hải"
    )


@pytest.mark.asyncio
async def test_code_studio_preflight_grounds_ambiguous_simulation_followup() -> None:
    pushed: list[dict] = []
    state = {"domain_id": "maritime"}

    async def push_event(event: dict) -> None:
        pushed.append(event)

    result = await execute_code_studio_node_preflight(
        request=CodeStudioNodePreflightRequest(
            query="mô phỏng tiếp đi",
            state=state,
            default_domain="maritime",
            push_event=push_event,
            tracer=MagicMock(),
        ),
        dependencies=_dependencies(
            looks_like_ambiguous_simulation_request=lambda _query, _state: True,
            ground_simulation_query_from_visual_context=(
                lambda _query, _state: "mô phỏng dao động con lắc"
            ),
            last_inline_visual_title=lambda _state: "Con lắc đơn",
        ),
    )

    assert result.effective_query == "mô phỏng dao động con lắc"
    assert result.response == ""
    assert result.domain_name_vi == "Hang hai"
    assert state["thinking_content"].startswith("Mình đang bám theo visual")
    assert pushed == [
        {
            "type": "status",
            "content": "Mình đang nối mô phỏng vào chủ đề hiện tại: `Con lắc đơn`...",
            "step": "code_generation",
            "node": "code_studio_agent",
            "details": {"visibility": "status_only"},
        }
    ]


@pytest.mark.asyncio
async def test_code_studio_preflight_clarifies_ambiguous_simulation_without_context() -> None:
    tracer = MagicMock()

    result = await execute_code_studio_node_preflight(
        request=CodeStudioNodePreflightRequest(
            query="mô phỏng đi",
            state={},
            default_domain="traffic_law",
            push_event=lambda _event: SimpleNamespace(),
            tracer=tracer,
        ),
        dependencies=_dependencies(
            looks_like_ambiguous_simulation_request=lambda _query, _state: True,
            build_ambiguous_simulation_clarifier=lambda _state: (
                "Cậu muốn mô phỏng hiện tượng nào?"
            ),
        ),
    )

    assert result.has_response is True
    assert result.response == "Cậu muốn mô phỏng hiện tượng nào?"
    assert result.effective_query == "mô phỏng đi"
    assert result.domain_name_vi == "Luat Giao thong"
    tracer.end_step.assert_called_once()
    assert tracer.end_step.call_args.kwargs["details"] == {
        "response_type": "clarify",
        "reason": "ambiguous_simulation_request",
    }
