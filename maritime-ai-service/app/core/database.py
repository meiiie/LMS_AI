"""
Shared Database Engine - Singleton Pattern.

This module provides a SINGLE shared database engine for all repositories.

**CHỈ THỊ KỸ THUẬT SỐ 19: Migration to Neon**
- Neon Serverless Postgres với Pooled Connection
- Khắc phục vĩnh viễn lỗi MaxClients
- Pool sizes from config: async_pool_min_size / async_pool_max_size
"""

import logging
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import NoSuchModuleError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# SINGLETON DATABASE ENGINE
# =============================================================================

_shared_engine = None
_shared_session_factory = None
_engine_initialized = False
_database_unavailable_until = 0.0
_database_unavailable_reason = ""
_DATABASE_UNAVAILABLE_COOLDOWN_SECONDS = 30.0


def _build_sync_postgres_url_candidates(raw_url: str) -> list[str]:
    """Return dialect candidates for sync PostgreSQL engines."""
    candidates: list[str] = []

    def _add(candidate: str) -> None:
        if candidate not in candidates:
            candidates.append(candidate)

    normalized = raw_url
    if raw_url.startswith("postgresql://"):
        normalized = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

    _add(normalized)

    if normalized.startswith("postgresql+psycopg://"):
        _add(normalized.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1))
    elif normalized.startswith("postgresql+psycopg2://"):
        _add(normalized.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1))

    if raw_url.startswith("postgresql://"):
        _add(raw_url)

    return candidates


