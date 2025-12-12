"""
API Version 1 Router
Aggregates all v1 endpoints
"""
from fastapi import APIRouter

from app.api.v1.chat import router as chat_router
from app.api.v1.chat_stream import router as chat_stream_router  # Streaming API
from app.api.v1.health import router as health_router
from app.api.v1.insights import router as insights_router  # Insights API
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.memories import router as memories_router
from app.api.v1.sources import router as sources_router
from app.api.v1.admin import router as admin_router  # Admin Document API

router = APIRouter(tags=["v1"])

# Include sub-routers
router.include_router(chat_router)
router.include_router(chat_stream_router)  # POST /chat/stream
router.include_router(health_router)
router.include_router(insights_router)  # GET /insights/{user_id}
router.include_router(knowledge_router)
router.include_router(memories_router)
router.include_router(sources_router)
router.include_router(admin_router)  # POST/GET/DELETE /admin/documents


@router.get("/")
async def api_v1_root():
    """API v1 root endpoint"""
    return {"api": "v1", "status": "active"}
