"""
API Dependencies - Dependency Injection for FastAPI
Requirements: 1.3

Provides reusable dependencies for authentication, database sessions, etc.
LMS Integration: Added RequireAdmin for admin-only endpoints.
"""
from typing import Annotated, Optional

from fastapi import Depends, HTTPException

from app.core.security import (
    AuthenticatedUser,
    optional_auth,
    require_auth,
)


# =============================================================================
# Authentication Dependencies
# =============================================================================

# Require authentication (API Key or JWT)
RequireAuth = Annotated[AuthenticatedUser, Depends(require_auth)]

# Optional authentication
OptionalAuth = Annotated[Optional[AuthenticatedUser], Depends(optional_auth)]


# =============================================================================
# Role-Based Access Control
# =============================================================================

async def _require_admin(auth: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
    """
    Require admin role for endpoint access.
    
    LMS Integration: Only users with role='admin' can access.
    
    Raises:
        HTTPException 403: If user is not admin
    """
    if auth.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Your role: " + auth.role
        )
    return auth

# Require admin role
RequireAdmin = Annotated[AuthenticatedUser, Depends(_require_admin)]


# =============================================================================
# Database Dependencies (Placeholder)
# =============================================================================

# TODO: Add database session dependency
# async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
#     async with async_session_maker() as session:
#         yield session

# DBSession = Annotated[AsyncSession, Depends(get_db_session)]


# =============================================================================
# Service Dependencies (Placeholder)
# =============================================================================

# TODO: Add service dependencies
# async def get_memory_engine() -> IMemoryEngine:
#     return MemoriEngine()

# MemoryEngine = Annotated[IMemoryEngine, Depends(get_memory_engine)]

# async def get_knowledge_graph() -> IKnowledgeGraph:
#     return KnowledgeGraphRepository()

# KnowledgeGraph = Annotated[IKnowledgeGraph, Depends(get_knowledge_graph)]

