from types import SimpleNamespace

import pytest

from app.services.chat_stream_visual_fast_path import (
    build_visual_fast_path_result,
    should_use_visual_fast_path,
)


def _request(message: str, **overrides):
    data = {
        "message": message,
        "user_context": None,
        "images": [],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_build_visual_fast_path_result_emits_lifecycle_for_creation_request():
    request = _request(
        "Create a compact inline visual comparing soft attention and linear attention. "
        "Use structured visual lifecycle."
    )

    result = await build_visual_fast_path_result(request)

    assert result is not None
    event_types = [event.type for event in result.events]
    assert "visual_open" in event_types
    assert "visual_commit" in event_types
    assert result.routing_metadata["method"] == "structured_visual_fast_path"


def test_visual_fast_path_skips_uploaded_document_context():
    request = _request(
        "Create an inline visual from this document.",
        user_context=SimpleNamespace(
            document_context={
                "attachments": [
                    {
                        "name": "lesson.docx",
                        "markdown": "# Lesson\nSource-backed content",
                    }
                ]
            }
        ),
    )

    assert should_use_visual_fast_path(request) is False


def test_visual_fast_path_skips_fresh_or_web_sensitive_visuals():
    request = _request("Create a chart of latest shipping prices today.")

    assert should_use_visual_fast_path(request) is False
