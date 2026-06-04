"""
Organization Knowledge Base Management API — Sprint 190: "Kho Tri Thức"

Enables org admins to upload, list, and delete PDF documents for their
organization's knowledge base. Full lifecycle tracking with audit logging.

Triple gate: enable_org_knowledge AND enable_multi_tenant AND org admin check.
"""

import logging
import os
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import AuthenticatedUser, is_platform_admin, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations", tags=["Org Knowledge"])

# Constants
ALLOWED_MIME_TYPES = ["application/pdf"]


# =============================================================================
# Response Models
# =============================================================================

class OrgDocumentResponse(BaseModel):
    """Document tracking record."""
    document_id: str
    organization_id: str
    filename: str
    file_size_bytes: Optional[int] = None
    status: str  # uploading | processing | ready | failed | deleted
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
    uploaded_by: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OrgDocumentListResponse(BaseModel):
    """Paginated document list."""
    documents: list[OrgDocumentResponse]
    total: int


# =============================================================================
# Auth Helpers
# =============================================================================

async def _require_org_knowledge_admin(auth: AuthenticatedUser, org_id: str) -> str:
    """
    Triple gate: feature flag + multi_tenant + org admin/owner or platform admin.
    Returns user_id on success.
    Sprint 217: Uses require_auth dependency — no header trust.
    """
    settings = get_settings()

    if not settings.enable_org_knowledge:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org knowledge management is disabled",
        )

    if not settings.enable_multi_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-tenant mode is required",
        )

    # Platform admin bypass
    if is_platform_admin(auth):
        return auth.user_id

    # Check org admin/owner
    if not settings.enable_org_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    active_org_id = getattr(auth, "organization_id", None)
    if not active_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context required for org knowledge access",
        )
    if active_org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active organization does not match route organization",
        )

    from app.repositories.organization_repository import get_organization_repository
    repo = get_organization_repository()
    org_role = repo.get_user_org_role(auth.user_id, org_id)
    if org_role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin role required",
        )

    return auth.user_id


async def _require_org_member(auth: AuthenticatedUser, org_id: str) -> str:
    """Require org membership (any role) or platform admin. Returns user_id.
    Sprint 217: Uses require_auth dependency — no header trust.
    """
    settings = get_settings()

    if not settings.enable_org_knowledge or not settings.enable_multi_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org knowledge management is disabled",
        )

    if is_platform_admin(auth):
        return auth.user_id

    active_org_id = getattr(auth, "organization_id", None)
    if not active_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context required for org knowledge access",
        )
    if active_org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active organization does not match route organization",
        )

    from app.repositories.organization_repository import get_organization_repository
    repo = get_organization_repository()
    if not repo.is_user_in_org(auth.user_id, org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    return auth.user_id


# =============================================================================
# DB Helpers
# =============================================================================

async def _get_pool():
    """Get asyncpg connection pool."""
    from app.core.database import get_asyncpg_pool
    return await get_asyncpg_pool()


async def _insert_document(pool, doc_id: str, org_id: str, filename: str,
                           file_size: int, user_id: str) -> None:
    """Insert a new document tracking record."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO organization_documents
                (document_id, organization_id, filename, file_size_bytes, status, uploaded_by)
            VALUES ($1, $2, $3, $4, 'uploading', $5)
            """,
            doc_id, org_id, filename, file_size, user_id,
        )


async def _update_document_status(pool, doc_id: str, org_id: str, new_status: str,
                                  page_count: Optional[int] = None,
                                  chunk_count: Optional[int] = None,
                                  error_message: Optional[str] = None) -> None:
    """Update document status and metadata."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE organization_documents
            SET status = $3, page_count = $4, chunk_count = $5,
                error_message = $6, updated_at = NOW()
            WHERE document_id = $1 AND organization_id = $2
            """,
            doc_id, org_id, new_status, page_count, chunk_count, error_message,
        )


async def _get_document(pool, doc_id: str, org_id: str) -> Optional[dict]:
    """Get a single document by ID, scoped to org."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT document_id, organization_id, filename, file_size_bytes,
                   status, page_count, chunk_count, error_message, uploaded_by,
                   created_at, updated_at
            FROM organization_documents
            WHERE document_id = $1 AND organization_id = $2 AND status != 'deleted'
            """,
            doc_id, org_id,
        )
        return dict(row) if row else None


