"""
Investigation Script: Sources và Evidence Images

Điều tra 2 vấn đề:
1. Tại sao một số queries không có sources?
2. Tại sao chỉ 2/5 sources có image_url?
"""
import os
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

async def check_database_stats():
    """Check database for image_url coverage"""
    import asyncpg
    
    db_url = os.getenv("DATABASE_URL", "")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgres://", "postgresql://")
    
    conn = await asyncpg.connect(db_url)
    try:
        # Total chunks
        total = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
        print(f"📊 Total chunks in DB: {total}")
        
        # Chunks with image_url
        with_image = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_embeddings WHERE image_url IS NOT NULL AND image_url != ''"
        )
        print(f"🖼️ Chunks with image_url: {with_image} ({with_image/total*100:.1f}%)")
        
        # Chunks without image_url
        without_image = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_embeddings WHERE image_url IS NULL OR image_url = ''"
        )
        print(f"❌ Chunks without image_url: {without_image} ({without_image/total*100:.1f}%)")
        
        # Sample chunks without image_url
        print("\n📝 Sample chunks WITHOUT image_url:")
        rows = await conn.fetch(
            """
            SELECT id::text, document_id, page_number, LEFT(content, 100) as content_preview
            FROM knowledge_embeddings 
            WHERE image_url IS NULL OR image_url = ''
            LIMIT 5
            """
        )
        for row in rows:
            print(f"  - ID: {row['id'][:8]}... | Doc: {row['document_id']} | Page: {row['page_number']}")
            print(f"    Content: {row['content_preview']}...")
        
        # Sample chunks WITH image_url
        print("\n✅ Sample chunks WITH image_url:")
        rows = await conn.fetch(
            """
            SELECT id::text, document_id, page_number, image_url, LEFT(content, 100) as content_preview
            FROM knowledge_embeddings 
            WHERE image_url IS NOT NULL AND image_url != ''
            LIMIT 5
            """
        )
        for row in rows:
            print(f"  - ID: {row['id'][:8]}... | Doc: {row['document_id']} | Page: {row['page_number']}")
            print(f"    Image: {row['image_url'][:60]}...")
        
        # Check by document_id
        print("\n📁 Image coverage by document:")
        rows = await conn.fetch(
            """
            SELECT 
                document_id,
                COUNT(*) as total,
                COUNT(CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 1 END) as with_image
            FROM knowledge_embeddings
            GROUP BY document_id
            ORDER BY total DESC
            """
        )
        for row in rows:
            pct = row['with_image']/row['total']*100 if row['total'] > 0 else 0
            print(f"  - {row['document_id']}: {row['with_image']}/{row['total']} ({pct:.0f}%)")
        
    finally:
        await conn.close()


async def test_hybrid_search():
    """Test hybrid search to see if image_url is returned"""
    from app.services.hybrid_search_service import get_hybrid_search_service
    
    search_service = get_hybrid_search_service()
    
    queries = [
        "Luật Hàng hải Việt Nam 2015 quy định những gì về tàu biển?",
        "Điều kiện để đăng ký tàu biển Việt Nam là gì?",
        "thuyền viên"
    ]
    
    print("\n" + "="*60)
    print("🔍 HYBRID SEARCH TEST")
    print("="*60)
    
    for query in queries:
        print(f"\n📝 Query: {query[:50]}...")
        results = await search_service.search(query, limit=5)
        
        print(f"   Results: {len(results)}")
        for i, r in enumerate(results):
            has_image = "✅" if r.image_url else "❌"
            print(f"   {i+1}. {has_image} {r.title[:40]}... | image_url: {r.image_url[:30] if r.image_url else 'None'}...")


async def test_rag_query():
    """Test RAG query to see sources and evidence images"""
    from app.engine.tools.rag_tool import RAGAgent, get_knowledge_repository
    
    rag = RAGAgent()
    
    queries = [
        "Điều kiện để đăng ký tàu biển Việt Nam là gì?",
    ]
    
    print("\n" + "="*60)
    print("🔍 RAG QUERY TEST")
    print("="*60)
    
    for query in queries:
        print(f"\n📝 Query: {query[:50]}...")
        response = await rag.query(query, limit=5)
        
        print(f"   Citations: {len(response.citations)}")
        for c in response.citations:
            has_image = "✅" if c.image_url else "❌"
            print(f"   - {has_image} {c.title[:40]}... | image_url: {c.image_url[:30] if c.image_url else 'None'}...")
        
        print(f"\n   Evidence Images: {len(response.evidence_images)}")
        for img in response.evidence_images:
            print(f"   - Page {img.page_number}: {img.url[:50]}...")


async def main():
    print("="*60)
    print("SOURCES & EVIDENCE IMAGES INVESTIGATION")
    print("="*60)
    
    await check_database_stats()
    await test_hybrid_search()
    await test_rag_query()


if __name__ == "__main__":
    asyncio.run(main())
