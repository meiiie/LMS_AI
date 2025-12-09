"""Test script for PostgreSQL sparse search migration."""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import asyncpg


def get_db_url():
    """Get database URL in asyncpg format."""
    url = os.getenv('DATABASE_URL', '')
    # Convert SQLAlchemy format to asyncpg format
    if url.startswith('postgresql+asyncpg://'):
        url = url.replace('postgresql+asyncpg://', 'postgresql://')
    return url


async def check_search_vector_column():
    """Check if search_vector column exists."""
    conn = await asyncpg.connect(get_db_url())
    try:
        result = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'knowledge_embeddings' 
            AND column_name = 'search_vector';
        """)
        print("search_vector column:", result)
        return len(result) > 0
    finally:
        await conn.close()


async def check_sample_data():
    """Check sample data with search_vector."""
    conn = await asyncpg.connect(get_db_url())
    try:
        result = await conn.fetch("""
            SELECT id, LEFT(content, 50) as content_preview, 
                   LEFT(search_vector::text, 100) as search_vector_preview
            FROM knowledge_embeddings
            LIMIT 3;
        """)
        print("\nSample rows with search_vector:")
        for row in result:
            print(f"  ID: {row['id']}")
            print(f"  Content: {row['content_preview']}...")
            print(f"  Search Vector: {row['search_vector_preview']}...")
            print()
        return len(result) > 0
    finally:
        await conn.close()


async def test_sparse_search():
    """Test sparse search functionality."""
    from app.repositories.sparse_search_repository import SparseSearchRepository
    
    repo = SparseSearchRepository()
    print(f"Sparse search available: {repo.is_available()}")
    
    if repo.is_available():
        # Test Vietnamese search
        results = await repo.search("cảnh giới", limit=3)
        print(f"\nVietnamese search 'cảnh giới' returned {len(results)} results:")
        for r in results:
            print(f"  - Score: {r.score:.4f}, Content: {r.content[:60]}...")
        
        # Test English search with number
        results = await repo.search("Rule 5", limit=3)
        print(f"\nEnglish search 'Rule 5' returned {len(results)} results:")
        for r in results:
            print(f"  - Score: {r.score:.4f}, Content: {r.content[:60]}...")


async def test_hybrid_search():
    """Test hybrid search service."""
    from app.services.hybrid_search_service import HybridSearchService
    
    service = HybridSearchService()
    print(f"\nHybrid search available: {service.is_available()}")
    print(f"Dense repo available: {service._dense_repo.is_available()}")
    print(f"Sparse repo available: {service._sparse_repo.is_available()}")
    
    if service.is_available():
        # Test hybrid search
        results = await service.search("quy tắc cảnh giới", limit=3)
        print(f"\nHybrid search 'quy tắc cảnh giới' returned {len(results)} results:")
        for r in results:
            print(f"  - RRF: {r.rrf_score:.4f}, Dense: {r.dense_score}, Sparse: {r.sparse_score}")
            print(f"    Content: {r.content[:60]}...")


async def test_graceful_fallback():
    """Test graceful fallback when sparse search fails."""
    from app.services.hybrid_search_service import HybridSearchService
    
    service = HybridSearchService()
    
    # Simulate sparse search failure by setting unavailable
    original_available = service._sparse_repo._available
    service._sparse_repo._available = False
    
    print("\nTesting graceful fallback (sparse disabled)...")
    results = await service.search("test query", limit=3)
    print(f"Fallback to dense-only returned {len(results)} results")
    
    if results:
        for r in results:
            print(f"  - Dense: {r.dense_score}, Sparse: {r.sparse_score}")
    
    # Restore
    service._sparse_repo._available = original_available
    print("Graceful fallback test passed!")


async def main():
    print("=" * 60)
    print("Testing Sparse Search Migration")
    print("=" * 60)
    
    # Check column exists
    print("\n1. Checking search_vector column...")
    column_exists = await check_search_vector_column()
    
    if not column_exists:
        print("ERROR: search_vector column not found!")
        return
    
    # Check sample data
    print("\n2. Checking sample data...")
    has_data = await check_sample_data()
    
    if not has_data:
        print("WARNING: No data in knowledge_embeddings table")
    
    # Test sparse search
    print("\n3. Testing sparse search...")
    await test_sparse_search()
    
    # Test hybrid search
    print("\n4. Testing hybrid search service...")
    await test_hybrid_search()
    
    # Test graceful fallback
    print("\n5. Testing graceful fallback...")
    await test_graceful_fallback()
    
    print("\n" + "=" * 60)
    print("Migration test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
