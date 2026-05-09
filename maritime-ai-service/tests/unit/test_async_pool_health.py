"""
Tests for Async Pool Health Check (Sprint 10).

Verifies:
- check_async_pool_health returns HEALTHY when async engine works
- check_async_pool_health returns UNAVAILABLE on connection failure
- check_async_pool_health handles ImportError (asyncpg not installed)
- Component is wired into deep health check endpoint
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio

from app.models.schemas import ComponentStatus


class TestAsyncPoolHealth:
    """Test async pool health check function."""

    @pytest.fixture(autouse=True)
    def reset_shared_engine(self):
        """Reset singleton async engine between tests."""
        import app.api.v1.health as health_mod
        health_mod._shared_async_engine = None
        yield
        health_mod._shared_async_engine = None

    @pytest.mark.asyncio
    async def test_healthy_connection(self):
        """Returns HEALTHY when async engine connects successfully."""
        from app.api.v1.health import check_async_pool_health

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        with patch("app.api.v1.health.create_async_engine", return_value=mock_engine):
            result = await check_async_pool_health()

        assert result.name == "Async Pool"
        assert result.status == ComponentStatus.HEALTHY
        assert result.latency_ms >= 0
        assert "connected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        """Returns UNAVAILABLE when connection fails."""
        from app.api.v1.health import check_async_pool_health

        with patch(
            "app.api.v1.health.create_async_engine",
            side_effect=Exception("Connection refused"),
        ):
            result = await check_async_pool_health()

        assert result.name == "Async Pool"
        assert result.status == ComponentStatus.UNAVAILABLE
        assert "Service check failed" in result.message

    @pytest.mark.asyncio
    async def test_import_error(self):
        """Returns UNAVAILABLE when asyncpg not installed."""
        from app.api.v1.health import check_async_pool_health

        with patch(
            "app.api.v1.health.create_async_engine",
            side_effect=ImportError("No module named 'asyncpg'"),
        ):
            result = await check_async_pool_health()

        assert result.name == "Async Pool"
        assert result.status == ComponentStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_latency_measured(self):
        """Latency is measured in milliseconds."""
        from app.api.v1.health import check_async_pool_health

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_engine = AsyncMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        with patch("app.api.v1.health.create_async_engine", return_value=mock_engine):
            result = await check_async_pool_health()

        assert result.latency_ms >= 0
        assert isinstance(result.latency_ms, float)


class TestAsyncPoolIntegration:
    """Test async pool check is wired into deep health endpoint."""

    def test_health_module_has_function(self):
        """check_async_pool_health exists in health module."""
        from app.api.v1 import health
        assert hasattr(health, "check_async_pool_health")
        assert callable(health.check_async_pool_health)

    @pytest.mark.asyncio
    async def test_shared_engine_strips_connect_timeout_from_sqlalchemy_url(self):
        """Health checks should keep asyncpg driver but drop invalid timeout query."""
        import app.api.v1.health as health_mod

        health_mod._shared_async_engine = None
        mock_settings = MagicMock()
        mock_settings.postgres_url = (
            "postgresql+asyncpg://wiii:secret@postgres:5432/wiii"
            "?connect_timeout=5&ssl=require"
        )
        mock_settings._remove_connect_timeout.side_effect = (
            lambda url: url.replace("?connect_timeout=5&ssl=require", "?ssl=require")
        )

        with patch("app.api.v1.health.settings", mock_settings), \
             patch("app.api.v1.health.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            engine = await health_mod._get_shared_async_engine()

        assert engine is mock_engine
        created_url = mock_create.call_args.args[0]
        assert created_url.startswith("postgresql+asyncpg://")
        assert "connect_timeout" not in created_url

    def test_deep_health_includes_async_pool(self):
        """Deep health check source code references async_pool."""
        import inspect
        from app.api.v1.health import health_check_deep
        source = inspect.getsource(health_check_deep)
        assert "async_pool" in source
        assert "check_async_pool_health" in source

    def test_deep_health_includes_llm_model_health(self):
        """Deep health check source code references llm_model_health."""
        import inspect
        from app.api.v1.health import health_check_deep
        source = inspect.getsource(health_check_deep)
        assert "llm_model_health" in source
        assert "check_llm_model_health" in source


class TestAsyncPoolComponentHealth:
    """Test ComponentHealth response format."""

    @pytest.mark.asyncio
    async def test_component_health_fields(self):
        """Response has all required ComponentHealth fields."""
        from app.api.v1.health import check_async_pool_health

        with patch(
            "app.api.v1.health.create_async_engine",
            side_effect=Exception("test error"),
        ):
            result = await check_async_pool_health()

        # Check all required fields exist
        assert hasattr(result, "name")
        assert hasattr(result, "status")
        assert hasattr(result, "latency_ms")
        assert hasattr(result, "message")
