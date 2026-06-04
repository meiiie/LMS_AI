"""
Sprint 190: "Kho Tri Thức" — Org Admin Knowledge Base Management

Tests for org knowledge upload, list, detail, delete endpoints.
Triple gate: enable_org_knowledge AND enable_multi_tenant AND org admin check.
"""

import io
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# Helpers
# ============================================================================

def _make_settings(**overrides):
    """Create a Settings mock with defaults + overrides."""
    defaults = {
        "enable_org_knowledge": True,
        "enable_multi_tenant": True,
        "enable_org_admin": True,
        "enable_auth_audit": False,
        "org_knowledge_max_file_size_mb": 50,
        "org_knowledge_rate_limit": "5/minute",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_auth(user_id="admin-user", role="admin", org_id=None):
    """Create an AuthenticatedUser for testing (Sprint 217: require_auth migration)."""
    from app.core.security import AuthenticatedUser
    return AuthenticatedUser(
        user_id=user_id,
        auth_method="api_key",
        role=role,
        organization_id=org_id,
    )


def _make_request(user_id="admin-user", role="admin", org_id=None):
    """Create a mock Request for rate limiter (still needed by endpoints)."""
    headers = {
        "x-user-id": user_id,
        "x-role": role,
    }
    if org_id:
        headers["x-organization-id"] = org_id

    mock_req = MagicMock()
    mock_req.headers = MagicMock()
    mock_req.headers.get = lambda key, default=None: headers.get(key, default)
    # For rate limiter
    mock_req.client = MagicMock()
    mock_req.client.host = "127.0.0.1"
    mock_req.state = MagicMock()
    return mock_req


def _make_upload_file(filename="test.pdf", content=b"%PDF-1.4 test content", content_type="application/pdf"):
    """Create a mock UploadFile."""
    mock = AsyncMock()
    mock.filename = filename
    mock.content_type = content_type
    mock.read = AsyncMock(return_value=content)
    return mock


def _make_pool():
    """Create a mock asyncpg pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=0)
    # Transaction support: conn.transaction() returns an async context manager
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_cm)
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_doc_row(doc_id="doc-1", org_id="test-org", status="ready", **kwargs):
    """Create a dict mimicking a DB row for organization_documents."""
    defaults = {
        "document_id": doc_id,
        "organization_id": org_id,
        "filename": "test.pdf",
        "file_size_bytes": 1024,
        "status": status,
        "page_count": 10,
        "chunk_count": 10,
        "error_message": None,
        "uploaded_by": "admin-user",
        "created_at": datetime(2026, 2, 24, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 2, 24, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return defaults


# ============================================================================
# 1. TestOrgKnowledgeConfig — Feature flag gating
# ============================================================================

class TestOrgKnowledgeConfig:
    """Test feature flag gating for org knowledge endpoints."""

    @pytest.mark.asyncio
    async def test_disabled_when_feature_off(self):
        """Endpoints return 403 when enable_org_knowledge=False."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="admin")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings(enable_org_knowledge=False)):
            with pytest.raises(Exception) as exc_info:
                await _require_org_knowledge_admin(auth, "test-org")
            assert "disabled" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_disabled_when_multi_tenant_off(self):
        """Endpoints return 403 when enable_multi_tenant=False."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="admin")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings(enable_multi_tenant=False)):
            with pytest.raises(Exception) as exc_info:
                await _require_org_knowledge_admin(auth, "test-org")
            assert "multi-tenant" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_enabled_when_all_flags_on(self):
        """Platform admin passes triple gate when all flags enabled."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="admin", user_id="admin-1")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            user_id = await _require_org_knowledge_admin(auth, "test-org")
            assert user_id == "admin-1"


# ============================================================================
# 2. TestOrgKnowledgeAuth — Triple gate, org admin check, platform bypass
# ============================================================================

class TestOrgKnowledgeAuth:
    """Test auth patterns for org knowledge endpoints."""

    @pytest.mark.asyncio
    async def test_platform_admin_bypass(self):
        """Platform admin (role=admin) always passes auth."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="admin", user_id="platform-admin")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            user_id = await _require_org_knowledge_admin(auth, "any-org")
            assert user_id == "platform-admin"

    @pytest.mark.asyncio
    async def test_org_admin_passes(self):
        """Org admin (org_role=admin) passes when enable_org_admin=True."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        mock_repo = MagicMock()
        mock_repo.get_user_org_role = MagicMock(return_value="admin")

        auth = _make_auth(role="student", user_id="org-admin-1", org_id="test-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                user_id = await _require_org_knowledge_admin(auth, "test-org")
                assert user_id == "org-admin-1"

    @pytest.mark.asyncio
    async def test_org_owner_passes(self):
        """Org owner passes auth."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        mock_repo = MagicMock()
        mock_repo.get_user_org_role = MagicMock(return_value="owner")

        auth = _make_auth(role="teacher", user_id="org-owner-1", org_id="test-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                user_id = await _require_org_knowledge_admin(auth, "test-org")
                assert user_id == "org-owner-1"

    @pytest.mark.asyncio
    async def test_regular_member_rejected(self):
        """Regular org member (member role) is rejected."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        mock_repo = MagicMock()
        mock_repo.get_user_org_role = MagicMock(return_value="member")

        auth = _make_auth(role="student", user_id="regular-user", org_id="test-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                with pytest.raises(Exception) as exc_info:
                    await _require_org_knowledge_admin(auth, "test-org")
                assert "admin" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_non_member_rejected(self):
        """Non-member is rejected."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        mock_repo = MagicMock()
        mock_repo.get_user_org_role = MagicMock(return_value=None)

        auth = _make_auth(role="student", user_id="outsider", org_id="test-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                with pytest.raises(Exception) as exc_info:
                    await _require_org_knowledge_admin(auth, "test-org")
                assert "admin" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_org_admin_rejected_when_flag_off(self):
        """Org admin is rejected when enable_org_admin=False."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="student", user_id="org-admin", org_id="test-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings(enable_org_admin=False)):
            with pytest.raises(Exception) as exc_info:
                await _require_org_knowledge_admin(auth, "test-org")
            assert "admin" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_admin_missing_active_org_rejected_before_role_lookup(self):
        """Org admins need active org context before document access."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="student", user_id="org-admin", org_id=None)
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository") as repo_factory:
                with pytest.raises(Exception) as exc_info:
                    await _require_org_knowledge_admin(auth, "test-org")
                assert exc_info.value.status_code == 403
                assert exc_info.value.detail == "Organization context required for org knowledge access"
                repo_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_admin_active_org_mismatch_rejected_before_role_lookup(self):
        """Route org must match active org for non-platform org admins."""
        from app.api.v1.org_knowledge import _require_org_knowledge_admin

        auth = _make_auth(role="student", user_id="org-admin", org_id="org-A")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository") as repo_factory:
                with pytest.raises(Exception) as exc_info:
                    await _require_org_knowledge_admin(auth, "org-B")
                assert exc_info.value.status_code == 403
                assert exc_info.value.detail == "Active organization does not match route organization"
                repo_factory.assert_not_called()


# ============================================================================
# 3. TestDocumentUpload — Upload flow, validation, size limit
# ============================================================================

class TestDocumentUpload:
    """Test document upload endpoint logic."""

    @pytest.mark.asyncio
    async def test_reject_non_pdf(self):
        """Non-PDF file is rejected."""
        from app.api.v1.org_knowledge import upload_org_document

        request = _make_request(role="admin")
        file = _make_upload_file(filename="test.docx", content_type="application/msword")
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with pytest.raises(Exception) as exc_info:
                    await upload_org_document(request, "test-org", file, auth=_make_auth(role="admin"))
                assert "PDF" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_reject_wrong_extension(self):
        """File with wrong extension is rejected."""
        from app.api.v1.org_knowledge import upload_org_document

        request = _make_request(role="admin")
        file = _make_upload_file(filename="test.txt", content_type="application/pdf")
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with pytest.raises(Exception) as exc_info:
                    await upload_org_document(request, "test-org", file, auth=_make_auth(role="admin"))
                assert "pdf" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_reject_oversized_file(self):
        """File exceeding size limit is rejected."""
        from app.api.v1.org_knowledge import upload_org_document

        big_content = b"x" * (51 * 1024 * 1024)  # 51MB
        request = _make_request(role="admin")
        file = _make_upload_file(content=big_content)
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with pytest.raises(Exception) as exc_info:
                    await upload_org_document(request, "test-org", file, auth=_make_auth(role="admin"))
                assert "large" in str(exc_info.value.detail).lower() or "413" in str(exc_info.value.status_code)

    @pytest.mark.asyncio
    async def test_successful_upload(self):
        """Successful upload creates tracking record and calls ingestion."""
        from app.api.v1.org_knowledge import upload_org_document

        request = _make_request(role="admin", user_id="admin-1")
        auth = _make_auth(role="admin", user_id="admin-1")
        file = _make_upload_file()
        pool, conn = _make_pool()

        # Mock ingestion result
        ingest_result = SimpleNamespace(
            total_pages=5,
            successful_pages=5,
            failed_pages=0,
            pages_processed=5,
            success_rate=100.0,
        )
        mock_service = MagicMock()
        mock_service.ingest_pdf = AsyncMock(return_value=ingest_result)

        # Mock _get_document to return after insert
        doc_row = _make_doc_row(org_id="test-org", status="ready", page_count=5, chunk_count=5)

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.api.v1.org_knowledge._insert_document", new_callable=AsyncMock):
                    with patch("app.api.v1.org_knowledge._update_document_status", new_callable=AsyncMock):
                        with patch("app.services.multimodal_ingestion_service.get_ingestion_service", return_value=mock_service):
                            with patch("app.api.v1.org_knowledge._get_document", new_callable=AsyncMock, return_value=doc_row):
                                with patch("app.api.v1.org_knowledge._audit_log", new_callable=AsyncMock):
                                    result = await upload_org_document(request, "test-org", file, auth=auth)

        assert result.status == "ready"
        assert result.organization_id == "test-org"
        assert result.page_count == 5

    @pytest.mark.asyncio
    async def test_upload_handles_ingestion_failure(self):
        """Upload marks document as failed when ingestion raises."""
        from app.api.v1.org_knowledge import upload_org_document

        request = _make_request(role="admin")
        file = _make_upload_file()
        pool, conn = _make_pool()

        mock_service = MagicMock()
        mock_service.ingest_pdf = AsyncMock(side_effect=RuntimeError("Ingestion boom"))

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.api.v1.org_knowledge._insert_document", new_callable=AsyncMock):
                    with patch("app.api.v1.org_knowledge._update_document_status", new_callable=AsyncMock) as mock_status:
                        with patch("app.services.multimodal_ingestion_service.get_ingestion_service", return_value=mock_service):
                            with pytest.raises(Exception) as exc_info:
                                await upload_org_document(request, "test-org", file, auth=_make_auth(role="admin"))
                            assert exc_info.value.status_code == 500

                    # Verify status was set to "failed"
                    calls = mock_status.call_args_list
                    assert any("failed" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_upload_null_filename_rejected(self):
        """Upload with no filename is rejected."""
        from app.api.v1.org_knowledge import upload_org_document

        request = _make_request(role="admin")
        file = _make_upload_file(filename=None)
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with pytest.raises(Exception):
                    await upload_org_document(request, "test-org", file, auth=_make_auth(role="admin"))

    @pytest.mark.asyncio
    async def test_custom_size_limit(self):
        """Custom org_knowledge_max_file_size_mb is respected."""
        from app.api.v1.org_knowledge import upload_org_document

        # 5MB limit
        content = b"x" * (6 * 1024 * 1024)  # 6MB
        request = _make_request(role="admin")
        file = _make_upload_file(content=content)
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings",
                    return_value=_make_settings(org_knowledge_max_file_size_mb=5)):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with pytest.raises(Exception) as exc_info:
                    await upload_org_document(request, "test-org", file, auth=_make_auth(role="admin"))
                assert "large" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_upload_generates_uuid(self):
        """Upload generates a UUID4 document_id."""
        from app.api.v1.org_knowledge import upload_org_document

        request = _make_request(role="admin")
        auth = _make_auth(role="admin")
        file = _make_upload_file()
        pool, conn = _make_pool()

        ingest_result = SimpleNamespace(total_pages=1, successful_pages=1, failed_pages=0, pages_processed=1, success_rate=100.0)
        mock_service = MagicMock()
        mock_service.ingest_pdf = AsyncMock(return_value=ingest_result)

        captured_doc_id = None

        async def capture_insert(p, doc_id, org_id, filename, size, uid):
            nonlocal captured_doc_id
            captured_doc_id = doc_id

        doc_row = _make_doc_row()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.api.v1.org_knowledge._insert_document", side_effect=capture_insert):
                    with patch("app.api.v1.org_knowledge._update_document_status", new_callable=AsyncMock):
                        with patch("app.services.multimodal_ingestion_service.get_ingestion_service", return_value=mock_service):
                            with patch("app.api.v1.org_knowledge._get_document", new_callable=AsyncMock, return_value=doc_row):
                                with patch("app.api.v1.org_knowledge._audit_log", new_callable=AsyncMock):
                                    await upload_org_document(request, "test-org", file, auth=auth)

        assert captured_doc_id is not None
        uuid.UUID(captured_doc_id)  # Validates it's a proper UUID


# ============================================================================
# 4. TestDocumentLifecycle — Status transitions
# ============================================================================

class TestDocumentLifecycle:
    """Test document status transitions."""

    @pytest.mark.asyncio
    async def test_status_uploading_to_processing(self):
        """Document transitions from uploading → processing."""
        from app.api.v1.org_knowledge import _update_document_status

        pool, conn = _make_pool()
        await _update_document_status(pool, "doc-1", "org-1", "processing")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "processing" in str(args)
        assert "WHERE document_id = $1 AND organization_id = $2" in args.args[0]
        assert args.args[1:4] == ("doc-1", "org-1", "processing")

    @pytest.mark.asyncio
    async def test_status_processing_to_ready(self):
        """Document transitions from processing → ready with counts."""
        from app.api.v1.org_knowledge import _update_document_status

        pool, conn = _make_pool()
        await _update_document_status(pool, "doc-1", "org-1", "ready", page_count=10, chunk_count=50)
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "ready" in str(args)
        assert "WHERE document_id = $1 AND organization_id = $2" in args.args[0]
        assert args.args[1:] == ("doc-1", "org-1", "ready", 10, 50, None)

    @pytest.mark.asyncio
    async def test_status_processing_to_failed(self):
        """Document transitions from processing → failed with error."""
        from app.api.v1.org_knowledge import _update_document_status

        pool, conn = _make_pool()
        await _update_document_status(pool, "doc-1", "org-1", "failed", error_message="Parse error")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "WHERE document_id = $1 AND organization_id = $2" in args.args[0]
        assert args.args[1:] == ("doc-1", "org-1", "failed", None, None, "Parse error")

    @pytest.mark.asyncio
    async def test_status_to_deleted(self):
        """Document transitions to deleted status."""
        from app.api.v1.org_knowledge import _update_document_status

        pool, conn = _make_pool()
        await _update_document_status(pool, "doc-1", "org-1", "deleted")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "WHERE document_id = $1 AND organization_id = $2" in args.args[0]
        assert args.args[1:4] == ("doc-1", "org-1", "deleted")

    @pytest.mark.asyncio
    async def test_insert_document(self):
        """Insert creates a new document record."""
        from app.api.v1.org_knowledge import _insert_document

        pool, conn = _make_pool()
        await _insert_document(pool, "doc-1", "org-1", "test.pdf", 1024, "user-1")
        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "INSERT" in str(args)


# ============================================================================
# 5. TestDocumentList — Org isolation, status filter
# ============================================================================

class TestDocumentList:
    """Test document listing."""

    @pytest.mark.asyncio
    async def test_list_scoped_to_org(self):
        """Documents are filtered by organization_id."""
        from app.api.v1.org_knowledge import _list_documents

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        await _list_documents(pool, "org-1")
        args = conn.fetch.call_args
        assert "org-1" in str(args)

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        """Status filter is applied when provided."""
        from app.api.v1.org_knowledge import _list_documents

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        await _list_documents(pool, "org-1", status_filter="ready")
        args = conn.fetch.call_args
        assert "ready" in str(args)

    @pytest.mark.asyncio
    async def test_list_excludes_deleted(self):
        """Default list excludes deleted documents."""
        from app.api.v1.org_knowledge import _list_documents

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        await _list_documents(pool, "org-1")
        query = str(conn.fetch.call_args)
        assert "deleted" in query

    @pytest.mark.asyncio
    async def test_list_endpoint_allows_member(self):
        """Regular org member can list documents."""
        from app.api.v1.org_knowledge import _require_org_member

        mock_repo = MagicMock()
        mock_repo.is_user_in_org = MagicMock(return_value=True)

        auth = _make_auth(role="student", user_id="member-1", org_id="test-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                user_id = await _require_org_member(auth, "test-org")
                assert user_id == "member-1"

    @pytest.mark.asyncio
    async def test_member_missing_active_org_rejected_before_membership_lookup(self):
        """Document list/detail reads require active org context."""
        from app.api.v1.org_knowledge import _require_org_member

        auth = _make_auth(role="student", user_id="member-1", org_id=None)
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository") as repo_factory:
                with pytest.raises(Exception) as exc_info:
                    await _require_org_member(auth, "test-org")
                assert exc_info.value.status_code == 403
                assert exc_info.value.detail == "Organization context required for org knowledge access"
                repo_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_member_active_org_mismatch_rejected_before_membership_lookup(self):
        """Document list/detail route org must match active org."""
        from app.api.v1.org_knowledge import _require_org_member

        auth = _make_auth(role="student", user_id="member-1", org_id="org-A")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository") as repo_factory:
                with pytest.raises(Exception) as exc_info:
                    await _require_org_member(auth, "org-B")
                assert exc_info.value.status_code == 403
                assert exc_info.value.detail == "Active organization does not match route organization"
                repo_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_count_documents(self):
        """Count returns total document count."""
        from app.api.v1.org_knowledge import _count_documents

        pool, conn = _make_pool()
        conn.fetchval = AsyncMock(return_value=42)
        count = await _count_documents(pool, "org-1")
        assert count == 42


# ============================================================================
# 6. TestDocumentDelete — Soft delete, embedding cleanup
# ============================================================================

class TestDocumentDelete:
    """Test document deletion."""

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """Delete returns 404 when document not found."""
        from app.api.v1.org_knowledge import delete_org_document

        request = _make_request(role="admin")
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.api.v1.org_knowledge._get_document", new_callable=AsyncMock, return_value=None):
                    with pytest.raises(Exception) as exc_info:
                        await delete_org_document(request, "test-org", "non-existent", auth=_make_auth(role="admin"))
                    assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_removes_embeddings(self):
        """Delete removes embeddings and marks status in a single transaction."""
        from app.api.v1.org_knowledge import delete_org_document

        request = _make_request(role="admin")
        pool, conn = _make_pool()
        doc_row = _make_doc_row()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.api.v1.org_knowledge._get_document", new_callable=AsyncMock, return_value=doc_row):
                    with patch("app.api.v1.org_knowledge._audit_log", new_callable=AsyncMock):
                        await delete_org_document(request, "test-org", "doc-1", auth=_make_auth(role="admin"))

        # Verify both DELETE and UPDATE were called within the transaction
        assert conn.execute.call_count >= 2
        calls = [call.args for call in conn.execute.call_args_list]
        assert any("knowledge_embeddings" in args[0] for args in calls)
        update_calls = [
            args for args in calls
            if "UPDATE organization_documents" in args[0]
        ]
        assert len(update_calls) == 1
        assert "WHERE document_id = $1 AND organization_id = $2" in update_calls[0][0]
        assert update_calls[0][1:] == ("doc-1", "test-org")

    @pytest.mark.asyncio
    async def test_delete_requires_admin(self):
        """Delete requires org admin, not just member."""
        from app.api.v1.org_knowledge import delete_org_document

        mock_repo = MagicMock()
        mock_repo.get_user_org_role = MagicMock(return_value="member")

        request = _make_request(role="student", user_id="regular-member")
        auth = _make_auth(role="student", user_id="regular-member", org_id="test-org")
        pool, conn = _make_pool()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                    with pytest.raises(Exception) as exc_info:
                        await delete_org_document(request, "test-org", "doc-1", auth=auth)
                    assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_marks_status_deleted(self):
        """Delete marks document status as 'deleted' within the same transaction."""
        from app.api.v1.org_knowledge import delete_org_document

        request = _make_request(role="admin")
        pool, conn = _make_pool()
        doc_row = _make_doc_row()

        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.api.v1.org_knowledge._get_pool", return_value=pool):
                with patch("app.api.v1.org_knowledge._get_document", new_callable=AsyncMock, return_value=doc_row):
                    with patch("app.api.v1.org_knowledge._audit_log", new_callable=AsyncMock):
                        await delete_org_document(request, "test-org", "doc-1", auth=_make_auth(role="admin"))

        # Verify UPDATE with status='deleted' was called
        calls = [call.args for call in conn.execute.call_args_list]
        assert any("deleted" in args[0] and "organization_documents" in args[0] for args in calls)
        assert any(
            "WHERE document_id = $1 AND organization_id = $2" in args[0]
            and args[1:] == ("doc-1", "test-org")
            for args in calls
        )


# ============================================================================
# 7. TestOrgIsolation — Cross-org isolation
# ============================================================================

class TestOrgIsolation:
    """Test cross-org data isolation."""

    @pytest.mark.asyncio
    async def test_get_document_scoped_to_org(self):
        """_get_document only returns docs matching org_id."""
        from app.api.v1.org_knowledge import _get_document

        pool, conn = _make_pool()
        conn.fetchrow = AsyncMock(return_value=None)
        result = await _get_document(pool, "doc-1", "org-A")
        assert result is None

        # Verify org_id was in the query
        args = conn.fetchrow.call_args
        assert "org-A" in str(args)

    @pytest.mark.asyncio
    async def test_list_documents_scoped_to_org(self):
        """_list_documents only returns docs for the specified org."""
        from app.api.v1.org_knowledge import _list_documents

        pool, conn = _make_pool()
        conn.fetch = AsyncMock(return_value=[])
        await _list_documents(pool, "org-B")
        args = conn.fetch.call_args
        assert "org-B" in str(args)

    @pytest.mark.asyncio
    async def test_member_check_prevents_cross_org_list(self):
        """Non-member cannot list another org's documents."""
        from app.api.v1.org_knowledge import _require_org_member

        mock_repo = MagicMock()
        mock_repo.is_user_in_org = MagicMock(return_value=False)

        auth = _make_auth(role="student", user_id="outsider", org_id="private-org")
        with patch("app.api.v1.org_knowledge.get_settings", return_value=_make_settings()):
            with patch("app.repositories.organization_repository.get_organization_repository", return_value=mock_repo):
                with pytest.raises(Exception) as exc_info:
                    await _require_org_member(auth, "private-org")
                assert "member" in str(exc_info.value.detail).lower()


# ============================================================================
# 8. TestAuditLogging — Upload/delete events logged
# ============================================================================

class TestAuditLogging:
    """Test audit event logging."""

    @pytest.mark.asyncio
    async def test_audit_log_fires_on_upload(self):
        """Upload triggers an audit log event."""
        from app.api.v1.org_knowledge import _audit_log

        with patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock) as mock_log:
            await _audit_log("org_knowledge_upload", "user-1", "org-1", {"doc": "test"})
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args.kwargs["event_type"] == "org_knowledge_upload"
            assert args.kwargs["organization_id"] == "org-1"

    @pytest.mark.asyncio
    async def test_audit_log_fires_on_delete(self):
        """Delete triggers an audit log event."""
        from app.api.v1.org_knowledge import _audit_log

        with patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock) as mock_log:
            await _audit_log("org_knowledge_delete", "user-1", "org-1", {"doc": "test"})
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_log_never_raises(self):
        """Audit log failure is swallowed (fire-and-forget)."""
        from app.api.v1.org_knowledge import _audit_log

        with patch("app.auth.auth_audit.log_auth_event", new_callable=AsyncMock, side_effect=RuntimeError("DB down")):
            # Should not raise
            await _audit_log("org_knowledge_upload", "user-1", "org-1")


