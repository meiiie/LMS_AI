"""
Shared Database Engine - Singleton Pattern.

This module provides a SINGLE shared database engine for all repositories.

**CHỈ THỊ KỸ THUẬT SỐ 19: Migration to Neon**
- Neon Serverless Postgres với Pooled Connection
- Khắc phục vĩnh viễn lỗi MaxClients từ Supabase
- pool_size=5, max_overflow=5 → Max 10 connections (Neon cho phép nhiều hơn)
"""

import logging
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# SINGLETON DATABASE ENGINE
# =============================================================================

_shared_engine = None
_shared_session_factory = None
_engine_initialized = False


def get_shared_engine():
    """
    Get the shared SQLAlchemy engine (Singleton).
    
    Creates ONE engine that all repositories share.
    CHỈ THỊ 19: Now using Neon Serverless Postgres.
    
    Connection Pool Settings:
    - pool_size=2: Only 2 persistent connections
    - max_overflow=1: Allow 1 extra connection under load
    - pool_timeout=10: Fail fast if no connection available
    - pool_recycle=1800: Recycle connections every 30 minutes
    - pool_pre_ping=True: Check connection health before use
    
    Returns:
        SQLAlchemy Engine instance
    """
    global _shared_engine, _engine_initialized
    
    if _shared_engine is None:
        try:
            _shared_engine = create_engine(
                settings.postgres_url_sync,
                echo=False,
                pool_pre_ping=True,
                pool_size=5,        # CHỈ THỊ 19: Neon Pooled Connection
                max_overflow=5,     # Allow 5 extra under load (total max: 10)
                pool_timeout=30,    # Neon có thể cần thời gian wake up
                pool_recycle=1800   # Recycle connections every 30 minutes
            )
            _engine_initialized = True
            logger.info(
                "Shared database engine created (Neon): "
                "pool_size=5, max_overflow=5, pool_timeout=30s"
            )
        except Exception as e:
            logger.error(f"Failed to create shared database engine: {e}")
            raise
    
    return _shared_engine


def get_shared_session_factory():
    """
    Get the shared SQLAlchemy session factory (Singleton).
    
    Returns:
        SQLAlchemy sessionmaker bound to shared engine
    """
    global _shared_session_factory
    
    if _shared_session_factory is None:
        engine = get_shared_engine()
        _shared_session_factory = sessionmaker(bind=engine)
        logger.info("Shared session factory created")
    
    return _shared_session_factory


def test_connection() -> bool:
    """
    Test database connection.
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


def close_shared_engine():
    """
    Close the shared engine and release all connections.
    
    Call this during application shutdown.
    """
    global _shared_engine, _shared_session_factory, _engine_initialized
    
    if _shared_engine is not None:
        _shared_engine.dispose()
        _shared_engine = None
        _shared_session_factory = None
        _engine_initialized = False
        logger.info("Shared database engine closed")
