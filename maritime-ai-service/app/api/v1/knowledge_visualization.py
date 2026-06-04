"""
Knowledge Visualization API — Sprint 191: "Mắt Tri Thức"

3 endpoints for visualizing org knowledge base:
- GET /scatter — PCA/t-SNE 2D/3D scatter
- GET /graph — Knowledge graph (Mermaid)
- POST /rag-flow — RAG retrieval simulation

Triple gate: enable_knowledge_visualization + enable_multi_tenant + org membership.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import AuthenticatedUser, is_platform_admin, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations", tags=["Knowledge Visualization"])


# =============================================================================
# Request Models
# =============================================================================

class RagFlowRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=50)


# =============================================================================
# Auth Helper
# =============================================================================

async def _require_org_member_viz(auth: AuthenticatedUser, org_id: str) -> str:
    """Triple gate: feature flag + multi_tenant + org membership.
    Sprint 217: Uses require_auth dependency — no header trust.
    """
    settings = get_settings()

    if not settings.enable_knowledge_visualization:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Knowledge visualization is disabled",
        )

    if not settings.enable_multi_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-tenant mode is required",
        )

    # Platform admin bypass
    if is_platform_admin(auth):
        return auth.user_id

    active_org_id = getattr(auth, "organization_id", None)
    if not active_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization context required for knowledge visualization",
        )
    if active_org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active organization does not match route organization",
        )

    # Check org membership
    from app.repositories.organization_repository import get_organization_repository
    repo = get_organization_repository()
    if not repo.is_user_in_org(auth.user_id, org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    return auth.user_id


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/{org_id}/knowledge/visualize/scatter")
@limiter.limit("10/minute")
async def get_knowledge_scatter(
    request: Request,
    org_id: str,
    method: str = "pca",
    dimensions: int = 2,
    limit: int = 500,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Compute PCA or t-SNE scatter from org knowledge embeddings."""
    await _require_org_member_viz(auth, org_id)

    # Validate params
    if method not in ("pca", "tsne"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="method must be 'pca' or 'tsne'",
        )
    if dimensions not in (2, 3):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dimensions must be 2 or 3",
        )
    if limit < 10 or limit > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 10 and 2000",
        )

    from app.services.knowledge_visualization_service import compute_scatter
    result = await compute_scatter(org_id, method=method, dimensions=dimensions, limit=limit)
    return result.model_dump()


@router.get("/{org_id}/knowledge/visualize/graph")
@limiter.limit("10/minute")
async def get_knowledge_graph(
    request: Request,
    org_id: str,
    max_nodes: int = 50,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Build knowledge graph from org documents and chunks."""
    await _require_org_member_viz(auth, org_id)

    if max_nodes < 5 or max_nodes > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_nodes must be between 5 and 200",
        )

    from app.services.knowledge_visualization_service import compute_knowledge_graph
    result = await compute_knowledge_graph(org_id, max_nodes=max_nodes)
    return result.model_dump()


@router.post("/{org_id}/knowledge/visualize/rag-flow")
@limiter.limit("5/minute")
async def simulate_rag_flow_endpoint(
    request: Request,
    org_id: str,
    body: RagFlowRequest,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Simulate RAG retrieval pipeline for a query."""
    await _require_org_member_viz(auth, org_id)

    from app.services.knowledge_visualization_service import simulate_rag_flow
    result = await simulate_rag_flow(org_id, query=body.query, top_k=body.top_k)
    return result.model_dump()
