from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.knowledge import (
    WorkbenchKnowledgeContextRequest,
    WorkbenchKnowledgeSource,
    render_workbench_knowledge_context,
    retrieve_workbench_knowledge_context,
)
from app.services.hybrid_search_service import HybridSearchUnavailableError


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
    assert "untrusted evidence" in rendered.text
    assert "document=guide.pdf" in rendered.text
    assert "page=7" in rendered.text
    assert "Rule 15 evidence" in rendered.text
    assert rendered.sources == [_source("Rule 15 evidence")]


def test_rendered_context_has_a_hard_character_budget() -> None:
    rendered = render_workbench_knowledge_context([_source("x" * 1000)], max_chars=200)
    assert len(rendered.text) == 200


def test_rendered_context_returns_only_sources_visible_to_the_model() -> None:
    first = _source("x" * 1000, source_id="chunk-1")
    second = _source("not visible", source_id="chunk-2")

    rendered = render_workbench_knowledge_context([first, second], max_chars=200)

    assert rendered.sources == [first]
    assert "chunk-2" not in rendered.text


@pytest.mark.asyncio
async def test_workbench_endpoint_propagates_total_retrieval_failure() -> None:
    service = MagicMock()
    service.search = AsyncMock(
        side_effect=HybridSearchUnavailableError("all retrieval paths failed")
    )

    with (
        patch(
            "app.api.v1.knowledge._resolve_knowledge_stats_org",
            return_value="org-1",
        ),
        patch(
            "app.services.hybrid_search_service.get_hybrid_search_service",
            return_value=service,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await retrieve_workbench_knowledge_context(
            request=MagicMock(),
            auth=MagicMock(organization_id="org-1"),
            body=WorkbenchKnowledgeContextRequest(query="collision rules"),
        )

    assert exc_info.value.status_code == 503
    service.search.assert_awaited_once_with(
        "collision rules",
        limit=5,
        domain_id=None,
        org_id="org-1",
        raise_on_total_failure=True,
    )
