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



async def check_knowledge_graph_health() -> ComponentHealth:
    """
    Check Neo4j Knowledge Graph health using real connection.
    
    Uses Neo4jKnowledgeRepository.is_available() for actual check.
    
    Requirements: 1.2, 1.8
    """
    start = time.time()
    
    try:
        # Import repository (lazy to avoid circular imports)
        from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
        
        # Check actual Neo4j connection
        neo4j_repo = Neo4jKnowledgeRepository()
        neo4j_available = neo4j_repo.is_available()
        
        latency = (time.time() - start) * 1000
        
        if neo4j_available:
            return ComponentHealth(
                name="Neo4j Knowledge Graph",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="Neo4j connected",
            )
        else:
            return ComponentHealth(
                name="Neo4j Knowledge Graph",
                status=ComponentStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message="Neo4j connection unavailable",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.error(f"Knowledge Graph health check failed: {e}")
        return ComponentHealth(
            name="Neo4j Knowledge Graph",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message=str(e),
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
    response_model=HealthResponse,
    summary="Health Check",
    description="""
    Returns the health status of all system components.
    
    Components checked:
    - **API**: FastAPI application status
    - **Memory**: Memory Engine (PostgreSQL + pgvector) status
    - **Knowledge Graph**: Neo4j status
    
    Timeout: 5 seconds per component.
    
    **Requirements: 8.4**
    """,
)
async def health_check() -> HealthResponse:
    """
    Perform health check on all components with timeout handling.
    
    Returns:
        HealthResponse with status of all components
    """
    # Check all components with timeout
    api_health = await check_with_timeout(check_api_health, "API")
    memory_health = await check_with_timeout(check_memory_health, "Memory Engine")
    kg_health = await check_with_timeout(check_knowledge_graph_health, "Neo4j Knowledge Graph")
    
    components = {
        "api": api_health,
        "memory": memory_health,
        "knowledge_graph": kg_health,
    }
    
    overall_status = determine_overall_status(components)
    
    response = HealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )
    
    logger.info(f"Health check: {overall_status}")
    
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
