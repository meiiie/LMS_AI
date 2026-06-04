"""
Tests for Knowledge API endpoints — Sprint 68.

Tests ingest-multimodal and stats endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1.knowledge import (
    validate_file,
    MAX_FILE_SIZE,
    ALLOWED_MIME_TYPES,
    KnowledgeStatsResponse,
)
from fastapi import HTTPException


# =============================================================================
# Fixtures
# =============================================================================


def _make_upload_file(filename="test.pdf", content_type="application/pdf", size=1024):
    """Create a mock UploadFile."""
    f = MagicMock()
    f.filename = filename
    f.content_type = content_type
    f.read = AsyncMock(return_value=b"x" * size)
    return f


# =============================================================================
# validate_file
# =============================================================================


class TestValidateFile:
    """Test validate_file() function."""

    def test_valid_pdf(self):
        """PDF file passes validation."""
        f = _make_upload_file("document.pdf", "application/pdf")
        # Should not raise
        validate_file(f)

    def test_invalid_mime_type(self):
        """Non-PDF mime type raises 400."""
        f = _make_upload_file("document.pdf", "text/plain")
        with pytest.raises(HTTPException) as exc_info:
            validate_file(f)
        assert exc_info.value.status_code == 400
        assert "Invalid file type" in str(exc_info.value.detail)

    def test_invalid_extension(self):
        """Non-.pdf extension raises 400."""
        f = _make_upload_file("document.txt", "application/pdf")
        with pytest.raises(HTTPException) as exc_info:
            validate_file(f)
        assert exc_info.value.status_code == 400
        assert "Invalid file extension" in str(exc_info.value.detail)


# =============================================================================
# Constants
# =============================================================================


class TestConstants:
    """Test knowledge module constants."""

    def test_max_file_size(self):
        assert MAX_FILE_SIZE == 50 * 1024 * 1024

    def test_allowed_mime_types(self):
        assert "application/pdf" in ALLOWED_MIME_TYPES


# =============================================================================
# KnowledgeStatsResponse model
# =============================================================================


class TestKnowledgeStatsResponse:
    """Test KnowledgeStatsResponse model."""

    def test_default_values(self):
        stats = KnowledgeStatsResponse(
            total_chunks=100,
            total_documents=5,
            content_types={"text": 80, "table": 20},
            avg_confidence=0.85,
        )
        assert stats.total_chunks == 100
        assert stats.total_documents == 5
        assert stats.warning is None

    def test_with_warning(self):
        stats = KnowledgeStatsResponse(
            total_chunks=0,
            total_documents=0,
            content_types={},
            avg_confidence=0.0,
            warning="Database connection failed",
        )
        assert stats.warning == "Database connection failed"

    def test_empty_db(self):
        stats = KnowledgeStatsResponse(
            total_chunks=0,
            total_documents=0,
            content_types={},
            avg_confidence=0.0,
        )
        assert stats.total_chunks == 0
        assert stats.total_documents == 0

    def test_multiple_content_types(self):
        content_types = {"text": 50, "table": 30, "heading": 20}
        stats = KnowledgeStatsResponse(
            total_chunks=100,
            total_documents=3,
            content_types=content_types,
            avg_confidence=0.9,
        )
        assert len(stats.content_types) == 3
        assert sum(stats.content_types.values()) == 100


class TestKnowledgeStatsTenantScope:
    """Knowledge stats queries must stay scoped to the active org."""

    @pytest.mark.asyncio
    async def test_get_statistics_filters_by_active_org(self, monkeypatch):
        from app.api.v1.knowledge import get_statistics
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production", raising=False)

        conn = MagicMock()
        conn.fetchval = AsyncMock(side_effect=[10, 2, 0.75])
        conn.fetch = AsyncMock(
            side_effect=[
                [{"content_type": "text", "count": 10}],
                [{"domain": "maritime", "count": 10}],
            ]
        )
        conn.close = AsyncMock()
        connect = AsyncMock(return_value=conn)
        auth = MagicMock()
        auth.organization_id = "org-A"

        with patch("asyncpg.connect", connect):
            result = await get_statistics(request=MagicMock(), auth=auth)

        all_calls = [*conn.fetchval.await_args_list, *conn.fetch.await_args_list]
        assert all("(organization_id = $1 OR organization_id IS NULL)" in c.args[0] for c in all_calls)
        assert all(c.args[1] == "org-A" for c in all_calls)
        assert result.total_chunks == 10
        assert result.total_documents == 2
        conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_statistics_requires_org_before_connect(self, monkeypatch):
        from app.api.v1.knowledge import get_statistics
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production", raising=False)
        connect = AsyncMock()
        auth = MagicMock()
        auth.organization_id = None

        token = current_org_id.set(None)
        try:
            with patch("asyncpg.connect", connect):
                with pytest.raises(HTTPException) as exc_info:
                    await get_statistics(request=MagicMock(), auth=auth)
        finally:
            current_org_id.reset(token)

        assert exc_info.value.status_code == 403
        assert "Organization context required" in str(exc_info.value.detail)
        connect.assert_not_awaited()


# =============================================================================
# Multimodal Ingestion Schema
# =============================================================================


class TestMultimodalIngestionResponse:
    """Test MultimodalIngestionResponse model."""

    def test_success_response(self):
        from app.api.v1.knowledge import MultimodalIngestionResponse
        resp = MultimodalIngestionResponse(
            status="completed",
            document_id="test_doc",
            total_pages=10,
            successful_pages=10,
            failed_pages=0,
            success_rate=100.0,
            errors=[],
            message="All pages processed",
            vision_pages=3,
            direct_pages=7,
            fallback_pages=0,
            api_savings_percent=70.0,
        )
        assert resp.status == "completed"
        assert resp.vision_pages == 3
        assert resp.api_savings_percent == 70.0

    def test_partial_response(self):
        from app.api.v1.knowledge import MultimodalIngestionResponse
        resp = MultimodalIngestionResponse(
            status="partial",
            document_id="test_doc",
            total_pages=10,
            successful_pages=8,
            failed_pages=2,
            success_rate=80.0,
            errors=["Page 3 failed", "Page 7 failed"],
            message="8 of 10 pages processed",
        )
        assert resp.status == "partial"
        assert len(resp.errors) == 2
        assert resp.failed_pages == 2

    def test_default_hybrid_fields(self):
        from app.api.v1.knowledge import MultimodalIngestionResponse
        resp = MultimodalIngestionResponse(
            status="completed",
            document_id="d",
            total_pages=1,
            successful_pages=1,
            failed_pages=0,
            success_rate=100.0,
            message="ok",
        )
        assert resp.vision_pages == 0
        assert resp.direct_pages == 0
        assert resp.fallback_pages == 0
        assert resp.api_savings_percent == 0.0
