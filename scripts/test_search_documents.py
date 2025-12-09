"""
Test which documents are returned by search
"""
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_search():
    import asyncpg
    
    db_url = os.getenv("DATABASE_URL", "")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgres://", "postgresql://")
    
    conn = await asyncpg.connect(db_url)
    try:
        # Test search query
        query = "đăng ký tàu biển"
        
        print(f"🔍 Search query: {query}")
        print("="*60)
        
        # Simple text search to see which documents match
        rows = await conn.fetch(
            """
            SELECT 
                document_id,
                page_number,
                CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 'YES' ELSE 'NO' END as has_image,
                LEFT(content, 100) as preview
            FROM knowledge_embeddings
            WHERE content ILIKE $1
            ORDER BY document_id, page_number
            LIMIT 20
            """,
            f"%{query}%"
        )
        
        print(f"Found {len(rows)} matching chunks:\n")
        
        current_doc = None
        for row in rows:
            if row['document_id'] != current_doc:
                current_doc = row['document_id']
                print(f"\n📁 Document: {current_doc}")
            
            img_icon = "🖼️" if row['has_image'] == 'YES' else "❌"
            print(f"  {img_icon} Page {row['page_number']}: {row['preview'][:60]}...")
        
        # Count by document
        print("\n" + "="*60)
        print("📊 Summary by document:")
        rows = await conn.fetch(
            """
            SELECT 
                document_id,
                COUNT(*) as matches,
                COUNT(CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 1 END) as with_image
            FROM knowledge_embeddings
            WHERE content ILIKE $1
            GROUP BY document_id
            ORDER BY matches DESC
            """,
            f"%{query}%"
        )
        
        for row in rows:
            pct = row['with_image']/row['matches']*100 if row['matches'] > 0 else 0
            print(f"  - {row['document_id']}: {row['matches']} matches, {row['with_image']} with image ({pct:.0f}%)")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(test_search())