async def _list_documents(pool, org_id: str, status_filter: Optional[str] = None) -> list[dict]:
    """List documents for an org, optionally filtered by status."""
    async with pool.acquire() as conn:
        if status_filter:
            rows = await conn.fetch(
                """
                SELECT document_id, organization_id, filename, file_size_bytes,
                       status, page_count, chunk_count, error_message, uploaded_by,
                       created_at, updated_at
                FROM organization_documents
                WHERE organization_id = $1 AND status = $2
                ORDER BY created_at DESC
                """,
                org_id, status_filter,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT document_id, organization_id, filename, file_size_bytes,
                       status, page_count, chunk_count, error_message, uploaded_by,
                       created_at, updated_at
                FROM organization_documents
                WHERE organization_id = $1 AND status != 'deleted'
                ORDER BY created_at DESC
                """,
                org_id,
            )
        return [dict(r) for r in rows]


async def _count_documents(pool, org_id: str, status_filter: Optional[str] = None) -> int:
    """Count documents for an org."""
    async with pool.acquire() as conn:
        if status_filter:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM organization_documents WHERE organization_id = $1 AND status = $2",
                org_id, status_filter,
            )
        return await conn.fetchval(
            "SELECT COUNT(*) FROM organization_documents WHERE organization_id = $1 AND status != 'deleted'",
            org_id,
        )


async def _audit_log(event_type: str, user_id: str, org_id: str, metadata: Optional[dict] = None) -> None:
    """Fire-and-forget audit logging. Reuses auth_audit pattern."""
    try:
        from app.auth.auth_audit import log_auth_event
        await log_auth_event(
            event_type=event_type,
            user_id=user_id,
            organization_id=org_id,
            result="success",
            metadata=metadata,
        )
    except Exception as e:
        logger.warning("Failed to log audit event %s: %s", event_type, e)


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/{org_id}/knowledge/upload", response_model=OrgDocumentResponse)
@limiter.limit("5/minute")
async def upload_org_document(
    request: Request,
    org_id: str,
    file: UploadFile = File(...),
    auth: AuthenticatedUser = Depends(require_auth),
) -> OrgDocumentResponse:
    """
    Upload a PDF document to the organization's knowledge base.

    Pipeline:
    1. Auth + validation (triple gate)
    2. Save temp file → ingest via MultimodalIngestionService
    3. Track lifecycle in organization_documents table
    4. Audit log
    """
    user_id = await _require_org_knowledge_admin(auth, org_id)
    settings = get_settings()

    # Validate file type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Only PDF files are accepted. Got: {file.content_type}",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file extension. Only .pdf files are accepted.",
        )

    # Read and validate size
    content = await file.read()
    max_size = settings.org_knowledge_max_file_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.org_knowledge_max_file_size_mb}MB. Got: {len(content) / 1024 / 1024:.2f}MB",
        )

    document_id = str(uuid.uuid4())
    pool = await _get_pool()

    # Insert tracking record
    await _insert_document(pool, document_id, org_id, file.filename, len(content), user_id)

    # Save temp file and process
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        # Update status → processing
        await _update_document_status(pool, document_id, org_id, "processing")

        # Ingest via existing service
        from app.services.multimodal_ingestion_service import get_ingestion_service
        service = get_ingestion_service()
        result = await service.ingest_pdf(
            pdf_path=tmp_path,
            document_id=document_id,
            organization_id=org_id,
        )

        # Update status → ready
        # Use pages_processed (actual pages attempted) instead of total_pages
        # When max_pages is set, total_pages is the full PDF but only a subset was processed
        await _update_document_status(
            pool, document_id, org_id, "ready",
            page_count=result.pages_processed if result.pages_processed > 0 else result.total_pages,
            chunk_count=result.successful_pages,
        )

        logger.info(
            "Org knowledge upload completed: org=%s doc=%s pages=%d/%d",
            org_id, document_id, result.successful_pages, result.total_pages,
        )

        # Audit log
        await _audit_log("org_knowledge_upload", user_id, org_id, {
            "document_id": document_id,
            "filename": file.filename,
            "pages": result.total_pages,
        })

        doc = await _get_document(pool, document_id, org_id)
        if doc:
            return OrgDocumentResponse(
                document_id=doc["document_id"],
                organization_id=doc["organization_id"],
                filename=doc["filename"],
                file_size_bytes=doc["file_size_bytes"],
                status=doc["status"],
                page_count=doc["page_count"],
                chunk_count=doc["chunk_count"],
                error_message=doc["error_message"],
                uploaded_by=doc["uploaded_by"],
                created_at=str(doc["created_at"]) if doc["created_at"] else None,
                updated_at=str(doc["updated_at"]) if doc["updated_at"] else None,
            )

        return OrgDocumentResponse(
            document_id=document_id,
            organization_id=org_id,
            filename=file.filename,
            file_size_bytes=len(content),
            status="ready",
            page_count=result.pages_processed if result.pages_processed > 0 else result.total_pages,
            chunk_count=result.successful_pages,
            uploaded_by=user_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Org knowledge upload failed: org=%s err=%s", org_id, e)
        await _update_document_status(
            pool, document_id, org_id, "failed",
            error_message=str(e)[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document ingestion failed",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/{org_id}/knowledge/documents", response_model=OrgDocumentListResponse)
@limiter.limit("30/minute")
async def list_org_documents(
    request: Request,
    org_id: str,
    doc_status: Optional[str] = None,
    auth: AuthenticatedUser = Depends(require_auth),
) -> OrgDocumentListResponse:
    """List documents in the organization's knowledge base. Any org member can view."""
    await _require_org_member(auth, org_id)

    pool = await _get_pool()
    docs = await _list_documents(pool, org_id, status_filter=doc_status)
    total = await _count_documents(pool, org_id, status_filter=doc_status)

    return OrgDocumentListResponse(
        documents=[
            OrgDocumentResponse(
                document_id=d["document_id"],
                organization_id=d["organization_id"],
                filename=d["filename"],
                file_size_bytes=d["file_size_bytes"],
                status=d["status"],
                page_count=d["page_count"],
                chunk_count=d["chunk_count"],
                error_message=d["error_message"],
                uploaded_by=d["uploaded_by"],
                created_at=str(d["created_at"]) if d["created_at"] else None,
                updated_at=str(d["updated_at"]) if d["updated_at"] else None,
            )
            for d in docs
        ],
        total=total,
    )


@router.get("/{org_id}/knowledge/documents/{doc_id}", response_model=OrgDocumentResponse)
@limiter.limit("30/minute")
async def get_org_document(
    request: Request,
    org_id: str,
    doc_id: str,
    auth: AuthenticatedUser = Depends(require_auth),
) -> OrgDocumentResponse:
    """Get details of a specific document. Any org member can view."""
    await _require_org_member(auth, org_id)

    pool = await _get_pool()
    doc = await _get_document(pool, doc_id, org_id)

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in organization '{org_id}'",
        )

    return OrgDocumentResponse(
        document_id=doc["document_id"],
        organization_id=doc["organization_id"],
        filename=doc["filename"],
        file_size_bytes=doc["file_size_bytes"],
        status=doc["status"],
        page_count=doc["page_count"],
        chunk_count=doc["chunk_count"],
        error_message=doc["error_message"],
        uploaded_by=doc["uploaded_by"],
        created_at=str(doc["created_at"]) if doc["created_at"] else None,
        updated_at=str(doc["updated_at"]) if doc["updated_at"] else None,
    )


