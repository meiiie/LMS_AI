import pytest

from app.engine.multi_agent.code_studio_node_final_state import (
    CodeStudioNodeFinalStateDependencies,
    CodeStudioNodeFinalStateRequest,
    apply_code_studio_node_final_state,
)


@pytest.mark.asyncio
async def test_apply_code_studio_node_final_state_builds_missing_thinking():
    state = {"tools_used": ["tool_create_visual_code"]}
    snapshots: list[tuple[str, str, str]] = []

    async def build_summary(query, _state, tool_names):
        assert query == "Tao mo phong con lac"
        assert tool_names == ["tool_create_visual_code"]
        return "Minh dang giu preview that."

    result = await apply_code_studio_node_final_state(
        request=CodeStudioNodeFinalStateRequest(
            state=state,
            response="Da tao preview.",
            query="Tao mo phong con lac",
        ),
        dependencies=CodeStudioNodeFinalStateDependencies(
            build_code_studio_reasoning_summary=build_summary,
            direct_tool_names=lambda tools: list(tools),
            resolve_visible_thinking_fn=(
                lambda _state, *, fallback, default_node: (
                    f"{default_node}: {fallback}"
                )
            ),
            record_thinking_snapshot_fn=(
                lambda _state, content, *, node, provenance: snapshots.append(
                    (node, provenance, content)
                )
            ),
        ),
    )

    assert result is state
    assert state["thinking_content"] == (
        "code_studio_agent: Minh dang giu preview that."
    )
    assert snapshots == [
        (
            "code_studio_agent",
            "final_snapshot",
            "code_studio_agent: Minh dang giu preview that.",
        )
    ]
    assert state["final_response"] == "Da tao preview."
    assert state["agent_outputs"] == {"code_studio_agent": "Da tao preview."}
    assert state["current_agent"] == "code_studio_agent"


@pytest.mark.asyncio
async def test_apply_code_studio_node_final_state_preserves_existing_thinking():
    state = {"thinking_content": "Existing public thinking."}
    summary_called = False
    snapshots: list[str] = []

    async def build_summary(*_args, **_kwargs):
        nonlocal summary_called
        summary_called = True
        return "Should not be used"

    await apply_code_studio_node_final_state(
        request=CodeStudioNodeFinalStateRequest(
            state=state,
            response="Clarify simulation.",
            query="mo phong di",
        ),
        dependencies=CodeStudioNodeFinalStateDependencies(
            build_code_studio_reasoning_summary=build_summary,
            direct_tool_names=lambda tools: list(tools),
            record_thinking_snapshot_fn=(
                lambda _state, content, **_kwargs: snapshots.append(content)
            ),
        ),
    )

    assert summary_called is False
    assert snapshots == ["Existing public thinking."]
    assert state["thinking_content"] == "Existing public thinking."
    assert state["final_response"] == "Clarify simulation."
