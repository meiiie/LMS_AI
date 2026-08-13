"""
Test connection pool configuration.
Verifies TASK-001 fix.
"""
import pytest
from app.core.config import settings


def test_async_pool_config_exists():
    """Verify async pool configuration is defined."""
    assert hasattr(settings, 'async_pool_min_size')
    assert hasattr(settings, 'async_pool_max_size')


def test_async_pool_config_values():
    """Verify pool sizes are reasonable."""
    assert settings.async_pool_min_size >= 1, "min_size should be at least 1"
    assert settings.async_pool_max_size >= 5, "max_size should be at least 5"
    assert settings.async_pool_max_size >= settings.async_pool_min_size




def test_sparse_repo_has_pool():
    """Verify SparseSearchRepository has connection pooling."""
    from app.repositories.sparse_search_repository import SparseSearchRepository

    repo = SparseSearchRepository()
    assert hasattr(repo, '_pool'), "SparseSearchRepository should have _pool attribute"
    assert hasattr(repo, '_get_pool'), "SparseSearchRepository should have _get_pool method"
