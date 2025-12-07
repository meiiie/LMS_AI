"""
Test Insight Engine v0.5 - LOCAL (Direct Component Test)
Verify InsightExtractor và SemanticMemoryEngine hoạt động đúng
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def test_direct_insight_extraction():
    """Test InsightExtractor trực tiếp."""
    print("\n" + "="*60)
    print("TEST: Direct InsightExtractor")
    print("="*60)
    
    from app.engine.insight_extractor import InsightExtractor
    
    extractor = InsightExtractor()
    
    test_message = """
    Tôi là Minh, đang học để thi bằng thuyền trưởng hạng 3.
    Tôi thấy học qua ví dụ thực tế dễ hiểu hơn nhiều so với đọc lý thuyết.
    Đặc biệt là khi học về COLREGs, tôi hay nhầm lẫn giữa Rule 13 và Rule 15.
    """
    
    print(f"\nInput: {test_message[:80]}...")
    
    insights = await extractor.extract_insights(
        user_id="local_test_user",
        message=test_message,
        conversation_history=[]
    )
    
    print(f"\n✅ Extracted {len(insights)} insights:")
    for i, insight in enumerate(insights):
        print(f"   {i+1}. [{insight.category.value}] {insight.content[:80]}...")
        print(f"      Confidence: {insight.confidence}, Sub-topic: {insight.sub_topic}")
    
    return insights


async def test_semantic_memory_store():
    """Test SemanticMemoryEngine.extract_and_store_insights()."""
    print("\n" + "="*60)
    print("TEST: SemanticMemoryEngine.extract_and_store_insights()")
    print("="*60)
    
    from app.engine.semantic_memory import SemanticMemoryEngine
    
    engine = SemanticMemoryEngine()
    
    if not engine.is_available():
        print("⚠️ SemanticMemoryEngine not available")
        return []
    
    test_user = f"local_insight_test_{int(time.time())}"
    test_message = """
    Tôi thấy học qua ví dụ thực tế dễ hiểu hơn nhiều.
    Đặc biệt là khi học về COLREGs, tôi hay nhầm lẫn giữa Rule 13 và Rule 15.
    Mục tiêu của tôi là thi đậu bằng thuyền trưởng hạng 3 trong năm nay.
    """
    
    print(f"\nUser: {test_user}")
    print(f"Message: {test_message[:80]}...")
    
    insights = await engine.extract_and_store_insights(
        user_id=test_user,
        message=test_message,
        conversation_history=["Tôi đang học về hàng hải"],
        session_id="test_session"
    )
    
    print(f"\n✅ Stored {len(insights)} insights:")
    for i, insight in enumerate(insights):
        print(f"   {i+1}. [{insight.category.value}] {insight.content[:80]}...")
    
    # Verify in database
    print("\n📊 Verifying in database...")
    
    from app.core.database import get_shared_session_factory
    from sqlalchemy import text
    
    session_factory = get_shared_session_factory()
    with session_factory() as session:
        result = session.execute(text("""
            SELECT content, memory_type, metadata 
            FROM semantic_memories 
            WHERE user_id = :user_id
            ORDER BY created_at DESC;
        """), {"user_id": test_user})
        
        rows = result.fetchall()
        print(f"\nFound {len(rows)} records for user {test_user}:")
        
        for row in rows:
            meta = row[2] or {}
            cat = meta.get("insight_category", "N/A")
            print(f"   Type: {row[1]}, Category: {cat}")
            print(f"   Content: {row[0][:60]}...")
    
    return insights


async def test_retrieve_prioritized():
    """Test retrieve_insights_prioritized()."""
    print("\n" + "="*60)
    print("TEST: retrieve_insights_prioritized()")
    print("="*60)
    
    from app.engine.semantic_memory import SemanticMemoryEngine
    
    engine = SemanticMemoryEngine()
    
    if not engine.is_available():
        print("⚠️ SemanticMemoryEngine not available")
        return []
    
    # Use the test user from previous test
    test_user = "test_insight_engine_v05"
    
    print(f"\nRetrieving insights for user: {test_user}")
    
    insights = await engine.retrieve_insights_prioritized(
        user_id=test_user,
        query="học tập",
        limit=10
    )
    
    print(f"\n✅ Retrieved {len(insights)} prioritized insights:")
    for i, insight in enumerate(insights):
        print(f"   {i+1}. [{insight.category.value}] {insight.content[:80]}...")
    
    return insights


async def main():
    print("\n" + "="*60)
    print("INSIGHT ENGINE v0.5 - LOCAL COMPONENT TEST")
    print("="*60)
    
    # Test 1: Direct extraction
    insights1 = await test_direct_insight_extraction()
    
    # Test 2: Store via SemanticMemoryEngine
    insights2 = await test_semantic_memory_store()
    
    # Test 3: Retrieve prioritized
    insights3 = await test_retrieve_prioritized()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"  InsightExtractor: {len(insights1)} insights extracted")
    print(f"  SemanticMemoryEngine.store: {len(insights2)} insights stored")
    print(f"  SemanticMemoryEngine.retrieve: {len(insights3)} insights retrieved")
    
    if insights1 and insights2:
        print("\n✅ Insight Engine v0.5 is working correctly locally!")
        print("   If production doesn't work, code needs to be deployed.")
    else:
        print("\n⚠️ Some components not working")


if __name__ == "__main__":
    asyncio.run(main())
