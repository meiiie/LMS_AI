from app.services.chat_runtime_lifecycle import (
    CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION,
    ChatLifecycleName,
    ChatRuntimeLifecycleEvent,
    capability_snapshot_from_ledger_payload,
)


def test_chat_runtime_lifecycle_truncates_strings_to_limit():
    payload = ChatRuntimeLifecycleEvent(
        name=ChatLifecycleName.PATH_SELECTED,
        phase="routing",
        status="selected",
        message="x" * 200,
        reason="r" * 200,
    ).to_payload()

    assert payload["schema_version"] == CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION
    assert len(payload["reason"]) == 128
    assert payload["reason"].endswith("...")


def test_chat_runtime_lifecycle_metadata_is_allowlisted_and_bounded():
    payload = ChatRuntimeLifecycleEvent(
        name=ChatLifecycleName.CAPABILITY_CHECKED,
        phase="capability",
        status="ready",
        message="ok",
        metadata={
            "bound_tools": ["visual_runtime", "x" * 200],
            "provider": "nvidia",
            "fallback_used": False,
            "secret_token": "must-not-leak",
            "nested": {"unsafe": "payload"},
        },
    ).to_payload()

    metadata = payload["metadata"]
    assert metadata["provider"] == "nvidia"
    assert metadata["fallback_used"] is False
    assert metadata["bound_tools"][0] == "visual_runtime"
    assert len(metadata["bound_tools"][1]) == 128
    assert "secret_token" not in metadata
    assert "nested" not in metadata


def test_capability_snapshot_includes_redacted_wiii_connect_snapshot():
    payload = capability_snapshot_from_ledger_payload(
        {
            "request": {
                "host_surface": "lms_course_editor",
                "host_capabilities": ["lms", "host_action"],
            },
            "tools": {"observed": ["tool_web_search"]},
            "host_actions": {
                "preview_required": True,
                "approval_token_present": True,
            },
        },
        wiii_connect_snapshot={
            "version": "wiii_connect_snapshot.v0",
            "generated_at": "2026-05-27T00:00:00Z",
            "surface": "lms_course_editor",
            "connections": [
                {
                    "slug": "document_corpus",
                    "label": "Document corpus",
                    "status": "connected",
                    "active": True,
                    "agent_ready": True,
                    "scopes": {"read": True, "write": False},
                    "capabilities": ["document.read", "document.cite"],
                    "attachment_count": 1,
                    "filename": "private.docx",
                    "approval_token": "must-not-leak",
                }
            ],
            "path_capabilities": [
                {
                    "path": "lms_document_apply",
                    "mutation_policy": "approval_token_required",
                    "raw_prompt": "must-not-leak",
                }
            ],
            "warnings": ["document_context_without_source_refs"],
        },
    )

    snapshot = payload["wiii_connect"]
    assert snapshot["version"] == "wiii_connect_snapshot.v0"
    assert snapshot["connections"][0]["slug"] == "document_corpus"
    assert snapshot["connections"][0]["attachment_count"] == 1
    assert snapshot["connections"][0]["scopes"] == {"read": True, "write": False}
    assert snapshot["path_capabilities"][0]["mutation_policy"] == "approval_token_required"
    serialized = str(snapshot)
    assert "private.docx" not in serialized
    assert "must-not-leak" not in serialized
    assert "raw_prompt" not in serialized
