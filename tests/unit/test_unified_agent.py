"""
Test UnifiedAgent với Manual ReAct pattern.
"""

import sys
import asyncio
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

async def main():
    print("=" * 60)
    print("Testing UnifiedAgent (Manual ReAct)")
    print("=" * 60)

    # Test 1: Import and initialize
    print("\n1. Importing UnifiedAgent...")
    try:
        from app.engine.unified_agent import UnifiedAgent, get_unified_agent
        print("   ✅ Import SUCCESS")
    except Exception as e:
        print(f"   ❌ Import FAILED: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 2: Initialize agent
    print("\n2. Initializing UnifiedAgent...")
    try:
        agent = UnifiedAgent()
        print(f"   ✅ Agent initialized")
        print(f"   Available: {agent.is_available()}")
    except Exception as e:
        print(f"   ❌ Init FAILED: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 3: Process simple greeting
    print("\n3. Testing simple greeting...")
    try:
        result = await agent.process(
            message="Xin chào!",
            user_id="test_user",
            session_id="test_session"
        )
        print(f"   ✅ Response received")
        print(f"   Method: {result.get('method', 'N/A')}")
        print(f"   Tools used: {len(result.get('tools_used', []))}")
        print(f"   Content: {result['content'][:150]}...")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

    # Test 4: Process maritime question (should use tool)
    print("\n4. Testing maritime question (should call tool)...")
    try:
        result = await agent.process(
            message="Quy tắc 15 COLREGs là gì?",
            user_id="test_user",
            session_id="test_session"
        )
        print(f"   ✅ Response received")
        print(f"   Method: {result.get('method', 'N/A')}")
        print(f"   Iterations: {result.get('iterations', 'N/A')}")
        print(f"   Tools used: {[t['name'] for t in result.get('tools_used', [])]}")
        print(f"   Content: {result['content'][:200]}...")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

    # Test 5: Test user info save
    print("\n5. Testing user info save...")
    try:
        result = await agent.process(
            message="Tôi là Minh, sinh viên Đại học Hàng hải",
            user_id="test_user",
            session_id="test_session"
        )
        print(f"   ✅ Response received")
        print(f"   Tools used: {[t['name'] for t in result.get('tools_used', [])]}")
        print(f"   Content: {result['content'][:150]}...")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("UnifiedAgent Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
