"""
Test Semantic Memory directly on Production Database
Kết nối trực tiếp đến Neon database để kiểm tra
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load production env
from dotenv import load_dotenv
load_dotenv('.env.render')  # Use production env

async def test_production_database():
    """Test direct connection to production database"""
    print("\n" + "="*60)
    print("TEST: Production Database Connection")
    print("="*60)
    
    from app.core.config import settings
    print(f"Database URL: {settings.database_url[:50]}...")
    
    try:
        from app.repositories.semantic_memory_repository import SemanticMemoryRepository
        
        repo = SemanticMemoryRepository()
        
        if not repo.is_available():
            print("❌ Repository not available")
            return False
        
        print("✅ Repository connected to production database")
        
        # Check for any user facts
        print("\n--- Checking existing user facts ---")
        
        # Get facts for test user
        test_users = ["memory_test_detailed", "test_memory_490bd867", "test_direct_001"]
        
        for user_id in test_users:
            facts = repo.get_user_facts(user_id, limit=10, deduplicate=True)
            print(f"\n{user_id}: {len(facts)} facts")
            for fact in facts:
                print(f"  - {fact.content}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_store_fact_production():
    """Test storing a fact directly to production"""
    print("\n" + "="*60)
    print("TEST: Store Fact to Production")
    print("="*60)
    
    try:
        from app.engine.semantic_memory import SemanticMemoryEngine
        
        engine = SemanticMemoryEngine()
        
        if not engine.is_available():
            print("❌ Engine not available")
            return False
        
        print("✅ Engine initialized")
        
        # Store a test fact
        user_id = "production_test_001"
        success = await engine.store_user_fact_upsert(
            user_id=user_id,
            fact_content="Test user name is Production Tester",
            fact_type="name",
            confidence=0.95
        )
        
        print(f"Store result: {'✅ Success' if success else '❌ Failed'}")
        
        # Verify
        context = await engine.retrieve_context(
            user_id=user_id,
            query="test",
            include_user_facts=True
        )
        
        print(f"Retrieved facts: {len(context.user_facts)}")
        for fact in context.user_facts:
            print(f"  - {fact.content}")
        
        return success
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("="*60)
    print("PRODUCTION MEMORY DIRECT TEST")
    print("="*60)
    
    await test_production_database()
    await test_store_fact_production()

if __name__ == "__main__":
    asyncio.run(main())
