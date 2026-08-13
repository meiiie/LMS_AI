"""
Sprint 171: PostgreSQL & MinIO Production Hardening Tests.

Tests verify all CRITICAL and HIGH audit fixes:
1. Health check singleton engine (no ephemeral creation)
2. MinIO bucket policy (download, not public)
3. Statement timeout config + pool init
4. Org_id in storage paths (multi-tenant isolation)
5. Sources API pool consolidation (shared DenseSearch pool)
6. Presigned URL support
7. Autovacuum tuning migration

30 tests across 7 groups.
"""

import importlib.util
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock


# ============================================================================
# Helpers
# ============================================================================

def _make_settings(**overrides):
    """Create a mock settings object."""
    s = MagicMock()
    s.enable_multi_tenant = overrides.get("enable_multi_tenant", False)
    s.default_organization_id = overrides.get("default_organization_id", "default")
    s.postgres_url = "postgresql+asyncpg://wiii:secret@localhost:5433/wiii_ai"
    s.postgres_url_sync = "postgresql+psycopg://wiii:secret@localhost:5433/wiii_ai"
    s.asyncpg_url = "postgresql://wiii:secret@localhost:5433/wiii_ai"
    s.async_pool_min_size = 2
    s.async_pool_max_size = 10
    s.postgres_statement_timeout_ms = 30000
    s.postgres_idle_in_transaction_timeout_ms = 60000
    s.storage_url = "http://localhost:9000"
    s.storage_key = "test-key"
    s.storage_bucket = "wiii-docs"
    s.app_name = "wiii"
    s.app_version = "1.0"
    s.environment = "test"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ============================================================================
# Group 1: Health Check Singleton Engine (4 tests)
# ============================================================================

class TestHealthCheckSingleton:
    """Verify health check uses singleton async engine."""

    def test_shared_engine_module_var_exists(self):
        """health.py declares _shared_async_engine module variable."""
        from app.api.v1 import health
        assert hasattr(health, "_shared_async_engine")

    def test_get_shared_async_engine_is_defined(self):
        """_get_shared_async_engine function exists."""
        from app.api.v1.health import _get_shared_async_engine
        import asyncio
        assert callable(_get_shared_async_engine)

    @pytest.mark.asyncio
    async def test_shared_engine_reuses_instance(self):
        """Multiple calls return the same engine object."""
        import app.api.v1.health as health_mod
        # Reset
        health_mod._shared_async_engine = None

        with patch("app.api.v1.health.create_async_engine") as mock_create, \
             patch("app.api.v1.health.settings", _make_settings()):
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            engine1 = await health_mod._get_shared_async_engine()
            engine2 = await health_mod._get_shared_async_engine()

            assert engine1 is engine2
            mock_create.assert_called_once()  # Only created ONCE

        # Cleanup
        health_mod._shared_async_engine = None



# ============================================================================
# Group 2: MinIO Bucket Policy (2 tests)
# ============================================================================

