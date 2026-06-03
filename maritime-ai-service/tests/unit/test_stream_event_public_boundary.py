import json

import pytest

from app.engine.multi_agent.stream_utils import (
    create_artifact_event,
    create_browser_screenshot_event,
    create_code_complete_event,
    create_code_delta_event,
    create_host_action_event,
    create_pointy_action_event,
    create_preview_event,
    create_visual_open_event,
)


def _serialized(event) -> str:
    return json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)


@pytest.mark.asyncio
async def test_preview_event_sanitizes_public_metadata_and_text():
    event = await create_preview_event(
        preview_type="web",
        preview_id="pv_1",
        title="Bearer raw-preview-title-token-12345678",
        snippet="access_token=raw-preview-snippet-token",
        url="https://example.com?token=raw-preview-url-token",
        metadata={
            "source": "search",
            "access_token": "raw-preview-metadata-token",
            "provider_payload": {"id": "raw-provider"},
        },
    )

    payload = _serialized(event)

    assert event.content["metadata"]["source"] == "search"
    assert "provider_payload" not in payload
    assert "access_token" not in payload
    assert "raw-preview-title-token" not in payload
    assert "raw-preview-snippet-token" not in payload
    assert "raw-preview-url-token" not in payload
    assert "raw-preview-metadata-token" not in payload


@pytest.mark.asyncio
async def test_artifact_and_code_events_sanitize_render_payloads_without_dropping_shape():
    artifact = await create_artifact_event(
        artifact_type="html",
        artifact_id="art_1",
        title="Secret demo",
        content='const api_key = "raw-artifact-token-123456";',
        language="javascript",
        metadata={"execution_status": "success", "access_token": "raw-meta-token"},
    )
    code_delta = await create_code_delta_event(
        session_id="cs_1",
        chunk='authorization: "raw-code-delta-token-123456"',
        chunk_index=0,
        total_bytes=42,
    )
    code_complete = await create_code_complete_event(
        session_id="cs_1",
        full_code='const client_secret = "raw-code-complete-token-123456";',
        language="html",
        version=1,
        visual_payload={
            "id": "visual_1",
            "provider_payload": {"access_token": "raw-visual-token"},
        },
    )

    serialized = "\n".join(
        [_serialized(artifact), _serialized(code_delta), _serialized(code_complete)]
    )

    assert artifact.content["artifact_type"] == "html"
    assert artifact.content["metadata"]["execution_status"] == "success"
    assert code_delta.content["session_id"] == "cs_1"
    assert code_complete.content["visual_payload"]["id"] == "visual_1"
    assert "provider_payload" not in serialized
    assert "access_token" not in serialized
    assert "raw-artifact-token" not in serialized
    assert "raw-meta-token" not in serialized
    assert "raw-code-delta-token" not in serialized
    assert "raw-code-complete-token" not in serialized
    assert "raw-visual-token" not in serialized


@pytest.mark.asyncio
async def test_visual_host_and_pointy_events_sanitize_nested_params():
    visual = await create_visual_open_event(
        {
            "visual_session_id": "visual_1",
            "provider_payload": {"token": "raw-visual-open-token"},
            "safe": {"kind": "chart"},
        },
    )
    host = await create_host_action_event(
        request_id="host_1",
        action="navigate",
        params={
            "url": "/course/123",
            "access_token": "raw-host-token",
            "query": "Bearer raw-host-query-token-12345678",
        },
    )
    pointy = await create_pointy_action_event(
        {
            "action": "highlight",
            "requestId": "pointy_1",
            "params": {
                "selector": "#safe",
                "connection_ref": "wcn_raw_connection_ref",
            },
        },
    )

    serialized = "\n".join([_serialized(visual), _serialized(host), _serialized(pointy)])

    assert visual.content["safe"]["kind"] == "chart"
    assert host.content["params"]["url"] == "/course/123"
    assert pointy.content["params"]["selector"] == "#safe"
    assert "provider_payload" not in serialized
    assert "access_token" not in serialized
    assert "connection_ref" not in serialized
    assert "raw-visual-open-token" not in serialized
    assert "raw-host-token" not in serialized
    assert "raw-host-query-token" not in serialized
    assert "wcn_raw_connection_ref" not in serialized


@pytest.mark.asyncio
async def test_browser_screenshot_event_sanitizes_metadata_but_preserves_image():
    event = await create_browser_screenshot_event(
        url="https://example.com?token=raw-browser-url-token",
        image_base64="abc123==",
        label="Screenshot access_token=raw-browser-label-token",
        metadata={
            "execution_id": "exec-1",
            "access_token": "raw-browser-metadata-token",
        },
    )

    payload = _serialized(event)

    assert event.content["image"] == "abc123=="
    assert event.content["metadata"]["execution_id"] == "exec-1"
    assert "access_token" not in payload
    assert "raw-browser-url-token" not in payload
    assert "raw-browser-label-token" not in payload
    assert "raw-browser-metadata-token" not in payload
