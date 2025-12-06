"""Test tool_save_user_info is called when user introduces themselves."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    from app.services.chat_service import ChatService
    from app.models.schemas import ChatRequest
    
    cs = ChatService()
    
    print("=== Test tool_save_user_info ===")
    print(f"SemanticMemory available: {cs._semantic_memory is not None and cs._semantic_memory.is_available()}")
    
    # Test introduction message
    request = ChatRequest(
        user_id="test_tool_user",
        message="Xin chào, tôi là Minh, tôi là sinh viên hàng hải năm 3",
        role="student"
    )
    
    print("\n[TEST] Sending introduction message...")
    response = await cs.process_message(request)
    
    print(f"\n[RESPONSE]")
    print(f"Message: {response.message[:200]}...")
    print(f"Metadata: {response.metadata}")
    
    # Check if tool_save_user_info was called
    tools_used = response.metadata.get("tools_used", []) if response.metadata else []
    print(f"\nTools used: {tools_used}")
    
    save_user_info_called = any("save_user_info" in str(t) for t in tools_used)
    print(f"tool_save_user_info called: {save_user_info_called}")
    
    # Check semantic memory for user facts
    if cs._semantic_memory and cs._semantic_memory.is_available():
        print("\n[CHECKING] Semantic Memory for user facts...")
        await asyncio.sleep(1)  # Wait for async storage
        
        context = await cs._semantic_memory.retrieve_context(
            user_id="test_tool_user",
            query="user name",
            include_user_facts=True
        )
        
        print(f"User facts found: {len(context.user_facts)}")
        for fact in context.user_facts:
            print(f"  - {fact.content}")

if __name__ == "__main__":
    asyncio.run(main())
