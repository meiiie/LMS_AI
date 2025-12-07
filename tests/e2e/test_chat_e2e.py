"""
End-to-End Chat Test with Semantic Memory v0.3
CHỈ THỊ KỸ THUẬT SỐ 06

Test real chat flow with semantic memory integration.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import uuid4


async def test_chat_with_semantic_memory():
    """Test chat service with semantic memory integration."""
    print("=" * 60)
    print("END-TO-END CHAT TEST WITH SEMANTIC MEMORY v0.3")
    print("CHI THI KY THUAT SO 06")
    print("=" * 60)
    
    from app.services.chat_service import ChatService
    from app.models.schemas import ChatRequest
    
    # Create chat service
    chat_service = ChatService()
    
    # Test user
    user_id = f"test_e2e_{uuid4().hex[:8]}"
    session_id = str(uuid4())
    
    print(f"\n[INFO] User ID: {user_id}")
    print(f"[INFO] Session ID: {session_id}")
    
    # Test conversations
    test_messages = [
        "Xin chào, tôi là Minh, tôi là sinh viên hàng hải năm 3",
        "Tôi muốn học về quy tắc 15 COLREGs - tình huống cắt hướng",
        "Khi hai tàu cắt hướng nhau, tàu nào phải nhường đường?",
        "Còn quy tắc 13 về tàu vượt thì sao?",
    ]
    
    print("\n" + "=" * 60)
    print("STARTING CHAT CONVERSATION")
    print("=" * 60)
    
    for i, message in enumerate(test_messages, 1):
        print(f"\n[{i}] USER: {message}")
        print("-" * 40)
        
        try:
            request = ChatRequest(
                user_id=user_id,
                message=message,
                role="student",
                context={"session_id": session_id}
            )
            
            response = await chat_service.process_message(request)
            
            # Truncate response for display
            response_text = response.message[:300] + "..." if len(response.message) > 300 else response.message
            print(f"[{i}] AI: {response_text}")
            
            # Show metadata
            if response.metadata:
                print(f"    [Metadata] {response.metadata}")
                
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
        
        # Small delay between messages
        await asyncio.sleep(1)
    
    # Test semantic memory retrieval
    print("\n" + "=" * 60)
    print("TESTING SEMANTIC MEMORY RETRIEVAL")
    print("=" * 60)
    
    try:
        from app.engine.semantic_memory import SemanticMemoryEngine
        
        engine = SemanticMemoryEngine()
        
        if engine.is_available():
            print("\n[INFO] Semantic Memory Engine is available")
            
            # First, store some test interactions
            print("\n[STORING] Saving test interactions to semantic memory...")
            await engine.store_interaction(
                user_id=user_id,
                message="Toi la Minh, sinh vien hang hai nam 3",
                response="Chao Minh! Rat vui duoc gap em.",
                session_id=session_id,
                extract_facts=False  # Skip fact extraction for speed
            )
            await engine.store_interaction(
                user_id=user_id,
                message="Quy tac 15 COLREGs ve tinh huong cat huong la gi?",
                response="Quy tac 15 quy dinh khi hai tau cat huong, tau nao thay tau kia o ben man phai phai nhuong duong.",
                session_id=session_id,
                extract_facts=False
            )
            print("  Stored 2 interactions")
            
            # Now test context retrieval
            query = "quy tac cat huong COLREGs"
            print(f"\n[QUERY] {query}")
            
            context = await engine.retrieve_context(user_id, query)
            
            print(f"\n[RESULTS]")
            print(f"  - Relevant memories: {len(context.relevant_memories)}")
            print(f"  - User facts: {len(context.user_facts)}")
            print(f"  - Total tokens: {context.total_tokens}")
            
            if context.relevant_memories:
                print("\n  Top memories:")
                for mem in context.relevant_memories[:3]:
                    content_preview = mem.content[:80] + "..." if len(mem.content) > 80 else mem.content
                    print(f"    - {content_preview} (sim: {mem.similarity:.2f})")
            
            if context.user_facts:
                print("\n  User facts:")
                for fact in context.user_facts[:3]:
                    print(f"    - {fact.content}")
            
            # Show prompt context
            prompt_context = context.to_prompt_context()
            if prompt_context:
                print(f"\n[PROMPT CONTEXT PREVIEW]")
                preview = prompt_context[:500] + "..." if len(prompt_context) > 500 else prompt_context
                print(preview)
        else:
            print("\n[WARNING] Semantic Memory Engine not available")
            
    except Exception as e:
        print(f"\n[ERROR] Semantic memory test failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("🎉 END-TO-END TEST COMPLETED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_chat_with_semantic_memory())
