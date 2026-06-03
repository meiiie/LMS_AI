import json
from types import SimpleNamespace

import pytest

from app.engine.multi_agent.direct_tool_response_finalization_runtime import (
    finalize_direct_tool_response,
    facebook_direct_apply_final_answer,
)
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
)


def test_facebook_direct_apply_final_answer_uses_completed_host_result() -> None:
    answer = facebook_direct_apply_final_answer(
        [
            {
                "type": "result",
                "name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
                "result": json.dumps(
                    {
                        "status": "action_completed",
                        "success": True,
                        "summary": "Đã đăng bài lên Facebook: Wiii.",
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    assert answer == "Đã đăng bài lên Facebook: Wiii."


def test_facebook_direct_apply_final_answer_uses_failed_host_result() -> None:
    answer = facebook_direct_apply_final_answer(
        [
            {
                "type": "result",
                "name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
                "result": json.dumps(
                    {
                        "status": "action_failed",
                        "success": False,
                        "error": "facebook_connection_missing",
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    assert answer == "Facebook chưa đăng được: facebook_connection_missing"


def test_facebook_direct_apply_final_answer_has_utf8_default_completion_copy() -> None:
    answer = facebook_direct_apply_final_answer(
        [
            {
                "type": "result",
                "name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
                "result": json.dumps(
                    {
                        "status": "action_completed",
                        "success": True,
                        "provider_slug": "facebook",
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    assert answer == "Đã đăng bài lên Facebook qua Wiii Connect."


def test_external_app_action_final_answer_uses_generic_wiii_connect_result() -> None:
    from app.engine.multi_agent.external_app_action_runtime import (
        external_app_action_final_answer,
    )

    answer = external_app_action_final_answer(
        [
            {
                "type": "result",
                "name": "tool_wiii_connect_delegate_to_integration",
                "result": json.dumps(
                    {
                        "version": "wiii_connect_integration_delegate_tool.v1",
                        "status": "action_completed",
                        "provider_slug": "gmail",
                        "summary": "Đã đọc danh sách email mới nhất.",
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    assert answer == "Đã đọc danh sách email mới nhất."


def test_external_app_action_final_answer_ignores_catalog_only_result() -> None:
    from app.engine.multi_agent.external_app_action_runtime import (
        external_app_action_final_answer,
    )

    answer = external_app_action_final_answer(
        [
            {
                "type": "result",
                "name": "tool_wiii_connect_list_actions",
                "result": json.dumps(
                    {
                        "version": "wiii_connect_generic_direct_tool.v1",
                        "status": "action_completed",
                        "success": True,
                        "summary": "Action catalog loaded.",
                        "provider_slug": "gmail",
                        "data": {
                            "action_catalog": {
                                "provider_slug": "gmail",
                                "actions": [{"slug": "GMAIL_FETCH_EMAILS"}],
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    assert answer == ""


@pytest.mark.asyncio
async def test_finalize_direct_tool_response_records_action_result_answer_source() -> None:
    state: dict = {}
    answer = "Posted from Wiii Connect."
    tool_call_events = [
        {
            "type": "result",
            "name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
            "result": json.dumps(
                {
                    "version": "wiii_connect_facebook_direct_tool.v1",
                    "status": "action_completed",
                    "success": True,
                    "summary": answer,
                    "provider_slug": "facebook",
                    "action": "wiii_connect.facebook_post.direct_apply",
                },
                ensure_ascii=False,
            ),
        }
    ]

    result = await finalize_direct_tool_response(
        llm_response=SimpleNamespace(content="I still need content.", tool_calls=[]),
        messages=[],
        tools=[],
        tool_call_events=tool_call_events,
        query="post to facebook",
        state=state,
        push_event=lambda _event: None,
        native_tool_messages=False,
        llm_base=None,
        llm_auto=None,
        llm_with_tools=None,
        provider=None,
        resolved_provider=None,
        request_failover_mode="auto",
        allowed_fallback_providers=None,
        ainvoke_with_fallback=None,
        stream_direct_wait_heartbeats=None,
        remember_execution_target=lambda *_args, **_kwargs: (None, None),
        runtime_tier_for=lambda *_args, **_kwargs: "default",
        inject_widget_blocks_from_tool_results=lambda response, *_args, **_kwargs: response,
        structured_visuals_enabled=False,
    )

    assert result.llm_response.content == answer
    assert state["_final_answer_trace"] == {
        "version": "final_answer_trace.v1",
        "source": "wiii_connect_action_result",
        "reason": "external_app_action_payload",
        "status": "resolved",
        "answer_present": True,
    }