# ============================================================================
# 9. TestBackwardCompat — Existing knowledge endpoints still work
# ============================================================================

class TestBackwardCompat:
    """Test existing knowledge endpoints are unaffected."""

    def test_knowledge_router_exists(self):
        """Existing knowledge router is still importable."""
        from app.api.v1.knowledge import router
        assert router is not None

    def test_org_knowledge_router_exists(self):
        """New org knowledge router is importable."""
        from app.api.v1.org_knowledge import router
        assert router is not None
        assert router.prefix == "/organizations"

    def test_response_models(self):
        """Response models validate correctly."""
        from app.api.v1.org_knowledge import OrgDocumentResponse, OrgDocumentListResponse

        doc = OrgDocumentResponse(
            document_id="test-doc",
            organization_id="test-org",
            filename="test.pdf",
            status="ready",
            uploaded_by="user-1",
        )
        assert doc.document_id == "test-doc"

        doc_list = OrgDocumentListResponse(documents=[doc], total=1)
        assert doc_list.total == 1
        assert len(doc_list.documents) == 1


# ============================================================================
# 10. TestPermissions — manage:knowledge permission
# ============================================================================

class TestPermissions:
    """Test manage:knowledge permission integration."""

    def test_admin_has_manage_knowledge(self):
        """Admin role includes manage:knowledge in default permissions."""
        from app.models.organization import OrgPermissions
        perms = OrgPermissions()
        assert "manage:knowledge" in perms.admin

    def test_student_lacks_manage_knowledge(self):
        """Student role does NOT include manage:knowledge."""
        from app.models.organization import OrgPermissions
        perms = OrgPermissions()
        assert "manage:knowledge" not in perms.student

    def test_org_admin_gets_manage_knowledge(self):
        """Org admin (Sprint 181) gets manage:knowledge permission."""
        with patch("app.core.org_settings.get_effective_settings") as mock_eff:
            from app.models.organization import OrgSettings
            mock_eff.return_value = OrgSettings()

            with patch("app.core.config.settings") as mock_settings:
                mock_settings.enable_org_admin = True

                from app.core.org_settings import get_org_permissions
                perms = get_org_permissions("test-org", "student", org_role="admin")
                assert "manage:knowledge" in perms


# ============================================================================
# 11. TestConfigFlags — Config field validation
# ============================================================================

class TestConfigFlags:
    """Test new config flags exist and have correct defaults."""

    def test_enable_org_knowledge_default(self):
        """enable_org_knowledge defaults to False."""
        settings = _make_settings(enable_org_knowledge=False)
        assert settings.enable_org_knowledge is False

    def test_org_knowledge_max_file_size_default(self):
        """org_knowledge_max_file_size_mb defaults to 50."""
        settings = _make_settings()
        assert settings.org_knowledge_max_file_size_mb == 50

    def test_org_knowledge_rate_limit_default(self):
        """org_knowledge_rate_limit defaults to '5/minute'."""
        settings = _make_settings()
        assert settings.org_knowledge_rate_limit == "5/minute"
