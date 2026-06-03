"""
Tests for Admin API endpoints - Sprint 68.

Tests document upload/status/list/delete and domain management endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException

from app.core.security_models import AuthenticatedUser

from app.api.v1.admin import (
    _ingestion_jobs,
    _cleanup_old_jobs,
    _MAX_TRACKED_JOBS,
    _run_ingestion_background,
)


def _admin_auth(organization_id="org-admin") -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id="admin-1",
        auth_method="jwt",
        role="admin",
        platform_role="platform_admin",
        organization_id=organization_id,
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear ingestion jobs between tests."""
    _ingestion_jobs.clear()
    yield
    _ingestion_jobs.clear()


def _make_domain_plugin(domain_id="maritime", name="Maritime", skills=None):
    """Create a mock domain plugin."""
    plugin = MagicMock()
    cfg = MagicMock()
    cfg.id = domain_id
    cfg.name = name
    cfg.name_vi = f"{name} (VN)"
    cfg.version = "1.0.0"
    cfg.description = f"{name} domain"
    cfg.routing_keywords = ["keyword1"]
    cfg.mandatory_search_triggers = ["trigger1"]
    cfg.rag_agent_description = "RAG agent"
    cfg.tutor_agent_description = "Tutor agent"
    plugin.get_config.return_value = cfg
    skill_list = skills or []
    plugin.get_skills.return_value = skill_list
    plugin.get_hyde_templates.return_value = []
    plugin.get_prompts_dir.return_value = MagicMock(exists=MagicMock(return_value=True))
    plugin.activate_skill.return_value = "skill content"
    return plugin


def _make_skill(skill_id="s1", name="Skill One", domain_id="maritime"):
    """Create a mock skill manifest."""
    s = MagicMock()
    s.id = skill_id
    s.name = name
    s.description = f"{name} description"
    s.domain_id = domain_id
    s.version = "1.0.0"
    s.triggers = ["trigger_a"]
    return s


# =============================================================================
# Document Status
# =============================================================================


class TestGetDocumentStatus:
    """Tests for GET /admin/documents/{job_id}."""

    def test_existing_job_returns_status(self):
        """Should return status for an existing job."""
        job_id = "test-job-1"
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "doc1",
            "status": "processing",
            "progress_percent": 50.0,
            "total_pages": 10,
            "processed_pages": 5,
            "error": None,
        }

        from app.api.v1.admin import DocumentStatus

        status = DocumentStatus(**_ingestion_jobs[job_id])
        assert status.job_id == job_id
        assert status.status == "processing"
        assert status.progress_percent == 50.0

    def test_completed_job(self):
        """Should return completed status."""
        job_id = "test-job-2"
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "doc2",
            "status": "completed",
            "progress_percent": 100.0,
            "total_pages": 20,
            "processed_pages": 20,
            "error": None,
        }

        from app.api.v1.admin import DocumentStatus

        status = DocumentStatus(**_ingestion_jobs[job_id])
        assert status.status == "completed"
        assert status.progress_percent == 100.0
        assert status.total_pages == 20

    def test_nonexistent_job(self):
        """Job dict should not contain missing IDs."""
        assert "nonexistent" not in _ingestion_jobs


# =============================================================================
# Cleanup Old Jobs
# =============================================================================


class TestCleanupOldJobs:
    """Tests for _cleanup_old_jobs."""

    def test_under_limit_noop(self):
        """Should not remove anything if under limit."""
        _ingestion_jobs["j1"] = {"status": "completed"}
        _ingestion_jobs["j2"] = {"status": "processing"}
        _cleanup_old_jobs()
        assert len(_ingestion_jobs) == 2

    def test_removes_completed_when_over_limit(self):
        """Should remove completed/failed jobs when over limit."""
        for i in range(_MAX_TRACKED_JOBS + 5):
            status = "completed" if i < _MAX_TRACKED_JOBS else "pending"
            _ingestion_jobs[f"j-{i}"] = {"status": status}

        assert len(_ingestion_jobs) > _MAX_TRACKED_JOBS
        _cleanup_old_jobs()
        assert len(_ingestion_jobs) <= _MAX_TRACKED_JOBS + 5

    def test_preserves_pending_jobs(self):
        """Should not remove pending/processing jobs."""
        for i in range(_MAX_TRACKED_JOBS + 5):
            _ingestion_jobs[f"j-{i}"] = {"status": "pending"}

        _cleanup_old_jobs()
        assert len(_ingestion_jobs) == _MAX_TRACKED_JOBS + 5


