import pytest
from unittest.mock import AsyncMock, patch

from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent import direct_execution


class _PinnedNativeLLM:
    _wiii_native_route = True
    _wiii_provider_name = "nvidia"
    _wiii_model_name = "nvidia/nemotron-3-ultra-550b-a55b"
    _wiii_tier_key = "light"

    async def ainvoke(self, *_args, **_kwargs):  # pragma: no cover - must not be used
        raise AssertionError("pinned native fallback must not call legacy ainvoke")


async def _push_event(_event):
    return None


@pytest.mark.asyncio
async def test_pinned_native_no_response_does_not_fallback_to_pooled_default_model():
    state = {
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
    }

    with patch.object(
        direct_execution,
        "_stream_openai_compatible_answer_with_route",
        new=AsyncMock(return_value=(None, False)),
    ) as stream_route, patch(
        "app.engine.llm_pool.LLMPool.resolve_runtime_route",
    ) as resolve_route:
        with pytest.raises(ProviderUnavailableError):
            await direct_execution._stream_answer_with_fallback(
                _PinnedNativeLLM(),
                messages=[],
                push_event=_push_event,
                provider="nvidia",
                resolved_provider="nvidia",
                failover_mode="pinned",
                state=state,
            )

    stream_route.assert_awaited_once()
    resolve_route.assert_not_called()
    assert state["_execution_provider"] == "nvidia"
    assert state["_execution_model"] == "nvidia/nemotron-3-ultra-550b-a55b"
