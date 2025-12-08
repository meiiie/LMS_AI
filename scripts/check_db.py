"""Quick DB check script"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def check():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    
    # Count total
    row = await conn.fetchrow('SELECT COUNT(*) as cnt FROM knowledge_embeddings')
    print(f"Total chunks: {row['cnt']}")
    
    # Count by document
    rows = await conn.fetch('SELECT document_id, COUNT(*) as cnt FROM knowledge_embeddings GROUP BY document_id')
    print("\nBy document:")
    for r in rows:
        print(f"  {r['document_id']}: {r['cnt']} chunks")
    
    # Count by content_type
    rows = await conn.fetch('SELECT content_type, COUNT(*) as cnt FROM knowledge_embeddings GROUP BY content_type ORDER BY cnt DESC')
    print("\nBy content_type:")
    for r in rows:
        print(f"  {r['content_type']}: {r['cnt']}")
    
    # Check embedding column type
    row = await conn.fetchrow("""
        SELECT column_name, data_type, udt_name 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge_embeddings' AND column_name = 'embedding'
    """)
    if row:
        print(f"\nEmbedding column: type={row['data_type']}, udt={row['udt_name']}")
    
    # Sample content
    row = await conn.fetchrow('SELECT content, content_type, page_number, array_length(embedding, 1) as emb_len FROM knowledge_embeddings LIMIT 1')
    if row:
        print(f"\nSample content (page {row['page_number']}, type={row['content_type']}, emb_len={row['emb_len']}):")
        print(f"  {row['content'][:200]}...")
    
    await conn.close()

asyncio.run(check())