@router.delete("/{org_id}/knowledge/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_org_document(
    request: Request,
    org_id: str,
    doc_id: str,
    auth: AuthenticatedUser = Depends(require_auth),
) -> None:
    """
    Soft-delete a document: remove embeddings from knowledge_embeddings,
    mark document as 'deleted' in tracking table.
    """
    user_id = await _require_org_knowledge_admin(auth, org_id)

    pool = await _get_pool()

    # Check document exists
    doc = await _get_document(pool, doc_id, org_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in organization '{org_id}'",
        )

    # Delete embeddings + mark as deleted in a single transaction
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.execute(
                "DELETE FROM knowledge_embeddings WHERE document_id = $1 AND organization_id = $2",
                doc_id, org_id,
            )
            logger.info("Deleted embeddings: %s (org=%s, doc=%s)", result, org_id, doc_id)
            await conn.execute(
                """
                UPDATE organization_documents
                SET status = 'deleted', updated_at = NOW()
                WHERE document_id = $1 AND organization_id = $2
                """,
                doc_id, org_id,
            )

    logger.info("Org knowledge deleted: org=%s doc=%s user=%s", org_id, doc_id, user_id)

    # Audit log
    await _audit_log("org_knowledge_delete", user_id, org_id, {
        "document_id": doc_id,
        "filename": doc.get("filename"),
    })
