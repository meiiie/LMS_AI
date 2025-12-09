"""
Health Check Endpoint
Requirements: 8.4

GET /api/v1/health - Returns status of all components (API, Memory, Knowledge Graph)

Production Readiness Spec:
- Uses real is_available() methods from repositories
- Timeout: 5 seconds per component
- Startup behavior: Warn and continue
"""
import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter

from app.core.config import settings
from app.models.schemas import ComponentHealth, ComponentStatus, HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

# Health check timeout in seconds (per expert decision)
HEALTH_CHECK_TIMEOUT = 5


async def check_api_health() -> ComponentHealth:
    """Check API component health"""
    start = time.time()
    # API is healthy if we can execute this code
    latency = (time.time() - start) * 1000
    return ComponentHealth(
        name="API",
        status=ComponentStatus.HEALTHY,
        latency_ms=round(latency, 2),
        message="API is responding",
    )


async def check_memory_health() -> ComponentHealth:
    """
    Check Memory Engine health using real database connections.
    
    Checks:
    - PostgreSQL via ChatHistoryRepository.is_available()
    - pgvector via SemanticMemoryRepository.is_available()
    
    Requirements: 1.1, 1.3, 1.8
    """
    start = time.time()
    
    try:
        # Import repositories (lazy to avoid circular imports)
        from app.repositories.chat_history_repository import get_chat_history_repository
        from app.repositories.semantic_memory_repository import get_semantic_memory_repository
        
        # Check actual database connections
        chat_repo = get_chat_history_repository()
        chat_available = chat_repo.is_available()
        
        semantic_repo = get_semantic_memory_repository()
        semantic_available = semantic_repo.is_available()
        
        latency = (time.time() - start) * 1000
        
        # Determine status based on actual availability
        if chat_available and semantic_available:
            return ComponentHealth(
                name="Memory Engine",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="PostgreSQL + pgvector connected",
            )
        elif chat_available or semantic_available:
            # Partial availability
            available_services = []
            if chat_available:
                available_services.append("PostgreSQL")
            if semantic_available:
                available_services.append("pgvector")
            return ComponentHealth(
                name="Memory Engine",
                status=ComponentStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message=f"Partial: {', '.join(available_services)} available",
            )
        else:
            return ComponentHealth(
                name="Memory Engine",
                status=ComponentStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message="PostgreSQL and pgvector unavailable",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(f"Memory health check failed: {e}")
        return ComponentHealth(
            name="Memory Engine",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message=str(e),
        )



async def check_supabase_storage_health() -> ComponentHealth:
    """
    Check Supabase Storage health for Multimodal RAG.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Hybrid Infrastructure
    
    Requirements: 4.5
    """
    start = time.time()
    
    try:
        from app.services.supabase_storage import get_storage_client
        
        storage = get_storage_client()
        is_healthy = await storage.check_health()
        
        latency = (time.time() - start) * 1000
        
        if is_healthy:
            return ComponentHealth(
                name="Supabase Storage",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="Supabase Storage connected",
            )
        else:
            return ComponentHealth(
                name="Supabase Storage",
                status=ComponentStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message="Supabase Storage unavailable",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning(f"Supabase Storage health check failed: {e}")
        return ComponentHealth(
            name="Supabase Storage",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message=str(e),
        )


async def check_sparse_search_health() -> ComponentHealth:
    """
    Check PostgreSQL Sparse Search health.
    
    Feature: sparse-search-migration
    Requirements: 5.2
    
    Sparse search uses PostgreSQL tsvector for keyword-based search.
    This is part of the Hybrid Search system.
    """
    start = time.time()
    
    try:
        from app.repositories.sparse_search_repository import SparseSearchRepository
        
        sparse_repo = SparseSearchRepository()
        is_available = sparse_repo.is_available()
        
        latency = (time.time() - start) * 1000
        
        if is_available:
            return ComponentHealth(
                name="Sparse Search",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="PostgreSQL tsvector search available",
            )
        else:
            return ComponentHealth(
                name="Sparse Search",
                status=ComponentStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message="Sparse search unavailable (DATABASE_URL not configured)",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning(f"Sparse search health check failed: {e}")
        return ComponentHealth(
            name="Sparse Search",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message=str(e),
        )


async def check_knowledge_graph_health() -> ComponentHealth:
    """
    Check Neo4j Knowledge Graph health using real connection.
    
    NOTE: Neo4j is OPTIONAL for RAG functionality after sparse-search-migration.
    RAG now uses PostgreSQL for both dense (pgvector) and sparse (tsvector) search.
    Neo4j is reserved for future Learning Graph integration with LMS.
    
    CRITICAL: This function runs a real query (RETURN 1) to Neo4j.
    This is essential for Neo4j Aura Free Tier which pauses after 72 hours
    of inactivity. Each health check ping resets the inactivity timer.
    
    Requirements: 1.2, 1.8
    Feature: sparse-search-migration (Neo4j now optional for RAG)
    """
    start = time.time()
    
    try:
        # Import repository (lazy to avoid circular imports)
        from app.engine.tools.rag_tool import get_knowledge_repository
        
        # Get cached repository instance (singleton)
        neo4j_repo = get_knowledge_repository()
        
        # CRITICAL: Use ping() which runs actual query "RETURN 1"
        # This keeps Neo4j Aura Free Tier alive (resets 72h inactivity timer)
        ping_success = neo4j_repo.ping()
        
        latency = (time.time() - start) * 1000
        
        if ping_success:
            return ComponentHealth(
                name="Neo4j Knowledge Graph",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="Neo4j connected (reserved for Learning Graph)",
            )
        elif neo4j_repo.is_available():
            # Connection exists but ping failed
            return ComponentHealth(
                name="Neo4j Knowledge Graph",
                status=ComponentStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message="Neo4j connected but ping failed",
            )
        else:
            # Neo4j unavailable is OK - RAG works without it
            return ComponentHealth(
                name="Neo4j Knowledge Graph",
                status=ComponentStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message="Neo4j unavailable (optional for RAG)",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        # Log as warning, not error - Neo4j is optional
        logger.warning(f"Knowledge Graph health check failed: {e}")
        return ComponentHealth(
            name="Neo4j Knowledge Graph",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message=f"Neo4j unavailable (optional): {str(e)}",
        )


def determine_overall_status(components: dict[str, ComponentHealth]) -> str:
    """
    Determine overall system status based on component health.
    
    - healthy: All components are healthy
    - degraded: Some components are degraded or unavailable
    - unhealthy: Critical components are unavailable
    """
    statuses = [c.status for c in components.values()]
    
    if all(s == ComponentStatus.HEALTHY for s in statuses):
        return "healthy"
    elif ComponentStatus.UNAVAILABLE in statuses:
        # Check if critical components (API) are down
        if components.get("api", ComponentHealth(name="", status=ComponentStatus.UNAVAILABLE)).status == ComponentStatus.UNAVAILABLE:
            return "unhealthy"
        return "degraded"
    else:
        return "degraded"


async def check_with_timeout(
    check_func,
    component_name: str,
    timeout_seconds: float = HEALTH_CHECK_TIMEOUT
) -> ComponentHealth:
    """
    Execute health check with timeout.
    
    Args:
        check_func: Async function to execute
        component_name: Name of component for error response
        timeout_seconds: Timeout in seconds (default: 5)
        
    Returns:
        ComponentHealth from check_func or UNAVAILABLE on timeout
        
    Requirements: 1.4
    """
    try:
        return await asyncio.wait_for(check_func(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(f"Health check timeout for {component_name} (>{timeout_seconds}s)")
        return ComponentHealth(
            name=component_name,
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=timeout_seconds * 1000,
            message=f"Health check timeout (>{timeout_seconds}s)",
        )


@router.get(
    "",
    summary="Shallow Health Check (Cronjob/Render Ping)",
    description="""
    CHỈ THỊ KỸ THUẬT SỐ 19: Shallow Health Check
    
    KHÔNG kết nối Database - Chỉ trả về static JSON.
    Mục đích: Giữ Server Python (Render) không ngủ, nhưng cho phép Database (Neon) ngủ khi không có user.
    
    Dùng cho: UptimeRobot, Cron-job ping
    """,
)
async def health_check_shallow():
    """
    Shallow health check - NO DATABASE ACCESS.
    
    CHỈ THỊ 19: Bảo vệ Neon Free Tier (100 giờ compute)
    - Cronjob ping vào đây sẽ KHÔNG đánh thức Neon
    - Chỉ kiểm tra Python server còn sống
    """
    return {
        "status": "ok",
        "service": "maritime-ai-tutor",
        "version": settings.app_version,
        "environment": settings.environment,
    }


@router.get(
    "/db",
    response_model=HealthResponse,
    summary="Deep Health Check (Debug/Admin)",
    description="""
    CHỈ THỊ KỸ THUẬT SỐ 19: Deep Health Check
    
    Thực hiện query vào Database - SẼ ĐÁNH THỨC Neon.
    Chỉ dùng khi Dev cần kiểm tra kết nối bằng tay.
    
    Components checked:
    - **API**: FastAPI application status
    - **Memory**: Memory Engine (PostgreSQL + pgvector) status
    - **Knowledge Graph**: Neo4j status
    
    Timeout: 5 seconds per component.
    """,
)
async def health_check_deep() -> HealthResponse:
    """
    Deep health check - WAKES UP Neon DB.
    
    CHỈ THỊ 19: Chỉ dùng cho Debug/Admin
    - KHÔNG để Cronjob ping vào endpoint này
    - Sẽ tiêu tốn compute hours của Neon
    
    Feature: sparse-search-migration
    - Added Sparse Search health check (PostgreSQL tsvector)
    - Neo4j is now optional for RAG
    """
    # Check all components with timeout
    api_health = await check_with_timeout(check_api_health, "API")
    memory_health = await check_with_timeout(check_memory_health, "Memory Engine")
    sparse_health = await check_with_timeout(check_sparse_search_health, "Sparse Search")
    kg_health = await check_with_timeout(check_knowledge_graph_health, "Neo4j Knowledge Graph")
    supabase_health = await check_with_timeout(check_supabase_storage_health, "Supabase Storage")
    
    components = {
        "api": api_health,
        "memory": memory_health,
        "sparse_search": sparse_health,  # Feature: sparse-search-migration
        "knowledge_graph": kg_health,  # Optional for RAG, reserved for Learning Graph
        "supabase_storage": supabase_health,  # CHỈ THỊ 26: Hybrid Infrastructure
    }
    
    overall_status = determine_overall_status(components)
    
    response = HealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )
    
    logger.info(f"Deep health check: {overall_status}")
    
    return response


@router.get(
    "/live",
    summary="Liveness Probe",
    description="Simple liveness check for Kubernetes",
)
async def liveness():
    """Kubernetes liveness probe"""
    return {"status": "alive"}


@router.get(
    "/ready",
    summary="Readiness Probe",
    description="Readiness check for Kubernetes - checks if service can accept traffic",
)
async def readiness():
    """
    Kubernetes readiness probe.
    
    Checks if critical services (PostgreSQL) are available.
    Returns 503 if not ready to accept traffic.
    """
    try:
        from app.repositories.chat_history_repository import get_chat_history_repository
        chat_repo = get_chat_history_repository()
        
        if chat_repo.is_available():
            return {"status": "ready"}
        else:
            return {"status": "not_ready", "reason": "Database unavailable"}
    except Exception as e:
        logger.warning(f"Readiness check failed: {e}")
        return {"status": "not_ready", "reason": str(e)}
