"""
Test script for Hybrid Search feature.

Tests Dense Search, Sparse Search, and RRF Reranking.

Usage:
    python scripts/test_hybrid_search.py
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def test_rrf_reranker():
    """Test RRF Reranker logic."""
    print("\n" + "="*60)
    print("TEST 1: RRF Reranker")
    print("="*60)
    
    from app.engine.rrf_reranker import RRFReranker, HybridSearchResult
    from app.repositories.dense_search_repository import DenseSearchResult
    from app.repositories.sparse_search_repository import SparseSearchResult
    
    reranker = RRFReranker(k=60)
    
    # Create mock dense results
    dense_results = [
        DenseSearchResult(node_id="node_1", similarity=0.95),
        DenseSearchResult(node_id="node_2", similarity=0.85),
        DenseSearchResult(node_id="node_3", similarity=0.75),
    ]
    
    # Create mock sparse results (different order)
    sparse_results = [
        SparseSearchResult(node_id="node_2", title="Rule 15", content="...", source="COLREGs", category="Navigation", score=10.5),
        SparseSearchResult(node_id="node_1", title="Rule 14", content="...", source="COLREGs", category="Navigation", score=8.2),
        SparseSearchResult(node_id="node_4", title="Rule 16", content="...", source="COLREGs", category="Navigation", score=5.1),
    ]
    
    # Merge with RRF
    results = reranker.merge(dense_results, sparse_results, limit=5)
    
    print(f"\nMerged {len(results)} results:")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r.node_id}: RRF={r.rrf_score:.4f}, dense={r.dense_score}, sparse={r.sparse_score}")
        print(f"     Appears in both: {r.appears_in_both()}")
    
    # Verify node_2 is boosted (appears in both)
    assert results[0].node_id in ["node_1", "node_2"], "Top result should be node appearing in both"
    print("\n✅ RRF Reranker test passed!")


async def test_embedding_dimensions():
    """Test that embeddings have correct dimensions."""
    print("\n" + "="*60)
    print("TEST 2: Embedding Dimensions (768)")
    print("="*60)
    
    from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
    
    embeddings = GeminiOptimizedEmbeddings()
    
    test_texts = [
        "Rule 15 COLREGs crossing situation",
        "Quy tắc 19 về tầm nhìn hạn chế",
        "SOLAS Chapter II-2 Fire protection"
    ]
    
    for text in test_texts:
        embedding = embeddings.embed_query(text)
        print(f"\n  Text: '{text[:40]}...'")
        print(f"  Dimensions: {len(embedding)}")
        
        # Verify L2 normalization
        import numpy as np
        norm = np.linalg.norm(embedding)
        print(f"  L2 Norm: {norm:.6f}")
        
        assert len(embedding) == 768, f"Expected 768 dimensions, got {len(embedding)}"
        assert abs(norm - 1.0) < 1e-4, f"Expected L2 norm ~1.0, got {norm}"
    
    print("\n✅ Embedding dimensions test passed!")


async def test_sparse_search():
    """Test Neo4j Full-text search."""
    print("\n" + "="*60)
    print("TEST 3: Sparse Search (Neo4j Full-text)")
    print("="*60)
    
    from app.repositories.sparse_search_repository import SparseSearchRepository
    
    repo = SparseSearchRepository()
    
    if not repo.is_available():
        print("⚠️ Neo4j not available, skipping sparse search test")
        return
    
    # Create full-text index if not exists
    await repo.create_fulltext_index()
    
    # Test searches
    test_queries = [
        "Rule 15",
        "crossing situation",
        "Quy tắc 19",
        "tầm nhìn hạn chế"
    ]
    
    for query in test_queries:
        print(f"\n  Query: '{query}'")
        results = await repo.search(query, limit=3)
        print(f"  Results: {len(results)}")
        for r in results[:3]:
            print(f"    - {r.title} (score: {r.score:.2f})")
    
    print("\n✅ Sparse search test passed!")


async def test_hybrid_search_service():
    """Test full hybrid search pipeline."""
    print("\n" + "="*60)
    print("TEST 4: Hybrid Search Service")
    print("="*60)
    
    from app.services.hybrid_search_service import HybridSearchService
    
    service = HybridSearchService(
        dense_weight=0.5,
        sparse_weight=0.5
    )
    
    if not service.is_available():
        print("⚠️ Hybrid search not available (missing Neo4j or pgvector)")
        return
    
    test_queries = [
        "Rule 15 crossing",
        "Quy tắc về tàu cắt hướng",
        "restricted visibility navigation"
    ]
    
    for query in test_queries:
        print(f"\n  Query: '{query}'")
        results = await service.search(query, limit=3)
        print(f"  Results: {len(results)}, Method: {results[0].search_method if results else 'N/A'}")
        for r in results[:3]:
            print(f"    - {r.title}")
            print(f"      RRF: {r.rrf_score:.4f}, Dense: {r.dense_score}, Sparse: {r.sparse_score}")
    
    print("\n✅ Hybrid search service test passed!")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("HYBRID SEARCH TEST SUITE")
    print("="*60)
    
    try:
        await test_rrf_reranker()
        await test_embedding_dimensions()
        await test_sparse_search()
        await test_hybrid_search_service()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
