"""Test sparse search returns image_url"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.repositories.sparse_search_repository import SparseSearchRepository

async def test():
    repo = SparseSearchRepository()
    results = await repo.search('điều kiện đăng ký tàu biển', limit=5)
    print(f'Results: {len(results)}')
    for r in results:
        img = r.image_url[:50] if r.image_url else "None"
        print(f'  - {r.title[:50]}... | image_url: {img}...')

if __name__ == "__main__":
    asyncio.run(test())