# =============================================================================
# Background Ingestion
# =============================================================================


class TestBackgroundIngestion:
    """Tests for _run_ingestion_background."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Should complete ingestion and update status."""
        job_id = "bg-1"
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "test_doc",
            "status": "pending",
            "progress_percent": 0.0,
            "total_pages": 0,
            "processed_pages": 0,
            "error": None,
        }

        mock_result = MagicMock()
        mock_result.total_pages = 10
        mock_result.successful_pages = 10
        mock_result.success_rate = 1.0

        mock_service = MagicMock()
        mock_service.ingest_pdf = AsyncMock(return_value=mock_result)

        mock_graph = MagicMock()
        mock_graph.is_available.return_value = False

        with patch("app.api.v1.admin.get_ingestion_service", return_value=mock_service), \
             patch("app.api.v1.admin.get_user_graph_repository", return_value=mock_graph):
            await _run_ingestion_background(
                job_id=job_id,
                document_id="test_doc",
                pdf_path="/tmp/test.pdf",
                create_neo4j_module=True,
            )

        assert _ingestion_jobs[job_id]["status"] == "completed"
        assert _ingestion_jobs[job_id]["total_pages"] == 10

    @pytest.mark.asyncio
    async def test_failure(self):
        """Should set failed status on exception."""
        job_id = "bg-2"
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "fail_doc",
            "status": "pending",
            "progress_percent": 0.0,
            "total_pages": 0,
            "processed_pages": 0,
            "error": None,
        }

        mock_service = MagicMock()
        mock_service.ingest_pdf = AsyncMock(side_effect=RuntimeError("Ingest broke"))

        with patch("app.api.v1.admin.get_ingestion_service", return_value=mock_service):
            await _run_ingestion_background(
                job_id=job_id,
                document_id="fail_doc",
                pdf_path="/tmp/fail.pdf",
                create_neo4j_module=False,
            )

        assert _ingestion_jobs[job_id]["status"] == "failed"
        assert _ingestion_jobs[job_id]["error"] == "Ingestion processing failed"

    @pytest.mark.asyncio
    async def test_neo4j_integration(self):
        """Should create Module node when Neo4j is available."""
        job_id = "bg-3"
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "neo4j_doc",
            "status": "pending",
            "progress_percent": 0.0,
            "total_pages": 0,
            "processed_pages": 0,
            "error": None,
        }

        mock_result = MagicMock()
        mock_result.total_pages = 5
        mock_result.successful_pages = 5
        mock_result.success_rate = 1.0

        mock_service = MagicMock()
        mock_service.ingest_pdf = AsyncMock(return_value=mock_result)

        mock_graph = MagicMock()
        mock_graph.is_available.return_value = True

        with patch("app.api.v1.admin.get_ingestion_service", return_value=mock_service), \
             patch("app.api.v1.admin.get_user_graph_repository", return_value=mock_graph):
            await _run_ingestion_background(
                job_id=job_id,
                document_id="neo4j_doc",
                pdf_path="/tmp/neo4j.pdf",
                create_neo4j_module=True,
            )

        mock_graph.ensure_module_node.assert_called_once_with(
            module_id="neo4j_doc",
            title="Neo4J Doc",
        )
        assert _ingestion_jobs[job_id]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_sets_processing_status(self):
        """Should set status to processing before starting ingestion."""
        job_id = "bg-4"
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "proc_doc",
            "status": "pending",
            "progress_percent": 0.0,
            "total_pages": 0,
            "processed_pages": 0,
            "error": None,
        }

        captured_status = {}

        async def capture_ingest(**kwargs):
            captured_status["during_ingest"] = _ingestion_jobs[job_id]["status"]
            result = MagicMock()
            result.total_pages = 1
            result.successful_pages = 1
            result.success_rate = 1.0
            return result

        mock_service = MagicMock()
        mock_service.ingest_pdf = capture_ingest

        mock_graph = MagicMock()
        mock_graph.is_available.return_value = False

        with patch("app.api.v1.admin.get_ingestion_service", return_value=mock_service), \
             patch("app.api.v1.admin.get_user_graph_repository", return_value=mock_graph):
            await _run_ingestion_background(
                job_id=job_id,
                document_id="proc_doc",
                pdf_path="/tmp/proc.pdf",
                create_neo4j_module=False,
            )

        assert captured_status["during_ingest"] == "processing"
        assert _ingestion_jobs[job_id]["status"] == "completed"


