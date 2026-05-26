from app.services.chat_runtime_lifecycle import (
    CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION,
    ChatLifecycleName,
    ChatRuntimeLifecycleEvent,
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