def get_shared_engine():
    """
    Get the shared SQLAlchemy engine (Singleton).
    
    Creates ONE engine that all repositories share.
    CHỈ THỊ 19: Now using Neon Serverless Postgres.
    
    Connection Pool Settings (from config.py):
    - pool_size=settings.async_pool_min_size: Persistent connections
    - max_overflow=max_size - min_size: Extra connections under load
    - pool_timeout=30: Wait 30s for connection
    - pool_recycle=1800: Recycle connections every 30 minutes
    - pool_pre_ping=True: Check connection health before use
    
    Returns:
        SQLAlchemy Engine instance
    """
    global _shared_engine, _engine_initialized
    
    if _shared_engine is None:
        try:
            pool_size = settings.async_pool_min_size
            max_overflow = settings.async_pool_max_size - settings.async_pool_min_size
            last_error = None
            sync_candidates = _build_sync_postgres_url_candidates(settings.postgres_url_sync)
            for sync_url in sync_candidates:
                try:
                    _shared_engine = create_engine(
                        sync_url,
                        echo=False,
                        pool_pre_ping=True,
                        pool_size=pool_size,
                        max_overflow=max_overflow,
                        pool_timeout=30,
                        pool_recycle=1800
                    )
                    if sync_url != sync_candidates[0]:
                        logger.warning(
                            "Shared database engine falling back to sync dialect URL: %s",
                            sync_url,
                        )
                    break
                except NoSuchModuleError as exc:
                    last_error = exc
                    logger.warning(
                        "Sync database dialect unavailable for URL '%s': %s",
                        sync_url,
                        exc,
                    )
            if _shared_engine is None:
                if last_error is not None:
                    raise last_error
                raise RuntimeError("No usable sync PostgreSQL SQLAlchemy dialect candidate found")
            # Sprint 171: Set statement_timeout + idle_in_transaction on checkout
            # CIS PostgreSQL Benchmark 5.4 — prevent runaway queries
            stmt_timeout = getattr(settings, "postgres_statement_timeout_ms", 30000)
            idle_timeout = getattr(settings, "postgres_idle_in_transaction_timeout_ms", 60000)

            @event.listens_for(_shared_engine, "connect")
            def _set_pg_timeouts(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute(f"SET statement_timeout = {int(stmt_timeout)}")
                cursor.execute(f"SET idle_in_transaction_session_timeout = {int(idle_timeout)}")
                cursor.close()

            # Sprint 175b: RLS context injection on connection checkout
            # Sets app.current_org_id so PostgreSQL RLS policies can filter rows.
            # No-op when enable_rls=False (default).
            @event.listens_for(_shared_engine, "checkout")
            def _set_rls_context(dbapi_conn, connection_record, connection_proxy):
                if not settings.enable_rls:
                    return
                try:
                    from app.core.org_context import get_current_org_id
                    org_id = get_current_org_id() or ""
                    cursor = dbapi_conn.cursor()
                    cursor.execute("SET app.current_org_id = %s", (org_id,))
                    cursor.close()
                except Exception:
                    # Don't block connection checkout on RLS context failure
                    pass

            _engine_initialized = True
            logger.info(
                "Shared database engine created: "
                "pool_size=%d, max_overflow=%d, pool_timeout=30s, "
                "statement_timeout=%dms, idle_tx_timeout=%dms, rls=%s",
                pool_size, max_overflow, stmt_timeout, idle_timeout,
                settings.enable_rls,
            )
        except Exception as e:
            logger.error("Failed to create shared database engine: %s", e)
            raise
    
    return _shared_engine


def is_shared_database_temporarily_unavailable() -> bool:
    """Return True while the process is intentionally failing DB access fast."""
    return time.monotonic() < _database_unavailable_until


def mark_shared_database_unavailable(
    reason: Exception | str,
    *,
    cooldown_seconds: float = _DATABASE_UNAVAILABLE_COOLDOWN_SECONDS,
) -> None:
    """Throttle repeated DB connection attempts after an observed outage."""
    global _database_unavailable_until, _database_unavailable_reason

    cooldown = max(1.0, float(cooldown_seconds))
    now = time.monotonic()
    until = now + cooldown
    if until > _database_unavailable_until:
        _database_unavailable_until = until
        _database_unavailable_reason = str(reason)
        logger.warning(
            "Shared database marked temporarily unavailable for %.0fs: %s",
            cooldown,
            _database_unavailable_reason,
        )


def clear_shared_database_unavailable() -> None:
    """Clear the degraded-DB cooldown.

    This is primarily useful for unit tests that intentionally simulate a DB
    outage and then immediately mock a healthy pool in the same Python process.
    """
    global _database_unavailable_until, _database_unavailable_reason

    _database_unavailable_until = 0.0
    _database_unavailable_reason = ""


def get_shared_session_factory():
    """
    Get the shared SQLAlchemy session factory (Singleton).
    
    Returns:
        SQLAlchemy sessionmaker bound to shared engine
    """
    global _shared_session_factory

    if is_shared_database_temporarily_unavailable():
        raise RuntimeError(
            "Shared database temporarily unavailable; retry after cooldown"
        )
    
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
        logger.error("Database connection test failed: %s", e)
        mark_shared_database_unavailable(e)
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


# =============================================================================
# ASYNCPG POOL — Sprint 179: Raw asyncpg for admin dashboard queries
# =============================================================================

_asyncpg_pool = None


async def get_asyncpg_pool(create: bool = True):
    """
    Get a raw asyncpg connection pool for lightweight admin queries.

    Uses settings.asyncpg_url (plain postgresql:// format).
    The pool is created lazily on first call and reused thereafter.
    """
    global _asyncpg_pool

    if _asyncpg_pool is not None:
        return _asyncpg_pool

    if not create:
        return None

    if is_shared_database_temporarily_unavailable():
        raise RuntimeError(
            "Shared asyncpg pool temporarily unavailable; retry after cooldown"
        )

    try:
        import asyncpg

        pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_url,
            min_size=2,
            max_size=5,
            timeout=getattr(settings, "postgres_connect_timeout_seconds", 5),
            command_timeout=15,
        )
        _asyncpg_pool = pool
        logger.info("asyncpg pool created (min=2, max=5)")
        return pool
    except Exception as e:
        logger.error("Failed to create asyncpg pool: %s", e)
        mark_shared_database_unavailable(e)
        raise


async def close_asyncpg_pool():
    """Close the asyncpg pool on shutdown."""
    global _asyncpg_pool
    if _asyncpg_pool is not None:
        await _asyncpg_pool.close()
        _asyncpg_pool = None
        logger.info("asyncpg pool closed")
