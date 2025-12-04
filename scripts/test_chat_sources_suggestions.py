"""
Test Chat với Sources và Suggested Questions
Kiểm tra xem chatbot có trích xuất nguồn tài liệu và gợi ý câu hỏi chính xác không.
"""
import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import uuid4


async def test_rag_with_sources():
    """Test RAG Agent trả về sources chính xác."""
    print("=" * 70)
    print("TEST: RAG AGENT WITH SOURCES & CITATIONS")
    print("=" * 70)
    
    from app.engine.tools.rag_tool import RAGAgent
    from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
    
    # Initialize
    knowledge_graph = Neo4jKnowledgeRepository()
    rag_agent = RAGAgent(knowledge_graph=knowledge_graph)
    
    # Test queries
    test_queries = [
        "Quy tắc 15 COLREGs về tình huống cắt hướng",
        "Rule 19 restricted visibility",
        "Tàu vượt theo quy tắc 13",
        "Safe speed Rule 6",
    ]
    
    for query in test_queries:
        print(f"\n{'='*70}")
        print(f"QUERY: {query}")
        print("-" * 70)
        
        try:
            response = await rag_agent.query(
                query,
                conversation_history="",
                user_role="student"
            )
            
            # Show response
            print(f"\n📝 RESPONSE (first 300 chars):")
            print(response.content[:300] + "..." if len(response.content) > 300 else response.content)
            
            # Show citations
            print(f"\n📚 CITATIONS ({len(response.citations)} sources):")
            if response.citations:
                for i, citation in enumerate(response.citations, 1):
                    print(f"  {i}. {citation.title}")
                    print(f"     Source: {citation.source}")
                    print(f"     Node ID: {citation.node_id}")
                    print(f"     Relevance: {citation.relevance_score:.4f}")
            else:
                print("  ⚠️ No citations found!")
            
            # Show metadata
            print(f"\n📊 METADATA:")
            print(f"  - Is Fallback: {response.is_fallback}")
            print(f"  - Disclaimer: {response.disclaimer or 'None'}")
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)


async def test_chat_api_response():
    """Test full chat API response format với sources và suggested_questions."""
    print("\n" + "=" * 70)
    print("TEST: FULL CHAT API RESPONSE FORMAT")
    print("=" * 70)
    
    from app.services.chat_service import ChatService
    from app.models.schemas import ChatRequest, UserRole
    from app.api.v1.chat import _generate_suggested_questions
    
    chat_service = ChatService()
    
    # Test cases
    test_cases = [
        {
            "message": "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng",
            "role": "student",
            "expected_topic": "colregs"
        },
        {
            "message": "Rule 19 về tầm nhìn hạn chế quy định gì?",
            "role": "student", 
            "expected_topic": "colregs"
        },
        {
            "message": "SOLAS yêu cầu gì về thiết bị cứu sinh?",
            "role": "teacher",
            "expected_topic": "solas"
        },
    ]
    
    user_id = f"test_sources_{uuid4().hex[:8]}"
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"TEST CASE {i}: {test['message'][:50]}...")
        print(f"Role: {test['role']}")
        print("-" * 70)
        
        try:
            request = ChatRequest(
                user_id=user_id,
                message=test["message"],
                role=UserRole(test["role"])
            )
            
            response = await chat_service.process_message(request)
            
            # Show response
            print(f"\n📝 AI RESPONSE (first 400 chars):")
            print(response.message[:400] + "..." if len(response.message) > 400 else response.message)
            
            # Show sources
            print(f"\n📚 SOURCES ({len(response.sources) if response.sources else 0}):")
            if response.sources:
                for j, src in enumerate(response.sources, 1):
                    print(f"  {j}. {src.title}")
                    print(f"     Type: {src.source_type}")
                    if src.content_snippet:
                        snippet = src.content_snippet[:100] + "..." if len(src.content_snippet) > 100 else src.content_snippet
                        print(f"     Snippet: {snippet}")
            else:
                print("  ⚠️ No sources returned!")
            
            # Generate and show suggested questions
            suggested = _generate_suggested_questions(test["message"], response.message)
            print(f"\n💡 SUGGESTED QUESTIONS:")
            for j, q in enumerate(suggested, 1):
                print(f"  {j}. {q}")
            
            # Show metadata
            print(f"\n📊 METADATA:")
            if response.metadata:
                for key, value in response.metadata.items():
                    print(f"  - {key}: {value}")
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        await asyncio.sleep(1)  # Rate limit
    
    print("\n" + "=" * 70)


async def test_hybrid_search_sources():
    """Test Hybrid Search trả về đủ thông tin cho sources."""
    print("\n" + "=" * 70)
    print("TEST: HYBRID SEARCH SOURCE INFORMATION")
    print("=" * 70)
    
    from app.services.hybrid_search_service import HybridSearchService
    
    service = HybridSearchService()
    
    queries = [
        "Rule 15 crossing situation",
        "restricted visibility navigation",
        "overtaking vessel Rule 13",
    ]
    
    for query in queries:
        print(f"\n{'='*70}")
        print(f"QUERY: {query}")
        print("-" * 70)
        
        try:
            results = await service.search(query, limit=3)
            
            print(f"\n📊 RESULTS ({len(results)}):")
            for i, r in enumerate(results, 1):
                print(f"\n  {i}. {r.title}")
                print(f"     Node ID: {r.node_id}")
                print(f"     Source: {r.source}")
                print(f"     Category: {r.category}")
                print(f"     RRF Score: {r.rrf_score:.4f}")
                print(f"     Dense: {r.dense_score}, Sparse: {r.sparse_score}")
                print(f"     Method: {r.search_method}")
                if r.content:
                    content_preview = r.content[:150] + "..." if len(r.content) > 150 else r.content
                    print(f"     Content: {content_preview}")
                else:
                    print(f"     Content: ⚠️ EMPTY!")
                    
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("🔍 TESTING SOURCES & SUGGESTED QUESTIONS")
    print("=" * 70)
    
    # Test 1: Hybrid Search sources
    await test_hybrid_search_sources()
    
    # Test 2: RAG Agent with citations
    await test_rag_with_sources()
    
    # Test 3: Full Chat API response
    await test_chat_api_response()
    
    print("\n" + "=" * 70)
    print("🎉 ALL TESTS COMPLETED!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
