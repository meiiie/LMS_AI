"""
API Version 1 Router
Aggregates all v1 endpoints
"""
from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.health import router as health_router
from app.api.v1.knowledge import router as knowledge_router

router = APIRouter(tags=["v1"])

# Include sub-routers
router.include_router(chat_router)
router.include_router(health_router)
router.include_router(knowledge_router)


@router.get("/")
async def api_v1_root():
    """API v1 root endpoint"""
    return {"api": "v1", "status": "active"}
