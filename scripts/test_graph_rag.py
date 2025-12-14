"""
Test script for GraphRAG Service integration

Run: python -m scripts.test_graph_rag
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.graph_rag_service import GraphRAGService, get_graph_rag_service


async def test_graph_rag():
    """Test GraphRAG service"""
    print("=" * 60)
    print("GraphRAG Service Test")
    print("=" * 60)
    
    service = get_graph_rag_service()
    
    print(f"\n✅ GraphRAGService created")
    print(f"   HybridSearch available: {service.is_available()}")
    print(f"   Neo4j graph available: {service.is_graph_available()}")
    
    # Test search with entity context
    print("\n" + "=" * 60)
    print("Testing Graph-Enhanced Search")
    print("=" * 60)
    
    query = "Thuyền trưởng có trách nhiệm và nghĩa vụ gì trên tàu biển?"
    print(f"\n📝 Query: {query}")
    
    print("\n🔄 Searching with graph context...")
    
    results, entity_context = await service.search_with_graph_context(
        query=query,
        limit=3
    )
    
    print(f"\n📌 Results: {len(results)} found")
    
    for i, r in enumerate(results):
        print(f"\n   [{i+1}] Score: {r.score:.3f}")
        print(f"       Content: {r.content[:100]}...")
        if r.related_regulations:
            print(f"       Related: {', '.join(r.related_regulations)}")
    
    if entity_context:
        print(f"\n🔗 Entity Context for LLM:")
        print(f"   {entity_context}")
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = len(results) > 0
    print(f"   GraphRAG search: {'✅ PASS' if passed else '❌ FAIL'}")
    
    return passed


if __name__ == "__main__":
    asyncio.run(test_graph_rag())
