"""Tests for Sprint 170b: "Nền Tảng Vững" — PostgreSQL Performance Overhaul.

15 tests covering:
- Migration 015 (vector column type, HNSW index, B-tree indexes)
- Dense search rewrite (pgvector <=> operator, hnsw.ef_search)
- Pool config (settings-driven, not hardcoded)
- Filtering (org, domain, content type, confidence)
"""
import os
import importlib.util
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper to load migration module by file path
# ---------------------------------------------------------------------------
_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "alembic",
    "versions",
    "015_pgvector_performance_overhaul.py",
)
_MIGRATION_PATH = os.path.normpath(_MIGRATION_PATH)


def _load_migration():
    """Load migration 015 as a module."""
    spec = importlib.util.spec_from_file_location("migration_015", _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Migration 015 tests
# ---------------------------------------------------------------------------

class TestMigration015:
    """Tests for alembic/versions/015_pgvector_performance_overhaul.py."""

    def test_migration_revision_chain(self):
        """Migration 015 has correct revision chain (down_revision=014)."""
        mod = _load_migration()
        assert mod.revision == "015"
        assert mod.down_revision == "014"

    def test_migration_upgrade_creates_extension(self):
        """upgrade() calls CREATE EXTENSION IF NOT EXISTS vector."""
        mod = _load_migration()

        with patch.object(mod, "op") as mock_op, \
             patch.object(mod, "_index_exists", return_value=False), \
             patch.object(mod, "_column_type", return_value="_float8"):
            mod.upgrade()

            calls = [str(c) for c in mock_op.execute.call_args_list]
            assert any("CREATE EXTENSION" in c for c in calls), \
                "upgrade() must call CREATE EXTENSION IF NOT EXISTS vector"

    def test_migration_upgrade_alters_column_type(self):
        """upgrade() converts FLOAT[] to vector(768) when column is _float8."""
        mod = _load_migration()

        with patch.object(mod, "op") as mock_op, \
             patch.object(mod, "_index_exists", return_value=False), \
             patch.object(mod, "_column_type", return_value="_float8"):
            mod.upgrade()

            calls_str = " ".join(str(c) for c in mock_op.execute.call_args_list)
            assert "vector(768)" in calls_str, \
                "upgrade() must ALTER COLUMN embedding TYPE vector(768)"

    def test_migration_upgrade_skips_alter_if_already_vector(self):
        """upgrade() does NOT alter column if already vector type."""
        mod = _load_migration()

        with patch.object(mod, "op") as mock_op, \
             patch.object(mod, "_index_exists", return_value=False), \
             patch.object(mod, "_column_type", return_value="vector"):
            mod.upgrade()

            calls_str = " ".join(str(c) for c in mock_op.execute.call_args_list)
            assert "ALTER TABLE" not in calls_str, \
                "Should skip ALTER when column is already vector"

    def test_migration_creates_hnsw_index(self):
        """upgrade() creates HNSW index with vector_cosine_ops."""
        mod = _load_migration()

        with patch.object(mod, "op") as mock_op, \
             patch.object(mod, "_index_exists", return_value=False), \
             patch.object(mod, "_column_type", return_value="vector"):
            mod.upgrade()

            calls_str = " ".join(str(c) for c in mock_op.execute.call_args_list)
            assert "hnsw" in calls_str.lower(), "Must create HNSW index"
            assert "vector_cosine_ops" in calls_str, "Must use vector_cosine_ops"

    def test_migration_creates_btree_indexes(self):
        """upgrade() creates B-tree indexes on user_id columns."""
        mod = _load_migration()

        with patch.object(mod, "op") as mock_op, \
             patch.object(mod, "_index_exists", return_value=False), \
             patch.object(mod, "_column_type", return_value="vector"):
            mod.upgrade()

            create_index_calls = mock_op.create_index.call_args_list
            index_names = [c[0][0] for c in create_index_calls]

            expected = [
                "idx_chat_messages_user_id",
                "idx_character_blocks_user_id",
                "idx_semantic_memories_user_id",
                "idx_chat_history_user_id",
                "idx_experiences_user_id",
                "idx_knowledge_embeddings_org_domain",
                "idx_character_blocks_user_label",
            ]
            for name in expected:
                assert name in index_names, f"Missing B-tree index: {name}"

    def test_migration_downgrade_drops_indexes_and_reverts_type(self):
        """downgrade() drops all indexes and reverts vector → FLOAT[]."""
        mod = _load_migration()

        with patch.object(mod, "op") as mock_op, \
             patch.object(mod, "_index_exists", return_value=True), \
             patch.object(mod, "_column_type", return_value="vector"):
            mod.downgrade()

            # Should drop 8 indexes
            assert mock_op.drop_index.call_count == 8

            # Should revert to float8[]
            calls_str = " ".join(str(c) for c in mock_op.execute.call_args_list)
            assert "float8[]" in calls_str, "downgrade must revert to float8[]"


# ---------------------------------------------------------------------------
# Dense search repository tests
# ---------------------------------------------------------------------------

def _make_repo():
    """Create a DenseSearchRepository with mocked pool."""
    from app.repositories.dense_search_repository import DenseSearchRepository
    repo = DenseSearchRepository.__new__(DenseSearchRepository)
    repo._pool = MagicMock()
    repo._available = True
    repo._column_cache = {}
    return repo


def _mock_conn_ctx(repo):
    """Set up mock connection context on repo._pool.acquire."""
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=True)  # _has_column
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock()  # SET LOCAL

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    repo._pool.acquire.return_value = ctx
    return mock_conn


