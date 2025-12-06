"""Debug script to check UnifiedAgent behavior."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    from app.services.chat_service import ChatService
    from app.models.schemas import ChatRequest
    
    cs = ChatService()
    
    print("=== UnifiedAgent Debug ===")
    print(f"UnifiedAgent available: {cs._unified_agent is not None}")
    print(f"RAG Agent available: {cs._rag_agent is not None if hasattr(cs, '_rag_agent') else 'N/A'}")
    print(f"Knowledge Graph available: {cs._knowledge_graph.is_available()}")
    
    # Test a knowledge question
    request = ChatRequest(
        user_id="debug-user",
        message="Quy tắc 15 COLREGs là gì?",
        role="student"
    )
    
    print("\n[TEST] Sending knowledge question...")
    response = await cs.process_message(request)
    
    print(f"\n[RESPONSE]")
    print(f"Message: {response.message[:200]}...")
    print(f"Sources: {response.sources}")
    print(f"Metadata: {response.metadata}")
    
    # Check if unified_agent was used
    if response.metadata:
        print(f"\nUnified Agent used: {response.metadata.get('unified_agent', False)}")
        print(f"Tools used: {response.metadata.get('tools_used', [])}")

if __name__ == "__main__":
    asyncio.run(main())
