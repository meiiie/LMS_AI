"""
Memory Management API for Maritime AI Tutor v0.4
CHỈ THỊ KỸ THUẬT SỐ 23

API endpoints for managing user memories (facts).

Requirements: 3.1, 3.2, 3.3, 3.4
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import RequireAuth
from app.repositories.semantic_memory_repository import SemanticMemoryRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memories", tags=["memories"])


# ========== Response Models ==========

class MemoryItem(BaseModel):
    """Single memory item in response."""
    id: str
    type: str  # fact_type
    value: str  # content (extracted value)
    created_at: datetime
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MemoryListResponse(BaseModel):
    """Response for GET /memories/{user_id}."""
    data: List[MemoryItem]
    total: int


# ========== API Endpoints ==========

@router.get("/{user_id}", response_model=MemoryListResponse)
async def get_user_memories(
    user_id: str,
    auth: RequireAuth
) -> MemoryListResponse:
    """
    Get all stored facts for a user.
    
    Returns a list of memory items with id, type, value, and created_at.
    
    Args:
        user_id: User ID to get memories for
        
    Returns:
        MemoryListResponse with list of memory items
        
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    try:
        repository = SemanticMemoryRepository()
        
        # Get all facts for user
        facts = repository.get_all_user_facts(user_id)
        
        # Transform to response format
        items = []
        for fact in facts:
            # Extract fact_type and value from metadata/content
            fact_type = fact.metadata.get("fact_type", "unknown")
            
            # Extract value from content (format: "fact_type: value")
            content = fact.content
            if ": " in content:
                value = content.split(": ", 1)[-1]
            else:
                value = content
            
            items.append(MemoryItem(
                id=str(fact.id),
                type=fact_type,
                value=value,
                created_at=fact.created_at
            ))
        
        logger.info(f"Retrieved {len(items)} memories for user {user_id}")
        
        return MemoryListResponse(
            data=items,
            total=len(items)
        )
        
    except Exception as e:
        logger.error(f"Failed to get memories for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
