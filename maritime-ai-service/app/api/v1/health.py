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

from fastapi import APIRouter
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.constants import HEALTH_CHECK_TIMEOUT
from app.engine.agentic_rag.rag_agent import get_knowledge_repository
from app.engine.llm_model_health import get_model_health_snapshot
from app.models.schemas import ComponentHealth, ComponentStatus, HealthResponse
from app.repositories.chat_history_repository import get_chat_history_repository
from app.repositories.semantic_memory_repository import get_semantic_memory_repository
from app.repositories.sparse_search_repository import SparseSearchRepository
from app.services.object_storage import get_storage_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

# Imported from app.core.constants


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
        logger.error("Memory health check failed: %s", e)
        return ComponentHealth(
            name="Memory Engine",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="Service check failed",
        )



async def check_object_storage_health() -> ComponentHealth:
    """
    Check Object Storage (MinIO) health for Multimodal RAG.

    CHỈ THỊ KỸ THUẬT SỐ 26: Hybrid Infrastructure

    Requirements: 4.5
    """
    start = time.time()

    try:
        storage = get_storage_client()
        is_healthy = await storage.check_health()

        latency = (time.time() - start) * 1000

        if is_healthy:
            return ComponentHealth(
                name="Object Storage",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="Object Storage connected",
            )
        else:
            return ComponentHealth(
                name="Object Storage",
                status=ComponentStatus.UNAVAILABLE,
                latency_ms=round(latency, 2),
                message="Object Storage unavailable",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning("Object Storage health check failed: %s", e)
        return ComponentHealth(
            name="Object Storage",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="Service check failed",
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
        logger.warning("Sparse search health check failed: %s", e)
        return ComponentHealth(
            name="Sparse Search",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="Service check failed",
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
        logger.warning("Knowledge Graph health check failed: %s", e)
        return ComponentHealth(
            name="Neo4j Knowledge Graph",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="Neo4j unavailable (optional)",
        )


_shared_async_engine = None


def _get_sqlalchemy_async_engine_url() -> str:
    """Return a SQLAlchemy async URL without asyncpg-incompatible options."""
    return settings._remove_connect_timeout(settings.postgres_url)


async def _get_shared_async_engine():
    """Get or create a module-level singleton async engine for health checks."""
    global _shared_async_engine
    if _shared_async_engine is None:
        _shared_async_engine = create_async_engine(
            _get_sqlalchemy_async_engine_url(),
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )
    return _shared_async_engine


async def check_async_pool_health() -> ComponentHealth:
    """
    Check async PostgreSQL connection pool health.

    SOTA 2026: Verifies the shared async engine used by repositories and
    runner-backed runtime services can execute queries.

    Sprint 171: Uses singleton engine — no longer creates/disposes per call.
    """
    start = time.time()

    try:
        engine = await _get_shared_async_engine()

        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))

        latency = (time.time() - start) * 1000
        return ComponentHealth(
            name="Async Pool",
            status=ComponentStatus.HEALTHY,
            latency_ms=round(latency, 2),
            message="Async PostgreSQL pool connected",
        )
    except ImportError:
        latency = (time.time() - start) * 1000
        return ComponentHealth(
            name="Async Pool",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="asyncpg not installed",
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning("Async pool health check failed: %s", e)
        return ComponentHealth(
            name="Async Pool",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="Service check failed",
        )


def _build_llm_model_health_report() -> dict:
    """Return a redacted operator-facing model health snapshot."""
    snapshot = get_model_health_snapshot()
    models = []
    for provider, provider_models in sorted(snapshot.items()):
        for model, record in sorted(provider_models.items()):
            models.append(
                {
                    "provider": provider,
                    "model": model,
                    "state": record.get("state"),
                    "last_reason_code": record.get("last_reason_code"),
                    "last_timeout_seconds": record.get("last_timeout_seconds"),
                    "last_failure_at": record.get("last_failure_at"),
                    "last_success_at": record.get("last_success_at"),
                    "degraded_until": record.get("degraded_until"),
                }
            )

    degraded_count = sum(1 for item in models if item.get("state") == "degraded")
    healthy_count = sum(1 for item in models if item.get("state") == "healthy")
    all_known_models_degraded = bool(models) and degraded_count >= len(models)
    return {
        "status": "degraded" if all_known_models_degraded else "healthy",
        "model_count": len(models),
        "healthy_count": healthy_count,
        "degraded_count": degraded_count,
        "models": models,
    }


async def check_llm_model_health() -> ComponentHealth:
    """Summarize process-local model health without exposing raw provider errors."""
    start = time.time()
    try:
        report = _build_llm_model_health_report()
        latency = (time.time() - start) * 1000
        model_count = report["model_count"]
        healthy_count = report["healthy_count"]
        degraded_count = report["degraded_count"]

        if model_count == 0:
            status = ComponentStatus.HEALTHY
            message = "No model health records yet"
        elif degraded_count >= model_count:
            status = ComponentStatus.DEGRADED
            message = f"All {model_count} model(s) degraded"
        elif degraded_count:
            status = ComponentStatus.HEALTHY
            message = (
                f"{degraded_count}/{model_count} model(s) degraded; "
                f"{healthy_count} model(s) healthy for routing"
            )
        else:
            status = ComponentStatus.HEALTHY
            message = f"{model_count} model health record(s), all healthy"

        return ComponentHealth(
            name="LLM Model Health",
            status=status,
            latency_ms=round(latency, 2),
            message=message,
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        logger.warning("LLM model health check failed: %s", e)
        return ComponentHealth(
            name="LLM Model Health",
            status=ComponentStatus.UNAVAILABLE,
            latency_ms=round(latency, 2),
            message="Model health snapshot unavailable",
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
        logger.warning("Health check timeout for %s (>%ss)", component_name, timeout_seconds)
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
        "service": settings.app_name,
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
    storage_health = await check_with_timeout(check_object_storage_health, "Object Storage")
    async_pool_health = await check_with_timeout(check_async_pool_health, "Async Pool")
    llm_model_health = await check_with_timeout(check_llm_model_health, "LLM Model Health")

    components = {
        "api": api_health,
        "memory": memory_health,
        "sparse_search": sparse_health,  # Feature: sparse-search-migration
        "knowledge_graph": kg_health,  # Optional for RAG, reserved for Learning Graph
        "object_storage": storage_health,  # MinIO / S3-compatible storage
        "async_pool": async_pool_health,  # SOTA 2026: Async connection pool
        "llm_model_health": llm_model_health,
    }
    
    overall_status = determine_overall_status(components)
    
    response = HealthResponse(
        status=overall_status,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )
    
    logger.info("Deep health check: %s", overall_status)
    
    return response


@router.get(
    "/llm-models",
    summary="LLM Model Health Snapshot",
    description="Return redacted per-provider/per-model health for runtime operators.",
)
async def llm_model_health_snapshot():
    """Expose model health state without API keys or raw provider error bodies."""
    return _build_llm_model_health_report()


@router.get(
    "/ollama",
    summary="Ollama Health Check",
    description="Check Ollama availability and list loaded models",
)
async def ollama_health():
    """
    Ollama health check — Sprint 59.

    Checks if Ollama is reachable at the configured base URL
    and returns the list of available models.
    """
    import httpx

    base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
    normalized_base_url = base_url
    if isinstance(base_url, str) and base_url.rstrip().endswith("/api"):
        normalized_base_url = base_url.rstrip()[:-4]
    keep_alive = getattr(settings, "ollama_keep_alive", None)
    if not isinstance(keep_alive, str):
        keep_alive = None
    else:
        keep_alive = keep_alive.strip() or None
    if not normalized_base_url:
        return {"status": "unavailable", "reason": "ollama_base_url not configured"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{normalized_base_url.rstrip('/')}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return {
                    "status": "available",
                    "base_url": base_url,
                    "normalized_base_url": normalized_base_url,
                    "keep_alive": keep_alive,
                    "models": models,
                    "model_count": len(models),
                    "default_model": getattr(
                        settings,
                        "ollama_model",
                        "qwen3:4b-instruct-2507-q4_K_M",
                    ),
                }
            else:
                return {
                    "status": "unavailable",
                    "base_url": base_url,
                    "normalized_base_url": normalized_base_url,
                    "keep_alive": keep_alive,
                    "http_status": resp.status_code,
                }
    except Exception as e:
        logger.warning("Ollama health check failed: %s", e)
        return {
            "status": "unavailable",
            "base_url": base_url,
            "normalized_base_url": normalized_base_url,
            "keep_alive": keep_alive,
            "reason": "Connection failed",
        }


@router.get(
    "/opensandbox",
    summary="OpenSandbox Health Check",
    description="Check OpenSandbox privileged execution control plane availability",
)
async def opensandbox_health():
    """OpenSandbox health check for the privileged execution layer."""
    if not getattr(settings, "enable_privileged_sandbox", False):
        return {
            "status": "disabled",
            "provider": getattr(settings, "sandbox_provider", "disabled"),
            "reason": "enable_privileged_sandbox is false",
        }

    provider = getattr(settings, "sandbox_provider", "disabled")
    if provider != "opensandbox":
        return {
            "status": "disabled",
            "provider": provider,
            "reason": "sandbox_provider is not opensandbox",
        }

    base_url = getattr(settings, "opensandbox_base_url", None)
    if not base_url:
        return {
            "status": "unavailable",
            "provider": provider,
            "reason": "opensandbox_base_url not configured",
        }

    from app.sandbox.factory import get_sandbox_executor

    executor = get_sandbox_executor()
    if executor is None or not executor.is_configured():
        return {
            "status": "unavailable",
            "provider": provider,
            "base_url": base_url,
            "reason": "OpenSandbox executor not configured",
        }

    ok = await executor.healthcheck()
    return {
        "status": "available" if ok else "unavailable",
        "provider": provider,
        "base_url": base_url,
        "code_image": getattr(settings, "opensandbox_code_template", ""),
        "browser_image": getattr(settings, "opensandbox_browser_template", ""),
        "code_template": getattr(settings, "opensandbox_code_template", ""),
        "browser_template": getattr(settings, "opensandbox_browser_template", ""),
        "network_mode": getattr(settings, "opensandbox_network_mode", "disabled"),
        "browser_workloads_enabled": getattr(
            settings,
            "sandbox_allow_browser_workloads",
            False,
        ),
    }


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
    from fastapi.responses import JSONResponse

    try:
        chat_repo = get_chat_history_repository()

        if chat_repo.is_available():
            return {"status": "ready"}
        else:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "Database unavailable"},
            )
    except Exception as e:
        logger.warning("Readiness check failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "Service check failed"},
        )
