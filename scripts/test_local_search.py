"""Test local search directly"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

async def test_search():
    # Generate embedding for query
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    
    query = "Điều 15 về tình huống cắt hướng"
    print(f"Query: {query}")
    
    # Get embedding
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=query,
        task_type="retrieval_query"
    )
    query_embedding = result['embedding']
    print(f"Embedding dim: {len(query_embedding)}")
    
    # Connect to DB
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    
    # Check if embedding column has data
    row = await conn.fetchrow('''
        SELECT id, embedding IS NOT NULL as has_emb, array_length(embedding, 1) as emb_len
        FROM knowledge_embeddings 
        LIMIT 1
    ''')
    print(f"\nEmbedding check: has_emb={row['has_emb']}, dim={row['emb_len']}")
    
    # Simple text search first
    print("\n--- Text Search (LIKE) ---")
    rows = await conn.fetch('''
        SELECT content, content_type, page_number 
        FROM knowledge_embeddings 
        WHERE content ILIKE '%Điều 15%' OR content ILIKE '%cắt hướng%'
        LIMIT 3
    ''')
    for r in rows:
        print(f"Page {r['page_number']} ({r['content_type']}): {r['content'][:100]}...")
    
    if not rows:
        print("No results from text search")
        # Try broader search
        rows = await conn.fetch('''
            SELECT content, content_type, page_number 
            FROM knowledge_embeddings 
            WHERE content ILIKE '%Điều%'
            LIMIT 3
        ''')
        print("\nBroader search (Điều):")
        for r in rows:
            print(f"Page {r['page_number']} ({r['content_type']}): {r['content'][:100]}...")
    
    await conn.close()

asyncio.run(test_search())
