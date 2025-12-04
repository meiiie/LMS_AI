"""
Re-ingest COLREGs data with embeddings for Hybrid Search.

This script:
1. Reads existing Knowledge nodes from Neo4j
2. Generates Gemini embeddings (768 dims)
3. Stores embeddings in pgvector (Supabase)

Usage:
    python scripts/reingest_with_embeddings.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


async def create_embeddings_table():
    """Create knowledge_embeddings table in Supabase if not exists."""
    print("\n" + "="*60)
    print("STEP 1: Create pgvector table")
    print("="*60)
    
    try:
        import asyncpg
        
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            print("❌ DATABASE_URL not set in .env")
            return False
        
        print(f"Connecting to: {database_url[:50]}...")
        
        conn = await asyncpg.connect(database_url)
        
        # Enable pgvector extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("✅ pgvector extension enabled")
        
        # Create table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                node_id VARCHAR(255) UNIQUE NOT NULL,
                content TEXT,
                embedding vector(768) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
        print("✅ knowledge_embeddings table created")
        
        # Create index
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_embeddings_vector_idx 
            ON knowledge_embeddings 
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
        print("✅ IVFFlat index created")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Failed to create table: {e}")
        return False


async def get_knowledge_nodes():
    """Get all Knowledge nodes from Neo4j."""
    print("\n" + "="*60)
    print("STEP 2: Fetch Knowledge nodes from Neo4j")
    print("="*60)
    
    try:
        from neo4j import GraphDatabase
        
        neo4j_uri = os.getenv("NEO4J_URI")
        neo4j_user = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
        neo4j_pass = os.getenv("NEO4J_PASSWORD")
        
        print(f"Connecting to: {neo4j_uri}")
        
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        driver.verify_connectivity()
        print("✅ Neo4j connected")
        
        nodes = []
        with driver.session() as session:
            result = session.run("""
                MATCH (k:Knowledge)
                RETURN k.id as id, k.title as title, k.content as content
            """)
            
            for record in result:
                nodes.append({
                    "id": record["id"],
                    "title": record["title"],
                    "content": record["content"]
                })
        
        driver.close()
        print(f"✅ Found {len(nodes)} Knowledge nodes")
        return nodes
        
    except Exception as e:
        print(f"❌ Failed to fetch nodes: {e}")
        return []


async def generate_and_store_embeddings(nodes):
    """Generate embeddings and store in pgvector."""
    print("\n" + "="*60)
    print("STEP 3: Generate and store embeddings")
    print("="*60)
    
    if not nodes:
        print("⚠️ No nodes to process")
        return 0
    
    try:
        import asyncpg
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        
        # Initialize embeddings
        embeddings = GeminiOptimizedEmbeddings()
        print("✅ Gemini embeddings initialized")
        
        # Connect to database
        database_url = os.getenv("DATABASE_URL")
        conn = await asyncpg.connect(database_url)
        print("✅ Database connected")
        
        success_count = 0
        
        for i, node in enumerate(nodes):
            try:
                # Generate embedding
                text = f"{node['title']}\n{node['content']}"
                embedding = embeddings.embed_documents([text])[0]
                
                # Convert to pgvector format
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                
                # Store in database (UPSERT)
                await conn.execute("""
                    INSERT INTO knowledge_embeddings (node_id, content, embedding)
                    VALUES ($1, $2, $3::vector)
                    ON CONFLICT (node_id) 
                    DO UPDATE SET 
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                """, node['id'], text[:500], embedding_str)
                
                success_count += 1
                print(f"  [{i+1}/{len(nodes)}] ✅ {node['title'][:50]}...")
                
            except Exception as e:
                print(f"  [{i+1}/{len(nodes)}] ❌ {node['title'][:30]}... - {e}")
        
        await conn.close()
        print(f"\n✅ Stored {success_count}/{len(nodes)} embeddings")
        return success_count
        
    except Exception as e:
        print(f"❌ Failed to generate embeddings: {e}")
        import traceback
        traceback.print_exc()
        return 0


async def verify_embeddings():
    """Verify embeddings were stored correctly."""
    print("\n" + "="*60)
    print("STEP 4: Verify embeddings")
    print("="*60)
    
    try:
        import asyncpg
        
        database_url = os.getenv("DATABASE_URL")
        conn = await asyncpg.connect(database_url)
        
        # Count embeddings
        row = await conn.fetchrow("SELECT COUNT(*) as count FROM knowledge_embeddings")
        count = row['count']
        print(f"✅ Total embeddings in database: {count}")
        
        # Sample query
        if count > 0:
            row = await conn.fetchrow("""
                SELECT node_id, content, 
                       array_length(embedding::real[], 1) as dims
                FROM knowledge_embeddings 
                LIMIT 1
            """)
            print(f"  Sample node_id: {row['node_id']}")
            print(f"  Embedding dimensions: {row['dims']}")
        
        await conn.close()
        return count
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return 0


async def test_dense_search():
    """Test dense search with a sample query."""
    print("\n" + "="*60)
    print("STEP 5: Test Dense Search")
    print("="*60)
    
    try:
        from app.repositories.dense_search_repository import DenseSearchRepository
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        
        embeddings = GeminiOptimizedEmbeddings()
        repo = DenseSearchRepository()
        
        # Test query
        query = "Rule 15 crossing situation"
        print(f"Query: '{query}'")
        
        query_embedding = embeddings.embed_query(query)
        results = await repo.search(query_embedding, limit=3)
        
        print(f"Results: {len(results)}")
        for r in results:
            print(f"  - {r.node_id} (similarity: {r.similarity:.4f})")
        
        return len(results) > 0
        
    except Exception as e:
        print(f"❌ Dense search test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main function to re-ingest data with embeddings."""
    print("\n" + "="*60)
    print("RE-INGEST WITH EMBEDDINGS - Maritime AI Tutor v0.5.0")
    print("="*60)
    
    # Step 1: Create table
    if not await create_embeddings_table():
        print("\n❌ Failed at Step 1. Please check DATABASE_URL.")
        return 1
    
    # Step 2: Get nodes from Neo4j
    nodes = await get_knowledge_nodes()
    if not nodes:
        print("\n❌ Failed at Step 2. Please check Neo4j connection.")
        return 1
    
    # Step 3: Generate and store embeddings
    count = await generate_and_store_embeddings(nodes)
    if count == 0:
        print("\n❌ Failed at Step 3. Please check Gemini API key.")
        return 1
    
    # Step 4: Verify
    await verify_embeddings()
    
    # Step 5: Test dense search
    success = await test_dense_search()
    
    print("\n" + "="*60)
    if success:
        print("✅ RE-INGEST COMPLETED SUCCESSFULLY!")
        print("Dense Search is now operational.")
    else:
        print("⚠️ RE-INGEST COMPLETED but Dense Search test failed.")
        print("Please run test_hybrid_search.py to verify.")
    print("="*60)
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
