"""
Test Semantic Memory Engine directly (local)
Kiểm tra xem fact extraction có hoạt động không
"""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

async def test_fact_extraction():
    """Test fact extraction directly"""
    print("\n" + "="*60)
    print("TEST: Direct Fact Extraction")
    print("="*60)
    
    try:
        from app.engine.semantic_memory import SemanticMemoryEngine
        
        engine = SemanticMemoryEngine()
        
        if not engine.is_available():
            print("❌ Semantic Memory Engine not available")
            return False
        
        print("✅ Semantic Memory Engine initialized")
        
        # Test message with personal info
        test_message = "Xin chào! Tôi tên là Nguyễn Văn An, sinh viên năm 4 ngành Điều khiển tàu biển"
        user_id = "test_direct_001"
        
        print(f"\nTest message: {test_message}")
        print(f"User ID: {user_id}")
        
        # Test extract_user_facts
        print("\n--- Testing extract_user_facts ---")
        extraction = await engine.extract_user_facts(user_id, test_message)
        
        print(f"Has facts: {extraction.has_facts}")
        print(f"Facts count: {len(extraction.facts)}")
        
        if extraction.facts:
            print("\nExtracted facts:")
            for fact in extraction.facts:
                print(f"  - [{fact.fact_type.value}] {fact.value} (confidence: {fact.confidence})")
        else:
            print("⚠️ No facts extracted")
        
        # Test store_user_fact_upsert
        print("\n--- Testing store_user_fact_upsert ---")
        success = await engine.store_user_fact_upsert(
            user_id=user_id,
            fact_content="User's name is Nguyễn Văn An",
            fact_type="name",
            confidence=0.95
        )
        print(f"Store result: {'✅ Success' if success else '❌ Failed'}")
        
        # Test _extract_and_store_facts
        print("\n--- Testing _extract_and_store_facts ---")
        stored_facts = await engine._extract_and_store_facts(
            user_id=user_id,
            message=test_message,
            session_id="test_session_001"
        )
        print(f"Stored facts count: {len(stored_facts)}")
        
        if stored_facts:
            print("Stored facts:")
            for fact in stored_facts:
                print(f"  - [{fact.fact_type.value}] {fact.value}")
        
        # Verify by retrieving context
        print("\n--- Verifying by retrieving context ---")
        context = await engine.retrieve_context(
            user_id=user_id,
            query="thông tin người dùng",
            include_user_facts=True
        )
        
        print(f"User facts in context: {len(context.user_facts)}")
        if context.user_facts:
            for fact in context.user_facts:
                print(f"  - {fact.content}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_llm_availability():
    """Test if LLM is available for fact extraction"""
    print("\n" + "="*60)
    print("TEST: LLM Availability")
    print("="*60)
    
    try:
        from app.core.config import settings
        print(f"Google API Key: {'SET' if settings.google_api_key else 'NOT SET'}")
        print(f"Google Model: {settings.google_model}")
        
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",
            google_api_key=settings.google_api_key,
            temperature=0.1
        )
        
        # Test simple prompt
        response = await llm.ainvoke("Say 'Hello' in Vietnamese")
        print(f"LLM Response: {response.content}")
        print("✅ LLM is available")
        return True
        
    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return False

async def main():
    print("="*60)
    print("SEMANTIC MEMORY DIRECT TEST")
    print("="*60)
    
    await test_llm_availability()
    await test_fact_extraction()

if __name__ == "__main__":
    asyncio.run(main())