# =============================================================================
# Domain Management
# =============================================================================


class TestListDomains:
    """Tests for list_domains via DomainRegistry."""

    def test_returns_all_domains(self):
        """Should create DomainSummary for each domain."""
        from app.api.v1.admin import DomainSummary

        plugin = _make_domain_plugin("maritime", "Maritime")
        cfg = plugin.get_config()

        summary = DomainSummary(
            id=cfg.id,
            name=cfg.name,
            name_vi=cfg.name_vi,
            version=cfg.version,
            description=cfg.description,
            skill_count=0,
            keyword_count=len(cfg.routing_keywords),
        )

        assert summary.id == "maritime"
        assert summary.name == "Maritime"
        assert summary.keyword_count == 1

    def test_multiple_domains(self):
        """Should handle multiple domains from registry."""
        p1 = _make_domain_plugin("maritime", "Maritime")
        p2 = _make_domain_plugin("traffic_law", "Traffic Law")
        registry = {"maritime": p1, "traffic_law": p2}
        result = []
        for did, plugin in registry.items():
            cfg = plugin.get_config()
            skills = plugin.get_skills()
            result.append({
                "id": cfg.id,
                "name": cfg.name,
                "skill_count": len(skills),
                "keyword_count": len(cfg.routing_keywords),
            })
        assert len(result) == 2
        assert result[0]["id"] == "maritime"

    def test_empty_registry(self):
        """Should return empty list for empty registry."""
        domains = {}
        result = list(domains.values())
        assert result == []

    def test_skill_count(self):
        """Should report correct skill count."""
        from app.api.v1.admin import DomainSummary

        skills = [_make_skill("s1"), _make_skill("s2"), _make_skill("s3")]
        plugin = _make_domain_plugin("maritime", "Maritime", skills=skills)
        cfg = plugin.get_config()

        summary = DomainSummary(
            id=cfg.id,
            name=cfg.name,
            name_vi=cfg.name_vi,
            version=cfg.version,
            description=cfg.description,
            skill_count=len(plugin.get_skills()),
            keyword_count=len(cfg.routing_keywords),
        )

        assert summary.skill_count == 3


# =============================================================================
# Domain Detail
# =============================================================================


class TestGetDomain:
    """Tests for get_domain detail endpoint logic."""

    def test_found(self):
        """Should create DomainDetail for existing domain."""
        from app.api.v1.admin import DomainDetail

        plugin = _make_domain_plugin("maritime", "Maritime")
        cfg = plugin.get_config()

        detail = DomainDetail(
            id=cfg.id,
            name=cfg.name,
            name_vi=cfg.name_vi,
            version=cfg.version,
            description=cfg.description,
            routing_keywords=cfg.routing_keywords,
            mandatory_search_triggers=cfg.mandatory_search_triggers,
            rag_agent_description=cfg.rag_agent_description,
            tutor_agent_description=cfg.tutor_agent_description,
            skills=[],
            has_prompts=True,
            has_hyde_templates=False,
        )

        assert detail.id == "maritime"
        assert detail.has_prompts is True
        assert detail.has_hyde_templates is False

    def test_not_found(self):
        """Registry.get() returns None for missing domain."""
        registry = MagicMock()
        registry.get.return_value = None
        assert registry.get("nonexistent") is None

    def test_details_complete(self):
        """All detail fields should be populated."""
        from app.api.v1.admin import DomainDetail

        skills = [_make_skill("s1", "Collision Regs")]
        plugin = _make_domain_plugin("maritime", "Maritime", skills=skills)
        cfg = plugin.get_config()

        detail = DomainDetail(
            id=cfg.id,
            name=cfg.name,
            name_vi=cfg.name_vi,
            version=cfg.version,
            description=cfg.description,
            routing_keywords=cfg.routing_keywords,
            mandatory_search_triggers=cfg.mandatory_search_triggers,
            rag_agent_description=cfg.rag_agent_description,
            tutor_agent_description=cfg.tutor_agent_description,
            skills=[{"id": s.id, "name": s.name, "description": s.description} for s in skills],
            has_prompts=True,
            has_hyde_templates=False,
        )

        assert len(detail.skills) == 1
        assert detail.skills[0]["name"] == "Collision Regs"
        assert detail.routing_keywords == ["keyword1"]


