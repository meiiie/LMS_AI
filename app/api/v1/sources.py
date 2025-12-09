"""
Source Details API - Get detailed source information for PDF highlighting.

Feature: source-highlight-citation
Validates: Requirements 5.1, 5.2, 5.3

This endpoint provides full source metadata including bounding boxes
for frontend PDF highlighting functionality.
"""
import logging
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level pool for async operations
_pool: Optional[asyncpg.Pool] = None


def _get_asyncpg_url() -> str:
    """Convert SQLAlchemy URL to asyncpg URL format."""
    url = settings.database_url or ""
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgres://", "postgresql://")
    return url


async def get_pool() -> asyncpg.Pool:
    """Get or create connection pool."""
    global _pool
    if _pool is None:
        db_url = _get_asyncpg_url()
        _pool = await asyncpg.create_pool(
            db_url,
            min_size=1,
            max_size=2
        )
        logger.info("Sources API: Created asyncpg connection pool")
    return _pool

router = APIRouter(prefix="/sources", tags=["sources"])


# =============================================================================
# Response Schemas
# =============================================================================

class SourceDetailResponse(BaseModel):
    """
    Detailed source information for PDF highlighting.
    
    Feature: source-highlight-citation
    Validates: Requirements 5.1, 5.3
    """
    node_id: str = Field(..., description="Unique identifier for the source chunk")
    content: str = Field(..., description="Full text content of the chunk")
    document_id: Optional[str] = Field(default=None, description="Document ID for PDF reference")
    page_number: Optional[int] = Field(default=None, description="Page number in PDF")
    image_url: Optional[str] = Field(default=None, description="URL to page image (Supabase)")
    bounding_boxes: Optional[list[dict]] = Field(
        default=None, 
        description="Normalized coordinates for text highlighting (0-100 percentage)"
    )
    content_type: Optional[str] = Field(default="text", description="Type: text, table, heading, etc.")
    chunk_index: Optional[int] = Field(default=None, description="Index of chunk within page")
    confidence_score: Optional[float] = Field(default=None, description="Extraction confidence (0-1)")
    metadata: Optional[dict] = Field(default=None, description="Additional metadata")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "node_id": "chunk_colregs_p15_001",
                    "content": "Rule 15 - Crossing Situation\nWhen two power-driven vessels are crossing...",
                    "document_id": "colregs_2024",
                    "page_number": 15,
                    "image_url": "https://xyz.supabase.co/storage/v1/object/public/maritime-docs/colregs/page_15.jpg",
                    "bounding_boxes": [
                        {"x0": 10.5, "y0": 45.2, "x1": 90.3, "y1": 52.7}
                    ],
                    "content_type": "text",
                    "chunk_index": 1,
                    "confidence_score": 0.95
                }
            ]
        }
    }


class SourceNotFoundResponse(BaseModel):
    """Response when source is not found."""
    error: str = Field(default="not_found", description="Error type")
    message: str = Field(..., description="Error message")
    node_id: str = Field(..., description="Requested node_id")


# =============================================================================
# API Endpoints
# =============================================================================

@router.get(
    "/{node_id}",
    response_model=SourceDetailResponse,
    responses={
        404: {"model": SourceNotFoundResponse, "description": "Source not found"},
        500: {"description": "Internal server error"}
    },
    summary="Get source details by node_id",
    description="""
    Get detailed source information including bounding boxes for PDF highlighting.
    
    This endpoint is used by the frontend to:
    - Display the exact text location in PDF viewer
    - Jump to the correct page
    - Highlight the relevant text area
    
    **Feature: source-highlight-citation**
    **Validates: Requirements 5.1, 5.2, 5.3**
    """
)
async def get_source_details(node_id: str) -> SourceDetailResponse:
    """
    Get detailed source information by node_id.
    
    Args:
        node_id: Unique identifier for the source chunk
        
    Returns:
        Full source metadata including bounding_boxes
        
    Raises:
        HTTPException 404: If source not found
        HTTPException 500: If database error
    """
    try:
        pool = await get_pool()
        if pool is None:
            logger.error("Database pool not available")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database connection unavailable"
            )
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 
                    id::text as node_id,
                    content,
                    document_id,
                    page_number,
                    image_url,
                    bounding_boxes,
                    content_type,
                    chunk_index,
                    confidence_score,
                    metadata
                FROM knowledge_embeddings
                WHERE id::text = $1
                """,
                node_id
            )
            
            if row is None:
                logger.warning(f"Source not found: {node_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "not_found",
                        "message": f"Source with node_id '{node_id}' not found",
                        "node_id": node_id
                    }
                )
            
            # Parse bounding_boxes from JSONB
            bounding_boxes = None
            if row["bounding_boxes"]:
                import json
                if isinstance(row["bounding_boxes"], str):
                    bounding_boxes = json.loads(row["bounding_boxes"])
                else:
                    bounding_boxes = row["bounding_boxes"]
            
            # Parse metadata from JSONB
            metadata = None
            if row["metadata"]:
                import json
                if isinstance(row["metadata"], str):
                    metadata = json.loads(row["metadata"])
                else:
                    metadata = row["metadata"]
            
            logger.info(f"Retrieved source details for node_id: {node_id}")
            
            return SourceDetailResponse(
                node_id=row["node_id"],
                content=row["content"] or "",
                document_id=row["document_id"],
                page_number=row["page_number"],
                image_url=row["image_url"],
                bounding_boxes=bounding_boxes,
                content_type=row["content_type"] or "text",
                chunk_index=row["chunk_index"],
                confidence_score=row["confidence_score"],
                metadata=metadata
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving source details for {node_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve source details: {str(e)}"
        )


@router.get(
    "/",
    summary="List sources (paginated)",
    description="List all sources with pagination support"
)
async def list_sources(
    document_id: Optional[str] = None,
    page_number: Optional[int] = None,
    limit: int = 20,
    offset: int = 0
) -> dict:
    """
    List sources with optional filtering.
    
    Args:
        document_id: Filter by document ID
        page_number: Filter by page number
        limit: Maximum results (default 20, max 100)
        offset: Pagination offset
        
    Returns:
        Paginated list of sources
    """
    # Clamp limit
    limit = min(max(1, limit), 100)
    
    try:
        pool = await get_pool()
        if pool is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database connection unavailable"
            )
        
        async with pool.acquire() as conn:
            # Build query with optional filters
            conditions = []
            params = []
            param_idx = 1
            
            if document_id:
                conditions.append(f"document_id = ${param_idx}")
                params.append(document_id)
                param_idx += 1
            
            if page_number is not None:
                conditions.append(f"page_number = ${param_idx}")
                params.append(page_number)
                param_idx += 1
            
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            
            # Get total count
            count_query = f"SELECT COUNT(*) as total FROM knowledge_embeddings {where_clause}"
            count_row = await conn.fetchrow(count_query, *params)
            total = count_row["total"] if count_row else 0
            
            # Get paginated results
            params.extend([limit, offset])
            query = f"""
                SELECT 
                    id::text as node_id,
                    document_id,
                    page_number,
                    content_type,
                    chunk_index
                FROM knowledge_embeddings
                {where_clause}
                ORDER BY document_id, page_number, chunk_index
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            
            rows = await conn.fetch(query, *params)
            
            sources = [
                {
                    "node_id": row["node_id"],
                    "document_id": row["document_id"],
                    "page_number": row["page_number"],
                    "content_type": row["content_type"],
                    "chunk_index": row["chunk_index"]
                }
                for row in rows
            ]
            
            return {
                "data": sources,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + len(sources) < total
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error listing sources: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list sources: {str(e)}"
        )
