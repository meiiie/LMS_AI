"""Host action audit endpoints."""
from fastapi import APIRouter, HTTPException, Request

from app.api.deps import RequireAuth
from app.core.rate_limit import limiter
from app.engine.context.host_action_audit import log_host_action_event
from app.engine.context.host_action_result_bridge import publish_host_action_result
from app.models.host_context_schemas import (
    HostActionAuditRequest,
    HostActionAuditResponse,
    HostActionResultRequest,
    HostActionResultResponse,
)

router = APIRouter(prefix="/host-actions", tags=["host-actions"])


@router.post("/audit", response_model=HostActionAuditResponse)
@limiter.limit("120/minute")
async def submit_host_action_audit(
    request: Request,
    body: HostActionAuditRequest,
    auth: RequireAuth,
) -> HostActionAuditResponse:
    await log_host_action_event(
        event_type=body.event_type,
        user_id=auth.user_id,
        action=body.action,
        request_id=body.request_id,
        summary=body.summary,
        organization_id=auth.organization_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        host_type=body.host_type,
        host_name=body.host_name,
        page_type=body.page_type,
        page_title=body.page_title,
        user_role=body.user_role,
        workflow_stage=body.workflow_stage,
        preview_kind=body.preview_kind,
        preview_token=body.preview_token,
        target_type=body.target_type,
        target_id=body.target_id,
        surface=body.surface,
        metadata=body.metadata,
    )
    return HostActionAuditResponse(
        event_type=body.event_type,
        action=body.action,
        request_id=body.request_id,
    )


@router.post("/result", response_model=HostActionResultResponse)
@limiter.limit("120/minute")
async def submit_host_action_result(
    request: Request,
    body: HostActionResultRequest,
    auth: RequireAuth,
) -> HostActionResultResponse:
    """Submit the real host-side result for a pending action request.

    This endpoint is intentionally separate from audit. Audit records what the
    host says happened; result submission resumes an in-flight chat turn when a
    matching waiter exists.
    """

    publication = publish_host_action_result(
        request_id=body.request_id,
        action=body.action,
        success=body.success,
        summary=body.summary,
        error=body.error,
        data=body.data,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
    )
    if publication.status == "identity_mismatch":
        raise HTTPException(status_code=403, detail="Host action result identity mismatch.")
    if publication.status == "action_mismatch":
        raise HTTPException(status_code=409, detail="Host action result action mismatch.")

    matched = publication.status == "accepted"
    return HostActionResultResponse(
        status="accepted" if matched else "ignored",
        action=body.action,
        request_id=body.request_id,
        matched=matched,
        reason=None if matched else publication.reason,
    )
