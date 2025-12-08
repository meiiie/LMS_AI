"""Test hybrid search directly"""
import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

async def test():
    from app.services.hybrid_search_service import HybridSearchService
    
    service = HybridSearchService()
    
    queries = [
        "Điều 15 về tình huống cắt hướng",
        "Rule 19 tầm nhìn hạn chế",
        "đèn hiệu tàu thuyền"
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        results = await service.search(query, limit=3)
        
        if not results:
            print("❌ No results!")
        else:
            print(f"✅ Found {len(results)} results:")
            for i, r in enumerate(results, 1):
                print(f"\n  [{i}] RRF Score: {r.rrf_score:.3f}, Type: {r.content_type}")
                print(f"      Page: {r.page_number}, Doc: {r.document_id}")
                print(f"      Dense: {r.dense_score}, Sparse: {r.sparse_score}")
                print(f"      Content: {r.content[:150]}...")

asyncio.run(test())