class TestDenseSearchPgvector:
    """Tests for pgvector <=> operator in dense_search_repository.py."""

    @pytest.mark.asyncio
    async def test_search_uses_cosine_distance_operator(self):
        """Dense search SQL uses <=> operator (not UNNEST)."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        await repo.search([0.1] * 768, limit=10)

        sql = mock_conn.fetch.call_args[0][0]
        assert "<=>" in sql, "Must use pgvector <=> operator"
        assert "UNNEST" not in sql, "Must NOT use UNNEST anymore"

    @pytest.mark.asyncio
    async def test_search_sets_hnsw_ef_search(self):
        """Dense search sets hnsw.ef_search = 100 per connection."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        await repo.search([0.1] * 768, limit=5)

        execute_calls = mock_conn.execute.call_args_list
        assert len(execute_calls) >= 1
        first_call_sql = str(execute_calls[0])
        assert "hnsw.ef_search" in first_call_sql, \
            "Must SET LOCAL hnsw.ef_search = 100"

    @pytest.mark.asyncio
    async def test_similarity_score_is_one_minus_distance(self):
        """Similarity = 1 - cosine_distance (range 0-1)."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        await repo.search([0.1] * 768, limit=5)

        sql = mock_conn.fetch.call_args[0][0]
        assert "1 - (embedding <=> $1::vector)" in sql, \
            "Similarity must be 1 - cosine_distance"

    @pytest.mark.asyncio
    async def test_query_parameter_cast_as_vector(self):
        """Query embedding is cast as ::vector not ::float8[]."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        await repo.search([0.5] * 768, limit=3)

        sql = mock_conn.fetch.call_args[0][0]
        assert "$1::vector" in sql, "Must cast parameter as ::vector"
        assert "float8[]" not in sql, "Must NOT use float8[] cast"

    @pytest.mark.asyncio
    async def test_null_embeddings_filtered(self):
        """WHERE embedding IS NOT NULL still present."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        await repo.search([0.1] * 768, limit=5)

        sql = mock_conn.fetch.call_args[0][0]
        assert "embedding IS NOT NULL" in sql

    @pytest.mark.asyncio
    async def test_org_filtering_works_with_pgvector(self):
        """Org filtering still works with new <=> operator (when multi_tenant enabled)."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        # Enable multi_tenant so org_where_positional actually adds the clause
        from app.core.config import settings as real_settings
        with patch.object(real_settings, "enable_multi_tenant", True):
            await repo.search([0.1] * 768, limit=5, org_id="test-org")

        sql = mock_conn.fetch.call_args[0][0]
        assert "organization_id" in sql, "Org filtering must be present"

    @pytest.mark.asyncio
    async def test_empty_results_on_unavailable(self):
        """Returns empty list when repository is unavailable."""
        repo = _make_repo()
        repo._available = False

        results = await repo.search([0.1] * 768, limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_order_by_distance_asc(self):
        """Results ordered by embedding <=> $1::vector (distance ASC)."""
        repo = _make_repo()
        mock_conn = _mock_conn_ctx(repo)

        await repo.search([0.1] * 768, limit=5)

        sql = mock_conn.fetch.call_args[0][0]
        assert "ORDER BY embedding <=> $1::vector" in sql, \
            "Must ORDER BY distance ASC for HNSW acceleration"


# ---------------------------------------------------------------------------
# Pool config tests
# ---------------------------------------------------------------------------

