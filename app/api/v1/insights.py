"""
Insights API for Maritime AI Tutor v0.5
CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN

API endpoints for accessing user behavioral insights.

Requirements: 4.3, 4.4, 5.1, 5.2
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import RequireAuth
from app.repositories.semantic_memory_repository import SemanticMemoryRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


# ========== Response Models ==========

class InsightItem(BaseModel):
    """Single insight item in response."""
    id: str
    category: str  # learning_style, knowledge_gap, goal_evolution, habit, preference
    content: str
    sub_topic: Optional[str] = None
    confidence: float
    created_at: datetime
    updated_at: Optional[datetime] = None
    evolution_notes: List[str] = []
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class InsightListResponse(BaseModel):
    """Response for GET /insights/{user_id}."""
    data: List[InsightItem]
    total: int
    categories: dict  # Count per category


# ========== API Endpoints ==========

@router.get("/{user_id}", response_model=InsightListResponse)
async def get_user_insights(
    user_id: str,
    category: Optional[str] = None,
    auth: RequireAuth = None
) -> InsightListResponse:
    """
    Get all behavioral insights for a user.
    
    Returns a list of insights with category, content, confidence, and evolution history.
    
    Args:
        user_id: User ID to get insights for
        category: Optional filter by category (learning_style, knowledge_gap, etc.)
        
    Returns:
        InsightListResponse with list of insights and category breakdown
        
    **Validates: Requirements 4.3, 4.4, 5.1, 5.2**
    """
    try:
        repository = SemanticMemoryRepository()
        
        # Get all insights for user (memory_type = 'insight')
        insights = repository.get_user_insights(user_id)
        
        # Transform to response format
        items = []
        category_counts = {}
        
        for insight in insights:
            insight_category = insight.metadata.get("insight_category", "unknown")
            
            # Filter by category if specified
            if category and insight_category != category:
                continue
            
            # Count categories
            category_counts[insight_category] = category_counts.get(insight_category, 0) + 1
            
            items.append(InsightItem(
                id=str(insight.id),
                category=insight_category,
                content=insight.content,
                sub_topic=insight.metadata.get("sub_topic"),
                confidence=insight.metadata.get("confidence", 0.8),
                created_at=insight.created_at,
                updated_at=insight.updated_at,
                evolution_notes=insight.metadata.get("evolution_notes", [])
            ))
        
        logger.info(f"Retrieved {len(items)} insights for user {user_id}")
        
        return InsightListResponse(
            data=items,
            total=len(items),
            categories=category_counts
        )
        
    except Exception as e:
        logger.error(f"Failed to get insights for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
