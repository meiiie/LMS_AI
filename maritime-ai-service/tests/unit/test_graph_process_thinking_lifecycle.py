from app.engine.multi_agent.graph_process import _build_process_result_payload


class _TrackerStub:
    def summary(self):
        return {
            "total_calls": 2,
            "total_input_tokens": 100,
            "total_output_tokens": 40,
            "total_tokens": 140,
            "estimated_cost_usd": 0.01,
            "duration_ms": 42.5,
            "access_token": "raw-usage-token",
        }


def test_build_process_result_payload_includes_thinking_lifecycle():
    result = {
        "final_response": "Answer.",
        "sources": [],
        "tools_used": [],
        "grader_score": 8.5,
        "agent_outputs": {},
        "current_agent": "direct",
        "next_agent": "direct",
        "thinking": "Public thinking.",
        "thinking_content": "Public thinking.",
        "routing_metadata": {"final_agent": "direct"},
    }

    payload = _build_process_result_payload(
        result=result,
        trace_id="trace-1",
        trace_summary={},
        tracker=None,
        resolve_public_thinking_content=lambda state, fallback="": (
            state.get("thinking_content") or fallback
        ),
    )

    lifecycle = payload.get("thinking_lifecycle")
    assert isinstance(lifecycle, dict)
    assert lifecycle["final_text"] == "Public thinking."
    assert payload["thinking_content"] == "Public thinking."


def test_build_process_result_payload_uses_public_thinking_boundary():
    result = {
        "final_response": "Done",
        "thinking": "private native thinking access_token=raw-private-thinking-token",
        "thinking_content": "Public thinking summary.",
        "routing_metadata": {"final_agent": "direct"},
    }

    payload = _build_process_result_payload(
        result=result,
        trace_id="trace-private-thinking",
        trace_summary={},
        tracker=None,
        resolve_public_thinking_content=lambda state, fallback="": (
            state.get("thinking_content") or fallback
        ),
    )

    serialized = str(payload)

    assert payload["thinking"] == "Public thinking summary."
    assert payload["thinking_content"] == "Public thinking summary."
    assert payload["thinking_lifecycle"]["final_text"] == "Public thinking summary."
    assert "private native thinking" not in serialized
    assert "raw-private-thinking-token" not in serialized


def test_build_process_result_payload_sanitizes_public_result_surfaces():
    result = {
        "final_response": "Posted. Bearer raw-response-token-12345678",
        "sources": [
            {
                "title": "Doc",
                "content": "safe",
                "provider_payload": {"access_token": "raw-source-token"},
            }
        ],
        "tools_used": [
            {
                "name": "external_tool",
                "args": {
                    "access_token": "raw-tool-token",
                    "query": "Bearer raw-query-token-12345678",
                },
            }
        ],
        "agent_outputs": {
            "direct": {
                "provider_payload": {"id": "raw-provider"},
                "message": "Bearer raw-agent-token-12345678",
            }
        },
        "error": "Failed access_token=raw-error-token",
        "thinking_content": "Public thinking.",
        "routing_metadata": {
            "final_agent": "direct",
            "connection_ref": "wcn_raw_connection",
            "safe": "ok",
        },
        "evidence_images": [{"image_base64": "raw-image-data", "label": "screen"}],
        "_llm_failover_events": [
            {"reason_label": "Bearer raw-failover-token-12345678"}
        ],
    }

    payload = _build_process_result_payload(
        result=result,
        trace_id="trace-safe-payload",
        trace_summary={"span_count": 1, "access_token": "raw-trace-token"},
        tracker=_TrackerStub(),
        resolve_public_thinking_content=lambda state, fallback="": (
            state.get("thinking_content") or fallback
        ),
    )

    serialized = str(payload)

    assert payload["response"] == "Posted. Bearer <redacted-secret>"
    assert payload["routing_metadata"]["safe"] == "ok"
    assert payload["token_usage"]["total_tokens"] == 140
    assert "total_input_tokens" in payload["token_usage"]
    assert "provider_payload" not in serialized
    assert "access_token" not in serialized
    assert "connection_ref" not in serialized
    assert "image_base64" not in serialized
    assert "raw-response-token" not in serialized
    assert "raw-tool-token" not in serialized
    assert "raw-query-token" not in serialized
    assert "raw-agent-token" not in serialized
    assert "raw-error-token" not in serialized
    assert "raw-image-data" not in serialized
    assert "raw-failover-token" not in serialized
    assert "raw-trace-token" not in serialized
