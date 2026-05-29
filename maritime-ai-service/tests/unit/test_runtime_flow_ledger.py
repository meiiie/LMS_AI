from __future__ import annotations

import json
from types import SimpleNamespace

from app.engine.multi_agent.runtime_flow_ledger import RuntimeFlowLedger


def test_runtime_flow_ledger_records_host_action_result_without_raw_payload() -> None:
    ledger = RuntimeFlowLedger(request_id="req-host-result")

    ledger.record_event(
        SimpleNamespace(
            type="host_action_result",
            content={
                "action": "wiii_connect.facebook_post.direct_apply",
                "status": "action_completed",
                "success": True,
                "approval_token": "raw-approval-token",
                "data": {
                    "provider_post_id": "safe-post-id",
                    "access_token": "raw-provider-token",
                },
            },
        )
    )

    payload = ledger.to_payload()

    assert "wiii_connect.facebook_post.direct_apply" in payload["tools"]["observed"]
    assert "host_action" not in payload["tools"]["suppressed"]
    assert payload["stream"]["event_counts"]["host_action_result"] == 1
    assert payload["host_actions"]["apply_attempted"] is True
    assert payload["host_actions"]["result_received"] is True
    assert payload["host_actions"]["result_success"] is True
    assert payload["host_actions"]["result_statuses"] == ["action_completed"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "raw-approval-token" not in serialized
    assert "raw-provider-token" not in serialized
