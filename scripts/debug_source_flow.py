"""
Debug Script: Trace data flow for source highlighting.

Truy vết từng bước xem page_number, document_id đi đâu mất.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()


async def debug_data_flow():
    """Trace data flow step by step."""
    print("=" * 60)
    print("DEBUG: SOURCE HIGHLIGHTING DATA FLOW")
    print("=" * 60)
    
    # Step 1: Check raw database
    print("\n📊 STEP 1: Raw Database Query")
    print("-" * 40)
    
    import asyncpg
    db_url = os.getenv("DATABASE_URL", "")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgres://", "postgresql://")
    
    conn = await asyncpg.connect(db_url)
    try:
        # Get sample with all relevant fields
        rows = await conn.fetch("""
            SELECT 
                id::text as node_id,
                page_number,
                document_id,
                bounding_boxes,
                LEFT(content, 50) as content_preview
            FROM knowledge_embeddings
            LIMIT 3
        """)
        
        for row in rows:
            print(f"   node_id: {row['node_id'][:20]}...")
            print(f"   page_number: {row['page_number']} (type: {type(row['page_number']).__name__})")
            print(f"   document_id: {row['document_id']} (type: {type(row['document_id']).__name__})")
            print(f"   bounding_boxes: {row['bounding_boxes']}")
            print()
    finally:
        await conn.close()
    
    # Step 2: Test dense search
    print("\n📊 STEP 2: Dense Search Result")
    print("-" * 40)
    
    from app.repositories.dense_search_repository import get_dense_search_repository
    from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
    
    embedding_service = GeminiOptimizedEmbeddings()
    query = "Điều 15 chủ tàu"
    embedding = embedding_service.embed_query(query)
    
    dense_repo = get_dense_search_repository()
    dense_results = await dense_repo.search(embedding, limit=3)
    
    for i, r in enumerate(dense_results[:2]):
        print(f"   [{i+1}] node_id: {r.node_id[:20]}...")
        print(f"       page_number: {r.page_number} (type: {type(r.page_number).__name__})")
        print(f"       document_id: {r.document_id} (type: {type(r.document_id).__name__})")
        print(f"       bounding_boxes: {r.bounding_boxes}")
        print()
    
    # Step 3: Test hybrid search
    print("\n📊 STEP 3: Hybrid Search (RRF) Result")
    print("-" * 40)
    
    from app.services.hybrid_search_service import get_hybrid_search_service
    
    hybrid_service = get_hybrid_search_service()
    hybrid_results = await hybrid_service.search(query, limit=3)
    
    for i, r in enumerate(hybrid_results[:2]):
        print(f"   [{i+1}] node_id: {r.node_id[:20]}...")
        print(f"       page_number: {r.page_number} (type: {type(r.page_number).__name__})")
        print(f"       document_id: {r.document_id} (type: {type(r.document_id).__name__})")
        print(f"       bounding_boxes: {r.bounding_boxes}")
        print()
    
    # Step 4: Test RAG Citations
    print("\n📊 STEP 4: RAG Agent Citations")
    print("-" * 40)
    
    from app.engine.tools.rag_tool import RAGAgent
    
    rag = RAGAgent()
    response = await rag.query(query, limit=3)
    
    for i, c in enumerate(response.citations[:2]):
        print(f"   [{i+1}] node_id: {c.node_id[:20]}...")
        print(f"       page_number: {c.page_number} (type: {type(c.page_number).__name__})")
        print(f"       document_id: {c.document_id} (type: {type(c.document_id).__name__})")
        print(f"       bounding_boxes: {c.bounding_boxes}")
        print()
    
    # Step 5: Test tool_maritime_search
    print("\n📊 STEP 5: tool_maritime_search Sources")
    print("-" * 40)
    
    from app.engine.unified_agent import (
        tool_maritime_search,
        get_last_retrieved_sources,
        clear_retrieved_sources,
        _rag_agent
    )
    
    # Set RAG agent for tool
    import app.engine.unified_agent as ua
    ua._rag_agent = rag
    
    clear_retrieved_sources()
    await tool_maritime_search.ainvoke({"query": query})
    
    sources = get_last_retrieved_sources()
    
    for i, s in enumerate(sources[:2]):
        print(f"   [{i+1}] node_id: {s.get('node_id', 'N/A')[:20]}...")
        print(f"       page_number: {s.get('page_number')} (type: {type(s.get('page_number')).__name__})")
        print(f"       document_id: {s.get('document_id')} (type: {type(s.get('document_id')).__name__})")
        print(f"       bounding_boxes: {s.get('bounding_boxes')}")
        print()
    
    print("\n" + "=" * 60)
    print("DEBUG COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(debug_data_flow())
