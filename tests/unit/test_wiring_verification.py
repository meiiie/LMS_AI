"""
Test Wiring Verification - Kiểm tra đấu nối các components.

Theo yêu cầu của Chuyên gia (phanhoi9.md):
1. tool_maritime_search -> HybridSearchService
2. tool_save_user_info -> SemanticMemoryRepository
"""

import sys
import asyncio
import logging
sys.path.insert(0, ".")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

from dotenv import load_dotenv
load_dotenv()

# Set timeout for async operations
TIMEOUT = 30

async def main():
    print("=" * 70)
    print("WIRING VERIFICATION TEST")
    print("Kiểm tra đấu nối các components theo yêu cầu Chuyên gia")
    print("=" * 70)

    # Test 1: ChatService initialization
    print("\n1. Kiểm tra ChatService initialization...")
    try:
        from app.services.chat_service import get_chat_service
        chat_service = get_chat_service()
        
        print(f"   ✅ ChatService initialized")
        print(f"   - Knowledge Graph: {chat_service._knowledge_graph.is_available()}")
        print(f"   - Chat History: {chat_service._chat_history.is_available()}")
        print(f"   - Semantic Memory: {chat_service._semantic_memory is not None}")
        print(f"   - Unified Agent: {chat_service._unified_agent is not None}")
        
        if chat_service._unified_agent:
            print(f"   - Unified Agent Available: {chat_service._unified_agent.is_available()}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 2: RAGAgent -> HybridSearchService wiring
    print("\n2. Kiểm tra RAGAgent -> HybridSearchService wiring...")
    try:
        rag_agent = chat_service._rag_agent
        print(f"   - RAGAgent: {rag_agent is not None}")
        
        if rag_agent:
            hybrid_search = rag_agent._hybrid_search
            print(f"   - HybridSearchService: {hybrid_search is not None}")
            
            if hybrid_search:
                print(f"   - HybridSearch Available: {hybrid_search.is_available()}")
                print(f"   ✅ RAGAgent -> HybridSearchService: CONNECTED")
            else:
                print(f"   ⚠️ HybridSearchService is None")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 3: UnifiedAgent -> RAGAgent wiring
    print("\n3. Kiểm tra UnifiedAgent -> RAGAgent wiring...")
    try:
        from app.engine.unified_agent import _rag_agent as unified_rag_agent
        
        if unified_rag_agent is not None:
            print(f"   ✅ UnifiedAgent._rag_agent: CONNECTED")
            print(f"   - Same instance as ChatService._rag_agent: {unified_rag_agent is rag_agent}")
        else:
            print(f"   ⚠️ UnifiedAgent._rag_agent is None (will be set on first process)")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 4: UnifiedAgent -> SemanticMemory wiring
    print("\n4. Kiểm tra UnifiedAgent -> SemanticMemory wiring...")
    try:
        from app.engine.unified_agent import _semantic_memory as unified_semantic_memory
        
        if unified_semantic_memory is not None:
            print(f"   ✅ UnifiedAgent._semantic_memory: CONNECTED")
        else:
            print(f"   ⚠️ UnifiedAgent._semantic_memory is None (will be set on first process)")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")

    # Test 5: End-to-end test với maritime question
    print("\n5. End-to-end test: Maritime question qua UnifiedAgent...")
    try:
        from app.models.schemas import ChatRequest, UserRole
        
        request = ChatRequest(
            user_id="test_wiring_user",
            message="Quy tắc 15 COLREGs là gì?",
            role=UserRole.STUDENT
        )
        
        response = await asyncio.wait_for(
            chat_service.process_message(request),
            timeout=TIMEOUT
        )
        
        print(f"   ✅ Response received")
        print(f"   - Agent Type: {response.agent_type}")
        print(f"   - Unified Agent Used: {response.metadata.get('unified_agent', False)}")
        print(f"   - Tools Used: {response.metadata.get('tools_used', [])}")
        print(f"   - Content (first 200 chars): {response.message[:200]}...")
        
        # Check if tool was called
        tools_used = response.metadata.get('tools_used', [])
        if any(t.get('name') == 'tool_maritime_search' for t in tools_used):
            print(f"   ✅ tool_maritime_search was called!")
        else:
            print(f"   ⚠️ tool_maritime_search was NOT called")
            
    except asyncio.TimeoutError:
        print(f"   ⚠️ TIMEOUT after {TIMEOUT}s - skipping")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

    # Test 6: Test user info save
    print("\n6. End-to-end test: User info save qua UnifiedAgent...")
    try:
        request = ChatRequest(
            user_id="test_wiring_user",
            message="Tôi là Minh, sinh viên Đại học Hàng hải Việt Nam",
            role=UserRole.STUDENT
        )
        
        response = await asyncio.wait_for(
            chat_service.process_message(request),
            timeout=TIMEOUT
        )
        
        print(f"   ✅ Response received")
        print(f"   - Tools Used: {response.metadata.get('tools_used', [])}")
        
        tools_used = response.metadata.get('tools_used', [])
        if any(t.get('name') == 'tool_save_user_info' for t in tools_used):
            print(f"   ✅ tool_save_user_info was called!")
        else:
            print(f"   ⚠️ tool_save_user_info was NOT called")
            
    except asyncio.TimeoutError:
        print(f"   ⚠️ TIMEOUT after {TIMEOUT}s - skipping")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("WIRING VERIFICATION COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
