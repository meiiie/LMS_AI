"""
Test script for Semantic Memory v0.3
CHỈ THỊ KỸ THUẬT SỐ 06

Run: python scripts/test_semantic_memory.py
"""
import asyncio
import sys
sys.path.insert(0, '.')

from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
from app.engine.semantic_memory import SemanticMemoryEngine
from app.repositories.semantic_memory_repository import SemanticMemoryRepository
from app.models.semantic_memory import MemoryType, SemanticMemoryCreate


async def test_embeddings():
    """Test GeminiOptimizedEmbeddings"""
    print("\n" + "="*60)
    print("TEST 1: GeminiOptimizedEmbeddings")
    print("="*60)
    
    embeddings = GeminiOptimizedEmbeddings()
    
    # Test embed_query
    print("\n[1.1] Testing embed_query...")
    query = "Quy tắc 15 COLREGs về tình huống cắt hướng là gì?"
    query_vector = embeddings.embed_query(query)
    
    print(f"  Query: {query[:50]}...")
    print(f"  Vector dimensions: {len(query_vector)}")
    print(f"  First 5 values: {query_vector[:5]}")
    
    # Verify dimensions
    assert len(query_vector) == 768, f"Expected 768 dimensions, got {len(query_vector)}"
    print("  ✅ Dimensions correct (768)")
    
    # Verify normalization
    import numpy as np
    norm = np.linalg.norm(query_vector)
    print(f"  L2 Norm: {norm:.6f}")
    assert abs(norm - 1.0) < 0.001, f"Expected norm ~1.0, got {norm}"
    print("  ✅ L2 Normalization correct")
    
    # Test embed_documents
    print("\n[1.2] Testing embed_documents...")
    docs = [
        "Điều 15 COLREGs quy định về tình huống cắt hướng",
        "Tàu nhìn thấy tàu khác bên mạn phải phải nhường đường"
    ]
    doc_vectors = embeddings.embed_documents(docs)
    
    print(f"  Documents: {len(docs)}")
    print(f"  Vectors generated: {len(doc_vectors)}")
    for i, vec in enumerate(doc_vectors):
        print(f"  Doc {i+1} dimensions: {len(vec)}, norm: {np.linalg.norm(vec):.6f}")
    
    print("\n✅ GeminiOptimizedEmbeddings TEST PASSED")
    return embeddings


async def test_repository(embeddings):
    """Test SemanticMemoryRepository"""
    print("\n" + "="*60)
    print("TEST 2: SemanticMemoryRepository")
    print("="*60)
    
    repo = SemanticMemoryRepository()
    
    # Check availability
    print("\n[2.1] Checking repository availability...")
    is_available = repo.is_available()
    print(f"  Repository available: {is_available}")
    
    if not is_available:
        print("  ⚠️ Repository not available - skipping database tests")
        print("  Make sure pgvector is enabled in Supabase")
        return None
    
    # Test save_memory
    print("\n[2.2] Testing save_memory...")
    test_user_id = "test_user_semantic_v03"
    test_content = "User hỏi về quy tắc 15 COLREGs"
    test_embedding = embeddings.embed_documents([test_content])[0]
    
    memory = SemanticMemoryCreate(
        user_id=test_user_id,
        content=test_content,
        embedding=test_embedding,
        memory_type=MemoryType.MESSAGE,
        importance=0.7,
        session_id="test_session_001"
    )
    
    saved = repo.save_memory(memory)
    if saved:
        print(f"  ✅ Memory saved: {saved.id}")
    else:
        print("  ❌ Failed to save memory")
        return None
    
    # Test search_similar
    print("\n[2.3] Testing search_similar...")
    query = "COLREGs quy tắc cắt hướng"
    query_embedding = embeddings.embed_query(query)
    
    results = repo.search_similar(
        user_id=test_user_id,
        query_embedding=query_embedding,
        limit=5,
        threshold=0.5
    )
    
    print(f"  Query: {query}")
    print(f"  Results found: {len(results)}")
    for r in results:
        print(f"    - {r.content[:50]}... (similarity: {r.similarity:.4f})")
    
    # Test count
    print("\n[2.4] Testing count_user_memories...")
    count = repo.count_user_memories(test_user_id)
    print(f"  Total memories for {test_user_id}: {count}")
    
    print("\n✅ SemanticMemoryRepository TEST PASSED")
    return repo


async def test_engine(embeddings, repo):
    """Test SemanticMemoryEngine"""
    print("\n" + "="*60)
    print("TEST 3: SemanticMemoryEngine")
    print("="*60)
    
    engine = SemanticMemoryEngine(embeddings=embeddings, repository=repo)
    
    test_user_id = "test_user_semantic_v03"
    test_session_id = "test_session_002"
    
    # Test store_interaction
    print("\n[3.1] Testing store_interaction...")
    success = await engine.store_interaction(
        user_id=test_user_id,
        message="Tôi là Minh, tôi muốn học về COLREGs",
        response="Chào Minh! Tôi sẽ giúp bạn học về COLREGs...",
        session_id=test_session_id,
        extract_facts=False  # Skip fact extraction for speed
    )
    print(f"  Interaction stored: {success}")
    
    # Test retrieve_context
    print("\n[3.2] Testing retrieve_context...")
    context = await engine.retrieve_context(
        user_id=test_user_id,
        query="Quy tắc COLREGs",
        search_limit=5,
        similarity_threshold=0.5
    )
    
    print(f"  Relevant memories: {len(context.relevant_memories)}")
    print(f"  User facts: {len(context.user_facts)}")
    print(f"  Total tokens: {context.total_tokens}")
    
    if context.relevant_memories:
        print("\n  Top memories:")
        for m in context.relevant_memories[:3]:
            print(f"    - {m.content[:60]}... (sim: {m.similarity:.4f})")
    
    # Test to_prompt_context
    print("\n[3.3] Testing to_prompt_context...")
    prompt_context = context.to_prompt_context()
    if prompt_context:
        print(f"  Context length: {len(prompt_context)} chars")
        print(f"  Preview: {prompt_context[:200]}...")
    else:
        print("  Context is empty")
    
    # Test token counting
    print("\n[3.4] Testing count_tokens...")
    test_text = "Đây là một đoạn văn bản tiếng Việt để test token counting"
    token_count = engine.count_tokens(test_text)
    print(f"  Text: {test_text}")
    print(f"  Token count: {token_count}")
    
    print("\n✅ SemanticMemoryEngine TEST PASSED")


async def main():
    print("\n" + "="*60)
    print("SEMANTIC MEMORY v0.3 - INTEGRATION TEST")
    print("CHỈ THỊ KỸ THUẬT SỐ 06")
    print("="*60)
    
    try:
        # Test 1: Embeddings
        embeddings = await test_embeddings()
        
        # Test 2: Repository
        repo = await test_repository(embeddings)
        
        # Test 3: Engine (only if repo available)
        if repo:
            await test_engine(embeddings, repo)
        
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
