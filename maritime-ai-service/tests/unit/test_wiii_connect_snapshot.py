from __future__ import annotations


def test_wiii_connect_snapshot_serializes_privacy_safe_metadata(monkeypatch):
    from app.engine.wiii_connect.snapshot import (
        WIII_CONNECT_SNAPSHOT_VERSION,
        build_wiii_connect_snapshot,
        settings,
    )

    monkeypatch.setattr(settings, "living_agent_enable_weather", True, raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "weather-secret", raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_city", "Ha Noi", raising=False)

    state = {
        "context": {
            "host_context": {
                "host_type": "lms",
                "connector_id": "lms-connector-1",
                "host_user_id": "private-user-id",
                "metadata": {
                    "pointyTargets": [{"id": "send", "label": "Gui"}],
                },
            },
            "host_capabilities": {
                "host_type": "lms",
                "tools": [
                    {"name": "authoring.preview_lesson_patch"},
                    {"name": "pointy.highlight"},
                ],
            },
            "document_context": {
                "attachments": [
                    {
                        "file_name": "private.docx",
                        "markdown": "RAW DOCUMENT TEXT MUST NOT LEAK",
                    }
                ],
                "source_refs": [{"id": "src-1"}],
                "approval_token": "approval-secret",
            },
        },
        "approval_token": "top-level-approval-secret",
    }

    snapshot = build_wiii_connect_snapshot(state=state, query="tao bai hoc")
    metadata = snapshot.to_metadata()
    serialized = str(metadata)

    assert metadata["version"] == WIII_CONNECT_SNAPSHOT_VERSION
    assert "RAW DOCUMENT TEXT MUST NOT LEAK" not in serialized
    assert "approval-secret" not in serialized
    assert "top-level-approval-secret" not in serialized
    assert "weather-secret" not in serialized
    assert "private.docx" not in serialized
    assert "private-user-id" not in serialized

    status = snapshot.connection_status_map()
    assert status["lms_authoring"]["active"] is True
    assert status["lms_authoring"]["host_user_id_present"] is True
    assert status["host_actions"]["tool_count"] == 2
    assert status["document_corpus"]["attachment_count"] == 1
    assert status["document_corpus"]["source_ref_count"] == 1
    assert status["pointy"]["target_count"] == 1
    assert status["weather"]["active"] is True


def test_wiii_connect_snapshot_fails_closed_without_host_or_provider(monkeypatch):
    from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot, settings

    monkeypatch.setattr(settings, "living_agent_enable_weather", False, raising=False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "", raising=False)

    snapshot = build_wiii_connect_snapshot(state={"context": {}}, query="")
    status = snapshot.connection_status_map()

    assert status["server"]["active"] is True
    assert status["lms_authoring"]["active"] is False
    assert status["lms_authoring"]["reason"] == "missing_lms_host"
    assert status["host_actions"]["active"] is False
    assert status["host_actions"]["reason"] == "missing_host_tools"
    assert status["weather"]["active"] is False
    assert status["weather"]["reason"] == "missing_weather_provider"
    assert status["query"]["active"] is False
