import json

from app.engine.multi_agent.direct_tool_response_finalization_runtime import (
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
