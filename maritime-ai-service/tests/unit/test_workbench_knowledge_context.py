from app.api.v1.knowledge import (
    WorkbenchKnowledgeContextRequest,
    WorkbenchKnowledgeSource,
    render_workbench_knowledge_context,
)


def _source(content: str, source_id: str = "chunk-1") -> WorkbenchKnowledgeSource:
    return WorkbenchKnowledgeSource(
        source_id=source_id,
        title="Safety guide",
        document_id="guide.pdf",
        page_number=7,
        content=content,
        score=0.82,
    )


def test_workbench_context_request_is_bounded() -> None:
    request = WorkbenchKnowledgeContextRequest(query="collision rules", limit=5)
    assert request.limit == 5


def test_rendered_context_marks_sources_as_untrusted_and_preserves_provenance() -> None:
    rendered = render_workbench_knowledge_context([_source("Rule 15 evidence")])
    assert "untrusted evidence" in rendered
    assert "document=guide.pdf" in rendered
    assert "page=7" in rendered
    assert "Rule 15 evidence" in rendered


def test_rendered_context_has_a_hard_character_budget() -> None:
    rendered = render_workbench_knowledge_context([_source("x" * 1000)], max_chars=200)
    assert len(rendered) == 200