class TestMinioBucketPolicy:
    """Verify docker-compose uses download policy, not public."""

    def test_docker_compose_no_public_policy(self):
        """docker-compose.yml should NOT have 'mc policy set public'."""
        compose_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "docker-compose.yml",
        )
        with open(compose_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "policy set public" not in content, \
            "MinIO bucket should NOT use public policy"

    def test_docker_compose_uses_download_policy(self):
        """docker-compose.yml should use 'mc anonymous set download'."""
        compose_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "docker-compose.yml",
        )
        with open(compose_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "anonymous set download" in content, \
            "MinIO bucket should use download (read-only) policy"


# ============================================================================
# Group 3: Statement Timeout Config (5 tests)
# ============================================================================

class TestStatementTimeout:
    """Verify statement_timeout is configured and applied."""

    def test_config_has_statement_timeout_field(self):
        """config.py Settings has postgres_statement_timeout_ms field."""
        from app.core.config import Settings
        field_names = [f for f in Settings.model_fields]
        assert "postgres_statement_timeout_ms" in field_names

    def test_config_has_idle_transaction_timeout_field(self):
        """config.py Settings has postgres_idle_in_transaction_timeout_ms field."""
        from app.core.config import Settings
        field_names = [f for f in Settings.model_fields]
        assert "postgres_idle_in_transaction_timeout_ms" in field_names

    def test_statement_timeout_default_30s(self):
        """Default statement_timeout is 30000ms."""
        from app.core.config import Settings
        default = Settings.model_fields["postgres_statement_timeout_ms"].default
        assert default == 30000

    def test_idle_transaction_timeout_default_60s(self):
        """Default idle_in_transaction_timeout is 60000ms."""
        from app.core.config import Settings
        default = Settings.model_fields["postgres_idle_in_transaction_timeout_ms"].default
        assert default == 60000

    def test_database_module_uses_event_listener(self):
        """database.py sets statement_timeout via SQLAlchemy event listener."""
        import os
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "app", "core", "database.py",
        )
        with open(db_path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "statement_timeout" in source
        assert "listens_for" in source



# ============================================================================
# Group 4: Org_id in Storage Paths (5 tests)
# ============================================================================

class TestStorageOrgPaths:
    """Verify storage paths include org_id when multi-tenant enabled."""

    def test_build_path_no_org_default(self):
        """Without multi-tenant, path is flat: {doc_id}/page_{n}.jpg."""
        with patch("app.core.config.settings", _make_settings(enable_multi_tenant=False)):
            from app.services.object_storage import ObjectStorageClient
            client = ObjectStorageClient.__new__(ObjectStorageClient)
            client.bucket = "test"
            path = client._build_path("doc-1", 5)
        assert path == "doc-1/page_5.jpg"

    def test_build_path_with_org(self):
        """With multi-tenant + org context, path includes org_id prefix."""
        with patch("app.core.config.settings", _make_settings(enable_multi_tenant=True)), \
             patch("app.services.object_storage.ObjectStorageClient._get_org_prefix",
                    return_value="org-maritime"):
            from app.services.object_storage import ObjectStorageClient
            client = ObjectStorageClient.__new__(ObjectStorageClient)
            client.bucket = "test"
            path = client._build_path("doc-1", 5)
        assert path == "org-maritime/doc-1/page_5.jpg"

    def test_build_path_org_default_is_excluded(self):
        """org_id='default' should NOT add prefix (backward compat)."""
        with patch("app.core.config.settings", _make_settings(enable_multi_tenant=True)):
            from app.services.object_storage import ObjectStorageClient
            with patch.object(ObjectStorageClient, "_get_org_prefix", return_value=""):
                client = ObjectStorageClient.__new__(ObjectStorageClient)
                client.bucket = "test"
                path = client._build_path("doc-1", 3)
        assert path == "doc-1/page_3.jpg"

    def test_get_org_prefix_returns_empty_when_disabled(self):
        """_get_org_prefix returns '' when multi-tenant disabled."""
        with patch("app.core.config.settings", _make_settings(enable_multi_tenant=False)):
            from app.services.object_storage import ObjectStorageClient
            result = ObjectStorageClient._get_org_prefix()
        assert result == ""

    def test_different_orgs_produce_different_paths(self):
        """Two orgs produce distinct storage paths for same document."""
        from app.services.object_storage import ObjectStorageClient

        client = ObjectStorageClient.__new__(ObjectStorageClient)
        client.bucket = "test"

        with patch.object(ObjectStorageClient, "_get_org_prefix", return_value="org-A"):
            path_a = client._build_path("doc-1", 1)
        with patch.object(ObjectStorageClient, "_get_org_prefix", return_value="org-B"):
            path_b = client._build_path("doc-1", 1)

        assert path_a != path_b
        assert "org-A" in path_a
        assert "org-B" in path_b


# ============================================================================
# Group 5: Sources Pool Consolidation (3 tests)
# ============================================================================

class TestSourcesPoolConsolidation:
    """Verify Sources API uses shared DenseSearch pool."""



    @pytest.mark.asyncio
    async def test_sources_close_pool_is_noop(self):
        """close_pool() is a no-op (lifecycle managed by DenseSearch)."""
        import importlib
        import app.api.v1.sources as _sources_mod
        # Reload in case test pollution replaced module with a MagicMock stub
        if not hasattr(_sources_mod, 'close_pool'):
            importlib.reload(_sources_mod)
        # Should not raise
        await _sources_mod.close_pool()


# ============================================================================
# Group 6: Presigned URL Support (4 tests)
# ============================================================================

class TestPresignedUrls:
    """Verify presigned URL support in ObjectStorageClient."""

    def test_get_signed_url_method_exists(self):
        """ObjectStorageClient has get_signed_url method."""
        from app.services.object_storage import ObjectStorageClient
        assert hasattr(ObjectStorageClient, "get_signed_url")

    def test_get_signed_url_default_expiry_1h(self):
        """Default expires_in parameter is 3600 (1 hour)."""
        import inspect
        from app.services.object_storage import ObjectStorageClient
        sig = inspect.signature(ObjectStorageClient.get_signed_url)
        assert sig.parameters["expires_in"].default == 3600

    def test_get_signed_url_calls_presigned_get_object(self):
        """get_signed_url delegates to MinIO presigned_get_object."""
        from app.services.object_storage import ObjectStorageClient
        from datetime import timedelta
        client = ObjectStorageClient.__new__(ObjectStorageClient)
        client.bucket = "test"
        client.secure = False
        client.endpoint = "test.co:9000"
        client.external_endpoint = ""

        mock_minio = MagicMock()
        mock_minio.presigned_get_object.return_value = "http://test.co:9000/test/test/path.jpg?X-Amz-Signature=abc"
        client._client = mock_minio

        url = client.get_signed_url("test/path.jpg", expires_in=7200)
        assert "path.jpg" in url
        mock_minio.presigned_get_object.assert_called_once_with(
            "test", "test/path.jpg", expires=timedelta(seconds=7200)
        )

    def test_get_signed_url_fallback_to_public(self):
        """On error, get_signed_url falls back to get_public_url."""
        from app.services.object_storage import ObjectStorageClient
        client = ObjectStorageClient.__new__(ObjectStorageClient)
        client.bucket = "test"
        client.secure = False
        client.endpoint = "test.co:9000"
        client.external_endpoint = ""

        mock_minio = MagicMock()
        mock_minio.presigned_get_object.side_effect = Exception("SDK error")
        client._client = mock_minio

        url = client.get_signed_url("test/path.jpg")
        assert url == "http://test.co:9000/test/test/path.jpg"


# ============================================================================
# Group 7: Autovacuum Migration (4 tests)
# ============================================================================

class TestAutovacuumMigration:
    """Verify migration 018 autovacuum tuning."""

    def _load_migration(self):
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "alembic", "versions", "018_autovacuum_and_safety.py",
        )
        spec = importlib.util.spec_from_file_location("migration_018", migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_migration_revision_chain(self):
        """Migration 018 follows 017."""
        mod = self._load_migration()
        assert mod.revision == "018"
        assert mod.down_revision == "017"

    def test_migration_has_upgrade_and_downgrade(self):
        """Migration has both functions."""
        mod = self._load_migration()
        assert callable(getattr(mod, "upgrade", None))
        assert callable(getattr(mod, "downgrade", None))

    def test_migration_source_contains_autovacuum_settings(self):
        """Migration SQL includes autovacuum_vacuum_scale_factor."""
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "alembic", "versions", "018_autovacuum_and_safety.py",
        )
        with open(migration_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "autovacuum_vacuum_scale_factor" in source
        assert "autovacuum_analyze_scale_factor" in source
        assert "autovacuum_vacuum_cost_delay" in source
        assert "autovacuum_vacuum_cost_limit" in source

    def test_migration_targets_hot_tables(self):
        """Migration targets semantic_memories, knowledge_embeddings, chat_messages."""
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "alembic", "versions", "018_autovacuum_and_safety.py",
        )
        with open(migration_path, "r", encoding="utf-8") as f:
            source = f.read()

        for table in ["semantic_memories", "knowledge_embeddings", "chat_messages", "chat_history"]:
            assert table in source, f"Missing hot table: {table}"


# ============================================================================
# Group 8: Upload Safety (3 tests)
# ============================================================================

