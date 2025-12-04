"""
KIỂM TRA TOÀN DIỆN HỆ THỐNG
Verify tất cả components đã chỉnh sửa hoạt động đúng.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

results = {}

def log_result(component: str, status: bool, detail: str = ""):
    """Log test result."""
    icon = "✅" if status else "❌"
    results[component] = status
    print(f"{icon} {component}: {detail}")


async def test_1_env_files():
    """Test 1: Kiểm tra .env và .env.render có đúng URL không."""
    print("\n" + "="*60)
    print("TEST 1: Environment Files")
    print("="*60)
    
    # Check .env
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Check for correct Session Pooler URL
        if "aws-1-ap-southeast-1.pooler.supabase.com:5432" in content:
            log_result(".env DATABASE_URL", True, "Session Pooler 5432 ✓")
        else:
            log_result(".env DATABASE_URL", False, "Wrong URL format")
    else:
        log_result(".env", False, "File not found")
    
    # Check .env.render
    render_path = ".env.render"
    if os.path.exists(render_path):
        with open(render_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        if "aws-1-ap-southeast-1.pooler.supabase.com:5432" in content:
            log_result(".env.render DATABASE_URL", True, "Session Pooler 5432 ✓")
        else:
            log_result(".env.render DATABASE_URL", False, "Wrong URL format")
    else:
        log_result(".env.render", False, "File not found")


async def test_2_supabase_connection():
    """Test 2: Kiểm tra kết nối Supabase PostgreSQL."""
    print("\n" + "="*60)
    print("TEST 2: Supabase PostgreSQL Connection")
    print("="*60)
    
    try:
        from sqlalchemy import create_engine, text
        from app.core.config import settings
        
        engine = create_engine(settings.postgres_url_sync, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            log_result("PostgreSQL Connection", True, f"v{version[:20]}...")
            
            # Check tables
            result = conn.execute(text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public'
            """))
            tables = [row[0] for row in result.fetchall()]
            log_result("Tables Found", True, f"{len(tables)} tables: {tables[:5]}...")
            
    except Exception as e:
        log_result("PostgreSQL Connection", False, str(e)[:50])


async def test_3_neo4j_connection():
    """Test 3: Kiểm tra kết nối Neo4j."""
    print("\n" + "="*60)
    print("TEST 3: Neo4j Connection")
    print("="*60)
    
    try:
        from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
        
        repo = Neo4jKnowledgeRepository()
        if repo.is_available():
            # Count nodes
            count = await repo.count_knowledge_nodes()
            log_result("Neo4j Connection", True, f"{count} Knowledge nodes")
        else:
            log_result("Neo4j Connection", False, "Not available")
            
    except Exception as e:
        log_result("Neo4j Connection", False, str(e)[:50])


async def test_4_dense_search():
    """Test 4: Kiểm tra Dense Search (pgvector)."""
    print("\n" + "="*60)
    print("TEST 4: Dense Search (pgvector)")
    print("="*60)
    
    try:
        import asyncpg
        from app.core.config import settings
        
        pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
        
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
            log_result("knowledge_embeddings Table", True, f"{count} embeddings")
            
            if count > 0:
                # Test vector search
                row = await conn.fetchrow(
                    "SELECT node_id, content FROM knowledge_embeddings LIMIT 1"
                )
                log_result("Sample Embedding", True, f"{row['node_id'][:30]}...")
        
        await pool.close()
        
    except Exception as e:
        log_result("Dense Search", False, str(e)[:50])


async def test_5_sparse_search():
    """Test 5: Kiểm tra Sparse Search (Neo4j Full-text)."""
    print("\n" + "="*60)
    print("TEST 5: Sparse Search (Neo4j Full-text)")
    print("="*60)
    
    try:
        from app.repositories.sparse_search_repository import SparseSearchRepository
        
        repo = SparseSearchRepository()
        if repo.is_available():
            results = await repo.search("Rule 15", limit=3)
            if results:
                log_result("Sparse Search", True, f"{len(results)} results for 'Rule 15'")
                log_result("Top Result", True, f"{results[0].title}")
            else:
                log_result("Sparse Search", False, "No results")
        else:
            log_result("Sparse Search", False, "Not available")
            
    except Exception as e:
        log_result("Sparse Search", False, str(e)[:50])


