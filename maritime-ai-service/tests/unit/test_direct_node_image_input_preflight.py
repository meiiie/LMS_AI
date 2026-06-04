import pytest

from app.engine.multi_agent.direct_node_pre_llm_stage_contract import (
    DirectImageInputPreflightDependencies,
    DirectImageInputPreflightRequest,
)


@pytest.mark.asyncio
async def test_image_preflight_clears_images_when_document_context_owns_turn():
    from app.engine.multi_agent.direct_node_image_input_preflight import (
        execute_direct_node_image_input_preflight,
    )

    ctx = {
        "image_input_error": "vision_disabled",
        "images": [{"data": "ignored"}],
    }

    result = await execute_direct_node_image_input_preflight(
        request=DirectImageInputPreflightRequest(
            query="tao bai giang tu file vua upload",
            state={},
            ctx=ctx,
            response_present=False,
            has_uploaded_document_context=True,
        ),
        dependencies=DirectImageInputPreflightDependencies(
            record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        ),
    )

    assert result is None
    assert ctx["images"] == []


@pytest.mark.asyncio
async def test_image_preflight_returns_vision_unavailable_without_llm():
    from app.engine.multi_agent.direct_node_image_input_preflight import (
        execute_direct_node_image_input_preflight,
    )

    snapshots = []
    state = {}

    result = await execute_direct_node_image_input_preflight(
        request=DirectImageInputPreflightRequest(
            query="Nhin anh nay va mo ta giup minh",
            state=state,
            ctx={"image_input_error": "vision_disabled"},
            response_present=False,
            has_uploaded_document_context=False,
        ),
        dependencies=DirectImageInputPreflightDependencies(
            record_thinking_snapshot_fn=lambda *args, **kwargs: snapshots.append(
                (args, kwargs)
            ),
        ),
    )

    assert result is not None
    assert result.response_type == "image_input_unavailable"
    assert "vision" in result.response.lower()
    assert state["thinking_content"]
    assert snapshots[0][1]["provenance"] == "deterministic_image_input_unavailable"


@pytest.mark.asyncio
async def test_image_preflight_analyzes_base64_images_before_llm(monkeypatch):
    from app.engine.multi_agent import direct_node_image_input_preflight as module

    async def fake_build_image_input_answer(query, images):
        assert query == "Nhin anh nay"
        assert images == [{"type": "base64", "data": "abc"}]
        return "Anh co mot vung chu thich mau xanh."

    monkeypatch.setattr(module, "_build_image_input_answer", fake_build_image_input_answer)

    state = {}
    result = await module.execute_direct_node_image_input_preflight(
        request=DirectImageInputPreflightRequest(
            query="Nhin anh nay",
            state=state,
            ctx={"images": [{"type": "base64", "data": "abc"}]},
            response_present=False,
            has_uploaded_document_context=False,
        ),
        dependencies=DirectImageInputPreflightDependencies(
            record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        ),
    )

    assert result is not None
    assert result.response == "Anh co mot vung chu thich mau xanh."
    assert result.response_type == "image_input"
    assert state["thinking_content"]


@pytest.mark.asyncio
async def test_image_preflight_does_not_steal_facebook_post_with_image():
    from app.engine.multi_agent.direct_node_image_input_preflight import (
        execute_direct_node_image_input_preflight,
    )

    state = {}
    result = await execute_direct_node_image_input_preflight(
        request=DirectImageInputPreflightRequest(
            query="Wiii đăng bài này lên Facebook giúp mình",
            state=state,
            ctx={"images": [{"type": "base64", "data": "abc"}]},
            response_present=False,
            has_uploaded_document_context=False,
        ),
        dependencies=DirectImageInputPreflightDependencies(
            record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        ),
    )

    assert result is None
    assert "thinking_content" not in state
