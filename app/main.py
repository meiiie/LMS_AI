"""
Maritime AI Tutor Service - FastAPI Application Entry Point
Requirements: 1.1

Clean Architecture + Agentic RAG + Long-term Memory
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.models.schemas import ErrorResponse, ErrorDetail

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    
    Production Readiness Spec:
    - Startup: Validate connections, log warnings if unavailable (don't crash)
    - Shutdown: Close Neo4j driver explicitly
    
    Requirements: 2.1, 2.2, 3.1, 3.2, 3.3
    """
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Validate database connections (warn only, don't crash)
    neo4j_repo = None
    try:
        from app.repositories.chat_history_repository import get_chat_history_repository
        chat_repo = get_chat_history_repository()
        if chat_repo.is_available():
            logger.info("✅ PostgreSQL connection: Available")
        else:
            logger.warning("⚠️ PostgreSQL connection: Unavailable (service will continue)")
    except Exception as e:
        logger.warning(f"⚠️ PostgreSQL validation failed: {e} (service will continue)")
    
    try:
        from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
        neo4j_repo = Neo4jKnowledgeRepository()
        if neo4j_repo.is_available():
            logger.info("✅ Neo4j connection: Available")
        else:
            logger.warning("⚠️ Neo4j connection: Unavailable (service will continue)")
    except Exception as e:
        logger.warning(f"⚠️ Neo4j validation failed: {e} (service will continue)")
    
    try:
        from app.repositories.semantic_memory_repository import get_semantic_memory_repository
        semantic_repo = get_semantic_memory_repository()
        if semantic_repo.is_available():
            logger.info("✅ pgvector connection: Available")
        else:
            logger.warning("⚠️ pgvector connection: Unavailable (service will continue)")
    except Exception as e:
        logger.warning(f"⚠️ pgvector validation failed: {e} (service will continue)")
    
    # Validate YAML persona files (CHỈ THỊ 16 - Humanization)
    try:
        from app.prompts.prompt_loader import get_prompt_loader
        prompt_loader = get_prompt_loader()
        # This will log which files were found/loaded
        logger.info("✅ PromptLoader initialized (persona YAML files checked)")
    except Exception as e:
        logger.warning(f"⚠️ PromptLoader initialization failed: {e} (using defaults)")
    
    # =========================================================================
    # PRE-WARMING AI COMPONENTS (SOTA Memory Optimization - Dec 2025)
    # =========================================================================
    # Purpose: Initialize heavy AI components at startup instead of first request
    # Reference: SOTA_DEEP_ROOT_CAUSE_ANALYSIS.md
    # Impact: Eliminates ~45s cold start on first request
    # =========================================================================
    
    # 1. Pre-warm RAGAgent singleton (contains LLM ~100MB)
    try:
        from app.engine.agentic_rag import get_rag_agent, is_rag_agent_initialized
        get_rag_agent()
        if is_rag_agent_initialized():
            logger.info("✅ RAGAgent singleton pre-warmed (memory optimized)")
    except Exception as e:
        logger.warning(f"⚠️ RAGAgent pre-warm failed: {e}")
    
    # 2. Pre-warm CorrectiveRAG singleton (contains all CRAG components)
    try:
        from app.engine.agentic_rag import get_corrective_rag
        get_corrective_rag()
        logger.info("✅ CorrectiveRAG pre-warmed (QueryAnalyzer, RetrievalGrader, etc.)")
    except Exception as e:
        logger.warning(f"⚠️ CorrectiveRAG pre-warm failed: {e}")
    
    # 3. Pre-warm ChatService (triggers all other service initialization)
    try:
        from app.services.chat_service import get_chat_service
        get_chat_service()
        logger.info("✅ ChatService pre-warmed (all agents initialized)")
    except Exception as e:
        logger.warning(f"⚠️ ChatService pre-warm failed: {e}")
    
    # 4. Pre-warm Neural Reranker (SOTA Dec 2025 - loads BGE cross-encoder model)
    # This can take 5-15s on first load, but eliminates cold start on first request
    try:
        from app.services.neural_reranker import get_neural_reranker
        reranker = get_neural_reranker()
        if reranker.is_available():
            logger.info("✅ Neural Reranker pre-warmed (BGE cross-encoder loaded)")
        else:
            logger.warning("⚠️ Neural Reranker unavailable (sentence-transformers not installed)")
    except Exception as e:
        logger.warning(f"⚠️ Neural Reranker pre-warm failed: {e}")
    
    logger.info(f"🚀 {settings.app_name} started successfully")
    
    yield
    
    # Shutdown - Close Neo4j driver explicitly (Requirements: 2.1, 2.2)
    logger.info("Shutting down Maritime AI Service...")
    
    if neo4j_repo is not None:
        try:
            neo4j_repo.close()
            logger.info("✅ Neo4j driver closed successfully")
        except Exception as e:
            logger.error(f"❌ Failed to close Neo4j driver: {e}")
    
    # Close shared database engine
    try:
        from app.core.database import close_shared_engine
        close_shared_engine()
        logger.info("✅ Shared database engine closed successfully")
    except Exception as e:
        logger.error(f"❌ Failed to close shared database engine: {e}")
    
    logger.info("👋 Maritime AI Service shutdown complete")


def create_application() -> FastAPI:
    """
    Application factory pattern.
    Creates and configures the FastAPI application.
    """
    app = FastAPI(
        title=settings.app_name,
        description="AI Tutor Microservice for Maritime LMS - Agentic RAG with Long-term Memory",
        version=settings.app_version,
        docs_url="/docs",  # Always enable for LMS team integration
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    
    # Configure CORS - Allow LMS Frontend origins
    # When allow_credentials=True, cannot use ["*"] for origins
    cors_origins = [
        "http://localhost:4200",      # Angular dev server
        "http://localhost:4300",      # Angular alternative port
        "http://localhost:3000",      # React/Next.js dev server
        "http://127.0.0.1:4200",
        "http://127.0.0.1:4300",
        "http://127.0.0.1:3000",
        "https://lms-maritime.com",   # Production domain (update when known)
        "https://*.vercel.app",       # Vercel deployments
        "https://*.netlify.app",      # Netlify deployments
    ]
    
    # Add any custom origins from settings
    if settings.cors_origins and settings.cors_origins != ["*"]:
        cors_origins.extend(settings.cors_origins)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    
    # Configure Rate Limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    
    # Register exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    # Include API routers
    from app.api.v1 import router as api_v1_router
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    
    return app


# =============================================================================
# Exception Handlers
# =============================================================================

async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors.
    Returns HTTP 400 with detailed error information.
    Requirements: 1.2
    """
    errors = []
    for error in exc.errors():
        errors.append(
            ErrorDetail(
                field=".".join(str(loc) for loc in error["loc"]),
                message=error["msg"],
                code=error["type"],
            )
        )
    
    response = ErrorResponse(
        error="validation_error",
        message="Request validation failed",
        details=errors,
        request_id=request.headers.get("X-Request-ID"),
    )
    
    logger.warning(f"Validation error: {response.model_dump_json()}")
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=response.model_dump(mode="json"),
    )


async def general_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Handle unexpected exceptions.
    Returns HTTP 500 with error details while maintaining service availability.
    Requirements: 1.4
    """
    logger.exception(f"Unexpected error: {exc}")
    
    response = ErrorResponse(
        error="internal_error",
        message="An unexpected error occurred" if not settings.debug else str(exc),
        request_id=request.headers.get("X-Request-ID"),
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump(mode="json"),
    )


# Create application instance
app = create_application()


# =============================================================================
# Root Endpoint
# =============================================================================

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint - service information"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": f"{settings.api_v1_prefix}/docs" if settings.debug else "disabled",
    }


@app.get("/health", tags=["Health"])
async def health_check_simple():
    """
    Simple health check endpoint for LMS/DevOps.
    
    Spec: CHỈ THỊ KỸ THUẬT SỐ 03
    URL: GET /health
    Response: {"status": "ok", "database": "connected"}
    """
    # Check database connection
    db_status = "connected"
    try:
        from app.repositories.chat_history_repository import get_chat_history_repository
        chat_history = get_chat_history_repository()
        if not chat_history.is_available():
            db_status = "disconnected"
    except Exception:
        db_status = "disconnected"
    
    return {
        "status": "ok",
        "database": db_status
    }