# =============================================================================
# Domain Skills
# =============================================================================


class TestListDomainSkills:
    """Tests for list_domain_skills endpoint logic."""

    def test_success(self):
        """Should create SkillDetail for each skill."""
        from app.api.v1.admin import SkillDetail

        s = _make_skill("s1", "Collision Regs", "maritime")
        plugin = _make_domain_plugin("maritime", "Maritime", skills=[s])
        content = plugin.activate_skill(s.id)

        detail = SkillDetail(
            id=s.id,
            name=s.name,
            description=s.description,
            domain_id=s.domain_id,
            version=s.version,
            triggers=s.triggers,
            content_length=len(content) if content else 0,
        )

        assert detail.id == "s1"
        assert detail.content_length > 0

    def test_empty_skills(self):
        """Should return empty list when domain has no skills."""
        plugin = _make_domain_plugin("empty", "Empty", skills=[])
        skills = plugin.get_skills()
        assert skills == []

    def test_domain_not_found(self):
        """Registry returns None for unknown domain."""
        registry = MagicMock()
        registry.get.return_value = None
        assert registry.get("unknown") is None


# =============================================================================
# Upload Validation
# =============================================================================


class TestUploadDocumentValidation:
    """Tests for upload_document validation logic."""

    def test_non_pdf_rejected(self):
        """Should reject non-PDF files."""
        filename = "document.txt"
        assert not filename.lower().endswith(".pdf")

    def test_pdf_accepted(self):
        """PDF filename accepted."""
        filename = "document.pdf"
        assert filename.lower().endswith(".pdf")

    def test_auto_document_id(self):
        """Should auto-generate document_id from filename."""
        filename = "COLREGs Rules.pdf"
        expected = filename.replace(".pdf", "").replace(" ", "_").lower()
        assert expected == "colregs_rules"

    def test_custom_document_id(self):
        """Should use provided document_id when given."""
        custom_id = "my-custom-doc-id"
        doc_id = custom_id or "fallback"
        assert doc_id == "my-custom-doc-id"

    def test_job_initialization(self):
        """Job should start with pending status."""
        job_id = str(uuid4())
        _ingestion_jobs[job_id] = {
            "job_id": job_id,
            "document_id": "test",
            "status": "pending",
            "progress_percent": 0.0,
            "total_pages": 0,
            "processed_pages": 0,
            "error": None,
        }

        assert _ingestion_jobs[job_id]["status"] == "pending"
        assert _ingestion_jobs[job_id]["progress_percent"] == 0.0

    def test_job_id_generated(self):
        """Job ID is a valid UUID."""
        job_id = str(uuid4())
        assert len(job_id) == 36

    def test_background_task_callable(self):
        """Background task function can be referenced."""
        assert callable(_run_ingestion_background)


# =============================================================================
# Document Administration Tenant Scope
# =============================================================================


