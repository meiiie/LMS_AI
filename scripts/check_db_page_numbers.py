#!/usr/bin/env python3
"""
Check if database records have page_number populated.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def check_page_numbers():
    import asyncpg
    from app.core.config import settings
    
    db_url = settings.database_url or ""
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgres://", "postgresql://")
    
    conn = await asyncpg.connect(db_url)
    
    try:
        # Count total records
        total = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
        print(f"Total records: {total}")
        
        # Count records with page_number
        with_page = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_embeddings WHERE page_number IS NOT NULL"
        )
        print(f"Records with page_number: {with_page}")
        
        # Count records without page_number
        without_page = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_embeddings WHERE page_number IS NULL"
        )
        print(f"Records without page_number: {without_page}")
        
        # Get distinct document_ids
        docs = await conn.fetch(
            "SELECT DISTINCT document_id, COUNT(*) as cnt FROM knowledge_embeddings GROUP BY document_id"
        )
        print(f"\nDocuments in DB:")
        for doc in docs:
            print(f"  - {doc['document_id']}: {doc['cnt']} records")
        
        # Sample records with page_number
        samples = await conn.fetch(
            """
            SELECT id::text as node_id, document_id, page_number, 
                   LEFT(content, 100) as content_preview
            FROM knowledge_embeddings 
            WHERE page_number IS NOT NULL
            LIMIT 5
            """
        )
        if samples:
            print(f"\nSample records WITH page_number:")
            for s in samples:
                print(f"  - {s['node_id'][:20]}... page={s['page_number']}, doc={s['document_id']}")
        
        # Sample records without page_number
        samples_null = await conn.fetch(
            """
            SELECT id::text as node_id, document_id, page_number,
                   LEFT(content, 100) as content_preview
            FROM knowledge_embeddings 
            WHERE page_number IS NULL
            LIMIT 5
            """
        )
        if samples_null:
            print(f"\nSample records WITHOUT page_number:")
            for s in samples_null:
                print(f"  - {s['node_id'][:20]}... page={s['page_number']}, doc={s['document_id']}")
                print(f"    content: {s['content_preview'][:80]}...")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_page_numbers())
