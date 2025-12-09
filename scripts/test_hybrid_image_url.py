"""Test hybrid search returns image_url"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from app.services.hybrid_search_service import get_hybrid_search_service

async def test():
    service = get_hybrid_search_service()
    results = await service.search('điều kiện đăng ký tàu biển', limit=5)
    print(f'Hybrid Results: {len(results)}')
    
    with_image = 0
    for r in results:
        img = r.image_url[:50] if r.image_url else "None"
        has_img = "✅" if r.image_url else "❌"
        if r.image_url:
            with_image += 1
        print(f'  {has_img} {r.title[:40]}... | image_url: {img}...')
    
    print(f'\n📊 Summary: {with_image}/{len(results)} have image_url')

if __name__ == "__main__":
    asyncio.run(test())
