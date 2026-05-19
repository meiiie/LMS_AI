from types import SimpleNamespace

from app.engine.multi_agent.document_preview_contract import (
    DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL,
    document_preview_forced_tool_choice,
    extract_document_preview_capabilities,
    has_document_preview_host_action_tool,
    has_uploaded_document_context,
    looks_uploaded_document_course_request,
    uploaded_document_attachments_from_context,
    uploaded_document_attachments_from_state,
)


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, exclude_none=True):
        return self.value


def test_uploaded_document_attachment_contract_accepts_mapping_like_values():
    attachment = Dumpable(
        {
            "file_name": "lesson.docx",
            "title": "Lesson",
            "markdown": "# Lesson\n\nSource-backed content.",
        }
    )
    ctx = {"document_context": {"attachments": [attachment, {"markdown": "   "}]}}

    assert has_uploaded_document_context(ctx)
    assert uploaded_document_attachments_from_context(ctx) == [attachment.value]
    assert uploaded_document_attachments_from_state({"context": ctx}) == [attachment.value]


def test_uploaded_document_course_intent_is_shared_by_preview_and_tool_rounds():
    assert looks_uploaded_document_course_request("tao bai giang di")
    assert looks_uploaded_document_course_request("turn this document into a course plan")
    assert not looks_uploaded_document_course_request("cap nhat bai hoc hien tai")


def test_document_preview_forced_tool_choice_prefers_course_when_available():
    tools = [
        SimpleNamespace(name=DOC_PREVIEW_HOST_ACTION_TOOL),
        SimpleNamespace(name=DOC_COURSE_HOST_ACTION_TOOL),
    ]

    assert has_document_preview_host_action_tool(tools)
    assert (
        document_preview_forced_tool_choice("tao bai giang di", tools)
        == DOC_COURSE_HOST_ACTION_TOOL
    )
    assert (
        document_preview_forced_tool_choice("cap nhat bai hoc hien tai", tools)
        == DOC_PREVIEW_HOST_ACTION_TOOL
    )


def test_extract_document_preview_capabilities_from_state_and_context():
    state = {
        "context": {
            "host_capabilities": {
                "tools": [
                    {"name": "authoring.generate_course_from_document", "source": "state"}
                ]
            }
        }
    }
    ctx = {
        "host_capabilities": {
            "tools": [{"name": "authoring.preview_lesson_patch", "source": "ctx"}]
        }
    }

    names = [item["name"] for item in extract_document_preview_capabilities(state, ctx)]

    assert names == [
        "authoring.preview_lesson_patch",
        "authoring.generate_course_from_document",
    ]
