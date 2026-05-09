"""Host action audit endpoints."""
from fastapi import APIRouter, Request

from app.api.deps import RequireAuth
from app.core.rate_limit import limiter
from app.engine.context.host_action_audit import log_host_action_event
from app.models.host_context_schemas import HostActionAuditRequest, HostActionAuditResponse

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
