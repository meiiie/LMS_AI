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
    """
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # TODO: Initialize database connections
    # TODO: Initialize Neo4j connection
    # TODO: Initialize Memori engine
    
    yield
    
    # Shutdown
    logger.info("Shutting down Maritime AI Service...")
    # TODO: Close database connections
    # TODO: Close Neo4j connection


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

    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