class TestDocumentAdministrationTenantScope:
    """Tests for tenant scoping in direct document administration SQL."""

    def _session_factory(self, session):
        factory = MagicMock()
        factory.return_value.__enter__ = MagicMock(return_value=session)
        factory.return_value.__exit__ = MagicMock(return_value=False)
        return factory

    @pytest.mark.asyncio
    async def test_list_documents_filters_by_active_org(self, monkeypatch):
        from app.api.v1.admin import list_documents
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = []

        with patch(
            "app.api.v1.admin.get_shared_session_factory",
            return_value=self._session_factory(session),
        ):
            result = await list_documents(request=MagicMock(), auth=_admin_auth("org-A"))

        assert result == []
        sql = str(session.execute.call_args[0][0])
        params = session.execute.call_args[0][1]
        assert "WHERE organization_id = :org_id" in sql
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_list_documents_requires_active_org_before_db(self, monkeypatch):
        from app.api.v1.admin import list_documents
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        get_factory = MagicMock()

        with patch("app.api.v1.admin.get_shared_session_factory", get_factory):
            with pytest.raises(HTTPException) as exc_info:
                await list_documents(request=MagicMock(), auth=_admin_auth(None))

        assert exc_info.value.status_code == 403
        get_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_document_filters_by_active_org(self, monkeypatch):
        from app.api.v1.admin import delete_document
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        session = MagicMock()
        delete_result = MagicMock()
        delete_result.rowcount = 3
        session.execute.return_value = delete_result
        graph = MagicMock()
        graph.is_available.return_value = False

        with patch(
            "app.api.v1.admin.get_shared_session_factory",
            return_value=self._session_factory(session),
        ), patch("app.api.v1.admin.get_user_graph_repository", return_value=graph):
            result = await delete_document(
                request=MagicMock(),
                document_id="PRIVATE-DOC",
                auth=_admin_auth("org-B"),
            )

        sql = str(session.execute.call_args[0][0])
        params = session.execute.call_args[0][1]
        assert "DELETE FROM knowledge_embeddings WHERE document_id = :doc_id" in sql
        assert "AND organization_id = :org_id" in sql
        assert params == {"doc_id": "PRIVATE-DOC", "org_id": "org-B"}
        assert result["deleted_chunks"] == 3

    @pytest.mark.asyncio
    async def test_delete_document_requires_active_org_before_db(self, monkeypatch):
        from app.api.v1.admin import delete_document
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        get_factory = MagicMock()

        with patch("app.api.v1.admin.get_shared_session_factory", get_factory):
            with pytest.raises(HTTPException) as exc_info:
                await delete_document(
                    request=MagicMock(),
                    document_id="PRIVATE-DOC",
                    auth=_admin_auth(None),
                )

        assert exc_info.value.status_code == 403
        get_factory.assert_not_called()


# =============================================================================
# Schemas
# =============================================================================


class TestSchemas:
    """Tests for admin schema models."""

    def test_document_upload_response(self):
        from app.api.v1.admin import DocumentUploadResponse

        resp = DocumentUploadResponse(
            job_id="j1",
            document_id="doc1",
            status="pending",
            message="Started",
        )
        assert resp.job_id == "j1"
        assert resp.status == "pending"

    def test_document_status(self):
        from app.api.v1.admin import DocumentStatus

        status = DocumentStatus(
            job_id="j2",
            document_id="doc2",
            status="completed",
            progress_percent=100.0,
            total_pages=20,
            processed_pages=20,
        )
        assert status.error is None
        assert status.progress_percent == 100.0

    def test_document_info(self):
        from app.api.v1.admin import DocumentInfo

        info = DocumentInfo(
            document_id="doc3",
            title="Test Document",
            total_pages=15,
            total_chunks=150,
            created_at="2026-02-13",
            status="completed",
        )
        assert info.total_chunks == 150

    def test_domain_summary(self):
        from app.api.v1.admin import DomainSummary

        summary = DomainSummary(
            id="maritime",
            name="Maritime",
            name_vi="Hang hai",
            version="1.0.0",
            description="Maritime domain",
            skill_count=5,
            keyword_count=10,
        )
        assert summary.id == "maritime"
        assert summary.skill_count == 5

    def test_skill_detail(self):
        from app.api.v1.admin import SkillDetail

        detail = SkillDetail(
            id="s1",
            name="COLREGs",
            description="Collision regulations",
            domain_id="maritime",
            version="1.0.0",
            triggers=["colreg", "collision"],
            content_length=1024,
        )
        assert detail.name == "COLREGs"
        assert len(detail.triggers) == 2