async def test_6_hybrid_search():
    """Test 6: Kiểm tra Hybrid Search Service."""
    print("\n" + "="*60)
    print("TEST 6: Hybrid Search Service")
    print("="*60)
    
    try:
        from app.services.hybrid_search_service import HybridSearchService
        
        service = HybridSearchService()
        results = await service.search("restricted visibility", limit=3)
        
        if results:
            log_result("Hybrid Search", True, f"{len(results)} results")
            
            # Check if we have both Dense and Sparse scores
            has_dense = any(r.dense_score is not None for r in results)
            has_sparse = any(r.sparse_score is not None for r in results)
            
            if has_dense and has_sparse:
                log_result("True Hybrid Mode", True, "Dense + Sparse working")
            elif has_sparse:
                log_result("True Hybrid Mode", False, "Sparse only (Dense failed)")
            else:
                log_result("True Hybrid Mode", False, "Unknown mode")
                
            # Show top result
            top = results[0]
            log_result("Top Result", True, 
                f"RRF={top.rrf_score:.4f}, D={top.dense_score}, S={top.sparse_score}")
        else:
            log_result("Hybrid Search", False, "No results")
            
    except Exception as e:
        log_result("Hybrid Search", False, str(e)[:50])


async def test_7_chat_history():
    """Test 7: Kiểm tra Chat History Repository."""
    print("\n" + "="*60)
    print("TEST 7: Chat History Repository")
    print("="*60)
    
    try:
        from app.repositories.chat_history_repository import ChatHistoryRepository
        
        repo = ChatHistoryRepository()
        if repo.is_available():
            log_result("Chat History Repo", True, "Connected")
        else:
            log_result("Chat History Repo", False, "Not available")
            
    except Exception as e:
        log_result("Chat History Repo", False, str(e)[:50])


async def test_8_semantic_memory():
    """Test 8: Kiểm tra Semantic Memory Repository."""
    print("\n" + "="*60)
    print("TEST 8: Semantic Memory Repository")
    print("="*60)
    
    try:
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository
        
        repo = SemanticMemoryRepository()
        if repo.is_available():
            log_result("Semantic Memory Repo", True, "Connected")
        else:
            log_result("Semantic Memory Repo", False, "Not available")
            
    except Exception as e:
        log_result("Semantic Memory Repo", False, str(e)[:50])


async def test_9_gemini_embeddings():
    """Test 9: Kiểm tra Gemini Embeddings."""
    print("\n" + "="*60)
    print("TEST 9: Gemini Embeddings")
    print("="*60)
    
    try:
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        import numpy as np
        
        embeddings = GeminiOptimizedEmbeddings()
        vector = embeddings.embed_query("Test query")
        
        log_result("Embedding Generation", True, f"{len(vector)} dimensions")
        
        # Check L2 norm
        norm = np.linalg.norm(vector)
        if abs(norm - 1.0) < 1e-4:
            log_result("L2 Normalization", True, f"norm = {norm:.6f}")
        else:
            log_result("L2 Normalization", False, f"norm = {norm:.6f}")
            
    except Exception as e:
        log_result("Gemini Embeddings", False, str(e)[:50])


async def test_10_rrf_reranker():
    """Test 10: Kiểm tra RRF Reranker."""
    print("\n" + "="*60)
    print("TEST 10: RRF Reranker")
    print("="*60)
    
    try:
        from app.engine.rrf_reranker import RRFReranker
        from app.repositories.dense_search_repository import DenseSearchResult
        from app.repositories.sparse_search_repository import SparseSearchResult
        
        reranker = RRFReranker(k=60)
        
        dense = [DenseSearchResult(node_id="n1", similarity=0.9)]
        sparse = [SparseSearchResult(node_id="n1", title="T", content="C", 
                                     source="S", category="C", score=10.0)]
        
        results = reranker.merge(dense, sparse, limit=5)
        
        if results and results[0].appears_in_both():
            log_result("RRF Reranker", True, "Merge & boost working")
        else:
            log_result("RRF Reranker", False, "Merge failed")
            
    except Exception as e:
        log_result("RRF Reranker", False, str(e)[:50])


async def main():
    """Run all verification tests."""
    print("\n" + "="*60)
    print("🔍 KIỂM TRA TOÀN DIỆN HỆ THỐNG")
    print("="*60)
    
    await test_1_env_files()
    await test_2_supabase_connection()
    await test_3_neo4j_connection()
    await test_4_dense_search()
    await test_5_sparse_search()
    await test_6_hybrid_search()
    await test_7_chat_history()
    await test_8_semantic_memory()
    await test_9_gemini_embeddings()
    await test_10_rrf_reranker()
    
    # Summary
    print("\n" + "="*60)
    print("📊 TÓM TẮT KẾT QUẢ")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\nTổng: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 TẤT CẢ COMPONENTS HOẠT ĐỘNG TỐT!")
    else:
        print("\n⚠️ Một số components cần kiểm tra:")
        for name, status in results.items():
            if not status:
                print(f"  ❌ {name}")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
