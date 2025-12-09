"""Test RAG with image_url - Full pipeline test"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.engine.tools.rag_tool import RAGAgent
from app.engine.unified_agent import get_last_retrieved_sources, clear_retrieved_sources, get_unified_agent
import asyncio

async def test_rag_direct():
    """Test RAG Agent directly"""
    print("=" * 60)
    print("Test 1: RAG Agent Direct Query")
    print("=" * 60)
    
    agent = RAGAgent()
    result = await agent.query("Quốc hội nước Cộng hòa xã hội chủ nghĩa Việt Nam", user_role="student")
    print(f"Citations: {len(result.citations)}")
    
    has_image = False
    for c in result.citations[:3]:
        print(f"  - {c.title[:50]}...")
        if c.image_url:
            print(f"    image_url: {c.image_url[:60]}...")
            has_image = True
        else:
            print(f"    image_url: None")
    
    if has_image:
        print("\n✅ RAG Agent returns image_url correctly!")
    else:
        print("\n⚠️ No image_url found in citations")

async def test_unified_agent():
    """Test Unified Agent (full pipeline)"""
    print("\n" + "=" * 60)
    print("Test 2: Unified Agent Full Pipeline")
    print("=" * 60)
    
    clear_retrieved_sources()
    
    agent = get_unified_agent()
    result = await agent.process(
        message="Quốc hội nước Cộng hòa xã hội chủ nghĩa Việt Nam",
        conversation_history=[],
        user_id="test_user",
        session_id="test_session"
    )
    
    sources = get_last_retrieved_sources()
    print(f"Retrieved sources: {len(sources)}")
    
    has_image = False
    for s in sources[:3]:
        print(f"  - {s.get('title', 'N/A')[:50]}...")
        if s.get('image_url'):
            print(f"    image_url: {s['image_url'][:60]}...")
            has_image = True
        else:
            print(f"    image_url: None")
    
    if has_image:
        print("\n✅ Unified Agent returns image_url correctly!")
    else:
        print("\n⚠️ No image_url found in sources")

async def main():
    await test_rag_direct()
    await test_unified_agent()
    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
