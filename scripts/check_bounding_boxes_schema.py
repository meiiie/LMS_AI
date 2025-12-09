"""
Quick script to check if bounding_boxes column exists in database.

Feature: source-highlight-citation
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def check_schema():
    """Check if bounding_boxes column exists."""
    from app.core.database import get_shared_pool
    
    pool = await get_shared_pool()
    if pool is None:
        print("❌ Database pool not available")
        return
    
    async with pool.acquire() as conn:
        # Check column exists
        row = await conn.fetchrow("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'knowledge_embeddings' 
            AND column_name = 'bounding_boxes'
        """)
        
        if row:
            print(f"✅ Column 'bounding_boxes' exists")
            print(f"   Type: {row['data_type']}")
        else:
            print("❌ Column 'bounding_boxes' NOT FOUND")
            print("   Run migration: alembic upgrade head")
            return
        
        # Check sample data
        sample = await conn.fetchrow("""
            SELECT node_id, document_id, page_number, bounding_boxes
            FROM knowledge_embeddings
            WHERE bounding_boxes IS NOT NULL
            LIMIT 1
        """)
        
        if sample:
            print(f"\n📦 Sample with bounding_boxes:")
            print(f"   node_id: {sample['node_id']}")
            print(f"   document_id: {sample['document_id']}")
            print(f"   page_number: {sample['page_number']}")
            print(f"   bounding_boxes: {sample['bounding_boxes']}")
        else:
            print("\n⚠️  No chunks have bounding_boxes yet")
            print("   Run: python scripts/reingest_bounding_boxes.py --pdf <path> --document-id <id>")
        
        # Count stats
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total,
                COUNT(bounding_boxes) as with_boxes
            FROM knowledge_embeddings
        """)
        
        print(f"\n📊 Statistics:")
        print(f"   Total chunks: {stats['total']}")
        print(f"   With bounding_boxes: {stats['with_boxes']}")
        print(f"   Without: {stats['total'] - stats['with_boxes']}")


if __name__ == "__main__":
    asyncio.run(check_schema())
