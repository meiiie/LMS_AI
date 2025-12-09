#!/usr/bin/env python
"""
Test RAG search locally with image_url verification.
Tests the full pipeline: search → results with image_url.
"""
import sys
import asyncio

sys.path.insert(0, ".")

from app.services.hybrid_search_service import HybridSearchService
from app.core.config import settings


async def test_search_with_images():
    print("=" * 60)
    print("🔍 Testing Local RAG Search with Image URLs")
    print("=" * 60)

    # Initialize search service
    search_service = HybridSearchService()

    # Test queries that should match colregs_vn_2015 document
    test_queries = [
        "Bộ luật hàng hải Việt Nam",
        "Điều 1 phạm vi điều chỉnh",
        "tàu thuyền phương tiện",
    ]

    for query in test_queries:
        print(f"\n📋 Query: {query}")
        print("-" * 50)

        try:
            results = await search_service.search(query=query, limit=5)

            print(f"   Results: {len(results)}")

            images_found = 0
            for i, result in enumerate(results):
                has_image = bool(result.image_url)
                if has_image:
                    images_found += 1

                print(f"\n   [{i+1}] RRF Score: {result.rrf_score:.4f}")
                print(f"       Doc: {result.document_id}, Page: {result.page_number}")
                print(f"       Content: {result.content[:80]}...")
                print(f"       Image URL: {result.image_url or 'None'}")

            print(f"\n   📷 Results with image_url: {images_found}/{len(results)}")

            if images_found > 0:
                print("   ✅ SUCCESS: Found results with image URLs!")
            else:
                print("   ⚠️ WARNING: No image URLs in results")

        except Exception as e:
            print(f"   ❌ ERROR: {e}")

    print("\n" + "=" * 60)
    print("🏁 Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_search_with_images())
